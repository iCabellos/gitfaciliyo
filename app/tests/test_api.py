"""Rutas de la API con el cliente de pruebas de Flask (SQLite temporal)."""

import json
import os

import app as app_module


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_version(client):
    r = client.get("/api/version")
    body = r.get_json()
    assert r.status_code == 200
    assert body["version"] == app_module.APP_VERSION
    assert body["db"] == "sqlite"
    assert "banco" in body["sources"]


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_snapshots_vacio(client):
    assert client.get("/api/snapshots").get_json() == {}


def test_snapshot_invalido(client):
    # month con formato incorrecto -> 400
    r = client.post("/api/snapshot", json={"month": "2026/07", "category": "X", "value": 1})
    assert r.status_code == 400


def test_snapshot_valido_y_persistencia(client):
    r = client.post("/api/snapshot",
                    json={"month": "2026-07", "category": "Acciones", "value": 1000.0})
    assert r.status_code == 200
    snaps = client.get("/api/snapshots").get_json()
    assert snaps["2026-07"]["Acciones"] == 1000.0


def test_summary_endpoint(client):
    client.post("/api/snapshot", json={"month": "2026-06", "category": "Acciones", "value": 1000.0})
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 1200.0})
    s = client.get("/api/summary").get_json()
    assert s["total"] == 1200.0
    assert s["delta"] == 200.0


def test_summary_vacio_devuelve_objeto_vacio(client):
    assert client.get("/api/summary").get_json() == {}


def test_monthly_summary_sin_datos(client):
    assert client.post("/api/monthly-summary").status_code == 404


def test_monthly_summary_envia(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(app_module, "send_whatsapp",
                        lambda msg: sent.update(msg=msg) or True)
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    r = client.post("/api/monthly-summary")
    assert r.status_code == 200
    assert r.get_json()["sent"] is True
    assert "Acciones" in sent["msg"]


def test_monthly_summary_token(client, monkeypatch):
    monkeypatch.setenv("SUMMARY_TOKEN", "secreto")
    monkeypatch.setattr(app_module, "send_whatsapp", lambda msg: True)
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 1.0})
    assert client.post("/api/monthly-summary").status_code == 403
    assert client.post("/api/monthly-summary?token=secreto").status_code == 200


