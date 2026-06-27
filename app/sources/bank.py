"""
Banco: parseo del extracto en PDF y desglose de gastos NETOS por categoria.

Reglas de negocio:
  1. NEXO (inversiones) NO se cuenta como gasto. Las inversiones no son gastos.
  2. Los "BIZUM RECIBIDO" pueden ser devoluciones de una compra previa -> en ese
     caso reducen el gasto, no son ingreso.
  3. El gasto se muestra DESGLOSADO y NETO (cena de 30 con dos bizums de 10 -> 10).
"""

import re
from collections import Counter
from datetime import datetime

from .common import DATE_RE, MONEY_EU_RE, parse_money, extract_rows

_DATE_FULL = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_MONEY = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}€$|^-?\d+,\d{2}€$")

# (patron, categoria, tipo). tipo: expense | investment | bizum_in | bizum_out | income
RULES = [
    (r"nexo",                        "Inversión (Nexo)",        "investment"),
    (r"bizum recibido",              "Bizum recibido",          "bizum_in"),
    (r"bizum enviado",               "Bizum enviado",           "bizum_out"),
    (r"nomina|nómina",               "Nómina",                  "income"),
    (r"transf.*favor|transferencia", "Transferencia recibida",  "income"),
    (r"impuesto",                    "Impuestos",               "expense"),
    (r"mercadona|supercor|carrefour|lidl|aldi|dia ", "Supermercado", "expense"),
    (r"glovo|just ?eat|uber ?eats|burger|bk\d|mcdonald|restaurant|cafe|bar |pizz",
                                     "Restauración / Comida",   "expense"),
    (r"decathlon|son moix sport|sport|gym|gimnas", "Deporte",   "expense"),
    (r"aliexpress|amazon|pandora|lindt|zara|primark|shop|boutique|tienda",
                                     "Compras / Tiendas",       "expense"),
    (r"apple\.com|netflix|spotify|hbo|disney|lootbar|google|microsoft|subscription|bill",
                                     "Suscripciones / Digital", "expense"),
    (r"barber|peluqu|hair|estetica|estética", "Cuidado personal", "expense"),
    (r"ryanair|vueling|iberia|airbnb|booking|hotel|renfe|autonet|ora palma|smap|parking|taxi|cabify",
                                     "Transporte / Viajes",     "expense"),
    (r"expmaran|comision|comisión|cuota|fee", "Comisiones / Otros", "expense"),
]

SHAREABLE = {
    "Restauración / Comida", "Compras / Tiendas",
    "Transporte / Viajes", "Supermercado",
}


def categorize(concept, amount):
    c = concept.lower()
    for pat, cat, kind in RULES:
        if re.search(pat, c):
            return cat, kind
    return ("Otros ingresos", "income") if amount >= 0 else ("Otros gastos", "expense")


def _parse_pdf(path):
    rows = []
    for cells in extract_rows(path):
        date = next((t for t in cells if _DATE_FULL.match(t)), None)
        monies = [t for t in cells if _MONEY.match(t)]
        concept = [t for t in cells if not _DATE_FULL.match(t) and not _MONEY.match(t)]
        if date and len(monies) >= 2 and concept:
            rows.append({
                "concept": " ".join(concept).strip(),
                "date": date,
                "amount": parse_money(monies[0]),
                "balance": parse_money(monies[1]),
            })
    return rows


def _day(d):
    return datetime.strptime(d, "%d/%m/%Y")


def _available_balance(path):
    """Lee 'Saldo disponible: X€' del extracto (liquidez para el patrimonio)."""
    for cells in extract_rows(path):
        for c in cells:
            m = re.search(r"saldo disponible[:\s]*(-?[\d.]+,\d{2})", c, re.I)
            if m:
                return parse_money(m.group(1))
    return None


def analyze(path):
    """Parsea, categoriza y sugiere enlaces bizum_recibido -> gasto."""
    raw = _parse_pdf(path)
    txs = []
    for i, r in enumerate(raw):
        cat, kind = categorize(r["concept"], r["amount"])
        txs.append({
            "id": i, "concept": r["concept"], "date": r["date"],
            "amount": round(r["amount"], 2), "balance": round(r["balance"], 2),
            "category": cat, "kind": kind,
        })

    counts = Counter(t["amount"] for t in txs if t["kind"] == "bizum_in")
    recurring = {a for a, n in counts.items() if n >= 3}
    expenses = [t for t in txs if t["kind"] in ("expense", "bizum_out")]

    for t in txs:
        t["recurring_income"] = False
        t["suggested_link"] = None
        if t["kind"] != "bizum_in":
            continue
        if t["amount"] in recurring:
            t["recurring_income"] = True
            continue
        bdate = _day(t["date"])
        best, best_score = None, None
        for e in expenses:
            if t["amount"] > abs(e["amount"]) + 0.001:
                continue
            diff = abs((bdate - _day(e["date"])).days)
            if diff > 5:
                continue
            score = diff + (0 if e["category"] in SHAREABLE else 3)
            if best_score is None or score < best_score:
                best, best_score = e, score
        if best is not None:
            t["suggested_link"] = best["id"]

    months = sorted(_day(r["date"]).strftime("%Y-%m") for r in raw) if raw else []
    month = months[-1] if months else None
    balance = _available_balance(path)
    return {"period": _period(raw), "transactions": txs,
            "available_balance": balance, "month": month,
            "aggregates": _aggregate(txs, balance, month)}


def _aggregate(txs, balance, month):
    """Calcula gasto neto, ingresos (ganancias) e inversión con los enlaces
    bizum sugeridos por defecto (lo mismo que muestra la web al cargar)."""
    refunds = {}
    for t in txs:
        if t["kind"] == "bizum_in" and t["suggested_link"] is not None:
            refunds[t["suggested_link"]] = refunds.get(t["suggested_link"], 0) + t["amount"]
    gross = refund = inv = income = 0.0
    for t in txs:
        if t["kind"] in ("expense", "bizum_out"):
            g = abs(t["amount"])
            gross += g
            refund += min(refunds.get(t["id"], 0), g)
        elif t["kind"] == "investment":
            inv += abs(t["amount"])
        elif t["kind"] == "income":
            income += t["amount"]
        elif t["kind"] == "bizum_in" and t["suggested_link"] is None:
            income += t["amount"]
    return {
        "month": month,
        "liquidez": round(balance, 2) if balance is not None else None,
        "gastos": round(gross - refund, 2),
        "ganancias": round(income, 2),
        "inversion": round(inv, 2),
    }


def _period(raw):
    if not raw:
        return ""
    ds = sorted(_day(r["date"]) for r in raw)
    return f"{ds[0].strftime('%d/%m/%Y')} - {ds[-1].strftime('%d/%m/%Y')}"
