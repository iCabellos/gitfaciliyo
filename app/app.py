"""
Panel de patrimonio personal: consolida banco, Trade Republic, Nexo,
skins de CS:GO (Steam) y cartas Magic (Moxfield + precios Scryfall en vivo).

Uso:
    pip install -r requirements.txt
    python app.py            # http://127.0.0.1:5000

Fuentes por informe (subes archivo cada mes):
    POST /api/bank             (PDF del banco)        -> gastos netos
    POST /api/trade-republic   (PDF/CSV)              -> acciones/ETFs
    POST /api/nexo             (CSV/PDF)              -> cripto
Fuentes en vivo (API):
    GET  /api/steam?steamid=...&currency=eur          -> skins CS:GO
    POST /api/magic  {moxfield|decklist}              -> cartas Magic
    GET  /api/config                                  -> valores por defecto
"""

import json
import os
import re
import tempfile

from flask import Flask, jsonify, render_template, request

from sources import bank, trade_republic, nexo, steam, moxfield

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

_HERE = os.path.dirname(__file__)
_CONFIG_PATH = os.path.join(_HERE, "config.json")
_CONFIG_EXAMPLE = os.path.join(_HERE, "config.example.json")


def load_config():
    """Lee config.json; si no existe, usa config.example.json como respaldo."""
    for path in (_CONFIG_PATH, _CONFIG_EXAMPLE):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return {}


def _save_upload(file_storage, suffixes):
    """Guarda el archivo subido en un temporal y devuelve la ruta."""
    name = (file_storage.filename or "").lower()
    if not name.endswith(suffixes):
        raise ValueError(f"El archivo debe ser {' o '.join(suffixes)}.")
    suffix = os.path.splitext(name)[1] or suffixes[0]
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    file_storage.save(tmp.name)
    tmp.close()
    return tmp.name


_DATA_DIR = os.environ.get("PATRIMONIO_DATA_DIR") or os.path.join(_HERE, "data")
_SNAPSHOTS = os.path.join(_DATA_DIR, "snapshots.json")


def _read_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/snapshots", methods=["GET"])
def api_snapshots_get():
    """Histórico mensual de patrimonio: { 'YYYY-MM': { categoria: valor } }."""
    return jsonify(_read_json(_SNAPSHOTS, {}))


def _record_snapshot(month, category, value):
    snaps = _read_json(_SNAPSHOTS, {})
    snaps.setdefault(month, {})[category] = round(float(value), 2)
    _write_json(_SNAPSHOTS, snaps)
    return snaps


@app.route("/api/snapshot", methods=["POST"])
def api_snapshot_post():
    """Guarda/actualiza el valor de una categoría para un mes concreto."""
    body = request.get_json(silent=True) or {}
    month = (body.get("month") or "").strip()
    category = (body.get("category") or "").strip()
    value = body.get("value")
    if not re.match(r"^\d{4}-\d{2}$", month) or not category or not isinstance(value, (int, float)):
        return jsonify({"error": "Datos inválidos (month=YYYY-MM, category, value)."}), 400
    return jsonify({"ok": True, "snapshots": _record_snapshot(month, category, value)})


@app.route("/api/snapshots/reset", methods=["POST"])
def api_snapshots_reset():
    _write_json(_SNAPSHOTS, {})
    return jsonify({"ok": True})


@app.route("/api/config")
def api_config():
    cfg = load_config()
    return jsonify({
        "currency": cfg.get("currency", "eur"),
        "steamid": cfg.get("steam", {}).get("steamid64", ""),
        "moxfield": cfg.get("moxfield", {}).get("default_deck", ""),
    })


def _file_route(field, suffixes, handler):
    f = request.files.get(field)
    if f is None or f.filename == "":
        return jsonify({"error": "No se ha recibido ningún archivo."}), 400
    try:
        path = _save_upload(f, suffixes)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        return jsonify(handler(path))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": f"No se pudo procesar: {exc}"}), 500
    finally:
        os.unlink(path)


@app.route("/api/bank", methods=["POST"])
def api_bank():
    return _file_route("file", (".pdf",), bank.analyze)


@app.route("/api/trade-republic", methods=["POST"])
def api_trade_republic():
    return _file_route("file", (".pdf", ".csv"), trade_republic.parse)


@app.route("/api/nexo", methods=["POST"])
def api_nexo():
    return _file_route("file", (".csv", ".pdf"), nexo.parse)


