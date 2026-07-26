"""
Configuración del panel: UN solo sitio que decide de dónde sale cada ajuste.

Antes esta lógica estaba repetida en tres sitios (`app.load_config`,
`revalue._steamid` y `track_prices._steamid`) con reglas distintas, así que la
web, el resumen semanal y el cron podían no coincidir en algo tan básico como
qué SteamID es el tuyo. Ahora hay un único orden de precedencia, de lo más
específico a lo más general:

  1. Variable de entorno   -> lo que define el servidor o el cron (STEAM_ID64).
  2. `config.json`         -> configuración local, en .gitignore (desarrollo).
  3. Ajuste en la base de datos -> lo último que guardaste desde la web.
  4. `settings.json`       -> TU configuración versionada, la que se despliega.

`config.example.json` NO entra en esa cadena: es una plantilla. Caer en él fue
lo que hizo que la web propusiera un SteamID que no venía de ninguna
configuración real.

Nada de esto es secreto: un SteamID64 es público (sale en la URL de tu perfil) y
por eso `settings.json` puede estar versionado. Las credenciales de verdad
(tokens, PIN, claves) siguen yendo SOLO por variables de entorno.
"""

import json
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(_HERE, "config.json")        # local, .gitignore
SETTINGS_PATH = os.path.join(_HERE, "settings.json")    # versionado

# Marca de plantilla: cualquier valor que empiece así es un hueco por rellenar,
# no un dato. Vale para TU_STEAMID64, TU_TELEFONO, etc.
PLACEHOLDER = "TU_"


def _read_json(path):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def real_value(value):
    """Descarta vacíos y huecos de plantilla; devuelve '' si no hay dato real."""
    text = str(value or "").strip()
    return "" if not text or text.startswith(PLACEHOLDER) else text


def files():
    """Configuración de ficheros: `config.json` pisa a `settings.json`."""
    merged = dict(_read_json(SETTINGS_PATH))
    for key, value in _read_json(CONFIG_PATH).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _db_setting(key):
    """Ajuste guardado desde la web. Si no hay base de datos, no es un error."""
    try:
        from . import db
        return real_value(db.get_setting(key, "") or "")
    except Exception:  # noqa: BLE001 - sin DB simplemente no hay ajuste guardado
        return ""


def steam_id64():
    """Tu SteamID64 real, o '' si no está configurado en ninguna parte."""
    cfg = files()
    for candidate in (os.environ.get("STEAM_ID64", ""),
                      _read_json(CONFIG_PATH).get("steam", {}).get("steamid64", ""),
                      _db_setting("steam_id64"),
                      (cfg.get("steam") or {}).get("steamid64", "")):
        value = real_value(candidate)
        if value:
            return value
    return ""


def moxfield_deck():
    return real_value((files().get("moxfield") or {}).get("default_deck", ""))


def currency():
    return real_value(files().get("currency")) or "eur"
