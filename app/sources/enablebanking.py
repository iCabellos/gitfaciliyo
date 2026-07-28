"""
imagin / CaixaBank en vivo por PSD2, con Enable Banking.

imagin no tiene API propia para particulares: el acceso programático va por
open banking. Enable Banking es un agregador regulado con alta self-service y
modo «restricted production» gratuito para acceder a TUS PROPIAS cuentas, que
es exactamente este caso (ver `BANCOS_API.md`).

Flujo:
  1. `start_auth()` crea una autorización y devuelve la URL donde imagin pide el
     SCA (DNI + PIN/biometría). El usuario la abre y autoriza.
  2. El banco redirige a `redirect_url` con `?code=…&state=…` (o con
     `?error=…&error_description=…` si algo falla). La web recoge ese `code` en
     su ruta de retorno y `complete_auth(code, state)` crea la sesión y guarda
     su `session_id` y las cuentas en la base de datos.
  3. `analyze()` lee saldos y movimientos de la sesión guardada y los clasifica
     con la MISMA lógica del extracto en PDF (`bank.analyze_raw`).

El consentimiento PSD2 caduca (90/180 días según banco). Cuando caduca, la API
devuelve error y este módulo lo propaga tal cual: el resumen semanal lo dirá con
un ⚠️ y la web ofrecerá volver a autorizar. Nunca se arrastra un saldo viejo
haciéndolo pasar por nuevo.

Configuración (variables de entorno del servidor):
    ENABLE_BANKING_APP_ID        id de la aplicación registrada
    ENABLE_BANKING_PRIVATE_KEY   clave privada PEM (o su base64), o…
    ENABLE_BANKING_KEY_PATH      …ruta a la clave privada PEM
    ENABLE_BANKING_ASPSP         banco (opcional: si no, el elegido en la web)
    ENABLE_BANKING_COUNTRY       país (por defecto 'ES')
    ENABLE_BANKING_REDIRECT_URL  URL de retorno registrada en Enable Banking.
                                 Opcional: si no está, se usa la ruta de retorno
                                 de la propia web (/imagin/callback).
Doc: https://enablebanking.com/docs/api/reference/
"""

import base64
import datetime
import os
import urllib.parse
import uuid

from . import http, bank, db

API = "https://api.enablebanking.com"
SOURCE = "imagin (Enable Banking)"
SESSION_SETTING = "enablebanking_session"
PENDING_SETTING = SESSION_SETTING + ":pending"
# Banco elegido desde la web. Que sea un ajuste y no solo una variable de
# entorno es lo que permite descubrir cómo se llama TU banco en Enable Banking
# (`list_aspsps`) y elegirlo sin tocar el servidor.
ASPSP_SETTING = "enablebanking_aspsp"

DEFAULT_ASPSP = "imagin"
DEFAULT_COUNTRY = "ES"
# Días de vigencia que se piden para el consentimiento (el banco puede recortarlo).
CONSENT_DAYS = 90
# Cuántos días de movimientos se traen por defecto (el mes en curso y el anterior).
HISTORY_DAYS = 60


class NotConfigured(RuntimeError):
    """Falta la aplicación de Enable Banking o la autorización del banco."""


class EnableBankingError(RuntimeError):
    """Enable Banking o el banco han devuelto un error (p. ej. consentimiento caducado)."""


# ---------------------------------------------------------------------------
# Autenticación de la aplicación (JWT firmado con su clave privada)
# ---------------------------------------------------------------------------
def _private_key():
    """Clave privada PEM: variable de entorno (PEM o base64) o fichero."""
    raw = os.environ.get("ENABLE_BANKING_PRIVATE_KEY", "").strip()
    if raw:
        if "BEGIN" in raw:
            return raw.replace("\\n", "\n")
        try:
            return base64.b64decode(raw).decode()
        except Exception as exc:  # noqa: BLE001
            raise NotConfigured(
                "ENABLE_BANKING_PRIVATE_KEY no es ni un PEM ni su base64.") from exc
    path = os.environ.get("ENABLE_BANKING_KEY_PATH", "").strip()
    if path:
        try:
            with open(path) as fh:
                return fh.read()
        except OSError as exc:
            raise NotConfigured(f"No pude leer la clave de Enable Banking: {exc}") from exc
    raise NotConfigured("Falta ENABLE_BANKING_PRIVATE_KEY (o ENABLE_BANKING_KEY_PATH).")


