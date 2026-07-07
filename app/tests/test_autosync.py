"""Sincronización automática: conexiones, orquestación y rutas."""

import pytest

from sources import autosync, db


def _reset():
    db.set_setting(autosync.WR_CONNECTIONS_KEY, {})
    db.set_setting(autosync.TR_SESSION_KEY, {})


def test_save_and_get_connection(client):
    _reset()
    autosync.save_wr_connection("imagin", "imagin", "tok123")
    conns = autosync.get_connections()
    assert conns["imagin"]["code"] == "imagin"
    assert "token" not in conns["imagin"]          # el token no se expone


def test_save_connection_valida():
    with pytest.raises(ValueError):
        autosync.save_wr_connection("", "", "")


def test_run_all_sincroniza_wealthreader(client, monkeypatch):
    _reset()
    autosync.save_wr_connection("imagin", "imagin", "tok")

    def fake_analyze(code, token, *a, **k):
        assert code == "imagin"
        return {"aggregates": {"liquidez": 1000.0, "gastos": 200.0,
                               "ganancias": 1500.0, "inversion": 0.0, "month": "2026-07"}}
    monkeypatch.setattr(autosync.wealthreader, "analyze", fake_analyze)

    report = autosync.run_all()
    assert report["ok"] == 1
    assert report["ran"] == 1
    snaps = db.get_snapshots()
    assert snaps["2026-07"]["Liquidez (banco)"] == 1000.0
    assert snaps["2026-07"]["_flow:gastos"] == 200.0


def test_run_all_aisla_fallos(client, monkeypatch):
    _reset()
    autosync.save_wr_connection("imagin", "imagin", "tok")
    monkeypatch.setattr(autosync.wealthreader, "analyze",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    report = autosync.run_all()               # no lanza; reporta el fallo
    assert report["ran"] == 1 and report["ok"] == 0
    assert report["results"][0]["ok"] is False
    assert "boom" in report["results"][0]["error"]


def test_status_shape(client):
    st = autosync.status()
    assert "connections" in st
    assert "trade_republic_session" in st
    assert "wealthreader_api_key" in st


# ---- rutas ---------------------------------------------------------------
def test_connections_endpoint(client):
    _reset()
    r = client.post("/api/connections", json={"name": "imagin", "code": "imagin", "token": "tok"})
    assert r.status_code == 200
    body = client.get("/api/connections").get_json()
    assert "imagin" in body


def test_connections_endpoint_valida(client):
    assert client.post("/api/connections", json={"name": "x"}).status_code == 400


def test_weekly_sync_token(client, monkeypatch):
    monkeypatch.setenv("SUMMARY_TOKEN", "secret")
    assert client.post("/api/weekly-sync").status_code == 403
    monkeypatch.setattr("app.send_whatsapp", lambda m: True)
    assert client.post("/api/weekly-sync?token=secret").status_code == 200


def test_weekly_sync_runs(client, monkeypatch):
    _reset()
    monkeypatch.setattr("app.send_whatsapp", lambda m: True)
    r = client.post("/api/weekly-sync")
    assert r.status_code == 200
    assert "ran" in r.get_json()


def test_tr_login_valida(client):
    assert client.post("/api/tr/login", json={"phone": ""}).status_code == 400


def test_autosync_status_endpoint(client):
    st = client.get("/api/autosync/status").get_json()
    assert "connections" in st
