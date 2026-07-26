"""Seguimiento diario de precios: la watchlist sale de lo que REALMENTE tienes.

Verifica que no se siguen skins/cartas de ejemplo: solo el inventario real de
Steam y la lista de Magic guardada (o un override explícito).
"""

import json

from jobs import track_prices as tp


def _inventory(names_marketable, names_unmarketable=()):
    """Simula steam.fetch_inventory + _group_items sin tocar la red."""
    items = {n: {"marketable": True, "count": 1} for n in names_marketable}
    items.update({n: {"marketable": False, "count": 1} for n in names_unmarketable})
    return items


def test_skins_from_inventory_solo_vendibles(monkeypatch):
    monkeypatch.setattr(tp.settings, "steam_id64", lambda: "76561190000000000")
    monkeypatch.setattr(tp.steam, "fetch_inventory", lambda sid, **k: {"raw": sid})
    monkeypatch.setattr(tp.steam, "_group_items",
                        lambda inv: _inventory(["AK-47 | Redline (Field-Tested)"],
                                               ["Sticker | no vendible"]))
    skins = tp.skins_from_inventory()
    assert skins == ["AK-47 | Redline (Field-Tested)"]      # se ignora lo no vendible


def test_skins_from_inventory_sin_steamid(monkeypatch):
    """Sin SteamID configurado no se sigue nada (y no se toca la red)."""
    monkeypatch.setattr(tp.settings, "steam_id64", lambda: "")
    assert tp.skins_from_inventory() == []


def test_cards_from_saved_parsea_decklist(monkeypatch):
    from sources import db
    monkeypatch.setattr(db, "get_setting",
                        lambda k, d=None: {"reference": "", "decklist": "1 Sol Ring\n2 Counterspell"})
    cards = tp.cards_from_saved()
    names = [c["name"] for c in cards]
    assert names == ["Sol Ring", "Counterspell"]


def test_load_watchlist_deriva_de_tenencias(monkeypatch):
    monkeypatch.setattr(tp, "_read", lambda p, d: d)         # sin ficheros de override
    monkeypatch.setattr(tp, "skins_from_inventory", lambda: ["★ Bayonet | Fade (Factory New)"])
    monkeypatch.setattr(tp, "cards_from_saved", lambda: [{"name": "Sol Ring"}])
    wl = tp.load_watchlist()
    assert wl["skins"] == ["★ Bayonet | Fade (Factory New)"]
    assert wl["cards"] == [{"name": "Sol Ring"}]


def test_load_watchlist_respeta_override_explicito(monkeypatch, tmp_path):
    override = {"cards": ["Rhystic Study"], "skins": ["★ Karambit | Doppler (Factory New)"]}
    wl_file = tmp_path / "watchlist.json"
    wl_file.write_text(json.dumps(override))
    monkeypatch.setattr(tp, "DATA_DIR", str(tmp_path))
    # Aunque haya inventario, el override manda.
    monkeypatch.setattr(tp, "skins_from_inventory", lambda: ["otra skin"])
    wl = tp.load_watchlist()
    assert wl == override


def test_load_watchlist_nunca_usa_el_ejemplo(monkeypatch):
    """Sin nada configurado: watchlist vacía (no las skins de watchlist.example.json)."""
    monkeypatch.setattr(tp, "_read", lambda p, d: d)
    monkeypatch.setattr(tp, "skins_from_inventory", lambda: [])
    monkeypatch.setattr(tp, "cards_from_saved", lambda: [])
    wl = tp.load_watchlist()
    assert wl == {"cards": [], "skins": []}


def test_main_falla_en_voz_alta_si_watchlist_vacia(monkeypatch, tmp_path):
    """Sin nada que seguir NO se inventan precios, pero el trabajo falla.

    Terminar en silencio es lo que dejó el histórico congelado durante semanas
    sin que se notara: ahora el cron se pone en rojo.
    """
    import pytest

    hist = tmp_path / "price_history.json"
    monkeypatch.setattr(tp.prices, "HISTORY_FILE", str(hist))
    monkeypatch.setattr(tp.prices, "record_portfolio", lambda *a, **k: 0)
    monkeypatch.setattr(tp, "load_watchlist", lambda: {"cards": [], "skins": []})
    with pytest.raises(RuntimeError, match="Nada que seguir"):
        tp.main()
    assert not hist.exists()      # no genera histórico con datos inventados


