"""API de la BANDEJA DE ENTRADA (documentos recibidos, 2026-10-06; servicios/entradas.py).

Flujo de la web: arrastrar uno o varios PDF (o Word e imágenes, que se pasan a PDF) →
`POST /analizar` (guarda cada PDF a la espera y devuelve su ficha automática y si es un
duplicado) → la persona revisa y corrige las fichas: junta las partes de un mismo envío
(`POST /unir`) y pega el resumen del grupo (`POST /leer-resumen`, que también propone el
evento de la Agenda) → `POST /api/entradas` (las registra). Para subir sin revisar (p. ej. lo que lleve el bot
de Telegram) existe `POST /subir`, que hace las dos cosas de una vez.

Después: lista con filtros, ficha, actualizar (asignar, plazo, atención, campaña),
archivar y reabrir, el PDF (por `enviar_archivo`), «Responder» (crea el borrador del
oficio de respuesta, vinculado) y vincular a mano un documento propio.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from tiqsi.modulo import opcional
from tiqsi.puertos import Usuario, usuario_actual
from tiqsi.pdf import contar_paginas
from tiqsi.web import enviar_archivo

from punku.modelos import Entrada
from punku import entradas as svc
from punku import eventos as punku_eventos
from punku import puertos
from punku.config import config
from punku.db import obtener_sesion_punku

import logging

log = logging.getLogger("qillqa.entradas")
router = APIRouter(prefix="/api/entradas", tags=["entradas"])


def _puede_escribir(u: Usuario) -> None:
    if u.rol == "invitado":
        raise HTTPException(403, "La cuenta de invitado solo puede consultar.")


async def _entrada(sesion: AsyncSession, eid: int) -> Entrada:
    e = await sesion.get(Entrada, eid)
    if e is None:
        raise HTTPException(404, "El documento recibido no existe.")
    return e


def _texto_valido(valor: str, permitidos: tuple[str, ...], campo: str) -> str:
    if valor not in permitidos:
        raise HTTPException(422, f"{campo} no válido: «{valor}». Opciones: {', '.join(permitidos)}.")
    return valor


def _fecha(valor: str, campo: str) -> str:
    valor = (valor or "").strip()
    if valor and not (len(valor) == 10 and valor[4] == "-" and valor[7] == "-" and valor.replace("-", "").isdigit()):
        raise HTTPException(422, f"{campo}: use el formato AAAA-MM-DD.")
    return valor


# --- serialización ----------------------------------------------------------------------


async def _nombres(sesion: AsyncSession, filas: list[Entrada]) -> tuple[dict, dict, dict, dict]:
    uids = {x for e in filas for x in (e.responsable_id, e.creado_por) if x}
    pids = {e.remitente_persona_id for e in filas if e.remitente_persona_id}
    iids = {e.remitente_institucion_id for e in filas if e.remitente_institucion_id}
    dids = {x for e in filas for x in (e.respuesta_documento_id, e.responde_a_documento_id) if x}
    # Las cuentas y el directorio, por el contrato (Punku P1a): «identidad.v1» y «directorio.v1».
    usuarios = await puertos.nombres_de(uids)
    fichas = await puertos.fichas(pids, iids)
    personas, insts = fichas["personas"], fichas["instituciones"]
    docs = await puertos.breves(dids)   # el documento propio, por «documentos.v1» (Punku P1b)
    return usuarios, personas, insts, docs


def _resumen(e: Entrada, nombres: tuple[dict, dict, dict, dict], hoy: str) -> dict:
    usuarios, personas, insts, docs = nombres
    p = personas.get(e.remitente_persona_id) if e.remitente_persona_id else None
    i = insts.get(e.remitente_institucion_id) if e.remitente_institucion_id else None
    # Vinculado al directorio, el remitente se ve con su nombre y cargo VIGENTES (2026-10-12);
    # lo registrado queda en `remitente_registrado` (punku_puertos.remitente_vigente).
    remitente, remitente_cargo = puertos.remitente_vigente(
        e.remitente, e.remitente_cargo, (p["nombre"], p["cargo"] or "") if p else None, i["nombre"] if i and not p else None)
    return {
        "id": e.id,
        "std_numero": e.std_numero,
        "documento": e.documento,
        "clase": e.clase,
        "via": e.via,
        "remitente": remitente,
        "remitente_cargo": remitente_cargo,
        "remitente_registrado": e.remitente,
        "remitente_persona_id": e.remitente_persona_id,
        "remitente_persona": p["nombre"] if p else "",
        "remitente_institucion_id": e.remitente_institucion_id,
        "remitente_institucion": (i["siglas"] or i["nombre"]) if i else "",
        "remitente_institucion_nombre": i["nombre"] if i else "",
        "fecha_documento": e.fecha_documento,
        "fecha_recepcion": e.fecha_recepcion,
        "asunto": e.asunto,
        "referencia": e.referencia,
        "resumen": e.resumen,
        "atencion": e.atencion,
        "categoria": e.categoria or "",
        "requiere_revision": bool(e.requiere_revision),
        "responde_a_documento_id": e.responde_a_documento_id,
        "responde_a": docs.get(e.responde_a_documento_id) if e.responde_a_documento_id else None,
        "responsable_id": e.responsable_id,
        "responsable": usuarios.get(e.responsable_id, "") if e.responsable_id else "",
        "plazo": e.plazo,
        "estado": e.estado,
        "campana": e.campana,
        "nota": e.nota,
        "origen_campos": e.origen_campos or {},
        "nombre_original": e.nombre_original,
        "paginas": e.paginas,
        "bytes": e.bytes,
        "respuesta": docs.get(e.respuesta_documento_id) if e.respuesta_documento_id else None,
        "vencida": svc.vencida(e.plazo, e.estado, hoy),
        "por_vencer": svc.por_vencer(e.plazo, e.estado, hoy),
        "creado_por": usuarios.get(e.creado_por, "") if e.creado_por else "",
        "creado_en": e.creado_en.isoformat() if e.creado_en else None,
        "respondida_en": e.respondida_en.isoformat() if e.respondida_en else None,
        "archivada_en": e.archivada_en.isoformat() if e.archivada_en else None,
        "cita": svc.texto_cita(e),
    }


# --- conciliación perezosa ---------------------------------------------------------------

_ULTIMA_CONCILIACION = [0.0]


async def _al_dia(sesion: AsyncSession) -> None:
    """Conciliación con los oficios propios y avisos de plazo vencido, como mucho una vez
    por minuto (la lista y la tarjeta del Inicio la disparan)."""
    if time.monotonic() - _ULTIMA_CONCILIACION[0] < 60:
        return
    _ULTIMA_CONCILIACION[0] = time.monotonic()
    cambios, relaciones = await svc.conciliar_todo(sesion)
    vencidas = await svc.avisar_vencidas(sesion)
    if cambios or vencidas:
        await sesion.commit()
    if cambios:
        await puertos.registrar_relaciones(relaciones)   # el grafo es de Qillqa: «relaciones.v1», después del commit


# --- lista, resumen y campañas ------------------------------------------------------------


@router.get("")
async def listar(
    q: str = "",
    estado: str = "",
    atencion: str = "",
    responsable: str = "",
    vencidas: bool = False,
    campana: str = "",
    clase: str = "",
    via: str = "",
    limite: int = 200,
    desde_n: int = 0,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Documentos recibidos con filtros. `estado`: uno de los cuatro, «abiertas» (nueva o
    en atención) o vacío (todas menos archivadas). `responsable`: un id, «yo» o «sin»."""
    await _al_dia(sesion)
    hoy = svc.hoy_lima()
    cond = []
    if estado == "abiertas":
        cond.append(Entrada.estado.in_(svc.ESTADOS_ABIERTOS))
    elif estado == "todas":
        pass
    elif estado:
        cond.append(Entrada.estado == _texto_valido(estado, svc.ESTADOS, "Estado"))
    else:
        cond.append(Entrada.estado != "archivada")
    if atencion:
        cond.append(Entrada.atencion == _texto_valido(atencion, svc.ATENCIONES, "Tipo de atención"))
    if clase:
        cond.append(Entrada.clase == _texto_valido(clase, svc.CLASES, "Clase"))
    if via:
        cond.append(Entrada.via == _texto_valido(via, svc.VIAS, "Vía"))
    if responsable == "yo":
        cond.append(Entrada.responsable_id == usuario.id)
    elif responsable == "sin":
        cond.append(Entrada.responsable_id.is_(None))
    elif responsable.isdigit():
        cond.append(Entrada.responsable_id == int(responsable))
    if vencidas:
        cond += [Entrada.estado.in_(svc.ESTADOS_ABIERTOS), Entrada.plazo != "", Entrada.plazo < hoy]
    if campana:
        cond.append(Entrada.campana == campana)
    for palabra in q.split()[:6]:
        patron = f"%{palabra}%"
        cond.append(or_(
            Entrada.asunto.ilike(patron), Entrada.remitente.ilike(patron), Entrada.documento.ilike(patron),
            Entrada.std_numero.ilike(patron), Entrada.campana.ilike(patron), Entrada.resumen.ilike(patron),
            Entrada.texto.ilike(patron),
        ))
    total = (await sesion.execute(select(func.count()).select_from(Entrada).where(*cond))).scalar_one()
    filas = (await sesion.execute(
        select(Entrada).where(*cond)
        .order_by(
            # Primero lo abierto con plazo más cercano; después lo más reciente.
            Entrada.estado.in_(svc.ESTADOS_ABIERTOS).desc(),
            (Entrada.plazo == "").asc(), Entrada.plazo.asc(),
            Entrada.fecha_recepcion.desc(), Entrada.id.desc(),
        )
        .offset(max(desde_n, 0)).limit(min(max(limite, 1), 500))
    )).scalars().all()
    nombres = await _nombres(sesion, list(filas))
    mesa = await _mesa(sesion, [e.id for e in filas if e.via == "mesa_virtual"])
    return {"total": total, "items": [{**_resumen(e, nombres, hoy), "mesa": mesa.get(e.id)} for e in filas]}


