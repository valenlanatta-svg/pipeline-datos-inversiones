-- Vistas analíticas: KPIs comerciales y alertas de cumplimiento.
-- Usan CTEs y funciones de ventana (SUM/LAG/RANK OVER).

-- ==========================================================================
-- KPIs comerciales mensuales
-- ==========================================================================
DROP VIEW IF EXISTS vw_kpis_mensuales;
CREATE VIEW vw_kpis_mensuales AS
WITH operaciones_mes AS (
    SELECT f.anio_mes,
           SUM(o.monto_ars)            AS volumen_operado_ars,
           SUM(o.comision_ars)         AS comisiones_ars,
           COUNT(*)                    AS cantidad_operaciones,
           COUNT(DISTINCT o.cliente_id) AS clientes_activos
    FROM fact_operaciones o
    JOIN dim_fecha f ON f.fecha_id = o.fecha_id
    GROUP BY f.anio_mes
),
movimientos_mes AS (
    SELECT f.anio_mes,
           SUM(CASE WHEN m.tipo_movimiento = 'Deposito' THEN m.monto_ars ELSE 0 END) AS depositos_ars,
           SUM(CASE WHEN m.tipo_movimiento = 'Retiro'   THEN m.monto_ars ELSE 0 END) AS retiros_ars
    FROM fact_movimientos m
    JOIN dim_fecha f ON f.fecha_id = m.fecha_id
    GROUP BY f.anio_mes
)
SELECT o.anio_mes,
       ROUND(o.volumen_operado_ars, 2)                       AS volumen_operado_ars,
       ROUND(o.comisiones_ars, 2)                            AS comisiones_ars,
       o.cantidad_operaciones,
       o.clientes_activos,
       ROUND(COALESCE(m.depositos_ars, 0), 2)                AS depositos_ars,
       ROUND(COALESCE(m.retiros_ars, 0), 2)                  AS retiros_ars,
       ROUND(COALESCE(m.depositos_ars, 0) - COALESCE(m.retiros_ars, 0), 2) AS captacion_neta_ars,
       ROUND(SUM(COALESCE(m.depositos_ars, 0) - COALESCE(m.retiros_ars, 0))
             OVER (ORDER BY o.anio_mes), 2)                  AS captacion_neta_acumulada_ars,
       ROUND(100.0 * (o.volumen_operado_ars - LAG(o.volumen_operado_ars) OVER (ORDER BY o.anio_mes))
             / LAG(o.volumen_operado_ars) OVER (ORDER BY o.anio_mes), 2) AS variacion_volumen_pct
FROM operaciones_mes o
LEFT JOIN movimientos_mes m ON m.anio_mes = o.anio_mes;


-- ==========================================================================
-- Ranking mensual de asesores
-- ==========================================================================
DROP VIEW IF EXISTS vw_ranking_asesores;
CREATE VIEW vw_ranking_asesores AS
WITH por_asesor AS (
    SELECT f.anio_mes,
           o.asesor_id,
           SUM(o.monto_ars)             AS volumen_operado_ars,
           SUM(o.comision_ars)          AS comisiones_ars,
           COUNT(DISTINCT o.cliente_id) AS clientes_activos
    FROM fact_operaciones o
    JOIN dim_fecha f ON f.fecha_id = o.fecha_id
    GROUP BY f.anio_mes, o.asesor_id
)
SELECT p.anio_mes,
       p.asesor_id,
       a.nombre  AS asesor,
       a.equipo,
       ROUND(p.volumen_operado_ars, 2) AS volumen_operado_ars,
       ROUND(p.comisiones_ars, 2)      AS comisiones_ars,
       p.clientes_activos,
       RANK() OVER (PARTITION BY p.anio_mes ORDER BY p.comisiones_ars DESC) AS ranking_comisiones,
       ROUND(100.0 * p.comisiones_ars / SUM(p.comisiones_ars) OVER (PARTITION BY p.anio_mes), 2)
                                                                            AS participacion_pct
FROM por_asesor p
JOIN dim_asesor a ON a.asesor_id = p.asesor_id;


