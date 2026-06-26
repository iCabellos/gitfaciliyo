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
# Línea de decklist de Moxfield, p.ej: "2 Lightning Bolt (2X2) 117 *F*"
#   grupo 1 = cantidad · 2 = nombre · 3 = set · 4 = nº coleccionista
_LINE_RE = re.compile(
    r"^\s*(?:(\d+)\s*[xX]?\s+)?"          # cantidad
    r"(.+?)"                                # nombre
    r"(?:\s+\(([A-Za-z0-9]{2,6})\)\s+(\S+))?"  # (SET) colector  -> arte/edición exacta
    r"((?:\s+[*#][^*#\s]+[*#]?)*)\s*$"     # flags como *F* (foil), *E*, #etiquetas
)


def _ident_key(c):
    """Clave de identidad para precio: scryfall_id > set+colector > nombre."""
    if c.get("scryfall_id"):
        return ("id", c["scryfall_id"])
    if c.get("set") and c.get("collector"):
        return ("sc", c["set"].lower(), str(c["collector"]))
    return ("name", c["name"].lower())


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
            finish = (entry.get("finish") or card.get("finish") or "").lower()
            cards.append({
                "name": name,
                "quantity": entry.get("quantity", 1),
                # scryfall_id apunta a la impresión EXACTA (arte alternativo incluido).
                "scryfall_id": card.get("scryfall_id") or card.get("scryfallId"),
                "set": card.get("set"),
                "collector": card.get("cn") or card.get("collector_number"),
                "foil": entry.get("isFoil") or finish in ("foil", "etched"),
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
    """Parsea una decklist conservando set + nº de coleccionista (arte exacto) y foil."""
    cards = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#", "Deck", "Commander", "Sideboard", "About", "Maybeboard")):
            continue
        if line.startswith("SB:"):
            line = line[3:].strip()
        m = _LINE_RE.match(line)
        if not m:
            continue
        qty = int(m.group(1)) if m.group(1) else 1
        name = m.group(2).strip()
        set_code = m.group(3)
        collector = m.group(4)
        flags = (m.group(5) or "").lower()
        foil = "*f*" in flags or "*e*" in flags        # *F* foil, *E* etched
        if name:
            cards.append({"name": name, "quantity": qty, "scryfall_id": None,
                          "set": set_code, "collector": collector, "foil": foil})
    return cards


# --------------------------------------------------------------------------
# 2. Precios en vivo (Scryfall)
# --------------------------------------------------------------------------
def _payload(key, names):
    if key[0] == "id":
        return {"id": key[1]}
    if key[0] == "sc":
        return {"set": key[1], "collector_number": key[2]}
    return {"name": names[key]}


def price_cards(cards):
    """Precios en vivo de Scryfall por IMPRESIÓN exacta (arte alternativo) y foil.

    Devuelve prices[key] = {eur, usd, eur_foil, usd_foil}.
    """
    uniq = {}     # key -> nombre original (para identificar por nombre)
    for c in cards:
        uniq.setdefault(_ident_key(c), c["name"])
    keys = list(uniq.keys())
    prices, warnings = {}, []
    for i in range(0, len(keys), 75):
        chunk = keys[i:i + 75]
        try:
            status, data = http.post_json(
                "https://api.scryfall.com/cards/collection",
                {"identifiers": [_payload(k, uniq) for k in chunk]})
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Scryfall falló en un lote: {exc}")
            continue
        if status != 200 or not data:
            warnings.append(f"Scryfall devolvió {status} en un lote.")
            continue
        found = {}
        for card in data.get("data", []):
            p = card.get("prices", {})
            pr = {k: (float(p[k]) if p.get(k) else None)
                  for k in ("eur", "usd", "eur_foil", "usd_foil")}
            if card.get("id"):
                found[("id", card["id"])] = pr
            if card.get("set") and card.get("collector_number"):
                found[("sc", card["set"].lower(), str(card["collector_number"]))] = pr
            found[("name", card.get("name", "").lower())] = pr
        for k in chunk:
            prices[k] = found.get(k) or found.get(("name", uniq[k].lower()), {})
        time.sleep(0.12)  # cortesía con la API de Scryfall
    return prices, warnings


def _pick_price(pr, foil):
    """Elige el precio adecuado: foil si la carta es foil; EUR preferente, USD si no."""
    order = (["eur_foil", "eur", "usd_foil", "usd"] if foil else ["eur", "usd"])
    for k in order:
        v = pr.get(k)
        if v is not None:
            return v, ("USD" if k.startswith("usd") else "EUR")
    return None, None


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
        pr = prices.get(_ident_key(c), {})
        foil = bool(c.get("foil"))
        unit, cur = _pick_price(pr, foil)
        if cur == "USD":
            usd_only += 1
        if unit is None:
            unit, cur = 0.0, "EUR"
            warnings.append(f"Sin precio para «{c['name']}».")
        edition = " ".join(x for x in [c.get("set", "").upper() if c.get("set") else "",
                                       str(c.get("collector") or "")] if x).strip()
        tag = (edition + (" ✦foil" if foil else "")).strip() or deck_name
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=c["name"], quantity=c["quantity"],
            unit_value=unit, value=round(unit * c["quantity"], 2), currency=cur,
            extra={"deck": deck_name, "edition": edition, "foil": foil, "tag": tag},
        ).finalize())
    if usd_only:
        warnings.append(f"{usd_only} carta(s) solo tenían precio en USD (no sumadas al total en €).")
    total_eur = round(sum(p.value for p in positions if p.currency == "EUR"), 2)
    return {
        "source": SOURCE, "category": CATEGORY, "deck": deck_name,
        "positions": [p.to_dict() for p in positions],
        "total": total_eur, "currency": "EUR", "warnings": warnings,
    }
