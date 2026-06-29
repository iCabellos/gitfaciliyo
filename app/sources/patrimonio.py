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


def summary(snapshots):
    """Resumen del último mes: total, total previo, variación y flujos.

    snapshots: { 'YYYY-MM': { categoria|_flow:x : valor } }. None si no hay datos.
    """
    months = sorted(snapshots or {})
    if not months:
        return None
    last = months[-1]
    cur = month_total(snapshots[last])
    prev = month_total(snapshots[months[-2]]) if len(months) > 1 else None
    delta = round(cur - prev, 2) if prev is not None else None
    pct = round((cur - prev) / prev * 100, 1) if prev else None
    flows = snapshots[last]
    return {
        "month": last, "total": cur, "prev": prev, "delta": delta, "pct": pct,
        "gastos": flows.get("_flow:gastos"), "ganancias": flows.get("_flow:ganancias"),
        "categories": {k: v for k, v in flows.items() if not is_flow(k)},
    }


def eur(n):
    """Formatea un número como '1.234,56 €' (formato español)."""
    return f"{n:,.2f} €".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def whatsapp_message(s):
    """Construye el mensaje de WhatsApp del resumen de patrimonio."""
    lines = [f"💼 *Tu patrimonio* ({s['month']})", "", f"Total: *{eur(s['total'])}*"]
    if s["pct"] is not None:
        arrow = "📈" if s["delta"] >= 0 else "📉"
        sign = "+" if s["delta"] >= 0 else ""
        lines.append(f"{arrow} {sign}{eur(s['delta'])} ({s['pct']:+.1f}%) vs periodo anterior")
    for k, v in sorted(s["categories"].items(), key=lambda x: -x[1]):
        lines.append(f"• {k}: {eur(v)}")
    if s.get("ganancias") is not None:
        lines.append(f"\n🟢 Ingresos: {eur(s['ganancias'])}   🔴 Gastos: {eur(s.get('gastos') or 0)}")
    lines.append("\nMi patrimonio · resumen automático")
    return "\n".join(lines)
