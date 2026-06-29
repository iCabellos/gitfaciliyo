"""Utilidades compartidas: parseo de importes y extracción de mes."""

from sources.common import parse_money, to_month


def test_parse_money_europeo():
    assert parse_money("1.234,56 €") == 1234.56
    assert parse_money("0,99") == 0.99
    assert parse_money("-45,00€") == -45.0


def test_parse_money_americano():
    assert parse_money("1,234.56") == 1234.56
    assert parse_money("$1,000.00") == 1000.0


def test_parse_money_solo_coma_miles_vs_decimal():
    # Con coma como separador de miles (sin decimales) -> entero.
    assert parse_money("1,000") == 1000.0
    assert parse_money("12,50") == 12.5            # coma decimal


def test_parse_money_parentesis_negativo():
    assert parse_money("(30,00)") == -30.0


def test_parse_money_invalido():
    assert parse_money("") is None
    assert parse_money(None) is None
    assert parse_money("n/a") is None


def test_to_month():
    assert to_month("Movimiento del 05/07/2026") == "2026-07"
    assert to_month("fecha 31.12.2025 ref") == "2025-12"
    assert to_month("sin fecha") is None
