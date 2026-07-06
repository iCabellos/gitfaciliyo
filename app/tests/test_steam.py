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
