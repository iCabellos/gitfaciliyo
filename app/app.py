"""
App web para desglosar gastos a partir de un extracto bancario en PDF.

Uso:
    pip install -r requirements.txt
    python app.py
    -> abre http://127.0.0.1:5000

El usuario sube el PDF, la app parsea y categoriza los movimientos y aplica
las reglas: Nexo (inversion) no es gasto, y los bizums recibidos que sean
devoluciones reducen el gasto correspondiente. Los enlaces bizum->gasto se
pueden revisar y ajustar manualmente; los totales se recalculan al instante.
"""

import os
import tempfile

from flask import Flask, jsonify, render_template, request

from parser import analyze

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    f = request.files.get("pdf")
    if f is None or f.filename == "":
        return jsonify({"error": "No se ha recibido ningún PDF."}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "El archivo debe ser un PDF."}), 400

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        f.save(tmp.name)
        tmp.close()
        result = analyze(tmp.name)
    except Exception as exc:  # noqa: BLE001 - mostrar el error al usuario
        return jsonify({"error": f"No se pudo procesar el PDF: {exc}"}), 500
    finally:
        os.unlink(tmp.name)

    return jsonify(result)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
