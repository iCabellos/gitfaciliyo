"""imagin por PSD2 (Enable Banking): mapeo real de saldos y movimientos.

Las llamadas HTTP se sustituyen por respuestas con la forma que devuelve la API
(no se toca la red en los tests); lo que se comprueba es el mapeo y que una
fuente sin autorizar se detecte como «no conectada», no como un fallo.
"""

import datetime

import pytest

from sources import enablebanking, db


@pytest.fixture(autouse=True)
def _sin_sesion():
    db.set_setting(enablebanking.SESSION_SETTING, {})
    yield
    db.set_setting(enablebanking.SESSION_SETTING, {})


def test_sin_autorizar_es_not_configured():
    with pytest.raises(enablebanking.NotConfigured):
        enablebanking.session()
    assert enablebanking.is_connected() is False


def test_default_aspsp_es_imagin(monkeypatch):
    monkeypatch.delenv("ENABLE_BANKING_ASPSP", raising=False)
    monkeypatch.delenv("ENABLE_BANKING_COUNTRY", raising=False)
    assert enablebanking.default_aspsp() == {"name": "imagin", "country": "ES"}


def test_normalize_signo_y_concepto():
    gasto = enablebanking._normalize({
        "transaction_amount": {"amount": "12.34", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "booking_date": "2026-07-15",
        "remittance_information": ["MERCADONA", "PALMA"],
    })
    assert gasto == {"concept": "MERCADONA PALMA", "date": "15/07/2026",
                     "amount": -12.34, "balance": 0.0}

    ingreso = enablebanking._normalize({
        "transaction_amount": {"amount": "1500.00"},
        "credit_debit_indicator": "CRDT",
        "value_date": "2026-07-01",
        "creditor": {"name": "NOMINA EMPRESA SL"},
    })
    assert ingreso["amount"] == 1500.0
    assert ingreso["concept"] == "NOMINA EMPRESA SL"
    assert ingreso["date"] == "01/07/2026"


def test_normalize_descarta_lo_que_no_tiene_fecha_o_importe():
    assert enablebanking._normalize({"transaction_amount": {"amount": "5"}}) is None
    assert enablebanking._normalize({"booking_date": "2026-07-01"}) is None


def test_account_balance_prefiere_el_disponible(monkeypatch):
    monkeypatch.setattr(enablebanking, "_api", lambda path, *a, **k: {"balances": [
        {"balance_type": "CLBD", "balance_amount": {"amount": "1000.00"}},
        {"balance_type": "ITAV", "balance_amount": {"amount": "950.25"}},
    ]})
    assert enablebanking.account_balance("uid") == 950.25


def test_account_transactions_pagina_hasta_agotar(monkeypatch):
    paginas = [
        {"transactions": [{"id": 1}], "continuation_key": "abc"},
        {"transactions": [{"id": 2}], "continuation_key": None},
    ]
    vistas = []

    def fake_api(path, *a, **k):
        vistas.append(path)
        return paginas[len(vistas) - 1]

    monkeypatch.setattr(enablebanking, "_api", fake_api)
    txs = enablebanking.account_transactions("uid", date_from="2026-07-01")
    assert [t["id"] for t in txs] == [1, 2]
    assert "continuation_key=abc" in vistas[1]


def test_analyze_suma_cuentas_y_clasifica(monkeypatch):
    db.set_setting(enablebanking.SESSION_SETTING, {
        "session_id": "sess-1",
        "accounts": [{"uid": "a1", "iban": "ES1234", "name": "imagin", "currency": "EUR"},
                     {"uid": "a2", "iban": "ES9999", "name": "ahorro", "currency": "EUR"}],
        "access_valid_until": "2026-10-01T00:00:00Z",
    })
    monkeypatch.setattr(enablebanking, "account_balance",
                        lambda uid: {"a1": 6000.78, "a2": 200.00}[uid])
    monkeypatch.setattr(enablebanking, "account_transactions", lambda uid, date_from=None: (
        [{"transaction_amount": {"amount": "50.00"}, "credit_debit_indicator": "DBIT",
          "booking_date": "2026-07-10", "remittance_information": ["MERCADONA"]}]
        if uid == "a1" else
        [{"transaction_amount": {"amount": "1800.00"}, "credit_debit_indicator": "CRDT",
          "booking_date": "2026-07-01", "remittance_information": ["NOMINA"]}]))

    r = enablebanking.analyze()
    assert r["source"] == enablebanking.SOURCE
    assert r["available_balance"] == 6200.78
    assert r["aggregates"]["liquidez"] == 6200.78
    assert r["aggregates"]["gastos"] == 50.0        # supermercado
    assert r["aggregates"]["ganancias"] == 1800.0   # nómina
    assert r["month"] == "2026-07"
    assert r["access_valid_until"] == "2026-10-01T00:00:00Z"


def test_analyze_sin_movimientos_usa_el_mes_actual(monkeypatch):
    db.set_setting(enablebanking.SESSION_SETTING, {
        "session_id": "s", "accounts": [{"uid": "a1", "iban": "", "name": "", "currency": "EUR"}]})
    monkeypatch.setattr(enablebanking, "account_balance", lambda uid: 100.0)
    monkeypatch.setattr(enablebanking, "account_transactions", lambda uid, date_from=None: [])
    r = enablebanking.analyze()
    assert r["month"] == datetime.date.today().strftime("%Y-%m")
    assert r["aggregates"]["month"] == r["month"]
    assert r["aggregates"]["liquidez"] == 100.0
