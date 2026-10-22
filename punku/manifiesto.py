"""El manifiesto de la Mesa de Partes (proyecto Punku; fase 10.2b de docs/plataforma/propuesta-repositorios.md, 2026-10-20).

Aislándose por rebanadas, como Minka y Rimay. P1a (hecha): su configuración (servicios/punku_config.py), su sesión y
su Base sin claves foráneas hacia Qillqa (servicios/punku_db.py, punku/modelos.py) y su ajuste (`punku_ajustes`);
las cuentas, por «identidad.v1»; el directorio (las fichas del remitente, el cruce del membrete, «Llevar al
directorio»), por «directorio.v1»; los feriados, el registro de módulos, el pegado y las etiquetas, por sus
capacidades (servicios/punku_puertos.py). Aún toma de Qillqa el documento propio (responder, vincular), las
relaciones, el nombre y el número de los archivos, la campana y los eventos del sistema (P1b, P1c), y aún ofrece
«recibidos.v1» desde la plataforma (P2).

P1b (hecha): el documento propio por «documentos.v1» (su número y asunto, el que cita una referencia, el que se entrega
al remitente, el borrador de respuesta), el grafo de relaciones por «relaciones.v1» (después de su commit) y la campana
y los eventos de las reglas por su bandeja (`punku_bandeja`, servicios/punku_eventos.py). Cuando Qillqa concilia un
documento propio con los recibidos, la relación la registra ella en su transacción (servicios/conciliacion_recibidos.py).

P1c (hecha): la bitácora por su bandeja; sus nombres de archivo y el conteo de páginas, de Tiqsi.

P2 (hecha): Qillqa la usa solo por «recibidos.v1» (servicios/punku_contrato.py, que ahora vive aquí) y por el bus: al
guardar o firmar un oficio, Qillqa anota «recibidos.conciliar» en su bandeja de salida y Punku concilia después de su
commit, en su transacción, y pone al día el grafo por «relaciones.v1». Lo que lee un documento (normalizar, la fecha,
el remitente…) Qillqa lo tiene en su copia (servicios/lectura.py; la prueba de fronteras comprueba que lean igual).
"""
from __future__ import annotations

from tiqsi import Manifiesto
from tiqsi.bandeja_sql import BandejaSQL

from punku import api_entradas as entradas
from punku import api_mesa_publica as mesa_publica
from punku import api_mesa_virtual as mesa_virtual
from punku.modelos import BANDEJA
from punku import contrato as punku_contrato
from punku import db as punku_db
from punku.db import SesionPunku

VERSION = "0.1.0"


async def _preparar_base(_anfitrion) -> None:
    """Su base (si falta), sus tablas, sus migraciones y su ajuste (P1a)."""
    await punku_db.preparar()


MANIFIESTO = Manifiesto(
    id="recibidos", nombre="Mesa de Partes", version=VERSION, contrato="^0.1",
    routers=[entradas.router, mesa_publica.router, mesa_virtual.router],
    # Los prefijos con que se apaga (los del registro de módulos encendibles, servicios/modulos.py).
    prefijos=("/api/entradas", "/api/mesa-virtual"), publico=True,
    necesita=("identidad.v1",),
    aprovecha=("directorio.v1", "pegado.v1", "calendario.v1", "etiquetas.v1", "modulos.v1", "agenda.v1",
               "documentos.v1", "relaciones.v1"),
    al_arrancar=[_preparar_base],
    # Lo que cuenta a las reglas («entrada.*») y avisa a la campana («aviso.nuevo»), tras su commit (P1b).
    bandeja=BandejaSQL(SesionPunku, BANDEJA),
    # Lo que los demás leen y piden de lo recibido (servicios/punku_contrato.py; P2).
    ofrece={"recibidos.v1": punku_contrato.RECIBIDOS_V1},
    # Qillqa guardó o cambió de estado un documento propio: sus recibidos al día (P2).
    eventos={"recibidos.conciliar": [punku_contrato.al_conciliar]},
)
