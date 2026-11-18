"""Configuración central del pipeline."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
REPORTS_DIR = ROOT / "reports"
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "inversiones.db"

# API pública de Estadísticas Cambiarias del BCRA (no requiere autenticación)
BCRA_URL = "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/{moneda}"
BCRA_TIMEOUT_SEG = 15

# Parámetros de las alertas de cumplimiento. Se cargan en la tabla `parametros`
# para que las vistas SQL los usen y se puedan ajustar sin tocar código.
# Los valores son de ejemplo: no corresponden a umbrales normativos.
PARAMETROS_ALERTAS = {
    "umbral_reporte_ars": 10_000_000,       # umbral de referencia para depósitos en efectivo
    "fraccionamiento_pct_min": 0.80,         # depósitos entre 80% y 100% del umbral
    "fraccionamiento_ventana_dias": 7,       # ventana de análisis
    "fraccionamiento_min_movimientos": 3,    # cantidad mínima de depósitos en la ventana
    "fuera_perfil_factor": 5,                # depósitos del mes > 5 veces el ingreso declarado
    "ida_vuelta_dias": 3,                    # retiro dentro de N días del depósito
    "ida_vuelta_pct_min": 0.90,              # retiro >= 90% del depósito
    "ida_vuelta_monto_min_ars": 5_000_000,   # solo montos relevantes
}
