"""
Trade Republic EN VIVO: cartera real leída de la API de la propia app.

Trade Republic no publica API para clientes; su app habla con
`api.traderepublic.com` y este módulo usa ese mismo protocolo (el que documenta
la comunidad en pytr). Es ingeniería inversa: puede romperse cuando TR cambie
algo, y entonces el resumen semanal lo dirá en voz alta en vez de arrastrar el
valor viejo. La vía manual por PDF/CSV (`sources/trade_republic.py`) sigue ahí.

Flujo, en dos fases:

  1. EMPAREJAR EL DISPOSITIVO (una sola vez, desde la web):
       a) `pair_start(telefono, pin)` -> TR manda un código de 4 dígitos.
       b) `pair_complete(process_id, codigo)` -> se genera un par de claves
          EC P-256, se registra la pública como dispositivo autorizado y la
          privada queda guardada en la base de datos.
     A partir de aquí ya no hace falta ningún código: es lo que permite que el
     resumen semanal se actualice solo.

  2. LEER LA CARTERA (cada vez):
       a) `login()` firma `{timestamp}.{cuerpo}` con la clave privada y obtiene
          un `sessionToken`.
       b) Por websocket se piden `compactPortfolio` (posiciones con su ISIN y
          número de títulos), `cash` (efectivo) y, por cada ISIN, `instrument`
          (nombre y bolsa) y `ticker` (precio actual).

Variables/ajustes:
    TR_PHONE   teléfono en formato internacional (+34…), o se pasa en la llamada
    TR_PIN     PIN de 4 dígitos de la app
La clave privada del dispositivo se guarda en el ajuste `tr_device_key`.
"""

import base64
import json
import os
import time

from . import http, db
from .common import Position

SOURCE = "Trade Republic"
CATEGORY = "Acciones / ETFs"

API = "https://api.traderepublic.com/api/v1"
WS_URL = "wss://api.traderepublic.com/"
ORIGIN = "https://app.traderepublic.com"

DEVICE_KEY_SETTING = "tr_device_key"
# Bolsas donde cotizan los valores de TR, en orden de preferencia para el precio.
EXCHANGES = ("LSX", "TDG", "TUB")

USER_AGENT = "TradeRepublic/Android 1.1.5534"
JSON_HEADERS = {"Content-Type": "application/json", "User-Agent": USER_AGENT,
                "Origin": ORIGIN, "Accept": "application/json"}


class NotPaired(RuntimeError):
    """No hay dispositivo emparejado todavía: hay que hacerlo una vez desde la web."""


class TradeRepublicError(RuntimeError):
    """Fallo real hablando con Trade Republic (login caducado, protocolo cambiado…)."""


# ---------------------------------------------------------------------------
# Emparejado del dispositivo (una sola vez)
# ---------------------------------------------------------------------------
def _credentials(phone=None, pin=None):
    phone = (phone or os.environ.get("TR_PHONE", "")).strip()
    pin = str(pin or os.environ.get("TR_PIN", "")).strip()
    if not phone or not pin:
        raise NotPaired("Faltan el teléfono (+34…) y el PIN de Trade Republic.")
    return phone, pin


def _post(path, payload, headers=None):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    hdrs = dict(JSON_HEADERS)
    if headers:
        hdrs.update(headers)
    status, text, out_headers = http.request_raw(API + path, "POST", body, hdrs)
    data = None
    if text:
        try:
            data = json.loads(text)
        except ValueError:
            data = None
    return status, data, text, out_headers


def pair_start(phone=None, pin=None):
    """Paso 1: pide a TR el código de emparejado. Devuelve el processId."""
    phone, pin = _credentials(phone, pin)
    status, data, text, _ = _post("/auth/account/reset/device",
                                  {"phoneNumber": phone, "pin": pin})
    if status != 200 or not data or not data.get("processId"):
        raise TradeRepublicError(
            f"Trade Republic rechazó el emparejado (HTTP {status}). {text[:200]}")
    return {"process_id": data["processId"],
            "countdown": data.get("countdownInSeconds")}