async def _mesa(sesion: AsyncSession, ids: list[int]) -> dict[int, dict]:
    """Expediente y estado PÚBLICO de los recibidos que llegaron por la mesa de partes virtual
    (2026-10-12, servicios/mesa_virtual.py): la lista los distingue y avisa lo observado."""
    if not ids:
        return {}
    from punku.modelos import MesaTramite
    from punku import mesa_virtual as mv

    hoy = mv.ahora_local().date()
    filas = (await sesion.execute(select(MesaTramite).where(MesaTramite.entrada_id.in_(ids)))).scalars()
    return {t.entrada_id: {"expediente": t.expediente, "estado": t.estado, "estado_texto": mv.ETIQUETA.get(t.estado, t.estado),
                           "plazo_subsanacion": t.plazo_subsanacion.isoformat() if t.plazo_subsanacion else "",
                           "vencido": bool(t.estado == "observado" and t.plazo_subsanacion and hoy > t.plazo_subsanacion)}
            for t in filas}


@router.get("/resumen")
async def resumen(
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Para la tarjeta del Inicio: nuevas, en atención, por vencer, vencidas, las mías y
    las cinco más urgentes."""
    await _al_dia(sesion)
    hoy = svc.hoy_lima()
    abiertas = (await sesion.execute(select(Entrada).where(Entrada.estado.in_(svc.ESTADOS_ABIERTOS)))).scalars().all()
    urgentes = sorted(
        [e for e in abiertas if e.plazo],
        key=lambda e: (e.plazo, e.id),
    )[:5]
    nombres = await _nombres(sesion, urgentes)
    return {
        "nuevas": sum(1 for e in abiertas if e.estado == "nueva"),
        "en_atencion": sum(1 for e in abiertas if e.estado == "en_atencion"),
        "por_vencer": sum(1 for e in abiertas if svc.por_vencer(e.plazo, e.estado, hoy)),
        "vencidas": sum(1 for e in abiertas if svc.vencida(e.plazo, e.estado, hoy)),
        "mias": sum(1 for e in abiertas if e.responsable_id == usuario.id),
        "sin_responsable": sum(1 for e in abiertas if not e.responsable_id),
        "urgentes": [_resumen(e, nombres, hoy) for e in urgentes],
    }


@router.get("/campanas")
async def campanas(
    _: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> list[dict]:
    """Las campañas (grupos de cartas iguales) con su conteo."""
    filas = (await sesion.execute(
        select(Entrada.campana, func.count(), func.count().filter(Entrada.estado.in_(svc.ESTADOS_ABIERTOS)))
        .where(Entrada.campana != "").group_by(Entrada.campana).order_by(func.count().desc())
    )).all()
    return [{"campana": c, "total": t, "abiertas": a} for c, t, a in filas]


# --- subir: analizar y confirmar ------------------------------------------------------------


async def _directorio(sesion: AsyncSession) -> tuple[list, list]:
    """(instituciones, personas) activas para cruzar el remitente, por «directorio.v1» (Punku P1a)."""
    return await puertos.para_cruzar()


async def _existentes(sesion: AsyncSession) -> list[tuple[int, str, str]]:
    return [(i, s, n) for i, s, n in (await sesion.execute(select(Entrada.id, Entrada.sha256, Entrada.std_numero))).all()]


async def _recibir(archivo: UploadFile, tmp: Path) -> tuple[Path | None, str]:
    """Guarda lo subido en la carpeta de trabajo del lote: (ruta, motivo de rechazo)."""
    sufijo = Path(archivo.filename or "documento.pdf").suffix.lower()
    if sufijo not in svc.ADMITIDOS:
        return None, "Solo PDF, Word o imágenes (JPG, PNG)."
    ruta = tmp / f"{uuid.uuid4().hex}{sufijo}"
    tam = 0
    with ruta.open("wb") as fh:
        while trozo := await archivo.read(1024 * 1024):
            tam += len(trozo)
            if tam > svc.MAX_PDF:
                return None, f"Pesa más de {svc.MAX_PDF // (1024 * 1024)} MB."
            fh.write(trozo)
    return ruta, ""


def _poner_en_espera(ruta: Path) -> tuple[Path | None, str, str]:
    """(ruta en espera, huella, motivo de rechazo). El nombre en espera es la huella."""
    if ruta.stat().st_size > svc.MAX_PDF:
        return None, "", f"Pesa más de {svc.MAX_PDF // (1024 * 1024)} MB."
    with ruta.open("rb") as fh:
        if not svc.es_pdf(fh.read(8)):
            return None, "", "El archivo no es un PDF válido."
    sha = svc.huella(ruta)
    destino = svc.carpeta_por_confirmar() / f"{sha}.pdf"
    shutil.copyfile(ruta, destino)
    return destino, sha, ""


def _carpeta_de_trabajo() -> Path:
    """Carpeta temporal del lote, junto a los PDF en espera (mismo disco); se borra al terminar."""
    return Path(tempfile.mkdtemp(prefix=".lote-", dir=svc.carpeta_por_confirmar()))


async def _analizar_uno(sesion: AsyncSession, nombre: str, ruta: Path, directorio, existentes, previas, hoy) -> dict:
    import asyncio

    destino, sha, motivo = await asyncio.to_thread(_poner_en_espera, ruta)
    if destino is None:
        return {"nombre": nombre, "error": motivo}
    texto = await asyncio.to_thread(svc.texto_pdf, destino)
    ficha = svc.construir_ficha(
        nombre, texto, hoy=hoy, instituciones=directorio[0], personas=directorio[1],
        siglas_propias=config.siglas, previas=previas,
    )
    dup = svc.duplicado(sha, ficha.std_numero, existentes)
    return {
        "token": sha,
        "nombre": nombre,
        "bytes": destino.stat().st_size,
        "paginas": await asyncio.to_thread(contar_paginas, destino),
        "ficha": ficha.como_dict(),
        "duplicado": dup,
        "copia_de_descarga": svc.nombre_limpio(nombre) != nombre,
    }


async def _contexto(sesion: AsyncSession) -> tuple:
    directorio = await _directorio(sesion)
    existentes = await _existentes(sesion)
    previas = [(a, c) for a, c in (await sesion.execute(
        select(Entrada.asunto, Entrada.campana).where(Entrada.campana != ""))).all()]
    return directorio, existentes, previas, svc.hoy_lima()


async def _analizar_lote(sesion: AsyncSession, archivos: list[UploadFile]) -> list[dict]:
    import asyncio

    directorio, existentes, previas, hoy = await _contexto(sesion)
    salida = []
    vistos: dict[str, str] = {}
    tmp = _carpeta_de_trabajo()
    try:
        for archivo in archivos[:60]:
            nombre = Path(archivo.filename or "documento.pdf").name
            ruta, motivo = await _recibir(archivo, tmp)
            if ruta is not None:
                try:
                    ruta = await asyncio.to_thread(svc.convertir_a_pdf, ruta, tmp)
                except svc.ErrorConversion as e:
                    ruta, motivo = None, str(e)
            if ruta is None:
                salida.append({"nombre": nombre, "error": motivo})
                continue
            # Un Word o una foto se registra con el nombre de su PDF (el n.º STD se lee igual).
            r = await _analizar_uno(sesion, str(Path(nombre).with_suffix(".pdf")), ruta, directorio, existentes, previas, hoy)
            token = r.get("token")
            if token and not r.get("duplicado"):
                std = r["ficha"]["std_numero"]
                for clave in (token, f"std:{std}" if std else ""):
                    if clave and clave in vistos:
                        r["duplicado"] = {"id": None, "motivo": f"repetido en este mismo lote ({vistos[clave]})"}
                        break
                vistos[token] = r["nombre"]
                if std:
                    vistos.setdefault(f"std:{std}", r["nombre"])
            salida.append(r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return salida


@router.post("/analizar")
async def analizar(
    archivos: list[UploadFile] = File(...),
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> list[dict]:
    """Uno o varios archivos (PDF, Word o imágenes: estos se pasan a PDF): cada uno queda
    a la espera (24 h) y vuelve con su ficha automática y, si ya estaba registrado, el
    aviso de duplicado. Nada se registra aún. Dos archivos iguales en el mismo lote
    también se avisan."""
    _puede_escribir(usuario)
    return await _analizar_lote(sesion, archivos)


class Unir(BaseModel):
    tokens: list[str] = Field(min_length=2, max_length=60)
    nombre: str = ""


@router.post("/unir")
async def unir(
    datos: Unir,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Varios PDF ya analizados que son partes de UN envío (la citación, su agenda y los
    proyectos) → un solo PDF, en el orden dado, con su ficha. Las partes siguen a la espera
    (se limpian solas a las 24 h)."""
    import asyncio

    _puede_escribir(usuario)
    rutas = [svc.ruta_por_confirmar(t) for t in datos.tokens]
    if any(r is None for r in rutas):
        raise HTTPException(409, "Alguna parte ya no está a la espera (pasaron 24 h o ya se registró): vuelva a subirla.")
    directorio, existentes, previas, hoy = await _contexto(sesion)
    tmp = _carpeta_de_trabajo()
    try:
        try:
            unido = await asyncio.to_thread(svc.unir_pdfs, rutas, tmp / "unido.pdf")
        except svc.ErrorConversion as e:
            raise HTTPException(422, str(e)) from None
        nombre = Path(datos.nombre or f"{datos.tokens[0][:12]}.pdf").name
        r = await _analizar_uno(sesion, nombre, unido, directorio, existentes, previas, hoy)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if r.get("error"):
        raise HTTPException(422, r["error"])
    return {**r, "partes": len(rutas)}


class Resumen(BaseModel):
    texto: str = Field(min_length=1, max_length=60000)
    actual: dict = {}          # la ficha como está en pantalla (para la tabla de diferencias)
    excluir_id: int | None = None   # la entrada abierta: no es duplicado de sí misma


def _evento_de(ag: dict) -> dict | None:
    """El bloque `agenda` del pegado → el evento que se propone a la Agenda (la forma de
    `POST /api/agenda/eventos`)."""
    if not ag or not ag.get("inicio") or not ag.get("titulo"):
        return None
    inicio = ag["inicio"]
    todo_el_dia = bool(ag.get("todo_el_dia")) or "T" not in inicio
    descripcion = [ag.get("descripcion", "")] if ag.get("descripcion") else []
    for k, rotulo in (("convoca", "Convoca"), ("confirmacion", "Confirmación"), ("accion_previa", "Acción previa"), ("prioridad", "Prioridad")):
        if ag.get(k):
            descripcion.append(f"{rotulo}: {ag[k]}")
    return {
        "titulo": ag["titulo"][:300], "tipo": ag.get("tipo") or "externa",
        "inicio": inicio if "T" in inicio else f"{inicio}T00:00:00",
        "fin": ag.get("fin") if ag.get("fin") and "T" in ag.get("fin", "") else None,
        "todo_el_dia": todo_el_dia, "lugar": (ag.get("lugar") or "")[:300],
        "modalidad": ag.get("modalidad") or "presencial", "enlace": ag.get("enlace") or "",
        "descripcion": "\n".join(descripcion), "participa": ag.get("participa") or [],
        "recordatorio_minutos": ag.get("recordatorio"),
    }


@router.post("/pegar")
async def pegar(
    datos: Resumen,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """El resultado del prompt de recepción pegado (bloque `documento-recibido` o, de
    transición, el mensaje 📌/🗓️ con rótulos) → vista previa: los campos de la ficha, la
    tabla de diferencias con lo que hay en pantalla y las propuestas (remitente del
    directorio, duplicado por n.º STD, documento propio que cita, evento para la Agenda).
    No escribe nada: la ficha se guarda con `POST /api/entradas` o `PUT /{eid}`."""
    _puede_escribir(usuario)
    pegado = puertos.pegado()   # «pegado.v1» (Punku P1a)
    respuesta_lectura = pegado.respuesta
    le = pegado.interpretar(datos.texto, ("documento-recibido",))
    if not le.valido:
        raise HTTPException(422, {"codigo": "pegado_invalido", "errores": le.errores, "avisos": le.avisos,
                                  "formatos": [f for f in pegado.formatos() if f["tipo"] == "documento-recibido"]})
    val = le.valores
    propuestas: dict = {}
    dudosos: set[str] = set()
    # La categoría con poca confianza, o sin reconocer, se CONFIRMA (2026-10-18): la tabla ofrece las
    # opciones (la propuesta y sus alternativas) y la ficha queda «por revisar» hasta que alguien decida.
    alternativas = [a for a in (val.get("categoria_alternativas") or []) if isinstance(a, str)]
    alternativas = [x for x in (pegado.opcion(a, le.esquema.campos["categoria"]) for a in alternativas) if x]
    confianza = val.get("categoria_confianza") or ("baja" if "categoria" in le.dudas else "alta")
    if val.get("categoria") and (confianza == "baja" or alternativas):
        opciones = [val["categoria"]] + [a for a in alternativas if a != val["categoria"]]
        if confianza == "baja":
            opciones = opciones + [c for c in svc.CATEGORIAS if c not in opciones]
            le.dudas["categoria"] = {"valor": val["categoria"], "opciones": opciones}
            dudosos.add("categoria")
        propuestas["categoria_opciones"] = opciones
    propuestas["requiere_revision"] = confianza == "baja" or "categoria" in le.dudas or not val.get("categoria")
    # Remitente e institución contra el directorio (lo mismo que hace la ficha automática).
    if val.get("remitente") or val.get("remitente_institucion"):
        insts, personas = await _directorio(sesion)
        texto_cruce = "\n".join(x for x in (val.get("remitente_institucion", ""), val.get("remitente", ""), val.get("remitente_cargo", "")) if x)
        c = svc.cruzar_remitente(texto_cruce, insts, personas)
        propuestas["remitente_persona_id"] = c.persona_id
        propuestas["remitente_institucion_id"] = c.institucion_id
        if c.institucion_id is None and val.get("remitente_institucion"):
            n = svc.normalizar(val["remitente_institucion"])
            candidatas = [{"id": i, "nombre": nom} for i, nom, sig in insts
                          if svc.similitud(n, nom) >= 0.5 or (sig and svc.normalizar(sig) == n)][:5]
            if candidatas:
                propuestas["instituciones_candidatas"] = candidatas
                dudosos.add("remitente_institucion_id")
    # Duplicado por n.º STD (la misma comprobación de /analizar).
    if val.get("std_numero"):
        std = "".join(ch for ch in val["std_numero"] if ch.isdigit())
        if std:
            q = select(Entrada.id, Entrada.asunto, Entrada.estado).where(Entrada.std_numero == std)
            if datos.excluir_id:
                q = q.where(Entrada.id != datos.excluir_id)
            otra = (await sesion.execute(q)).first()
            if otra:
                propuestas["duplicado"] = {"id": otra[0], "asunto": otra[1], "estado": otra[2], "std_numero": std}
                # Dudoso CON su opción (2026-10-18): sin opciones, la fila bloqueaba «Aplicar».
                le.dudas["std_numero"] = {"valor": std, "opciones": [std]}
                dudosos.add("std_numero")
    # El documento propio que cita en la Referencia → «responde a» (se guarda al registrar, 2026-10-18).
    if val.get("referencia"):
        doc = await _documento_citado(sesion, val["referencia"])
        if doc:
            propuestas["responde_a"] = doc
    # El expediente o trámite que nombra → el oficio propio con ese expediente o registro STD.
    if val.get("expediente"):
        doc = await _documento_por_expediente(sesion, str(val["expediente"]))
        if doc:
            propuestas["expediente_doc"] = doc
            propuestas.setdefault("responde_a", doc)
    # La reunión o actividad a la que da seguimiento → el evento parecido de la Agenda.
    if val.get("reunion"):
        propuestas["reunion_existente"] = await _reunion_parecida(sesion, str(val["reunion"]))
    # La actividad que convoca → evento de la Agenda (nuevo o el que ya está).
    ev = _evento_de(val.get("agenda") or {})
    if ev:
        propuestas["evento"] = ev
        agenda = opcional("agenda.v1")
        propuestas["evento_existente"] = await agenda.parecido(ev["titulo"], ev["inicio"], ev["todo_el_dia"]) if agenda else None
    r = respuesta_lectura(le, datos.actual, dudosos=dudosos)
    for k in ("remitente_persona_id", "remitente_institucion_id"):
        if k in propuestas and propuestas[k] is not None:
            r["campos"][k] = propuestas[k]
    if propuestas.get("responde_a"):
        r["campos"]["responde_a_documento_id"] = propuestas["responde_a"]["id"]
    r["campos"]["requiere_revision"] = bool(propuestas.get("requiere_revision"))
    r["propuestas"] = propuestas
    return r


async def _documento_citado(sesion: AsyncSession, referencia: str) -> dict | None:
    """El documento propio cuyo número aparece en la referencia: «Oficio N.° 0123-2026-…» (serie por su
    nombre, número y año) o «OF-0123». Casa por serie + número + año cuando el año viene (2026-10-18;
    antes solo la serie abreviada y por número suelto, con falsos positivos). Lo busca Qillqa («documentos.v1»)."""
    cita = svc.referencia_citada(referencia)
    return await puertos.documento_citado(cita) if cita else None


async def _documento_por_expediente(sesion: AsyncSession, expediente: str) -> dict | None:
    """El oficio propio que lleva ese expediente (el de la entidad o el registro STD del Congreso)."""
    digitos = "".join(ch for ch in expediente if ch.isdigit())
    n = svc.normalizar(expediente)
    if len(digitos) < 3 and len(n) < 4:
        return None
    return await puertos.documento_por_expediente(expediente)


async def _reunion_parecida(sesion: AsyncSession, reunion: str) -> dict | None:
    """El evento de la Agenda al que el documento da seguimiento (Tareas y Agenda, «agenda.v1».reunion_parecida: por su
    fecha si la trae y, si no, el más parecido por título de los últimos y próximos 90 días)."""
    agenda = opcional("agenda.v1")
    return await agenda.reunion_parecida(reunion) if agenda is not None else None


@router.post("/leer-resumen")
async def leer_resumen(
    datos: Resumen,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Alias de `/pegar` para las pestañas abiertas antes del 2026-10-11: devuelve además
    la forma antigua (`tipo`, `ficha`, `evento`, `evento_existente`, `avisos`)."""
    r = await pegar(datos, usuario, sesion)
    prop = r.get("propuestas", {})
    r.update({
        "tipo": "agenda" if prop.get("evento") else "comunicado",
        "ficha": r["campos"], "evento": prop.get("evento"), "evento_existente": prop.get("evento_existente"),
        "avisos": r["lectura"]["avisos"],
    })
    return r


@router.get("/por-confirmar/{token}/pdf")
async def pdf_por_confirmar(
    token: str,
    peticion: Request,
    _: Usuario = Depends(usuario_actual),
) -> Response:
    """El PDF analizado aún sin registrar (vista previa antes de confirmar la ficha)."""
    ruta = svc.ruta_por_confirmar(token)
    if ruta is None:
        raise HTTPException(404, "Ese PDF ya no está a la espera: vuelva a subirlo.")
    return enviar_archivo(ruta, f"{token[:12]}.pdf", peticion=peticion)


class FichaEntrada(BaseModel):
    std_numero: str = Field("", max_length=20)
    documento: str = Field("", max_length=300)
    clase: str = "otro"
    via: str = "std"
    remitente: str = Field("", max_length=300)
    remitente_cargo: str = Field("", max_length=300)
    remitente_persona_id: int | None = None
    remitente_institucion_id: int | None = None
    fecha_documento: str = ""
    fecha_recepcion: str = ""
    asunto: str = ""
    referencia: str = ""
    resumen: str = ""
    atencion: str = "conocimiento"
    # Clasificación (2026-10-18): qué es para el despacho, si queda «por revisar» y el oficio propio al que responde.
    categoria: str = ""
    requiere_revision: bool = False
    responde_a_documento_id: int | None = None
    responsable_id: int | None = None
    plazo: str = ""
    campana: str = Field("", max_length=160)
    nota: str = ""
    # {campo: 'documento' | 'pegado' | 'persona'}: de dónde salió cada dato (2026-10-11).
    origen_campos: dict = {}


class Confirmar(FichaEntrada):
    token: str
    nombre: str = ""


class Lote(BaseModel):
    items: list[Confirmar] = Field(min_length=1, max_length=60)


async def _validar(sesion: AsyncSession, datos: dict) -> dict:
    """Valida y normaliza los campos de una ficha (crear o actualizar)."""
    if "std_numero" in datos:
        datos["std_numero"] = "".join(c for c in (datos["std_numero"] or "") if c.isdigit())
    if "clase" in datos:
        _texto_valido(datos["clase"], svc.CLASES, "Clase")
    if "via" in datos:
        _texto_valido(datos["via"], svc.VIAS, "Vía")
    if "atencion" in datos:
        _texto_valido(datos["atencion"], svc.ATENCIONES, "Tipo de atención")
    if datos.get("categoria"):
        _texto_valido(datos["categoria"], svc.CATEGORIAS, "Categoría")
    for campo, rotulo in (("fecha_documento", "Fecha del documento"), ("fecha_recepcion", "Fecha de recepción"), ("plazo", "Plazo")):
        if campo in datos:
            datos[campo] = _fecha(datos[campo], rotulo)
    if datos.get("responsable_id"):
        if not await puertos.cuenta_activa(datos["responsable_id"]):
            raise HTTPException(422, "El responsable no es una cuenta activa.")
    pid, iid = datos.get("remitente_persona_id"), datos.get("remitente_institucion_id")
    if pid or iid:
        # Lo vinculado que ya no está en el directorio se desvincula (sin directorio, se conserva).
        if opcional("directorio.v1") is not None:
            existen = await puertos.fichas([pid] if pid else [], [iid] if iid else [])
            if pid and int(pid) not in existen["personas"]:
                datos["remitente_persona_id"] = None
            if iid and int(iid) not in existen["instituciones"]:
                datos["remitente_institucion_id"] = None
    for campo in ("asunto", "referencia", "resumen", "nota", "remitente", "documento", "campana", "remitente_cargo"):
        if campo in datos and isinstance(datos[campo], str):
            datos[campo] = datos[campo].strip()
    if "origen_campos" in datos:
        oc = datos["origen_campos"] or {}
        datos["origen_campos"] = {str(k): v for k, v in oc.items() if v in ("documento", "pegado", "persona")}
    return datos


def _avisar_asignacion(sesion: AsyncSession, e: Entrada, usuario: Usuario) -> None:
    if e.responsable_id:
        punku_eventos.avisar(
            sesion, e.responsable_id,
            f"{usuario.nombre_completo} le encargó un documento recibido ({svc.ETIQUETA_ATENCION.get(e.atencion, e.atencion).lower()}): "
            f"«{(e.asunto or e.documento or 'sin asunto')[:120]}»" + (f", plazo {e.plazo}" if e.plazo else "") + ".",
            tipo="entrada", destino=f"entrada:{e.id}", evitar=usuario.id,
        )


async def _responde_a_existe(e: Entrada) -> None:
    """El oficio propio al que el recibido responde debe existir (si los documentos están, por «documentos.v1»)."""
    if e.responde_a_documento_id and opcional("documentos.v1") is not None \
            and e.responde_a_documento_id not in await puertos.breves([e.responde_a_documento_id]):
        e.responde_a_documento_id = None


async def despues_de_registrar(e: Entrada, usuario_id: int | None) -> None:
    """Después del commit de un recibido nuevo: si responde a un oficio PROPIO (2026-10-18), la relación y la actuación
    «respuesta» en el seguimiento del oficio (Qillqa, por «documentos.v1»); nunca hace fallar el registro."""
    if e.responde_a_documento_id:
        await puertos.respuesta_recibida(e.id, e.responde_a_documento_id, e.fecha_recepcion, svc.texto_cita(e), usuario_id)


async def _registrar(sesion: AsyncSession, item: Confirmar, usuario: Usuario, existentes) -> tuple[Entrada | None, dict | None]:
    import asyncio

    ruta = svc.ruta_por_confirmar(item.token)
    if ruta is None:
        return None, {"motivo": "El PDF ya no está a la espera (pasaron 24 h o ya se registró): vuelva a subirlo."}
    datos = await _validar(sesion, item.model_dump(exclude={"token", "nombre"}))
    dup = svc.duplicado(item.token, datos["std_numero"], existentes)
    if dup:
        return None, dup
    texto = await asyncio.to_thread(svc.texto_pdf, ruta)
    paginas = await asyncio.to_thread(contar_paginas, ruta)
    tam = ruta.stat().st_size
    datos["fecha_recepcion"] = datos["fecha_recepcion"] or svc.hoy_lima()
    nombre = svc.nombre_archivo(datos["std_numero"], datos["fecha_recepcion"],
                            datos["remitente"] or "", datos["asunto"] or datos["documento"] or "")
    archivo = await asyncio.to_thread(svc.archivar_pdf, ruta, nombre, datos["fecha_recepcion"])
    e = Entrada(
        despacho_id=1, periodo=config.periodo, archivo=archivo, nombre_original=(item.nombre or "")[:300],
        sha256=item.token, bytes=tam, paginas=paginas, texto=texto[:200_000], creado_por=usuario.id,
        estado="en_atencion" if datos.get("responsable_id") else "nueva", **datos,
    )
    sesion.add(e)
    await sesion.flush()
    existentes.append((e.id, e.sha256, e.std_numero))
    _avisar_asignacion(sesion, e, usuario)
    # Responde a un oficio PROPIO (2026-10-18): la relación se registra después del commit (`despues_de_registrar`).
    await _responde_a_existe(e)
    # Lo que el recibido anuncia (una citación, una sesión) se propone en la Agenda (2026-10-12);
    # Lo que el recibido anuncia lo propone Tareas y Agenda al recibir «entrada.registrada» por el bus (fase 10.2b).
    punku_eventos.emitir(sesion, "entrada.registrada", f"entrada:{e.id}", _datos_evento(e), usuario_id=usuario.id)
    return e, None


def _datos_evento(e: Entrada) -> dict:
    return {"asunto": e.asunto or e.documento or "", "remitente": e.remitente or "", "clase": e.clase, "atencion": e.atencion,
            "plazo": e.plazo or "", "responsable_id": e.responsable_id, "std_numero": e.std_numero or ""}


@router.post("")
async def confirmar(
    lote: Lote,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Registra las fichas revisadas. Un duplicado (por huella o por número STD) no se
    registra: vuelve en `duplicadas` con la entrada que ya existe."""
    _puede_escribir(usuario)
    existentes = await _existentes(sesion)
    creadas, duplicadas, por_token, nuevas = [], [], {}, []
    for item in lote.items:
        e, dup = await _registrar(sesion, item, usuario, existentes)
        if e is None:
            duplicadas.append({"nombre": item.nombre, **(dup or {})})
        else:
            creadas.append(e.id)
            por_token[item.token] = e.id
            nuevas.append(e)
    await sesion.commit()
    for e in nuevas:
        await despues_de_registrar(e, usuario.id)
    if creadas:
        _ULTIMA_CONCILIACION[0] = 0.0  # que la próxima lista concilie lo nuevo
    # `por_token`: qué entrada salió de cada PDF (la web vincula ahí el evento de la Agenda).
    return {"creadas": creadas, "duplicadas": duplicadas, "por_token": por_token}


@router.post("/subir")
async def subir(
    archivos: list[UploadFile] = File(...),
    via: str = Form("std"),
    campana: str = Form(""),
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Analizar y registrar de una vez, con la ficha automática tal cual (para un puente
    automático; la web usa analizar + confirmar para revisar antes)."""
    _puede_escribir(usuario)
    _texto_valido(via, svc.VIAS, "Vía")
    analizados = await _analizar_lote(sesion, archivos)
    existentes = await _existentes(sesion)
    creadas, duplicadas, rechazadas, nuevas = [], [], [], []
    for a in analizados:
        if a.get("error"):
            rechazadas.append({"nombre": a["nombre"], "motivo": a["error"]})
            continue
        f = {k: v for k, v in a["ficha"].items() if k in FichaEntrada.model_fields}
        item = Confirmar(token=a["token"], nombre=a["nombre"], **{**f, "via": via, "campana": campana or f.get("campana", "")})
        e, dup = await _registrar(sesion, item, usuario, existentes)
        if e is None:
            duplicadas.append({"nombre": a["nombre"], **(dup or {})})
        else:
            creadas.append(e.id)
            nuevas.append(e)
    await sesion.commit()
    for e in nuevas:
        await despues_de_registrar(e, usuario.id)
    return {"creadas": creadas, "duplicadas": duplicadas, "rechazadas": rechazadas}


# --- una entrada ------------------------------------------------------------------------------


async def _vinculos(sesion: AsyncSession, e: Entrada) -> list[dict]:
    """Documentos propios relacionados con la entrada (el grafo de Qillqa, por «relaciones.v1»)."""
    ids = {}
    for r in await puertos.relaciones_de(f"entrada:{e.id}"):
        otro = r["origen"] if r["destino"] == f"entrada:{e.id}" else r["destino"]
        if otro.startswith("doc:") and otro[4:].isdigit():
            ids.setdefault(int(otro[4:]), r)
    if not ids:
        return []
    docs = await puertos.breves(list(ids))
    salida = []
    for did, r in ids.items():
        d = docs.get(did)
        if d is None:
            continue
        salida.append({**d, "tipo": r["tipo"], "fuente": r["fuente"], "contexto": r["contexto"], "relacion_id": r["id"]})
    return salida


@router.get("/{eid}")
async def ficha(
    eid: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    e = await _entrada(sesion, eid)
    nombres = await _nombres(sesion, [e])
    return {
        **_resumen(e, nombres, svc.hoy_lima()),
        "mesa": (await _mesa(sesion, [e.id])).get(e.id) if e.via == "mesa_virtual" else None,
        "vinculos": await _vinculos(sesion, e),
        "tiene_pdf": svc.ruta_de(e.archivo) is not None,
        "texto": (e.texto or "")[:20_000],
    }


class Cambio(BaseModel):
    std_numero: str | None = Field(None, max_length=20)
    documento: str | None = Field(None, max_length=300)
    clase: str | None = None
    via: str | None = None
    remitente: str | None = Field(None, max_length=300)
    remitente_cargo: str | None = Field(None, max_length=300)
    remitente_persona_id: int | None = None
    remitente_institucion_id: int | None = None
    fecha_documento: str | None = None
    fecha_recepcion: str | None = None
    asunto: str | None = None
    referencia: str | None = None
    resumen: str | None = None
    atencion: str | None = None
    categoria: str | None = None
    requiere_revision: bool | None = None
    responde_a_documento_id: int | None = None
    responsable_id: int | None = None
    plazo: str | None = None
    campana: str | None = Field(None, max_length=160)
    nota: str | None = None
    estado: str | None = None
    origen_campos: dict | None = None


@router.put("/{eid}")
async def actualizar(
    eid: int,
    cambio: Cambio,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Corrige la ficha o la asigna. Solo viaja lo que cambia (`null` en responsable o
    remitente lo quita). Asignar a alguien una entrada nueva la pone «en atención»."""
    _puede_escribir(usuario)
    e = await _entrada(sesion, eid)
    datos = cambio.model_dump(exclude_unset=True)
    estado = datos.pop("estado", None)
    datos = await _validar(sesion, datos)
    if "std_numero" in datos and datos["std_numero"] and datos["std_numero"] != e.std_numero:
        otra = (await sesion.execute(select(Entrada.id).where(Entrada.std_numero == datos["std_numero"], Entrada.id != e.id))).first()
        if otra:
            raise HTTPException(409, f"El número STD {datos['std_numero']} ya está registrado (entrada {otra[0]}).")
    responsable_antes = e.responsable_id
    if "origen_campos" in datos:
        datos["origen_campos"] = {**(e.origen_campos or {}), **datos["origen_campos"]}
    for k, v in datos.items():
        setattr(e, k, v if v is not None or k.endswith("_id") else "")
    if estado:
        _texto_valido(estado, svc.ESTADOS, "Estado")
        if estado == "archivada" and e.estado != "archivada":
            e.archivada_en = datetime.now(timezone.utc)
        if estado == "respondida" and e.estado != "respondida":
            e.respondida_en = datetime.now(timezone.utc)
        e.estado = estado
    if e.responsable_id and e.responsable_id != responsable_antes:
        if e.estado == "nueva":
            e.estado = "en_atencion"
        _avisar_asignacion(sesion, e, usuario)
        await _mesa_sigue(sesion, e, "en_revision", "revision", "", usuario, solo_desde="recibido")
        punku_eventos.emitir(sesion, "entrada.asignada", f"entrada:{e.id}", _datos_evento(e),
                             clave=f"entrada:{e.id}:asignada:{e.responsable_id}", usuario_id=usuario.id)
    if "plazo" in datos:
        e.aviso_vencida_en = None  # un plazo nuevo vuelve a avisar si vence
    await sesion.commit()
    await puertos.propagar(f"entrada:{e.id}")  # los mensajes del chat sobre el recibido, al día (2026-10-18), por «etiquetas.v1»
    nombres = await _nombres(sesion, [e])
    return _resumen(e, nombres, svc.hoy_lima())


class Nota(BaseModel):
    nota: str = ""


@router.post("/{eid}/archivar")
async def archivar(
    eid: int,
    datos: Nota | None = None,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Archiva la entrada (atendida sin oficio, solo para conocimiento, repetida…). No
    borra nada: se reabre cuando haga falta."""
    _puede_escribir(usuario)
    e = await _entrada(sesion, eid)
    e.estado = "archivada"
    e.archivada_en = datetime.now(timezone.utc)
    texto = (datos.nota if datos else "").strip()
    if texto:
        e.nota = (f"{e.nota}\n" if e.nota else "") + f"Archivada: {texto}"
    await _mesa_sigue(sesion, e, "archivado", "archivado", texto, usuario)
    await sesion.commit()
    return {"ok": True, "estado": e.estado}


async def _mesa_sigue(sesion: AsyncSession, e: Entrada, estado: str, accion: str, nota: str, usuario: Usuario,
                     solo_desde: str = "") -> None:
    """Archivar, reabrir o asignar un recibido de la mesa virtual también lo dice en su seguimiento
    público (asignar solo lo pasa de «Recibido» a «En revisión»)."""
    if e.via != "mesa_virtual":
        return
    from punku import mesa_virtual as mv

    t = await mv.tramite_de_entrada(sesion, e.id)
    if t is None or t.estado == estado or (solo_desde and t.estado != solo_desde):
        return
    mv.poner_estado(t, None, estado)
    mv.movimiento(sesion, t, accion, nota, usuario_id=usuario.id)


@router.post("/{eid}/reabrir")
async def reabrir(
    eid: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    _puede_escribir(usuario)
    e = await _entrada(sesion, eid)
    e.estado = "en_atencion" if e.responsable_id or e.respuesta_documento_id else "nueva"
    e.archivada_en = None
    e.respondida_en = None
    await _mesa_sigue(sesion, e, "en_revision", "reabierto", "", usuario)
    await sesion.commit()
    return {"ok": True, "estado": e.estado}


@router.get("/{eid}/pdf")
async def pdf(
    eid: int,
    peticion: Request,
    _: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> Response:
    e = await _entrada(sesion, eid)
    ruta = svc.ruta_de(e.archivo)
    if ruta is None:
        raise HTTPException(404, "El PDF de este documento recibido no está en el archivo documental.")
    return enviar_archivo(ruta, ruta.name, peticion=peticion)


@router.post("/{eid}/responder")
async def responder(
    eid: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Crea el BORRADOR del oficio de respuesta por el camino de siempre
    (`POST /api/documentos`: fecha, formato predeterminado y copias sugeridas) y le pone
    destinatario, asunto y referencia desde la ficha. Queda vinculado a la entrada; la
    entrada pasa a «en atención» y a «respondida» cuando el oficio se firme o se envíe.
    Si ya tiene un oficio de respuesta, devuelve ese. El borrador lo crea Qillqa («documentos.v1»; Punku P1b)."""
    _puede_escribir(usuario)
    documentos = puertos.documentos()
    e = await _entrada(sesion, eid)
    if e.respuesta_documento_id and e.respuesta_documento_id in await documentos.breves([e.respuesta_documento_id]):
        return {"id": e.respuesta_documento_id, "ya_existia": True}
    fichas = await puertos.fichas([e.remitente_persona_id] if e.remitente_persona_id else [],
                                  [e.remitente_institucion_id] if e.remitente_institucion_id else [])
    persona = fichas["personas"].get(e.remitente_persona_id)
    inst = fichas["instituciones"].get(e.remitente_institucion_id)
    campos: dict = {}
    if persona is not None:
        campos["destinatario_nombre"] = persona["nombre"]
        campos["destinatario_cargo"] = persona["cargo"] or e.remitente_cargo
        tratamiento = persona["tratamiento"] or ""
        if tratamiento:
            campos["destinatario_tratamiento"] = tratamiento if tratamiento.endswith(":") else f"{tratamiento}:"
    else:
        # Sin persona del directorio: la autoridad se completa a mano; la entidad, la del remitente.
        campos["destinatario_nombre"] = ""
        campos["destinatario_cargo"] = e.remitente_cargo
    if inst is not None:
        campos["destinatario_institucion"] = inst["nombre"]
    elif persona is None and e.remitente:
        campos["destinatario_institucion"] = e.remitente
    if e.asunto:
        campos["asunto"] = f"Atención a lo solicitado: {e.asunto}"[:600] if e.atencion in ("responder", "interceder") else e.asunto
    campos["referencia"] = svc.texto_cita(e)
    doc = await documentos.borrador_respuesta(
        usuario.id, campos, f"Borrador de respuesta al documento recibido «{(e.asunto or e.documento)[:120]}»")
    await svc.vincular(sesion, e, doc, usuario.id, "responder")
    if not e.responsable_id:
        e.responsable_id = usuario.id
    await sesion.commit()
    await puertos.registrar_relaciones([svc.relacion_respuesta(e, doc["id"], "responder", usuario.id)])
    return {"id": doc["id"], "ya_existia": False}


class Vinculo(BaseModel):
    documento_id: int


@router.post("/{eid}/vincular")
async def vincular(
    eid: int,
    datos: Vinculo,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    """Vincula a mano un documento propio como respuesta de la entrada (p. ej. un oficio
    que se redactó antes de registrar la entrada, o elegido en la Referencia)."""
    _puede_escribir(usuario)
    e = await _entrada(sesion, eid)
    doc = (await puertos.documentos().breves([datos.documento_id])).get(datos.documento_id)
    if doc is None:
        raise HTTPException(404, "El documento no existe.")
    await svc.vincular(sesion, e, doc, usuario.id, "manual")
    await sesion.commit()
    await puertos.registrar_relaciones([svc.relacion_respuesta(e, doc["id"], "manual", usuario.id)])
    return {"ok": True, "estado": e.estado}


@router.delete("/{eid}/vincular/{documento_id}")
async def desvincular(
    eid: int,
    documento_id: int,
    usuario: Usuario = Depends(usuario_actual),
    sesion: AsyncSession = Depends(obtener_sesion_punku),
) -> dict:
    _puede_escribir(usuario)
    e = await _entrada(sesion, eid)
    await puertos.quitar_relacion(f"doc:{documento_id}", f"entrada:{e.id}", "responde")   # «relaciones.v1»
    if e.respuesta_documento_id == documento_id:
        e.respuesta_documento_id = None
        if e.estado == "respondida":
            e.estado = "en_atencion"
            e.respondida_en = None
    await sesion.commit()
    return {"ok": True, "estado": e.estado}
