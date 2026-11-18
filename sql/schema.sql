-- Modelo estrella de la casa de inversión (SQLite)
-- Hechos: operaciones, movimientos de fondos, cotizaciones y tipo de cambio
-- Dimensiones: fecha, cliente, asesor, instrumento

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dim_fecha (
    fecha_id      INTEGER PRIMARY KEY,      -- AAAAMMDD
    fecha         TEXT    NOT NULL UNIQUE,
    anio          INTEGER NOT NULL,
    trimestre     INTEGER NOT NULL,
    mes           INTEGER NOT NULL,
    nombre_mes    TEXT    NOT NULL,
    anio_mes      TEXT    NOT NULL,
    dia_semana    INTEGER NOT NULL,         -- 1 = lunes
    es_dia_habil  INTEGER NOT NULL CHECK (es_dia_habil IN (0, 1))
);

CREATE TABLE IF NOT EXISTS dim_asesor (
    asesor_id  TEXT PRIMARY KEY,
    nombre     TEXT NOT NULL,
    equipo     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_cliente (
    cliente_id                     TEXT PRIMARY KEY,
    tipo_persona                   TEXT NOT NULL,
    segmento                       TEXT NOT NULL,
    perfil_riesgo                  TEXT NOT NULL,
    provincia                      TEXT,
    fecha_alta                     TEXT,
    ingreso_mensual_declarado_ars  REAL,
    asesor_id                      TEXT REFERENCES dim_asesor (asesor_id)
);

CREATE TABLE IF NOT EXISTS dim_instrumento (
    ticker            TEXT PRIMARY KEY,
    nombre            TEXT NOT NULL,
    tipo_instrumento  TEXT NOT NULL,
    moneda            TEXT NOT NULL CHECK (moneda IN ('ARS', 'USD'))
);

CREATE TABLE IF NOT EXISTS fact_operaciones (
    operacion_id    TEXT PRIMARY KEY,
    fecha_id        INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    fecha           TEXT    NOT NULL,
    cliente_id      TEXT    NOT NULL REFERENCES dim_cliente (cliente_id),
    asesor_id       TEXT    REFERENCES dim_asesor (asesor_id),
    ticker          TEXT    NOT NULL REFERENCES dim_instrumento (ticker),
    tipo_operacion  TEXT    NOT NULL CHECK (tipo_operacion IN ('Compra', 'Venta', 'Suscripcion', 'Rescate')),
    cantidad        REAL    NOT NULL CHECK (cantidad > 0),
    precio          REAL    NOT NULL,
    moneda          TEXT    NOT NULL,
    monto           REAL    NOT NULL,
    monto_ars       REAL    NOT NULL,
    monto_usd       REAL    NOT NULL,
    comision_ars    REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fact_movimientos (
    movimiento_id    TEXT PRIMARY KEY,
    fecha_id         INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    fecha            TEXT    NOT NULL,
    cliente_id       TEXT    NOT NULL REFERENCES dim_cliente (cliente_id),
    asesor_id        TEXT    REFERENCES dim_asesor (asesor_id),
    tipo_movimiento  TEXT    NOT NULL CHECK (tipo_movimiento IN ('Deposito', 'Retiro')),
    canal            TEXT    NOT NULL,
    moneda           TEXT    NOT NULL,
    monto            REAL    NOT NULL CHECK (monto > 0),
    monto_ars        REAL    NOT NULL,
    monto_usd        REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_cotizaciones (
    fecha_id       INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    ticker         TEXT    NOT NULL REFERENCES dim_instrumento (ticker),
    precio_cierre  REAL    NOT NULL,
    PRIMARY KEY (fecha_id, ticker)
);

CREATE TABLE IF NOT EXISTS fact_tipo_cambio (
    fecha_id    INTEGER NOT NULL REFERENCES dim_fecha (fecha_id),
    moneda      TEXT    NOT NULL,
    cotizacion  REAL    NOT NULL,
    PRIMARY KEY (fecha_id, moneda)
);

-- Parámetros de las alertas (se pueden ajustar sin tocar las vistas)
CREATE TABLE IF NOT EXISTS parametros (
    nombre  TEXT PRIMARY KEY,
    valor   REAL NOT NULL
);

-- Auditoría de cada ejecución del pipeline
CREATE TABLE IF NOT EXISTS log_ejecuciones (
    ejecucion_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio            TEXT NOT NULL,
    fin               TEXT NOT NULL,
    fuente_tipo_cambio TEXT NOT NULL,
    filas_operaciones INTEGER NOT NULL,
    filas_movimientos INTEGER NOT NULL,
    estado            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_oper_fecha   ON fact_operaciones (fecha_id);
CREATE INDEX IF NOT EXISTS ix_oper_cliente ON fact_operaciones (cliente_id);
CREATE INDEX IF NOT EXISTS ix_oper_ticker  ON fact_operaciones (ticker);
CREATE INDEX IF NOT EXISTS ix_mov_fecha    ON fact_movimientos (fecha_id);
CREATE INDEX IF NOT EXISTS ix_mov_cliente  ON fact_movimientos (cliente_id, fecha);
