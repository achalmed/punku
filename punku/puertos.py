"""Lo que la Mesa de Partes (proyecto Punku) pide a la plataforma, en un solo lugar (fase 10.2b, P1a, 2026-10-20).

Punku ya no lee las tablas de cuentas, personas ni instituciones, ni los ajustes, el registro de módulos, los
feriados ni el pegado de Qillqa: los pide por el contrato de Tiqsi. Aquí está cada pedido con lo que se hace cuando
la capacidad no está (Punku solo, con el anfitrión mínimo):

- «identidad.v1» (la necesita): los nombres de las cuentas, el responsable válido y quiénes administran;
- «directorio.v1» (la aprovecha): las fichas del remitente, el cruce del membrete, la institución por RUC, las
  coincidencias y «Llevar al directorio»; sin él, el remitente se ve como se registró y no se cruza nada;
- «etiquetas.v1»: el nombre del recibido en los mensajes del chat, al día tras guardar;
- «calendario.v1»: los feriados (sin él, solo sábados y domingos no son hábiles);
- «modulos.v1»: si la mesa virtual está encendida (sin el registro, apagada);
- «pegado.v1»: la lectura de un prompt pegado (sin él, «Pegar» responde que no está disponible).
- «documentos.v1» (P1b): el documento PROPIO (su número y asunto, el que cita una referencia, el que se entrega al
  remitente, el borrador de respuesta); sin él, el recibido no se cruza con documentos propios;
- «relaciones.v1» (P1b): el grafo de Qillqa (lo que responde a qué); se escribe DESPUÉS del commit de Punku, y un fallo
  allí se anota sin deshacer lo de Punku (la conciliación lo vuelve a intentar).

La campana y los eventos de las reglas no se piden: salen por su bandeja (servicios/punku_eventos.py).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import HTTPException
from tiqsi.modulo import Perezosa, opcional

identidad = Perezosa("identidad.v1")
log = logging.getLogger("qillqa.entradas")


# --- las cuentas ------------------------------------------------------------------------------------------------


async def nombres_de(ids) -> dict[int, str]:
    """{id: nombre completo} de las cuentas pedidas (las que existen)."""
    ids = {int(x) for x in ids or () if x}
    if not ids:
        return {}
    return {c["id"]: c["nombre_completo"] for c in await identidad.cuentas() if c["id"] in ids}


async def cuenta_activa(uid: int) -> bool:
    c = await identidad.cuenta(int(uid))
    return bool(c and c["activo"])


async def administradores() -> list[int]:
    """Los ids de las cuentas activas que administran (a quienes se avisa de lo que llega por la mesa virtual)."""
    return [c["id"] for c in await identidad.cuentas() if c["activo"] and c["rol"] == "administrador"]


# --- el directorio ---------------------------------------------------------------------------------------------


async def fichas(personas=(), instituciones=()) -> dict:
    """{"personas": {id: ficha}, "instituciones": {id: ficha}}; sin directorio, vacías."""
    directorio = opcional("directorio.v1")
    if directorio is None:
        return {"personas": {}, "instituciones": {}}
    return await directorio.fichas(personas, instituciones)


async def para_cruzar() -> tuple[list, list]:
    """(instituciones, personas) activas para cruzar el membrete y la firma; sin directorio, nada que cruzar."""
    directorio = opcional("directorio.v1")
    return await directorio.para_cruzar() if directorio is not None else ([], [])


async def institucion_por_ruc(ruc: str) -> int | None:
    directorio = opcional("directorio.v1")
    return await directorio.institucion_por_ruc(ruc) if directorio is not None and ruc else None


def directorio():
    """El directorio para «Llevar al directorio» (503 si no está: esa acción no tiene otro camino)."""
    d = opcional("directorio.v1")
    if d is None:
        raise HTTPException(503, "El directorio no está disponible.")
    return d


def remitente_vigente(texto: str, cargo: str, persona: tuple[str, str] | None = None,
                      institucion: str | None = None) -> tuple[str, str]:
    """Remitente de un recibido con el valor VIGENTE del directorio: vinculado a una persona, su nombre y su cargo de
    hoy; solo a una institución, su nombre de hoy; sin vínculo, lo registrado. `persona` = (nombre, cargo). Pura (la
    misma regla que `etiquetas.remitente_vigente` de Qillqa; la prueba de fronteras comprueba que coinciden)."""
    if persona and persona[0]:
        return persona[0], persona[1] or cargo or ""
    if institucion:
        return institucion, cargo or ""
    return texto or "", cargo or ""


# --- etiquetas, calendario, módulos, pegado ---------------------------------------------------------------------


async def propagar(entidad: str) -> None:
    """Lo que muestra el nombre de `entidad` (los mensajes del chat), al día; después del commit de Punku."""
    etiquetas = opcional("etiquetas.v1")
    if etiquetas is not None:
        await etiquetas.propagar(entidad)


def dias_habiles(desde: date, dias: int) -> date:
    calendario = opcional("calendario.v1")
    if calendario is not None:
        return calendario.dias_habiles(desde, dias)
    d, n = desde, 0
    while n < dias:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return d


def feriados_entre(desde: date, hasta: date) -> list[dict]:
    calendario = opcional("calendario.v1")
    return calendario.entre(desde, hasta) if calendario is not None else []


APAGADA = "La mesa de partes virtual no está disponible por el momento."


async def modulo(mid: str) -> dict:
    """{activo, mensaje} de un módulo encendible (la mesa virtual). Sin el registro (Punku sola), APAGADO: la página
    pública no se abre sin que alguien la encienda (Edison 2026-10-18: «debe quedar desactivada»)."""
    modulos = opcional("modulos.v1")
    return await modulos.estado(mid) if modulos is not None else {"activo": False, "mensaje": APAGADA}


def pegado():
    """El lector de prompts pegados (503 si no está)."""
    p = opcional("pegado.v1")
    if p is None:
        raise HTTPException(503, "La lectura de lo pegado no está disponible.")
    return p


# --- el documento propio y las relaciones (P1b) ------------------------------------------------------------------


def _documentos():
    return opcional("documentos.v1")


def documentos():
    """«documentos.v1» para lo que no tiene otro camino (entregar un documento propio, crear el borrador): 503 sin él."""
    d = _documentos()
    if d is None:
        raise HTTPException(503, "Los documentos propios no están disponibles.")
    return d


async def breves(ids) -> dict[int, dict]:
    """{id: {id, numero, estado, asunto}} de los documentos propios; sin el módulo, vacío."""
    d = _documentos()
    return await d.breves(ids) if d is not None and ids else {}


async def documento_citado(cita: dict) -> dict | None:
    d = _documentos()
    return await d.citado(cita) if d is not None else None


async def documento_por_expediente(expediente: str) -> dict | None:
    d = _documentos()
    return await d.por_expediente(expediente) if d is not None else None


async def documento_por_numero(numero: int) -> dict | None:
    d = _documentos()
    return await d.por_numero(numero) if d is not None else None


async def referencias_de_documentos() -> list[dict]:
    d = _documentos()
    return await d.referencias() if d is not None else []


async def respuesta_recibida(entrada_id: int, doc_id: int, fecha: str, texto: str, usuario_id: int | None) -> None:
    """El recibido contesta un oficio propio: relación y actuación en el seguimiento del oficio (después del commit;
    nunca hace fallar el registro)."""
    d = _documentos()
    if d is None:
        return
    try:
        await d.respuesta_recibida(entrada_id, doc_id, fecha, texto, usuario_id)
    except Exception:  # noqa: BLE001
        log.exception("No se pudo vincular el recibido %s con el oficio %s", entrada_id, doc_id)


async def relaciones_de(entidad: str) -> list[dict]:
    r = opcional("relaciones.v1")
    return await r.de(entidad) if r is not None else []


async def registrar_relaciones(lista: list[dict]) -> None:
    """Registra en el grafo de Qillqa las relaciones de `lista` (las de `entradas.relacion_respuesta`), después del
    commit de Punku; un fallo se anota y no deshace nada."""
    r = opcional("relaciones.v1")
    if r is None:
        return
    for kw in lista:
        try:
            await r.registrar(**kw)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo registrar la relación %s → %s", kw.get("origen"), kw.get("destino"))


async def quitar_relacion(origen: str, destino: str, tipo: str, contexto: str | None = None, fuente: str | None = None) -> None:
    r = opcional("relaciones.v1")
    if r is not None:
        await r.quitar(origen, destino, tipo, contexto=contexto, fuente=fuente)
