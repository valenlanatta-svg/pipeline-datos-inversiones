import pytest

from api import repository as repo
from etl import load


def test_upsert_es_idempotente(con, tablas):
    load.cargar_modelo(con, tablas)  # segunda carga de los mismos datos
    assert con.execute("SELECT COUNT(*) FROM fact_movimientos").fetchone()[0] == len(tablas["fact_movimientos"])


def test_upsert_actualiza_filas_existentes(con, tablas):
    corregida = tablas["fact_operaciones"].copy()
    corregida.loc[0, "comision_ars"] = 999
    load.upsert(con, "fact_operaciones", corregida, ["operacion_id"])
    valor = con.execute("SELECT comision_ars FROM fact_operaciones WHERE operacion_id = 'OP1'").fetchone()[0]
    assert valor == 999


def test_alerta_fraccionamiento_detecta_cliente(con):
    alertas = repo.listar_alertas(con, "Fraccionamiento de depositos en efectivo")
    assert [a["cliente_id"] for a in alertas] == ["C1"]
    assert alertas[0]["cantidad_movimientos"] == 4


def test_alerta_ida_y_vuelta_detecta_cliente(con):
    alertas = repo.listar_alertas(con, "Ida y vuelta de fondos")
    assert [a["cliente_id"] for a in alertas] == ["C2"]


def test_alerta_fuera_de_perfil(con):
    clientes = {a["cliente_id"] for a in repo.listar_alertas(con, "Depositos fuera de perfil")}
    assert clientes == {"C1", "C2"}  # C3 tiene ingresos acordes a sus depósitos


def test_kpis_captacion_neta(con):
    kpi = repo.kpis_mensuales(con)[0]
    depositos = 9_500_000 + 9_700_000 + 9_100_000 + 9_900_000 + 30_000_000 + 8_000_000
    retiros = 29_000_000 + 1_000_000
    assert kpi["captacion_neta_ars"] == depositos - retiros
    assert kpi["clientes_activos"] == 2


def test_filtros_y_paginacion_de_operaciones(con):
    total, filas = repo.listar_operaciones(con, ticker="aapl", limit=1)
    assert total == 2 and len(filas) == 1
    total, filas = repo.listar_operaciones(con, cliente_id="C3")
    assert total == 1 and filas[0]["operacion_id"] == "OP2"


def test_filtro_no_permite_inyeccion_sql(con):
    total, _ = repo.listar_operaciones(con, cliente_id="C1' OR '1'='1")
    assert total == 0


def test_exportar_csv(con):
    _, filas = repo.listar_operaciones(con)
    csv_texto = repo.a_csv(filas)
    assert csv_texto.splitlines()[0].startswith("operacion_id,fecha")
    assert len(csv_texto.splitlines()) == 3


def test_endpoints_api(con, tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from api import main

    def conexion_de_prueba():
        yield con

    main.app.dependency_overrides[main.get_conexion] = conexion_de_prueba
    cliente = TestClient(main.app)

    r = cliente.get("/operaciones", params={"cliente_id": "C1"})
    assert r.status_code == 200 and r.json()["total"] == 1

    r = cliente.get("/operaciones", params={"formato": "csv"})
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]

    r = cliente.get("/operaciones", params={"desde": "02-03-2026"})
    assert r.status_code == 422  # formato de fecha inválido

    r = cliente.get("/alertas")
    assert r.status_code == 200 and r.json()["cantidad"] >= 2
    main.app.dependency_overrides.clear()
