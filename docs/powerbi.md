# Guía del dashboard en Power BI

El pipeline exporta el modelo a `data/processed/` en CSV. Esta guía describe cómo
armar el tablero sobre esos archivos.

## 1. Importar los datos

1. Correr `python -m etl.pipeline`.
2. En Power BI Desktop: **Obtener datos → Carpeta** y elegir `data/processed/`,
   o importar cada CSV con **Texto/CSV**.
3. En Power Query, revisar tipos:
   - `dim_fecha[fecha]` → **Fecha**
   - `*_id` de fecha → **Número entero**
   - montos → **Número decimal**
4. Marcar `dim_fecha` como **tabla de fechas** (columna `fecha`).

## 2. Relaciones (esquema estrella)

| Desde (1)                   | Hacia (*)                         |
|-----------------------------|-----------------------------------|
| `dim_fecha[fecha_id]`       | `fact_operaciones[fecha_id]`      |
| `dim_fecha[fecha_id]`       | `fact_movimientos[fecha_id]`      |
| `dim_cliente[cliente_id]`   | `fact_operaciones[cliente_id]`    |
| `dim_cliente[cliente_id]`   | `fact_movimientos[cliente_id]`    |
| `dim_cliente[cliente_id]`   | `vw_alertas[cliente_id]`          |
| `dim_asesor[asesor_id]`     | `fact_operaciones[asesor_id]`     |
| `dim_asesor[asesor_id]`     | `fact_movimientos[asesor_id]`     |
| `dim_instrumento[ticker]`   | `fact_operaciones[ticker]`        |

No relacionar `dim_cliente` con `dim_asesor`: los hechos ya tienen `asesor_id` y
una segunda ruta generaría ambigüedad.

## 3. Medidas DAX

Crear una tabla vacía `_Medidas` para agruparlas.

```dax
Volumen Operado = SUM ( fact_operaciones[monto_ars] )

Comisiones = SUM ( fact_operaciones[comision_ars] )

Cantidad Operaciones = COUNTROWS ( fact_operaciones )

Ticket Promedio = DIVIDE ( [Volumen Operado], [Cantidad Operaciones] )

Clientes Activos = DISTINCTCOUNT ( fact_operaciones[cliente_id] )

Depositos =
CALCULATE ( SUM ( fact_movimientos[monto_ars] ), fact_movimientos[tipo_movimiento] = "Deposito" )

Retiros =
CALCULATE ( SUM ( fact_movimientos[monto_ars] ), fact_movimientos[tipo_movimiento] = "Retiro" )

Captacion Neta = [Depositos] - [Retiros]

Captacion Neta Acumulada =
CALCULATE (
    [Captacion Neta],
    FILTER ( ALL ( dim_fecha ), dim_fecha[fecha] <= MAX ( dim_fecha[fecha] ) )
)

Volumen MTD = TOTALMTD ( [Volumen Operado], dim_fecha[fecha] )

Volumen YTD = TOTALYTD ( [Volumen Operado], dim_fecha[fecha] )

Volumen Mes Anterior =
CALCULATE ( [Volumen Operado], DATEADD ( dim_fecha[fecha], -1, MONTH ) )

Var % Volumen =
DIVIDE ( [Volumen Operado] - [Volumen Mes Anterior], [Volumen Mes Anterior] )

Ranking Asesor =
IF ( HASONEVALUE ( dim_asesor[asesor_id] ), RANKX ( ALL ( dim_asesor ), [Comisiones] ) )

Alertas Abiertas = COUNTROWS ( vw_alertas )

Monto en Alerta = SUM ( vw_alertas[monto_total_ars] )
```

## 4. Páginas sugeridas

**Resumen comercial**
- Tarjetas: Volumen Operado, Comisiones, Captación Neta, Clientes Activos, Var % Volumen.
- Columnas: Volumen Operado por `dim_fecha[anio_mes]`.
- Línea: Captación Neta Acumulada.
- Segmentadores: mes, segmento de cliente, equipo.

**Asesores**
- Tabla: asesor, equipo, Comisiones, Volumen Operado, Clientes Activos, Ranking Asesor.
- Barras: Comisiones por asesor.

**Productos**
- Treemap: Volumen Operado por `tipo_instrumento`.
- Top 10 tickers por volumen.
- Flujo neto por instrumento (compras − ventas).

**Cumplimiento**
- Tarjetas: Alertas Abiertas, Monto en Alerta.
- Barras: alertas por `tipo_alerta`.
- Tabla de detalle: cliente, asesor, fechas, monto, detalle.

## 5. Seguridad a nivel de fila (RLS)

Modelado → **Administrar roles** → crear un rol por equipo, por ejemplo
`Retail CABA` con el filtro sobre `dim_asesor`:

```dax
[equipo] = "Retail CABA"
```

Para RLS dinámica en Power BI Service, agregar una tabla con el email de cada
usuario y su equipo, y filtrar con `USERPRINCIPALNAME()`.

## 6. Capturas para el README

Guardar capturas de cada página en `docs/img/` con estos nombres:

- `dashboard_resumen.png`
- `dashboard_asesores.png`
- `dashboard_cumplimiento.png`
