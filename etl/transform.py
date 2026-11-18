"""Transformación: saneamiento de datos y armado del modelo estrella."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

log = logging.getLogger(__name__)

TIPOS_OPERACION = {"Compra", "Venta", "Suscripcion", "Rescate"}
TIPOS_MOVIMIENTO = {"Deposito", "Retiro"}


@dataclass
class ReporteCalidad:
    """Registra qué se corrigió o descartó en cada tabla."""

    tablas: dict[str, dict[str, int]] = field(default_factory=dict)

    def registrar(self, tabla: str, regla: str, filas: int) -> None:
        self.tablas.setdefault(tabla, {})[regla] = int(filas)


# --------------------------------------------------------------------------
# Funciones de limpieza reutilizables
# --------------------------------------------------------------------------
def parsear_fechas(serie: pd.Series) -> pd.Series:
    """Acepta AAAA-MM-DD y DD/MM/AAAA. Lo que no se pueda leer queda como NaT."""
    iso = pd.to_datetime(serie, format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(serie, format="%d/%m/%Y", errors="coerce")
    return iso.fillna(dmy)


def normalizar_ticker(serie: pd.Series) -> pd.Series:
    return serie.astype("string").str.strip().str.upper()


def normalizar_categoria(serie: pd.Series) -> pd.Series:
    """'DEPOSITO', ' deposito ' -> 'Deposito'."""
    return serie.astype("string").str.strip().str.capitalize()


def a_numero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie, errors="coerce")


# --------------------------------------------------------------------------
# Dimensiones
# --------------------------------------------------------------------------
def construir_dim_fecha(desde: pd.Timestamp, hasta: pd.Timestamp) -> pd.DataFrame:
    fechas = pd.date_range(desde, hasta, freq="D")
    nombres_mes = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
        "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ]
    return pd.DataFrame(
        {
            "fecha_id": fechas.strftime("%Y%m%d").astype(int),
            "fecha": fechas.strftime("%Y-%m-%d"),
            "anio": fechas.year,
            "trimestre": fechas.quarter,
            "mes": fechas.month,
            "nombre_mes": [nombres_mes[m - 1] for m in fechas.month],
            "anio_mes": fechas.strftime("%Y-%m"),
            "dia_semana": fechas.dayofweek + 1,  # 1 = lunes
            "es_dia_habil": (fechas.dayofweek < 5).astype(int),
        }
    )


def limpiar_clientes(df: pd.DataFrame, rep: ReporteCalidad) -> pd.DataFrame:
    rep.registrar("clientes", "filas_entrada", len(df))
    out = df.drop_duplicates(subset="cliente_id").copy()
    rep.registrar("clientes", "duplicados_eliminados", len(df) - len(out))
    out["fecha_alta"] = parsear_fechas(out["fecha_alta"]).dt.strftime("%Y-%m-%d")
    out["ingreso_mensual_declarado_ars"] = a_numero(out["ingreso_mensual_declarado_ars"])
    rep.registrar("clientes", "filas_salida", len(out))
    return out


def limpiar_instrumentos(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ticker"] = normalizar_ticker(out["ticker"])
    return out.drop_duplicates(subset="ticker")


# --------------------------------------------------------------------------
# Tipo de cambio
# --------------------------------------------------------------------------
def preparar_tipo_cambio(df: pd.DataFrame, dim_fecha: pd.DataFrame) -> pd.DataFrame:
    """Lleva el tipo de cambio a todos los días del calendario.

    Fines de semana y feriados toman la última cotización disponible.
    """
    tc = df.copy()
    tc["fecha"] = parsear_fechas(tc["fecha"])
    tc["cotizacion"] = a_numero(tc["cotizacion"])
    tc = tc.dropna(subset=["fecha", "cotizacion"]).sort_values("fecha")

    calendario = pd.DataFrame({"fecha": pd.to_datetime(dim_fecha["fecha"])}).sort_values("fecha")
    completo = pd.merge_asof(calendario, tc[["fecha", "cotizacion"]], on="fecha", direction="backward")
    completo["cotizacion"] = completo["cotizacion"].bfill()  # primeros días sin dato previo
    completo["fecha_id"] = completo["fecha"].dt.strftime("%Y%m%d").astype(int)
    completo["moneda"] = "USD"
    return completo[["fecha_id", "moneda", "cotizacion"]]


def convertir_montos(df: pd.DataFrame, tc: pd.DataFrame, col_monto: str = "monto") -> pd.DataFrame:
    """Agrega monto_ars y monto_usd usando el tipo de cambio del día."""
    out = df.merge(tc[["fecha_id", "cotizacion"]], on="fecha_id", how="left")
    es_usd = out["moneda"] == "USD"
    out["monto_ars"] = out[col_monto].where(~es_usd, out[col_monto] * out["cotizacion"]).round(2)
    out["monto_usd"] = out[col_monto].where(es_usd, out[col_monto] / out["cotizacion"]).round(2)
    return out.drop(columns=["cotizacion"])


# --------------------------------------------------------------------------
# Hechos
# --------------------------------------------------------------------------
def limpiar_operaciones(
    df: pd.DataFrame,
    clientes: pd.DataFrame,
    instrumentos: pd.DataFrame,
    rep: ReporteCalidad,
) -> pd.DataFrame:
    tabla = "operaciones"
    rep.registrar(tabla, "filas_entrada", len(df))

    out = df.drop_duplicates(subset="operacion_id").copy()
    rep.registrar(tabla, "duplicados_eliminados", len(df) - len(out))

    out["fecha"] = parsear_fechas(out["fecha"])
    rep.registrar(tabla, "fechas_formato_alternativo_corregidas",
                  (~df["fecha"].str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)).sum())
    sin_fecha = out["fecha"].isna()
    rep.registrar(tabla, "fechas_invalidas_descartadas", sin_fecha.sum())
    out = out[~sin_fecha]

    ticker_original = out["ticker"].copy()
    out["ticker"] = normalizar_ticker(out["ticker"])
    rep.registrar(tabla, "tickers_normalizados", (ticker_original != out["ticker"]).sum())

    huerfanos = ~out["cliente_id"].isin(clientes["cliente_id"])
    rep.registrar(tabla, "clientes_inexistentes_descartados", huerfanos.sum())
    out = out[~huerfanos]

    ticker_invalido = ~out["ticker"].isin(instrumentos["ticker"])
    rep.registrar(tabla, "tickers_inexistentes_descartados", ticker_invalido.sum())
    out = out[~ticker_invalido]

    for col in ("cantidad", "precio", "monto", "comision"):
        out[col] = a_numero(out[col])

    cantidad_invalida = out["cantidad"].isna() | (out["cantidad"] <= 0) | (out["precio"] <= 0)
    rep.registrar(tabla, "cantidad_o_precio_invalido_descartados", cantidad_invalida.sum())
    out = out[~cantidad_invalida].copy()

    # Si falta el monto pero hay cantidad y precio, se reconstruye (imputación trazable)
    sin_monto = out["monto"].isna()
    out.loc[sin_monto, "monto"] = (out.loc[sin_monto, "cantidad"] * out.loc[sin_monto, "precio"]).round(2)
    rep.registrar(tabla, "montos_recalculados", sin_monto.sum())
    out["comision"] = out["comision"].fillna(0)

    out["tipo_operacion"] = normalizar_categoria(out["tipo_operacion"])
    tipo_invalido = ~out["tipo_operacion"].isin(TIPOS_OPERACION)
    rep.registrar(tabla, "tipo_operacion_invalido_descartados", tipo_invalido.sum())
    out = out[~tipo_invalido].copy()

    out["fecha_id"] = out["fecha"].dt.strftime("%Y%m%d").astype(int)
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    rep.registrar(tabla, "filas_salida", len(out))
    return out


def limpiar_movimientos(df: pd.DataFrame, clientes: pd.DataFrame, rep: ReporteCalidad) -> pd.DataFrame:
    tabla = "movimientos"
    rep.registrar(tabla, "filas_entrada", len(df))

    out = df.drop_duplicates(subset="movimiento_id").copy()
    rep.registrar(tabla, "duplicados_eliminados", len(df) - len(out))

    out["fecha"] = parsear_fechas(out["fecha"])
    sin_fecha = out["fecha"].isna()
    rep.registrar(tabla, "fechas_invalidas_descartadas", sin_fecha.sum())
    out = out[~sin_fecha]

    original = out["tipo_movimiento"].copy()
    out["tipo_movimiento"] = normalizar_categoria(out["tipo_movimiento"])
    rep.registrar(tabla, "tipos_normalizados", (original != out["tipo_movimiento"]).sum())
    tipo_invalido = ~out["tipo_movimiento"].isin(TIPOS_MOVIMIENTO)
    rep.registrar(tabla, "tipo_movimiento_invalido_descartados", tipo_invalido.sum())
    out = out[~tipo_invalido]

    huerfanos = ~out["cliente_id"].isin(clientes["cliente_id"])
    rep.registrar(tabla, "clientes_inexistentes_descartados", huerfanos.sum())
    out = out[~huerfanos].copy()

    out["monto"] = a_numero(out["monto"])
    monto_invalido = out["monto"].isna() | (out["monto"] <= 0)
    rep.registrar(tabla, "montos_invalidos_descartados", monto_invalido.sum())
    out = out[~monto_invalido].copy()

    out["fecha_id"] = out["fecha"].dt.strftime("%Y%m%d").astype(int)
    out["fecha"] = out["fecha"].dt.strftime("%Y-%m-%d")
    rep.registrar(tabla, "filas_salida", len(out))
    return out


def construir_modelo(datos: dict[str, pd.DataFrame], tipo_cambio: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], ReporteCalidad]:
    """Devuelve las tablas del modelo estrella listas para cargar."""
    rep = ReporteCalidad()

    clientes = limpiar_clientes(datos["clientes"], rep)
    instrumentos = limpiar_instrumentos(datos["instrumentos"])
    asesores = datos["asesores"].drop_duplicates(subset="asesor_id")

    operaciones = limpiar_operaciones(datos["operaciones"], clientes, instrumentos, rep)
    movimientos = limpiar_movimientos(datos["movimientos"], clientes, rep)

    fechas = pd.to_datetime(pd.concat([operaciones["fecha"], movimientos["fecha"]]))
    dim_fecha = construir_dim_fecha(fechas.min(), fechas.max())
    tc = preparar_tipo_cambio(tipo_cambio, dim_fecha)

    asesor_por_cliente = clientes[["cliente_id", "asesor_id"]]

    fact_operaciones = convertir_montos(operaciones, tc).merge(asesor_por_cliente, on="cliente_id", how="left")
    fact_operaciones["comision_ars"] = fact_operaciones["comision"].where(
        fact_operaciones["moneda"] != "USD",
        fact_operaciones["comision"] * fact_operaciones["monto_ars"] / fact_operaciones["monto"],
    ).round(2)
    fact_operaciones = fact_operaciones[
        ["operacion_id", "fecha_id", "fecha", "cliente_id", "asesor_id", "ticker", "tipo_operacion",
         "cantidad", "precio", "moneda", "monto", "monto_ars", "monto_usd", "comision_ars"]
    ]

    fact_movimientos = convertir_montos(movimientos, tc).merge(asesor_por_cliente, on="cliente_id", how="left")
    fact_movimientos = fact_movimientos[
        ["movimiento_id", "fecha_id", "fecha", "cliente_id", "asesor_id", "tipo_movimiento",
         "canal", "moneda", "monto", "monto_ars", "monto_usd"]
    ]

    cot = datos["cotizaciones"].copy()
    cot["ticker"] = normalizar_ticker(cot["ticker"])
    cot["fecha_id"] = parsear_fechas(cot["fecha"]).dt.strftime("%Y%m%d").astype(int)
    cot["precio_cierre"] = a_numero(cot["precio_cierre"])
    fact_cotizaciones = cot[["fecha_id", "ticker", "precio_cierre"]].drop_duplicates(["fecha_id", "ticker"])

    tablas = {
        "dim_fecha": dim_fecha,
        "dim_asesor": asesores,
        "dim_cliente": clientes,
        "dim_instrumento": instrumentos,
        "fact_tipo_cambio": tc,
        "fact_cotizaciones": fact_cotizaciones,
        "fact_operaciones": fact_operaciones,
        "fact_movimientos": fact_movimientos,
    }
    for nombre, df in tablas.items():
        log.info("Transformado %-18s %7d filas", nombre, len(df))
    return tablas, rep
