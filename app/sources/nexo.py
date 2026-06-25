"""
Nexo: parseo del informe/extracto mensual (CSV o PDF) -> posiciones cripto.

Nexo permite exportar tu actividad y balances. Este parser es tolerante:

  * CSV de balances (lo ideal) -> columnas asset/amount/value detectadas por cabecera.
  * CSV de transacciones de Nexo -> agrega el neto por divisa (aprox. de la posición).
  * PDF -> heurístico por filas.

Formato normalizado que SIEMPRE funciona (CSV con cabecera):

    asset,amount,value
    BTC,0.05,3120.00
    ETH,1.2,3450.00
    USDC,500,500.00

`value` es el valor actual en tu moneda de cuenta según el informe. (Si algún
día quieres precio cripto en vivo se puede añadir CoinGecko; el informe ya trae
el valor, así que por defecto se usa ese.)
"""

import csv
import io
import re
from collections import defaultdict

from .common import parse_money, extract_rows, Position

SOURCE = "Nexo"
CATEGORY = "Cripto (Nexo)"

COLUMN_ALIASES = {
    "asset":  ["asset", "currency", "coin", "crypto", "activo", "divisa", "moneda", "ticker", "symbol"],
    "amount": ["amount", "balance", "cantidad", "saldo", "quantity", "units"],
    "value":  ["value", "valor", "usd equivalent", "eur equivalent", "fiat value", "importe", "market value"],
    "price":  ["price", "precio", "rate"],
}
# Columnas tipicas del export de transacciones de Nexo.
TX_COLS = {"input currency", "output currency", "input amount", "output amount", "usd equivalent"}


def _idx(header):
    out = {}
    low = [h.strip().lower() for h in header]
    for key, aliases in COLUMN_ALIASES.items():
        for i, h in enumerate(low):
            if any(a == h or a in h for a in aliases):
                out[key] = i
                break
    return out


def _parse_balances_csv(reader):
    idx = _idx(reader[0])
    if "asset" not in idx:
        return None
    positions, warnings = [], []
    for row in reader[1:]:
        def get(k):
            return row[idx[k]].strip() if k in idx and idx[k] < len(row) else ""
        asset = get("asset")
        if not asset:
            continue
        amount = parse_money(get("amount")) or 0.0
        value = parse_money(get("value"))
        price = parse_money(get("price"))
        if value is None and price is not None:
            value = round(amount * price, 2)
        if value is None:
            warnings.append(f"Sin valor para «{asset}», se omite.")
            continue
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=asset,
            quantity=amount, unit_value=(value / amount if amount else value),
            value=value, currency="EUR", extra={"asset": asset},
        ).finalize())
    return positions, warnings


def _parse_tx_csv(reader):
    """Export de transacciones: agrega neto por divisa (aproximacion de holdings)."""
    low = [h.strip().lower() for h in reader[0]]
    if not (TX_COLS & set(low)):
        return None
    col = {h: i for i, h in enumerate(low)}
    net = defaultdict(float)
    for row in reader[1:]:
        try:
            ic = row[col["input currency"]].strip()
            ia = parse_money(row[col["input amount"]]) or 0.0
            oc = row[col["output currency"]].strip()
            oa = parse_money(row[col["output amount"]]) or 0.0
        except (KeyError, IndexError):
            continue
        if oc:
            net[oc] += oa
        if ic:
            net[ic] -= ia
    positions = [
        Position(source=SOURCE, category=CATEGORY, name=a, quantity=round(q, 8),
                 unit_value=0.0, value=0.0, extra={"asset": a, "needs_price": True}).finalize()
        for a, q in net.items() if abs(q) > 1e-9
    ]
    warnings = ["Detectado export de transacciones: se muestra el neto por divisa; "
                "el valor en € requiere precio en vivo (no incluido). Mejor adjunta un CSV de balances."]
    return positions, warnings


def _parse_pdf(path):
    positions = []
    for cells in extract_rows(path):
        nums = [parse_money(c) for c in cells if re.search(r"\d", c)]
        nums = [n for n in nums if n is not None]
        words = [c for c in cells if re.fullmatch(r"[A-Za-z]{2,6}", c)]
        if words and nums:
            positions.append(Position(
                source=SOURCE, category=CATEGORY, name=words[0],
                quantity=nums[0], unit_value=0.0, value=round(max(nums), 2),
                extra={"asset": words[0]},
            ).finalize())
    return positions, ["PDF interpretado de forma heurística; revisa o usa CSV de balances."]


def parse(path):
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
        delim = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
        reader = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
        result = None
        if reader:
            result = _parse_balances_csv(reader) or _parse_tx_csv(reader)
        if result is None:
            positions, warnings = [], ["No se reconoció el CSV. Usa el formato normalizado asset,amount,value."]
        else:
            positions, warnings = result
    else:
        positions, warnings = _parse_pdf(path)
    total = round(sum(p.value for p in positions), 2)
    return {
        "source": SOURCE, "category": CATEGORY,
        "positions": [p.to_dict() for p in positions],
        "total": total, "currency": "EUR", "warnings": warnings,
    }
