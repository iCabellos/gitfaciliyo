"""Menú de configuración: estado real de cada fuente, sin filtrar secretos."""

import json

import pytest

from sources import db, setup, trade_republic_live, enablebanking


SECRETOS = {
    "ENABLE_BANKING_APP_ID": "app-secreta-123",
    "ENABLE_BANKING_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----MUY-SECRETO-----",
    "ENABLE_BANKING_REDIRECT_URL": "https://ejemplo.test/volver",
    "TR_PHONE": "+34600111222",
    "TR_PIN": "9876",
    "CALLMEBOT_APIKEY": "clave-callmebot",
    "CALLMEBOT_PHONE": "34600111222",
    "SUMMARY_TOKEN": "token-del-resumen",
}


@pytest.fixture(autouse=True)
def _sin_entorno(monkeypatch):
    for nombre in SECRETOS:
        monkeypatch.delenv(nombre, raising=False)
    db.set_setting(enablebanking.SESSION_SETTING, {})
    db.set_setting(trade_republic_live.DEVICE_KEY_SETTING, {})
    db.set_setting("magic_cards", {})
    db.set_setting("steam_id64", "")
    yield
    db.set_setting(enablebanking.SESSION_SETTING, {})
    db.set_setting(trade_republic_live.DEVICE_KEY_SETTING, {})
    db.set_setting("magic_cards", {})
    db.set_setting("steam_id64", "")


def _fuente(estado, ident):
    return next(s for s in estado["sources"] if s["id"] == ident)


def test_las_cuatro_fuentes_estan_y_en_orden():
    ids = [s["id"] for s in setup.status()["sources"]]
    assert ids == ["imagin", "trade_republic", "steam", "magic"]


def test_sin_nada_configurado_todo_sale_pendiente():
    estado = setup.status()
    assert set(estado["pending"]) == {"imagin", "trade_republic", "steam", "magic"}
    for fuente in estado["sources"]:
        assert fuente["connected"] is False
        assert fuente["summary"]
        assert fuente["steps"] and all(not p["done"] for p in fuente["steps"])


def test_nunca_se_filtra_el_valor_de_un_secreto(monkeypatch):
    """Lo que se publica es si la variable está puesta, jamás su contenido."""
    for nombre, valor in SECRETOS.items():
        monkeypatch.setenv(nombre, valor)
    db.set_setting(trade_republic_live.DEVICE_KEY_SETTING,
                   {"phone": "+34600111222", "pem": "-----BEGIN PRIVATE KEY-----xyz"})
    volcado = json.dumps(setup.status(), ensure_ascii=False)
    for valor in SECRETOS.values():
        assert valor not in volcado, f"se ha filtrado el valor de un secreto: {valor}"
    assert "BEGIN PRIVATE KEY" not in volcado


def test_imagin_necesita_el_servidor_antes_de_poder_empezar(monkeypatch):
    estado = _fuente(setup.status(), "imagin")
    assert estado["server_ready"] is False
    assert set(estado["missing_env"]) == {"ENABLE_BANKING_APP_ID",
                                          "ENABLE_BANKING_REDIRECT_URL",
                                          "ENABLE_BANKING_PRIVATE_KEY"}
    # Con las credenciales puestas ya se puede empezar, aunque falte autorizar.
    monkeypatch.setenv("ENABLE_BANKING_APP_ID", SECRETOS["ENABLE_BANKING_APP_ID"])
    monkeypatch.setenv("ENABLE_BANKING_PRIVATE_KEY", SECRETOS["ENABLE_BANKING_PRIVATE_KEY"])
    monkeypatch.setenv("ENABLE_BANKING_REDIRECT_URL", SECRETOS["ENABLE_BANKING_REDIRECT_URL"])
    estado = _fuente(setup.status(), "imagin")
    assert estado["server_ready"] is True and estado["missing_env"] == []
    assert estado["connected"] is False
    assert "falta autorizar" in estado["summary"]


