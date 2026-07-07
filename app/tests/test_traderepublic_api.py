"""Trade Republic (API no oficial): mapeo puro de la cartera y validación de login."""

import pytest

from sources import traderepublic_api as tr


def test_map_portfolio_calcula_valor():
    positions = [{"instrumentId": "US0378331005", "netSize": "3"},
                 {"instrumentId": "IE00BK5BQT80", "netSize": "12"}]
    instruments = {"US0378331005": "Apple", "IE00BK5BQT80": "FTSE All-World"}
    tickers = {"US0378331005": 180.5, "IE00BK5BQT80": 118.2}
    out = tr.map_portfolio(positions, instruments, tickers)
    assert out["category"] == "Acciones / ETFs"
    assert len(out["positions"]) == 2
    assert out["positions"][0]["name"] == "Apple"
    assert out["positions"][0]["value"] == 541.5
    assert out["total"] == round(541.5 + 12 * 118.2, 2)


def test_map_portfolio_sin_precio():
    out = tr.map_portfolio([{"instrumentId": "X", "netSize": "5"}], {}, {})
    assert out["positions"][0]["value"] == 0.0
    assert out["positions"][0]["name"] == "X"     # cae al ISIN si no hay nombre
    assert out["total"] == 0.0


def test_map_portfolio_ignora_sin_isin():
    out = tr.map_portfolio([{"netSize": "5"}], {}, {})
    assert out["positions"] == []


def test_start_login_valida_telefono():
    with pytest.raises(ValueError):
        tr.start_login("640253466", "1234")   # sin prefijo internacional
