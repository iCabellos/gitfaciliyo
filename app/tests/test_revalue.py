"""Revalorización en vivo de skins/cartas: guarda el snapshot del mes actual."""

import datetime

import pytest

from sources import db, revalue

MONTH = datetime.date.today().strftime("%Y-%m")


@pytest.fixture(autouse=True)
def _aislado(monkeypatch):
    """Sin STEAM_ID64 del entorno y con los snapshots limpios en cada test."""
    monkeypatch.delenv("STEAM_ID64", raising=False)
    db.reset_snapshots()
    yield
    db.reset_snapshots()


def _settings(monkeypatch, values):
    monkeypatch.setattr(revalue.db, "get_setting",
                        lambda key, default=None: values.get(key, default))


def test_sin_configurar_no_registra_nada(monkeypatch):
    _settings(monkeypatch, {})
    results, errors = revalue.refresh_live()
    assert results == {}
    assert errors == {}
    assert db.get_snapshots() == {}


def test_refresh_skins_guarda_snapshot(monkeypatch):
    _settings(monkeypatch, {"steam_id64": "76561198000000000"})
    monkeypatch.setattr(revalue.steam, "analyze", lambda sid: {
        "category": "Skins CS:GO", "total": 123.45, "warnings": []})
    results, errors = revalue.refresh_live()
    assert results["Skins CS:GO"] == 123.45
    assert errors == {}
    assert db.get_snapshots()[MONTH]["Skins CS:GO"] == 123.45


def test_refresh_skins_descarta_total_parcial_por_429(monkeypatch):
    _settings(monkeypatch, {"steam_id64": "76561198000000000"})
    monkeypatch.setattr(revalue.steam, "analyze", lambda sid: {
        "category": "Skins CS:GO", "total": 10.0,
        "warnings": ["Steam Market limitó las peticiones (429); precios parciales."]})
    results, errors = revalue.refresh_live()
    assert "Skins CS:GO" not in results
    assert "429" in errors["Skins CS:GO"]
    assert db.get_snapshots() == {}


def test_refresh_cards_guarda_snapshot(monkeypatch):
    _settings(monkeypatch, {"magic_cards": {"reference": "", "decklist": "1 Sol Ring"}})
    seen = {}
    monkeypatch.setattr(revalue.moxfield, "analyze",
                        lambda reference=None, decklist=None:
                        seen.update(decklist=decklist)
                        or {"category": "Cartas Magic", "total": 9.99})
    results, errors = revalue.refresh_live()
    assert results["Cartas Magic"] == 9.99
    assert errors == {}
    assert seen["decklist"] == "1 Sol Ring"
    assert db.get_snapshots()[MONTH]["Cartas Magic"] == 9.99


def test_fallo_de_una_fuente_no_frena_a_la_otra(monkeypatch):
    _settings(monkeypatch, {"steam_id64": "76561198000000000",
                            "magic_cards": {"reference": "", "decklist": "1 Sol Ring"}})

    def steam_roto(sid):
        raise RuntimeError("Steam no deja leer el inventario (parece privado).")

    monkeypatch.setattr(revalue.steam, "analyze", steam_roto)
    monkeypatch.setattr(revalue.moxfield, "analyze",
                        lambda reference=None, decklist=None:
                        {"category": "Cartas Magic", "total": 5.0})
    results, errors = revalue.refresh_live()
    assert results == {"Cartas Magic": 5.0}
    assert "privado" in errors["Skins CS:GO"]
