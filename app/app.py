"""
Panel de patrimonio personal: consolida banco (PDF o Wealth Reader), Trade
Republic, skins de CS:GO (Steam) y cartas Magic (Scryfall), con valoración en
vivo, histórico mensual en base de datos y resumen por WhatsApp.

Uso local:
    pip install -r requirements.txt
    python app.py            # http://127.0.0.1:5000

API:
    GET  /api/snapshots                         histórico mensual del patrimonio
    POST /api/snapshot                          guarda una categoría/mes
    GET  /api/summary                           resumen + variación mensual
    POST /api/monthly-summary?token=...         envía el resumen por WhatsApp
    POST /api/bank            (PDF)             extracto -> gasto neto + liquidez
    POST /api/wealthreader    {code,token}      banca automática (Wealth Reader)
    POST /api/trade-republic  (PDF/CSV)         acciones / ETFs
    GET  /api/steam?steamid=...                 skins CS:GO (Steam Market)
    POST /api/magic           {moxfield|decklist}  cartas Magic (Scryfall)
    GET/POST /api/cards                         lista de cartas guardada
    POST /webhook/whatsapp                      ingesta de PDFs por WhatsApp

    -- imagin por PSD2 (Enable Banking) --
    GET  /api/imagin/status                     si el banco está autorizado
    POST /api/imagin/auth                       inicia la autorización (SCA)
    POST /api/imagin/session  {code}            completa la autorización
    POST /api/imagin/refresh                    saldo + movimientos en vivo

    -- Trade Republic por su API --
    GET  /api/trade-republic/status             si el dispositivo está emparejado
    POST /api/trade-republic/pair {phone,pin}   pide el código de emparejado
    POST /api/trade-republic/pair/verify {code} completa el emparejado
    POST /api/trade-republic/live               cartera en vivo

    -- histórico semanal de TODO el patrimonio --
    GET  /api/prices/weekly[?kind=cat,card]     serie SEMANAL (total, categorías,
                                                acciones, cartas y skins)
    GET  /api/prices/movers?threshold=5         movimientos de la semana
    POST /api/prices/record                     registra el punto de hoy
    GET  /api/holdings?month=YYYY-MM            valores registrados y sus títulos
"""

import base64
import datetime
import functools
import hashlib
import json
import logging
import os
import re
import tempfile
import urllib.request
from xml.sax.saxutils import escape as xml_escape

from flask import Flask, jsonify, render_template, request

from sources import (bank, trade_republic, trade_republic_live, steam, moxfield,
                     db, ingest, wealthreader, enablebanking, patrimonio,
                     prices, revalue)
from jobs.weekly_whatsapp import send_whatsapp, coverage_warnings

APP_VERSION = "2026-07-r15-apis"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("patrimonio")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

