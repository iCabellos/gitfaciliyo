"""
Trade Republic: cliente de su API **no oficial** (no hay API pública oficial).

Flujo de acceso (igual que la app/web de Trade Republic):
  1. `start_login(phone, pin)` -> Trade Republic manda un código 2FA (app o SMS)
     y devuelve un `process_id`.
  2. `complete_login(process_id, code)` -> valida el 2FA y devuelve las cookies de
     sesión (`tr_session` + `tr_refresh`). Guardamos SOLO esas cookies (no el PIN).
  3. En las ejecuciones semanales se refresca la sesión con la cookie `tr_refresh`
     (`refresh_session`) y se piden las posiciones con `portfolio`.

IMPORTANTE: es una API no oficial; Trade Republic puede cambiarla sin aviso. Todo
va protegido: si algo falla, el conector lo reporta y el resto de la sync sigue.
La valoración de la cartera llega por WebSocket; requiere el paquete opcional
`websocket-client` (si no está, `portfolio` lanza un error claro y se hace fallback
al PDF).

Doc de referencia de la comunidad: https://github.com/pytr-org/pytr
"""

import http.cookiejar
import json
import urllib.request

from .common import Position
from .http import _CTX  # contexto TLS que confía en la CA del proxy de salida

BASE = "https://api.traderepublic.com"
WS_URL = "wss://api.traderepublic.com/"
SOURCE = "Trade Republic"
CATEGORY = "Acciones / ETFs"

_HEADERS = {
    "User-Agent": "TradeRepublic/Android 30/App Version 1.1.5534",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _opener(cookiejar=None):
    handlers = [urllib.request.HTTPSHandler(context=_CTX)]
    if cookiejar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(cookiejar))
    return urllib.request.build_opener(*handlers)


def _post(path, payload, cookiejar=None, timeout=25):
    body = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(BASE + path, data=body, headers=_HEADERS, method="POST")
    try:
        resp = _opener(cookiejar).open(req, timeout=timeout)
        raw = resp.read().decode("utf-8", "replace")
        return getattr(resp, "status", 200), (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:  # noqa: PERF203
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"raw": raw}


def start_login(phone, pin):
    """Inicia el login. Devuelve {process_id, mode, seconds}. Dispara el 2FA."""
    phone = phone.strip()
    if not phone.startswith("+"):
        raise ValueError("El teléfono debe ir en formato internacional, p. ej. +34640253466.")
    status, data = _post("/api/v1/auth/web/login", {"phoneNumber": phone, "pin": str(pin)})
    if status != 200 or "processId" not in data:
        raise RuntimeError(f"Trade Republic rechazó el login ({status}). {data.get('errors') or data}")
    return {"process_id": data["processId"], "mode": data.get("2fa", "APP"),
            "seconds": data.get("countdownInSeconds", 0)}


def complete_login(process_id, code):
    """Valida el código 2FA. Devuelve las cookies de sesión a persistir."""
    jar = http.cookiejar.CookieJar()
    status, data = _post(f"/api/v1/auth/web/login/{process_id}/{str(code).strip()}", {}, cookiejar=jar)
    if status != 200:
        raise RuntimeError(f"Código 2FA inválido o caducado ({status}). {data}")
    cookies = {c.name: c.value for c in jar}
    if not cookies.get("tr_session"):
        raise RuntimeError("Trade Republic no devolvió sesión; reintenta el login.")
    return cookies


def refresh_session(cookies):
    """Renueva la cookie de sesión con la de refresco (para la sync semanal)."""
    jar = http.cookiejar.CookieJar()
    for name, value in (cookies or {}).items():
        jar.set_cookie(http.cookiejar.Cookie(
            0, name, value, None, False, ".traderepublic.com", True, False,
            "/", True, True, None, False, None, None, {}))
    status, _ = _post("/api/v1/auth/web/session", {}, cookiejar=jar)
    if status != 200:
        raise RuntimeError("La sesión de Trade Republic ha caducado; vuelve a hacer login.")
    return {c.name: c.value for c in jar} or cookies


