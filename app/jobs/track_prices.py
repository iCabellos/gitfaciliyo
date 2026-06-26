"""
Seguimiento DIARIO de precios de cartas Magic y skins de CS:GO.

Ejecuta una vez al día (cron). Lee tu watchlist, consulta los precios y los
guarda en data/price_history.json con una entrada por día:

    { "2026-06-26": { "card:Sol Ring": 3.85, "skin:AK-47 | Redline (Field-Tested)": 37.5 } }

Fuentes de precio:
  * Cartas Magic  -> Scryfall (actualiza precios a diario; EUR preferente, USD si no hay).
  * Skins CS:GO   -> Steam Market por defecto; CSFloat si defines CSFLOAT_API_KEY.

Watchlist (data/watchlist.json, o "watchlist" dentro de config.json):

    {
      "cards": ["Sol Ring", "Rhystic Study", "Cyclonic Rift"],
      "skins": ["AK-47 | Redline (Field-Tested)", "★ Karambit | Doppler (Factory New)"]
    }
"""

import datetime
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from sources import moxfield, steam, http  # noqa: E402
from sources.common import parse_money       # noqa: E402

DATA_DIR = os.environ.get("PATRIMONIO_DATA_DIR") or os.path.join(HERE, "data")
HISTORY = os.path.join(DATA_DIR, "price_history.json")


def _read(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False)


def load_watchlist():
    for path in (os.path.join(DATA_DIR, "watchlist.json"),
                 os.path.join(HERE, "config.json"),
                 os.path.join(HERE, "watchlist.example.json")):
        data = _read(path, None)
        if isinstance(data, dict):
            wl = data.get("watchlist", data)
            if "cards" in wl or "skins" in wl:
                return {"cards": wl.get("cards", []), "skins": wl.get("skins", [])}
    return {"cards": [], "skins": []}


def card_prices(names):
    if not names:
        return {}
    cards = [_card_from_entry(n) for n in names]
    prices, _ = moxfield.price_cards(cards)
    out = {}
    for n, c in zip(names, cards):
        pr = prices.get(moxfield._ident_key(c), {})
        unit, _cur = moxfield._pick_price(pr, bool(c.get("foil")))
        if unit is not None:
            out["card:" + (n if isinstance(n, str) else c["name"])] = round(unit, 2)
    return out


def _card_from_entry(entry):
    """Una entrada de watchlist puede ser texto ('Sol Ring') o un objeto con
    set/colector/foil para fijar el arte alternativo exacto."""
    if isinstance(entry, dict):
        return {"name": entry.get("name", ""), "quantity": 1,
                "scryfall_id": entry.get("scryfall_id"),
                "set": entry.get("set"), "collector": entry.get("collector"),
                "foil": entry.get("foil", False)}
    return {"name": entry, "quantity": 1, "scryfall_id": None,
            "set": None, "collector": None, "foil": False}


def _csfloat_price(name, api_key):
    import urllib.parse
    url = ("https://csfloat.com/api/v1/listings?limit=1&sort_by=lowest_price"
           f"&market_hash_name={urllib.parse.quote(name)}")
    status, data = http.get_json(url, headers={"Authorization": api_key})
    if status == 200 and data:
        items = data.get("data") if isinstance(data, dict) else data
        if items:
            cents = items[0].get("price")        # CSFloat devuelve céntimos USD
            if cents:
                return round(cents / 100.0, 2)
    return None


def skin_prices(names):
    if not names:
        return {}
    api_key = os.environ.get("CSFLOAT_API_KEY", "").strip()
    cache = {}
    out = {}
    for i, name in enumerate(names):
        val = None
        try:
            if api_key:
                val = _csfloat_price(name, api_key)
            if val is None:
                val, _ = steam._price(name, 3, cache)   # 3 = EUR
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name}: {exc}")
        if val is not None:
            out["skin:" + name] = round(val, 2)
        if (i + 1) % 8 == 0:
            time.sleep(1.2)   # rate-limit del Steam Market
    return out


def main():
    wl = load_watchlist()
    print(f"Watchlist: {len(wl['cards'])} cartas, {len(wl['skins'])} skins")
    today = datetime.date.today().isoformat()
    prices = {}
    prices.update(card_prices(wl["cards"]))
    prices.update(skin_prices(wl["skins"]))
    history = _read(HISTORY, {})
    history[today] = prices
    _write(HISTORY, history)
    print(f"[{today}] guardados {len(prices)} precios en {HISTORY}")
    return prices


if __name__ == "__main__":
    main()
