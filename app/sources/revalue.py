"""
Revalorización en vivo, en el servidor, de las CUATRO fuentes de patrimonio.

El resumen semanal (POST /api/monthly-summary) la usa para que las categorías se
actualicen aunque nadie abra la web, con la configuración ya guardada:

  * Skins CS:GO      -> inventario de Steam + Steam Market.
  * Cartas Magic     -> lista guardada + Scryfall.
  * Liquidez (banco) -> imagin por PSD2 (Enable Banking).
  * Acciones / ETFs  -> cartera de Trade Republic por su API.

Reglas:
  * Fuente sin conectar -> NotConfigured: no es un fallo, pero SÍ se reporta
    (aparece en `skipped`) para que se vea por qué esa cifra no se mueve.
  * Fuente conectada que falla -> la excepción llega al llamador para que el
    fallo sea VISIBLE (nada de valores antiguos disfrazados de nuevos).
  * Si Steam corta por rate-limit (429) el total sería parcial: se descarta y
    se reporta el error en vez de guardar un valor incompleto.
"""

import datetime

from . import (steam, moxfield, db, enablebanking, trade_republic_live, ingest,
               settings)


class NotConfigured(RuntimeError):
    """La fuente no está configurada: se omite sin considerarlo un fallo."""


def refresh_skins(month):
    """Valora el inventario de Steam en vivo y guarda el snapshot del mes."""
    sid = settings.steam_id64()
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


def refresh_bank(month):
    """Lee imagin por PSD2 (Enable Banking) y guarda liquidez y flujos del mes."""
    try:
        r = enablebanking.analyze()
    except enablebanking.NotConfigured as exc:
        raise NotConfigured(str(exc)) from exc
    aggregates = dict(r.get("aggregates") or {})
    aggregates["month"] = aggregates.get("month") or month
    ingest.persist_bank_aggregates(aggregates)
    balance = r.get("available_balance")
    if balance is None:
        raise RuntimeError("imagin no devolvió saldo de ninguna cuenta.")
    return round(balance, 2)


def refresh_stocks(month):
    """Lee la cartera de Trade Republic por su API y guarda snapshot y posiciones."""
    try:
        r = trade_republic_live.analyze()
    except trade_republic_live.NotPaired as exc:
        raise NotConfigured(str(exc)) from exc
    ingest.persist_positions(month, trade_republic_live.SOURCE, r["positions"])
    db.set_snapshot(month, r["category"], r["total"])
    return r["total"]


SOURCES = (
    ("Skins CS:GO", refresh_skins),
    ("Cartas Magic", refresh_cards),
    ("Liquidez (banco)", refresh_bank),
    ("Acciones / ETFs", refresh_stocks),
)


def refresh_live(month=None):
    """Revaloriza todas las fuentes en vivo para `month` (por defecto, el actual).

    Devuelve (results, errors, skipped):
      * results[categoría] = total guardado.
      * errors[categoría]  = mensaje del fallo de una fuente SÍ configurada.
      * skipped[categoría] = por qué una fuente no está conectada todavía.

    Lo no configurado se devuelve aparte —y no en silencio— porque una categoría
    que nunca se revaloriza es exactamente lo que hace que el resumen semanal
    repita las mismas cifras sin que se note.
    """
    month = month or datetime.date.today().strftime("%Y-%m")
    results, errors, skipped = {}, {}, {}
    for category, fn in SOURCES:
        try:
            results[category] = fn(month)
        except NotConfigured as exc:
            skipped[category] = str(exc)
        except Exception as exc:  # noqa: BLE001
            errors[category] = str(exc)
    return results, errors, skipped
