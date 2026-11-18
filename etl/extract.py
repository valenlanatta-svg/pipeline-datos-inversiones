"""Extracción: archivos de los sistemas operativos y API del BCRA."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from etl.config import BCRA_TIMEOUT_SEG, BCRA_URL, RAW_DIR

log = logging.getLogger(__name__)

ARCHIVOS = [
    "asesores",
    "instrumentos",
    "clientes",
    "cotizaciones",
    "operaciones",
    "movimientos",
    "tipo_cambio",
]


def leer_archivos(raw_dir: Path = RAW_DIR) -> dict[str, pd.DataFrame]:
    """Lee los CSV crudos. Todo como texto: los tipos se validan en transform."""
    datos = {}
    for nombre in ARCHIVOS:
        ruta = raw_dir / f"{nombre}.csv"
        if not ruta.exists():
            raise FileNotFoundError(
                f"No existe {ruta}. Corré primero: python scripts/generate_data.py"
            )
        datos[nombre] = pd.read_csv(ruta, dtype=str)
        log.info("Extraído %-13s %7d filas", nombre, len(datos[nombre]))
    return datos


def parsear_respuesta_bcra(payload: dict, moneda: str = "USD") -> pd.DataFrame:
    """Convierte la respuesta de la API del BCRA en un DataFrame fecha/moneda/cotizacion."""
    resultados = payload.get("results") or []
    if isinstance(resultados, dict):  # el endpoint por fecha devuelve un objeto
        resultados = [resultados]
    filas = []
    for item in resultados:
        for det in item.get("detalle") or []:
            if det.get("codigoMoneda", moneda) == moneda and det.get("tipoCotizacion"):
                filas.append(
                    {"fecha": item["fecha"], "moneda": moneda, "cotizacion": float(det["tipoCotizacion"])}
                )
    return pd.DataFrame(filas, columns=["fecha", "moneda", "cotizacion"])


def obtener_tipo_cambio_bcra(desde: date, hasta: date, moneda: str = "USD") -> pd.DataFrame:
    """Descarga el tipo de cambio oficial publicado por el BCRA."""
    respuesta = requests.get(
        BCRA_URL.format(moneda=moneda),
        params={"fechadesde": desde.isoformat(), "fechahasta": hasta.isoformat()},
        timeout=BCRA_TIMEOUT_SEG,
    )
    respuesta.raise_for_status()
    df = parsear_respuesta_bcra(respuesta.json(), moneda)
    if df.empty:
        raise ValueError("La API del BCRA no devolvió cotizaciones para el rango pedido")
    return df


def obtener_tipo_cambio(
    archivo_respaldo: pd.DataFrame, desde: date, hasta: date, usar_api: bool = True
) -> tuple[pd.DataFrame, str]:
    """Intenta la API del BCRA y, si falla, usa el archivo local como respaldo.

    Devuelve el DataFrame y la fuente utilizada ("api_bcra" o "archivo_local").
    """
    if usar_api:
        try:
            df = obtener_tipo_cambio_bcra(desde, hasta)
            log.info("Tipo de cambio obtenido de la API del BCRA (%d fechas)", len(df))
            return df, "api_bcra"
        except Exception as exc:  # red caída, timeout, cambio de formato, etc.
            log.warning("No se pudo usar la API del BCRA (%s). Uso archivo local.", exc)
    return archivo_respaldo, "archivo_local"
