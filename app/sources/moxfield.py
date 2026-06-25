"""
Cartas Magic: obtiene los mazos de Moxfield y pide el precio EN VIVO a Scryfall.

Flujo:
  1. Conseguir la lista de cartas. Dos vias:
       a) Moxfield API (por usuario o por deck id/URL). Moxfield protege su API
          tras Cloudflare y puede bloquear el acceso por script; si falla, se avisa.
       b) Pegar/subir la decklist exportada de Moxfield (SIEMPRE funciona).
  2. Pedir el precio en tiempo real a Scryfall (endpoint en lote, 75 cartas/petición).
     Se prioriza el precio en EUR (Cardmarket); si una carta solo tiene precio en
     USD se indica aparte y no se suma al total en EUR.
"""

import re
import time

from . import http
from .common import Position

SOURCE = "Magic"
CATEGORY = "Cartas Magic"

MOXFIELD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.moxfield.com/",
    "Origin": "https://www.moxfield.com",
}

_DECK_ID_RE = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_-]+)")
# "2 Lightning Bolt (2X2) 117 *F*"  /  "1x Sol Ring"  /  "Sol Ring"
_LINE_RE = re.compile(r"^\s*(?:(\d+)\s*[xX]?\s+)?(.+?)\s*$")


# --------------------------------------------------------------------------
# 1a. Moxfield API (best-effort)
# --------------------------------------------------------------------------
def _moxfield_deck(deck_id):
    for ver in ("v3", "v2"):
        try:
            status, data = http.get_json(
                f"https://api.moxfield.com/{ver}/decks/all/{deck_id}",
                headers=MOXFIELD_HEADERS)
        except Exception:  # noqa: BLE001
            continue
        if status == 200 and data:
            return data
    raise RuntimeError(
        "No se pudo leer de Moxfield (suele bloquear el acceso automático por Cloudflare). "
        "Exporta la decklist en Moxfield y pégala/súbela; el precio se calcula igual.")


def _cards_from_moxfield_json(data):
    cards = []
    boards = []
    if "boards" in data:  # esquema v3
        for b in data["boards"].values():
            boards.append(b.get("cards", {}))
    else:                 # esquema v2
        for key in ("commanders", "mainboard", "companions"):
            if isinstance(data.get(key), dict):
                boards.append(data[key])
    for board in boards:
        for entry in board.values():
            card = entry.get("card", entry)
            name = card.get("name")
            if not name:
                continue
            cards.append({
                "name": name,
                "quantity": entry.get("quantity", 1),
                "scryfall_id": card.get("scryfall_id") or card.get("scryfallId"),
            })
    return cards


def cards_from_moxfield(reference):
    """`reference` puede ser la URL de un deck o su ID público."""
    m = _DECK_ID_RE.search(reference or "")
    deck_id = m.group(1) if m else (reference or "").strip().strip("/")
    data = _moxfield_deck(deck_id)
    name = data.get("name", "Mazo")
    return name, _cards_from_moxfield_json(data)


# --------------------------------------------------------------------------
# 1b. Decklist pegada/subida
# --------------------------------------------------------------------------
def cards_from_decklist(text):
    cards = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#", "SB:", "Deck", "Commander", "Sideboard")):
            # Permite "SB: 1 Card" quitando el prefijo
            if line.startswith("SB:"):
                line = line[3:].strip()
            else:
                continue
        m = _LINE_RE.match(line)
        if not m:
            continue
        qty = int(m.group(1)) if m.group(1) else 1
        name = m.group(2)
        name = re.sub(r"\s*\([A-Za-z0-9]{2,5}\)\s*[\dA-Za-z]*\s*", " ", name)  # (SET) 117
        name = re.sub(r"\s*\*[^*]*\*\s*", " ", name)                            # *F*
        name = name.split("//")[0].strip() if " // " not in name else name.strip()
        name = name.strip()
        if name:
            cards.append({"name": name, "quantity": qty, "scryfall_id": None})
    return cards


# --------------------------------------------------------------------------
# 2. Precios en vivo (Scryfall)
# --------------------------------------------------------------------------
def price_cards(cards):
    """Añade precio EUR (o USD si no hay EUR) a cada carta vía Scryfall en lote."""
    # Deduplicar identificadores (por scryfall_id si existe, si no por nombre).
    uniq = {}
    for c in cards:
        key = ("id", c["scryfall_id"]) if c.get("scryfall_id") else ("name", c["name"])
        uniq.setdefault(key, c["name"])
    keys = list(uniq.keys())
    prices = {}   # key -> (eur, usd)
    warnings = []
    for i in range(0, len(keys), 75):
        chunk = keys[i:i + 75]
        identifiers = [{"id": k[1]} if k[0] == "id" else {"name": k[1]} for k in chunk]
        try:
            status, data = http.post_json(
                "https://api.scryfall.com/cards/collection",
                {"identifiers": identifiers})
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Scryfall falló en un lote: {exc}")
            continue
        if status != 200 or not data:
            warnings.append(f"Scryfall devolvió {status} en un lote.")
            continue
        found = {}
        for card in data.get("data", []):
            p = card.get("prices", {})
            eur = float(p["eur"]) if p.get("eur") else None
            usd = float(p["usd"]) if p.get("usd") else None
            found[card.get("name", "").lower()] = (eur, usd)
            if card.get("id"):
                found[("id", card["id"])] = (eur, usd)
        for k in chunk:
            if k[0] == "id" and ("id", k[1]) in found:
                prices[k] = found[("id", k[1])]
            else:
                prices[k] = found.get(uniq[k].lower(), (None, None))
        time.sleep(0.12)  # cortesía con la API de Scryfall
    return prices, warnings


def analyze(reference=None, decklist=None):
    deck_name = "Decklist"
    if decklist and decklist.strip():
        cards = cards_from_decklist(decklist)
    elif reference:
        deck_name, cards = cards_from_moxfield(reference)
    else:
        raise RuntimeError("Indica una URL/usuario de Moxfield o pega una decklist.")
    if not cards:
        return {"source": SOURCE, "category": CATEGORY, "positions": [], "total": 0.0,
                "currency": "EUR", "warnings": ["No se encontraron cartas."]}

    prices, warnings = price_cards(cards)
    positions = []
    usd_only = 0
    for c in cards:
        key = ("id", c["scryfall_id"]) if c.get("scryfall_id") else ("name", c["name"])
        eur, usd = prices.get(key, (None, None))
        if eur is not None:
            unit, cur = eur, "EUR"
        elif usd is not None:
            unit, cur = usd, "USD"
            usd_only += 1
        else:
            unit, cur = 0.0, "EUR"
            warnings.append(f"Sin precio para «{c['name']}».")
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=c["name"], quantity=c["quantity"],
            unit_value=unit, value=round(unit * c["quantity"], 2), currency=cur,
            extra={"deck": deck_name},
        ).finalize())
    if usd_only:
        warnings.append(f"{usd_only} carta(s) solo tenían precio en USD (no sumadas al total en €).")
    total_eur = round(sum(p.value for p in positions if p.currency == "EUR"), 2)
    return {
        "source": SOURCE, "category": CATEGORY, "deck": deck_name,
        "positions": [p.to_dict() for p in positions],
        "total": total_eur, "currency": "EUR", "warnings": warnings,
    }
