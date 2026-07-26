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


def test_sin_configurar_no_registra_nada_pero_lo_dice(monkeypatch):
    _settings(monkeypatch, {})
    results, errors, skipped = revalue.refresh_live()
    assert results == {}
    assert errors == {}
    assert db.get_snapshots() == {}
    # Lo no conectado no se calla: se devuelve para poder avisarlo en el mensaje.
    assert set(skipped) == {"Skins CS:GO", "Cartas Magic",
                            "Liquidez (banco)", "Acciones / ETFs"}


def test_acciones_en_vivo_guarda_snapshot_y_posiciones(monkeypatch):
    _settings(monkeypatch, {})
    monkeypatch.setattr(revalue.trade_republic_live, "analyze", lambda: {
        "category": "Acciones / ETFs", "total": 1500.0, "month": MONTH,
        "positions": [{"name": "Apple", "quantity": 3.0, "unit_value": 200.0,
                       "value": 600.0, "currency": "EUR", "extra": {"isin": "US0378331005"}},
                      {"name": "Vanguard FTSE All-World", "quantity": 7.5,
                       "unit_value": 120.0, "value": 900.0, "currency": "EUR",
                       "extra": {"isin": "IE00BK5BQT80"}}]})
    results, errors, skipped = revalue.refresh_live()
    assert results["Acciones / ETFs"] == 1500.0
    assert "Acciones / ETFs" not in skipped
    assert db.get_snapshots()[MONTH]["Acciones / ETFs"] == 1500.0
    rows = db.get_holdings(month=MONTH)
    assert {(r["name"], r["quantity"]) for r in rows} == {
        ("Apple", 3.0), ("Vanguard FTSE All-World", 7.5)}


def test_banco_en_vivo_guarda_liquidez_y_flujos(monkeypatch):
    _settings(monkeypatch, {})
    monkeypatch.setattr(revalue.enablebanking, "analyze", lambda: {
        "available_balance": 6200.78, "month": MONTH,
        "aggregates": {"month": MONTH, "liquidez": 6200.78,
                       "gastos": 2146.52, "ganancias": 2936.43, "inversion": 0}})
    results, errors, skipped = revalue.refresh_live()
    assert results["Liquidez (banco)"] == 6200.78
    snap = db.get_snapshots()[MONTH]
    assert snap["Liquidez (banco)"] == 6200.78
    assert snap["_flow:gastos"] == 2146.52
    assert snap["_flow:ganancias"] == 2936.43


def test_refresh_skins_guarda_snapshot(monkeypatch):
    _settings(monkeypatch, {"steam_id64": "76561198000000000"})
    monkeypatch.setattr(revalue.steam, "analyze", lambda sid: {
        "category": "Skins CS:GO", "total": 123.45, "warnings": []})
    results, errors, skipped = revalue.refresh_live()
    assert results["Skins CS:GO"] == 123.45
    assert errors == {}
    assert db.get_snapshots()[MONTH]["Skins CS:GO"] == 123.45


def test_refresh_skins_descarta_total_parcial_por_429(monkeypatch):
    _settings(monkeypatch, {"steam_id64": "76561198000000000"})
    monkeypatch.setattr(revalue.steam, "analyze", lambda sid: {
        "category": "Skins CS:GO", "total": 10.0,
        "warnings": ["Steam Market limitó las peticiones (429); precios parciales."]})
    results, errors, skipped = revalue.refresh_live()
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
    results, errors, skipped = revalue.refresh_live()
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
    results, errors, skipped = revalue.refresh_live()
    assert results == {"Cartas Magic": 5.0}
    assert "privado" in errors["Skins CS:GO"]
