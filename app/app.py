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
"""

import base64
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

from sources import (bank, trade_republic, steam, moxfield, db, ingest,
                     wealthreader, patrimonio, autosync)
from jobs.weekly_whatsapp import send_whatsapp

APP_VERSION = "2026-07-r14-autosync"
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("patrimonio")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

_HERE = os.path.dirname(__file__)
_CONFIG_PATHS = (os.path.join(_HERE, "config.json"), os.path.join(_HERE, "config.example.json"))


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def load_config():
    """Lee config.json; si no existe, usa config.example.json como respaldo."""
    for path in _CONFIG_PATHS:
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return {}


def api_error(status=502):
    """Decorador: convierte excepciones de una ruta en JSON {error} (no 500 crudo).

    ValueError -> 400 (validación); el resto -> `status` (por defecto 502).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            except Exception as exc:  # noqa: BLE001
                log.exception("Error en %s", fn.__name__)
                return jsonify({"error": str(exc)}), status
        return wrapper
    return decorator


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
                    "sources": ["banco", "trade_republic", "csgo", "magic"]})


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
    db.reset_snapshots()
    return jsonify({"ok": True})


@app.route("/api/summary")
def api_summary():
    """Resumen de patrimonio + variación mensual (web y resumen WhatsApp)."""
    return jsonify(patrimonio.summary(db.get_snapshots()) or {})


@app.route("/api/monthly-summary", methods=["GET", "POST"])
def api_monthly_summary():
    """Envía por WhatsApp el patrimonio y su variación (cron semanal)."""
    expected = os.environ.get("SUMMARY_TOKEN", "").strip()
    if expected and request.args.get("token", "") != expected:
        return jsonify({"error": "No autorizado."}), 403
    s = patrimonio.summary(db.get_snapshots())
    if not s:
        return jsonify({"error": "Sin datos."}), 404
    sent = send_whatsapp(patrimonio.whatsapp_message(s))
    return jsonify({"sent": bool(sent), "summary": s})


# ---------------------------------------------------------------------------
# Sincronización automática (imaginBank vía Wealth Reader + Trade Republic)
# ---------------------------------------------------------------------------
def _authorized(token_env="SUMMARY_TOKEN"):
    expected = os.environ.get(token_env, "").strip()
    return not expected or request.args.get("token", "") == expected


@app.route("/api/autosync/status")
def api_autosync_status():
    """Estado de los conectores automáticos (claves y conexiones configuradas)."""
    return jsonify(autosync.status())


@app.route("/api/connections", methods=["GET", "POST"])
@api_error()
def api_connections():
    """Conexiones de banca automática (Wealth Reader): imaginBank y otras."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        conns = autosync.save_wr_connection((body.get("name") or "").strip(),
                                            (body.get("code") or "").strip(),
                                            (body.get("token") or "").strip())
        return jsonify({"ok": True, "connections": conns})
    return jsonify(autosync.get_connections())


@app.route("/api/tr/login", methods=["POST"])
@api_error()
def api_tr_login():
    """Paso 1 del login de Trade Republic: dispara el 2FA (app/SMS)."""
    from sources import traderepublic_api as tr
    body = request.get_json(silent=True) or {}
    phone = (body.get("phone") or "").strip()
    pin = (body.get("pin") or "").strip()
    if not phone or not pin:
        raise ValueError("Indica 'phone' (+34…) y 'pin' de Trade Republic.")
    return jsonify(tr.start_login(phone, pin))


@app.route("/api/tr/2fa", methods=["POST"])
@api_error()
def api_tr_2fa():
    """Paso 2: valida el código 2FA y guarda la sesión (no el PIN)."""
    from sources import traderepublic_api as tr
    body = request.get_json(silent=True) or {}
    process_id = (body.get("process_id") or "").strip()
    code = (body.get("code") or "").strip()
    if not process_id or not code:
        raise ValueError("Faltan 'process_id' y 'code' (el 2FA de Trade Republic).")
    cookies = tr.complete_login(process_id, code)
    autosync.save_tr_session(cookies)
    return jsonify({"ok": True, "message": "Sesión de Trade Republic guardada."})


@app.route("/api/weekly-sync", methods=["GET", "POST"])
def api_weekly_sync():
    """Tarea semanal: sincroniza todas las fuentes automáticas y avisa por WhatsApp."""
    if not _authorized():
        return jsonify({"error": "No autorizado."}), 403
    report = autosync.run_all()
    s = patrimonio.summary(db.get_snapshots())
    if s:
        report["sent"] = bool(send_whatsapp(patrimonio.whatsapp_message(s)))
        report["summary"] = s
    return jsonify(report)


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


@app.route("/api/trade-republic", methods=["POST"])
@api_error(500)
def api_trade_republic():
    return _process_upload("file", (".pdf", ".csv"), trade_republic.parse)


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
