"""tests/test_punku_sola.py — la Mesa de Partes arranca SOLA, con el anfitrión mínimo de Tiqsi, sin Qillqa ni la
base documental (proyecto Punku P3; fase 10.2b, 2026-10-20; app/punku_sola.py). Sin base de datos: lo que la necesita se
prueba en vivo contra una vacía (qillqa/scripts/verde.sh sola-punku).
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SECRETO = "k" * 40


def _entorno_limpio(tmp_path) -> dict:
    return {"HOME": os.environ.get("HOME", "/tmp"), "PATH": os.environ.get("PATH", ""),
            "PUNKU_DATABASE_URL": "postgresql+asyncpg://nadie:nada@127.0.0.1:1/punku_prueba",
            "PUNKU_DIR": str(tmp_path / "punku"), "JWT_SECRET": SECRETO}


def test_sola_no_carga_nada_de_qillqa(tmp_path):
    codigo = ("import sys, json; import punku.sola as m; "
              "print(json.dumps({'ajenos': sorted(x for x in sys.modules if x == 'app' or x.startswith('app.')), "
              "'informe': m.app.state.anfitrion.informe(), 'capacidades': m.app.state.anfitrion.capacidades.ofrecidas()}))")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, env=_entorno_limpio(tmp_path),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    datos = json.loads(r.stdout.strip().splitlines()[-1])
    assert datos["ajenos"] == []                                    # nada de Qillqa
    assert datos["informe"] == [{"id": "recibidos", "nombre": "Mesa de Partes", "version": "0.1.0"}]
    assert set(datos["capacidades"]) == {"identidad.v1", "recibidos.v1"}


def test_sola_sin_su_base_o_sin_secreto_no_arranca(tmp_path):
    for falta in ("PUNKU_DATABASE_URL", "PUNKU_DIR", "JWT_SECRET"):
        entorno = {k: v for k, v in _entorno_limpio(tmp_path).items() if k != falta}
        r = subprocess.run([sys.executable, "-c", "import punku.sola"], cwd=RAIZ, env=entorno,
                           capture_output=True, text=True, timeout=120)
        assert r.returncode != 0 and falta in r.stderr, falta


def test_sola_atiende_con_su_propia_sesion_y_la_mesa_virtual_apagada(tmp_path):
    from fastapi.testclient import TestClient
    from tiqsi import Manifiesto
    from tiqsi.minimo import Cuentas, crear_app

    from punku import puertos as punku_puertos
    from punku.manifiesto import MANIFIESTO

    cuentas = tmp_path / "cuentas.json"
    Cuentas(cuentas).crear("ana", "clave-larga-1", "administrador", "Ana Pérez")
    copia = Manifiesto(**{**MANIFIESTO.__dict__, "al_arrancar": [], "tareas": [], "bandeja": None})   # sin base aquí
    c = TestClient(crear_app([copia], nombre="Mesa de Partes", secreto=SECRETO, cuentas=cuentas))
    assert c.get("/api/health").json()["anfitrion"] == "Mesa de Partes"
    assert c.get("/api/entradas/resumen").status_code == 401
    rutas = {x.path for x in c.app.routes}
    assert {"/api/entradas", "/api/entradas/{eid}", "/api/mesa-virtual/config", "/api/publico/mesa/config"} <= rutas
    # Sin Qillqa: nadie la enciende (sin el registro de módulos, la página pública queda apagada).
    assert asyncio.run(punku_puertos.modulo("mesa_virtual"))["activo"] is False
    assert asyncio.run(punku_puertos.fichas([1], [2])) == {"personas": {}, "instituciones": {}}
    assert asyncio.run(punku_puertos.breves([5])) == {}


def test_la_configuracion_de_la_base_de_punku():
    from punku import config as punku_config

    assert punku_config.url_base() == (punku_config.config.punku_database_url or punku_config.config.database_url)
