"""Fixtures compartidas: una base chica construida desde cero en cada test."""

import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from etl import load  # noqa: E402
from etl.config import PARAMETROS_ALERTAS  # noqa: E402


def _tablas_minimas() -> dict[str, pd.DataFrame]:
    fechas = pd.date_range("2026-03-01", "2026-03-31", freq="D")
    dim_fecha = pd.DataFrame(
        {
            "fecha_id": fechas.strftime("%Y%m%d").astype(int),
            "fecha": fechas.strftime("%Y-%m-%d"),
            "anio": fechas.year,
            "trimestre": fechas.quarter,
            "mes": fechas.month,
            "nombre_mes": "Marzo",
            "anio_mes": fechas.strftime("%Y-%m"),
            "dia_semana": fechas.dayofweek + 1,
            "es_dia_habil": (fechas.dayofweek < 5).astype(int),
        }
    )
    asesores = pd.DataFrame([{"asesor_id": "A001", "nombre": "Asesor 01", "equipo": "Retail CABA"}])
    clientes = pd.DataFrame(
        [
            {"cliente_id": c, "tipo_persona": "Persona humana", "segmento": "Retail",
             "perfil_riesgo": "Moderado", "provincia": "CABA", "fecha_alta": "2025-01-01",
             "ingreso_mensual_declarado_ars": ingreso, "asesor_id": "A001"}
            for c, ingreso in [("C1", 2_000_000), ("C2", 2_000_000), ("C3", 50_000_000)]
        ]
    )
    instrumentos = pd.DataFrame(
        [{"ticker": "AAPL", "nombre": "CEDEAR Apple", "tipo_instrumento": "CEDEAR", "moneda": "ARS"}]
    )

    def mov(i, fecha, cliente, tipo, monto, canal="Transferencia"):
        return {"movimiento_id": f"M{i}", "fecha_id": int(fecha.replace("-", "")), "fecha": fecha,
                "cliente_id": cliente, "asesor_id": "A001", "tipo_movimiento": tipo, "canal": canal,
                "moneda": "ARS", "monto": monto, "monto_ars": monto, "monto_usd": monto / 1_400}

    movimientos = pd.DataFrame(
        [
            # C1: fraccionamiento (4 depósitos en efectivo apenas debajo de 10M en 4 días)
            mov(1, "2026-03-02", "C1", "Deposito", 9_500_000, "Efectivo"),
            mov(2, "2026-03-03", "C1", "Deposito", 9_700_000, "Efectivo"),
            mov(3, "2026-03-04", "C1", "Deposito", 9_100_000, "Efectivo"),
            mov(4, "2026-03-05", "C1", "Deposito", 9_900_000, "Efectivo"),
            # C2: ida y vuelta (deposita 30M y retira 29M al día siguiente)
            mov(5, "2026-03-10", "C2", "Deposito", 30_000_000),
            mov(6, "2026-03-11", "C2", "Retiro", 29_000_000),
            # C3: cliente corporativo con movimientos normales para su perfil
            mov(7, "2026-03-12", "C3", "Deposito", 8_000_000),
            mov(8, "2026-03-20", "C3", "Retiro", 1_000_000),
        ]
    )
    operaciones = pd.DataFrame(
        [
            {"operacion_id": "OP1", "fecha_id": 20260302, "fecha": "2026-03-02", "cliente_id": "C1",
             "asesor_id": "A001", "ticker": "AAPL", "tipo_operacion": "Compra", "cantidad": 10,
             "precio": 17_000, "moneda": "ARS", "monto": 170_000, "monto_ars": 170_000,
             "monto_usd": 121.43, "comision_ars": 850},
            {"operacion_id": "OP2", "fecha_id": 20260315, "fecha": "2026-03-15", "cliente_id": "C3",
             "asesor_id": "A001", "ticker": "AAPL", "tipo_operacion": "Venta", "cantidad": 5,
             "precio": 18_000, "moneda": "ARS", "monto": 90_000, "monto_ars": 90_000,
             "monto_usd": 64.29, "comision_ars": 450},
        ]
    )
    tc = pd.DataFrame({"fecha_id": dim_fecha["fecha_id"], "moneda": "USD", "cotizacion": 1_400.0})
    cot = pd.DataFrame({"fecha_id": dim_fecha["fecha_id"], "ticker": "AAPL", "precio_cierre": 17_000.0})
    return {
        "dim_fecha": dim_fecha, "dim_asesor": asesores, "dim_cliente": clientes,
        "dim_instrumento": instrumentos, "fact_tipo_cambio": tc, "fact_cotizaciones": cot,
        "fact_operaciones": operaciones, "fact_movimientos": movimientos,
    }


@pytest.fixture
def tablas():
    return _tablas_minimas()


@pytest.fixture
def con(tablas):
    conexion = sqlite3.connect(":memory:", check_same_thread=False)  # la API de prueba corre en otro hilo
    load.crear_esquema(conexion)
    load.cargar_parametros(conexion, PARAMETROS_ALERTAS)
    load.cargar_modelo(conexion, tablas)
    load.crear_vistas(conexion)
    yield conexion
    conexion.close()
