"""
Sincronización automática del patrimonio (sin adjuntar PDFs).

Orquesta varios *conectores* que consumen APIs externas y actualizan los
snapshots mensuales en la base de datos. Pensado para una tarea SEMANAL:

  * imaginBank -> vía Wealth Reader (agregador PSD2). Trae saldo y movimientos y
    los clasifica igual que el PDF del banco (liquidez + flujos gastos/ingresos).
  * Trade Republic -> vía su API no oficial (sesión persistida). Trae la cartera.

Cada conector está aislado: si uno no está configurado o falla, se registra el
motivo y el resto de la sincronización continúa. La configuración (tokens de
Wealth Reader y la sesión de Trade Republic) se guarda en la tabla `settings`.
"""

import datetime
import os

from . import db, ingest, wealthreader

WR_CONNECTIONS_KEY = "wr_connections"   # { nombre: {code, token, saved} }
TR_SESSION_KEY = "tr_session"           # { cookies: {...}, saved }


def _this_month():
    return datetime.date.today().strftime("%Y-%m")


# --------------------------------------------------------------------------
# Configuración persistida
# --------------------------------------------------------------------------
def get_connections():
    """Conexiones de Wealth Reader guardadas (sin exponer los tokens)."""
    conns = db.get_setting(WR_CONNECTIONS_KEY, {}) or {}
    return {name: {"code": c.get("code"), "saved": c.get("saved")} for name, c in conns.items()}


def save_wr_connection(name, code, token):
    if not name or not code or not token:
        raise ValueError("Faltan 'name', 'code' (banco) y 'token' del widget de Wealth Reader.")
    conns = db.get_setting(WR_CONNECTIONS_KEY, {}) or {}
    conns[name] = {"code": code, "token": token,
                   "saved": datetime.datetime.utcnow().isoformat(timespec="seconds")}
    db.set_setting(WR_CONNECTIONS_KEY, conns)
    return get_connections()


def save_tr_session(cookies):
    db.set_setting(TR_SESSION_KEY, {"cookies": cookies,
                   "saved": datetime.datetime.utcnow().isoformat(timespec="seconds")})


def status():
    """Estado de los conectores (para pintar en la web o depurar)."""
    conns = db.get_setting(WR_CONNECTIONS_KEY, {}) or {}
    tr = db.get_setting(TR_SESSION_KEY, {}) or {}
    return {
        "wealthreader_api_key": bool(os.environ.get("WEALTHREADER_API_KEY", "").strip()),
        "connections": get_connections(),
        "trade_republic_session": bool(tr.get("cookies")),
        "trade_republic_saved": tr.get("saved"),
    }


# --------------------------------------------------------------------------
# Conectores
# --------------------------------------------------------------------------
def sync_wealthreader():
    """Sincroniza todas las conexiones bancarias de Wealth Reader (p. ej. imagin)."""
    conns = db.get_setting(WR_CONNECTIONS_KEY, {}) or {}
    if not conns:
        return []
    results = []
    month = _this_month()
    for name, c in conns.items():
        try:
            data = wealthreader.analyze(c["code"], c["token"])
            agg = data.get("aggregates") or {}
            agg["month"] = agg.get("month") or month
            ingest.persist_bank_aggregates(agg)
            results.append({"source": name, "ok": True, "month": agg["month"],
                            "liquidez": agg.get("liquidez"), "gastos": agg.get("gastos"),
                            "ganancias": agg.get("ganancias")})
        except Exception as exc:  # noqa: BLE001
            results.append({"source": name, "ok": False, "error": str(exc)})
    return results


def sync_trade_republic():
    """Sincroniza Trade Republic con la sesión guardada (API no oficial)."""
    stored = db.get_setting(TR_SESSION_KEY, {}) or {}
    cookies = stored.get("cookies")
    if not cookies:
        return None
    from . import traderepublic_api as tr
    try:
        try:
            cookies = tr.refresh_session(cookies)
            save_tr_session(cookies)
        except Exception:  # noqa: BLE001
            pass  # si el refresco falla, probamos con la sesión tal cual
        data = tr.portfolio(cookies)
        month = _this_month()
        db.set_snapshot(month, data["category"], data["total"])
        return {"source": "trade_republic", "ok": True, "month": month,
                "total": data["total"], "positions": len(data["positions"])}
    except Exception as exc:  # noqa: BLE001
        return {"source": "trade_republic", "ok": False, "error": str(exc)}


def run_all():
    """Ejecuta todos los conectores configurados. Nunca lanza: agrega resultados."""
    results = list(sync_wealthreader())
    tr = sync_trade_republic()
    if tr is not None:
        results.append(tr)
    ok = [r for r in results if r.get("ok")]
    return {"ran": len(results), "ok": len(ok), "results": results}
