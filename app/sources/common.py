"""Utilidades compartidas por las distintas fuentes de patrimonio."""

import re
from dataclasses import dataclass, field, asdict

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer

DATE_RE = re.compile(r"\d{2}/\d{2}/\d{4}")
ISIN_RE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b")
# Importes europeos (1.234,56) o americanos (1,234.56), con o sin simbolo.
MONEY_EU_RE = re.compile(r"^-?\d{1,3}(?:\.\d{3})*,\d{2}\s*[€$]?$|^-?\d+,\d{2}\s*[€$]?$")


def parse_money(token):
    """Convierte un importe en texto a float.

    Soporta formato europeo (1.234,56 €) y americano (1,234.56) y simbolos.
    """
    if token is None:
        return None
    t = str(token).strip().replace("€", "").replace("$", "").replace(" ", "")
    if not t:
        return None
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()")
    if "," in t and "." in t:
        # El ultimo separador es el decimal.
        if t.rfind(",") > t.rfind("."):      # europeo: 1.234,56
            t = t.replace(".", "").replace(",", ".")
        else:                                 # americano: 1,234.56
            t = t.replace(",", "")
    elif "," in t:
        # Solo coma: decimal si hay 2 digitos tras ella, si no separador de miles.
        if re.search(r",\d{2}$", t):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    try:
        val = float(t)
    except ValueError:
        return None
    return -val if neg else val


def extract_rows(path):
    """Reconstruye filas de tablas en un PDF agrupando texto por coordenada Y.

    Devuelve una lista de filas; cada fila es la lista de celdas (texto)
    ordenadas por su posicion X (izquierda -> derecha). Mas fiable que leer el
    texto plano, cuyo orden el extractor no garantiza.
    """
    out = []
    for page in extract_pages(path):
        items = []
        for el in page:
            if isinstance(el, LTTextContainer):
                for line in el:
                    if hasattr(line, "get_text"):
                        t = line.get_text().strip()
                        if t:
                            items.append((round(line.y0, 1), round(line.x0, 1), t))
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
            out.append([t for _, t in cells])
    return out


@dataclass
class Position:
    """Una posicion/holding de inversion, normalizada entre fuentes."""

    source: str                 # "Trade Republic", "Nexo", "CS:GO", "Magic"
    category: str               # "Acciones", "Cripto", "Skins CS:GO", "Cartas Magic"
    name: str
    quantity: float = 1.0
    unit_value: float = 0.0     # valor actual por unidad
    value: float = 0.0          # valor total = quantity * unit_value
    currency: str = "EUR"
    cost: float = None          # invertido (si se conoce)
    extra: dict = field(default_factory=dict)

    def finalize(self):
        if not self.value:
            self.value = round(self.quantity * self.unit_value, 2)
        return self

    def to_dict(self):
        return asdict(self)
