"""Carga: SQLite con upsert idempotente (equivalente a MERGE)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from etl.config import SQL_DIR

log = logging.getLogger(__name__)

# Clave primaria de cada tabla, usada para el upsert
CLAVES = {
    "dim_fecha": ["fecha_id"],
    "dim_asesor": ["asesor_id"],
    "dim_cliente": ["cliente_id"],
    "dim_instrumento": ["ticker"],
    "fact_tipo_cambio": ["fecha_id", "moneda"],
    "fact_cotizaciones": ["fecha_id", "ticker"],
    "fact_operaciones": ["operacion_id"],
    "fact_movimientos": ["movimiento_id"],
}

# Orden de carga: primero dimensiones, después hechos (integridad referencial)
ORDEN_CARGA = list(CLAVES)


def conectar(db_path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def crear_esquema(con: sqlite3.Connection, sql_dir: Path = SQL_DIR) -> None:
    con.executescript((sql_dir / "schema.sql").read_text(encoding="utf-8"))


def crear_vistas(con: sqlite3.Connection, sql_dir: Path = SQL_DIR) -> None:
    con.executescript((sql_dir / "views.sql").read_text(encoding="utf-8"))


def cargar_parametros(con: sqlite3.Connection, parametros: dict[str, float]) -> None:
    con.executemany(
        "INSERT INTO parametros (nombre, valor) VALUES (?, ?) "
        "ON CONFLICT (nombre) DO UPDATE SET valor = excluded.valor",
        list(parametros.items()),
    )


def upsert(con: sqlite3.Connection, tabla: str, df: pd.DataFrame, claves: list[str]) -> int:
    """Inserta filas nuevas y actualiza las existentes según la clave primaria.

    Es el equivalente en SQLite de un MERGE: correr el pipeline dos veces con
    los mismos datos no duplica filas.
    """
    if df.empty:
        return 0
    columnas = list(df.columns)
    actualizables = [c for c in columnas if c not in claves]
    set_clause = ", ".join(f"{c} = excluded.{c}" for c in actualizables) or None
    sql = (
        f"INSERT INTO {tabla} ({', '.join(columnas)}) "
        f"VALUES ({', '.join('?' for _ in columnas)}) "
        f"ON CONFLICT ({', '.join(claves)}) "
        + (f"DO UPDATE SET {set_clause}" if set_clause else "DO NOTHING")
    )
    registros = df.astype(object).where(df.notna(), None).itertuples(index=False, name=None)
    con.executemany(sql, list(registros))
    return len(df)


def cargar_modelo(con: sqlite3.Connection, tablas: dict[str, pd.DataFrame]) -> dict[str, int]:
    resumen = {}
    with con:  # una sola transacción: si algo falla, no queda una carga a medias
        for tabla in ORDEN_CARGA:
            resumen[tabla] = upsert(con, tabla, tablas[tabla], CLAVES[tabla])
            log.info("Cargado %-18s %7d filas", tabla, resumen[tabla])
    return resumen


def exportar_para_power_bi(con: sqlite3.Connection, destino: Path) -> list[Path]:
    """Exporta tablas y vistas a CSV para importarlas en Power BI."""
    destino.mkdir(parents=True, exist_ok=True)
    objetos = ORDEN_CARGA + ["vw_kpis_mensuales", "vw_ranking_asesores", "vw_alertas"]
    rutas = []
    for nombre in objetos:
        ruta = destino / f"{nombre}.csv"
        pd.read_sql_query(f"SELECT * FROM {nombre}", con).to_csv(ruta, index=False)
        rutas.append(ruta)
    log.info("Exportados %d archivos para Power BI en %s", len(rutas), destino)
    return rutas
