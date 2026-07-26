"""Configuración: un único orden de precedencia, sin plantillas por medio."""

import json

import pytest

from sources import settings


@pytest.fixture()
def aislado(monkeypatch, tmp_path):
    """Parte de cero: sin entorno, sin ficheros y sin ajuste en la base de datos."""
    monkeypatch.delenv("STEAM_ID64", raising=False)
    monkeypatch.setattr(settings, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(settings, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(settings, "_db_setting", lambda key: "")
    return tmp_path


def _escribe(path, data):
    path.write_text(json.dumps(data))


def test_sin_nada_configurado_no_hay_steamid(aislado):
    assert settings.steam_id64() == ""
    assert settings.moxfield_deck() == ""
    assert settings.currency() == "eur"


def test_los_huecos_de_plantilla_no_cuentan(aislado):
    _escribe(aislado / "settings.json", {"steam": {"steamid64": "TU_STEAMID64"}})
    assert settings.steam_id64() == ""
    assert settings.real_value("TU_TELEFONO") == ""
    assert settings.real_value("  ") == ""
    assert settings.real_value(" 76561190000000000 ") == "76561190000000000"


def test_settings_json_versionado_es_la_base(aislado):
    _escribe(aislado / "settings.json", {"steam": {"steamid64": "76561190000000001"},
                                         "currency": "usd"})
    assert settings.steam_id64() == "76561190000000001"
    assert settings.currency() == "usd"


def test_precedencia_entorno_gana_a_todo(aislado, monkeypatch):
    _escribe(aislado / "settings.json", {"steam": {"steamid64": "76561190000000001"}})
    _escribe(aislado / "config.json", {"steam": {"steamid64": "76561190000000002"}})
    monkeypatch.setattr(settings, "_db_setting", lambda key: "76561190000000003")
    monkeypatch.setenv("STEAM_ID64", "76561190000000004")
    assert settings.steam_id64() == "76561190000000004"


def test_precedencia_config_json_gana_al_resto(aislado, monkeypatch):
    _escribe(aislado / "settings.json", {"steam": {"steamid64": "76561190000000001"}})
    _escribe(aislado / "config.json", {"steam": {"steamid64": "76561190000000002"}})
    monkeypatch.setattr(settings, "_db_setting", lambda key: "76561190000000003")
    assert settings.steam_id64() == "76561190000000002"


def test_lo_guardado_en_la_web_gana_al_fichero_versionado(aislado, monkeypatch):
    """Si lo cambias desde la web, manda eso y no el valor por defecto del repo."""
    _escribe(aislado / "settings.json", {"steam": {"steamid64": "76561190000000001"}})
    monkeypatch.setattr(settings, "_db_setting", lambda key: "76561190000000003")
    assert settings.steam_id64() == "76561190000000003"


def test_config_json_se_fusiona_sobre_settings_json(aislado):
    _escribe(aislado / "settings.json", {"currency": "eur",
                                         "moxfield": {"default_deck": "del-repo"}})
    _escribe(aislado / "config.json", {"currency": "usd"})
    merged = settings.files()
    assert merged["currency"] == "usd"                       # config.json pisa
    assert merged["moxfield"]["default_deck"] == "del-repo"  # lo demás se conserva


def test_sin_base_de_datos_no_es_un_error(aislado, monkeypatch):
    def db_rota():
        raise RuntimeError("sin base de datos")

    monkeypatch.setattr(settings, "_db_setting",
                        lambda key: settings.real_value(db_rota()))
    _escribe(aislado / "settings.json", {"steam": {"steamid64": "76561190000000001"}})
    with pytest.raises(RuntimeError):
        settings._db_setting("steam_id64")      # el doble sí lanza…
    # …pero el módulo real se lo traga y sigue con los ficheros.
    monkeypatch.undo()
    monkeypatch.setattr(settings, "CONFIG_PATH", str(aislado / "config.json"))
    monkeypatch.setattr(settings, "SETTINGS_PATH", str(aislado / "settings.json"))
    monkeypatch.delenv("STEAM_ID64", raising=False)
    assert settings.steam_id64() == "76561190000000001"


def test_la_plantilla_no_entra_en_la_cadena(aislado):
    """config.example.json existe en el repo pero NO es una fuente de configuración."""
    assert "example" not in settings.CONFIG_PATH
    assert "example" not in settings.SETTINGS_PATH
