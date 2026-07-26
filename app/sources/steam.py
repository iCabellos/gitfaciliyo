"""
CS:GO / CS2 skins: conecta con el Steam Inventory y valora con el Steam Market.

Flujo en vivo:
  1. Descarga el inventario publico (appid 730, context 2) de un SteamID64,
     PAGINANDO: Steam sirve como mucho 2000 objetos por peticion y encadena las
     paginas con `more_items` + `last_assetid`.
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
# Tope de objetos por peticion que acepta Steam. Pedir mas NO devuelve mas: la
# peticion se rechaza entera (400/429), y durante meses eso se confundio con un
# inventario privado. Comprobado contra la API: 2000 pasa, 2001 ya no.
PAGE_SIZE = 2000
# Tope de seguridad para no encadenar paginas indefinidamente.
MAX_ITEMS = 20000

_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "steam_prices.json")
_TTL = 6 * 3600  # 6 horas

# Ritmo contra el Steam Market. Medido contra la API real: pidiendo cada 1,2 s
# corta por 429 alrededor de la peticion 37. Con 3 s aguanta el inventario
# entero. Ajustable por si Steam cambia de humor.
MARKET_DELAY = float(os.environ.get("STEAM_MARKET_DELAY", "3.0"))
RATE_LIMIT_WAIT = float(os.environ.get("STEAM_RATE_LIMIT_WAIT", "30"))
RATE_LIMIT_RETRIES = int(os.environ.get("STEAM_RATE_LIMIT_RETRIES", "2"))

_last_fetch = 0.0


def _wait_turn():
    """Espacia las peticiones al Market: el limite es por IP, no por proceso."""
    global _last_fetch
    pending = MARKET_DELAY - (time.time() - _last_fetch)
    if pending > 0:
        time.sleep(pending)
    _last_fetch = time.time()


def _load_cache():
    """Caché de precios: la base de datos si la hay, si no un fichero local.

    Compartirla importa: el cron diario y la web piden los mismos precios, y con
    cachés separadas se duplicaban las peticiones y Steam cortaba a mitad. En la
    base de datos además sobrevive a los reinicios de Render, donde el disco de
    `sources/.cache/` es efímero.
    """
    try:
        from . import db
        cached = db.cache_get_today("steam_prices")
        if isinstance(cached, dict):
            return cached
    except Exception as exc:  # noqa: BLE001 - sin DB seguimos con el fichero
        print(f"  ! Caché de precios en base de datos no disponible: {exc}")
    try:
        with open(_CACHE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        from . import db
        db.cache_put("steam_prices", cache)
        return
    except Exception:  # noqa: BLE001
        pass
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_FILE, "w") as fh:
        json.dump(cache, fh)


def _inventory_error(status, steamid):
    """Mensaje exacto por codigo HTTP: cada uno se arregla de forma distinta."""
    if status in (401, 403):
        return RuntimeError(
            "Steam no deja leer el inventario: está en privado. En Steam: Editar perfil → "
            "Privacidad → «Detalles del juego» = Público y desmarca «Mantener mi inventario "
            "siempre privado». Luego vuelve a intentarlo.")
    if status == 429:
        return RuntimeError(
            "Steam ha limitado las peticiones (429). Espera unos minutos y reinténtalo; "
            "el inventario no tiene nada de malo.")
    if status == 404:
        return RuntimeError(f"Steam no encuentra el perfil {steamid}. ¿Es correcto el SteamID64?")
    if status == 400:
        return RuntimeError(
            f"Steam rechazó la petición del inventario (400) para {steamid}. Suele ser un "
            "SteamID64 mal formado.")
    return RuntimeError(f"Steam devolvió {status} al pedir el inventario de {steamid}.")


def fetch_inventory(steamid, max_items=MAX_ITEMS):
    """Inventario público COMPLETO, encadenando páginas de {PAGE_SIZE} objetos.

    Steam pagina con `more_items` + `last_assetid`; sin seguir esas páginas, un
    inventario grande se quedaría a medias y el patrimonio saldría corto.
    """
    base = (f"https://steamcommunity.com/inventory/{steamid}/{APPID}/{CONTEXTID}"
            f"?l=english&count={PAGE_SIZE}")
    assets, descriptions, seen = [], [], set()
    start_assetid = None
    while True:
        url = base + (f"&start_assetid={start_assetid}" if start_assetid else "")
        status, data = http.get_json(url)
        if status != 200 or not isinstance(data, dict):
            raise _inventory_error(status, steamid)
        assets.extend(data.get("assets") or [])
        for d in data.get("descriptions") or []:
            key = (d.get("classid"), d.get("instanceid"))
            if key not in seen:
                seen.add(key)
                descriptions.append(d)
        start_assetid = data.get("last_assetid")
        if not data.get("more_items") or not start_assetid or len(assets) >= max_items:
            break
        time.sleep(1.0)     # cortesía entre páginas
    return {"assets": assets, "descriptions": descriptions,
            "total_inventory_count": len(assets)}


def _tags_by_category(description):
    """Indexa los `tags` de un item de Steam por su categoría (Rarity, Exterior…)."""
    out = {}
    for t in description.get("tags", []) or []:
        cat = t.get("category")
        if cat:
            out[cat] = t
    return out


def _skin_meta(description):
    """Extrae metadatos reales del item para pintar la carta (rareza, color, desgaste…).

    Todo sale de las `tags` que devuelve Steam; se omite lo que no venga.
    """
    tags = _tags_by_category(description)
    meta = {}
    rarity = tags.get("Rarity")
    if rarity:
        meta["rarity"] = rarity.get("localized_tag_name", "")
        color = rarity.get("color")
        if color:
            meta["rarity_color"] = "#" + color.lstrip("#")
    exterior = tags.get("Exterior")
    if exterior:
        meta["exterior"] = exterior.get("localized_tag_name", "")
    weapon = tags.get("Weapon")
    if weapon:
        meta["weapon"] = weapon.get("localized_tag_name", "")
    quality = tags.get("Quality")   # StatTrak™ / Souvenir / Normal…
    if quality:
        q_internal = (quality.get("internal_name") or "").lower()
        if q_internal not in ("", "normal"):
            meta["quality"] = quality.get("localized_tag_name", "")
    name_color = description.get("name_color")
    if name_color:
        meta["name_color"] = "#" + name_color.lstrip("#")
    return meta


def _group_items(inv):
    """Devuelve {market_hash_name: {count, marketable, type, icon, meta…}}."""
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
        e = items.get(name)
        if e is None:
            e = {
                "count": 0,
                "marketable": bool(d.get("marketable")),
                "type": d.get("type", ""),
                "icon": "https://community.cloudflare.steamstatic.com/economy/image/" + d.get("icon_url", ""),
            }
            e.update(_skin_meta(d))
            items[name] = e
        e["count"] += int(a.get("amount", 1))
    return items


def _price(name, currency_code, cache):
    """Precio de una skin. Devuelve (valor, si_hubo_peticion_de_red).

    Espacia las peticiones y, si aun asi llega un 429, espera y reintenta antes
    de rendirse: un corte pasajero no debe dejar el inventario a medias.
    """
    key = f"{name}|{currency_code}"
    now = time.time()
    hit = cache.get(key)
    if hit and now - hit["t"] < _TTL:
        return hit["v"], False
    url = ("https://steamcommunity.com/market/priceoverview/"
           f"?appid={APPID}&currency={currency_code}"
           f"&market_hash_name={urllib.parse.quote(name)}")
    status, data = None, None
    for intento in range(RATE_LIMIT_RETRIES + 1):
        _wait_turn()
        status, data = http.get_json(url)
        if status != 429:
            break
        if intento < RATE_LIMIT_RETRIES:
            print(f"  · 429 en «{name}»; espero {RATE_LIMIT_WAIT:.0f}s y reintento.")
            time.sleep(RATE_LIMIT_WAIT)
    if status == 429:
        raise _RateLimited(
            f"Steam Market sigue limitando tras {RATE_LIMIT_RETRIES} reintentos.")
    val = None
    if status == 200 and data and data.get("success"):
        val = parse_money(data.get("median_price") or data.get("lowest_price"))
    cache[key] = {"t": time.time(), "v": val}
    return val, True


class _RateLimited(Exception):
    """Steam Market ha devuelto 429. Lleva mensaje: al imprimirla debe leerse algo."""

    def __init__(self, message="Steam Market limitó las peticiones (429)."):
        super().__init__(message)


def analyze(steamid, currency="eur"):
    cur = CURRENCY.get(currency.lower(), 3)
    inv = fetch_inventory(steamid)
    items = _group_items(inv)
    cache = _load_cache()
    positions, warnings = [], []
    fetched = 0
    for name, info in sorted(items.items()):
        meta = {k: info[k] for k in ("rarity", "rarity_color", "exterior", "weapon",
                                     "quality", "name_color") if k in info}
        if not info["marketable"]:
            positions.append(Position(
                source=SOURCE, category=CATEGORY, name=name, quantity=info["count"],
                unit_value=0.0, value=0.0, extra={"type": info["type"], "icon": info["icon"],
                                                  "marketable": False, **meta}).finalize())
            continue
        try:
            unit, hit_net = _price(name, cur, cache)
            fetched += hit_net
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
            extra={"type": info["type"], "icon": info["icon"], "marketable": True, **meta},
        ).finalize())
    _save_cache(cache)
    total = round(sum(p.value for p in positions), 2)
    return {
        "source": SOURCE, "category": CATEGORY,
        "positions": [p.to_dict() for p in positions],
        "total": total, "currency": currency.upper(), "warnings": warnings,
    }
