"""API del EQUIPO para la mesa de partes virtual (2026-10-12; con sesión). La página pública vive en
api/mesa_publica.py; esto es lo que se hace desde Recibidos y desde Administración.

- `GET  /api/mesa-virtual/config`                 — la configuración (todo el equipo la lee; el enlace para copiar).
- `PUT  /api/mesa-virtual/config`                 — guardarla (solo administración): horario,
                                                     días no hábiles, plazo de subsanación, límites y tipos.
- `GET  /api/mesa-virtual/plazo?dias=2`           — hasta qué día hábil iría un plazo que empieza hoy.
- `GET  /api/mesa-virtual/entradas/{eid}`         — el trámite de un recibido que llegó por la mesa virtual.
- `POST /api/mesa-virtual/entradas/{eid}/accion`  — revisión, observar (motivo y plazo en días hábiles),
                                                     derivar, archivar o reabrir: cambia el estado PÚBLICO.
- `POST /api/mesa-virtual/entradas/{eid}/atender` — atender con la respuesta: un PDF subido o un documento
                                                     propio de Qillqa (firmado o generado), que el remitente descarga.
- `GET  /api/mesa-virtual/archivos/{aid}`         — un archivo del trámite (principal, anexo, subsanación, respuesta).
- `GET|POST /api/mesa-virtual/entradas/{eid}/contacto` — el remitente al directorio (2026-10-13): lo que se
                                                     propone y lo que coincide; vincular o crear, con confirmación.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tiqsi.puertos import Usuario, solo_administrador, usuario_actual
from tiqsi.pdf import contar_paginas
from tiqsi.web import enviar_archivo

from punku.modelos import Entrada
from punku.modelos import MesaArchivo, MesaTramite
from punku import puertos
from punku.db import obtener_sesion_punku
from punku import entradas as svc_entradas
from punku import eventos as punku_eventos
from punku import mesa_virtual as mv

router = APIRouter(prefix="/api/mesa-virtual", tags=["mesa de partes virtual"])


def _puede_escribir(u: Usuario) -> None:
    if u.rol == "invitado":
        raise HTTPException(403, "La cuenta de invitado solo puede consultar.")


# --- configuración ---------------------------------------------------------------------------------


@router.get("/config")
async def leer_config(_: Usuario = Depends(usuario_actual), sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    cfg = await mv.cargar_config(sesion)
    return {**cfg, "receptor": mv.nombre_receptor(cfg)}


@router.put("/config")
async def guardar_config(datos: dict, usuario: Usuario = Depends(solo_administrador),
                         sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    # Encenderla o apagarla (y su mensaje) va por `PUT /api/modulos/mesa_virtual`; aquí, lo demás.
    cfg = await mv.guardar_config(sesion, datos)
    # La bitácora es de Qillqa: la anotación sale por la bandeja de Punku («bitacora.nueva», P1c).
    punku_eventos.bitacora(sesion, usuario.id, "ajustes", "Configuración de la mesa de partes virtual")
    await sesion.commit()
    return {**cfg, "receptor": mv.nombre_receptor(cfg)}


@router.get("/plazo")
async def plazo(dias: int = 0, _: Usuario = Depends(usuario_actual), sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    cfg = await mv.cargar_config(sesion)
    n = dias if 1 <= dias <= 30 else cfg["plazo_subsanacion"]
    return {"dias": n, "plazo": mv.sumar_habiles(mv.ahora_local().date(), n, cfg).isoformat(), "hasta": mv.hora_cierre(cfg)}


# --- el trámite de un recibido ------------------------------------------------------------------------


async def _tramite(sesion: AsyncSession, eid: int) -> tuple[MesaTramite, Entrada]:
    e = await sesion.get(Entrada, eid)
    t = await mv.tramite_de_entrada(sesion, eid) if e is not None else None
    if e is None or t is None:
        raise HTTPException(404, "Este recibido no llegó por la mesa de partes virtual.")
    return t, e


async def _vista(sesion: AsyncSession, t: MesaTramite) -> dict:
    cfg = await mv.cargar_config(sesion)
    movimientos = await mv.movimientos_de(sesion, t.id)
    uids = {m.usuario_id for m in movimientos if m.usuario_id}
    usuarios = await puertos.nombres_de(uids)   # «identidad.v1» (Punku P1a)
    return mv.vista_interna(t, await mv.archivos_de(sesion, t.id), movimientos, usuarios, cfg)


@router.get("/entradas/{eid}")
async def ver(eid: int, _: Usuario = Depends(usuario_actual), sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    t, _e = await _tramite(sesion, eid)
    return await _vista(sesion, t)


class Accion(BaseModel):
    accion: str
    nota: str = Field("", max_length=4000)
    dias: int | None = None


@router.post("/entradas/{eid}/accion")
async def accion(eid: int, datos: Accion, usuario: Usuario = Depends(usuario_actual),
                 sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    """Cambia el estado que ve el remitente. Observar exige decir QUÉ subsanar (en un solo acto,
    TUO 27444, arts. 125.1 y 126.2) y fija el plazo en días hábiles desde el día hábil siguiente."""
    _puede_escribir(usuario)
    if datos.accion not in mv.ACCIONES:
        raise HTTPException(422, f"Acción no válida: {datos.accion}.")
    t, e = await _tramite(sesion, eid)
    nota = datos.nota.strip()
    cfg = await mv.cargar_config(sesion)
    if datos.accion == "observar":
        if len(nota) < 10:
            raise HTTPException(422, "Diga qué falta o qué debe corregir (lo leerá el remitente).")
        if t.estado in ("atendido", "archivado"):
            raise HTTPException(409, "El trámite ya está cerrado: reábralo antes de observarlo.")
        dias = datos.dias if datos.dias and 1 <= datos.dias <= 30 else cfg["plazo_subsanacion"]
        t.observacion = nota
        t.plazo_subsanacion = mv.sumar_habiles(mv.ahora_local().date(), dias, cfg)
    elif datos.accion == "reabrir":
        if t.estado not in ("atendido", "archivado"):
            raise HTTPException(409, "El trámite no está cerrado.")
    elif t.estado == mv.ACCIONES[datos.accion] and not nota:
        return await _vista(sesion, t)
    mv.poner_estado(t, e, mv.ACCIONES[datos.accion])
    accion_mov = {"revision": "revision", "observar": "observado", "derivar": "derivado", "archivar": "archivado", "reabrir": "reabierto"}[datos.accion]
    texto = nota
    if datos.accion == "observar":
        texto = f"{nota}\nPlazo para subsanar: hasta el {t.plazo_subsanacion.strftime('%d/%m/%Y')} ({mv.hora_cierre(cfg)})."
    mv.movimiento(sesion, t, accion_mov, texto, usuario_id=usuario.id)
    if datos.accion == "archivar" and nota:
        e.nota = (f"{e.nota}\n" if e.nota else "") + f"Archivada: {nota}"
    await sesion.commit()
    return await _vista(sesion, t)


@router.post("/entradas/{eid}/atender")
async def atender(eid: int, peticion: Request, usuario: Usuario = Depends(usuario_actual),
                  sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    """Atiende el trámite con su respuesta: `documento_id` (un documento propio; se toma el
    FIRMADO si lo tiene, si no el PDF generado, y queda vinculado como respuesta del recibido) o
    `archivo` (un PDF subido). La copia queda en la carpeta del trámite: lo que se entregó no cambia
    si después se recompila el documento."""
    _puede_escribir(usuario)
    t, e = await _tramite(sesion, eid)
    cfg = await mv.cargar_config(sesion)
    form = await peticion.form(max_files=2, max_fields=10)
    nota = str(form.get("nota") or "").strip()[:4000]
    doc_id = str(form.get("documento_id") or "").strip()
    subido = form.get("archivo")
    carpeta = mv.carpeta_tramite(t.expediente, t.recibido_en.astimezone(mv.zona()).date())
    orden = len(await mv.archivos_de(sesion, t.id)) + 1
    doc = None
    if doc_id.isdigit():
        # El documento propio y su PDF entregable (el FIRMADO si lo tiene), por «documentos.v1» (Punku P1b).
        doc = await puertos.documentos().entregable(int(doc_id))
        if doc is None:
            raise HTTPException(404, "El documento no existe.")
        # Al remitente solo se entrega lo que ya vale: firmado o enviado (nunca un borrador).
        if not doc["firmado"] and doc["estado"] not in svc_entradas.ESTADOS_DOC_RESPONDE:
            raise HTTPException(409, "Ese documento aún no está firmado ni enviado: entréguelo cuando lo esté o suba el PDF firmado.")
        origen = Path(doc["ruta"]) if doc["ruta"] else None
        if origen is None or not origen.is_file():
            raise HTTPException(409, "Ese documento aún no tiene PDF: genérelo o súbalo firmado.")
        destino = carpeta / mv.nombre_en_disco(orden, "respuesta", "pdf")
        await asyncio.to_thread(shutil.copyfile, origen, destino)
        nombre = origen.name
    elif subido is not None and hasattr(subido, "read"):
        trabajo = Path(tempfile.mkdtemp(prefix="respuesta-", dir=mv.carpeta_recepcion()))
        try:
            try:
                r = await mv.recibir_archivo(subido, "principal", trabajo, 40 * 1024 * 1024, [0], 40 * 1024 * 1024)
            except mv.Rechazo as x:
                raise HTTPException(x.codigo, x.motivo.replace("El documento principal", "La respuesta")) from None
            destino = await asyncio.to_thread(mv.mover, r.ruta, carpeta, mv.nombre_en_disco(orden, "respuesta", "pdf"))
            nombre = r.nombre
        finally:
            shutil.rmtree(trabajo, ignore_errors=True)
    else:
        raise HTTPException(422, "Elija el documento propio que responde o suba el PDF de la respuesta.")
    sesion.add(MesaArchivo(tramite_id=t.id, clase="respuesta", archivo=mv.relativa(destino), nombre=mv.sanear_nombre(nombre),
                           tipo="pdf", bytes=destino.stat().st_size, paginas=await asyncio.to_thread(contar_paginas, destino),
                           sha256=await asyncio.to_thread(mv.huella, destino), documento_id=doc["id"] if doc else None,
                           creado_por=usuario.id))
    if doc is not None:
        await svc_entradas.vincular(sesion, e, doc, usuario.id, "manual")
    mv.poner_estado(t, e, "atendido")
    mv.movimiento(sesion, t, "atendido", nota or "La respuesta está disponible para descargar.", usuario_id=usuario.id)
    punku_eventos.emitir(sesion, "entrada.respondida", f"entrada:{e.id}",
                         {"asunto": e.asunto or e.documento or "", "responsable_id": e.responsable_id,
                          "documento": f"doc:{doc['id']}" if doc else ""}, usuario_id=usuario.id)
    await sesion.commit()
    if doc is not None:   # el grafo es de Qillqa: «relaciones.v1», después del commit
        await puertos.registrar_relaciones([svc_entradas.relacion_respuesta(e, doc["id"], "manual", usuario.id)])
    return await _vista(sesion, t)


@router.get("/archivos/{aid}")
async def archivo(aid: int, peticion: Request, _: Usuario = Depends(usuario_actual),
                  sesion: AsyncSession = Depends(obtener_sesion_punku)) -> Response:
    a = await sesion.get(MesaArchivo, aid)
    ruta = mv.absoluta(a.archivo) if a else None
    if a is None or ruta is None:
        raise HTTPException(404, "El archivo no está en el archivo documental.")
    t = await sesion.get(MesaTramite, a.tramite_id)
    nombre = f"{t.expediente}-{a.nombre}" if t else a.nombre
    r = enviar_archivo(ruta, nombre, media_type=mv.TIPOS_ARCHIVO.get(a.tipo, "application/octet-stream"), peticion=peticion)
    r.headers["X-Content-Type-Options"] = "nosniff"
    return r


# --- el remitente al directorio (2026-10-13) --------------------------------------------------------
# Edison: «eso de datos personales podemos usarlo para el directorio, para tener contacto». Al atender
# un trámite, el remitente se PROPONE como contacto (persona o institución, con su celular y correo):
# vincular si ya está, crear si no. Nada se crea solo: la persona del equipo lo confirma con un toque,
# y el recibido queda vinculado a su ficha (docs/arquitectura.md §27). La regla de duplicados es la
# misma de la importación de contactos (servicios/contactos.py).


def _remitente(t: MesaTramite) -> dict:
    return {"tipo_persona": t.tipo_persona, "nombre": t.nombre, "representante": t.representante, "cargo": t.cargo,
            "correo": t.correo, "telefono": t.telefono, "direccion": t.direccion, "doc_numero": t.doc_numero}


async def _remitente_y_coincidencias(t: MesaTramite, e: Entrada) -> dict:
    """La propuesta, lo que coincide y lo vinculado: lo decide el directorio («directorio.v1», Punku P1a)."""
    return await puertos.directorio().coincidencias(_remitente(t), e.remitente_persona_id, e.remitente_institucion_id)


@router.get("/entradas/{eid}/contacto")
async def contacto_del_remitente(eid: int, _: Usuario = Depends(usuario_actual), sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    """Lo que se propone llevar al directorio y lo que ya hay: la persona o institución que coincide
    (mismo celular, correo o nombre; la entidad por RUC o nombre) y lo ya vinculado al recibido."""
    t, e = await _tramite(sesion, eid)
    return await _remitente_y_coincidencias(t, e)


class AlDirectorio(BaseModel):
    # vincular (con su id) | crear | omitir
    persona: str = "omitir"
    persona_id: int | None = None
    institucion: str = "omitir"
    institucion_id: int | None = None


@router.post("/entradas/{eid}/contacto")
async def llevar_al_directorio(eid: int, datos: AlDirectorio, usuario: Usuario = Depends(usuario_actual),
                               sesion: AsyncSession = Depends(obtener_sesion_punku)) -> dict:
    """Vincula el recibido a la ficha que ya existe (rellenando solo lo vacío: celular, correo; lo
    que dicta una cuenta de Qillqa no se toca) o crea la ficha con los datos del remitente. Lo hace el directorio
    («directorio.v1».llevar, con su bitácora); aquí queda el vínculo del recibido y el movimiento del trámite."""
    _puede_escribir(usuario)
    t, e = await _tramite(sesion, eid)
    vinc_p, vinc_i = e.remitente_persona_id, e.remitente_institucion_id
    try:
        r = await puertos.directorio().llevar(_remitente(t), t.expediente, datos.persona, datos.persona_id, datos.institucion,
                                              datos.institucion_id, usuario.id, vinc_p, vinc_i)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if r["institucion_id"]:
        e.remitente_institucion_id = r["institucion_id"]
    if r["persona_id"]:
        e.remitente_persona_id = r["persona_id"]
    mv.movimiento(sesion, t, "directorio", "Remitente en el directorio: " + "; ".join(r["hecho"]) + ".", publico=False, usuario_id=usuario.id)
    await sesion.commit()
    return await _remitente_y_coincidencias(t, e)
