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
import tempfile

from flask import Flask, jsonify, render_template, request

from sources import bank, trade_republic, nexo, steam, moxfield

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def load_config():
    try:
        with open(_CONFIG_PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
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


@app.route("/")
def index():
    return render_template("index.html")


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
