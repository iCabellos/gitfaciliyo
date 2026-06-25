"""
Trade Republic: parseo del informe mensual (PDF o CSV) -> posiciones de acciones/ETFs.

Trade Republic no ofrece API publica para clientes, asi que el flujo es adjuntar
el informe mensual. Este parser reconoce:

  * El "Extracto del patrimonio neto" en PDF (formato real de TR): posiciones
    "<unidades> unidades <nombre> | <precio> | <valor>" con su ISIN, mas el efectivo.
  * CSV  -> detecta columnas por su cabecera (ISIN, nombre, cantidad, precio, valor).
  * PDF generico -> heuristica por filas con ISIN (respaldo).

Formato normalizado que SIEMPRE funciona (CSV con cabecera, separador ',' o ';'):

    name,isin,quantity,price,value
    Apple,US0378331005,3,180.50,541.50
    Vanguard FTSE All-World,IE00BK5BQT80,12,118.20,1418.40
"""

import csv
import io
import re

from .common import ISIN_RE, parse_money, extract_rows, Position

SOURCE = "Trade Republic"
CATEGORY = "Acciones / ETFs"

_EU_NUM_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:,\d+)?$")
_DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")
_UNITS_RE = re.compile(r"^([\d.,]+)\s+unidades?\s+(.+)$", re.I)


def _eu(s):
    """Numero en formato europeo: '.' miles, ',' decimal. '8,267789' -> 8.267789."""
    if s is None:
        return None
    t = str(s).replace("EUR", "").replace("€", "").strip()
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


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


def _looks_like_statement(rows):
    flat = " ".join(c for r in rows for c in r).lower()
    return "nombre del valor" in flat and "unidades" in flat


def _parse_statement(rows):
    """Parser del 'Extracto del patrimonio neto' real de Trade Republic.

    Las posiciones llegan como filas tipo
        ['8,267789 unidades S&P 500 EUR (Acc)', '129,26', '1.068,69']
    seguidas de filas de continuacion con el nombre y el 'ISIN: ...'.
    """
    positions, warnings = [], []
    # Acotar al bloque de posiciones (entre la cabecera y 'NÚMERO DE POSICIONES').
    start = end = None
    for i, r in enumerate(rows):
        joined = " ".join(r).lower()
        if "nombre del valor" in joined:
            start = i + 1
        elif start is not None and "número de posiciones" in joined:
            end = i
            break
    block = rows[start:end] if start is not None else []

    current = None
    for r in block:
        m = _UNITS_RE.match(r[0]) if r else None
        if m:
            if current:
                positions.append(current)
            qty = _eu(m.group(1))
            nums = [c for c in r[1:] if _EU_NUM_RE.match(c.replace(" EUR", "").strip())]
            price = _eu(nums[0]) if len(nums) >= 1 else None
            value = _eu(nums[-1]) if nums else None
            current = Position(
                source=SOURCE, category=CATEGORY, name=m.group(2).strip(),
                quantity=qty or 1.0, unit_value=price or 0.0,
                value=round(value, 2) if value is not None else 0.0,
                extra={"isin": ""},
            )
        elif current:
            for c in r:
                mi = ISIN_RE.search(c)
                if mi:
                    current.extra["isin"] = mi.group(0)
                elif not _DATE_RE.match(c) and "isin" not in c.lower():
                    current.name = (current.name + " " + c).strip()  # nombre en varias lineas
    if current:
        positions.append(current)
    for p in positions:
        p.finalize()

    # Efectivo (cuenta corriente) como liquidez dentro de TR.
    for r in rows:
        if r and r[0].strip().lower() in ("cuenta corriente", "efectivo"):
            cash = next((_eu(c) for c in r[1:] if _eu(c) is not None), None)
            if cash:
                positions.append(Position(
                    source=SOURCE, category=CATEGORY, name="Efectivo (cuenta corriente)",
                    quantity=1.0, unit_value=cash, value=round(cash, 2),
                    extra={"isin": ""}).finalize())
            break

    if not positions:
        warnings.append("No se detectaron posiciones en el extracto.")
    return positions, warnings


def parse(path):
    if path.lower().endswith(".csv"):
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            positions, warnings = _parse_csv(fh.read())
    else:
        rows = extract_rows(path)
        if _looks_like_statement(rows):
            positions, warnings = _parse_statement(rows)
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
