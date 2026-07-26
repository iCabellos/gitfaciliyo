"""
Dominio del patrimonio: cálculo del resumen mensual y su mensaje de WhatsApp.

Separa la lógica de negocio (a partir de los snapshots) de la capa web (app.py).
Las claves con prefijo '_flow:' (gastos/ganancias/inversión) son flujos del mes,
no patrimonio, y no suman al total.
"""

FLOW_PREFIX = "_flow:"


def is_flow(key):
    return key.startswith(FLOW_PREFIX)


def month_total(month_snapshot):
    """Suma de las categorías de patrimonio de un mes (excluye flujos)."""
    return round(sum(v for k, v in month_snapshot.items() if not is_flow(k)), 2)


def latest_categories(snapshots):
    """Último valor conocido de cada categoría: { cat: (valor, mes de origen) }.

    Cada fuente se actualiza a su ritmo (skins/cartas en vivo, banco/TR al subir
    el extracto); el patrimonio actual es el dato más reciente de cada una.
    """
    view = {}
    for month in sorted(snapshots or {}):
        for k, v in snapshots[month].items():
            if not is_flow(k):
                view[k] = (v, month)
    return view


def summary(snapshots):
    """Resumen actual: total (último valor de cada categoría), variación y flujos.

    snapshots: { 'YYYY-MM': { categoria|_flow:x : valor } }. None si no hay datos.
    Las categorías sin dato del último mes conservan su valor previo, y su mes de
    origen queda en 'category_months' para poder señalarlas como antiguas.
    """
    months = sorted(snapshots or {})
    if not months:
        return None
    last = months[-1]
    view = latest_categories(snapshots)
    cur = round(sum(v for v, _ in view.values()), 2)
    prev_view = latest_categories({m: snapshots[m] for m in months[:-1]})
    prev = round(sum(v for v, _ in prev_view.values()), 2) if prev_view else None
    delta = round(cur - prev, 2) if prev is not None else None
    pct = round((cur - prev) / prev * 100, 1) if prev else None
    flows = snapshots[last]
    return {
        "month": last, "total": cur, "prev": prev, "delta": delta, "pct": pct,
        "gastos": flows.get("_flow:gastos"), "ganancias": flows.get("_flow:ganancias"),
        "categories": {k: v for k, (v, _) in view.items()},
        "category_months": {k: m for k, (_, m) in view.items()},
    }


def eur(n):
    """Formatea un número como '1.234,56 €' (formato español)."""
    return f"{n:,.2f} €".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def qty(n):
    """Cantidad de títulos: sin decimales si es entera, hasta 4 si es fraccionada."""
    n = round(float(n), 4)
    text = f"{n:,.0f}" if n == int(n) else f"{n:,.4f}".rstrip("0").rstrip(".")
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pct(n):
    """Porcentaje con signo y coma decimal: '+10,0%' / '-12,0%'."""
    return f"{n:+.1f}%".replace(".", ",")


# Cuántos movimientos caben en el mensaje antes de resumir el resto.
MOVERS_LIMIT = 12


def movers_lines(movers, threshold=5.0, limit=MOVERS_LIMIT):
    """Bloque de movimientos de precio de la semana (subidas Y bajadas).

    Cada línea lleva el elemento, su precio ANTERIOR y el ACTUAL, y el
    porcentaje. Lista vacía -> se dice que nada superó el umbral (que también
    es información: confirma que el seguimiento está vivo).
    """
    header = f"📊 *Movimientos ≥{threshold:g}% esta semana*"
    if not movers:
        return [f"{header}\nNinguna carta ni skin se movió más de un {threshold:g}%."]
    icons = {"card": "🃏", "skin": "🔫"}
    days = movers[0].get("days")
    span = f" (últimos {days} días)" if days else ""
    lines = [header + span]
    for m in movers[:limit]:
        arrow = "🔺" if m["direction"] == "up" else "🔻"
        icon = icons.get(m["kind"], "•")
        lines.append(f"{icon} {m['name']}\n"
                     f"   {arrow} {eur(m['price_from'])} → {eur(m['price_to'])} "
                     f"({pct(m['pct'])})")
    if len(movers) > limit:
        lines.append(f"…y {len(movers) - limit} más (consúltalos en la web).")
    return lines


def whatsapp_message(s, warnings=None, movers=None, threshold=5.0, holdings=None):
    """Construye el mensaje de WhatsApp del resumen de patrimonio.

    Las categorías cuyo dato no es del mes en curso se marcan con su mes de
    origen, y los avisos (p. ej. una fuente que falló al revalorizar o que no
    está conectada) se añaden al final: mejor un fallo visible que un número que
    parece fresco sin serlo.

    `movers` (de `prices.movers`) añade el detalle de qué carta/skin se ha
    movido y entre qué precios; con None no se incluye la sección.
    `holdings` son las posiciones guardadas (acciones/ETFs) para resumir cuántos
    títulos hay registrados.
    """
    lines = [f"💼 *Tu patrimonio* ({s['month']})", "", f"Total: *{eur(s['total'])}*"]
    if s["pct"] is not None:
        arrow = "📈" if s["delta"] >= 0 else "📉"
        sign = "+" if s["delta"] >= 0 else ""
        lines.append(f"{arrow} {sign}{eur(s['delta'])} ({pct(s['pct'])}) vs periodo anterior")
    cat_months = s.get("category_months") or {}
    for k, v in sorted(s["categories"].items(), key=lambda x: -x[1]):
        m = cat_months.get(k)
        stale = f" (de {m})" if m and m != s["month"] else ""
        lines.append(f"• {k}: {eur(v)}{stale}")
    if s.get("ganancias") is not None:
        lines.append(f"\n🟢 Ingresos: {eur(s['ganancias'])}   🔴 Gastos: {eur(s.get('gastos') or 0)}")
    if holdings:
        titles = sum(h.get("quantity") or 0 for h in holdings)
        lines.append(f"\n📄 Acciones/ETFs: {len(holdings)} valores · "
                     f"{qty(titles)} títulos")
    if movers is not None:
        lines.append("")
        lines.extend(movers_lines(movers, threshold))
    for w in warnings or []:
        lines.append(f"\n⚠️ {w}")
    lines.append("\nMi patrimonio · resumen automático")
    return "\n".join(lines)
