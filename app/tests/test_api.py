"""Rutas de la API con el cliente de pruebas de Flask (SQLite temporal)."""

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


def test_magic_requiere_entrada(client):
    r = client.post("/api/magic", json={})
    assert r.status_code == 400


def test_cards_roundtrip(client):
    client.post("/api/cards", json={"reference": "abc", "decklist": "1 Sol Ring"})
    body = client.get("/api/cards").get_json()
    assert body["reference"] == "abc"
    assert body["decklist"] == "1 Sol Ring"