-- ==========================================================================
-- Volumen por tipo de instrumento
-- ==========================================================================
DROP VIEW IF EXISTS vw_volumen_instrumentos;
CREATE VIEW vw_volumen_instrumentos AS
SELECT f.anio_mes,
       i.tipo_instrumento,
       o.ticker,
       COUNT(*)                     AS cantidad_operaciones,
       ROUND(SUM(o.monto_ars), 2)   AS volumen_operado_ars,
       ROUND(SUM(CASE WHEN o.tipo_operacion IN ('Compra', 'Suscripcion') THEN o.monto_ars
                      ELSE -o.monto_ars END), 2) AS flujo_neto_ars
FROM fact_operaciones o
JOIN dim_fecha f       ON f.fecha_id = o.fecha_id
JOIN dim_instrumento i ON i.ticker   = o.ticker
GROUP BY f.anio_mes, i.tipo_instrumento, o.ticker;


-- ==========================================================================
-- ALERTA 1: fraccionamiento de depósitos en efectivo
-- Varios depósitos apenas debajo del umbral dentro de una ventana corta.
-- ==========================================================================
DROP VIEW IF EXISTS vw_alerta_fraccionamiento;
CREATE VIEW vw_alerta_fraccionamiento AS
WITH p AS (
    SELECT MAX(CASE WHEN nombre = 'umbral_reporte_ars'              THEN valor END) AS umbral,
           MAX(CASE WHEN nombre = 'fraccionamiento_pct_min'         THEN valor END) AS pct_min,
           MAX(CASE WHEN nombre = 'fraccionamiento_ventana_dias'    THEN valor END) AS ventana,
           MAX(CASE WHEN nombre = 'fraccionamiento_min_movimientos' THEN valor END) AS min_mov
    FROM parametros
),
depositos_sospechosos AS (
    SELECT m.*
    FROM fact_movimientos m, p
    WHERE m.tipo_movimiento = 'Deposito'
      AND m.canal = 'Efectivo'
      AND m.monto_ars >= p.umbral * p.pct_min
      AND m.monto_ars <  p.umbral
),
ventanas AS (
    -- Para cada depósito, cuántos depósitos similares hubo en los N días previos
    SELECT d1.cliente_id,
           d1.fecha                    AS fecha_hasta,
           MIN(d2.fecha)               AS fecha_desde,
           COUNT(*)                    AS cantidad_movimientos,
           SUM(d2.monto_ars)           AS monto_total_ars
    FROM depositos_sospechosos d1
    JOIN depositos_sospechosos d2
      ON d2.cliente_id = d1.cliente_id
     AND julianday(d2.fecha) BETWEEN julianday(d1.fecha) - (SELECT ventana FROM p) + 1
                                 AND julianday(d1.fecha)
    GROUP BY d1.cliente_id, d1.fecha
),
mejor_ventana AS (
    SELECT v.*,
           ROW_NUMBER() OVER (PARTITION BY v.cliente_id
                              ORDER BY v.cantidad_movimientos DESC, v.monto_total_ars DESC) AS rn
    FROM ventanas v, p
    WHERE v.cantidad_movimientos >= p.min_mov
)
SELECT 'Fraccionamiento de depositos en efectivo' AS tipo_alerta,
       w.cliente_id,
       c.asesor_id,
       w.fecha_desde,
       w.fecha_hasta,
       w.cantidad_movimientos,
       ROUND(w.monto_total_ars, 2) AS monto_total_ars,
       w.cantidad_movimientos || ' depositos en efectivo debajo del umbral en '
           || CAST((SELECT ventana FROM p) AS INTEGER) || ' dias' AS detalle
FROM mejor_ventana w
JOIN dim_cliente c ON c.cliente_id = w.cliente_id
WHERE w.rn = 1;