def test_imagin_vale_tambien_con_la_clave_en_fichero(monkeypatch):
    monkeypatch.setenv("ENABLE_BANKING_APP_ID", "x")
    monkeypatch.setenv("ENABLE_BANKING_REDIRECT_URL", "https://x.test/")
    monkeypatch.setenv("ENABLE_BANKING_KEY_PATH", "/data/clave.pem")
    assert _fuente(setup.status(), "imagin")["missing_env"] == []


def test_imagin_conectado_muestra_las_cuentas_sin_el_iban_entero(monkeypatch):
    monkeypatch.setenv("ENABLE_BANKING_APP_ID", "x")
    monkeypatch.setenv("ENABLE_BANKING_PRIVATE_KEY", "x")
    monkeypatch.setenv("ENABLE_BANKING_REDIRECT_URL", "https://x.test/")
    db.set_setting(enablebanking.SESSION_SETTING, {
        "session_id": "s1", "access_valid_until": "2026-10-24T00:00:00Z",
        "accounts": [{"uid": "a1", "iban": "ES9121000418450200051332", "name": "imagin"}]})
    estado = _fuente(setup.status(), "imagin")
    assert estado["connected"] is True
    assert estado["detail"]["accounts"] == [{"name": "imagin", "iban_end": "1332"}]
    assert "ES9121000418450200051332" not in json.dumps(estado)


def test_trade_republic_se_puede_emparejar_sin_variables_de_entorno():
    """No hace falta nada del servidor para emparejar: se hace desde la web.

    Las variables solo hacen falta para que el resumen SEMANAL entre solo, y eso
    es `auto_ready`, no `server_ready`.
    """
    estado = _fuente(setup.status(), "trade_republic")
    assert estado["server_ready"] is True
    assert estado["auto_ready"] is False
    assert set(estado["missing_env"]) == {"TR_PHONE", "TR_PIN"}


def test_trade_republic_emparejado(monkeypatch):
    monkeypatch.setenv("TR_PHONE", SECRETOS["TR_PHONE"])
    monkeypatch.setenv("TR_PIN", SECRETOS["TR_PIN"])
    db.set_setting(trade_republic_live.DEVICE_KEY_SETTING,
                   {"phone": "+34600111222", "pem": "clave", "paired_at": "2026-07-26T20:00:00"})
    estado = _fuente(setup.status(), "trade_republic")
    assert estado["connected"] is True and estado["auto_ready"] is True
    assert estado["detail"]["phone_end"] == "222"      # solo los últimos dígitos


def test_steam_se_marca_conectado_con_el_id_guardado(monkeypatch):
    monkeypatch.setattr(setup.settings, "steam_id64", lambda: "76561198110817711")
    estado = _fuente(setup.status(), "steam")
    assert estado["connected"] is True
    assert estado["detail"]["steamid"] == "76561198110817711"   # público, se muestra
    assert all(p["done"] for p in estado["steps"])


def test_magic_cuenta_las_lineas_guardadas():
    db.set_setting("magic_cards", {"reference": "", "decklist": "1 Sol Ring\n2 Counterspell\n"})
    estado = _fuente(setup.status(), "magic")
    assert estado["connected"] is True
    assert estado["detail"]["lines"] == 2
    assert "2 líneas" in estado["summary"]


def test_entorno_avisa_de_lo_que_impide_el_resumen_semanal(monkeypatch):
    env = setup.environment()
    assert env["db"] == "sqlite" and env["db_shared"] is False
    assert env["whatsapp"] is False and env["summary_token"] is False
    monkeypatch.setenv("CALLMEBOT_APIKEY", SECRETOS["CALLMEBOT_APIKEY"])
    monkeypatch.setenv("CALLMEBOT_PHONE", SECRETOS["CALLMEBOT_PHONE"])
    monkeypatch.setenv("SUMMARY_TOKEN", SECRETOS["SUMMARY_TOKEN"])
    env = setup.environment()
    assert env["whatsapp"] is True and env["summary_token"] is True