def test_monthly_summary_revaloriza_skins_y_cartas(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(app_module, "send_whatsapp",
                        lambda msg: sent.update(msg=msg) or True)
    monkeypatch.setattr(app_module.revalue, "refresh_live",
                        lambda: ({"Skins CS:GO": 150.0}, {}, {}))
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    body = client.post("/api/monthly-summary").get_json()
    assert body["refreshed"] == {"Skins CS:GO": 150.0}
    assert body["refresh_errors"] == {}


def test_monthly_summary_avisa_si_una_fuente_falla(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(app_module, "send_whatsapp",
                        lambda msg: sent.update(msg=msg) or True)
    monkeypatch.setattr(app_module.revalue, "refresh_live",
                        lambda: ({}, {"Skins CS:GO": "Steam no deja leer el inventario."}, {}))
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    r = client.post("/api/monthly-summary")
    assert r.status_code == 200
    assert "⚠️ Skins CS:GO no se pudo revalorizar" in sent["msg"]
    assert "Steam no deja leer el inventario." in sent["msg"]


def test_monthly_summary_avisa_de_las_fuentes_sin_conectar(client, monkeypatch):
    """Una fuente sin conectar deja de saltarse en silencio: sale en el mensaje.

    Es la causa de recibir el mismo importe semana tras semana sin explicación.
    """
    sent = {}
    monkeypatch.setattr(app_module, "send_whatsapp",
                        lambda msg: sent.update(msg=msg) or True)
    monkeypatch.setattr(app_module.revalue, "refresh_live",
                        lambda: ({}, {}, {"Acciones / ETFs": "Trade Republic no está emparejado."}))
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    body = client.post("/api/monthly-summary").get_json()
    assert body["not_connected"] == {"Acciones / ETFs": "Trade Republic no está emparejado."}
    assert "⚠️ Acciones / ETFs no está conectado" in sent["msg"]


def test_monthly_summary_incluye_los_movimientos_de_precio(client, monkeypatch):
    from sources import prices

    sent = {}
    monkeypatch.setattr(app_module, "send_whatsapp",
                        lambda msg: sent.update(msg=msg) or True)
    monkeypatch.setattr(app_module.revalue, "refresh_live", lambda: ({}, {}, {}))
    monkeypatch.setattr(prices, "history", lambda days=None: {
        "2026-07-19": {"card:Sol Ring": 3.00, "skin:AK-47 | Redline (FT)": 40.00},
        "2026-07-26": {"card:Sol Ring": 3.30, "skin:AK-47 | Redline (FT)": 35.20},
    })
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    body = client.post("/api/monthly-summary").get_json()
    assert {m["name"] for m in body["movers"]} == {"Sol Ring", "AK-47 | Redline (FT)"}
    assert "3,00 € → 3,30 €" in sent["msg"]
    assert "40,00 € → 35,20 €" in sent["msg"]


def test_prices_weekly_endpoint(client, monkeypatch):
    from sources import prices

    monkeypatch.setattr(prices, "history", lambda days=None: {
        "2026-07-10": {"card:Sol Ring": 3.00},
        "2026-07-17": {"card:Sol Ring": 3.60},
    })
    body = client.get("/api/prices/weekly").get_json()
    assert body["items"][0]["name"] == "Sol Ring"
    assert body["items"][0]["price"] == 3.60
    assert body["items"][0]["prev"] == 3.00
    assert body["items"][0]["pct"] == 20.0
    assert len(body["items"][0]["points"]) == 2
    assert body["coverage"]["days"] == 2


def test_prices_movers_endpoint_respeta_el_umbral(client, monkeypatch):
    from sources import prices

    monkeypatch.setattr(prices, "history", lambda days=None: {
        "2026-07-10": {"card:Sol Ring": 3.00},
        "2026-07-26": {"card:Sol Ring": 3.20},      # +6,7%
    })
    assert len(client.get("/api/prices/movers?threshold=5").get_json()["movers"]) == 1
    assert client.get("/api/prices/movers?threshold=10").get_json()["movers"] == []


def test_prices_weekly_incluye_el_patrimonio_completo(client, monkeypatch):
    from sources import prices

    monkeypatch.setattr(prices, "history", lambda days=None: {
        "2026-07-12": {prices.TOTAL_KEY: 9000.0, "cat:Cartas Magic": 1000.0,
                       "stock:Apple Inc.": 170.0, "card:Sol Ring": 3.00},
        "2026-07-19": {prices.TOTAL_KEY: 9600.0, "cat:Cartas Magic": 1100.0,
                       "stock:Apple Inc.": 180.5, "card:Sol Ring": 3.60},
    })
    body = client.get("/api/prices/weekly").get_json()
    kinds = {i["key"]: i["kind"] for i in body["items"]}
    assert kinds == {prices.TOTAL_KEY: "total", "cat:Cartas Magic": "cat",
                     "stock:Apple Inc.": "stock", "card:Sol Ring": "card"}
    # `portfolio` repite solo lo agregado, que es lo del gráfico de cabecera.
    assert {p["key"] for p in body["portfolio"]} == {prices.TOTAL_KEY, "cat:Cartas Magic"}
    total = next(p for p in body["portfolio"] if p["key"] == prices.TOTAL_KEY)
    assert (total["prev"], total["price"], total["pct"]) == (9000.0, 9600.0, 6.7)
    assert body["coverage"]["tracks_portfolio"] is True
    assert body["total_key"] == prices.TOTAL_KEY


def test_prices_weekly_filtra_por_tipo(client, monkeypatch):
    from sources import prices

    monkeypatch.setattr(prices, "history", lambda days=None: {
        "2026-07-19": {prices.TOTAL_KEY: 9600.0, "card:Sol Ring": 3.60},
    })
    body = client.get("/api/prices/weekly?kind=card").get_json()
    assert [i["key"] for i in body["items"]] == ["card:Sol Ring"]


def test_prices_movers_incluye_categorias_y_total(client, monkeypatch):
    from sources import prices

    monkeypatch.setattr(prices, "history", lambda days=None: {
        "2026-07-19": {prices.TOTAL_KEY: 9000.0, "cat:Acciones / ETFs": 1000.0},
        "2026-07-26": {prices.TOTAL_KEY: 9600.0, "cat:Acciones / ETFs": 1200.0},
    })
    movers = client.get("/api/prices/movers").get_json()["movers"]
    assert [m["kind"] for m in movers] == ["total", "cat"]
    assert movers[0]["price_from"] == 9000.0 and movers[0]["price_to"] == 9600.0


def test_prices_record_guarda_el_punto_del_patrimonio(client, monkeypatch):
    from sources import db, prices

    monkeypatch.setattr(prices, "write_file_history", lambda h: None)
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    db.set_holdings("2026-07", "Trade Republic", [
        {"name": "Apple", "quantity": 3, "unit_value": 180.5, "value": 541.5}])
    body = client.post("/api/prices/record").get_json()
    assert body["recorded"] == 3          # total + categoría + acción
    saved = db.get_price_history()
    hoy = saved[max(saved)]
    assert hoy[prices.TOTAL_KEY] == 5000.0
    assert hoy["cat:Acciones"] == 5000.0
    assert hoy["stock:Apple"] == 180.5


def test_monthly_summary_registra_el_patrimonio_en_el_historico(client, monkeypatch):
    """El resumen semanal deja su propio punto: el histórico no depende del cron."""
    from sources import db, prices

    monkeypatch.setattr(app_module, "send_whatsapp", lambda msg: True)
    monkeypatch.setattr(app_module.revalue, "refresh_live", lambda: ({}, {}, {}))
    monkeypatch.setattr(prices, "write_file_history", lambda h: None)
    client.post("/api/snapshot", json={"month": "2026-07", "category": "Acciones", "value": 5000.0})
    assert client.post("/api/monthly-summary").status_code == 200
    saved = db.get_price_history()
    assert saved[max(saved)][prices.TOTAL_KEY] == 5000.0


def test_prices_endpoints_sin_historico(client, monkeypatch):
    from sources import prices

    monkeypatch.setattr(prices, "history", lambda days=None: {})
    weekly = client.get("/api/prices/weekly").get_json()
    assert weekly["items"] == []
    assert weekly["coverage"]["days"] == 0        # se dice que no hay nada
    assert client.get("/api/prices/movers").get_json()["movers"] == []


def test_holdings_endpoint(client):
    from sources import db

    db.set_holdings("2026-07", "Trade Republic", [
        {"name": "Apple", "isin": "US0378331005", "quantity": 3, "unit_value": 180.5,
         "value": 541.5, "currency": "EUR"},
        {"name": "S&P 500 EUR (Acc)", "isin": "IE00BK5BQT80", "quantity": 8.267789,
         "unit_value": 129.26, "value": 1068.69, "currency": "EUR"},
    ])
    body = client.get("/api/holdings").get_json()
    assert body["month"] == "2026-07"
    assert {h["name"]: h["quantity"] for h in body["holdings"]} == {
        "Apple": 3.0, "S&P 500 EUR (Acc)": 8.267789}
    assert body["total"] == 1610.19
    assert body["titles"] == 11.2678


def test_holdings_endpoint_vacio(client):
    body = client.get("/api/holdings").get_json()
    assert body["holdings"] == []
    assert body["months"] == []


def test_imagin_y_tr_reportan_que_no_estan_conectados(client):
    assert client.get("/api/imagin/status").get_json()["connected"] is False
    assert client.get("/api/trade-republic/status").get_json()["paired"] is False
    # 409: no es un fallo del servidor, es que falta autorizar la fuente.
    r = client.post("/api/trade-republic/live")
    assert r.status_code == 409
    assert r.get_json()["connected"] is False
    assert client.post("/api/imagin/refresh").status_code == 409


def test_config_no_usa_nunca_el_fichero_de_ejemplo(client, monkeypatch, tmp_path):
    """Sin config.json propio, la web NO propone datos de la plantilla.

    Caer en config.example.json hacía que /api/config devolviera un SteamID que
    no es el del usuario, que la web lo prefijara y que /api/steam valorara ese
    inventario como su patrimonio.
    """
    from sources import settings

    monkeypatch.setattr(settings, "CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.setattr(settings, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    body = client.get("/api/config").get_json()
    assert body["steamid"] == ""
    assert body["moxfield"] == ""
    # Y /api/steam sin id falla a la vista en vez de tirar de la plantilla.
    r = client.get("/api/steam")
    assert r.status_code == 400
    assert "SteamID64" in r.get_json()["error"]


def test_config_lee_el_config_json_real(client, monkeypatch, tmp_path):
    from sources import settings

    real = tmp_path / "config.json"
    real.write_text(json.dumps({"steam": {"steamid64": "76561190000000001"},
                                "moxfield": {"default_deck": "abc"}}))
    monkeypatch.setattr(settings, "CONFIG_PATH", str(real))
    monkeypatch.setattr(settings, "SETTINGS_PATH", str(tmp_path / "settings.json"))
    body = client.get("/api/config").get_json()
    assert body["steamid"] == "76561190000000001"
    assert body["moxfield"] == "abc"


def test_la_plantilla_no_lleva_datos_reales():
    """config.example.json está en el repo: no puede llevar un SteamID de verdad."""
    from sources import settings as settings_mod

    example = os.path.join(os.path.dirname(settings_mod.__file__), os.pardir,
                           "config.example.json")
    with open(example) as fh:
        cfg = json.load(fh)
    steamid = cfg["steam"]["steamid64"]
    assert steamid.startswith("TU_"), f"la plantilla lleva un SteamID real: {steamid}"


def test_magic_requiere_entrada(client):
    r = client.post("/api/magic", json={})
    assert r.status_code == 400


def test_cards_roundtrip(client):
    client.post("/api/cards", json={"reference": "abc", "decklist": "1 Sol Ring"})
    body = client.get("/api/cards").get_json()
    assert body["reference"] == "abc"
    assert body["decklist"] == "1 Sol Ring"