-- ==========================================================================
-- ALERTA 2: depósitos fuera del perfil declarado
-- Depósitos del mes muy superiores al ingreso mensual declarado.
-- ==========================================================================
DROP VIEW IF EXISTS vw_alerta_fuera_perfil;
CREATE VIEW vw_alerta_fuera_perfil AS
WITH p AS (
    SELECT MAX(CASE WHEN nombre = 'fuera_perfil_factor' THEN valor END) AS factor FROM parametros
),
depositos_mes AS (
    SELECT m.cliente_id,
           f.anio_mes,
           MIN(m.fecha)      AS fecha_desde,
           MAX(m.fecha)      AS fecha_hasta,
           COUNT(*)          AS cantidad_movimientos,
           SUM(m.monto_ars)  AS monto_total_ars
    FROM fact_movimientos m
    JOIN dim_fecha f ON f.fecha_id = m.fecha_id
    WHERE m.tipo_movimiento = 'Deposito'
    GROUP BY m.cliente_id, f.anio_mes
)
SELECT 'Depositos fuera de perfil' AS tipo_alerta,
       d.cliente_id,
       c.asesor_id,
       d.fecha_desde,
       d.fecha_hasta,
       d.cantidad_movimientos,
       ROUND(d.monto_total_ars, 2) AS monto_total_ars,
       'Depositos de ' || d.anio_mes || ' = ' ||
           CAST(ROUND(d.monto_total_ars / c.ingreso_mensual_declarado_ars, 1) AS TEXT) ||
           ' veces el ingreso mensual declarado' AS detalle
FROM depositos_mes d
JOIN dim_cliente c ON c.cliente_id = d.cliente_id, p
WHERE c.ingreso_mensual_declarado_ars > 0
  AND d.monto_total_ars > p.factor * c.ingreso_mensual_declarado_ars;


-- ==========================================================================
-- ALERTA 3: "ida y vuelta" de fondos
-- Depósito relevante retirado casi completo en pocos días.
-- ==========================================================================
DROP VIEW IF EXISTS vw_alerta_ida_vuelta;
CREATE VIEW vw_alerta_ida_vuelta AS
WITH p AS (
    SELECT MAX(CASE WHEN nombre = 'ida_vuelta_dias'          THEN valor END) AS dias,
           MAX(CASE WHEN nombre = 'ida_vuelta_pct_min'       THEN valor END) AS pct_min,
           MAX(CASE WHEN nombre = 'ida_vuelta_monto_min_ars' THEN valor END) AS monto_min
    FROM parametros
)
SELECT 'Ida y vuelta de fondos' AS tipo_alerta,
       d.cliente_id,
       c.asesor_id,
       d.fecha  AS fecha_desde,
       r.fecha  AS fecha_hasta,
       2        AS cantidad_movimientos,
       ROUND(d.monto_ars, 2) AS monto_total_ars,
       'Deposito de ' || CAST(ROUND(d.monto_ars, 0) AS INTEGER) || ' ARS retirado en ' ||
           CAST(julianday(r.fecha) - julianday(d.fecha) AS INTEGER) || ' dia(s) (' ||
           CAST(ROUND(100.0 * r.monto_ars / d.monto_ars, 0) AS INTEGER) || '%)' AS detalle
FROM fact_movimientos d
JOIN fact_movimientos r
  ON r.cliente_id = d.cliente_id
 AND r.tipo_movimiento = 'Retiro'
 AND julianday(r.fecha) - julianday(d.fecha) BETWEEN 0 AND (SELECT dias FROM p)
JOIN dim_cliente c ON c.cliente_id = d.cliente_id, p
WHERE d.tipo_movimiento = 'Deposito'
  AND d.monto_ars >= p.monto_min
  AND r.monto_ars BETWEEN p.pct_min * d.monto_ars AND 1.10 * d.monto_ars;


-- ==========================================================================
-- Vista unificada de alertas para la API y Power BI
-- ==========================================================================
DROP VIEW IF EXISTS vw_alertas;
CREATE VIEW vw_alertas AS
SELECT * FROM vw_alerta_fraccionamiento
UNION ALL
SELECT * FROM vw_alerta_fuera_perfil
UNION ALL
SELECT * FROM vw_alerta_ida_vuelta;
