"""
Parseo de extractos bancarios en PDF y categorizacion de movimientos.

Reglas de negocio principales (segun lo pedido):
  1. NEXO (inversiones) NO se cuenta como gasto. Las inversiones no son gastos.
  2. Los "BIZUM RECIBIDO" pueden ser devoluciones de una compra previa
     (te han devuelto dinero) -> en ese caso reducen el gasto, no son ingreso.
  3. El gasto se muestra DESGLOSADO y NETO: si una cena costo 30 y te hacen
     dos bizums de 10, el gasto de restaurante es 10, no 30.

El parser usa el layout (coordenadas) del PDF para reconstruir filas de forma
robusta, en lugar de depender del orden del texto plano (que es fragil).
"""

import re
from datetime import datetime

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
MONEY_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}€$")


def parse_money(token):
    """'5.560,87€' -> 5560.87 ; '-1.296,18€' -> -1296.18"""
    t = token.replace("€", "").strip()
    neg = t.startswith("-")
    t = t.lstrip("-").replace(".", "").replace(",", ".")
    val = float(t)
    return -val if neg else val


# ---------------------------------------------------------------------------
# Categorizacion
# ---------------------------------------------------------------------------
# kind:
#   expense      -> gasto normal (cuenta para el total de gastos)
#   investment   -> inversion (Nexo): NO es gasto
#   bizum_in     -> bizum recibido (posible devolucion)
#   bizum_out    -> bizum enviado (salida de dinero, gasto por defecto)
#   income       -> ingreso real (nomina, transferencias a favor)
#
# Cada regla: (patron_regex, categoria, kind)
RULES = [
    (r"nexo",                       "Inversión (Nexo)",          "investment"),
    (r"bizum recibido",             "Bizum recibido",            "bizum_in"),
    (r"bizum enviado",              "Bizum enviado",             "bizum_out"),
    (r"nomina|nómina",              "Nómina",                    "income"),
    (r"transf.*favor|transferencia","Transferencia recibida",    "income"),
    (r"impuesto",                   "Impuestos",                 "expense"),
    (r"mercadona|supercor|carrefour|lidl|aldi|dia ", "Supermercado", "expense"),
    (r"glovo|just ?eat|uber ?eats|burger|bk\d|mcdonald|restaurant|cafe|bar |pizz",
                                    "Restauración / Comida",     "expense"),
    (r"decathlon|son moix sport|sport|gym|gimnas", "Deporte",     "expense"),
    (r"aliexpress|amazon|pandora|lindt|zara|primark|shop|boutique|tienda",
                                    "Compras / Tiendas",         "expense"),
    (r"apple\.com|netflix|spotify|hbo|disney|lootbar|google|microsoft|subscription|bill",
                                    "Suscripciones / Digital",   "expense"),
    (r"barber|peluqu|hair|estetica|estética", "Cuidado personal", "expense"),
    (r"ryanair|vueling|iberia|airbnb|booking|hotel|renfe|autonet|ora palma|smap|parking|taxi|cabify",
                                    "Transporte / Viajes",       "expense"),
    (r"expmaran|comision|comisión|cuota|fee", "Comisiones / Otros", "expense"),
]


def categorize(concept, amount):
    c = concept.lower()
    for pat, cat, kind in RULES:
        if re.search(pat, c):
            return cat, kind
    # Fallback por signo del importe
    if amount >= 0:
        return "Otros ingresos", "income"
    return "Otros gastos", "expense"


# Categorias "compartibles": tipicas de gastos que se dividen entre varios
# y por las que es probable recibir un bizum de devolucion.
SHAREABLE = {
    "Restauración / Comida",
    "Compras / Tiendas",
    "Transporte / Viajes",
    "Supermercado",
}


# ---------------------------------------------------------------------------
# Parseo del PDF
# ---------------------------------------------------------------------------
def parse_pdf(path):
    """Devuelve la lista de movimientos en el orden del extracto."""
    rows = []
    for page in extract_pages(path):
        items = []
        for el in page:
            if isinstance(el, LTTextContainer):
                for line in el:
                    if hasattr(line, "get_text"):
                        t = line.get_text().strip()
                        if t:
                            items.append((round(line.y0, 1), round(line.x0, 1), t))
        # Agrupar por coordenada Y (cada fila de la tabla)
        items.sort(key=lambda r: -r[0])
        grouped = []
        for y, x, t in items:
            for g in grouped:
                if abs(g[0] - y) <= 3:
                    g[1].append((x, t))
                    break
            else:
                grouped.append([y, [(x, t)]])
        for _, cells in grouped:
            cells.sort()
            texts = [t for _, t in cells]
            date = next((t for t in texts if DATE_RE.match(t)), None)
            monies = [t for t in texts if MONEY_RE.match(t)]
            concept_parts = [t for t in texts if not DATE_RE.match(t) and not MONEY_RE.match(t)]
            # Una fila de movimiento valida tiene: concepto, fecha, importe y saldo
            if date and len(monies) >= 2 and concept_parts:
                rows.append({
                    "concept": " ".join(concept_parts).strip(),
                    "date": date,
                    "amount": parse_money(monies[0]),
                    "balance": parse_money(monies[1]),
                })
    return rows


def _day(d):
    return datetime.strptime(d, "%d/%m/%Y")


def analyze(path):
    """Parsea, categoriza y sugiere enlaces bizum->gasto.

    Devuelve un dict listo para serializar a JSON y consumir desde el front.
    """
    raw = parse_pdf(path)
    txs = []
    for i, r in enumerate(raw):
        cat, kind = categorize(r["concept"], r["amount"])
        txs.append({
            "id": i,
            "concept": r["concept"],
            "date": r["date"],
            "amount": round(r["amount"], 2),
            "balance": round(r["balance"], 2),
            "category": cat,
            "kind": kind,
        })

    # Detectar ingresos recurrentes: mismo importe en bizums recibidos que
    # se repite >=3 veces suele ser un ingreso real, no una devolucion.
    from collections import Counter
    bizum_in_amounts = Counter(t["amount"] for t in txs if t["kind"] == "bizum_in")
    recurring = {amt for amt, n in bizum_in_amounts.items() if n >= 3}

    expenses = [t for t in txs if t["kind"] in ("expense", "bizum_out")]

    # Sugerencia automatica de enlace bizum_recibido -> gasto que reembolsa.
    for t in txs:
        t["recurring_income"] = False
        t["suggested_link"] = None
        if t["kind"] != "bizum_in":
            continue
        if t["amount"] in recurring:
            # Probable ingreso recurrente -> no se sugiere devolucion.
            t["recurring_income"] = True
            continue
        bdate = _day(t["date"])
        best, best_score = None, None
        for e in expenses:
            if t["amount"] > abs(e["amount"]) + 0.001:
                continue  # una devolucion no deberia superar el gasto
            diff = abs((bdate - _day(e["date"])).days)
            if diff > 5:
                continue  # ventana temporal razonable
            # menor diferencia de dias y categoria compartible puntuan mejor
            score = diff + (0 if e["category"] in SHAREABLE else 3)
            if best_score is None or score < best_score:
                best, best_score = e, score
        if best is not None:
            t["suggested_link"] = best["id"]

    return {
        "period": _period(raw),
        "transactions": txs,
    }


def _period(raw):
    if not raw:
        return ""
    dates = sorted(_day(r["date"]) for r in raw)
    return f"{dates[0].strftime('%d/%m/%Y')} - {dates[-1].strftime('%d/%m/%Y')}"
