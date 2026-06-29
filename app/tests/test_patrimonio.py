"""Dominio del patrimonio: resumen mensual, formato y mensaje de WhatsApp."""

from sources import patrimonio


def test_is_flow():
    assert patrimonio.is_flow("_flow:gastos")
    assert not patrimonio.is_flow("Acciones / ETFs")


def test_month_total_excluye_flujos():
    snap = {"Acciones": 1000.0, "Liquidez (banco)": 500.0,
            "_flow:gastos": 200.0, "_flow:ganancias": 1800.0}
    assert patrimonio.month_total(snap) == 1500.0


def test_summary_vacio():
    assert patrimonio.summary({}) is None
    assert patrimonio.summary(None) is None


def test_summary_un_solo_mes():
    s = patrimonio.summary({"2026-07": {"Acciones": 1000.0, "_flow:gastos": 100.0}})
    assert s["month"] == "2026-07"
    assert s["total"] == 1000.0
    assert s["prev"] is None
    assert s["delta"] is None
    assert s["pct"] is None
    assert s["gastos"] == 100.0
    assert s["categories"] == {"Acciones": 1000.0}


def test_summary_variacion_entre_meses():
    snaps = {
        "2026-06": {"Acciones": 1000.0},
        "2026-07": {"Acciones": 1100.0, "Liquidez": 400.0,
                    "_flow:gastos": 300.0, "_flow:ganancias": 1800.0},
    }
    s = patrimonio.summary(snaps)
    assert s["total"] == 1500.0
    assert s["prev"] == 1000.0
    assert s["delta"] == 500.0
    assert s["pct"] == 50.0
    assert s["ganancias"] == 1800.0


def test_eur_formato_espanol():
    assert patrimonio.eur(1234.56) == "1.234,56 €"
    assert patrimonio.eur(0) == "0,00 €"
    assert patrimonio.eur(1000000) == "1.000.000,00 €"


def test_whatsapp_message_incluye_total_y_flecha():
    snaps = {
        "2026-06": {"Acciones": 1000.0},
        "2026-07": {"Acciones": 1500.0, "_flow:gastos": 200.0, "_flow:ganancias": 1800.0},
    }
    msg = patrimonio.whatsapp_message(patrimonio.summary(snaps))
    assert "Tu patrimonio" in msg
    assert "1.500,00 €" in msg
    assert "📈" in msg                 # subió
    assert "Acciones" in msg


def test_whatsapp_message_baja():
    snaps = {"2026-06": {"Acciones": 1000.0}, "2026-07": {"Acciones": 800.0}}
    msg = patrimonio.whatsapp_message(patrimonio.summary(snaps))
    assert "📉" in msg
