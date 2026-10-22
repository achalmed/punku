"""API PÚBLICA de la mesa de partes virtual (2026-10-12; servicios/mesa_virtual.py, docs/arquitectura.md §28).

Las ÚNICAS rutas del sistema que no piden sesión (además de las que ya existían: salud, inicio de
sesión…; tests/test_mesa_virtual.py lo comprueba sobre la aplicación entera). Prefijo propio,
`/api/publico/mesa`:

- `GET  /config`       — si la mesa atiende, su presentación, horario, tipos y límites, y la ficha
                          firmada del formulario.
- `POST /enviar`       — presentar un documento (multipart): crea el trámite y su Entrada de Recibidos
                          y devuelve el cargo y una ficha de acceso de 2 horas.
- `POST /seguimiento`  — código de seguimiento + documento de identidad → estado y ficha de acceso.
- `POST /cargo`        — el cargo en PDF (con la ficha de acceso).
- `POST /respuesta`    — un archivo de la respuesta de la entidad (trámite atendido).
- `POST /subsanar`     — los archivos que subsanan una observación (multipart).

Defensas: límite de envíos y consultas por IP (la real, tras el proxy) y por ventana; campo trampa y
ficha firmada con espera mínima (sin captchas de terceros); tamaño máximo por archivo y por envío
comprobado ANTES de leer el cuerpo y mientras se lee; tipo por la firma de bytes y contenido legible;
nombres saneados y rutas generadas aquí; código de seguimiento aleatorio; la respuesta a un código o
documento que no coincide es la misma exista o no el código; todo se registra en `mesa_auditoria`; y
nada de esto se guarda en cachés (`Cache-Control: no-store`; el service worker no toca /api/publico).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tiqsi.web import enviar_archivo

from punku.modelos import Entrada
from punku.modelos import MesaArchivo, MesaTramite
from punku import cargo_pdf
from punku import entradas as svc_entradas
from punku import mesa_virtual as mv
from punku import eventos as punku_eventos
from punku import puertos
from punku.config import config
from punku.db import SesionPunku, obtener_sesion_punku

log = logging.getLogger("qillqa.mesa_virtual")

SIN_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def _cabeceras(respuesta: Response) -> None:
    for k, v in SIN_CACHE.items():
        respuesta.headers[k] = v


router = APIRouter(prefix="/api/publico/mesa", tags=["mesa de partes virtual (pública)"], dependencies=[Depends(_cabeceras)])

NO_COINCIDE = "No encontramos un trámite con ese código y ese documento. Revise los dos datos."
DEMASIADOS = "Demasiados intentos desde esta conexión. Espere unos minutos y vuelva a intentarlo."
# Apagada (registro de módulos, 2026-10-18), la mesa responde con el mensaje que edita quien
# administra (`cfg["mensaje"]`): el mismo en la página y en la API. Quien ya presentó sigue
# consultando, descargando su cargo y subsanando: eso no es recibir un trámite nuevo.


def _ip(peticion: Request) -> str:
    return mv.ip_real(peticion.client.host if peticion.client else "", peticion.headers.get("x-forwarded-for", ""))


def _navegador(peticion: Request) -> str:
    return (peticion.headers.get("user-agent") or "")[:300]


def _demasiados(segundos: int = 600) -> HTTPException:
    return HTTPException(429, DEMASIADOS, headers={"Retry-After": str(segundos), **SIN_CACHE})


async def _auditar_aparte(ip: str, accion: str, detalle: str, navegador: str = "", tramite_id: int | None = None) -> None:
    """Auditoría en su propia transacción: queda aunque la petición termine en error."""
    try:
        async with SesionPunku() as s:
            mv.auditar(s, ip, accion, detalle, tramite_id, navegador)
            await s.commit()
    except Exception:  # noqa: BLE001
        log.exception("No se pudo registrar la auditoría de la mesa virtual")


# --- configuración pública ----------------------------------------------------------------------


@router.get("/config")
async def configuracion(sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    cfg = await mv.cargar_config(sesion)
    receptor = mv.nombre_receptor(cfg)
    if not cfg["activa"]:
        return {"activa": False, "receptor": receptor, "mensaje": cfg["mensaje"]}
    ahora = mv.ahora_local()
    presentado, fuera = mv.momento_presentacion(ahora, cfg)
    return {
        "activa": True,
        "receptor": receptor,
        "presentacion": cfg["presentacion"],
        "horario": cfg["horario"],
        "tipos": cfg["tipos"],
        "max_archivo_mb": cfg["max_archivo_mb"],
        "max_total_mb": cfg["max_total_mb"],
        "max_anexos": cfg["max_anexos"],
        "plazo_subsanacion": cfg["plazo_subsanacion"],
        "ahora": ahora.strftime("%Y-%m-%dT%H:%M"),
        # Si enviara ahora: qué día se tendría por presentado (para avisarlo antes de enviar).
        "presentado_si_envia": presentado.isoformat(),
        "fuera_de_horario": fuera,
        "ficha": mv.ficha_formulario(),
    }


# --- presentar un documento --------------------------------------------------------------------


def _txt(form, campo: str, maximo: int, obligatorio: str = "") -> str:
    v = form.get(campo)
    v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v if isinstance(v, str) else "").strip()
    if obligatorio and not v:
        raise mv.Rechazo(obligatorio, campo=campo)
    if len(v) > maximo:
        raise mv.Rechazo(f"El campo es demasiado largo (máximo {maximo} caracteres).", campo=campo)
    return v


def _remitente(form) -> dict:
    """Los datos del remitente, validados. Persona natural: DNI o carné de extranjería; persona
    jurídica o entidad: RUC, razón social y quien la representa."""
    tipo = _txt(form, "tipo_persona", 10) or "natural"
    if tipo not in ("natural", "juridica"):
        raise mv.Rechazo("Elija si envía como persona o como entidad.", campo="tipo_persona")
    r: dict = {"tipo_persona": tipo}
    if tipo == "natural":
        r["doc_tipo"] = _txt(form, "doc_tipo", 5) or "DNI"
        if r["doc_tipo"] not in mv.DOCS_PERSONA:
            raise mv.Rechazo("Elija DNI o carné de extranjería.", campo="doc_tipo")
        r["doc_numero"] = mv.limpiar_doc(_txt(form, "doc_numero", 20, "Escriba su número de documento."))
        if (e := mv.error_doc(r["doc_tipo"], r["doc_numero"])):
            raise mv.Rechazo(e, campo="doc_numero")
        nombres = _txt(form, "nombres", 100, "Escriba sus nombres.")
        apellidos = _txt(form, "apellidos", 100, "Escriba sus apellidos.")
        r["nombre"] = f"{nombres} {apellidos}"
        r.update(representante="", representante_doc_tipo="", representante_doc="", cargo="")
    else:
        r["doc_tipo"] = "RUC"
        r["doc_numero"] = mv.limpiar_doc(_txt(form, "doc_numero", 20, "Escriba el RUC."))
        if (e := mv.error_doc("RUC", r["doc_numero"])):
            raise mv.Rechazo(e, campo="doc_numero")
        r["nombre"] = _txt(form, "razon_social", 300, "Escriba la razón social o el nombre de la entidad.")
        r["representante"] = _txt(form, "representante", 200, "Escriba el nombre de quien firma o representa.")
        r["representante_doc_tipo"] = _txt(form, "representante_doc_tipo", 5) or "DNI"
        if r["representante_doc_tipo"] not in mv.DOCS_PERSONA:
            raise mv.Rechazo("Elija DNI o carné de extranjería.", campo="representante_doc_tipo")
        r["representante_doc"] = mv.limpiar_doc(_txt(form, "representante_doc", 20, "Escriba el documento de quien representa."))
        if (e := mv.error_doc(r["representante_doc_tipo"], r["representante_doc"])):
            raise mv.Rechazo(e, campo="representante_doc")
        r["cargo"] = _txt(form, "cargo", 200)
    r["correo"] = _txt(form, "correo", 200).lower()
    if r["correo"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", r["correo"]):
        raise mv.Rechazo("El correo no parece válido.", campo="correo")
    r["telefono"] = re.sub(r"[^\d+]", "", _txt(form, "telefono", 30))
    if r["telefono"] and not re.fullmatch(r"\+?\d{6,15}", r["telefono"]):
        raise mv.Rechazo("El celular o teléfono no parece válido.", campo="telefono")
    if not r["correo"] and not r["telefono"]:
        raise mv.Rechazo("Deje un celular o un correo para poder comunicarnos con usted.", campo="telefono")
    r["direccion"] = _txt(form, "direccion", 300)
    return r


def _documento(form, cfg: dict) -> dict:
    tipo = _txt(form, "tipo_documento", 60, "Elija el tipo de documento.")
    if tipo not in cfg["tipos"]:
        raise mv.Rechazo("Elija un tipo de documento de la lista.", campo="tipo_documento")
    folios_txt = _txt(form, "folios", 6, "Indique cuántos folios (hojas) tiene.")
    if not folios_txt.isdigit() or not 1 <= int(folios_txt) <= 9999:
        raise mv.Rechazo("Los folios son un número entre 1 y 9999.", campo="folios")
    asunto = _txt(form, "asunto", 600, "Escriba el asunto.")
    if len(asunto) < 5:
        raise mv.Rechazo("El asunto es muy breve.", campo="asunto")
    return {
        "tipo_documento": tipo, "numero_documento": _txt(form, "numero_documento", 120), "folios": int(folios_txt),
        "asunto": asunto, "comentario": _txt(form, "comentario", 2000), "referencia": _txt(form, "referencia", 300),
    }


async def _documento_citado(referencia: str) -> dict | None:
    """El documento propio que la referencia cita (OF-0061, «Oficio N° 61…»), si existe («documentos.v1»)."""
    m = re.search(r"\b(OF|OM|MEM|SOL|ACT|CAR|CARTA|INF|OFICIO)[-\s.N°º]*0*(\d{1,5})\b", referencia or "", re.I)
    if not m:
        return None
    return await puertos.documento_por_numero(int(m.group(2)))


@router.post("/enviar")
async def enviar(peticion: Request, sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    ip, nav = _ip(peticion), _navegador(peticion)
    cfg = await mv.cargar_config(sesion)
    if not cfg["activa"]:
        await _auditar_aparte(ip, "cerrada", "envío con la mesa apagada", nav)
        raise HTTPException(503, cfg["mensaje"], headers=SIN_CACHE)
    # 1) Límites por IP ANTES de leer el cuerpo (memoria) y contra lo ya registrado (base).
    if not mv.LIMITES.permitir(f"envio:{ip}", cfg["envios_por_hora"], 3600):
        await _auditar_aparte(ip, "limite", "envíos por hora (memoria)", nav)
        raise _demasiados(3600)
    hora, dia, todos = await mv.envios_recientes(sesion, ip)
    if hora >= cfg["envios_por_hora"] or dia >= cfg["envios_por_dia"] or todos >= mv.ENVIOS_GLOBALES_POR_DIA:
        await _auditar_aparte(ip, "limite", f"envíos registrados: {hora}/h, {dia}/día, {todos} en total", nav)
        raise _demasiados(3600)
    # 2) Tamaño declarado: sin Content-Length no se lee; con más del máximo, tampoco.
    max_total = cfg["max_total_mb"] * 1024 * 1024
    largo = peticion.headers.get("content-length", "")
    if not largo.isdigit():
        raise HTTPException(411, "Falta el tamaño del envío.")
    if int(largo) > max_total + 512 * 1024:
        await _auditar_aparte(ip, "envio_rechazado", f"cuerpo de {int(largo)} bytes", nav)
        raise HTTPException(413, f"El envío pasa de {cfg['max_total_mb']} MB en total.")
    if not mv.disco_suficiente(mv.carpeta_recepcion(), max_total):
        await _auditar_aparte(ip, "envio_rechazado", "disco casi lleno", nav)
        raise HTTPException(503, "La mesa de partes no puede recibir archivos en este momento. Intente más tarde.")
    trabajo = Path(tempfile.mkdtemp(prefix="envio-", dir=mv.carpeta_recepcion()))
    try:
        try:
            form = await peticion.form(max_files=cfg["max_anexos"] + 1, max_fields=60)
        except Exception as e:  # noqa: BLE001  (MultiPartException: demasiados archivos o cuerpo roto)
            raise mv.Rechazo(f"No se pudo leer el envío: {'demasiados archivos' if 'files' in str(e) else 'formulario incompleto'}.", 400) from None
        # 3) Robots: campo trampa (invisible para una persona) y ficha firmada con espera mínima.
        trampa = form.get("sitio_web")
        if isinstance(trampa, str) and trampa.strip():
            await _auditar_aparte(ip, "trampa", "campo trampa lleno", nav)
            return {"recibido": True}
        motivo_ficha = mv.error_ficha_formulario(str(form.get("ficha") or ""))
        if motivo_ficha:
            await _auditar_aparte(ip, "trampa" if motivo_ficha == "rapida" else "envio_rechazado", f"ficha {motivo_ficha}", nav)
            raise HTTPException(422, {"mensaje": "La página estuvo abierta demasiado tiempo o se envió demasiado rápido: "
                                                 "recárguela y vuelva a enviar.", "campo": "ficha"})
        if form.get("declaracion") != "si" or form.get("datos_personales") != "si":
            raise mv.Rechazo("Marque la declaración jurada y la autorización de datos personales.", campo="declaracion")
        remitente = _remitente(form)
        documento = _documento(form, cfg)
        # 4) Archivos: un PDF principal y hasta N anexos (PDF, JPG o PNG), por su firma de bytes.
        principal = [f for k, f in form.multi_items() if k == "principal" and hasattr(f, "read")]
        anexos = [f for k, f in form.multi_items() if k == "anexos" and hasattr(f, "read")]
        if len(principal) != 1:
            raise mv.Rechazo("Adjunte el documento principal en PDF.", campo="principal")
        if len(anexos) > cfg["max_anexos"]:
            raise mv.Rechazo(f"Puede adjuntar hasta {cfg['max_anexos']} anexos.", campo="anexos")
        max_archivo = cfg["max_archivo_mb"] * 1024 * 1024
        total = [0]
        recibidos = [await mv.recibir_archivo(principal[0], "principal", trabajo, max_archivo, total, max_total)]
        for a in anexos:
            recibidos.append(await mv.recibir_archivo(a, "anexo", trabajo, max_archivo, total, max_total))
        tramite, entrada = await _registrar(sesion, cfg, remitente, documento, recibidos, ip, nav)
    except mv.Rechazo as r:
        await _auditar_aparte(ip, "envio_rechazado", f"{r.campo}: {r.motivo}", nav)
        raise HTTPException(r.codigo, {"mensaje": r.motivo, "campo": r.campo}) from None
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)
    archivos = await mv.archivos_de(sesion, tramite.id)
    movimientos = await mv.movimientos_de(sesion, tramite.id, solo_publicos=True)
    return {"tramite": mv.vista_publica(tramite, archivos, movimientos, cfg), "acceso": mv.ficha_acceso(tramite.id),
            "enlace": cfg["enlace_publico"]}


async def _registrar(sesion: AsyncSession, cfg: dict, remitente: dict, documento: dict, recibidos: list, ip: str, nav: str):
    """Expediente, código, archivos en su carpeta, el trámite, su Entrada de Recibidos, el primer
    paso de la historia, la auditoría y el evento «recibido nuevo». Un solo commit."""
    ahora = mv.ahora_local()
    presentado, fuera = mv.momento_presentacion(ahora, cfg)
    for intento in range(3):
        try:
            correlativo = await mv.siguiente_correlativo(sesion, ahora.year)
            expediente = mv.texto_expediente(ahora.year, correlativo)
            codigo = await mv.codigo_libre(sesion)
            carpeta = mv.carpeta_tramite(expediente, ahora.date())
            guardados = []
            for i, r in enumerate(recibidos, 1):
                final = await asyncio.to_thread(mv.mover, r.ruta, carpeta, mv.nombre_en_disco(i, r.clase, r.tipo))
                r.ruta = final
                guardados.append((r, mv.relativa(final)))
            principal, rel_principal = guardados[0]
            texto = await asyncio.to_thread(svc_entradas.texto_pdf, principal.ruta)
            tramite = MesaTramite(
                anio=ahora.year, correlativo=correlativo, expediente=expediente, codigo=codigo, ip=ip,
                presentado_el=presentado, fuera_de_horario=fuera, estado="recibido",
                declaracion={"veracidad": True, "datos_personales": True, "en": ahora.isoformat(timespec="seconds"),
                             "texto": "Declaro bajo juramento que la información y los documentos son veraces (TUO Ley 27444, "
                                      "art. 51) y autorizo el tratamiento de mis datos personales para atender este trámite y para mantener "
                                      "contacto con el despacho (Ley 29733, de Protección de Datos Personales).",
                             "navegador": nav[:200]},
                **remitente, **documento,
            )
            sesion.add(tramite)
            await sesion.flush()
            # La Entrada de Recibidos: el equipo la procesa como cualquier otro recibido.
            inst_id = None
            if remitente["tipo_persona"] == "juridica":
                inst_id = await puertos.institucion_por_ruc(remitente["doc_numero"])   # «directorio.v1» (Punku P1a)
            clase = mv.clase_de_tipo(documento["tipo_documento"])
            atencion = svc_entradas.atencion_sugerida(" ".join((documento["asunto"], documento["comentario"], texto[:6000])), clase)
            fecha = presentado.isoformat()
            sha = principal.sha256
            if (await sesion.execute(select(Entrada.id).where(Entrada.sha256 == sha))).first() is not None:
                sha = hashlib.sha256(f"{principal.sha256}:{expediente}".encode()).hexdigest()  # mismo PDF ya registrado
            contacto = " · ".join(x for x in (remitente["correo"], remitente["telefono"]) if x)
            numero_doc = documento["numero_documento"]
            e = Entrada(
                despacho_id=1, periodo=config.periodo, archivo=rel_principal, nombre_original=principal.nombre[:300],
                sha256=sha, bytes=principal.bytes, paginas=principal.paginas, texto=texto[:200_000],
                documento=(f"{documento['tipo_documento']} {numero_doc}" if numero_doc else documento["tipo_documento"])[:300],
                clase=clase, via="mesa_virtual", remitente=remitente["nombre"][:300],
                remitente_cargo=(f"{remitente['representante']}" + (f", {remitente['cargo']}" if remitente["cargo"] else ""))[:300],
                remitente_institucion_id=inst_id, fecha_recepcion=fecha, asunto=documento["asunto"],
                referencia=documento["referencia"], resumen=(documento["comentario"] or svc_entradas.resumen_breve(texto, documento["asunto"]))[:2000],
                atencion=atencion, plazo=svc_entradas.plazo_sugerido(atencion, fecha), estado="nueva",
                nota=f"Mesa de partes virtual: expediente {expediente}" + (f" · contacto: {contacto}" if contacto else ""),
                creado_por=None,
            )
            sesion.add(e)
            await sesion.flush()
            tramite.entrada_id = e.id
            for r, rel in guardados:
                sesion.add(MesaArchivo(tramite_id=tramite.id, clase=r.clase, archivo=rel, nombre=r.nombre, tipo=r.tipo,
                                       bytes=r.bytes, paginas=r.paginas, sha256=r.sha256))
            mv.movimiento(sesion, tramite, "recibido", f"Llegó fuera del horario de atención: se tiene por presentado el {presentado.strftime('%d/%m/%Y')}." if fuera else "")
            doc = await _documento_citado(documento["referencia"])
            mv.auditar(sesion, ip, "envio", f"{expediente} · {len(recibidos)} archivo(s) · {sum(r.bytes for r in recibidos)} bytes", tramite.id, nav)
            punku_eventos.emitir(sesion, "entrada.registrada", f"entrada:{e.id}", mv.datos_evento(tramite, e))
            await sesion.commit()
            if doc is not None:   # el grafo es de Qillqa: «relaciones.v1», después del commit
                await puertos.registrar_relaciones([{"origen": f"entrada:{e.id}", "destino": f"doc:{doc['id']}", "tipo": "responde",
                                                     "contexto": "referencia", "fuente": "auto", "texto": documento["referencia"][:300]}])
            return tramite, e
        except IntegrityError:
            await sesion.rollback()
            if intento == 2:
                raise
            # Los archivos ya movidos vuelven a esperar en su carpeta: se reintenta con otro número.
    raise RuntimeError("No se pudo registrar el trámite")


# --- seguimiento ----------------------------------------------------------------------------------


class Consulta(BaseModel):
    codigo: str = Field(max_length=40)
    documento: str = Field(max_length=30)


@router.post("/seguimiento")
async def seguimiento(datos: Consulta, peticion: Request, sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    ip, nav = _ip(peticion), _navegador(peticion)
    if not mv.LIMITES.permitir(f"consulta:{ip}", *mv.CONSULTAS_POR_VENTANA) or \
            mv.LIMITES.restantes(f"fallida:{ip}", *mv.FALLIDAS_POR_VENTANA) == 0:
        await _auditar_aparte(ip, "limite", "consultas", nav)
        raise _demasiados(900)
    cfg = await mv.cargar_config(sesion)
    codigo = mv.normalizar_codigo(datos.codigo)
    t = None
    if codigo:
        t = (await sesion.execute(select(MesaTramite).where(MesaTramite.codigo == codigo))).scalars().first()
    # Se compara siempre (exista o no el código): misma respuesta y tiempo parecido.
    ok = mv.coincide_dato(datos.documento, *(([t.doc_numero, t.representante_doc]) if t else ["0" * 8]))
    if t is None or not ok:
        mv.LIMITES.permitir(f"fallida:{ip}", *mv.FALLIDAS_POR_VENTANA)
        await _auditar_aparte(ip, "seguimiento_fallido", f"código «{(datos.codigo or '')[:20]}»", nav)
        raise HTTPException(404, NO_COINCIDE, headers=SIN_CACHE)
    mv.auditar(sesion, ip, "seguimiento", t.expediente, t.id, nav)
    await sesion.commit()
    archivos = await mv.archivos_de(sesion, t.id)
    movimientos = await mv.movimientos_de(sesion, t.id, solo_publicos=True)
    return {"tramite": mv.vista_publica(t, archivos, movimientos, cfg), "acceso": mv.ficha_acceso(t.id), "enlace": cfg["enlace_publico"]}


# --- con la ficha de acceso: cargo, respuesta y subsanación -----------------------------------------


async def _con_acceso(sesion: AsyncSession, ficha: str, ip: str, nav: str) -> MesaTramite:
    if not mv.LIMITES.permitir(f"descarga:{ip}", *mv.DESCARGAS_POR_VENTANA):
        raise _demasiados(600)
    tid = mv.tramite_de_acceso(ficha)
    t = await sesion.get(MesaTramite, tid) if tid else None
    if t is None:
        await _auditar_aparte(ip, "seguimiento_fallido", "ficha de acceso vencida o falsa", nav)
        raise HTTPException(401, "Su consulta venció: vuelva a buscar su trámite con el código y su documento.", headers=SIN_CACHE)
    return t


def _archivo_sin_cache(ruta: Path, nombre: str, media: str, peticion: Request) -> Response:
    r = enviar_archivo(ruta, nombre, media_type=media, peticion=None)
    for k, v in SIN_CACHE.items():
        r.headers[k] = v
    return r


class Acceso(BaseModel):
    acceso: str = Field(max_length=2000)
    archivo_id: int | None = None


@router.post("/cargo")
async def cargo(datos: Acceso, peticion: Request, sesion: AsyncSession = Depends(obtener_sesion_punku)) -> Response:
    ip, nav = _ip(peticion), _navegador(peticion)
    t = await _con_acceso(sesion, datos.acceso, ip, nav)
    cfg = await mv.cargar_config(sesion)
    v = mv.vista_publica(t, await mv.archivos_de(sesion, t.id), [], cfg)
    pdf = await asyncio.to_thread(cargo_pdf.cargo, v, cfg["enlace_publico"])
    mv.auditar(sesion, ip, "descarga", f"cargo {t.expediente}", t.id, nav)
    await sesion.commit()
    return Response(pdf, media_type="application/pdf", headers={
        **SIN_CACHE, "Content-Disposition": f'attachment; filename="Cargo-{t.expediente}.pdf"'})


@router.post("/respuesta")
async def respuesta(datos: Acceso, peticion: Request, sesion: AsyncSession = Depends(obtener_sesion_punku)) -> Response:
    ip, nav = _ip(peticion), _navegador(peticion)
    t = await _con_acceso(sesion, datos.acceso, ip, nav)
    a = await sesion.get(MesaArchivo, datos.archivo_id) if datos.archivo_id else None
    if a is None or a.tramite_id != t.id or a.clase != "respuesta" or t.estado != "atendido":
        raise HTTPException(404, "Ese archivo no está disponible.", headers=SIN_CACHE)
    ruta = mv.absoluta(a.archivo)
    if ruta is None:
        raise HTTPException(404, "El archivo de la respuesta no está en el archivo documental: avise al despacho.", headers=SIN_CACHE)
    mv.auditar(sesion, ip, "descarga", f"respuesta {t.expediente} · {a.nombre}", t.id, nav)
    await sesion.commit()
    return _archivo_sin_cache(ruta, f"Respuesta-{t.expediente}.{a.tipo}", mv.TIPOS_ARCHIVO.get(a.tipo, "application/octet-stream"), peticion)


@router.post("/subsanar")
async def subsanar(peticion: Request, sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    ip, nav = _ip(peticion), _navegador(peticion)
    cfg = await mv.cargar_config(sesion)
    if not mv.LIMITES.permitir(f"subsanar:{ip}", *mv.SUBSANACIONES_POR_HORA):
        await _auditar_aparte(ip, "limite", "subsanaciones", nav)
        raise _demasiados(3600)
    max_total = cfg["max_total_mb"] * 1024 * 1024
    largo = peticion.headers.get("content-length", "")
    if not largo.isdigit():
        raise HTTPException(411, "Falta el tamaño del envío.")
    if int(largo) > max_total + 256 * 1024:
        raise HTTPException(413, f"El envío pasa de {cfg['max_total_mb']} MB en total.")
    trabajo = Path(tempfile.mkdtemp(prefix="subsana-", dir=mv.carpeta_recepcion()))
    try:
        try:
            form = await peticion.form(max_files=max(cfg["max_anexos"], 1) + 1, max_fields=10)
        except Exception:  # noqa: BLE001
            raise mv.Rechazo("No se pudo leer el envío: demasiados archivos o formulario incompleto.", 400) from None
        t = await _con_acceso(sesion, str(form.get("acceso") or ""), ip, nav)
        if t.estado != "observado":
            raise mv.Rechazo("Este trámite no tiene una observación pendiente.", 409)
        nota = _txt(form, "nota", 2000)
        subidos = [f for k, f in form.multi_items() if k == "archivos" and hasattr(f, "read")]
        if not subidos:
            raise mv.Rechazo("Adjunte al menos un archivo con lo que subsana.", campo="archivos")
        if len(subidos) > max(cfg["max_anexos"], 1) + 1:
            raise mv.Rechazo("Demasiados archivos.", campo="archivos")
        total = [0]
        recibidos = [await mv.recibir_archivo(f, "subsanacion", trabajo, cfg["max_archivo_mb"] * 1024 * 1024, total, max_total) for f in subidos]
        await _registrar_subsanacion(sesion, cfg, t, recibidos, nota, ip, nav)
    except mv.Rechazo as r:
        await _auditar_aparte(ip, "envio_rechazado", f"subsanación · {r.campo}: {r.motivo}", nav)
        raise HTTPException(r.codigo, {"mensaje": r.motivo, "campo": r.campo}) from None
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)
    await sesion.refresh(t)
    return {"tramite": mv.vista_publica(t, await mv.archivos_de(sesion, t.id), await mv.movimientos_de(sesion, t.id, True), cfg),
            "acceso": mv.ficha_acceso(t.id)}


async def _registrar_subsanacion(sesion: AsyncSession, cfg: dict, t: MesaTramite, recibidos: list, nota: str, ip: str, nav: str) -> None:
    """Los archivos entran como anexos nuevos (clase `subsanacion`), el trámite vuelve a «En
    revisión» y el equipo recibe el aviso. Si llegó tras el plazo, queda marcado: decide el equipo
    (TUO 27444, art. 125.4)."""
    ahora = mv.ahora_local()
    presentado, _ = mv.momento_presentacion(ahora, cfg)
    tarde = bool(t.plazo_subsanacion and presentado > t.plazo_subsanacion)
    carpeta = mv.carpeta_tramite(t.expediente, t.recibido_en.astimezone(mv.zona()).date() if t.recibido_en else ahora.date())
    previos = len(await mv.archivos_de(sesion, t.id))
    for i, r in enumerate(recibidos, previos + 1):
        final = await asyncio.to_thread(mv.mover, r.ruta, carpeta, mv.nombre_en_disco(i, "subsanacion", r.tipo))
        sesion.add(MesaArchivo(tramite_id=t.id, clase="subsanacion", archivo=mv.relativa(final), nombre=r.nombre, tipo=r.tipo,
                               bytes=r.bytes, paginas=r.paginas, sha256=r.sha256, fuera_de_plazo=tarde))
    e = await sesion.get(Entrada, t.entrada_id) if t.entrada_id else None
    mv.poner_estado(t, e, "en_revision")
    texto = f"{len(recibidos)} archivo(s)." + (f" Nota: {nota}" if nota else "") + (" Llegó después del plazo." if tarde else "")
    mv.movimiento(sesion, t, "subsanado", texto)
    mv.auditar(sesion, ip, "subsanacion", f"{t.expediente} · {len(recibidos)} archivo(s)" + (" · fuera de plazo" if tarde else ""), t.id, nav)
    # Aviso al equipo: a quien tiene el recibido o, si nadie, a quien administra.
    aviso = f"Subsanación recibida por la mesa virtual: {t.expediente} «{t.asunto[:100]}»" + (" (fuera de plazo)" if tarde else "") + "."
    destinos = {e.responsable_id} if e is not None and e.responsable_id else set(await puertos.administradores())
    for uid in destinos:
        punku_eventos.avisar(sesion, uid, aviso, tipo="entrada", destino=f"entrada:{t.entrada_id}" if t.entrada_id else "")
    if e is not None:
        n = len([m for m in await mv.movimientos_de(sesion, t.id) if m.accion == "subsanado"])  # incluye la de ahora
        punku_eventos.emitir(sesion, "entrada.subsanada", f"entrada:{e.id}",
                                            {**mv.datos_evento(t, e), "fuera_de_plazo": "sí" if tarde else ""},
                                            clave=f"entrada:{e.id}:subsanada:{n}")
    await sesion.commit()