_HERE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(_HERE, "config.json")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def load_config():
    """Lee TU config.json. Si no existe, no hay configuración: {}.

    NUNCA cae en config.example.json. Ese fichero es una plantilla y está en el
    repo; usarlo como respaldo hacía que la web propusiera —y valorara— un
    inventario de Steam que no es el tuyo, y que ese id acabara guardado como si
    lo hubieras elegido. Sin config.json, cada fuente pide su dato y falla a la
    vista si no se lo das.
    """
    try:
        with open(CONFIG_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def api_error(status=502):
    """Decorador: convierte excepciones de una ruta en JSON {error} (no 500 crudo).

    ValueError -> 400 (validación); fuente sin conectar -> 409 (no es un fallo,
    es que falta autorizarla); el resto -> `status` (por defecto 502).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            except (enablebanking.NotConfigured, trade_republic_live.NotPaired) as exc:
                return jsonify({"error": str(exc), "connected": False}), 409
            except Exception as exc:  # noqa: BLE001
                log.exception("Error en %s", fn.__name__)
                return jsonify({"error": str(exc)}), status
        return wrapper
    return decorator


def _this_month():
    return datetime.date.today().strftime("%Y-%m")


def _save_upload(file_storage, suffixes):
    """Guarda el archivo subido en un temporal y devuelve la ruta (o ValueError)."""
    if file_storage is None or not (file_storage.filename or ""):
        raise ValueError("No se ha recibido ningún archivo.")
    name = file_storage.filename.lower()
    if not name.endswith(suffixes):
        raise ValueError(f"El archivo debe ser {' o '.join(suffixes)}.")
    suffix = os.path.splitext(name)[1] or suffixes[0]
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    file_storage.save(tmp.name)
    tmp.close()
    return tmp.name


def _process_upload(field, suffixes, handler):
    """Guarda el adjunto, lo procesa con `handler(path)` y limpia el temporal."""
    path = _save_upload(request.files.get(field), suffixes)
    try:
        return jsonify(handler(path))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    return resp


# ---------------------------------------------------------------------------
# Páginas y meta
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/version")
def api_version():
    return jsonify({"version": APP_VERSION, "db": db.backend(),
                    "sources": ["banco", "imagin", "trade_republic", "csgo", "magic"]})


@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.svg")


@app.route("/api/config")
def api_config():
    cfg = load_config()
    return jsonify({
        "currency": cfg.get("currency", "eur"),
        "steamid": cfg.get("steam", {}).get("steamid64", ""),
        "moxfield": cfg.get("moxfield", {}).get("default_deck", ""),
    })


# ---------------------------------------------------------------------------
# Snapshots / resumen
# ---------------------------------------------------------------------------
@app.route("/api/snapshots")
def api_snapshots_get():
    """Histórico mensual de patrimonio: { 'YYYY-MM': { categoria: valor } }."""
    return jsonify(db.get_snapshots())


@app.route("/api/snapshot", methods=["POST"])
def api_snapshot_post():
    """Guarda/actualiza el valor de una categoría para un mes concreto."""
    body = request.get_json(silent=True) or {}
    month = (body.get("month") or "").strip()
    category = (body.get("category") or "").strip()
    value = body.get("value")
    if not MONTH_RE.match(month) or not category or not isinstance(value, (int, float)):
        return jsonify({"error": "Datos inválidos (month=YYYY-MM, category, value)."}), 400
    db.set_snapshot(month, category, value)
    return jsonify({"ok": True, "snapshots": db.get_snapshots()})


@app.route("/api/snapshots/reset", methods=["POST"])
def api_snapshots_reset():
    """Borra el histórico mensual y el registro de valores que lo acompaña."""
    db.reset_snapshots()
    db.reset_holdings()
    return jsonify({"ok": True})


@app.route("/api/summary")
def api_summary():
    """Resumen de patrimonio + variación mensual (web y resumen WhatsApp)."""
    return jsonify(patrimonio.summary(db.get_snapshots()) or {})


@app.route("/api/monthly-summary", methods=["GET", "POST"])
def api_monthly_summary():
    """Envía por WhatsApp el patrimonio y su variación (cron semanal).

    Antes de componer el mensaje revaloriza EN VIVO las skins (Steam Market) y
    las cartas (Scryfall) con la configuración guardada, para que esas cifras
    cambien cada semana sin abrir la web. Si una fuente configurada falla, el
    error va en el propio mensaje (nunca se disfraza con el valor antiguo).
    """
    expected = os.environ.get("SUMMARY_TOKEN", "").strip()
    if expected and request.args.get("token", "") != expected:
        return jsonify({"error": "No autorizado."}), 403
    refreshed, refresh_errors, skipped = revalue.refresh_live()
    snapshots = db.get_snapshots()
    s = patrimonio.summary(snapshots)
    if not s:
        return jsonify({"error": "Sin datos.", "refresh_errors": refresh_errors,
                        "not_connected": skipped}), 404
    # Registrar el punto de hoy de TODO el patrimonio antes de calcular los
    # movimientos: así el histórico semanal incluye el total, cada categoría y
    # cada acción, y no solo las cartas y skins que sigue el cron diario.
    holdings = db.get_holdings(month=_latest_holdings_month())
    prices.record_portfolio(snapshots=snapshots, holdings=holdings)
    history = prices.history()
    movers = prices.movers(history, threshold=prices.THRESHOLD)
    warnings = [f"{cat} no se pudo revalorizar: {err}"
                for cat, err in refresh_errors.items()]
    warnings += [f"{cat} no está conectado: {why}" for cat, why in skipped.items()]
    warnings += coverage_warnings(prices.coverage(history))
    message = patrimonio.whatsapp_message(
        s, warnings=warnings, movers=movers, threshold=prices.THRESHOLD,
        holdings=holdings)
    sent = send_whatsapp(message)
    return jsonify({"sent": bool(sent), "summary": s, "refreshed": refreshed,
                    "refresh_errors": refresh_errors, "not_connected": skipped,
                    "movers": movers, "message": message})


# ---------------------------------------------------------------------------
# Precios: histórico semanal de cartas y skins
# ---------------------------------------------------------------------------
def _threshold_arg():
    try:
        return max(0.0, float(request.args.get("threshold", prices.THRESHOLD)))
    except (TypeError, ValueError):
        return prices.THRESHOLD


def _days_arg(default=180):
    try:
        return max(1, int(request.args.get("days", default)))
    except (TypeError, ValueError):
        return default


def _kinds_arg():
    """?kind=card,skin -> ('card','skin'). Sin parámetro, todos los tipos."""
    raw = (request.args.get("kind") or "").strip()
    kinds = tuple(k for k in (p.strip() for p in raw.split(",")) if k)
    return kinds or None


@app.route("/api/prices/weekly")
@api_error(500)
def api_prices_weekly():
    """Serie SEMANAL de TODO el patrimonio: total, categorías, acciones, cartas y skins.

    `items` trae cada serie con su tipo; `portfolio` repite solo las agregadas
    (patrimonio total y categorías) porque son las del gráfico de cabecera.
    """
    history = prices.history(days=_days_arg())
    return jsonify({"items": prices.weekly_table(history, kinds=_kinds_arg()),
                    "portfolio": prices.weekly_table(history, kinds=prices.PORTFOLIO_KINDS),
                    "coverage": prices.coverage(history),
                    "kinds": prices.KIND_LABEL,
                    "total_key": prices.TOTAL_KEY,
                    "threshold": prices.THRESHOLD})


@app.route("/api/prices/movers")
@api_error(500)
def api_prices_movers():
    """Lo que se ha movido al menos el umbral (por defecto 5%), en todo el patrimonio."""
    history = prices.history(days=_days_arg(60))
    threshold = _threshold_arg()
    return jsonify({"threshold": threshold,
                    "movers": prices.movers(history, threshold=threshold,
                                            kinds=_kinds_arg()),
                    "coverage": prices.coverage(history)})


@app.route("/api/prices/record", methods=["POST"])
@api_error(500)
def api_prices_record():
    """Registra ahora mismo el punto del patrimonio completo en el histórico."""
    saved = prices.record_portfolio()
    return jsonify({"recorded": saved, "coverage": prices.coverage(prices.history())})


# ---------------------------------------------------------------------------
# Registro de posiciones (nombre y cantidad de acciones/ETFs)
# ---------------------------------------------------------------------------
def _latest_holdings_month():
    months = db.holdings_months()
    return months[0] if months else None


@app.route("/api/holdings")
@api_error(500)
def api_holdings():
    """Valores registrados con su nombre y número de títulos."""
    month = (request.args.get("month") or "").strip() or _latest_holdings_month()
    rows = db.get_holdings(month=month) if month else []
    return jsonify({"month": month, "months": db.holdings_months(),
                    "holdings": rows,
                    "titles": round(sum(r.get("quantity") or 0 for r in rows), 4),
                    "total": round(sum(r.get("value") or 0 for r in rows), 2)})


# ---------------------------------------------------------------------------
# Fuentes
# ---------------------------------------------------------------------------
def _bank_and_persist(path):
    data = bank.analyze(path)
    ingest.persist_bank_aggregates(data.get("aggregates") or {})
    return data


@app.route("/api/bank", methods=["POST"])
@api_error(500)
def api_bank():
    return _process_upload("file", (".pdf",), _bank_and_persist)


def _trade_republic_and_persist(path):
    data = trade_republic.parse(path)
    month = data.get("month") or _this_month()
    ingest.persist_positions(month, trade_republic.SOURCE, data["positions"])
    db.set_snapshot(month, data["category"], data["total"])
    return data


@app.route("/api/trade-republic", methods=["POST"])
@api_error(500)
def api_trade_republic():
    return _process_upload("file", (".pdf", ".csv"), _trade_republic_and_persist)


# ---------------------------------------------------------------------------
# imagin (CaixaBank) por PSD2: Enable Banking
# ---------------------------------------------------------------------------
@app.route("/api/imagin/status")
def api_imagin_status():
    saved = db.get_setting(enablebanking.SESSION_SETTING, {}) or {}
    return jsonify({
        "connected": bool(saved.get("session_id") and saved.get("accounts")),
        "accounts": [{"name": a.get("name"), "iban_end": (a.get("iban") or "")[-4:]}
                     for a in saved.get("accounts", [])],
        "valid_until": saved.get("access_valid_until"),
        "aspsp": saved.get("aspsp") or enablebanking.default_aspsp(),
    })


@app.route("/api/imagin/auth", methods=["POST"])
@api_error()
def api_imagin_auth():
    """Devuelve la URL donde imagin pide el SCA para autorizar la lectura."""
    body = request.get_json(silent=True) or {}
    return jsonify(enablebanking.start_auth(
        redirect_url=(body.get("redirect_url") or "").strip() or None,
        aspsp=(body.get("aspsp") or "").strip() or None))


@app.route("/api/imagin/session", methods=["POST"])
@api_error()
def api_imagin_session():
    """Cambia el `code` del retorno de imagin por una sesión reutilizable."""
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or request.args.get("code") or "").strip()
    saved = enablebanking.complete_auth(code)
    return jsonify({"connected": True, "accounts": saved["accounts"],
                    "valid_until": saved.get("access_valid_until")})


@app.route("/api/imagin/refresh", methods=["POST"])
@api_error()
def api_imagin_refresh():
    """Saldo y movimientos reales de imagin, guardados como el extracto PDF."""
    data = enablebanking.analyze()
    ingest.persist_bank_aggregates(data.get("aggregates") or {})
    return jsonify(data)


@app.route("/api/imagin/disconnect", methods=["POST"])
def api_imagin_disconnect():
    enablebanking.disconnect()
    return jsonify({"connected": False})


# ---------------------------------------------------------------------------
# Trade Republic por su API (emparejado del dispositivo + cartera en vivo)
# ---------------------------------------------------------------------------
@app.route("/api/trade-republic/status")
def api_tr_status():
    saved = db.get_setting(trade_republic_live.DEVICE_KEY_SETTING, {}) or {}
    return jsonify({"paired": bool(saved.get("pem")),
                    "phone_end": (saved.get("phone") or "")[-3:],
                    "paired_at": saved.get("paired_at")})


@app.route("/api/trade-republic/pair", methods=["POST"])
@api_error()
def api_tr_pair():
    """Paso 1 del emparejado: Trade Republic manda un código al móvil."""
    body = request.get_json(silent=True) or {}
    return jsonify(trade_republic_live.pair_start(
        phone=(body.get("phone") or "").strip() or None,
        pin=(body.get("pin") or "").strip() or None))


@app.route("/api/trade-republic/pair/verify", methods=["POST"])
@api_error()
def api_tr_pair_verify():
    """Paso 2: registra el dispositivo con el código recibido."""
    body = request.get_json(silent=True) or {}
    return jsonify(trade_republic_live.pair_complete(
        (body.get("process_id") or "").strip(),
        (body.get("code") or "").strip(),
        phone=(body.get("phone") or "").strip() or None,
        pin=(body.get("pin") or "").strip() or None))


@app.route("/api/trade-republic/live", methods=["GET", "POST"])
@api_error()
def api_tr_live():
    """Cartera real de Trade Republic: posiciones, títulos y efectivo."""
    data = trade_republic_live.analyze()
    month = data.get("month") or _this_month()
    ingest.persist_positions(month, trade_republic_live.SOURCE, data["positions"])
    db.set_snapshot(month, data["category"], data["total"])
    return jsonify(data)


@app.route("/api/trade-republic/unpair", methods=["POST"])
def api_tr_unpair():
    trade_republic_live.unpair()
    return jsonify({"paired": False})


@app.route("/api/wealthreader", methods=["POST"])
@api_error()
def api_wealthreader():
    """Banca automática: trae movimientos del banco vía Wealth Reader y los clasifica."""
    body = request.get_json(silent=True) or {}
    code = (body.get("code") or "").strip()
    token = (body.get("token") or "").strip()
    if not code or not token:
        raise ValueError("Faltan 'code' (banco) y 'token' (del widget de Wealth Reader).")
    data = wealthreader.analyze(code, token, body.get("date_from"), body.get("date_to"))
    ingest.persist_bank_aggregates(data.get("aggregates") or {})
    return jsonify(data)


def _cached_daily(key, compute, refresh=False):
    """Valoración cacheada una vez al día (evita golpear Steam/Scryfall por visita)."""
    if not refresh:
        hit = db.cache_get_today(key)
        if hit is not None:
            hit["cached"] = True
            return hit
    data = compute()
    db.cache_put(key, data)
    data["cached"] = False
    return data


@app.route("/api/steam")
@api_error()
def api_steam():
    steamid = (request.args.get("steamid") or load_config().get("steam", {}).get("steamid64", "")).strip()
    currency = request.args.get("currency", "eur")
    if not steamid or steamid.startswith("TU_"):
        raise ValueError("Indica tu SteamID64 (inventario en público).")
    # Recuerda el SteamID para que el seguimiento diario siga TUS skins.
    if db.get_setting("steam_id64", "") != steamid:
        db.set_setting("steam_id64", steamid)
    key = f"steam:{steamid}:{currency}"
    return jsonify(_cached_daily(key, lambda: steam.analyze(steamid, currency),
                                 refresh=request.args.get("refresh") == "1"))


@app.route("/api/magic", methods=["POST"])
@api_error()
def api_magic():
    body = request.get_json(silent=True) or {}
    reference = (body.get("moxfield") or "").strip()
    decklist = body.get("decklist") or ""
    if not reference and not decklist.strip():
        raise ValueError("Indica una URL/ID de Moxfield o pega una decklist.")
    db.set_setting("magic_cards", {"reference": reference, "decklist": decklist})
    key = "magic:" + hashlib.sha1((reference + "|" + decklist).encode()).hexdigest()
    return jsonify(_cached_daily(key, lambda: moxfield.analyze(reference=reference, decklist=decklist),
                                 refresh=bool(body.get("refresh"))))


@app.route("/api/cards", methods=["GET", "POST"])
def api_cards():
    """Lista de cartas guardada (precarga/guarda el gestor de cartas)."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        db.set_setting("magic_cards", {"reference": (body.get("reference") or "").strip(),
                                       "decklist": body.get("decklist") or ""})
        return jsonify({"ok": True})
    return jsonify(db.get_setting("magic_cards", {"reference": "", "decklist": ""}))


