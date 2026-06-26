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

## Opción A — Render (recomendada, con `render.yaml`)

1. Sube este repo a GitHub (ya está).
2. En Render: **New → Blueprint** y apunta al repo. Detectará `render.yaml` (en la raíz).
3. Render crea un servicio web (plan **starter**, no *free*) con disco de 1 GB.
4. En **Environment**, rellena las variables de Twilio (ver abajo). `ENABLE_SCHEDULER`
   ya viene a `1`.
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
