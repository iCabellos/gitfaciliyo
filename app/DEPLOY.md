# Despliegue público + alertas

La app está lista para desplegarse en cualquier hosting con Docker. El diseño:
**una sola instancia siempre activa** sirve la web y, con un **programador en
proceso**, hace el seguimiento diario de precios y el envío semanal por WhatsApp.
Un **disco persistente** en `/data` guarda los snapshots mensuales y el histórico
de precios.

> ⚠️ Importante sobre persistencia: en planes *free* que se duermen (y en los
> «cron jobs» de Render, que son instancias efímeras separadas), el histórico de
> precios no se conservaría entre ejecuciones. Por eso se usa **una instancia
> siempre activa + disco**: así el job diario y el semanal comparten los datos.

## La base de datos va FUERA de Render (Neon)

> ⚠️ **No uses la Postgres gratuita de Render.** [Caduca a los 30 días de
> creada](https://render.com/docs/free): al expirar «is inaccessible unless you
> upgrade it to a paid instance type», y 14 días después Render la **borra con
> todos los datos dentro**. Es un problema garantizado, no una posibilidad.

**Neon** ([neon.com](https://neon.com)) es la sustituta: Postgres gestionada,
plan gratuito **permanente**, sin tarjeta y **sin caducidad**. 0,5 GB por
proyecto y 100 CU-horas/mes, de sobra para esto. Su compute baja a cero a los
5 min de inactividad y despierta sola al conectarse; el tiempo dormida no gasta
horas. Como es Postgres, la app no cambia: `sources/db.py` habla por
`DATABASE_URL` con SQLAlchemy.

1. Crea cuenta en Neon → **New project** (región cercana, p. ej. Frankfurt).
2. Copia la cadena de conexión del **pooler** (el host lleva `-pooler`).
3. Pégala en Render → **Environment** → `DATABASE_URL` y guarda.
4. Comprueba en `/api/version` que dice `"db_ok": true`.

Alternativas que también son gratis para siempre, por si acaso:

| | Gratis siempre | Pega |
|---|---|---|
| **Neon** | ✅ sin tarjeta | Compute dormido: la primera consulta tarda un poco |
| Supabase | ✅ sin tarjeta | **Pausa el proyecto tras 1 semana sin actividad** y hay que despausarlo a mano |
| Aiven | ✅ sin tarjeta | 1 GB, solo regiones de DigitalOcean |
| ~~Render Postgres~~ | ❌ | Caduca a los 30 días y se borra |

## Opción A — Render (recomendada, con `render.yaml`)

1. Sube este repo a GitHub (ya está).
2. En Render: **New → Blueprint** y apunta al repo. Detectará `render.yaml` (en la raíz).
3. Render crea el servicio web. El plan **free** no caduca (solo se duerme por
   inactividad y despierta al abrirlo); el que caduca es la base de datos, por
   eso va en Neon.
4. En **Environment**, pega `DATABASE_URL` (Neon) y lo que quieras de los demás
   huecos que el blueprint ya deja creados.
5. Deploy. Te dará una URL pública tipo `https://mi-patrimonio.onrender.com`.

## Opción B — Cualquier host Docker (Fly.io, Railway, VPS…)

```bash
cd app
docker build -t mi-patrimonio .
docker run -d -p 8000:8000 \
  -e ENABLE_SCHEDULER=1 -e PATRIMONIO_DATA_DIR=/data \
  -e TWILIO_ACCOUNT_SID=... -e TWILIO_AUTH_TOKEN=... \
  -e TWILIO_WHATSAPP_FROM='whatsapp:+14155238886' \
  -e ALERT_WHATSAPP_TO='whatsapp:+34640253466' \
  -v patrimonio_data:/data \
  mi-patrimonio
```

Pon un proxy con HTTPS (Caddy/Nginx/Cloudflare) delante para la URL pública.

> La app lee `X-Forwarded-Proto` / `X-Forwarded-Host` (ProxyFix). Es lo que hace
> que la URL de retorno del banco salga como `https://tu-dominio/…` y no como
> `http://`, que es lo que Enable Banking rechazaría. Si pones tu propio proxy,
> asegúrate de que manda esas cabeceras.

## Conectar el banco (PSD2 · Enable Banking)

1. Regístrate en [enablebanking.com](https://enablebanking.com/docs/) y crea una
   aplicación en modo **restricted production** (gratis para leer TUS cuentas).
2. Abre tu panel en **⚙️ Configuración** y copia la **URL de retorno** que
   muestra la tarjeta del banco: es `https://<tu-app>/imagin/callback`. Regístrala
   en tu aplicación de Enable Banking **tal cual** (si no coincide carácter a
   carácter, el banco rechaza la autorización).
3. En Render → **Environment** pega `ENABLE_BANKING_APP_ID` y
   `ENABLE_BANKING_PRIVATE_KEY` (el PEM completo o su base64). El blueprint ya
   deja creados esos huecos.
4. Vuelve a ⚙️ Configuración, pulsa **🔎 Buscar bancos** y elige el tuyo de la
   lista (son los nombres exactos que reconoce Enable Banking).
5. Pulsa **Autorizar en mi banco**, confirma el SCA en la app del banco y, al
   volver, la conexión se completa sola.

El consentimiento PSD2 caduca a los ~90 días: cuando pase, el resumen semanal
avisa con ⚠️ y basta con volver a pulsar «Autorizar».

## WhatsApp (Twilio)

1. Crea cuenta en [twilio.com](https://www.twilio.com/) → **Messaging → Try WhatsApp**.
2. Activa el **sandbox**: envía el código `join <palabra>` desde tu WhatsApp
   (+34 640 25 34 66) al número del sandbox. Así autorizas la recepción.
3. Copia `Account SID` y `Auth Token` y configúralos como variables de entorno
   junto a `TWILIO_WHATSAPP_FROM=whatsapp:+14155238886` y
   `ALERT_WHATSAPP_TO=whatsapp:+34640253466`.
4. Para enviar fuera del sandbox (sin el `join`), Twilio exige un número de
   WhatsApp aprobado y una plantilla; el sandbox es suficiente para uso personal.

> Alternativa: Meta WhatsApp Cloud API (gratis hasta cierto volumen) en lugar de
> Twilio. El envío está aislado en `jobs/weekly_whatsapp.py:send_whatsapp`, así
> que cambiar de proveedor es tocar solo esa función.

## Precios y watchlist

- Copia `watchlist.example.json` a `data/watchlist.json` con tus cartas y skins.
- Cartas → **Scryfall** (precio diario, gratis). Skins → **Steam Market** por
  defecto, o **CSFloat** si defines `CSFLOAT_API_KEY`.

## Probar los jobs a mano

```bash
cd app
python -m jobs.track_prices        # registra los precios de hoy
python -m jobs.weekly_whatsapp     # calcula subidas >10% y envía (o simula sin credenciales)
```
