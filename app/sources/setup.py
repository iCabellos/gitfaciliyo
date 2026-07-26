"""
Estado de configuración de cada fuente, para el menú de Configuración de la web.

Responde a una sola pregunta por fuente: **¿qué falta para que esto se
actualice solo?** Y la responde mirando el estado REAL (variables del servidor
presentes, autorización hecha, ajuste guardado), no una lista fija de pasos.

Regla dura: aquí NUNCA sale el valor de un secreto. De las variables de entorno
solo se dice si están puestas o no; de la clave privada, del PIN o de los
tokens, jamás su contenido. Lo público (SteamID64, IBAN acabado en …) sí, porque
es lo que necesitas ver para comprobar que has configurado lo tuyo.
"""

import os

from . import settings

# Variables que el servidor necesita para cada fuente. Solo se comprueba su
# PRESENCIA; el valor no sale de aquí.
IMAGIN_ENV = ("ENABLE_BANKING_APP_ID", "ENABLE_BANKING_REDIRECT_URL")
IMAGIN_KEY_ENV = ("ENABLE_BANKING_PRIVATE_KEY", "ENABLE_BANKING_KEY_PATH")
TR_ENV = ("TR_PHONE", "TR_PIN")


def _is_set(name):
    return bool(os.environ.get(name, "").strip())


def _missing(names):
    return [n for n in names if not _is_set(n)]


def _steam():
    steamid = settings.steam_id64()
    return {
        "id": "steam",
        "name": "Skins de CS:GO (Steam)",
        "icon": "🔫",
        "server_ready": True,          # no necesita nada del servidor
        "auto_ready": True,
        "missing_env": [],
        "connected": bool(steamid),
        "detail": {"steamid": steamid},
        "summary": (f"Siguiendo el inventario de {steamid}." if steamid
                    else "Falta tu SteamID64."),
        "steps": [
            {"text": "En Steam: Editar perfil → Privacidad → «Detalles del juego» = "
                     "Público, y desmarca «Mantener mi inventario siempre privado».",
             "done": bool(steamid)},
            {"text": "Pega aquí tu SteamID64 (el número de la URL de tu perfil) y "
                     "guarda.", "done": bool(steamid)},
            {"text": "Comprueba: debe leer tu inventario y valorarlo con el Steam "
                     "Market.", "done": bool(steamid)},
        ],
    }


def _magic():
    try:
        from . import db
        saved = db.get_setting("magic_cards", {}) or {}
    except Exception:  # noqa: BLE001
        saved = {}
    decklist = (saved.get("decklist") or "").strip()
    reference = (saved.get("reference") or "").strip()
    lineas = len([l for l in decklist.splitlines() if l.strip()])
    listo = bool(decklist or reference)
    return {
        "id": "magic",
        "name": "Cartas Magic (Scryfall)",
        "icon": "🃏",
        "server_ready": True,
        "auto_ready": True,
        "missing_env": [],
        "connected": listo,
        "detail": {"lines": lineas, "reference": reference},
        "summary": (f"{lineas} líneas guardadas." if lineas else
                    f"Mazo de Moxfield: {reference}" if reference else
                    "Todavía no hay ninguna carta guardada."),
        "steps": [
            {"text": "Abre la pestaña «Cartas Magic».", "done": listo},
            {"text": "Añade cartas una a una, o pega una decklist exportada "
                     "(también vale la URL de un mazo de Moxfield).", "done": listo},
            {"text": "La lista se guarda sola: a partir de ahí el seguimiento diario "
                     "pide sus precios a Scryfall.", "done": listo},
        ],
    }


