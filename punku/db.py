"""La base de la Mesa de Partes: su motor, su sesión y la preparación de sus tablas (proyecto Punku P1a y P3; fase 10.2b,
2026-10-20). Con PUNKU_DATABASE_URL, su base propia (nace al arrancar si falta); sin ella, la documental.

Separar sus datos de la base documental es una orden del módulo (simula por omisión; tiqsi.sql.separar copia y verifica
cada tabla). Lee el origen de DATABASE_URL y el destino de PUNKU_DATABASE_URL:

    python -m punku.db separar             # qué copiaría (filas y huella por tabla)
    python -m punku.db separar --aplicar   # copia, verifica y trae su ajuste de `ajustes`

Su ajuste (la configuración de la mesa de partes virtual, «mesa_virtual») vivía en `ajustes` de la plataforma: en la
misma base se copia una vez a `punku_ajustes` al arrancar; a su base propia, al separar (allá se deja: nadie más lo lee).
Un seguro le impide arrancar sobre su base propia VACÍA si la documental aún tiene lo recibido: sembraría una Mesa de
Partes nueva y lo de antes quedaría a la vista de nadie (lo aprendido con el chat, Rimay R3).
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from punku.config import url_base

motor = create_async_engine(url_base(), pool_pre_ping=True)
SesionPunku = async_sessionmaker(motor, expire_on_commit=False)

AJUSTES = ("mesa_virtual",)

# Migraciones ligeras e idempotentes (antes en main.py): lo que `create_all` no altera en tablas ya existentes y los
# índices de la lista. Sin claves foráneas hacia Qillqa (el documento al que responde, como número).
MIGRACIONES = (
    "CREATE INDEX IF NOT EXISTS entradas_plazo ON entradas (estado, plazo)",
    "CREATE INDEX IF NOT EXISTS entradas_responsable ON entradas (responsable_id)",
    "CREATE INDEX IF NOT EXISTS entradas_respuesta ON entradas (respuesta_documento_id)",
    # Pegar resultado (2026-10-11): de dónde salió cada campo de la ficha.
    "ALTER TABLE entradas ADD COLUMN IF NOT EXISTS origen_campos jsonb NOT NULL DEFAULT '{}'::jsonb",
    # Clasificación (2026-10-18): categoría, «por revisar» y el oficio propio al que responde.
    "ALTER TABLE entradas ADD COLUMN IF NOT EXISTS categoria varchar(30) NOT NULL DEFAULT ''",
    "ALTER TABLE entradas ADD COLUMN IF NOT EXISTS requiere_revision boolean NOT NULL DEFAULT false",
    "ALTER TABLE entradas ADD COLUMN IF NOT EXISTS responde_a_documento_id integer",
    "CREATE INDEX IF NOT EXISTS entradas_responde_a ON entradas (responde_a_documento_id)",
)


async def obtener_sesion_punku() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI: una sesión de la base de la Mesa de Partes, siempre cerrada."""
    async with SesionPunku() as sesion:
        yield sesion


class SinSeparar(SystemExit):
    """Su base propia está vacía y la documental aún tiene lo recibido: arrancar así sembraría una Mesa de Partes nueva."""


async def _cuenta(conexion, tabla: str) -> int:
    if not (await conexion.execute(text(f"SELECT to_regclass('{tabla}')"))).scalar():
        return 0
    return (await conexion.execute(text(f"SELECT count(*) FROM {tabla}"))).scalar() or 0


async def _sin_separar() -> bool:
    """¿Su base es otra, está vacía y la documental aún tiene recibidos o trámites? Solo si DATABASE_URL está definida
    (sola, no)."""
    import os

    from punku.config import config

    if not config.punku_database_url or "DATABASE_URL" not in os.environ or config.punku_database_url == config.database_url:
        return False
    try:
        async with motor.connect() as c:
            if await _cuenta(c, "entradas") or await _cuenta(c, "mesa_tramites"):
                return False
        documental = create_async_engine(config.database_url)
        try:
            async with documental.connect() as c:
                return bool(await _cuenta(c, "entradas") or await _cuenta(c, "mesa_tramites"))
        finally:
            await documental.dispose()
    except Exception:  # noqa: BLE001 — sin la documental a la vista no hay nada que proteger
        return False


