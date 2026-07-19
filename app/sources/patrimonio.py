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


def whatsapp_message(s, warnings=None):
    """Construye el mensaje de WhatsApp del resumen de patrimonio.

    Las categorías cuyo dato no es del mes en curso se marcan con su mes de
    origen, y los avisos (p. ej. una fuente que falló al revalorizar) se añaden
    al final: mejor un fallo visible que un número que parece fresco sin serlo.
    """
    lines = [f"💼 *Tu patrimonio* ({s['month']})", "", f"Total: *{eur(s['total'])}*"]
    if s["pct"] is not None:
        arrow = "📈" if s["delta"] >= 0 else "📉"
        sign = "+" if s["delta"] >= 0 else ""
        lines.append(f"{arrow} {sign}{eur(s['delta'])} ({s['pct']:+.1f}%) vs periodo anterior")
    cat_months = s.get("category_months") or {}
    for k, v in sorted(s["categories"].items(), key=lambda x: -x[1]):
        m = cat_months.get(k)
        stale = f" (de {m})" if m and m != s["month"] else ""
        lines.append(f"• {k}: {eur(v)}{stale}")
    if s.get("ganancias") is not None:
        lines.append(f"\n🟢 Ingresos: {eur(s['ganancias'])}   🔴 Gastos: {eur(s.get('gastos') or 0)}")
    for w in warnings or []:
        lines.append(f"\n⚠️ {w}")
    lines.append("\nMi patrimonio · resumen automático")
    return "\n".join(lines)
