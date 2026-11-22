"""API REST para consultar y descargar los datos del modelo.

Levantar:
    uvicorn api.main:app --reload

Documentación interactiva:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response

from api import repository as repo
from etl.config import DB_PATH

FECHA = r"^\d{4}-\d{2}-\d{2}$"
MES = r"^\d{4}-\d{2}$"

app = FastAPI(
    title="API de datos de inversiones",
    description=(
        "Consulta y descarga de operaciones, movimientos de fondos, KPIs comerciales "
        "y alertas de cumplimiento. Datos simulados."
    ),
    version="1.0.0",
)


def get_conexion() -> Iterator[sqlite3.Connection]:
    """Abre la base en modo solo lectura para cada request."""
    if not DB_PATH.exists():
        raise HTTPException(503, "La base no existe. Corré primero: python -m etl.pipeline")
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    try:
        yield con
    finally:
        con.close()


def responder(
    filas: list[dict[str, Any]],
    formato: str,
    nombre_archivo: str,
    total: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
):
    if formato == "csv":
        return Response(
            content=repo.a_csv(filas),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}.csv"'},
        )
    if total is None:
        return {"cantidad": len(filas), "datos": filas}
    return {"total": total, "limit": limit, "offset": offset, "cantidad": len(filas), "datos": filas}


@app.get("/health", tags=["Estado"])
def health(con: sqlite3.Connection = Depends(get_conexion)):
    ultima = con.execute(
        "SELECT fin, fuente_tipo_cambio, estado FROM log_ejecuciones ORDER BY ejecucion_id DESC LIMIT 1"
    ).fetchone()
    return {
        "estado": "ok",
        "ultima_carga": dict(zip(["fin", "fuente_tipo_cambio", "estado"], ultima)) if ultima else None,
    }


@app.get("/operaciones", tags=["Descargas"])
def operaciones(
    cliente_id: str | None = None,
    ticker: str | None = None,
    tipo_operacion: Literal["Compra", "Venta", "Suscripcion", "Rescate"] | None = None,
    desde: str | None = Query(None, pattern=FECHA, description="AAAA-MM-DD"),
    hasta: str | None = Query(None, pattern=FECHA, description="AAAA-MM-DD"),
    formato: Literal["json", "csv"] = "json",
    limit: int = Query(1_000, ge=1, le=repo.LIMITE_MAXIMO),
    offset: int = Query(0, ge=0),
    con: sqlite3.Connection = Depends(get_conexion),
):
    total, filas = repo.listar_operaciones(con, cliente_id, ticker, tipo_operacion, desde, hasta, limit, offset)
    return responder(filas, formato, "operaciones", total, limit, offset)


@app.get("/movimientos", tags=["Descargas"])
def movimientos(
    cliente_id: str | None = None,
    tipo_movimiento: Literal["Deposito", "Retiro"] | None = None,
    desde: str | None = Query(None, pattern=FECHA, description="AAAA-MM-DD"),
    hasta: str | None = Query(None, pattern=FECHA, description="AAAA-MM-DD"),
    formato: Literal["json", "csv"] = "json",
    limit: int = Query(1_000, ge=1, le=repo.LIMITE_MAXIMO),
    offset: int = Query(0, ge=0),
    con: sqlite3.Connection = Depends(get_conexion),
):
    total, filas = repo.listar_movimientos(con, cliente_id, tipo_movimiento, desde, hasta, limit, offset)
    return responder(filas, formato, "movimientos", total, limit, offset)


@app.get("/kpis/mensuales", tags=["KPIs comerciales"])
def kpis_mensuales(
    desde_mes: str | None = Query(None, pattern=MES, description="AAAA-MM"),
    hasta_mes: str | None = Query(None, pattern=MES, description="AAAA-MM"),
    formato: Literal["json", "csv"] = "json",
    con: sqlite3.Connection = Depends(get_conexion),
):
    return responder(repo.kpis_mensuales(con, desde_mes, hasta_mes), formato, "kpis_mensuales")


@app.get("/kpis/asesores", tags=["KPIs comerciales"])
def kpis_asesores(
    anio_mes: str | None = Query(None, pattern=MES, description="AAAA-MM (por defecto, el último mes)"),
    formato: Literal["json", "csv"] = "json",
    con: sqlite3.Connection = Depends(get_conexion),
):
    return responder(repo.ranking_asesores(con, anio_mes), formato, "ranking_asesores")


@app.get("/alertas", tags=["Cumplimiento"])
def alertas(
    tipo_alerta: Literal[
        "Fraccionamiento de depositos en efectivo",
        "Depositos fuera de perfil",
        "Ida y vuelta de fondos",
    ] | None = None,
    asesor_id: str | None = None,
    formato: Literal["json", "csv"] = "json",
    con: sqlite3.Connection = Depends(get_conexion),
):
    return responder(repo.listar_alertas(con, tipo_alerta, asesor_id), formato, "alertas")
