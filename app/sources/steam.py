"""
CS:GO / CS2 skins: conecta con el Steam Inventory y valora con el Steam Market.

Flujo en vivo:
  1. Descarga el inventario publico (appid 730, context 2) de un SteamID64.
  2. Agrupa los items por `market_hash_name` (solo los vendibles en el Market).
  3. Pide el precio a la API publica `market/priceoverview` (EUR por defecto).

Requisitos: el inventario de Steam debe estar en PUBLICO. El Market limita las
peticiones, asi que se cachean los precios en disco (TTL) y se trocea el trabajo;
si Steam responde 429 se devuelve lo obtenido con un aviso.
"""

import json
import os
import time
import urllib.parse

from . import http
from .common import parse_money, Position

SOURCE = "CS:GO"
CATEGORY = "Skins CS:GO"
APPID = 730
CONTEXTID = 2
CURRENCY = {"eur": 3, "usd": 1, "gbp": 2}

_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "steam_prices.json")
_TTL = 6 * 3600  # 6 horas


def _load_cache():
    try:
        with open(_CACHE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_FILE, "w") as fh:
        json.dump(cache, fh)


def fetch_inventory(steamid, count=5000):
    url = (f"https://steamcommunity.com/inventory/{steamid}/{APPID}/{CONTEXTID}"
           f"?l=english&count={count}")
    status, data = http.get_json(url)
    if status != 200 or not data:
        raise RuntimeError(f"Steam devolvió {status}. ¿Inventario público y SteamID64 correcto?")
    return data


def _group_items(inv):
    """Devuelve {market_hash_name: {count, marketable, type, icon}}."""
    desc = {}
    for d in inv.get("descriptions", []):
        desc[(d["classid"], d["instanceid"])] = d
    items = {}
    for a in inv.get("assets", []):
        d = desc.get((a["classid"], a["instanceid"]))
        if not d:
            continue
        name = d.get("market_hash_name")
        if not name:
            continue
        e = items.setdefault(name, {
            "count": 0,
            "marketable": bool(d.get("marketable")),
            "type": d.get("type", ""),
            "icon": "https://community.cloudflare.steamstatic.com/economy/image/" + d.get("icon_url", ""),
        })
        e["count"] += int(a.get("amount", 1))
    return items


def _price(name, currency_code, cache):
    key = f"{name}|{currency_code}"
    now = time.time()
    hit = cache.get(key)
    if hit and now - hit["t"] < _TTL:
        return hit["v"], False
    url = ("https://steamcommunity.com/market/priceoverview/"
           f"?appid={APPID}&currency={currency_code}"
           f"&market_hash_name={urllib.parse.quote(name)}")
    status, data = http.get_json(url)
    if status == 429:
        raise _RateLimited()
    val = None
    if status == 200 and data and data.get("success"):
        val = parse_money(data.get("median_price") or data.get("lowest_price"))
    cache[key] = {"t": now, "v": val}
    return val, True


class _RateLimited(Exception):
    pass


def analyze(steamid, currency="eur"):
    cur = CURRENCY.get(currency.lower(), 3)
    inv = fetch_inventory(steamid)
    items = _group_items(inv)
    cache = _load_cache()
    positions, warnings = [], []
    fetched = 0
    for name, info in sorted(items.items()):
        if not info["marketable"]:
            positions.append(Position(
                source=SOURCE, category=CATEGORY, name=name, quantity=info["count"],
                unit_value=0.0, value=0.0, extra={"type": info["type"], "icon": info["icon"],
                                                  "marketable": False}).finalize())
            continue
        try:
            unit, hit_net = _price(name, cur, cache)
            if hit_net:
                fetched += 1
                if fetched % 8 == 0:
                    time.sleep(1.2)   # respeta el rate-limit del Market
        except _RateLimited:
            warnings.append("Steam Market limitó las peticiones (429); precios parciales. "
                            "Vuelve a intentarlo en unos minutos (se cachea lo ya obtenido).")
            break
        if unit is None:
            warnings.append(f"Sin precio de mercado para «{name}».")
            unit = 0.0
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name=name, quantity=info["count"],
            unit_value=unit, value=round(unit * info["count"], 2),
            currency=currency.upper(),
            extra={"type": info["type"], "icon": info["icon"], "marketable": True},
        ).finalize())
    _save_cache(cache)
    total = round(sum(p.value for p in positions), 2)
    return {
        "source": SOURCE, "category": CATEGORY,
        "positions": [p.to_dict() for p in positions],
        "total": total, "currency": currency.upper(), "warnings": warnings,
    }
