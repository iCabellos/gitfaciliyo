"""Tipo de cambio en vivo (gratis) con caché diaria. USD -> EUR."""

from . import http, db


def rate_usd_eur():
    cached = db.cache_get_today("fx:usd_eur")
    if cached and cached.get("rate"):
        return cached["rate"]
    rate = None
    for url, pick in (
        ("https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR", lambda d: d["rates"]["EUR"]),
        ("https://open.er-api.com/v6/latest/USD", lambda d: d["rates"]["EUR"]),
    ):
        try:
            status, data = http.get_json(url)
            if status == 200 and data:
                rate = float(pick(data))
                break
        except Exception:  # noqa: BLE001
            continue
    if rate:
        db.cache_put("fx:usd_eur", {"rate": rate})
    return rate


def usd_to_eur(amount):
    r = rate_usd_eur()
    return round(amount * r, 2) if r else None
