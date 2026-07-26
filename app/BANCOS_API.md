# Estudio: conectar imagin (CaixaBank) y Trade Republic por API

Objetivo: que «Liquidez (banco)» y «Acciones / ETFs» se actualicen solas cada
semana, igual que ya hacen skins y cartas, sin subir PDFs a mano. Este
documento recoge las vías REALES disponibles a fecha 2026-07, con sus
requisitos y riesgos. Nada de lo de abajo está inventado: cada opción enlaza a
su documentación.

> **Estado: implementado.** Las dos vías recomendadas ya están en el código
> (`sources/enablebanking.py` y `sources/trade_republic_live.py`), enganchadas a
> `revalue.refresh_live()` y con su UI en la web. Lo único que falta es dar de
> alta las credenciales en el servidor (ver `.env.example`).

---

## 1. imagin (CaixaBank)

imagin no tiene API pública propia para particulares: es una marca de
CaixaBank y su acceso programático pasa por PSD2 (open banking). Tres vías:

### 1a. PSD2 directo (hub Redsys) — descartado
CaixaBank/imagin exponen su API XS2A en el hub de Redsys
(<https://market.apis-i.redsys.es/psd2/xs2a/nodos/caixabank>). Solo pueden
usarla TPPs con licencia AISP del Banco de España y certificado eIDAS.
Inviable para uso personal.

### 1b. Enable Banking — RECOMENDADA
<https://enablebanking.com/docs/> · cobertura ES: imagin y CaixaBank aparecen
como ASPSPs integrados (AIS en sandbox y producción; imagin migró en 2025 a
APIs específicas para clientes de la app imagin).

Por qué encaja aquí:
* **Alta self-service** y modo «restricted production»: gratis para acceder a
  TUS PROPIAS cuentas (el backend solo devuelve las cuentas vinculadas a la
  aplicación). Es exactamente el caso de este proyecto.
* API REST con JWT (firmas con clave privada propia); endpoints de sesiones,
  `accounts`, `balances` y `transactions`.
* SCA: la autorización se hace en la app de imagin (DNI/NIE + PIN/biometría).
  El consentimiento PSD2 caduca (90/180 días según banco) y hay que renovarlo
  repitiendo la autorización — es una limitación regulatoria, no del agregador.

Integración (hecha):
1. Registra la app en Enable Banking (modo restricted production) y define
   `ENABLE_BANKING_APP_ID`, `ENABLE_BANKING_PRIVATE_KEY` (PEM o su base64, o
   bien `ENABLE_BANKING_KEY_PATH`) y `ENABLE_BANKING_REDIRECT_URL`.
2. `sources/enablebanking.py`: JWT RS256 con el `kid` de la aplicación →
   `POST /auth` (URL de SCA) → `POST /sessions` (sesión reutilizable) →
   `GET /accounts/{uid}/balances` y `/transactions` (con paginación por
   `continuation_key`). Los movimientos se mapean al formato de
   `bank.analyze_raw()` y se persisten con `ingest.persist_bank_aggregates()`.
3. «Liquidez (banco)» entra en `revalue.refresh_live()`. Si el consentimiento ha
   caducado, el error real sube hasta el resumen de WhatsApp como ⚠️ (sin
   arrastrar el saldo viejo en silencio) y la web permite volver a autorizar.

Rutas: `GET /api/imagin/status`, `POST /api/imagin/auth`,
`POST /api/imagin/session`, `POST /api/imagin/refresh`.

### 1c. Wealth Reader — ya integrada, requiere API key comercial
El repo ya tiene `sources/wealthreader.py` y `POST /api/wealthreader`
(<https://www.wealthreader.com/api-reference/es/>). Soporta `caixabank`; si
imagin aparece como entidad separada se comprueba en su endpoint
`GET /entities/`. Pega: la API key es de contratación comercial (no hay tier
gratuito personal publicado). Mantenerla como vía alternativa si ya se dispone
de key.

### Descartada: GoCardless Bank Account Data (ex-Nordigen)
Era la opción gratuita clásica, pero desde mediados de 2025 **no acepta altas
nuevas** y está en proceso de cierre. No empezar nada nuevo sobre ella.

---

## 2. Trade Republic

**No existe API oficial pública.** La app habla con
`api.traderepublic.com` por websocket y la comunidad lo ha documentado:

### 2a. pytr (cliente no oficial) — la vía práctica
<https://github.com/pytr-org/pytr> (PyPI: `pytr`).
* Login con teléfono + PIN; el primer login hace «device pairing» (genera un
  keypair local que queda como dispositivo autorizado) y después ya no pide
  SMS en cada ejecución.
* Da lo que necesitamos: `portfolio()` (posiciones con valor actual),
  `cash()`, histórico y descarga de documentos.
* Riesgos reales: es ingeniería inversa (puede romperse con cualquier cambio
  de TR y va contra sus condiciones de uso → en el peor caso, bloqueo de la
  cuenta); desde mediados de 2026 TR añadió un token AWS WAF al login y el
  bypass de pytr sufre rate-limiting. Alternativas de la comunidad:
  `tr-api` (<https://github.com/cdamken/tr-api>, login con Playwright o
  importación de cookies) y `pytrpp` para exportar movimientos.

Integración (hecha):
1. `sources/trade_republic_live.py` implementa el protocolo directamente (sin
   depender del paquete `pytr`, para no arrastrar sus dependencias):
   * **Emparejado**, una sola vez: `POST /auth/account/reset/device` →
     código por SMS → `POST /auth/account/reset/device/{processId}/key` con la
     clave pública de un par EC P-256. La privada queda en el ajuste
     `tr_device_key` de la base de datos.
   * **Login** automático: se firma `{timestamp}.{cuerpo}` con esa clave
     (`X-Zeta-Timestamp` + `X-Zeta-Signature`) y se obtiene el `sessionToken`.
     Por eso el resumen semanal no vuelve a pedir ningún código.
   * **Cartera**: websocket `wss://api.traderepublic.com/` con
     `compactPortfolio` (ISIN + títulos), `instrument` (nombre y bolsa),
     `ticker` (precio) y `cash` (efectivo).
2. «Acciones / ETFs» entra en `revalue.refresh_live()`, guarda el snapshot del
   mes y además el **registro de posiciones** (nombre y nº de títulos) en la
   tabla `holdings`.
3. Si el login caduca o TR rompe el protocolo: error visible en el WhatsApp
   semanal, y siempre queda la ingesta por PDF/CSV
   (`sources/trade_republic.py`), que sigue siendo el camino manual soportado.

Rutas: `GET /api/trade-republic/status`, `POST /api/trade-republic/pair`,
`POST /api/trade-republic/pair/verify`, `POST /api/trade-republic/live`.

### 2b. Mantener PDF/CSV (estado actual)
Cero riesgo y ya funciona, pero exige subir el extracto a mano: es
exactamente lo que hace que el mensaje semanal repita el mismo importe. Se
mantiene como camino manual, no como sustituto de 2a.

---

## Resumen y orden propuesto

| Fuente | Vía | Coste | Riesgo | Estado |
|---|---|---|---|---|
| imagin | Enable Banking (restricted prod) | 0 € (cuentas propias) | Bajo (agregador regulado; renovar consentimiento cada 90/180 días) | **Implementado** (falta dar de alta las credenciales) |
| imagin | Wealth Reader | API key comercial | Bajo | Integrado, sin key |
| Trade Republic | websocket no oficial (protocolo de su app) | 0 € | Medio-alto (no oficial, ToS, WAF) | **Implementado** (falta emparejar el dispositivo) |
| Trade Republic | PDF/CSV manual | 0 € | Ninguno | Funciona hoy |

Las dos vías por API asumen su fragilidad: cuando se rompan, el fallo se ve en
el WhatsApp semanal y la vía manual sigue disponible. Nunca se muestran datos
antiguos disfrazados de nuevos.
