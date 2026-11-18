"""Orquestador del pipeline ETL.

Uso:
    python -m etl.pipeline                  # intenta la API del BCRA, con respaldo local
    python -m etl.pipeline --sin-api        # usa solo archivos locales
    python -m etl.pipeline --db otra.db     # otra base de destino
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path

from etl import extract, load, transform
from etl.config import DB_PATH, PARAMETROS_ALERTAS, PROCESSED_DIR, RAW_DIR, REPORTS_DIR

log = logging.getLogger("pipeline")


def ejecutar(
    db_path: Path = DB_PATH,
    raw_dir: Path = RAW_DIR,
    usar_api: bool = True,
    exportar: bool = True,
) -> dict:
    inicio = datetime.now()
    log.info("=== Inicio del pipeline ===")

    # 1. Extracción
    datos = extract.leer_archivos(raw_dir)
    fechas_tc = datos["tipo_cambio"]["fecha"]
    tipo_cambio, fuente_tc = extract.obtener_tipo_cambio(
        datos["tipo_cambio"],
        desde=date.fromisoformat(fechas_tc.min()),
        hasta=date.fromisoformat(fechas_tc.max()),
        usar_api=usar_api,
    )

    # 2. Transformación
    tablas, reporte = transform.construir_modelo(datos, tipo_cambio)

    # 3. Carga
    con = load.conectar(db_path)
    try:
        load.crear_esquema(con)
        load.cargar_parametros(con, PARAMETROS_ALERTAS)
        cargadas = load.cargar_modelo(con, tablas)
        load.crear_vistas(con)

        alertas = dict(
            con.execute("SELECT tipo_alerta, COUNT(*) FROM vw_alertas GROUP BY tipo_alerta").fetchall()
        )
        with con:
            con.execute(
                "INSERT INTO log_ejecuciones (inicio, fin, fuente_tipo_cambio, filas_operaciones, "
                "filas_movimientos, estado) VALUES (?, ?, ?, ?, ?, 'OK')",
                (inicio.isoformat(timespec="seconds"), datetime.now().isoformat(timespec="seconds"),
                 fuente_tc, cargadas["fact_operaciones"], cargadas["fact_movimientos"]),
            )
        if exportar:
            load.exportar_para_power_bi(con, PROCESSED_DIR)
    finally:
        con.close()

    resultado = {
        "ejecutado": inicio.isoformat(timespec="seconds"),
        "fuente_tipo_cambio": fuente_tc,
        "filas_cargadas": cargadas,
        "calidad_de_datos": reporte.tablas,
        "alertas_generadas": alertas,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "calidad_datos.json").write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    log.info("Alertas generadas: %s", alertas)
    log.info("=== Pipeline finalizado en %.1f s ===", (datetime.now() - inicio).total_seconds())
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline ETL de operaciones de inversión")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="Ruta de la base SQLite")
    parser.add_argument("--sin-api", action="store_true", help="No consultar la API del BCRA")
    parser.add_argument("--sin-exportar", action="store_true", help="No exportar CSV para Power BI")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    ejecutar(db_path=args.db, usar_api=not args.sin_api, exportar=not args.sin_exportar)


if __name__ == "__main__":
    main()
