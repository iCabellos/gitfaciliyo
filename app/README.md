# 📊 Mi patrimonio — panel personal

Una sola app para controlar **todas tus inversiones y gastos**:

| Fuente | Cómo entra | Estado |
|---|---|---|
| 🏦 **imagin / CaixaBank** | **API PSD2** (Enable Banking) o PDF del extracto | Saldo y gastos **netos** por categoría |
| 📈 **Trade Republic** | **API de la propia app** (dispositivo emparejado) o PDF/CSV | Acciones / ETFs con nombre y nº de títulos |
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
- 🕒 **Histórico semanal de TODO el patrimonio**: en la misma serie conviven el
  patrimonio total, cada categoría, cada acción/ETF, cada carta y cada skin. Se
  consulta en la pestaña «Histórico semanal», con el gráfico del patrimonio
  semana a semana, la variación de cada elemento y su serie completa al tocarlo.
- 📲 **Resumen semanal por WhatsApp** con el patrimonio, su variación y **todo lo
  que se haya movido un ±5%** —el total, una categoría, una acción, una carta o
  una skin— con su valor anterior → valor actual. Si una fuente no está conectada o falla, sale un ⚠️ en el propio
  mensaje: nunca se repite una cifra vieja como si fuera nueva.
- 📄 **Registro de valores**: qué acciones/ETFs tienes y **cuántos títulos** de
  cada uno, mes a mes.
Ver **[DEPLOY.md](DEPLOY.md)** y **[BANCOS_API.md](BANCOS_API.md)**.

## Ejecutar

```bash
cd app
pip install -r requirements.txt
python app.py            # http://127.0.0.1:5000
```

### Configuración

`settings.json` (versionado) lleva la configuración real y pública: SteamID64 y
mazo de Moxfield por defecto. Por eso la web desplegada arranca ya configurada.

El orden de precedencia lo decide `sources/settings.py`, y es el mismo para la
web, el resumen semanal y el cron:

1. Variable de entorno (`STEAM_ID64`) — lo que defina el servidor o el cron.
2. `config.json` — configuración local, en `.gitignore` (desarrollo).
3. Ajuste en la base de datos — lo último que guardaste desde la web.
4. `settings.json` — la configuración versionada.

`config.example.json` es solo una **plantilla** y NUNCA entra en esa cadena.
Los secretos de verdad (PIN, tokens, claves) van solo en variables de entorno.

## Conectar las fuentes por API (una sola vez)

Con esto el resumen semanal se actualiza solo, sin subir nada a mano:

1. **imagin** → pestaña *Banco*, «Conectar imagin por API». Pulsa *Autorizar*,
   autoriza en la app de imagin (SCA) y pega el `code` del retorno. El
   consentimiento PSD2 dura ~90 días; al caducar te avisa el propio WhatsApp.
2. **Trade Republic** → pestaña *Trade Republic*, «Conectar por API». Teléfono +
   PIN → llega un código → *Emparejar*. El dispositivo queda autorizado y a
   partir de ahí no hace falta ningún código más.
3. **CS:GO** → «Conectar inventario» con tu SteamID64 (inventario en **público**).
4. **Magic** → pegas la decklist (o la URL del mazo); queda guardada.

Requisitos de servidor para 1 y 2 (ver `.env.example`): `ENABLE_BANKING_APP_ID`,
la clave privada de la app, `ENABLE_BANKING_REDIRECT_URL`, `TR_PHONE` y `TR_PIN`.

La vía manual (subir el PDF/CSV del banco o de Trade Republic) sigue funcionando
igual y es el respaldo cuando una API falla.

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
    trade_republic_live.py # API real de TR: emparejado + cartera por websocket
    enablebanking.py     # imagin/CaixaBank por PSD2 (Enable Banking)
    steam.py             # Steam Inventory + Steam Market -> skins CS:GO
    moxfield.py          # Moxfield/decklist + precios Scryfall en vivo -> cartas Magic
    prices.py            # histórico de TODO el patrimonio: diario, semanal y movimientos ±5%
    settings.py          # ÚNICO sitio que resuelve la configuración (SteamID, mazo, divisa)
    patrimonio.py        # resumen del patrimonio y mensaje de WhatsApp
    revalue.py           # revalorización en vivo de las 4 fuentes
    db.py                # snapshots, caché, histórico de precios y registro de valores
  jobs/
    track_prices.py      # seguimiento DIARIO de precios (cartas + skins)
    weekly_whatsapp.py   # alerta de precios ±5% por WhatsApp (disparo manual)
    scheduler.py         # programador en proceso (APScheduler) para producción
  templates/index.html   # panel con pestañas
  static/                # app.js, charts.js, history.js, connect.js, anim.js, styles.css
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
- **Steam Inventory**: requiere inventario **público**. La descarga **pagina**
  (Steam sirve como mucho 2000 objetos por petición; pedir más hace que rechace
  la petición entera). Los precios se cachean 6 h **en la base de datos**, que
  comparten el cron y la web: con cachés separadas se duplicaban las peticiones
  y el Market cortaba a mitad de inventario. El ritmo por defecto es de 3 s
  entre peticiones (`STEAM_MARKET_DELAY`), con reintento y espera ante un 429.
- **Moxfield**: su API suele bloquear el acceso automático (Cloudflare). Por eso la
  vía recomendada es **pegar la decklist** exportada; igualmente se intenta la API
  si das una URL/ID de mazo.
- **Enable Banking (imagin)**: agregador PSD2 regulado. El modo *restricted
  production* es gratuito para leer tus propias cuentas. La app firma cada
  llamada con un JWT RS256 (`PyJWT[crypto]`).
- **Trade Republic**: API **no oficial**, la misma que usa su app (login firmado
  con la clave del dispositivo + websocket `compactPortfolio`/`cash`/`ticker`).
  Puede romperse si TR cambia el protocolo; cuando pase, el fallo se ve en el
  WhatsApp semanal y queda la subida manual de PDF/CSV.
- **Histórico**: se guarda por duplicado en `data/price_history.json`
  (commiteado por GitHub Actions) y en la tabla `price_history` de la base de
  datos (lo que lee la web). La clave lleva delante el tipo, de modo que la
  misma serie cubre todo el patrimonio:

  | Clave | Qué guarda |
  |---|---|
  | `total:Patrimonio` | el patrimonio completo |
  | `cat:<categoría>` | el valor de una categoría entera |
  | `stock:<valor>` | el precio por título de una acción/ETF |
  | `card:<carta>` · `skin:<skin>` | el precio por unidad |

  Los artículos los registra el cron diario; el patrimonio lo registra cada
  resumen semanal (y el botón «Registrar punto de hoy» de la web), así que la
  serie del patrimonio no depende de que Steam o Magic estén configurados.
