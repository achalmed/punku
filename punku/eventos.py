"""Lo que la Mesa de Partes cuenta y avisa, por su bandeja de salida (proyecto Punku P1b; fase 10.2b, 2026-10-20).

    emitir(sesion, "entrada.asignada", "entrada:12", {...}, usuario_id=…)   # un hecho para las reglas de Qillqa
    avisar(sesion, usuario_id, "Le encargaron …", "entrada", evitar=…, destino="entrada:12")   # la campana
    bitacora(sesion, usuario_id, "ajustes", "Configuración de la mesa de partes virtual")   # la bitácora de Qillqa

Ninguna hace commit ni sale de la transacción de quien llama: se anotan en `punku_bandeja` (modelos_mesa.BANDEJA) y el
repartidor del anfitrión los entrega al bus. Así Punku no importa ni las reglas ni las notificaciones de Qillqa, el
aviso se guarda con el cambio o no se guarda, y nada se pierde si la API se reinicia en medio. La clave por omisión
de un evento es la de Qillqa (`entrada:12:asignada`): una segunda entrega no lo repite.
"""
from __future__ import annotations

from datetime import datetime, timezone

from punku.modelos import SalidaPunku

ORIGEN = "recibidos"


def emitir(sesion, nombre: str, entidad: str, datos: dict | None = None, clave: str | None = None,
           usuario_id: int | None = None) -> None:
    sesion.add(SalidaPunku(tipo=nombre, origen=ORIGEN, intentos=0, error="", datos={
        "entidad": entidad or "", "datos": dict(datos or {}), "clave": clave, "usuario_id": usuario_id,
        # Quien lo causó, con el nombre que usan los que escuchan los eventos de Qillqa (Tareas y Agenda).
        "emitido_por": usuario_id}))


def avisar(sesion, usuario_id: int | None, texto: str, tipo: str = "", evitar: int | None = None, destino: str = "") -> None:
    """Un aviso en la campana de `usuario_id`; nadie se avisa a sí mismo (`evitar`)."""
    if not usuario_id or usuario_id == evitar:
        return
    sesion.add(SalidaPunku(tipo="aviso.nuevo", origen=ORIGEN, intentos=0, error="", datos={
        "usuario_id": usuario_id, "texto": texto[:500], "tipo": tipo, "destino": destino[:80]}))


def bitacora(sesion, usuario_id: int | None, accion: str, detalle: str = "") -> None:
    """Una anotación en la bitácora de Qillqa (quién hizo qué; sin documento), como `bitacora.registrar` (P1c)."""
    sesion.add(SalidaPunku(tipo="bitacora.nueva", origen=ORIGEN, intentos=0, error="", datos={
        "usuario_id": usuario_id, "accion": accion[:40], "detalle": detalle[:2000],
        # La hora del cambio, no la de la entrega (hasta 2 s después).
        "fecha": datetime.now(timezone.utc).isoformat()}))
