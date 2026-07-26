"""Trade Republic por su API: emparejado, protocolo websocket y cartera.

El websocket y las llamadas HTTP se sustituyen por dobles con la forma exacta
del protocolo real (no se toca la red). Lo que se comprueba es que el mensaje
`sub`/`A` se interpreta bien y que las posiciones salen con su nombre, sus
títulos y su precio.
"""

import json

import pytest

from sources import trade_republic_live as trl, db


@pytest.fixture(autouse=True)
def _sin_emparejar():
    db.set_setting(trl.DEVICE_KEY_SETTING, {})
    yield
    db.set_setting(trl.DEVICE_KEY_SETTING, {})


class FakeWS:
    """Websocket de mentira que habla el protocolo real de Trade Republic."""

    def __init__(self, answers):
        self.answers = answers          # {tipo de sub: payload}
        self.sent = []
        self.queue = ["connected"]

    def send(self, message):
        self.sent.append(message)
        if message.startswith("connect"):
            return
        if message.startswith("unsub"):
            return
        _sub, sub_id, payload = message.split(" ", 2)
        body = json.loads(payload)
        key = body.get("id") or body["type"]
        answer = self.answers.get(key, self.answers.get(body["type"]))
        self.queue.append(f"{sub_id} A {json.dumps(answer)}")

    def recv(self):
        return self.queue.pop(0)

    def close(self):
        pass


def _socket_con(answers, monkeypatch):
    fake = FakeWS(answers)
    monkeypatch.setattr(trl, "login", lambda pin=None: "token-de-sesion")

    class FakeModule:
        @staticmethod
        def create_connection(url, **kwargs):
            return fake

    original_init = trl._Socket.__init__

    def init(self, token, locale="es", timeout=30):
        original_init(self, token, locale=locale, timeout=timeout)
        self._websocket = FakeModule

    monkeypatch.setattr(trl._Socket, "__init__", init)
    return fake


def test_sin_emparejar_es_not_paired():
    assert trl.is_paired() is False
    with pytest.raises(trl.NotPaired):
        trl.login(pin="1234")


def test_exchange_for_prefiere_la_bolsa_de_casa():
    assert trl._exchange_for({"homeExchangeId": "LSX",
                              "exchanges": [{"slice": "LSX"}, {"slice": "TDG"}]}) == "LSX"
    # Sin bolsa de casa declarada, se usa la preferida que sí cotiza.
    assert trl._exchange_for({"exchanges": [{"slice": "TDG"}]}) == "TDG"
    assert trl._exchange_for({}) == "LSX"


def test_ticker_price_usa_el_ultimo_disponible():
    assert trl._ticker_price({"last": {"price": "180.50"}}) == 180.5
    assert trl._ticker_price({"bid": {"price": "12.00"}}) == 12.0
    assert trl._ticker_price({}) is None


def test_fetch_portfolio_lee_posiciones_precio_y_efectivo(monkeypatch):
    _socket_con({
        "compactPortfolio": {"positions": [
            {"instrumentId": "US0378331005", "netSize": "3.000000"},
            {"instrumentId": "IE00BK5BQT80", "netSize": "8.267789"},
        ]},
        "US0378331005": {"name": "Apple Inc.", "homeExchangeId": "LSX",
                         "exchanges": [{"slice": "LSX"}]},
        "IE00BK5BQT80": {"name": "S&P 500 EUR (Acc)", "homeExchangeId": "LSX",
                         "exchanges": [{"slice": "LSX"}]},
        "US0378331005.LSX": {"last": {"price": "180.50"}},
        "IE00BK5BQT80.LSX": {"last": {"price": "129.26"}},
        "cash": [{"currencyId": "EUR", "amount": 250.40},
                 {"currencyId": "USD", "amount": 99.0}],
    }, monkeypatch)

    positions, warnings = trl.fetch_portfolio()
    by_name = {p.name: p for p in positions}
    assert by_name["Apple Inc."].quantity == 3.0
    assert by_name["Apple Inc."].unit_value == 180.5
    assert by_name["Apple Inc."].value == 541.5
    assert by_name["Apple Inc."].extra["isin"] == "US0378331005"
    assert by_name["S&P 500 EUR (Acc)"].value == round(8.267789 * 129.26, 2)
    # El efectivo entra solo en EUR (los 99 USD no se convierten a la ligera).
    assert by_name["Efectivo (cuenta corriente)"].value == 250.40
    assert warnings == []


def test_analyze_devuelve_el_formato_del_parser_de_pdf(monkeypatch):
    _socket_con({
        "compactPortfolio": {"positions": [{"instrumentId": "US0378331005", "netSize": "2"}]},
        "US0378331005": {"name": "Apple Inc.", "homeExchangeId": "LSX",
                         "exchanges": [{"slice": "LSX"}]},
        "US0378331005.LSX": {"last": {"price": "100.00"}},
        "cash": [],
    }, monkeypatch)
    r = trl.analyze()
    assert r["category"] == "Acciones / ETFs"
    assert r["total"] == 200.0
    assert r["currency"] == "EUR"
    assert r["positions"][0]["name"] == "Apple Inc."
    assert r["positions"][0]["quantity"] == 2.0


def test_posicion_sin_precio_avisa_y_no_suma(monkeypatch):
    _socket_con({
        "compactPortfolio": {"positions": [{"instrumentId": "US0378331005", "netSize": "5"}]},
        "US0378331005": {"name": "Apple Inc.", "homeExchangeId": "LSX",
                         "exchanges": [{"slice": "LSX"}]},
        "US0378331005.LSX": {},          # el ticker no trae precio
        "cash": [],
    }, monkeypatch)
    positions, warnings = trl.fetch_portfolio()
    assert positions[0].value == 0.0
    assert any("Sin precio" in w for w in warnings)


def test_error_del_servidor_se_propaga(monkeypatch):
    fake = _socket_con({"compactPortfolio": {}}, monkeypatch)

    def send_error(message):
        fake.sent.append(message)
        if message.startswith(("connect", "unsub")):
            return
        sub_id = message.split(" ")[1]
        fake.queue.append(f'{sub_id} E {{"errors":[{{"errorCode":"AUTHENTICATION"}}]}}')

    fake.send = send_error
    with pytest.raises(trl.TradeRepublicError, match="error"):
        trl.fetch_portfolio()
