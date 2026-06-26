# Mi patrimonio

Panel personal que consolida banco, Trade Republic, Nexo, skins de CS:GO y cartas
Magic, con gráficos, seguimiento diario de precios y alertas por WhatsApp.

La aplicación vive en [`app/`](app/). Documentación: [`app/README.md`](app/README.md) ·
montaje gratis en [`app/FREE_SETUP.md`](app/FREE_SETUP.md) · despliegue en
[`app/DEPLOY.md`](app/DEPLOY.md).

## Desplegar la web (gratis, ~2 clics)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/iCabellos/gitfaciliyo)

1. Haz **merge de este trabajo a `master`** (el botón despliega la rama por defecto).
2. Pulsa el botón, entra con tu GitHub y autoriza. Render lee `render.yaml` (plan
   **free**) y construye la imagen.
3. En ~3 min tendrás una URL pública tipo `https://mi-patrimonio.onrender.com`
   (el plan free se duerme al estar inactiva y despierta al abrirla).

> Los mensajes de WhatsApp y el seguimiento de precios **no** dependen de la web:
> corren gratis en **GitHub Actions**. Pasos en [`app/FREE_SETUP.md`](app/FREE_SETUP.md).