def _imagin():
    try:
        from . import enablebanking, db
        saved = db.get_setting(enablebanking.SESSION_SETTING, {}) or {}
        aspsp = enablebanking.default_aspsp()
    except Exception:  # noqa: BLE001
        saved, aspsp = {}, {"name": "imagin", "country": "ES"}
    falta = _missing(IMAGIN_ENV)
    if not any(_is_set(n) for n in IMAGIN_KEY_ENV):
        falta.append(IMAGIN_KEY_ENV[0])
    listo_servidor = not falta
    conectado = bool(saved.get("session_id") and saved.get("accounts"))
    cuentas = [{"name": a.get("name") or "cuenta",
                "iban_end": (a.get("iban") or "")[-4:]}
               for a in saved.get("accounts", [])]
    return {
        "id": "imagin",
        "name": f"Banco · {aspsp.get('name', 'imagin')} (PSD2)",
        "icon": "🏦",
        "server_ready": listo_servidor,
        "auto_ready": listo_servidor,
        "missing_env": falta,
        "connected": conectado,
        "detail": {"accounts": cuentas,
                   "valid_until": saved.get("access_valid_until")},
        "summary": (f"{len(cuentas)} cuenta(s) autorizadas." if conectado else
                    "Faltan credenciales en el servidor." if not listo_servidor else
                    "Credenciales listas: falta autorizar en la app del banco."),
        "steps": [
            {"text": "Regístrate en enablebanking.com y crea una aplicación en modo "
                     "«restricted production» (gratis para leer tus propias cuentas).",
             "done": listo_servidor},
            {"text": "En el servidor (Render → Environment) define "
                     "ENABLE_BANKING_APP_ID, la clave privada "
                     "(ENABLE_BANKING_PRIVATE_KEY o ENABLE_BANKING_KEY_PATH) y "
                     "ENABLE_BANKING_REDIRECT_URL.", "done": listo_servidor},
            {"text": "Pulsa «Autorizar» y confirma en la app del banco (DNI + "
                     "PIN/biometría).", "done": conectado},
            {"text": "Pega aquí el «code» de la URL de retorno y conecta.",
             "done": conectado},
        ],
        "note": ("El consentimiento PSD2 caduca a los ~90 días. Cuando pase, el "
                 "resumen semanal te avisará y bastará con repetir los pasos 3 y 4."),
    }


def _trade_republic():
    try:
        from . import trade_republic_live, db
        saved = db.get_setting(trade_republic_live.DEVICE_KEY_SETTING, {}) or {}
    except Exception:  # noqa: BLE001
        saved = {}
    emparejado = bool(saved.get("pem"))
    falta = _missing(TR_ENV)
    return {
        "id": "trade_republic",
        "name": "Trade Republic (acciones y ETFs)",
        "icon": "📈",
        # Aquí no falta nada del servidor para EMPAREJAR: se hace escribiendo
        # teléfono y PIN en esta misma pantalla. Las variables solo hacen falta
        # para que el resumen SEMANAL pueda entrar solo, y eso va en `auto_ready`.
        "server_ready": True,
        "auto_ready": not falta,
        "missing_env": falta,
        "connected": emparejado,
        "detail": {"phone_end": (saved.get("phone") or "")[-3:],
                   "paired_at": saved.get("paired_at")},
        "summary": ("Dispositivo emparejado." if emparejado
                    else "Falta emparejar el dispositivo."),
        "steps": [
            {"text": "Escribe tu teléfono (+34…) y tu PIN de Trade Republic y pulsa "
                     "«Pedir código».", "done": emparejado},
            {"text": "Te llega un código de 4 dígitos: escríbelo y pulsa «Emparejar». "
                     "Esto se hace UNA sola vez.", "done": emparejado},
            {"text": "Para que el resumen semanal entre solo, define TR_PHONE y TR_PIN "
                     "en el servidor (Render → Environment).", "done": not falta},
        ],
        "note": ("Es la API no oficial de la propia app de Trade Republic: puede "
                 "romperse si TR cambia el protocolo. Cuando pase, lo verás en el "
                 "WhatsApp semanal y siempre queda subir el PDF/CSV a mano."),
    }


def environment():
    """Estado de lo que hace que el resumen semanal llegue (y se conserve)."""
    try:
        from . import db
        backend = db.backend()
    except Exception as exc:  # noqa: BLE001
        backend = f"no disponible ({exc})"
    whatsapp = (_is_set("CALLMEBOT_APIKEY") and _is_set("CALLMEBOT_PHONE")) or all(
        _is_set(n) for n in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                             "TWILIO_WHATSAPP_FROM", "ALERT_WHATSAPP_TO"))
    return {
        "db": backend,
        "db_shared": backend == "postgresql",
        "whatsapp": whatsapp,
        "summary_token": _is_set("SUMMARY_TOKEN"),
    }


def status():
    """Estado completo de configuración: una entrada por fuente + el entorno."""
    fuentes = [_imagin(), _trade_republic(), _steam(), _magic()]
    return {
        "sources": fuentes,
        "environment": environment(),
        "pending": [s["id"] for s in fuentes if not (s["connected"] and s["server_ready"])],
    }
