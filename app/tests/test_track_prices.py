"""Seguimiento diario de precios: la watchlist sale de lo que REALMENTE tienes.

Verifica que no se siguen skins/cartas de ejemplo: solo el inventario real de
Steam y la lista de Magic guardada (o un override explícito).
"""

import json
import os

from jobs import track_prices as tp


def _inventory(names_marketable, names_unmarketable=()):
    """Simula steam.fetch_inventory + _group_items sin tocar la red."""
    items = {n: {"marketable": True, "count": 1} for n in names_marketable}
    items.update({n: {"marketable": False, "count": 1} for n in names_unmarketable})
    return items


def test_skins_from_inventory_solo_vendibles(monkeypatch):
    monkeypatch.setenv("STEAM_ID64", "76561190000000000")
    monkeypatch.setattr(tp.steam, "fetch_inventory", lambda sid, **k: {"raw": sid})
    monkeypatch.setattr(tp.steam, "_group_items",
                        lambda inv: _inventory(["AK-47 | Redline (Field-Tested)"],
                                               ["Sticker | no vendible"]))
    skins = tp.skins_from_inventory()
    assert skins == ["AK-47 | Redline (Field-Tested)"]      # se ignora lo no vendible


def test_skins_from_inventory_sin_steamid(monkeypatch):
    monkeypatch.delenv("STEAM_ID64", raising=False)
    monkeypatch.setattr(tp, "_read", lambda p, d: d)         # sin config.json
    monkeypatch.setattr(tp, "_steamid", lambda: "")
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


def test_main_no_escribe_nada_si_watchlist_vacia(monkeypatch, tmp_path):
    hist = tmp_path / "price_history.json"
    monkeypatch.setattr(tp, "HISTORY", str(hist))
    monkeypatch.setattr(tp, "load_watchlist", lambda: {"cards": [], "skins": []})
    out = tp.main()
    assert out == {}
    assert not hist.exists()      # no genera histórico con datos inventados
