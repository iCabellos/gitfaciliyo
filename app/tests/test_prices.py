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


# ---- el patrimonio entero dentro del mismo histórico ---------------------
SNAPSHOTS = {
    "2026-06": {"Liquidez (banco)": 6200.78, "Skins CS:GO": 1289.91,
                "_flow:gastos": 2146.52},
    "2026-07": {"Skins CS:GO": 1189.40, "Cartas Magic": 1041.51},
}
HOLDINGS = [{"name": "Apple Inc.", "quantity": 3.0, "unit_value": 180.5},
            {"name": "S&P 500 EUR (Acc)", "quantity": 8.267789, "unit_value": 129.26}]


def test_portfolio_points_cubre_total_categorias_y_acciones():
    points = prices.portfolio_points(SNAPSHOTS, HOLDINGS)
    # Cada categoría con su último valor conocido (la liquidez viene de junio).
    assert points["cat:Liquidez (banco)"] == 6200.78
    assert points["cat:Skins CS:GO"] == 1189.40
    assert points["cat:Cartas Magic"] == 1041.51
    # El total es la suma de esos últimos valores, sin contar los flujos.
    assert points[prices.TOTAL_KEY] == 8431.69
    # Y cada acción entra con su precio POR TÍTULO, no con su valor total.
    assert points["stock:Apple Inc."] == 180.5
    assert points["stock:S&P 500 EUR (Acc)"] == 129.26
    assert not any(k.startswith("_flow") for k in points)


def test_portfolio_points_sin_datos_no_inventa_nada():
    assert prices.portfolio_points({}, []) == {}
    assert prices.portfolio_points(None, None) == {}
    # Una acción sin precio unitario no se registra (no vale un 0 falso).
    assert prices.portfolio_points({}, [{"name": "X", "unit_value": 0}]) == {}


def test_record_portfolio_guarda_el_punto_del_dia(monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "HISTORY_FILE", str(tmp_path / "price_history.json"))
    saved = prices.record_portfolio("2026-07-26", snapshots=SNAPSHOTS, holdings=HOLDINGS)
    assert saved == 6
    assert prices.history()["2026-07-26"][prices.TOTAL_KEY] == 8431.69


def test_record_fusiona_el_dia_en_vez_de_reemplazarlo(monkeypatch, tmp_path):
    """El cron de precios y el registro del patrimonio caen el mismo día.

    Escriben claves distintas: el segundo no puede borrar lo del primero.
    """
    monkeypatch.setattr(prices, "HISTORY_FILE", str(tmp_path / "price_history.json"))
    prices.record("2026-07-26", {"card:Sol Ring": 3.85})
    prices.record_portfolio("2026-07-26", snapshots=SNAPSHOTS, holdings=HOLDINGS)
    day = prices.history()["2026-07-26"]
    assert day["card:Sol Ring"] == 3.85          # sigue ahí
    assert day[prices.TOTAL_KEY] == 8431.69      # y además el patrimonio


def test_movers_incluye_el_patrimonio_y_lo_pone_primero():
    hist = {
        _day(7): {prices.TOTAL_KEY: 9000.0, "cat:Acciones / ETFs": 1000.0,
                  "card:Sol Ring": 3.00},
        _day(0): {prices.TOTAL_KEY: 9600.0, "cat:Acciones / ETFs": 1200.0,
                  "card:Sol Ring": 3.90},
    }
    movers = prices.movers(hist, threshold=5.0)
    assert [m["kind"] for m in movers] == ["total", "cat", "card"]
    total = movers[0]
    assert total["name"] == "Patrimonio"
    assert total["kind_label"] == "Patrimonio"
    assert (total["price_from"], total["price_to"], total["pct"]) == (9000.0, 9600.0, 6.7)
    # La carta sube más (+30%) pero va detrás: primero se lee lo agregado.
    assert movers[-1]["pct"] == 30.0


def test_movers_y_weekly_table_filtran_por_tipo():
    hist = {
        _day(7): {prices.TOTAL_KEY: 9000.0, "card:Sol Ring": 3.00},
        _day(0): {prices.TOTAL_KEY: 9600.0, "card:Sol Ring": 3.90},
    }
    solo_patrimonio = prices.movers(hist, threshold=5.0, kinds=prices.PORTFOLIO_KINDS)
    assert [m["key"] for m in solo_patrimonio] == [prices.TOTAL_KEY]
    solo_cartas = prices.weekly_table(hist, kinds=("card",))
    assert [i["key"] for i in solo_cartas] == ["card:Sol Ring"]
    assert solo_cartas[0]["kind_label"] == "Carta"


def test_coverage_distingue_patrimonio_de_articulos():
    hist = {_day(0): {prices.TOTAL_KEY: 9600.0, "cat:Cartas Magic": 1041.51,
                      "card:Sol Ring": 3.90, "skin:AK-47": 36.10}}
    cov = prices.coverage(hist)
    assert cov["items"] == 2                 # la carta y la skin
    assert cov["portfolio_items"] == 2       # el total y la categoría
    assert cov["tracks_portfolio"] is True
    assert prices.coverage({})["tracks_portfolio"] is False


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
