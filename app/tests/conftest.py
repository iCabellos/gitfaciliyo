"""Configuración común de los tests.

Antes de importar nada de la app, apunta la base de datos a un SQLite temporal
(PATRIMONIO_DATA_DIR) y desactiva DATABASE_URL, para no tocar producción ni
depender de PostgreSQL. También deja el directorio de la app en sys.path.

Y, sobre todo, AÍSLA LA CONFIGURACIÓN: `settings.json` está versionado con el
SteamID real, así que sin aislarlo los tests que simulan «nada configurado»
acabarían llamando a Steam de verdad. Aquí se apunta a ficheros que no existen;
el test que quiera configuración se la pone él.
"""

import os
import sys
import tempfile

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

# Base de datos aislada en un temporal (SQLite local), sin SSL ni Postgres.
os.environ.pop("DATABASE_URL", None)
_TMP = tempfile.mkdtemp(prefix="patrimonio-tests-")
os.environ["PATRIMONIO_DATA_DIR"] = _TMP
# Sin token: que /api/monthly-summary no exija autorización en los tests.
os.environ.pop("SUMMARY_TOKEN", None)
# Sin configuración heredada del entorno del desarrollador.
os.environ.pop("STEAM_ID64", None)

import pytest  # noqa: E402

from sources import db, settings  # noqa: E402

# Configuración de ficheros aislada: por defecto, nada configurado.
settings.CONFIG_PATH = os.path.join(_TMP, "config.json")
settings.SETTINGS_PATH = os.path.join(_TMP, "settings.json")


@pytest.fixture()
def client():
    """Cliente de pruebas de Flask con la base de datos limpia."""
    import app as app_module
    db.reset_snapshots()
    db.reset_holdings()
    db.reset_prices()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c
    db.reset_snapshots()
    db.reset_holdings()
    db.reset_prices()
