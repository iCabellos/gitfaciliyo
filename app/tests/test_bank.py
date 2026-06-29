"""Banco: categorización, gasto neto y enlace de bizums (reglas de negocio)."""

from sources import bank


def test_categorize_reglas():
    assert bank.categorize("COMPRA MERCADONA PALMA", -42.0) == ("Supermercado", "expense")
    assert bank.categorize("NOMINA EMPRESA SL", 1800.0) == ("Nómina", "income")
    assert bank.categorize("TRASPASO A NEXO", -100.0) == ("Inversión (Nexo)", "investment")
    assert bank.categorize("BIZUM RECIBIDO DE ANA", 10.0) == ("Bizum recibido", "bizum_in")


def test_categorize_por_defecto_segun_signo():
    assert bank.categorize("algo raro", -5.0) == ("Otros gastos", "expense")
    assert bank.categorize("algo raro", 5.0) == ("Otros ingresos", "income")


def _raw(*rows):
    """rows: (concept, 'dd/mm/yyyy', amount)."""
    return [{"concept": c, "date": d, "amount": a, "balance": 1000.0} for c, d, a in rows]


def test_inversion_no_cuenta_como_gasto():
    data = bank.analyze_raw(_raw(
        ("COMPRA MERCADONA", "05/07/2026", -50.0),
        ("TRASPASO A NEXO", "06/07/2026", -200.0),
    ), balance=800.0)
    agg = data["aggregates"]
    assert agg["gastos"] == 50.0          # la inversión NO suma a gastos
    assert agg["inversion"] == 200.0
    assert agg["liquidez"] == 800.0
    assert agg["month"] == "2026-07"


def test_bizum_devolucion_reduce_gasto_neto():
    # Cena de 30 € con un bizum de 10 € el mismo día -> gasto neto 20 €.
    data = bank.analyze_raw(_raw(
        ("RESTAURANTE LA CENA", "10/07/2026", -30.0),
        ("BIZUM RECIBIDO DE LUIS", "10/07/2026", 10.0),
    ), balance=500.0)
    bizum = next(t for t in data["transactions"] if t["kind"] == "bizum_in")
    assert bizum["suggested_link"] is not None      # se liga a la cena
    assert data["aggregates"]["gastos"] == 20.0     # 30 - 10


def test_bizum_recurrente_se_marca_como_ingreso():
    # Tres bizums del mismo importe -> ingreso recurrente, no devolución.
    rows = _raw(
        ("RESTAURANTE", "01/07/2026", -100.0),
        ("BIZUM RECIBIDO ALQUILER", "02/07/2026", 25.0),
        ("BIZUM RECIBIDO ALQUILER", "12/07/2026", 25.0),
        ("BIZUM RECIBIDO ALQUILER", "22/07/2026", 25.0),
    )
    data = bank.analyze_raw(rows, balance=None)
    bizums = [t for t in data["transactions"] if t["kind"] == "bizum_in"]
    assert all(b["recurring_income"] for b in bizums)
    assert all(b["suggested_link"] is None for b in bizums)
    # 3 × 25 € entran como ingreso; el gasto bruto (100) no se reduce.
    assert data["aggregates"]["ganancias"] == 75.0
    assert data["aggregates"]["gastos"] == 100.0


def test_aggregates_sin_movimientos():
    data = bank.analyze_raw([], balance=None)
    assert data["month"] is None
    assert data["aggregates"]["gastos"] == 0.0
