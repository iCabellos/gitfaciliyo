"""
Seguimiento DIARIO de precios de cartas Magic y skins de CS:GO.

Ejecuta una vez al día (cron). Construye la watchlist a partir de lo que
REALMENTE tienes y guarda los precios en data/price_history.json Y en la tabla
`price_history` de la base de datos (para que la web los pueda consultar), una
entrada por día:

    { "2026-06-26": { "card:Sol Ring": 3.85, "skin:AK-47 | Redline (Field-Tested)": 37.5 } }

¿De dónde sale la watchlist? (en este orden, y sin inventarse nada):
  1. Override explícito: data/watchlist.json o "watchlist" en config.json.
  2. Skins  -> tu inventario público de Steam (STEAM_ID64 o config.steam.steamid64).
              Se siguen SOLO las skins vendibles que de verdad tienes.
  3. Cartas -> tu lista guardada de Magic (setting `magic_cards`, si hay DB).

Si no hay nada configurado NO se sigue nada, pero el trabajo FALLA con un error
claro en vez de terminar en silencio: un histórico que deja de crecer sin avisar
es justo lo que hace que el resumen semanal repita las mismas cifras durante
semanas. El fichero watchlist.example.json es solo un ejemplo y NUNCA se usa
como fuente real.

Fuentes de precio:
  * Cartas Magic  -> Scryfall (actualiza precios a diario; EUR preferente, USD si no hay).
  * Skins CS:GO   -> Steam Market por defecto; CSFloat si defines CSFLOAT_API_KEY.
"""

import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from sources import moxfield, steam, http, prices, settings  # noqa: E402

DATA_DIR = prices.DATA_DIR
HISTORY = prices.HISTORY_FILE


def _read(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# --------------------------------------------------------------------------
# Watchlist: se deriva de lo que realmente tienes
# --------------------------------------------------------------------------
def skins_from_inventory():
    """Skins vendibles del inventario público de Steam (las que de verdad tienes)."""
    sid = settings.steam_id64()
    if not sid:
        return []
    try:
        items = steam._group_items(steam.fetch_inventory(sid))
    except Exception as exc:  # noqa: BLE001
        print("  ! No pude leer el inventario de Steam:", exc)
        return []
    return sorted(name for name, info in items.items()
                  if name and info.get("marketable"))


def cards_from_saved():
    """Cartas de tu lista guardada de Magic (setting `magic_cards`), si hay DB."""
    try:
        from sources import db
        saved = db.get_setting("magic_cards", {}) or {}
    except Exception as exc:  # noqa: BLE001
        print("  ! No pude leer la lista de Magic guardada:", exc)
        return []
    reference = (saved.get("reference") or "").strip()
    decklist = saved.get("decklist") or ""
    cards = []
    try:
        if decklist.strip():
            cards = moxfield.cards_from_decklist(decklist)
        elif reference:
            _name, cards = moxfield.cards_from_moxfield(reference)
    except Exception as exc:  # noqa: BLE001
        print("  ! No pude interpretar la lista de Magic:", exc)
        return []
    # Nos quedamos con entradas que conservan set/nº/foil para valorar el arte exacto.
    return [{"name": c.get("name"), "set": c.get("set"), "collector": c.get("collector"),
             "scryfall_id": c.get("scryfall_id"), "foil": c.get("foil", False)}
            for c in cards if c.get("name")]


def load_watchlist():
    """Watchlist real: override explícito y, si no, derivada de tus tenencias."""
    explicit = {}
    for path in (os.path.join(DATA_DIR, "watchlist.json"),
                 os.path.join(HERE, "watchlist.json"),
                 os.path.join(HERE, "config.json")):
        data = _read(path, None)
        if isinstance(data, dict):
            wl = data.get("watchlist", data)
            if isinstance(wl, dict) and ("cards" in wl or "skins" in wl):
                explicit = wl
                break
    cards = explicit.get("cards") or cards_from_saved()
    skins = explicit.get("skins") or skins_from_inventory()
    return {"cards": cards, "skins": skins}


def _card_from_entry(entry):
    """Una entrada puede ser texto ('Sol Ring') o un objeto con set/nº/foil."""
    if isinstance(entry, dict):
        return {"name": entry.get("name", ""), "quantity": 1,
                "scryfall_id": entry.get("scryfall_id"),
                "set": entry.get("set"), "collector": entry.get("collector"),
                "foil": entry.get("foil", False)}
    return {"name": entry, "quantity": 1, "scryfall_id": None,
            "set": None, "collector": None, "foil": False}


def _entry_name(entry):
    return entry.get("name", "") if isinstance(entry, dict) else entry


def card_prices(names):
    if not names:
        return {}
    cards = [_card_from_entry(n) for n in names]
    scryfall, _ = moxfield.price_cards(cards)
    out = {}
    for n, c in zip(names, cards):
        pr = scryfall.get(moxfield._ident_key(c), {})
        unit, _cur = moxfield._pick_price(pr, bool(c.get("foil")))
        if unit is not None:
            out["card:" + (_entry_name(n) or c["name"])] = round(unit, 2)
    return out


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
    """Precio de cada skin. Devuelve (precios, avisos).

    Comparte con `steam.analyze` la misma caché (TTL 6 h, en base de datos si la
    hay): sin eso, abrir la web y ejecutar el cron seguidos duplicaban las
    peticiones al Market y Steam cortaba a mitad. El ritmo y los reintentos por
    429 los pone `steam._price`; si aun así corta, se para y se avisa en vez de
    seguir pidiendo y quedarse con medio inventario en silencio.
    """
    if not names:
        return {}, []
    api_key = os.environ.get("CSFLOAT_API_KEY", "").strip()
    cache = steam._load_cache()
    out, warnings = {}, []
    for name in names:
        val = None
        try:
            if api_key:
                val = _csfloat_price(name, api_key)
            if val is None:
                val, _hit_net = steam._price(name, 3, cache)   # 3 = EUR; ritmo en steam._price
        except steam._RateLimited:
            warnings.append(
                f"Steam Market cortó por rate-limit (429) tras {len(out)} de "
                f"{len(names)} skins. Se guarda lo obtenido; reintenta en unos "
                "minutos (lo ya pedido queda en caché).")
            break
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"{name}: {exc}")
        if val is not None:
            out["skin:" + name] = round(val, 2)
    steam._save_cache(cache)
    return out, warnings


