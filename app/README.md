# 📊 Mi patrimonio — panel personal

Una sola app para controlar **todas tus inversiones y gastos**:

| Fuente | Cómo entra | Estado |
|---|---|---|
| 🏦 **Banco** | Subes el PDF del extracto | Gastos **netos** por categoría |
| 📈 **Trade Republic** | Subes el informe mensual (PDF o CSV) | Acciones / ETFs |
| 🪙 **Nexo** | Subes el informe/balances (CSV o PDF) | Cripto |
| 🔫 **CS:GO** | Conecta con tu **Steam Inventory** | Skins valoradas con el Steam Market (en vivo) |
| 🃏 **Magic** | Mazo de **Moxfield** o decklist pegada | Precio **en tiempo real** con Scryfall |

Arriba se muestra el **patrimonio consolidado** (liquidez del banco + acciones +
cripto + skins + cartas), que se actualiza a medida que cargas cada fuente.

Además incluye:
- 📊 **Vista de gráficos**: tarta (doughnut) del reparto del patrimonio, barras
  apiladas del **patrimonio mensual** (según la fecha de cada documento) con línea
  de total, y mini-gráficas de evolución por categoría. El histórico se guarda en
  `data/snapshots.json`.
- 📈 **Seguimiento diario de precios** de tus cartas y skins (Scryfall + Steam
  Market/CSFloat) y 📲 **alerta semanal por WhatsApp** de lo que haya subido >10%
  algún día de la semana. Ver **[DEPLOY.md](DEPLOY.md)**.

## Ejecutar

```bash
cd app
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

(Opcional) Copia `config.example.json` a `config.json` y pon tu SteamID64 y tu
mazo de Moxfield por defecto. `config.json` está en `.gitignore`.

## Cada mes

1. **Banco / Trade Republic / Nexo** → subes los informes del mes en sus pestañas.
2. **CS:GO** → pulsas «Conectar inventario» (tu inventario de Steam debe estar en
   **público**); se valoran las skins con el Steam Market.
3. **Magic** → pegas la decklist (o la URL del mazo) y se piden los precios a Scryfall.

## Reglas del banco (gasto neto)

- 🟢 **Las inversiones no son gastos** → los cargos de **Nexo** se excluyen del gasto.
- 🔁 **Bizums recibidos = posible devolución** → si te devuelven dinero por una compra,
  ese bizum **resta del gasto** en vez de contar como ingreso.
- 🍽️ **Gasto neto** → cena de 30 € con dos bizums de 10 € → gasto de restaurante **10 €**.

Cada bizum recibido se puede **ligar manualmente** al gasto que reembolsa (con
sugerencia automática); los totales se recalculan al instante.

## Estructura

```
app/
  app.py                 # Flask: rutas y orquestación
  config.example.json    # plantilla de configuración (SteamID, Moxfield)
  sources/
    common.py            # Position, parseo de importes y de tablas PDF (por coordenadas)
    http.py              # cliente HTTP stdlib que respeta el proxy y su CA
    bank.py              # extracto del banco -> gasto neto + enlace de bizums
    trade_republic.py    # informe TR (PDF/CSV) -> acciones/ETFs
    nexo.py              # informe Nexo (CSV/PDF) -> cripto
    steam.py             # Steam Inventory + Steam Market -> skins CS:GO
    moxfield.py          # Moxfield/decklist + precios Scryfall en vivo -> cartas Magic
  jobs/
    track_prices.py      # seguimiento DIARIO de precios (cartas + skins)
    weekly_whatsapp.py   # alerta SEMANAL por WhatsApp de subidas >10%
    scheduler.py         # programador en proceso (APScheduler) para producción
  templates/index.html   # panel con pestañas
  static/                # app.js, charts.js, anim.js, styles.css, vendor/
  Dockerfile · Procfile · render.yaml · .env.example · DEPLOY.md   # despliegue
```

## Despliegue público + alertas de precio

Pensado para correr en una instancia siempre activa con disco persistente: sirve
la web y, con un programador en proceso, hace el seguimiento diario de precios y
el envío semanal por WhatsApp. Guía completa en **[DEPLOY.md](DEPLOY.md)**.

## Formatos de archivo

**Trade Republic** reconoce su PDF real *«Extracto del patrimonio neto»* (posiciones
`<unidades> unidades <nombre> | <precio> | <valor>` con ISIN, más el efectivo) y,
como respaldo, un CSV normalizado. **Nexo** detecta columnas por cabecera y también
acepta CSV normalizado:

```csv
# Trade Republic (respaldo CSV)
name,isin,quantity,price,value
Apple,US0378331005,3,180.50,541.50

# Nexo
asset,amount,value
BTC,0.05,3120.00
```

> El parser de TR está probado con el extracto real (S&P 500, Take-Two → 1.607,60 €).
> El de **Nexo** sigue siendo heurístico para PDF hasta tener un informe real de
> muestra; en cuanto me pases uno, ajusto sus columnas exactas.

## Notas e integraciones

- **Scryfall** (precios Magic) y **Steam Market** (precios skins): APIs públicas,
  funcionan tal cual. Scryfall se consulta en lotes de 75 cartas; si una carta solo
  tiene precio en USD se indica y no se suma al total en €.
- **Steam Inventory**: requiere inventario **público**. Los precios se **cachean**
  en `sources/.cache/` (6 h) y se respeta el límite de peticiones del Market.
- **Moxfield**: su API suele bloquear el acceso automático (Cloudflare). Por eso la
  vía recomendada es **pegar la decklist** exportada; igualmente se intenta la API
  si das una URL/ID de mazo.
