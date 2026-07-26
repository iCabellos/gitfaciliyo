"""
Ingesta de documentos: detecta el tipo (banco/TR/Nexo), lo parsea y guarda el
snapshot mensual en la base de datos. Reutilizado por el webhook de WhatsApp,
la subida web y el script de seed.
"""

import datetime

from . import bank, trade_republic, db
from .common import extract_rows


def detect_kind(path):
    """Decide si un documento es del banco o de Trade Republic."""
    if path.lower().endswith(".csv"):
        return "tr"
    text = " ".join(c for row in extract_rows(path) for c in row)
    low = text.lower()
    # Señales fuertes del banco primero ('trade republic' puede salir como
    # concepto de una transferencia en el extracto bancario).
    if "saldo disponible" in low or "bizum" in low:
        return "bank"
    if "patrimonio neto" in low or "cuenta de valores" in low:
        return "tr"
    return "bank"


def process(path):
    """Procesa un documento, guarda el snapshot mensual y devuelve un resumen."""
    kind = detect_kind(path)
    this_month = datetime.date.today().strftime("%Y-%m")
    if kind == "tr":
        r = trade_republic.parse(path)
        month = r.get("month") or this_month
        db.set_snapshot(month, r["category"], r["total"])
        persist_positions(month, trade_republic.SOURCE, r["positions"])
        return {"kind": "tr", "month": month, "category": r["category"], "value": r["total"],
                "summary": f"📈 Trade Republic: {r['total']:.2f} € guardado para {month} "
                           f"({len(r['positions'])} posiciones)."}
    r = bank.analyze(path)
    month = r.get("month") or this_month
    agg = r.get("aggregates") or {}
    agg["month"] = month
    persist_bank_aggregates(agg)
    value = r.get("available_balance") or 0.0
    return {"kind": "bank", "month": month, "category": "Liquidez (banco)", "value": value,
            "summary": f"🏦 Banco {month}: saldo {value:.2f} €, gastos {agg.get('gastos', 0):.2f} €, "
                       f"ganancias {agg.get('ganancias', 0):.2f} € ({len(r['transactions'])} mov.)."}


def persist_positions(month, source, positions):
    """Guarda el registro de posiciones (nombre y cantidad) de un mes y fuente.

    Es lo que permite consultar «qué valores tengo y cuántos títulos de cada
    uno», no solo el importe total de la categoría.
    """
    if not month or not positions:
        return 0
    rows = [{"name": p.get("name"), "isin": (p.get("extra") or {}).get("isin", ""),
             "quantity": p.get("quantity"), "unit_value": p.get("unit_value"),
             "value": p.get("value"), "currency": p.get("currency", "EUR")}
            for p in positions if p.get("name")]
    db.set_holdings(month, source, rows)
    return len(rows)


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
