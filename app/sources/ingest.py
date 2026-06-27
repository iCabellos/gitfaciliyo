"""
Ingesta de documentos: detecta el tipo (banco/TR/Nexo), lo parsea y guarda el
snapshot mensual en la base de datos. Reutilizado por el webhook de WhatsApp,
la subida web y el script de seed.
"""

import datetime

from . import bank, trade_republic, nexo, db
from .common import extract_rows


def detect_kind(path):
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
    return "bank"


def process(path):
    """Procesa un documento, guarda el snapshot mensual y devuelve un resumen."""
    kind = detect_kind(path)
    this_month = datetime.date.today().strftime("%Y-%m")
    if kind == "tr":
        r = trade_republic.parse(path)
        month = r.get("month") or this_month
        db.set_snapshot(month, r["category"], r["total"])
        return {"kind": "tr", "month": month, "category": r["category"], "value": r["total"],
                "summary": f"📈 Trade Republic: {r['total']:.2f} € guardado para {month} "
                           f"({len(r['positions'])} posiciones)."}
    if kind == "nexo":
        r = nexo.parse(path)
        month = r.get("month") or this_month
        db.set_snapshot(month, r["category"], r["total"])
        return {"kind": "nexo", "month": month, "category": r["category"], "value": r["total"],
                "summary": f"🪙 Nexo: {r['total']:.2f} € guardado para {month}."}
    r = bank.analyze(path)
    month = r.get("month") or this_month
    agg = r.get("aggregates") or {}
    agg["month"] = month
    persist_bank_aggregates(agg)
    value = r.get("available_balance") or 0.0
    return {"kind": "bank", "month": month, "category": "Liquidez (banco)", "value": value,
            "summary": f"🏦 Banco {month}: saldo {value:.2f} €, gastos {agg.get('gastos', 0):.2f} €, "
                       f"ganancias {agg.get('ganancias', 0):.2f} € ({len(r['transactions'])} mov.)."}


def persist_bank_aggregates(agg):
    """Guarda en la DB la liquidez (patrimonio) y los flujos mensuales del banco:
    gastos, ganancias e inversión (con prefijo '_flow:' para no sumarlos al patrimonio)."""
    month = agg.get("month")
    if not month:
        return
    if agg.get("liquidez") is not None:
        db.set_snapshot(month, "Liquidez (banco)", agg["liquidez"])
    for k in ("gastos", "ganancias", "inversion"):
        db.set_snapshot(month, "_flow:" + k, agg.get(k, 0) or 0)
