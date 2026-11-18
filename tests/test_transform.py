import pandas as pd

from etl import transform
from etl.transform import ReporteCalidad

CLIENTES = pd.DataFrame({"cliente_id": ["C1", "C2"]})
INSTRUMENTOS = pd.DataFrame({"ticker": ["AAPL", "GD30"]})


def operaciones_crudas(**cambios):
    base = {
        "operacion_id": "OP1", "fecha": "2026-03-02", "cliente_id": "C1", "ticker": "AAPL",
        "tipo_operacion": "Compra", "cantidad": "10", "precio": "100", "moneda": "ARS",
        "monto": "1000", "comision": "5",
    }
    base.update(cambios)
    return base


def test_parsear_fechas_acepta_dos_formatos():
    fechas = transform.parsear_fechas(pd.Series(["2026-03-02", "02/03/2026", "fecha mala"]))
    assert fechas[0] == fechas[1] == pd.Timestamp("2026-03-02")
    assert pd.isna(fechas[2])


def test_normalizar_ticker():
    assert transform.normalizar_ticker(pd.Series([" aapl  "])).iloc[0] == "AAPL"


def test_elimina_duplicados_y_huerfanos():
    df = pd.DataFrame(
        [
            operaciones_crudas(),
            operaciones_crudas(),                                   # duplicado exacto
            operaciones_crudas(operacion_id="OP2", cliente_id="C99"),  # cliente inexistente
        ]
    )
    rep = ReporteCalidad()
    out = transform.limpiar_operaciones(df, CLIENTES, INSTRUMENTOS, rep)
    assert list(out["operacion_id"]) == ["OP1"]
    assert rep.tablas["operaciones"]["duplicados_eliminados"] == 1
    assert rep.tablas["operaciones"]["clientes_inexistentes_descartados"] == 1


def test_recalcula_monto_faltante_y_descarta_cantidad_cero():
    df = pd.DataFrame(
        [
            operaciones_crudas(monto=None),
            operaciones_crudas(operacion_id="OP2", cantidad="0"),
        ]
    )
    rep = ReporteCalidad()
    out = transform.limpiar_operaciones(df, CLIENTES, INSTRUMENTOS, rep)
    assert len(out) == 1
    assert out.iloc[0]["monto"] == 1000
    assert rep.tablas["operaciones"]["montos_recalculados"] == 1


def test_normaliza_ticker_y_fecha_en_operaciones():
    df = pd.DataFrame([operaciones_crudas(ticker=" aapl ", fecha="02/03/2026")])
    out = transform.limpiar_operaciones(df, CLIENTES, INSTRUMENTOS, ReporteCalidad())
    assert out.iloc[0]["ticker"] == "AAPL"
    assert out.iloc[0]["fecha"] == "2026-03-02"
    assert out.iloc[0]["fecha_id"] == 20260302


def test_tipo_de_cambio_cubre_fines_de_semana():
    dim_fecha = transform.construir_dim_fecha(pd.Timestamp("2026-03-06"), pd.Timestamp("2026-03-09"))
    tc = pd.DataFrame({"fecha": ["2026-03-06", "2026-03-09"], "moneda": "USD", "cotizacion": ["1400", "1410"]})
    out = transform.preparar_tipo_cambio(tc, dim_fecha).set_index("fecha_id")["cotizacion"]
    assert out[20260307] == 1400  # sábado toma el viernes
    assert out[20260308] == 1400  # domingo toma el viernes
    assert out[20260309] == 1410


def test_convertir_montos_usd_y_ars():
    tc = pd.DataFrame({"fecha_id": [20260302], "cotizacion": [1_400.0]})
    df = pd.DataFrame({"fecha_id": [20260302, 20260302], "moneda": ["USD", "ARS"], "monto": [100.0, 140_000.0]})
    out = transform.convertir_montos(df, tc)
    assert list(out["monto_ars"]) == [140_000.0, 140_000.0]
    assert list(out["monto_usd"]) == [100.0, 100.0]
