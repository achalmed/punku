"""La configuración PROPIA de la Mesa de Partes (proyecto Punku P1a; fase 10.2b de docs/plataforma/propuesta-repositorios.md,
2026-10-20). Lee las mismas variables que Qillqa (DATABASE_URL, ZONA_HORARIA, MDD_DOCUMENTOS/MDD_RUTA, PERIODO, SIGLAS,
VITE_NOMBRE_DESPACHO, JWT_SECRET) más las suyas: PUNKU_DATABASE_URL (vacía: la base documental, como hasta hoy) y
PUNKU_DIR (sola: su carpeta). No depende de `app.config`: viaja con el módulo.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

# La carpeta de lo recibido dentro del archivo documental (la del tipo `recibido` del registro de tipos de Qillqa;
# tests/test_fronteras.py comprueba que siga siendo la misma).
CARPETA_RECIBIDOS = "recibidos"


class ConfigPunku(BaseSettings):
    database_url: str = "postgresql+asyncpg://qillqa:qillqa@db:5432/qillqa"
    punku_database_url: str = ""
    zona_horaria: str = "America/Lima"
    mdd_ruta: str = "/framework"
    mdd_documentos: str = ""
    periodo: str = "2026-2027"
    siglas: str = "DESPACHO-CD/CRP"
    vite_nombre_despacho: str = ""
    # La firma de los enlaces de la mesa virtual y, sola (punku/sola.py), de las sesiones.
    jwt_secret: str = "cambiar-en-produccion"
    punku_dir: str = ""


config = ConfigPunku()


def url_base() -> str:
    """La URL de su base: PUNKU_DATABASE_URL o, mientras no se separe, la documental."""
    return config.punku_database_url or config.database_url


def raiz() -> Path:
    """La raíz de sus archivos: PUNKU_DIR (sola) o la raíz documental de Qillqa (la misma regla que app.config)."""
    if config.punku_dir:
        return Path(config.punku_dir)
    return Path(config.mdd_documentos) if config.mdd_documentos else Path(config.mdd_ruta) / "documentos"