def map_portfolio(positions, instruments, tickers, deck_name=SOURCE):
    """Función pura: combina posiciones + nombres + precios -> posiciones nuestras.

    positions:   [{instrumentId(ISIN), netSize}]
    instruments: {isin: shortName}
    tickers:     {isin: last_price}
    """
    out = []
    for p in positions:
        isin = p.get("instrumentId") or p.get("isin")
        if not isin:
            continue
        qty = float(p.get("netSize") or p.get("netQuantity") or 0)
        price = float(tickers.get(isin) or 0)
        value = round(qty * price, 2)
        out.append(Position(
            source=SOURCE, category=CATEGORY,
            name=instruments.get(isin) or isin, quantity=qty,
            unit_value=price, value=value, currency="EUR",
            extra={"isin": isin, "deck": deck_name},
        ).finalize())
    total = round(sum(p.value for p in out), 2)
    return {"source": SOURCE, "category": CATEGORY,
            "positions": [p.to_dict() for p in out], "total": total,
            "currency": "EUR", "warnings": []}


def portfolio(cookies, timeout=30):
    """Pide la cartera por WebSocket (experimental). Requiere `websocket-client`.

    Devuelve el mismo formato que `trade_republic.parse`. Si el WebSocket no está
    disponible o Trade Republic cambió el protocolo, lanza una excepción y el
    conector cae al flujo por PDF.
    """
    try:
        import websocket  # type: ignore  (paquete opcional 'websocket-client')
    except ImportError as exc:
        raise RuntimeError("Falta 'websocket-client' para leer la cartera de Trade Republic.") from exc

    session = (cookies or {}).get("tr_session")
    if not session:
        raise RuntimeError("Sin sesión de Trade Republic; haz login primero.")

    ws = websocket.create_connection(
        WS_URL, timeout=timeout, sslopt={"context": _CTX},
        header=[f"Cookie: tr_session={session}"])
    positions, instruments, tickers = [], {}, {}
    try:
        ws.send('connect 31 {"locale":"es","platformId":"webtrading"}')
        ws.recv()  # 'connected'
        # 1) Cartera compacta (posiciones con ISIN y cantidad).
        ws.send('sub 1 {"type":"compactPortfolio"}')
        _, payload = _ws_read(ws)
        positions = (payload or {}).get("positions", [])
        ws.send("unsub 1")
        # 2) Nombre y precio de cada posición.
        for i, p in enumerate(positions, start=2):
            isin = p.get("instrumentId")
            if not isin:
                continue
            ws.send(f'sub {i} {{"type":"instrument","id":"{isin}"}}')
            _, ins = _ws_read(ws)
            instruments[isin] = (ins or {}).get("shortName") or (ins or {}).get("name") or isin
            ws.send(f"unsub {i}")
            ws.send(f'sub {i}00 {{"type":"ticker","id":"{isin}"}}')
            _, tk = _ws_read(ws)
            bid = ((tk or {}).get("bid") or {}).get("price")
            last = (tk or {}).get("last", {}).get("price") if isinstance(tk.get("last"), dict) else None
            tickers[isin] = float(bid or last or 0)
            ws.send(f"unsub {i}00")
    finally:
        try:
            ws.close()
        except Exception:  # noqa: BLE001
            pass
    return map_portfolio(positions, instruments, tickers)


def _ws_read(ws, tries=6):
    """Lee mensajes 'A <sub> <code> <json>' hasta encontrar uno con payload JSON."""
    for _ in range(tries):
        msg = ws.recv()
        if not isinstance(msg, str):
            continue
        parts = msg.split(" ", 3)
        if len(parts) == 4 and parts[0] in ("A", "D"):
            try:
                return parts[1], json.loads(parts[3])
            except ValueError:
                continue
    return None, {}
