"""Agrupación de inventario de Steam y extracción de metadatos de la skin.

Trabaja sobre estructuras reales de `descriptions`/`assets` tal y como las
devuelve la API pública de Steam; sin red (se prueban las funciones puras).
"""

from sources import steam


def _inv():
    """Inventario mínimo con dos ejemplares de una misma skin StatTrak."""
    return {
        "descriptions": [{
            "classid": "310777",
            "instanceid": "302028390",
            "market_hash_name": "StatTrak™ AK-47 | Redline (Field-Tested)",
            "marketable": 1,
            "type": "StatTrak™ Classified Rifle",
            "icon_url": "abc123",
            "name_color": "D2D2D2",
            "tags": [
                {"category": "Weapon", "localized_tag_name": "AK-47"},
                {"category": "Type", "localized_tag_name": "Rifle"},
                {"category": "Quality", "internal_name": "strange",
                 "localized_tag_name": "StatTrak™"},
                {"category": "Rarity", "internal_name": "Rarity_Legendary_Weapon",
                 "localized_tag_name": "Classified", "color": "d32ce6"},
                {"category": "Exterior", "localized_tag_name": "Field-Tested"},
            ],
        }],
        "assets": [
            {"classid": "310777", "instanceid": "302028390", "amount": "1"},
            {"classid": "310777", "instanceid": "302028390", "amount": "1"},
        ],
    }


def test_group_items_agrupa_y_cuenta():
    items = steam._group_items(_inv())
    name = "StatTrak™ AK-47 | Redline (Field-Tested)"
    assert name in items
    assert items[name]["count"] == 2
    assert items[name]["marketable"] is True
    assert items[name]["icon"].endswith("abc123")


def test_group_items_extrae_metadatos_reales():
    items = steam._group_items(_inv())
    meta = items["StatTrak™ AK-47 | Redline (Field-Tested)"]
    assert meta["rarity"] == "Classified"
    assert meta["rarity_color"] == "#d32ce6"
    assert meta["exterior"] == "Field-Tested"
    assert meta["weapon"] == "AK-47"
    assert meta["quality"] == "StatTrak™"
    assert meta["name_color"] == "#D2D2D2"


def test_quality_normal_no_se_incluye():
    inv = _inv()
    for t in inv["descriptions"][0]["tags"]:
        if t["category"] == "Quality":
            t["internal_name"] = "normal"
            t["localized_tag_name"] = "Normal"
    meta = steam._group_items(inv)["StatTrak™ AK-47 | Redline (Field-Tested)"]
    assert "quality" not in meta


def test_skin_meta_omite_lo_que_no_viene():
    # Un item sin tags ni name_color no debe inventar campos.
    meta = steam._skin_meta({"market_hash_name": "Sticker | X"})
    assert meta == {}


# ---- descarga del inventario --------------------------------------------
def test_no_se_pide_mas_del_tope_de_steam(monkeypatch):
    """Pedir más de 2000 no devuelve más: Steam rechaza la petición entera.

    Pedíamos 5000 y siempre fallaba; encima el error se etiquetaba como
    «inventario privado», que es un diagnóstico falso.
    """
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        return 200, {"assets": [], "descriptions": [], "more_items": 0}

    monkeypatch.setattr(steam.http, "get_json", fake_get)
    steam.fetch_inventory("76561190000000000")
    assert steam.PAGE_SIZE <= 2000
    assert f"count={steam.PAGE_SIZE}" in urls[0]


def test_fetch_inventory_encadena_paginas(monkeypatch):
    """Un inventario grande llega en varias páginas: hay que seguirlas todas."""
    paginas = [
        (200, {"assets": [{"classid": "1", "instanceid": "0", "amount": "1"}],
               "descriptions": [{"classid": "1", "instanceid": "0",
                                 "market_hash_name": "Skin A", "marketable": 1}],
               "more_items": 1, "last_assetid": "AAA"}),
        (200, {"assets": [{"classid": "2", "instanceid": "0", "amount": "1"}],
               "descriptions": [{"classid": "2", "instanceid": "0",
                                 "market_hash_name": "Skin B", "marketable": 1},
                                # descripción repetida: no debe duplicarse
                                {"classid": "1", "instanceid": "0",
                                 "market_hash_name": "Skin A", "marketable": 1}],
               "more_items": 0}),
    ]
    urls = []

    def fake_get(url, **kwargs):
        urls.append(url)
        return paginas[len(urls) - 1]

    monkeypatch.setattr(steam.http, "get_json", fake_get)
    monkeypatch.setattr(steam.time, "sleep", lambda s: None)
    inv = steam.fetch_inventory("76561190000000000")
    assert len(urls) == 2
    assert "start_assetid=AAA" in urls[1]
    assert len(inv["assets"]) == 2
    assert len(inv["descriptions"]) == 2          # sin duplicar
    assert set(steam._group_items(inv)) == {"Skin A", "Skin B"}


def test_errores_de_inventario_dicen_que_pasa_de_verdad(monkeypatch):
    """Cada código HTTP se arregla de forma distinta: el mensaje debe distinguirlos."""
    for status, esperado in [(403, "privado"), (429, "limitado"),
                             (404, "no encuentra"), (400, "mal formado")]:
        monkeypatch.setattr(steam.http, "get_json",
                            lambda url, s=status, **k: (s, None))
        try:
            steam.fetch_inventory("76561190000000000")
        except RuntimeError as exc:
            assert esperado in str(exc), f"HTTP {status}: {exc}"
        else:
            raise AssertionError(f"HTTP {status} debería fallar")


# ---- precios: ritmo y reintentos ----------------------------------------
def test_price_reintenta_ante_429_y_luego_se_rinde(monkeypatch):
    llamadas = []

    def siempre_429(url, **kwargs):
        llamadas.append(url)
        return 429, None

    monkeypatch.setattr(steam.http, "get_json", siempre_429)
    monkeypatch.setattr(steam, "_wait_turn", lambda: None)
    monkeypatch.setattr(steam.time, "sleep", lambda s: None)
    try:
        steam._price("AK-47 | Redline (Field-Tested)", 3, {})
    except steam._RateLimited as exc:
        assert str(exc), "la excepción debe llevar mensaje, no imprimirse vacía"
    else:
        raise AssertionError("un 429 persistente debe acabar en _RateLimited")
    assert len(llamadas) == steam.RATE_LIMIT_RETRIES + 1


def test_price_usa_la_cache_y_no_repite_peticion(monkeypatch):
    llamadas = []
    monkeypatch.setattr(steam.http, "get_json", lambda url, **k: (
        llamadas.append(url) or (200, {"success": True, "median_price": "37,27€"})))
    monkeypatch.setattr(steam, "_wait_turn", lambda: None)
    cache = {}
    valor, red = steam._price("AK-47 | Redline (Field-Tested)", 3, cache)
    assert valor == 37.27 and red is True
    valor2, red2 = steam._price("AK-47 | Redline (Field-Tested)", 3, cache)
    assert valor2 == 37.27 and red2 is False      # segunda vez, de caché
    assert len(llamadas) == 1
