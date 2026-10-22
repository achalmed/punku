"""La Mesa de Partes SOLA: sin Qillqa y sin la base documental, con el anfitrión mínimo de Tiqsi (proyecto Punku P3; fase
10.2b de docs/plataforma/propuesta-repositorios.md, 2026-10-20).

    PUNKU_DATABASE_URL=postgresql+asyncpg://…/punku  PUNKU_DIR=…  JWT_SECRET=<32 o más caracteres> \\
      .venv/bin/uvicorn punku.sola:app --port 8034

Las cuentas viven en PUNKU_CUENTAS (por omisión <PUNKU_DIR>/cuentas.json) y se crean con
`python -m tiqsi.minimo cuenta <archivo> <usuario> --rol administrador --nombre …`; los PDF recibidos y los trámites de
la mesa virtual, en <PUNKU_DIR>/recibidos/. Sin Qillqa no hay directorio (el remitente queda como se registró), ni
documentos propios (ni «Responder» ni «Atender» con un oficio: sí con un PDF subido), ni campana ni reglas (su bandeja
guarda lo que contaría), ni feriados (solo sábados y domingos), ni pegado; y la mesa de partes virtual queda APAGADA
(sin el registro de módulos nadie la enciende). Registrar, leer y cruzar lo recibido, asignar, plazos, archivar y la
mesa virtual por dentro funcionan con lo suyo.
"""
from __future__ import annotations

import os
from pathlib import Path

from tiqsi.minimo import crear_app

from punku.config import config
from punku.manifiesto import MANIFIESTO

if not config.punku_database_url:
    raise SystemExit("La Mesa de Partes sola necesita su base: PUNKU_DATABASE_URL.")
if not config.punku_dir:
    raise SystemExit("La Mesa de Partes sola necesita dónde guardar sus archivos y sus cuentas: PUNKU_DIR.")
if not os.environ.get("JWT_SECRET"):
    raise SystemExit("La Mesa de Partes sola necesita su secreto: JWT_SECRET (firma las sesiones y los enlaces de la mesa virtual).")

app = crear_app([MANIFIESTO], nombre="Mesa de Partes", secreto=config.jwt_secret,
                cuentas=os.environ.get("PUNKU_CUENTAS") or Path(config.punku_dir) / "cuentas.json",
                web=os.environ.get("PUNKU_WEB") or None)