@app.route("/api/steam")
def api_steam():
    steamid = (request.args.get("steamid") or load_config().get("steam", {}).get("steamid64", "")).strip()
    currency = request.args.get("currency", "eur")
    if not steamid or steamid.startswith("TU_"):
        return jsonify({"error": "Indica tu SteamID64 (inventario en público)."}), 400
    try:
        return jsonify(steam.analyze(steamid, currency))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502


@app.route("/api/magic", methods=["POST"])
def api_magic():
    body = request.get_json(silent=True) or {}
    reference = (body.get("moxfield") or "").strip()
    decklist = body.get("decklist") or ""
    if not reference and not decklist.strip():
        return jsonify({"error": "Indica una URL/ID de Moxfield o pega una decklist."}), 400
    try:
        return jsonify(moxfield.analyze(reference=reference, decklist=decklist))
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 502


# ---------------------------------------------------------------------------
# WhatsApp entrante: recibir y procesar PDFs enviados por WhatsApp (Twilio).
# ---------------------------------------------------------------------------
import base64                       # noqa: E402
import datetime                     # noqa: E402
import urllib.request               # noqa: E402

from sources.common import extract_rows   # noqa: E402


def _detect_kind(path):
    """Decide si un documento es del banco, Trade Republic o Nexo."""
    name = path.lower()
    if name.endswith(".csv"):
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            head = fh.read(2000).lower()
        if any(w in head for w in ("asset", "currency", "coin", "crypto")):
            return "nexo"
        return "tr"
    text = " ".join(c for row in extract_rows(path) for c in row)
    low = text.lower()
    if "trade republic" in low or "patrimonio neto" in low or "cuenta de valores" in low:
        return "tr"
    if "nexo" in low and "bizum" not in low:
        return "nexo"
    # Banco: bizum, saldo disponible o un IBAN sin pinta de cartera de valores.
    return "bank"


def _process_document(path):
    """Procesa un documento, guarda el snapshot mensual y devuelve un resumen."""
    kind = _detect_kind(path)
    this_month = datetime.date.today().strftime("%Y-%m")
    if kind == "tr":
        r = trade_republic.parse(path)
        month = r.get("month") or this_month
        _record_snapshot(month, r["category"], r["total"])
        return f"📈 Trade Republic: {r['total']:.2f} € guardado para {month} ({len(r['positions'])} posiciones)."
    if kind == "nexo":
        r = nexo.parse(path)
        month = r.get("month") or this_month
        _record_snapshot(month, r["category"], r["total"])
        return f"🪙 Nexo: {r['total']:.2f} € guardado para {month}."
    r = bank.analyze(path)
    month = r.get("month") or this_month
    if r.get("available_balance") is not None:
        _record_snapshot(month, "Liquidez (banco)", r["available_balance"])
    return (f"🏦 Banco: saldo {r.get('available_balance', 0):.2f} € guardado para {month} "
            f"({len(r['transactions'])} movimientos).")


def _download_twilio_media(url):
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    req = urllib.request.Request(url)
    if sid and token:
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        req.add_header("Authorization", "Basic " + auth)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()


def _twiml(message):
    xml = ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
           f"<Response><Message>{message}</Message></Response>")
    return app.response_class(xml, mimetype="text/xml")


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_inbound():
    """Webhook de Twilio: procesa PDFs/CSV adjuntos enviados por WhatsApp."""
    try:
        num_media = int(request.form.get("NumMedia", "0"))
    except ValueError:
        num_media = 0
    if not num_media:
        return _twiml("👋 Envíame el PDF del banco, de Trade Republic o de Nexo (o un CSV) "
                      "y lo añado a tu patrimonio. También valoro tus cartas y skins desde la web.")

    replies = []
    for i in range(num_media):
        ctype = request.form.get(f"MediaContentType{i}", "")
        url = request.form.get(f"MediaUrl{i}", "")
        if not url:
            continue
        suffix = ".csv" if "csv" in ctype or "excel" in ctype else ".pdf"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(_download_twilio_media(url))
            tmp.close()
            replies.append(_process_document(tmp.name))
        except Exception as exc:  # noqa: BLE001
            replies.append(f"⚠️ No pude procesar un adjunto: {exc}")
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    return _twiml("\n".join(replies) or "No encontré adjuntos válidos.")


# Programador en proceso para la versión desplegada (instancia siempre activa).
if os.environ.get("ENABLE_SCHEDULER") == "1":
    try:
        from jobs.scheduler import start_scheduler
        start_scheduler()
    except Exception as exc:  # noqa: BLE001
        print("No se pudo iniciar el scheduler:", exc)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
