"""imagin por PSD2 (Enable Banking): mapeo real de saldos y movimientos.

Las llamadas HTTP se sustituyen por respuestas con la forma que devuelve la API
(no se toca la red en los tests); lo que se comprueba es el mapeo y que una
fuente sin autorizar se detecte como «no conectada», no como un fallo.
"""

import datetime

import pytest

from sources import enablebanking, db


@pytest.fixture(autouse=True)
def _sin_sesion(monkeypatch):
    monkeypatch.delenv("ENABLE_BANKING_ASPSP", raising=False)
    monkeypatch.delenv("ENABLE_BANKING_COUNTRY", raising=False)
    monkeypatch.delenv("ENABLE_BANKING_REDIRECT_URL", raising=False)
    db.set_setting(enablebanking.SESSION_SETTING, {})
    db.set_setting(enablebanking.PENDING_SETTING, {})
    db.set_setting(enablebanking.ASPSP_SETTING, {})
    yield
    db.set_setting(enablebanking.SESSION_SETTING, {})
    db.set_setting(enablebanking.PENDING_SETTING, {})
    db.set_setting(enablebanking.ASPSP_SETTING, {})


def test_sin_autorizar_es_not_configured():
    with pytest.raises(enablebanking.NotConfigured):
        enablebanking.session()
    assert enablebanking.is_connected() is False


def test_default_aspsp_es_imagin():
    assert enablebanking.default_aspsp() == {"name": "imagin", "country": "ES"}


def test_el_banco_elegido_en_la_web_sustituye_al_de_por_defecto():
    assert enablebanking.set_aspsp("CaixaBank") == {"name": "CaixaBank", "country": "ES"}
    assert enablebanking.default_aspsp() == {"name": "CaixaBank", "country": "ES"}


def test_el_banco_del_servidor_manda_sobre_el_de_la_web(monkeypatch):
    enablebanking.set_aspsp("CaixaBank")
    monkeypatch.setenv("ENABLE_BANKING_ASPSP", "imagin")
    assert enablebanking.default_aspsp()["name"] == "imagin"


def test_elegir_un_banco_sin_nombre_es_un_error():
    with pytest.raises(ValueError):
        enablebanking.set_aspsp("   ")


def test_list_aspsps_pide_los_del_pais_y_los_ordena(monkeypatch):
    vistas = []

    def fake_api(path, *a, **k):
        vistas.append(path)
        return {"aspsps": [
            {"name": "Santander", "country": "ES", "maximum_consent_validity": 7776000},
            {"name": "CaixaBank", "country": "ES", "beta": True},
            {"country": "ES"},                       # sin nombre: no sirve, fuera
        ]}

    monkeypatch.setattr(enablebanking, "_api", fake_api)
    bancos = enablebanking.list_aspsps()
    assert [b["name"] for b in bancos] == ["CaixaBank", "Santander"]
    assert bancos[0]["beta"] is True
    assert bancos[1]["maximum_consent_validity"] == 7776000
    assert "country=ES" in vistas[0] and "psu_type=personal" in vistas[0]


def test_url_de_retorno_por_defecto_es_la_de_la_web(monkeypatch):
    assert enablebanking.configured_redirect_url("https://mi-app.test/imagin/callback") \
        == "https://mi-app.test/imagin/callback"
    monkeypatch.setenv("ENABLE_BANKING_REDIRECT_URL", "https://otra.test/x")
    assert enablebanking.configured_redirect_url("https://mi-app.test/imagin/callback") \
        == "https://otra.test/x"


def _dias_hasta(momento):
    return (momento - datetime.datetime.now(datetime.timezone.utc)).days


def test_el_consentimiento_no_pide_mas_dias_de_los_que_admite_el_banco():
    # 30 días en segundos: aunque se pidan 90, se recorta a lo que acepta el banco.
    assert 28 <= _dias_hasta(enablebanking._consent_valid_until(90, 30 * 86400)) <= 30
    # Y si el banco admite más de lo que pedimos, se queda en lo que pedimos.
    assert 88 <= _dias_hasta(enablebanking._consent_valid_until(90, 180 * 86400)) <= 90


def test_un_maximo_de_consentimiento_raro_no_tumba_la_autorizacion():
    """Es solo una ayuda: si llega mal, se ignora y se pide lo de siempre."""
    for basura in ("no-es-un-numero", {}, [], "  "):
        assert 88 <= _dias_hasta(enablebanking._consent_valid_until(90, basura)) <= 90


def test_start_auth_manda_lo_que_pide_la_api_y_deja_el_state_pendiente(monkeypatch):
    enviados = {}

    def fake_api(path, method="GET", payload=None):
        enviados["path"] = path
        enviados["payload"] = payload
        return {"url": "https://banco.test/sca?x=1", "authorization_id": "auth-1"}

    monkeypatch.setattr(enablebanking, "_api", fake_api)
    r = enablebanking.start_auth(default_redirect_url="https://mi-app.test/imagin/callback",
                                 aspsp="CaixaBank")
    assert enviados["path"] == "/auth" and enviados["payload"]["psu_type"] == "personal"
    assert enviados["payload"]["aspsp"] == {"name": "CaixaBank", "country": "ES"}
    assert enviados["payload"]["redirect_url"] == "https://mi-app.test/imagin/callback"
    assert r["url"] == "https://banco.test/sca?x=1"
    # El `state` queda guardado para poder comprobarlo cuando vuelva el banco.
    assert db.get_setting(enablebanking.PENDING_SETTING)["state"] == enviados["payload"]["state"]


def test_start_auth_sin_ninguna_url_de_retorno_lo_dice():
    with pytest.raises(enablebanking.NotConfigured):
        enablebanking.start_auth()


def test_complete_auth_rechaza_un_state_que_no_es_el_suyo(monkeypatch):
    db.set_setting(enablebanking.PENDING_SETTING, {"state": "el-bueno"})
    monkeypatch.setattr(enablebanking, "_api",
                        lambda *a, **k: pytest.fail("no debe llegar a llamar a la API"))
    with pytest.raises(ValueError):
        enablebanking.complete_auth("code-1", state="el-malo")


def test_complete_auth_guarda_la_sesion_y_las_cuentas(monkeypatch):
    db.set_setting(enablebanking.PENDING_SETTING, {"state": "s1"})
    monkeypatch.setattr(enablebanking, "_api", lambda *a, **k: {
        "session_id": "sess-9",
        "accounts": [{"uid": "a1", "account_id": {"iban": "ES99"}, "name": "imagin",
                      "currency": "EUR"}],
        "access": {"valid_until": "2026-10-01T00:00:00Z"}})
    saved = enablebanking.complete_auth("code-1", state="s1")
    assert saved["session_id"] == "sess-9"
    assert saved["accounts"] == [{"uid": "a1", "iban": "ES99", "name": "imagin",
                                  "currency": "EUR"}]
    assert enablebanking.is_connected() is True


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