NOTHING_TO_TRACK = (
    "Nada que seguir: el histórico de precios no puede crecer.\n"
    "  · Skins  -> define STEAM_ID64 (o abre una vez la web con tu SteamID64) "
    "y deja el inventario de Steam en público.\n"
    "  · Cartas -> guarda tu lista de Magic en la web (necesita DATABASE_URL "
    "para leerla desde el cron).")


def main():
    """Registra el punto de hoy: patrimonio completo + precios de cartas y skins.

    Falla (excepción) si no hay nada que seguir. El patrimonio se registra ANTES
    de comprobar la watchlist: aunque Steam o Magic no estén configurados, el
    histórico del patrimonio debe seguir creciendo.
    """
    today = datetime.date.today().isoformat()
    try:
        saved = prices.record_portfolio(today)
        print(f"Patrimonio: {saved} series registradas"
              if saved else "Patrimonio: sin snapshots todavía, nada que registrar.")
    except Exception as exc:  # noqa: BLE001 - no debe impedir seguir los precios
        print(f"  ! No pude registrar el patrimonio (¿sin DATABASE_URL?): {exc}")

    wl = load_watchlist()
    print(f"Watchlist: {len(wl['cards'])} cartas, {len(wl['skins'])} skins")
    if not wl["cards"] and not wl["skins"]:
        raise RuntimeError(NOTHING_TO_TRACK)
    day_prices = {}
    day_prices.update(card_prices(wl["cards"]))
    skins, warnings = skin_prices(wl["skins"])
    day_prices.update(skins)
    if not day_prices:
        raise RuntimeError(
            f"Ninguna de las {len(wl['cards'])} cartas y {len(wl['skins'])} skins "
            "de la watchlist devolvió precio (Scryfall/Steam Market). No se "
            "registra un día vacío.")
    to_file, to_db = prices.record(today, day_prices)
    print(f"[{today}] {to_file} precios en {HISTORY}"
          + (f" y {to_db} en la base de datos" if to_db else " (sin base de datos)"))
    for w in warnings:
        print(f"  ! {w}")
    # Lo obtenido ya está guardado, pero un día incompleto no puede pasar por
    # bueno: el trabajo se pone en rojo para que se vea y se reintente.
    faltan = len(wl["skins"]) - len(skins)
    if faltan > 0:
        raise RuntimeError(
            f"Día registrado a medias: faltan {faltan} de {len(wl['skins'])} skins. "
            + (warnings[-1] if warnings else "Revisa los avisos de arriba."))
    return day_prices


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"\n❌ {exc}")
        raise SystemExit(1)