async def preparar() -> None:
    """Su base (si falta), sus tablas, sus migraciones y, en la misma base que la plataforma, su ajuste (idempotente).
    Se NIEGA a arrancar sobre su base propia vacía si la documental aún tiene sus datos (separe primero)."""
    from tiqsi.sql import crear_base_si_falta

    from punku.modelos import BasePunku

    await crear_base_si_falta(motor.url)
    if await _sin_separar():
        raise SinSeparar("La base de la Mesa de Partes está vacía y la documental aún tiene lo recibido: sepárela "
                         "primero (python -m punku.db separar --aplicar).")
    async with motor.begin() as conexion:
        await conexion.run_sync(BasePunku.metadata.create_all)
        for sql in MIGRACIONES:
            await conexion.execute(text(sql))
        if (await conexion.execute(text("SELECT to_regclass('ajustes')"))).scalar():
            await conexion.execute(text(
                "INSERT INTO punku_ajustes (clave, valor) SELECT clave, valor FROM ajustes "
                "WHERE despacho_id = 1 AND clave = ANY(:claves) ON CONFLICT (clave) DO NOTHING"), {"claves": list(AJUSTES)})


async def separar(aplicar: bool = False) -> dict:
    """Sus tablas, de la base documental (DATABASE_URL) a la suya (PUNKU_DATABASE_URL), y su ajuste."""
    import json

    from tiqsi.sql import crear_base_si_falta, separar as separar_tablas

    from punku.modelos import BasePunku
    from punku.config import config

    if not config.punku_database_url:
        raise SystemExit("Falta PUNKU_DATABASE_URL (la base propia de la Mesa de Partes).")
    if aplicar:
        await crear_base_si_falta(motor.url)
    plan = await separar_tablas(config.database_url, config.punku_database_url, BasePunku.metadata, aplicar=aplicar)
    origen = create_async_engine(config.database_url)
    try:
        async with origen.connect() as o:
            ajustes = ((await o.execute(text("SELECT clave, valor FROM ajustes WHERE despacho_id = 1 AND clave = ANY(:c) ORDER BY clave"),
                                        {"c": list(AJUSTES)})).all()
                       if (await o.execute(text("SELECT to_regclass('ajustes')"))).scalar() else [])
        plan["(ajustes → punku_ajustes)"] = {"filas": len(ajustes), "huella": "-"}
        if not aplicar:
            return plan
        async with motor.begin() as d:
            for sql in MIGRACIONES:   # los índices que el modelo no declara
                await d.execute(text(sql))
            for clave, valor in ajustes:
                await d.execute(text("INSERT INTO punku_ajustes (clave, valor) VALUES (:c, CAST(:v AS jsonb)) ON CONFLICT (clave) DO NOTHING"),
                                {"c": clave, "v": json.dumps(valor)})
            copiados = (await d.execute(text("SELECT count(*) FROM punku_ajustes WHERE clave = ANY(:c)"), {"c": [a[0] for a in ajustes]})).scalar()
        if copiados != len(ajustes):
            raise SystemExit(f"Solo {copiados} de {len(ajustes)} ajustes llegaron.")
    finally:
        await origen.dispose()
    return plan


def _principal(argv: list[str]) -> int:
    import argparse
    import asyncio

    from tiqsi.sql import ErrorDeSeparacion

    p = argparse.ArgumentParser(prog="python -m punku.db", description="La base propia de la Mesa de Partes.")
    sub = p.add_subparsers(dest="orden", required=True)
    s = sub.add_parser("separar", help="sus tablas a su base (simula sin --aplicar)")
    s.add_argument("--aplicar", action="store_true")
    a = p.parse_args(argv)
    try:
        plan = asyncio.run(separar(a.aplicar))
    except ErrorDeSeparacion as e:
        print(f"[error] {e}")
        return 1
    for tabla, d in plan.items():
        print(f"  {tabla:<30} {d['filas']:>6} filas  {d['huella'][:12]}")
    print("Copiado y verificado." if a.aplicar else "Simulación: nada se copió (--aplicar para hacerlo).")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_principal(sys.argv[1:]))
