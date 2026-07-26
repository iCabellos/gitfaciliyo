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


def test_summary_arrastra_ultimo_valor_de_cada_categoria():
    # El banco no tiene dato de julio: se usa su último valor (junio) y se
    # recuerda de qué mes viene, en vez de hacer desaparecer la categoría.
    snaps = {
        "2026-06": {"Liquidez (banco)": 500.0, "Skins CS:GO": 100.0},
        "2026-07": {"Skins CS:GO": 120.0},
    }
    s = patrimonio.summary(snaps)
    assert s["total"] == 620.0
    assert s["categories"] == {"Liquidez (banco)": 500.0, "Skins CS:GO": 120.0}
    assert s["category_months"] == {"Liquidez (banco)": "2026-06",
                                    "Skins CS:GO": "2026-07"}
    assert s["prev"] == 600.0
    assert s["delta"] == 20.0


def test_whatsapp_message_marca_datos_antiguos():
    snaps = {
        "2026-06": {"Liquidez (banco)": 500.0},
        "2026-07": {"Skins CS:GO": 120.0},
    }
    msg = patrimonio.whatsapp_message(patrimonio.summary(snaps))
    assert "Liquidez (banco): 500,00 € (de 2026-06)" in msg
    assert "Skins CS:GO: 120,00 €\n" in msg     # dato fresco, sin marca


def test_whatsapp_message_incluye_avisos():
    snaps = {"2026-07": {"Skins CS:GO": 120.0}}
    msg = patrimonio.whatsapp_message(patrimonio.summary(snaps),
                                      warnings=["Cartas Magic no se pudo revalorizar: Moxfield caído"])
    assert "⚠️ Cartas Magic no se pudo revalorizar: Moxfield caído" in msg


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


# ---- movimientos de precio dentro del mensaje ----------------------------
MOVERS = [
    {"key": "skin:AK-47 | Redline (Field-Tested)", "kind": "skin",
     "name": "AK-47 | Redline (Field-Tested)", "pct": -12.0, "delta": -4.8,
     "price_from": 40.0, "price_to": 35.2, "direction": "down", "days": 7,
     "date_from": "2026-07-19", "date_to": "2026-07-26"},
    {"key": "card:Sol Ring", "kind": "card", "name": "Sol Ring", "pct": 10.0,
     "delta": 0.3, "price_from": 3.0, "price_to": 3.3, "direction": "up", "days": 7,
     "date_from": "2026-07-19", "date_to": "2026-07-26"},
]


def test_movers_lines_muestra_precio_anterior_y_actual():
    lines = "\n".join(patrimonio.movers_lines(MOVERS, threshold=5))
    assert "Movimientos ≥5% esta semana" in lines
    assert "(últimos 7 días)" in lines
    assert "🔫 AK-47 | Redline (Field-Tested)" in lines
    assert "🔻 40,00 € → 35,20 € (-12,0%)" in lines
    assert "🃏 Sol Ring" in lines
    assert "🔺 3,00 € → 3,30 € (+10,0%)" in lines


def test_movers_lines_sin_movimientos_lo_dice():
    lines = "\n".join(patrimonio.movers_lines([], threshold=5))
    assert "Ninguna carta ni skin se movió más de un 5%" in lines


def test_movers_lines_resume_cuando_hay_muchos():
    muchos = [dict(MOVERS[1], name=f"Carta {i}") for i in range(20)]
    lines = "\n".join(patrimonio.movers_lines(muchos, threshold=5, limit=12))
    assert "Carta 11" in lines
    assert "Carta 12" not in lines
    assert "…y 8 más" in lines


def test_whatsapp_message_incluye_los_movimientos():
    snaps = {"2026-07": {"Skins CS:GO": 120.0}}
    msg = patrimonio.whatsapp_message(patrimonio.summary(snaps), movers=MOVERS, threshold=5)
    assert "Movimientos ≥5% esta semana" in msg
    assert "40,00 € → 35,20 €" in msg
    assert msg.rstrip().endswith("Mi patrimonio · resumen automático")


def test_whatsapp_message_sin_movers_no_pone_la_seccion():
    snaps = {"2026-07": {"Skins CS:GO": 120.0}}
    assert "Movimientos" not in patrimonio.whatsapp_message(patrimonio.summary(snaps))


def test_whatsapp_message_resume_las_acciones_registradas():
    snaps = {"2026-07": {"Acciones / ETFs": 1500.0}}
    holdings = [{"name": "Apple", "quantity": 3.0}, {"name": "S&P 500", "quantity": 8.267789}]
    msg = patrimonio.whatsapp_message(patrimonio.summary(snaps), holdings=holdings)
    assert "📄 Acciones/ETFs: 2 valores · 11,2678 títulos" in msg


def test_qty_formato_espanol():
    assert patrimonio.qty(3) == "3"
    assert patrimonio.qty(1234) == "1.234"
    assert patrimonio.qty(8.267789) == "8,2678"
    assert patrimonio.qty(10.5) == "10,5"
