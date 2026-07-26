"""Histórico de precios: serie semanal y movimientos ±5% (arriba y abajo)."""

import datetime
import json

import pytest

from sources import prices


def _day(offset):
    return (datetime.date.today() - datetime.timedelta(days=offset)).isoformat()


@pytest.fixture()
def historia():
    """Una semana real: Sol Ring sube ~10%, la AK baja ~12%, Rhystic apenas se mueve."""
    return {
        _day(8): {"card:Sol Ring": 3.00, "card:Rhystic Study": 38.00,
                  "skin:AK-47 | Redline (Field-Tested)": 40.00},
        _day(4): {"card:Sol Ring": 3.10, "card:Rhystic Study": 38.20,
                  "skin:AK-47 | Redline (Field-Tested)": 38.00},
        _day(0): {"card:Sol Ring": 3.30, "card:Rhystic Study": 38.40,
                  "skin:AK-47 | Redline (Field-Tested)": 35.20},
    }


def test_split_key():
    assert prices.split_key("card:Sol Ring") == ("card", "Sol Ring")
    assert prices.split_key("skin:AK-47 | Redline (FT)") == ("skin", "AK-47 | Redline (FT)")
    assert prices.split_key("suelto") == ("", "suelto")


def test_movers_detecta_subidas_y_bajadas(historia):
    movers = prices.movers(historia, threshold=5.0)
    by_name = {m["name"]: m for m in movers}
    # Sol Ring +10%, AK -12%: los dos superan el 5%. Rhystic Study (+1%) no.
    assert set(by_name) == {"Sol Ring", "AK-47 | Redline (Field-Tested)"}
    assert by_name["Sol Ring"]["direction"] == "up"
    assert by_name["Sol Ring"]["price_from"] == 3.00
    assert by_name["Sol Ring"]["price_to"] == 3.30
    assert by_name["Sol Ring"]["pct"] == 10.0
    ak = by_name["AK-47 | Redline (Field-Tested)"]
    assert ak["direction"] == "down"
    assert ak["pct"] == -12.0
    assert ak["price_from"] == 40.00 and ak["price_to"] == 35.20
    # Ordenados por variación absoluta: la bajada del 12% va primero.
    assert movers[0]["name"] == "AK-47 | Redline (Field-Tested)"


def test_movers_respeta_el_umbral(historia):
    assert prices.movers(historia, threshold=15.0) == []
    assert len(prices.movers(historia, threshold=0.5)) == 3


def test_movers_sin_historial_suficiente():
    assert prices.movers({}) == []
    assert prices.movers({_day(0): {"card:Sol Ring": 3.0}}) == []


def test_weekly_series_toma_el_ultimo_dia_de_cada_semana():
    hist = {
        "2026-07-06": {"card:Sol Ring": 3.00},   # lunes, semana 28
        "2026-07-10": {"card:Sol Ring": 3.50},   # viernes, misma semana -> manda este
        "2026-07-13": {"card:Sol Ring": 4.00},   # semana 29
    }
    series = prices.weekly_series(hist)["card:Sol Ring"]
    assert [p["week"] for p in series] == ["2026-W28", "2026-W29"]
    assert [p["price"] for p in series] == [3.50, 4.00]
    assert series[0]["date"] == "2026-07-10"


def test_weekly_table_calcula_la_variacion_semanal():
    hist = {"2026-07-10": {"skin:AK-47 | Redline (Field-Tested)": 40.0},
            "2026-07-17": {"skin:AK-47 | Redline (Field-Tested)": 30.0}}
    row = prices.weekly_table(hist)[0]
    assert row["kind"] == "skin"
    assert row["prev"] == 40.0 and row["price"] == 30.0
    assert row["delta"] == -10.0 and row["pct"] == -25.0
    assert len(row["points"]) == 2


def test_coverage_detecta_seguimiento_parado(historia):
    cov = prices.coverage(historia)
    assert cov["days"] == 3
    assert cov["items"] == 3
    assert cov["last_day"] == _day(0)
    assert cov["stale_days"] == 0
    assert prices.coverage({})["days"] == 0


def test_record_escribe_fichero_y_base_de_datos(monkeypatch, tmp_path):
    from sources import db

    history_file = tmp_path / "price_history.json"
    monkeypatch.setattr(prices, "HISTORY_FILE", str(history_file))
    prices.record("2026-07-20", {"card:Sol Ring": 3.85})
    prices.record("2026-07-21", {"card:Sol Ring": 4.10})
    saved = json.loads(history_file.read_text())
    assert saved["2026-07-21"]["card:Sol Ring"] == 4.10
    assert db.get_price_history()["2026-07-20"]["card:Sol Ring"] == 3.85
    # `history()` fusiona ambos almacenes sin duplicar días.
    merged = prices.history()
    assert merged["2026-07-21"]["card:Sol Ring"] == 4.10