def _app_id():
    app_id = os.environ.get("ENABLE_BANKING_APP_ID", "").strip()
    if not app_id:
        raise NotConfigured("Falta ENABLE_BANKING_APP_ID (id de tu aplicación).")
    return app_id


def _jwt(ttl=3600):
    """JWT RS256 con el id de la aplicación como `kid`, tal y como pide la API."""
    try:
        import jwt as pyjwt
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise EnableBankingError(
            "Falta la dependencia 'PyJWT[crypto]' para firmar contra Enable "
            "Banking (pip install -r requirements.txt).") from exc
    now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    return pyjwt.encode(
        {"iss": "enablebanking.com", "aud": "api.enablebanking.com",
         "iat": now, "exp": now + ttl},
        _private_key(), algorithm="RS256", headers={"kid": _app_id()})


def _api(path, method="GET", payload=None):
    """Llamada autenticada. Devuelve el JSON o lanza EnableBankingError."""
    headers = {"Authorization": "Bearer " + _jwt()}
    url = API + path
    if method == "GET":
        status, data = http.get_json(url, headers=headers, timeout=40)
    else:
        status, data = http.post_json(url, payload or {}, headers=headers, timeout=40)
    if status >= 400 or data is None:
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("message") or data.get("error") or data)[:300]
        raise EnableBankingError(f"Enable Banking devolvió {status}. {detail}".strip())
    return data


# ---------------------------------------------------------------------------
# Autorización del banco (SCA en la app de imagin)
# ---------------------------------------------------------------------------
def default_country():
    return os.environ.get("ENABLE_BANKING_COUNTRY", "").strip() or DEFAULT_COUNTRY


def default_aspsp():
    """Banco con el que se autoriza: variable de entorno > elegido en la web > imagin.

    Mismo orden de precedencia que el resto de ajustes (`sources/settings.py`):
    lo que fija el servidor manda sobre lo que se guardó desde el navegador.
    """
    env_name = os.environ.get("ENABLE_BANKING_ASPSP", "").strip()
    if env_name:
        return {"name": env_name, "country": default_country()}
    try:
        saved = db.get_setting(ASPSP_SETTING, {}) or {}
    except Exception:  # noqa: BLE001 - sin base de datos, se usa el de por defecto
        saved = {}
    name = str(saved.get("name") or "").strip()
    if name:
        return {"name": name,
                "country": str(saved.get("country") or "").strip() or default_country()}
    return {"name": DEFAULT_ASPSP, "country": default_country()}