def pair_complete(process_id, code, phone=None, pin=None):
    """Paso 2: registra la clave pública con el código recibido y guarda la privada."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    if not process_id or not str(code).strip():
        raise ValueError("Faltan el processId y el código recibido de Trade Republic.")
    phone, pin = _credentials(phone, pin)
    key = ec.generate_private_key(ec.SECP256R1())
    public_der = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo)
    status, _data, text, _ = _post(
        f"/auth/account/reset/device/{process_id}/key",
        {"code": str(code).strip(), "deviceKey": base64.b64encode(public_der).decode()})
    if status not in (200, 201, 204):
        raise TradeRepublicError(
            f"Trade Republic no aceptó el código (HTTP {status}). {text[:200]}")
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()).decode()
    db.set_setting(DEVICE_KEY_SETTING, {"phone": phone, "pem": pem,
                                        "paired_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return {"paired": True, "phone": phone}


def is_paired():
    return bool((db.get_setting(DEVICE_KEY_SETTING, {}) or {}).get("pem"))


def unpair():
    db.set_setting(DEVICE_KEY_SETTING, {})


# ---------------------------------------------------------------------------
# Login firmado con la clave del dispositivo
# ---------------------------------------------------------------------------
def login(pin=None):
    """Inicia sesión firmando con la clave del dispositivo. Devuelve el sessionToken."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    saved = db.get_setting(DEVICE_KEY_SETTING, {}) or {}
    pem = saved.get("pem")
    if not pem:
        raise NotPaired("Trade Republic no está emparejado todavía: hazlo una vez "
                        "desde la web (teléfono + PIN + código).")
    phone = saved.get("phone") or os.environ.get("TR_PHONE", "").strip()
    pin = str(pin or os.environ.get("TR_PIN", "")).strip()
    if not pin:
        raise NotPaired("Falta TR_PIN para iniciar sesión en Trade Republic.")

    key = serialization.load_pem_private_key(pem.encode(), password=None)
    body = json.dumps({"phoneNumber": phone, "pin": pin}, separators=(",", ":"))
    ts = int(time.time() * 1000)
    signature = key.sign(f"{ts}.{body}".encode(), ec.ECDSA(hashes.SHA512()))
    status, text, headers = http.request_raw(
        API + "/auth/login", "POST", body.encode(),
        {**JSON_HEADERS, "X-Zeta-Timestamp": str(ts),
         "X-Zeta-Signature": base64.b64encode(signature).decode()})
    data = json.loads(text) if text.strip().startswith("{") else None
    token = (data or {}).get("sessionToken") or (headers or {}).get("X-Session-Token")
    if status != 200 or not token:
        raise TradeRepublicError(
            f"Login de Trade Republic rechazado (HTTP {status}). {text[:200]}")
    return token


# ---------------------------------------------------------------------------
# Websocket: el protocolo real de la app
# ---------------------------------------------------------------------------
class _Socket:
    """Websocket multiplexado de TR: `sub <id> <json>` / `<id> A|D|C|E <payload>`."""

    def __init__(self, token, locale="es", timeout=30):
        try:
            import websocket          # websocket-client
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise TradeRepublicError(
                "Falta la dependencia 'websocket-client' para hablar con "
                "Trade Republic (pip install -r requirements.txt).") from exc
        self._websocket = websocket
        self.token = token
        self.locale = locale
        self.timeout = timeout
        self.ws = None
        self._next_id = 1
        self._pending = {}

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        self.ws = self._websocket.create_connection(
            WS_URL, timeout=self.timeout, origin=ORIGIN,
            header=[f"User-Agent: {USER_AGENT}"])
        hello = {"locale": self.locale, "platformId": "webtrading",
                 "platformVersion": "chrome - 137.0.0",
                 "clientId": "app.traderepublic.com", "clientVersion": "3.151.3"}
        self.ws.send("connect 31 " + json.dumps(hello, separators=(",", ":")))
        reply = self.ws.recv()
        if not str(reply).startswith("connected"):
            raise TradeRepublicError(f"Trade Republic no aceptó la conexión: {reply!r}")

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close()
            finally:
                self.ws = None

    def _recv(self):
        """Lee un mensaje y lo parte en (id, código, payload)."""
        raw = str(self.ws.recv())
        head, _, payload = raw.partition(" ")
        code, _, body = payload.partition(" ")
        return head, code, body

    def ask(self, payload, timeout_reads=60):
        """Suscribe, espera la respuesta completa (A) y cancela la suscripción."""
        sub_id = str(self._next_id)
        self._next_id += 1
        if sub_id in self._pending:
            del self._pending[sub_id]
        message = dict(payload)
        message["token"] = self.token
        self.ws.send(f"sub {sub_id} " + json.dumps(message, separators=(",", ":")))
        for _ in range(timeout_reads):
            if sub_id in self._pending:
                break
            got_id, code, body = self._recv()
            if code == "E":
                if got_id == sub_id:
                    raise TradeRepublicError(f"Trade Republic devolvió un error: {body}")
                continue
            if code in ("A", "C"):
                self._pending[got_id] = body
        try:
            self.ws.send(f"unsub {sub_id}")
        except Exception:  # noqa: BLE001 - cerrar limpio nunca debe tapar el dato
            pass
        body = self._pending.pop(sub_id, None)
        if body is None:
            raise TradeRepublicError(
                f"Trade Republic no respondió a la suscripción {payload.get('type')!r}.")
        try:
            return json.loads(body) if body.strip() else None
        except ValueError as exc:
            raise TradeRepublicError(
                f"Respuesta no interpretable de Trade Republic: {body[:200]}") from exc