# ---------------------------------------------------------------------------
# WhatsApp entrante (Twilio): ingesta de PDFs adjuntos
# ---------------------------------------------------------------------------
def _download_twilio_media(url):
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    req = urllib.request.Request(url)
    if sid and token:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()


def _twiml(message):
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>'
           f"<Response><Message>{xml_escape(message)}</Message></Response>")
    return app.response_class(xml, mimetype="text/xml")


def _webhook_authorized():
    expected = os.environ.get("WHATSAPP_WEBHOOK_TOKEN", "").strip()
    return not expected or request.args.get("token", "") == expected


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_inbound():
    """Webhook de Twilio: procesa PDFs/CSV adjuntos enviados por WhatsApp."""
    if not _webhook_authorized():
        return _twiml("No autorizado."), 403
    try:
        num_media = int(request.form.get("NumMedia", "0"))
    except ValueError:
        num_media = 0
    if not num_media:
        return _twiml("👋 Envíame el PDF del banco o de Trade Republic (o un CSV) y lo añado "
                      "a tu patrimonio. También valoro cartas y skins desde la web.")
    replies = []
    for i in range(num_media):
        url = request.form.get(f"MediaUrl{i}", "")
        if not url:
            continue
        ctype = request.form.get(f"MediaContentType{i}", "")
        suffix = ".csv" if ("csv" in ctype or "excel" in ctype) else ".pdf"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(_download_twilio_media(url))
            tmp.close()
            replies.append(ingest.process(tmp.name)["summary"])
        except Exception as exc:  # noqa: BLE001
            log.exception("Webhook: fallo procesando adjunto")
            replies.append(f"⚠️ No pude procesar un adjunto: {exc}")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    return _twiml("\n".join(replies) or "No encontré adjuntos válidos.")


# Programador en proceso (solo en instancia siempre activa).
if os.environ.get("ENABLE_SCHEDULER") == "1":
    try:
        from jobs.scheduler import start_scheduler
        start_scheduler()
    except Exception:  # noqa: BLE001
        log.exception("No se pudo iniciar el scheduler")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG") == "1")
