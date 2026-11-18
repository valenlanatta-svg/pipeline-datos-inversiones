"""
Genera datos SIMULADOS de una casa de inversión (ALyC) para el pipeline.

Incluye a propósito:
  - Problemas de calidad de datos (duplicados, fechas en distintos formatos,
    tickers mal escritos, montos nulos, clientes inexistentes) para que el ETL
    tenga algo real que sanear.
  - Patrones de operaciones inusuales (fraccionamiento de depósitos,
    movimientos fuera de perfil y "ida y vuelta" de fondos) para las alertas.

Ningún dato corresponde a personas o clientes reales.

Uso:
    python scripts/generate_data.py
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
FECHA_INICIO = date(2025, 11, 1)
FECHA_FIN = date(2026, 10, 31)
N_CLIENTES = 1_500
N_OPERACIONES = 45_000
N_MOVIMIENTOS = 9_000

# Umbral de ejemplo para el reporte de operaciones en efectivo (configurable,
# no es un valor normativo).
UMBRAL_REPORTE_ARS = 10_000_000

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

rng = np.random.default_rng(SEED)


# --------------------------------------------------------------------------
# Dimensiones
# --------------------------------------------------------------------------
def dias_habiles(inicio: date, fin: date) -> list[date]:
    dias = pd.bdate_range(inicio, fin)
    return [d.date() for d in dias]


def generar_asesores() -> pd.DataFrame:
    equipos = ["Retail CABA", "Retail Interior", "Banca Privada", "Corporativo"]
    filas = []
    for i in range(1, 13):
        filas.append(
            {
                "asesor_id": f"A{i:03d}",
                "nombre": f"Asesor {i:02d}",
                "equipo": equipos[(i - 1) % len(equipos)],
            }
        )
    return pd.DataFrame(filas)


def generar_instrumentos() -> pd.DataFrame:
    filas = [
        # ticker, nombre, tipo, moneda, precio_inicial
        ("AAPL", "CEDEAR Apple", "CEDEAR", "ARS", 17_000),
        ("MSFT", "CEDEAR Microsoft", "CEDEAR", "ARS", 18_500),
        ("NVDA", "CEDEAR NVIDIA", "CEDEAR", "ARS", 9_800),
        ("MELI", "CEDEAR MercadoLibre", "CEDEAR", "ARS", 21_000),
        ("KO", "CEDEAR Coca-Cola", "CEDEAR", "ARS", 15_200),
        ("GOOGL", "CEDEAR Alphabet", "CEDEAR", "ARS", 4_300),
        ("AMZN", "CEDEAR Amazon", "CEDEAR", "ARS", 1_950),
        ("SPY", "CEDEAR SPDR S&P 500", "CEDEAR", "ARS", 36_000),
        ("GGAL", "Grupo Financiero Galicia", "Accion", "ARS", 6_200),
        ("YPFD", "YPF", "Accion", "ARS", 38_000),
        ("PAMP", "Pampa Energia", "Accion", "ARS", 3_400),
        ("BMA", "Banco Macro", "Accion", "ARS", 9_900),
        ("AL30", "Bono Soberano AL30", "Bono", "ARS", 82_000),
        ("GD30", "Bono Soberano GD30", "Bono", "ARS", 85_500),
        ("GD35", "Bono Soberano GD35", "Bono", "ARS", 74_000),
        ("GD38", "Bono Soberano GD38", "Bono", "ARS", 79_000),
        ("ON-ENERGIA-27", "Obligacion Negociable Energia 2027 (simulada)", "ON", "USD", 101),
        ("ON-TELCO-28", "Obligacion Negociable Telco 2028 (simulada)", "ON", "USD", 98),
        ("FCI-MM", "FCI Money Market (simulado)", "FCI", "ARS", 120),
        ("FCI-RF", "FCI Renta Fija T+1 (simulado)", "FCI", "ARS", 85),
        ("FCI-USD", "FCI Renta Fija Dolar (simulado)", "FCI", "USD", 1.15),
        ("CAUCION", "Caucion Bursatil", "Caucion", "ARS", 1),
    ]
    return pd.DataFrame(
        filas, columns=["ticker", "nombre", "tipo_instrumento", "moneda", "precio_inicial"]
    )


def generar_clientes(asesores: pd.DataFrame) -> pd.DataFrame:
    provincias = ["CABA", "Buenos Aires", "Cordoba", "Santa Fe", "Mendoza", "Neuquen", "Tucuman"]
    prob_prov = [0.38, 0.27, 0.11, 0.10, 0.06, 0.05, 0.03]
    tipo = rng.choice(["Persona humana", "Persona juridica"], N_CLIENTES, p=[0.92, 0.08])
    segmento = np.where(
        tipo == "Persona juridica",
        "Corporativo",
        rng.choice(["Retail", "Premium"], N_CLIENTES, p=[0.8, 0.2]),
    )
    ingreso_base = np.where(
        segmento == "Corporativo",
        rng.lognormal(mean=np.log(60_000_000), sigma=0.6, size=N_CLIENTES),
        np.where(
            segmento == "Premium",
            rng.lognormal(mean=np.log(9_000_000), sigma=0.5, size=N_CLIENTES),
            rng.lognormal(mean=np.log(1_800_000), sigma=0.5, size=N_CLIENTES),
        ),
    )
    alta_offsets = rng.integers(0, 3 * 365, N_CLIENTES)
    fecha_alta = [FECHA_FIN - timedelta(days=int(o)) for o in alta_offsets]
    return pd.DataFrame(
        {
            "cliente_id": [f"C{i:05d}" for i in range(1, N_CLIENTES + 1)],
            "tipo_persona": tipo,
            "segmento": segmento,
            "perfil_riesgo": rng.choice(
                ["Conservador", "Moderado", "Agresivo"], N_CLIENTES, p=[0.45, 0.4, 0.15]
            ),
            "provincia": rng.choice(provincias, N_CLIENTES, p=prob_prov),
            "fecha_alta": [d.isoformat() for d in fecha_alta],
            "ingreso_mensual_declarado_ars": ingreso_base.round(-3),
            "asesor_id": rng.choice(asesores["asesor_id"], N_CLIENTES),
        }
    )


# --------------------------------------------------------------------------
# Series de mercado
# --------------------------------------------------------------------------
def generar_tipo_cambio(dias: list[date]) -> pd.DataFrame:
    """Dolar oficial simulado con tendencia suave y ruido."""
    n = len(dias)
    tendencia = np.linspace(1_180, 1_450, n)
    ruido = rng.normal(0, 6, n).cumsum() * 0.3
    valores = (tendencia + ruido).round(2)
    return pd.DataFrame(
        {"fecha": [d.isoformat() for d in dias], "moneda": "USD", "cotizacion": valores}
    )


def generar_cotizaciones(dias: list[date], instrumentos: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for inst in instrumentos.itertuples():
        if inst.tipo_instrumento == "Caucion":
            precios = np.ones(len(dias))
        else:
            vol = {"CEDEAR": 0.018, "Accion": 0.025, "Bono": 0.012, "ON": 0.004, "FCI": 0.002}[
                inst.tipo_instrumento
            ]
            deriva = 0.0009 if inst.tipo_instrumento != "ON" else 0.0001
            retornos = rng.normal(deriva, vol, len(dias))
            precios = inst.precio_inicial * np.exp(np.cumsum(retornos))
        for d, p in zip(dias, precios):
            filas.append({"fecha": d.isoformat(), "ticker": inst.ticker, "precio_cierre": round(float(p), 4)})
    return pd.DataFrame(filas)


# --------------------------------------------------------------------------
# Hechos
# --------------------------------------------------------------------------
def generar_operaciones(
    dias: list[date], clientes: pd.DataFrame, instrumentos: pd.DataFrame, cotizaciones: pd.DataFrame
) -> pd.DataFrame:
    precios = cotizaciones.set_index(["fecha", "ticker"])["precio_cierre"]
    pesos_inst = np.array(
        [1.6 if t in ("CEDEAR", "FCI", "Caucion") else 1.0 for t in instrumentos["tipo_instrumento"]]
    )
    pesos_inst = pesos_inst / pesos_inst.sum()
    actividad = rng.pareto(1.6, len(clientes)) + 0.2  # pocos clientes operan mucho
    actividad = actividad / actividad.sum()

    idx_cli = rng.choice(len(clientes), N_OPERACIONES, p=actividad)
    idx_ins = rng.choice(len(instrumentos), N_OPERACIONES, p=pesos_inst)
    idx_dia = rng.integers(0, len(dias), N_OPERACIONES)
    tipo = rng.choice(["Compra", "Venta"], N_OPERACIONES, p=[0.56, 0.44])

    filas = []
    for k in range(N_OPERACIONES):
        cli = clientes.iloc[idx_cli[k]]
        inst = instrumentos.iloc[idx_ins[k]]
        fecha = dias[idx_dia[k]].isoformat()
        precio = float(precios.loc[(fecha, inst.ticker)])
        escala = {"Retail": 1.0, "Premium": 5.0, "Corporativo": 25.0}[cli.segmento]
        objetivo_ars = rng.lognormal(np.log(350_000 * escala), 0.9)
        if inst.moneda == "USD":
            objetivo = objetivo_ars / 1_300
        else:
            objetivo = objetivo_ars
        cantidad = max(1, round(objetivo / precio))
        monto = round(cantidad * precio, 2)
        filas.append(
            {
                "operacion_id": f"OP{k + 1:07d}",
                "fecha": fecha,
                "cliente_id": cli.cliente_id,
                "ticker": inst.ticker,
                "tipo_operacion": tipo[k] if inst.tipo_instrumento != "FCI" else
                ("Suscripcion" if tipo[k] == "Compra" else "Rescate"),
                "cantidad": cantidad,
                "precio": round(precio, 4),
                "moneda": inst.moneda,
                "monto": monto,
                "comision": round(monto * 0.005, 2) if inst.tipo_instrumento != "FCI" else 0.0,
            }
        )
    return pd.DataFrame(filas)


def generar_movimientos(dias: list[date], clientes: pd.DataFrame) -> pd.DataFrame:
    idx_cli = rng.integers(0, len(clientes), N_MOVIMIENTOS)
    idx_dia = rng.integers(0, len(dias), N_MOVIMIENTOS)
    tipo = rng.choice(["Deposito", "Retiro"], N_MOVIMIENTOS, p=[0.6, 0.4])
    moneda = rng.choice(["ARS", "USD"], N_MOVIMIENTOS, p=[0.8, 0.2])
    canal = rng.choice(["Transferencia", "Efectivo", "Cheque"], N_MOVIMIENTOS, p=[0.88, 0.07, 0.05])
    filas = []
    for k in range(N_MOVIMIENTOS):
        cli = clientes.iloc[idx_cli[k]]
        base = cli.ingreso_mensual_declarado_ars * rng.uniform(0.05, 0.6)
        monto = base if moneda[k] == "ARS" else base / 1_300
        filas.append(
            {
                "movimiento_id": f"MV{k + 1:07d}",
                "fecha": dias[idx_dia[k]].isoformat(),
                "cliente_id": cli.cliente_id,
                "tipo_movimiento": tipo[k],
                "moneda": moneda[k],
                "monto": round(float(monto), 2),
                "canal": canal[k],
            }
        )
    return pd.DataFrame(filas)


def inyectar_patrones_inusuales(
    movimientos: pd.DataFrame, clientes: pd.DataFrame, dias: list[date]
) -> pd.DataFrame:
    """Agrega casos que las alertas deberian detectar."""
    nuevos = []
    contador = len(movimientos)
    retail = clientes[clientes["segmento"] == "Retail"]["cliente_id"].to_list()
    elegidos = rng.choice(retail, 18, replace=False)

    # 1) Fraccionamiento: 4-6 depositos en efectivo apenas debajo del umbral en pocos dias
    for cli in elegidos[:8]:
        inicio = int(rng.integers(0, len(dias) - 10))
        for j in range(int(rng.integers(4, 7))):
            contador += 1
            nuevos.append(
                {
                    "movimiento_id": f"MV{contador:07d}",
                    "fecha": dias[inicio + j].isoformat(),
                    "cliente_id": cli,
                    "tipo_movimiento": "Deposito",
                    "moneda": "ARS",
                    "monto": round(UMBRAL_REPORTE_ARS * rng.uniform(0.86, 0.99), 2),
                    "canal": "Efectivo",
                }
            )

    # 2) Fuera de perfil: depositos muy superiores al ingreso declarado
    for cli in elegidos[8:13]:
        ingreso = float(clientes.loc[clientes["cliente_id"] == cli, "ingreso_mensual_declarado_ars"].iloc[0])
        contador += 1
        nuevos.append(
            {
                "movimiento_id": f"MV{contador:07d}",
                "fecha": dias[int(rng.integers(0, len(dias)))].isoformat(),
                "cliente_id": cli,
                "tipo_movimiento": "Deposito",
                "moneda": "ARS",
                "monto": round(ingreso * rng.uniform(15, 30), 2),
                "canal": "Transferencia",
            }
        )

    # 3) Ida y vuelta: deposito grande y retiro casi igual a los 1-2 dias
    for cli in elegidos[13:]:
        i = int(rng.integers(0, len(dias) - 3))
        monto = round(float(rng.uniform(20_000_000, 60_000_000)), 2)
        for tipo, dia, factor in (("Deposito", i, 1.0), ("Retiro", i + int(rng.integers(1, 3)), 0.97)):
            contador += 1
            nuevos.append(
                {
                    "movimiento_id": f"MV{contador:07d}",
                    "fecha": dias[dia].isoformat(),
                    "cliente_id": cli,
                    "tipo_movimiento": tipo,
                    "moneda": "ARS",
                    "monto": round(monto * factor, 2),
                    "canal": "Transferencia",
                }
            )
    return pd.concat([movimientos, pd.DataFrame(nuevos)], ignore_index=True)


def ensuciar_operaciones(operaciones: pd.DataFrame) -> pd.DataFrame:
    """Simula los problemas tipicos de datos que llegan de sistemas operativos."""
    df = operaciones.copy()
    n = len(df)
    # Duplicados exactos (reenvio del mismo archivo)
    df = pd.concat([df, df.sample(frac=0.012, random_state=SEED)], ignore_index=True)
    # Tickers en minuscula o con espacios
    idx = rng.choice(n, 400, replace=False)
    df.loc[idx, "ticker"] = df.loc[idx, "ticker"].str.lower().str.pad(8, side="right")
    # Fechas en formato dd/mm/aaaa
    idx = rng.choice(n, 600, replace=False)
    df.loc[idx, "fecha"] = pd.to_datetime(df.loc[idx, "fecha"]).dt.strftime("%d/%m/%Y")
    # Montos nulos
    idx = rng.choice(n, 150, replace=False)
    df.loc[idx, "monto"] = np.nan
    # Clientes inexistentes (huerfanos)
    idx = rng.choice(n, 60, replace=False)
    df.loc[idx, "cliente_id"] = "C99999"
    # Cantidades invalidas
    idx = rng.choice(n, 40, replace=False)
    df.loc[idx, "cantidad"] = 0
    return df.sample(frac=1, random_state=SEED).reset_index(drop=True)


def ensuciar_movimientos(movimientos: pd.DataFrame) -> pd.DataFrame:
    df = movimientos.copy()
    df = pd.concat([df, df.sample(frac=0.01, random_state=SEED)], ignore_index=True)
    idx = rng.choice(len(movimientos), 80, replace=False)
    df.loc[idx, "tipo_movimiento"] = df.loc[idx, "tipo_movimiento"].str.upper()
    return df.sample(frac=1, random_state=SEED).reset_index(drop=True)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dias = dias_habiles(FECHA_INICIO, FECHA_FIN)

    asesores = generar_asesores()
    instrumentos = generar_instrumentos()
    clientes = generar_clientes(asesores)
    tipo_cambio = generar_tipo_cambio(dias)
    cotizaciones = generar_cotizaciones(dias, instrumentos)
    operaciones = generar_operaciones(dias, clientes, instrumentos, cotizaciones)
    movimientos = generar_movimientos(dias, clientes)
    movimientos = inyectar_patrones_inusuales(movimientos, clientes, dias)

    salidas = {
        "asesores.csv": asesores,
        "instrumentos.csv": instrumentos.drop(columns=["precio_inicial"]),
        "clientes.csv": clientes,
        "tipo_cambio.csv": tipo_cambio,
        "cotizaciones.csv": cotizaciones,
        "operaciones.csv": ensuciar_operaciones(operaciones),
        "movimientos.csv": ensuciar_movimientos(movimientos),
    }
    for nombre, df in salidas.items():
        df.to_csv(RAW_DIR / nombre, index=False)
        print(f"{nombre:<18} {len(df):>7,} filas")


if __name__ == "__main__":
    main()