def test_main_registra_el_patrimonio_aunque_no_haya_watchlist(monkeypatch, tmp_path):
    """El histórico del patrimonio no depende de Steam ni de Magic.

    Si el inventario no está configurado el trabajo falla igual (hay que
    arreglarlo), pero el patrimonio del día ya ha quedado registrado.
    """
    import pytest

    hist = tmp_path / "price_history.json"
    monkeypatch.setattr(tp.prices, "HISTORY_FILE", str(hist))
    monkeypatch.setattr(tp.prices, "record_portfolio",
                        lambda day=None: tp.prices.record(
                            day, {"total:Patrimonio": 9615.87}) and 1)
    monkeypatch.setattr(tp, "load_watchlist", lambda: {"cards": [], "skins": []})
    with pytest.raises(RuntimeError, match="Nada que seguir"):
        tp.main()
    saved = json.loads(hist.read_text())
    assert list(saved.values())[0] == {"total:Patrimonio": 9615.87}


def test_main_falla_si_ninguna_fuente_devuelve_precio(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr(tp.prices, "HISTORY_FILE", str(tmp_path / "price_history.json"))
    monkeypatch.setattr(tp, "load_watchlist",
                        lambda: {"cards": ["Sol Ring"], "skins": []})
    monkeypatch.setattr(tp, "card_prices", lambda names: {})
    monkeypatch.setattr(tp, "skin_prices", lambda names: ({}, []))
    with pytest.raises(RuntimeError, match="no registra un día vacío|día vacío"):
        tp.main()


def test_skin_prices_para_y_avisa_si_steam_corta(monkeypatch):
    """Un 429 a mitad no puede pasar por «esta skin no tiene precio»."""
    precios = {"A": 10.0, "B": 20.0}

    def fake_price(name, cur, cache):
        if name == "C":
            raise tp.steam._RateLimited()
        return precios[name], True

    monkeypatch.setattr(tp.steam, "_price", fake_price)
    monkeypatch.setattr(tp.steam, "_load_cache", lambda: {})
    monkeypatch.setattr(tp.steam, "_save_cache", lambda c: None)
    out, warnings = tp.skin_prices(["A", "B", "C", "D"])
    assert out == {"skin:A": 10.0, "skin:B": 20.0}      # se guarda lo obtenido
    assert len(warnings) == 1
    assert "429" in warnings[0] and "2 de 4" in warnings[0]


def test_main_se_pone_en_rojo_si_el_dia_queda_incompleto(monkeypatch, tmp_path):
    """Guarda lo que tenga, pero un día a medias no puede pasar por bueno."""
    import pytest

    hist = tmp_path / "price_history.json"
    monkeypatch.setattr(tp.prices, "HISTORY_FILE", str(hist))
    monkeypatch.setattr(tp.prices, "record_portfolio", lambda *a, **k: 0)
    monkeypatch.setattr(tp, "load_watchlist",
                        lambda: {"cards": [], "skins": ["A", "B", "C"]})
    monkeypatch.setattr(tp, "skin_prices",
                        lambda names: ({"skin:A": 1.0}, ["Steam cortó (429)"]))
    with pytest.raises(RuntimeError, match="faltan 2 de 3"):
        tp.main()
    # …pero lo obtenido SÍ queda guardado, no se tira.
    assert json.loads(hist.read_text())[max(json.loads(hist.read_text()))] == {"skin:A": 1.0}


def test_main_registra_precios_en_fichero_y_db(monkeypatch, tmp_path):
    from sources import db, prices

    hist = tmp_path / "price_history.json"
    monkeypatch.setattr(prices, "HISTORY_FILE", str(hist))
    monkeypatch.setattr(tp, "load_watchlist",
                        lambda: {"cards": ["Sol Ring"], "skins": ["AK-47 | Redline (Field-Tested)"]})
    monkeypatch.setattr(tp, "card_prices", lambda names: {"card:Sol Ring": 3.85})
    monkeypatch.setattr(tp, "skin_prices",
                        lambda names: ({"skin:AK-47 | Redline (Field-Tested)": 37.5}, []))
    out = tp.main()
    assert out == {"card:Sol Ring": 3.85, "skin:AK-47 | Redline (Field-Tested)": 37.5}
    saved = json.loads(hist.read_text())
    assert list(saved.values())[0]["card:Sol Ring"] == 3.85
    # El mismo dato queda en la base de datos, que es de donde lo lee la web.
    assert any(day["card:Sol Ring"] == 3.85 for day in db.get_price_history().values())
