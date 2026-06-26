# Montaje 100% gratuito

Todo lo programado corre en **GitHub Actions** (gratis, sin servidor) y el WhatsApp
se envía con **CallMeBot** (gratis para uso personal). El histórico de precios se
guarda en el propio repositorio. La web (gráficos + subir PDFs) es opcional en
**Render free**.

## Qué queda automático (ya configurado en el repo)

| Workflow (`.github/workflows/`) | Cuándo | Qué hace |
|---|---|---|
| `track-prices.yml` | cada día ~08:07 | precios de tus cartas (Scryfall) y skins (Steam/CSFloat) → los guarda en el repo |
| `weekly-whatsapp.yml` | lunes ~09:07 | te avisa por WhatsApp de lo que subió >10% algún día de la semana |
| `monthly-reminder.yml` | día 1 ~10:07 | te recuerda por WhatsApp adjuntar los PDFs del mes |

## Pasos que solo puedes hacer tú (5 min, una vez)

> WhatsApp no permite que nadie te escriba sin que tú autorices al emisor: por eso
> estos pasos los tienes que dar desde **tu** móvil y **tu** GitHub. Después, todo
> es automático.

1. **Activar CallMeBot (gratis):** en tu WhatsApp, añade el contacto **+34 644 51 95 23**
   y envíale el mensaje:
   `I allow callmebot to send me messages`
   Te responde con tu **API key** personal. *(Si ese número cambia, mira la web oficial de CallMeBot → WhatsApp.)*

2. **Guardar la API key como secreto del repo:** en GitHub →
   *Settings → Secrets and variables → Actions → New repository secret*:
   - `CALLMEBOT_APIKEY` = la key del paso 1
   - (opcional) `CALLMEBOT_PHONE` = `34640253466` (ya viene por defecto)
   - (opcional) `CSFLOAT_API_KEY` si quieres precios de skins por CSFloat

3. **Activar los cron:** las tareas programadas solo se ejecutan desde la rama
   **por defecto** del repo. Haz *merge* de este PR a `master`. Para probar sin
   esperar, ve a la pestaña **Actions**, elige un workflow y pulsa **Run workflow**
   (`workflow_dispatch`).

4. **Tu lista de cartas/skins:** edita `app/watchlist.json` (o pásamela y la creo).
   Acepta artes alternativos y foil:
   ```json
   {
     "cards": [
       "Sol Ring",
       { "name": "Lightning Bolt", "set": "2X2", "collector": "117", "foil": true }
     ],
     "skins": ["AK-47 | Redline (Field-Tested)"]
   }
   ```

## Web (opcional, también gratis)

En Render: **New → Blueprint** apuntando al repo (`render.yaml` en la raíz, plan *free*).
Te da una URL pública para ver los gráficos y subir PDFs. Se duerme cuando no la
usas y despierta al abrirla.

### Base de datos gratis (Supabase) — datos compartidos en móvil/PC/amigos

La app guarda el patrimonio en PostgreSQL si defines `DATABASE_URL` (si no, usa
SQLite efímero). Con una base gratuita externa los datos persisten y son los
mismos en cualquier dispositivo:

1. Crea un proyecto gratis en **https://supabase.com** (o **https://neon.tech**).
2. En Supabase → *Project Settings → Database → Connection string* → copia la
   **URI del Pooler** (la de `...pooler.supabase.com`, compatible con IPv4;
   la conexión directa NO funciona desde Render). Formato:
   `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
3. En Render → servicio **mi-patrimonio** → *Environment* → añade
   `DATABASE_URL` = esa URI → **Save** (redeploya). La app crea las tablas sola.

> El SSL se activa automáticamente. Si la conexión fallara, prueba la cadena del
> *Session pooler* (puerto 5432) en lugar del *Transaction pooler* (6543).

## ¿Recibir PDFs por WhatsApp?

El envío gratis (CallMeBot) es de una sola dirección (hacia ti). **Recibir** los
PDFs por WhatsApp para que se procesen solos necesita un número que pueda recibir
+ webhook (Twilio sandbox o Meta) y la web siempre activa. Mientras tanto, súbelos
en el panel web (es inmediato). Si quieres, te dejo también el camino con Twilio.