# ---------------------------------------------------------------------------
# Cartera
# ---------------------------------------------------------------------------
def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exchange_for(instrument):
    """Bolsa donde pedir el precio: la del propio instrumento si la declara."""
    exchanges = [ex.get("slice") or ex.get("id")
                 for ex in instrument.get("exchanges") or []]
    exchanges = [e for e in exchanges if e]
    home = instrument.get("homeExchangeId")
    if home and (not exchanges or home in exchanges):
        return home
    for preferred in EXCHANGES:
        if preferred in exchanges:
            return preferred
    return exchanges[0] if exchanges else EXCHANGES[0]


def _ticker_price(ticker):
    for field in ("last", "bid", "ask", "pre", "open"):
        price = _num((ticker.get(field) or {}).get("price"))
        if price:
            return price
    return None


def fetch_portfolio(token=None, locale="es"):
    """Posiciones reales (nombre, ISIN, títulos, precio) y efectivo, en EUR."""
    token = token or login()
    positions, warnings = [], []
    with _Socket(token, locale=locale) as sock:
        portfolio = sock.ask({"type": "compactPortfolio"}) or {}
        for entry in portfolio.get("positions") or []:
            isin = entry.get("instrumentId") or entry.get("isin")
            size = _num(entry.get("netSize") or entry.get("virtualSize"))
            if not isin or not size:
                continue
            try:
                instrument = sock.ask({"type": "instrument", "id": isin,
                                       "jurisdiction": "DE"}) or {}
            except TradeRepublicError as exc:
                warnings.append(f"{isin}: sin datos del instrumento ({exc}).")
                instrument = {}
            name = (instrument.get("name") or instrument.get("shortName") or isin).strip()
            price = None
            try:
                ticker = sock.ask({"type": "ticker",
                                   "id": f"{isin}.{_exchange_for(instrument)}"}) or {}
                price = _ticker_price(ticker)
            except TradeRepublicError as exc:
                warnings.append(f"{name}: sin precio en vivo ({exc}).")
            if price is None:
                warnings.append(f"Sin precio para «{name}» ({isin}); no suma al total.")
                price = 0.0
            positions.append(Position(
                source=SOURCE, category=CATEGORY, name=name, quantity=size,
                unit_value=price, value=round(size * price, 2),
                extra={"isin": isin,
                       "type": instrument.get("typeId") or instrument.get("type") or ""},
            ).finalize())

        cash_total = 0.0
        cash = sock.ask({"type": "cash"})
        for entry in (cash or []):
            if (entry.get("currencyId") or "EUR").upper() == "EUR":
                cash_total += _num(entry.get("amount")) or 0.0
    if cash_total:
        positions.append(Position(
            source=SOURCE, category=CATEGORY, name="Efectivo (cuenta corriente)",
            quantity=1.0, unit_value=cash_total, value=round(cash_total, 2),
            extra={"isin": ""}).finalize())
    return positions, warnings


def analyze(token=None):
    """Cartera de Trade Republic en el mismo formato que el parser de PDF/CSV."""
    positions, warnings = fetch_portfolio(token)
    return {
        "source": SOURCE + " (API)",
        "category": CATEGORY,
        "positions": [p.to_dict() for p in positions],
        "total": round(sum(p.value for p in positions), 2),
        "currency": "EUR",
        "warnings": warnings,
        "month": time.strftime("%Y-%m"),
    }
