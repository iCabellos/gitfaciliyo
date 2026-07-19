"""
Revalorización en vivo, en el servidor, de skins CS:GO y cartas Magic.

El resumen semanal (POST /api/monthly-summary) la usa para que esas categorías
se actualicen aunque nadie abra la web: lee la configuración que ya está
guardada (SteamID64 y lista de Magic), pide los precios REALES a Steam Market
y Scryfall y guarda el snapshot del mes actual.

Reglas:
  * Fuente sin configurar -> NotConfigured (se omite, no es un error).
  * Fuente configurada que falla -> la excepción llega al llamador para que el
    fallo sea VISIBLE (nada de valores antiguos disfrazados de nuevos).
  * Si Steam corta por rate-limit (429) el total sería parcial: se descarta y
    se reporta el error en vez de guardar un valor incompleto.
"""

import datetime
import json
import os

from . import steam, moxfield, db

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NotConfigured(RuntimeError):
    """La fuente no está configurada: se omite sin considerarlo un fallo."""


def _config_steamid():
    try:
        with open(os.path.join(_HERE, "config.json")) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return ""
    return str((cfg.get("steam") or {}).get("steamid64", "")).strip()


def _steamid():
    """SteamID64 real: entorno > setting guardado por la web > config.json."""
    for sid in (os.environ.get("STEAM_ID64", "").strip(),
                str(db.get_setting("steam_id64", "") or "").strip(),
                _config_steamid()):
        if sid and not sid.startswith("TU_"):
            return sid
    return ""


def refresh_skins(month):
    """Valora el inventario de Steam en vivo y guarda el snapshot del mes."""
    sid = _steamid()
    if not sid:
        raise NotConfigured("Sin SteamID64 guardado (ábrelo una vez en la web "
                            "o define STEAM_ID64).")
    r = steam.analyze(sid)
    partial = [w for w in r.get("warnings", []) if "429" in w]
    if partial:
        raise RuntimeError(partial[0])
    db.set_snapshot(month, r["category"], r["total"])
    return r["total"]


def refresh_cards(month):
    """Valora la lista de Magic guardada en vivo y guarda el snapshot del mes."""
    saved = db.get_setting("magic_cards", {}) or {}
    reference = (saved.get("reference") or "").strip()
    decklist = saved.get("decklist") or ""
    if not reference and not decklist.strip():
        raise NotConfigured("Sin lista de Magic guardada (guárdala una vez en la web).")
    r = moxfield.analyze(reference=reference or None, decklist=decklist)
    db.set_snapshot(month, r["category"], r["total"])
    return r["total"]


def refresh_live(month=None):
    """Revaloriza skins y cartas para `month` (por defecto, el mes actual).

    Devuelve (results, errors): results[categoría] = total guardado y
    errors[categoría] = mensaje del fallo. Lo no configurado no aparece.
    """
    month = month or datetime.date.today().strftime("%Y-%m")
    results, errors = {}, {}
    for category, fn in (("Skins CS:GO", refresh_skins),
                         ("Cartas Magic", refresh_cards)):
        try:
            results[category] = fn(month)
        except NotConfigured:
            continue
        except Exception as exc:  # noqa: BLE001
            errors[category] = str(exc)
    return results, errors