def set_aspsp(name, country=None):
    """Guarda el banco elegido desde la web (el que se usará al autorizar)."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("Indica el nombre del banco tal y como lo lista Enable Banking.")
    target = {"name": name, "country": (str(country or "").strip() or default_country()).upper()}
    db.set_setting(ASPSP_SETTING, target)
    return target


def list_aspsps(country=None, psu_type="personal"):
    """Bancos que Enable Banking soporta en ese país, para elegir el tuyo.

    Sin esto no hay forma de saber con qué nombre EXACTO está dado de alta tu
    banco, y `POST /auth` falla con un error opaco si no coincide.
    """
    params = {"country": (country or default_country()).upper()}
    if psu_type:
        params["psu_type"] = psu_type
    data = _api("/aspsps?" + urllib.parse.urlencode(params))
    out = [{"name": a.get("name"), "country": a.get("country"),
            "psu_types": a.get("psu_types") or [],
            "logo": a.get("logo"), "bic": a.get("bic"), "beta": bool(a.get("beta")),
            # Días máximos de consentimiento que admite ese banco: pedir más de
            # los que acepta es motivo de rechazo en `POST /auth`.
            "maximum_consent_validity": a.get("maximum_consent_validity")}
           for a in data.get("aspsps", []) if a.get("name")]
    out.sort(key=lambda a: (a["name"] or "").lower())
    return out


def configured_redirect_url(default=None):
    """URL de retorno: la registrada en el servidor o, si no, la de la propia web."""
    return os.environ.get("ENABLE_BANKING_REDIRECT_URL", "").strip() or (default or "")


def _consent_valid_until(days, maximum_seconds=None):
    """Fecha de caducidad del consentimiento, sin pasarse del máximo del banco.

    `maximum_seconds` es el `maximum_consent_validity` de `/aspsps`, que viene en
    SEGUNDOS. Es solo una ayuda para no pedir más de lo que ese banco acepta: si
    llega con una forma rara se ignora, en vez de tumbar toda la autorización.
    """
    try:
        days = max(1, int(days or CONSENT_DAYS))
    except (TypeError, ValueError):
        days = CONSENT_DAYS
    try:
        if maximum_seconds:
            days = min(days, max(1, int(maximum_seconds) // 86400))
    except (TypeError, ValueError):
        pass
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)


def start_auth(redirect_url=None, aspsp=None, country=None, days=CONSENT_DAYS,
               maximum_consent_validity=None, default_redirect_url=None):
    """Crea la autorización y devuelve la URL de SCA que debe abrir el usuario.

    La URL de retorno sale, por este orden, de: lo que pida quien llama,
    `ENABLE_BANKING_REDIRECT_URL`, y la ruta de retorno de la propia web
    (`default_redirect_url`). Sea cual sea, tiene que estar registrada en
    Enable Banking o el banco rechaza la autorización.
    """
    target_url = (str(redirect_url or "").strip()
                  or configured_redirect_url(default_redirect_url))
    if not target_url:
        raise NotConfigured("Falta ENABLE_BANKING_REDIRECT_URL (la URL de retorno "
                            "que registraste en Enable Banking).")
    target = default_aspsp()
    if aspsp:
        target["name"] = aspsp
    if country:
        target["country"] = country
    valid_until = _consent_valid_until(days, maximum_consent_validity)
    state = uuid.uuid4().hex
    data = _api("/auth", "POST", {
        "access": {"valid_until": valid_until.isoformat().replace("+00:00", "Z")},
        "aspsp": target,
        "state": state,
        "redirect_url": target_url,
        "psu_type": "personal",
    })
    url = data.get("url")
    if not url:
        raise EnableBankingError(f"Enable Banking no devolvió URL de autorización: {data}")
    db.set_setting(PENDING_SETTING, {"state": state, "aspsp": target,
                                     "redirect_url": target_url})
    return {"url": url, "state": state, "aspsp": target,
            "redirect_url": target_url,
            "valid_until": valid_until.date().isoformat()}


def complete_auth(code, state=None):
    """Cambia el `code` del retorno por una sesión y la guarda.

    Si el retorno trae `state`, se comprueba contra el que se generó al empezar:
    un `state` que no cuadra significa que ese retorno no es de la autorización
    que pediste, y no se cambia por una sesión.
    """
    if not str(code or "").strip():
        raise ValueError("Falta el 'code' que devuelve imagin al autorizar.")
    pending = db.get_setting(PENDING_SETTING, {}) or {}
    expected = str(pending.get("state") or "")
    if state and expected and str(state) != expected:
        raise ValueError("El 'state' del retorno no coincide con el de la autorización "
                         "que se inició aquí. Vuelve a pulsar «Autorizar».")
    data = _api("/sessions", "POST", {"code": str(code).strip()})
    session_id = data.get("session_id")
    accounts = data.get("accounts") or []
    if not session_id:
        raise EnableBankingError(f"Enable Banking no devolvió session_id: {data}")
    saved = {
        "session_id": session_id,
        "accounts": [{"uid": a.get("uid"),
                      "iban": (a.get("account_id") or {}).get("iban", ""),
                      "name": a.get("name") or a.get("product") or "",
                      "currency": a.get("currency") or "EUR"}
                     for a in accounts if a.get("uid")],
        "aspsp": data.get("aspsp") or default_aspsp(),
        "access_valid_until": (data.get("access") or {}).get("valid_until"),
        "created": datetime.date.today().isoformat(),
    }
    db.set_setting(SESSION_SETTING, saved)
    return saved


def session():
    """Sesión guardada, o NotConfigured si todavía no se ha autorizado el banco."""
    saved = db.get_setting(SESSION_SETTING, {}) or {}
    if not saved.get("session_id") or not saved.get("accounts"):
        raise NotConfigured("imagin no está autorizado todavía: conéctalo una vez "
                            "desde la web (autorización PSD2 en la app del banco).")
    return saved


def is_connected():
    try:
        session()
        return True
    except NotConfigured:
        return False


def disconnect():
    db.set_setting(SESSION_SETTING, {})


# ---------------------------------------------------------------------------
# Saldos y movimientos
# ---------------------------------------------------------------------------
def _amount(node):
    try:
        return float((node or {}).get("amount"))
    except (TypeError, ValueError):
        return None


def account_balance(uid):
    """Saldo disponible de una cuenta (ITAV si está; si no, el contable CLBD)."""
    data = _api(f"/accounts/{uid}/balances")
    balances = data.get("balances") or []
    by_type = {}
    for b in balances:
        value = _amount(b.get("balance_amount"))
        if value is not None:
            by_type[(b.get("balance_type") or "").upper()] = value
    for kind in ("ITAV", "XPCD", "CLBD", "OTHR"):
        if kind in by_type:
            return by_type[kind]
    return next(iter(by_type.values()), None)


def account_transactions(uid, date_from=None, max_pages=10):
    """Movimientos de una cuenta desde `date_from` (ISO), paginando de verdad."""
    date_from = date_from or (datetime.date.today()
                              - datetime.timedelta(days=HISTORY_DAYS)).isoformat()
    out, continuation, pages = [], None, 0
    while pages < max_pages:
        path = f"/accounts/{uid}/transactions?date_from={date_from}"
        if continuation:
            path += f"&continuation_key={continuation}"
        data = _api(path)
        out.extend(data.get("transactions") or [])
        continuation = data.get("continuation_key")
        pages += 1
        if not continuation:
            break
    return out


def _concept(tx):
    """Concepto legible: la información de remesa y, si no, la contraparte."""
    remittance = tx.get("remittance_information")
    if isinstance(remittance, list):
        text = " ".join(str(x) for x in remittance if x).strip()
    else:
        text = str(remittance or "").strip()
    if text:
        return text
    for side in ("creditor", "debtor"):
        name = (tx.get(side) or {}).get("name")
        if name:
            return str(name).strip()
    return tx.get("bank_transaction_code", {}).get("description") or "Movimiento"


def _to_ddmmyyyy(iso):
    if not iso:
        return ""
    try:
        return datetime.date.fromisoformat(str(iso)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return ""


def _normalize(tx):
    """Movimiento de Enable Banking -> formato de `bank.analyze_raw`."""
    amount = _amount(tx.get("transaction_amount"))
    if amount is None:
        return None
    if (tx.get("credit_debit_indicator") or "").upper() == "DBIT":
        amount = -abs(amount)
    date = _to_ddmmyyyy(tx.get("booking_date") or tx.get("value_date")
                        or tx.get("transaction_date"))
    if not date:
        return None
    return {"concept": _concept(tx), "date": date, "amount": amount,
            "balance": _amount(tx.get("balance_after_transaction")) or 0.0}


def analyze(date_from=None):
    """Saldo + movimientos reales de imagin, clasificados como el extracto PDF."""
    saved = session()
    raw, balance = [], 0.0
    for account in saved["accounts"]:
        uid = account["uid"]
        account_bal = account_balance(uid)
        if account_bal is not None:
            balance += account_bal
        for tx in account_transactions(uid, date_from):
            row = _normalize(tx)
            if row:
                raw.append(row)
    result = bank.analyze_raw(raw, round(balance, 2))
    result["source"] = SOURCE
    result["accounts"] = saved["accounts"]
    result["access_valid_until"] = saved.get("access_valid_until")
    # Sin movimientos en la ventana, `bank.analyze_raw` no sabe de qué mes es el
    # saldo: es el de hoy, así que lo decimos explícitamente.
    if not result.get("month"):
        result["month"] = datetime.date.today().strftime("%Y-%m")
        result["aggregates"]["month"] = result["month"]
    return result
