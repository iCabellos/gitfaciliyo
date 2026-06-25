"""
Trade Republic: parseo del informe mensual (PDF o CSV) -> posiciones de acciones/ETFs.

Trade Republic no ofrece API publica para clientes, asi que el flujo es adjuntar
el informe mensual. Este parser es TOLERANTE al formato:

  * CSV  -> detecta columnas por su cabecera (ISIN, nombre, cantidad, precio, valor).
  * PDF  -> reconstruye filas por coordenadas y localiza las que contienen un ISIN.

Formato normalizado que SIEMPRE funciona (CSV con cabecera, separador ',' o ';'):

    name,isin,quantity,price,value
    Apple,US0378331005,3,180.50,541.50
    Vanguard FTSE All-World,IE00BK5BQT80,12,118.20,1418.40

Si tu informe real trae otras columnas, ajusta COLUMN_ALIASES o exporta al
formato normalizado. Marca `warnings` cuando algo no se pudo interpretar.
"""

import csv
import io
import re

from .common import ISIN_RE, parse_money, extract_rows, Position

SOURCE = "Trade Republic"
CATEGORY = "Acciones / ETFs"

COLUMN_ALIASES = {
    "name":     ["name", "nombre", "instrument", "instrumento", "producto", "security", "titulo", "título"],
    "isin":     ["isin"],
    "quantity": ["quantity", "cantidad", "shares", "qty", "participaciones", "units", "nominal"],
    "price":    ["price", "precio", "cotizacion", "cotización", "last", "ultimo", "último"],
    "value":    ["value", "valor", "market value", "valor de mercado", "amount", "importe", "total"],
    "currency": ["currency", "moneda", "divisa"],
}


def _match_columns(header):
    idx = {}
    low = [h.strip().lower() for h in header]
    for key, aliases in COLUMN_ALIASES.items():
        for i, h in enumerate(low):
            if any(a == h or a in h for a in aliases):
                idx[key] = i
                break
    return idx


def _parse_csv(text):
    warnings = []
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = list(csv.reader(io.StringIO(text), delimiter=delim))
    reader = [r for r in reader if any(c.strip() for c in r)]
    if not reader:
        return [], ["CSV vacío."]
    idx = _match_columns(reader[0])
    if "name" not in idx and "isin" not in idx:
        return [], ["No se reconocieron columnas (se esperaba name/isin). Usa el formato normalizado."]
    positions = []
    for row in reader[1:]:
        def get(k):
            return row[idx[k]].strip() if k in idx and idx[k] < len(row) else ""
        name = get("name") or get("isin")
        if not name:
            continue
        qty = parse_money(get("quantity")) or 1.0
        price = parse_money(get("price"))
        value = parse_money(get("value"))
        if value is None and price is not None:
            value = round(qty * price, 2)
        if value is None:
            warnings.append(f"Sin valor para «{name}», se omite.")
            continue
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=name,
            quantity=qty, unit_value=price or (value / qty if qty else value),
            value=value, currency=(get("currency") or "EUR").upper() or "EUR",
            extra={"isin": get("isin")},
        ).finalize())
    return positions, warnings


def _parse_pdf(path):
    """Best-effort: filas con ISIN; ultimo numero grande de la fila = valor."""
    warnings = ["PDF interpretado de forma heurística; revisa los valores o usa CSV normalizado."]
    positions = []
    for cells in extract_rows(path):
        joined = " ".join(cells)
        m = ISIN_RE.search(joined)
        if not m:
            continue
        isin = m.group(0)
        nums = [parse_money(c) for c in cells if re.search(r"\d", c)]
        nums = [n for n in nums if n is not None]
        name_cells = [c for c in cells if not re.search(r"^\W*[\d.,]+\W*$", c) and isin not in c]
        name = " ".join(name_cells).strip() or isin
        if not nums:
            continue
        value = max(nums)        # el importe mayor de la fila suele ser el valor de mercado
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=name,
            quantity=1.0, unit_value=value, value=round(value, 2),
            extra={"isin": isin},
        ).finalize())
    if not positions:
        warnings.append("No se detectaron filas con ISIN en el PDF.")
    return positions, warnings


def parse(path):
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            positions, warnings = _parse_csv(fh.read())
    else:
        positions, warnings = _parse_pdf(path)
    total = round(sum(p.value for p in positions), 2)
    return {
        "source": SOURCE,
        "category": CATEGORY,
        "positions": [p.to_dict() for p in positions],
        "total": total,
        "currency": positions[0].currency if positions else "EUR",
        "warnings": warnings,
    }
