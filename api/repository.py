"""Consultas a la base. Separadas de FastAPI para poder testearlas solas.

Todas las consultas usan parámetros (?) para evitar inyección SQL.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

LIMITE_MAXIMO = 10_000


def _filtros(condiciones: dict[str, tuple[str, Any]]) -> tuple[str, list[Any]]:
    """Arma el WHERE solo con los filtros que vienen informados."""
    partes, params = [], []
    for _, (sql, valor) in condiciones.items():
        if valor is not None:
            partes.append(sql)
            params.append(valor)
    where = f"WHERE {' AND '.join(partes)}" if partes else ""
    return where, params


def _consultar(con: sqlite3.Connection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    columnas = [c[0] for c in cur.description]
    return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


def _paginar(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, LIMITE_MAXIMO)), max(0, offset)


def listar_operaciones(
    con: sqlite3.Connection,
    cliente_id: str | None = None,
    ticker: str | None = None,
    tipo_operacion: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limit: int = 1_000,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    where, params = _filtros(
        {
            "cliente": ("o.cliente_id = ?", cliente_id),
            "ticker": ("o.ticker = ?", ticker.upper() if ticker else None),
            "tipo": ("o.tipo_operacion = ?", tipo_operacion),
            "desde": ("o.fecha >= ?", desde),
            "hasta": ("o.fecha <= ?", hasta),
        }
    )
    total = con.execute(f"SELECT COUNT(*) FROM fact_operaciones o {where}", params).fetchone()[0]
    limit, offset = _paginar(limit, offset)
    filas = _consultar(
        con,
        f"""
        SELECT o.operacion_id, o.fecha, o.cliente_id, o.asesor_id, o.ticker,
               i.tipo_instrumento, o.tipo_operacion, o.cantidad, o.precio, o.moneda,
               o.monto, o.monto_ars, o.monto_usd, o.comision_ars
        FROM fact_operaciones o
        JOIN dim_instrumento i ON i.ticker = o.ticker
        {where}
        ORDER BY o.fecha, o.operacion_id
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    )
    return total, filas


def listar_movimientos(
    con: sqlite3.Connection,
    cliente_id: str | None = None,
    tipo_movimiento: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    limit: int = 1_000,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    where, params = _filtros(
        {
            "cliente": ("cliente_id = ?", cliente_id),
            "tipo": ("tipo_movimiento = ?", tipo_movimiento),
            "desde": ("fecha >= ?", desde),
            "hasta": ("fecha <= ?", hasta),
        }
    )
    total = con.execute(f"SELECT COUNT(*) FROM fact_movimientos {where}", params).fetchone()[0]
    limit, offset = _paginar(limit, offset)
    filas = _consultar(
        con,
        f"SELECT * FROM fact_movimientos {where} ORDER BY fecha, movimiento_id LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return total, filas


def kpis_mensuales(
    con: sqlite3.Connection, desde_mes: str | None = None, hasta_mes: str | None = None
) -> list[dict[str, Any]]:
    where, params = _filtros(
        {"desde": ("anio_mes >= ?", desde_mes), "hasta": ("anio_mes <= ?", hasta_mes)}
    )
    return _consultar(con, f"SELECT * FROM vw_kpis_mensuales {where} ORDER BY anio_mes", params)


def ranking_asesores(con: sqlite3.Connection, anio_mes: str | None = None) -> list[dict[str, Any]]:
    if anio_mes is None:  # por defecto, el último mes disponible
        anio_mes = con.execute("SELECT MAX(anio_mes) FROM vw_ranking_asesores").fetchone()[0]
    return _consultar(
        con,
        "SELECT * FROM vw_ranking_asesores WHERE anio_mes = ? ORDER BY ranking_comisiones",
        [anio_mes],
    )


def listar_alertas(
    con: sqlite3.Connection, tipo_alerta: str | None = None, asesor_id: str | None = None
) -> list[dict[str, Any]]:
    where, params = _filtros(
        {"tipo": ("tipo_alerta = ?", tipo_alerta), "asesor": ("asesor_id = ?", asesor_id)}
    )
    return _consultar(
        con, f"SELECT * FROM vw_alertas {where} ORDER BY monto_total_ars DESC", params
    )


def a_csv(filas: list[dict[str, Any]]) -> str:
    """Convierte filas a CSV (con encabezado) para descarga."""
    buffer = io.StringIO()
    if filas:
        writer = csv.DictWriter(buffer, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)
    return buffer.getvalue()
