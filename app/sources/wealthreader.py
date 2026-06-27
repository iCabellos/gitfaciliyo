"""
Wealth Reader: banca automática (sin subir PDFs).

Conecta con el banco vía la API de Wealth Reader (agregador financiero) y trae
saldos y movimientos, que se clasifican con la MISMA lógica que el extracto en
PDF (gastos/ingresos, bizums, agregados).

Flujo:
  1. En el navegador, el widget de Wealth Reader autentica al usuario con su banco
     (las credenciales las gestiona Wealth Reader, no nosotros) y devuelve un `token`.
  2. El backend llama a POST https://api.wealthreader.com/entities/ con
     api_key + code (banco, p. ej. 'caixabank') + token.
  3. Se mapean las transacciones y se reutiliza bank.analyze_raw().

Requiere WEALTHREADER_API_KEY (variable de entorno). Sin ella, la ruta avisa.
Doc: https://www.wealthreader.com/api-reference/en/
"""

import datetime
import os

from . import http, bank

API_URL = "https://api.wealthreader.com/entities/"
SOURCE = "Banco (Wealth Reader)"


def _to_ddmmyyyy(iso):
    """'2026-06-27' (o ISO con hora) -> '27/06/2026' para bank.analyze_raw."""
    if not iso:
        return ""
    try:
        return datetime.datetime.fromisoformat(iso[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def fetch(code, token, date_from=None, date_to=None, api_key=None):
    api_key = api_key or os.environ.get("WEALTHREADER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta WEALTHREADER_API_KEY (configúrala en el servidor).")
    fields = {"api_key": api_key, "code": code, "token": token, "product_types": "accounts"}
    if date_from:
        fields["date_from"] = date_from
    if date_to:
        fields["date_to"] = date_to
    status, data = http.post_form(API_URL, fields)
    if status != 200 or not isinstance(data, dict):
        msg = (data or {}).get("error") if isinstance(data, dict) else None
        raise RuntimeError(f"Wealth Reader devolvió {status}. {msg or ''}".strip())
    return data


def analyze(code, token, date_from=None, date_to=None, api_key=None):
    """Trae los movimientos del banco y los clasifica como el extracto en PDF."""
    data = fetch(code, token, date_from, date_to, api_key)
    accounts = data.get("accounts", []) or data.get("data", {}).get("accounts", [])
    raw, balance = [], 0.0
    for acc in accounts:
        bal = (acc.get("balances") or {})
        balance += float(bal.get("available") or bal.get("current") or 0)
        for t in acc.get("transactions", []) or []:
            amount = float(t.get("amount") or 0)
            raw.append({
                "concept": t.get("description") or t.get("categorization") or "Movimiento",
                "date": _to_ddmmyyyy(t.get("operation_date") or t.get("value_date")),
                "amount": amount,
                "balance": float(t.get("balance") or 0),
            })
    raw = [r for r in raw if r["date"]]
    result = bank.analyze_raw(raw, round(balance, 2))
    result["source"] = SOURCE
    return result
