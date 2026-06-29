"""Trade Republic: parseo del CSV normalizado (cabeceras, delimitadores)."""

from sources import trade_republic as tr


def test_parse_csv_normalizado():
    text = ("name,isin,quantity,price,value\n"
            "Apple,US0378331005,3,180.50,541.50\n"
            "Vanguard FTSE All-World,IE00BK5BQT80,12,118.20,1418.40\n")
    positions, warnings = tr._parse_csv(text)
    assert len(positions) == 2
    assert positions[0].name == "Apple"
    assert positions[0].value == 541.50
    assert round(sum(p.value for p in positions), 2) == 1959.90


def test_parse_csv_delimitador_punto_y_coma_y_cabeceras_es():
    text = ("nombre;isin;cantidad;precio;valor\n"
            "Iberdrola;ES0144580Y14;100;11,50;1.150,00\n")
    positions, warnings = tr._parse_csv(text)
    assert len(positions) == 1
    assert positions[0].name == "Iberdrola"
    assert positions[0].value == 1150.0


def test_parse_csv_calcula_valor_desde_precio():
    text = "name,quantity,price\nTest,2,10.00\n"
    positions, _ = tr._parse_csv(text)
    assert positions[0].value == 20.0


def test_parse_csv_cabeceras_no_reconocidas():
    positions, warnings = tr._parse_csv("foo,bar\n1,2\n")
    assert positions == []
    assert warnings
