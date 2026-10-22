"""punku/contrato.py — «recibidos.v1»: lo que la Mesa de Partes (proyecto Punku) ofrece a los demás (fase 10.2b, P2, 2026-10-20).

Qillqa y Tareas y Agenda leen y piden lo recibido solo por aquí, cada función con su propia sesión de la base de Punku:

- `por_atender()`, `existen(ids)`, `ficha(id)`: lo que leen la agenda detectada y las tareas automáticas (con el texto);
- `fichas(ids)` y `todas(archivadas)`: las fichas sin el texto (las etiquetas, el chat, el Mapa);
- `citables(limite)`: lo que se ofrece al citar un recibido (el buscador de referencias), con cómo se cita;
- `buscar(std, documento)`: el recibido por su n.º STD o por el número de su documento (el pegado de seguimiento);
- `archivos()`: los PDF de lo recibido que están en disco (la copia sin conexión);
- `vincular(entrada_id, doc, usuario_id, contexto)`: un documento propio ({id, estado}) responde el recibido;
- `registrar_archivo(ruta, nombre, usuario_id, nota, campos)`: un archivo entra por la ficha automática (el chat).

Y escucha «recibidos.conciliar» (Qillqa guardó o cambió de estado un documento propio): concilia sus recibidos en su
transacción y pone al día el grafo de Qillqa por «relaciones.v1».
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from sqlalchemy import select

from punku.modelos import Entrada
from punku import entradas as svc
from punku import puertos
from punku.db import SesionPunku

log = logging.getLogger("qillqa.entradas")


def _ficha(e, con_texto: bool = True) -> dict:
    f = {"id": e.id, "asunto": e.asunto or "", "documento": e.documento or "", "nombre_original": e.nombre_original or "",
         "std_numero": e.std_numero or "", "clase": e.clase, "via": e.via, "remitente": e.remitente or "",
         "remitente_cargo": e.remitente_cargo or "", "remitente_persona_id": e.remitente_persona_id,
         "remitente_institucion_id": e.remitente_institucion_id, "fecha": str(e.fecha_documento or e.fecha_recepcion or ""),
         "fecha_documento": e.fecha_documento or "", "fecha_recepcion": e.fecha_recepcion or "", "resumen": e.resumen or "",
         "atencion": e.atencion, "etiqueta_atencion": svc.ETIQUETA_ATENCION.get(e.atencion, "Atender"),
         "abierta": e.estado in svc.ESTADOS_ABIERTOS, "estado": e.estado, "responsable_id": e.responsable_id,
         "plazo": e.plazo, "respuesta_documento_id": e.respuesta_documento_id, "cita": svc.texto_cita(e)}
    if con_texto:
        f["texto"] = e.texto or ""
    return f


async def por_atender() -> list[dict]:
    async with SesionPunku() as sesion:
        return [_ficha(e) for e in (await sesion.execute(
            select(Entrada).where(Entrada.atencion != "conocimiento", Entrada.responsable_id.is_not(None)))).scalars()]


async def existen(ids) -> set[int]:
    ids = {int(i) for i in ids or () if i}
    if not ids:
        return set()
    async with SesionPunku() as sesion:
        return set((await sesion.execute(select(Entrada.id).where(Entrada.id.in_(ids)))).scalars().all())


async def ficha(entrada_id: int) -> dict | None:
    async with SesionPunku() as sesion:
        e = await sesion.get(Entrada, int(entrada_id))
        return _ficha(e) if e is not None else None


async def fichas(ids) -> dict[int, dict]:
    ids = {int(i) for i in ids or () if i}
    if not ids:
        return {}
    async with SesionPunku() as sesion:
        return {e.id: _ficha(e, False) for e in (await sesion.execute(select(Entrada).where(Entrada.id.in_(ids)))).scalars()}


async def todas(archivadas: bool = False) -> list[dict]:
    q = select(Entrada).order_by(Entrada.id)
    if not archivadas:
        q = q.where(Entrada.estado != "archivada")
    async with SesionPunku() as sesion:
        return [_ficha(e, False) for e in (await sesion.execute(q)).scalars()]


async def citables(limite: int = 2000) -> list[dict]:
    async with SesionPunku() as sesion:
        return [_ficha(e, False) for e in (await sesion.execute(
            select(Entrada).where(Entrada.estado != "archivada").order_by(Entrada.id.desc()).limit(limite))).scalars()]


async def buscar(std: str = "", documento: str = "") -> dict | None:
    """Por n.º STD (exacto, solo cifras) o, si no, por el número del documento (el más parecido de los que lo llevan)."""
    import re

    async with SesionPunku() as sesion:
        hallada = None
        std = "".join(ch for ch in (std or "") if ch.isdigit())
        if std:
            hallada = (await sesion.execute(select(Entrada).where(Entrada.std_numero == std))).scalars().first()
        if hallada is None and documento:
            cifras = re.findall(r"\d{3,}", documento)
            if cifras:
                candidatas = (await sesion.execute(select(Entrada).where(Entrada.documento.ilike(f"%{cifras[0]}%")).limit(10))).scalars().all()
                hallada = max(candidatas, key=lambda e: svc.similitud(e.documento or "", documento), default=None)
        return _ficha(hallada, False) if hallada is not None else None


async def archivos() -> list[dict]:
    """[{id, archivo (relativo), ruta (absoluta)}] de lo recibido cuyo PDF está en disco, en orden de id."""
    async with SesionPunku() as sesion:
        filas = (await sesion.execute(select(Entrada.id, Entrada.archivo).order_by(Entrada.id))).all()
    salida = []
    for eid, archivo in filas:
        ruta = svc.ruta_de(archivo)
        if ruta is not None:
            salida.append({"id": eid, "archivo": archivo, "ruta": str(ruta)})
    return salida


async def vincular(entrada_id: int, doc: dict, usuario_id: int | None, contexto: str) -> bool:
    """El documento propio `doc` ({id, estado}) responde el recibido: la entrada (con su evento y su aviso) y la relación
    en el grafo de Qillqa. → si el recibido existe."""
    async with SesionPunku() as sesion:
        e = await sesion.get(Entrada, int(entrada_id))
        if e is None:
            return False
        await svc.vincular(sesion, e, doc, usuario_id, contexto)
        await sesion.commit()
    await puertos.registrar_relaciones([svc.relacion_respuesta(e, doc["id"], contexto, usuario_id)])
    return True


async def registrar_archivo(ruta, nombre: str, usuario_id: int, nota: str, campos: dict | None = None) -> tuple[int | None, str]:
    """El archivo entra por la ficha automática; `campos` (de un pegado) pisan lo que la ficha leyó. → (id de la
    entrada o None, texto para la persona). Con su sesión y su commit."""
    from punku.api_entradas import Confirmar, FichaEntrada, _analizar_uno, _contexto, _registrar, despues_de_registrar

    cuenta = await puertos.identidad.cuenta(int(usuario_id))
    usuario = SimpleNamespace(**cuenta) if cuenta else SimpleNamespace(id=usuario_id, nombre_completo="", rol="")
    async with SesionPunku() as sesion:
        directorio, existentes, previas, hoy = await _contexto(sesion)
        a = await _analizar_uno(sesion, nombre, ruta, directorio, existentes, previas, hoy)
        if a.get("error"):
            return None, f"No se pudo leer {nombre}: {a['error']}"
        f = {k: v for k, v in a["ficha"].items() if k in FichaEntrada.model_fields}
        extra = {k: v for k, v in (campos or {}).items() if k in FichaEntrada.model_fields and v not in (None, "", [])}
        origen = {**{k: "documento" for k, v in f.items() if v}, **{k: "pegado" for k in extra}}
        item = Confirmar(token=a["token"], nombre=a["nombre"], **{**f, "via": "otro", **extra,
                         "nota": "\n".join(x for x in (extra.get("nota", ""), nota) if x), "origen_campos": origen})
        e, dup = await _registrar(sesion, item, usuario, existentes)
        if e is None:
            return None, f"{nombre}: ya estaba registrado ({(dup or {}).get('motivo', 'duplicado')})."
        await sesion.commit()
    await despues_de_registrar(e, usuario.id)
    return e.id, f"Registrado en Mesa de Partes (n.º {e.id}): «{(e.asunto or e.documento or nombre)[:80]}»."


# --- lo que llega por el bus ------------------------------------------------------------------------------------


async def al_conciliar(evento) -> None:
    """«recibidos.conciliar» (Qillqa guardó o cambió de estado un documento propio, ya con su commit): sus recibidos al
    día y el grafo con ellos (las relaciones automáticas por referencia que ya no cita salen; las nuevas entran)."""
    d = evento.datos or {}
    doc, uid = dict(d.get("documento") or {}), d.get("usuario_id")
    if not doc.get("id"):
        return
    async with SesionPunku() as sesion:
        r = await svc.conciliar_documento(sesion, doc, uid)
        await sesion.commit()
    origen = f"doc:{doc['id']}"
    for rel in await puertos.relaciones_de(origen):
        if rel["origen"] == origen and rel["destino"].startswith("entrada:") and rel["fuente"] == "auto" \
                and rel["contexto"] == "referencia":
            eid = rel["destino"].split(":", 1)[1]
            if eid.isdigit() and int(eid) not in r["citadas"]:
                await puertos.quitar_relacion(origen, rel["destino"], rel["tipo"], contexto="referencia", fuente="auto")
    await puertos.registrar_relaciones(r["relaciones"])


class _Superficie:
    """Resuelve cada nombre al usarlo y rechaza lo que no está en la lista (el contrato se cumple)."""

    def __init__(self, nombre: str, funciones: tuple[str, ...]) -> None:
        self._nombre, self._funciones = nombre, funciones

    def __getattr__(self, nombre: str):
        if nombre in self._funciones:
            return globals()[nombre]
        raise AttributeError(f"«{nombre}» no es parte de «{self._nombre}» (servicios/punku_contrato.py)")

    def __dir__(self):
        return sorted(self._funciones)


RECIBIDOS_V1 = _Superficie("recibidos.v1", ("por_atender", "existen", "ficha", "fichas", "todas", "citables", "buscar",
                                            "archivos", "vincular", "registrar_archivo"))
