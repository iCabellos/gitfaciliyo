"""
Histórico de TODO el patrimonio, día a día y semana a semana.

Un único sitio por el que pasa todo lo que tiene precio, con dos almacenes que
guardan EXACTAMENTE lo mismo:

  * `data/price_history.json` — lo escribe el cron de GitHub Actions y queda
    commiteado en el repo (histórico versionado, sin servidor).
  * tabla `price_history` de la base de datos — lo que lee la web desplegada.

Cada registro es `{'YYYY-MM-DD': {clave: valor}}`, y la clave lleva delante el
tipo de lo que se sigue, de modo que en la MISMA serie conviven los artículos
sueltos y el patrimonio agregado:

    total:Patrimonio          9615.87   <- patrimonio completo
    cat:Liquidez (banco)      6200.78   <- una categoría entera
    stock:Apple Inc.            180.50  <- precio por título
    card:Sol Ring                 3.85  <- precio por carta
    skin:AK-47 | Redline (FT)    37.50  <- precio por skin

Sobre ese histórico se calculan dos cosas:

  * `weekly_series()` — la serie SEMANAL de cada clave (el último valor
    observado de cada semana ISO), que es lo que se consulta en la web.
  * `movers()` — lo que se ha movido al menos un % dado (por defecto 5) en la
    última semana, en cualquiera de los dos sentidos, con su valor anterior y
    el actual. Vale igual para una carta que para el patrimonio total.

Si no hay histórico no se inventa nada: las funciones devuelven listas vacías y
quien llama debe decirlo en voz alta.
"""

import datetime
import json
import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("PATRIMONIO_DATA_DIR") or os.path.join(_HERE, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "price_history.json")

THRESHOLD = float(os.environ.get("ALERT_THRESHOLD", "5"))
WINDOW_DAYS = 7

TOTAL_KEY = "total:Patrimonio"
# Artículos sueltos (precio por unidad) frente a agregados del patrimonio.
ITEM_KINDS = ("stock", "card", "skin")
PORTFOLIO_KINDS = ("total", "cat")

KIND_ICON = {"total": "💼", "cat": "📦", "stock": "📄", "card": "🃏", "skin": "🔫"}
KIND_LABEL = {"total": "Patrimonio", "cat": "Categoría", "stock": "Acción / ETF",
              "card": "Carta", "skin": "Skin"}
# Orden de lectura: primero el patrimonio, luego sus categorías y después los
# artículos sueltos. Entre artículos NO se separa por tipo: lo que importa es
# cuánto se ha movido, venga de una carta, de una skin o de una acción.
_SORT_RANK = {"total": 0, "cat": 1}


def split_key(key):
    """'card:Sol Ring' -> ('card', 'Sol Ring'). Sin prefijo -> ('', clave)."""
    kind, sep, name = str(key).partition(":")
    return (kind, name) if sep else ("", key)


def _kind_rank(kind):
    return _SORT_RANK.get(kind, 2)


# ---------------------------------------------------------------------------
# Almacenamiento
# ---------------------------------------------------------------------------
def read_file_history():
    """Histórico guardado en el fichero del repo (vacío si aún no hay ninguno)."""
    try:
        with open(HISTORY_FILE) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_file_history(history):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False, sort_keys=True)


def record(day, day_prices):
    """Guarda los valores de un día en el fichero y en la base de datos.

    Los valores del día se FUSIONAN con lo que ya hubiera: el cron de precios y
    el registro del patrimonio escriben claves distintas y pueden caer el mismo
    día, así que uno no debe borrar lo del otro.

    Devuelve (guardados_en_fichero, guardados_en_db). Un fallo de base de datos
    no debe tirar el cron (el fichero es el histórico canónico del repo), pero
    se avisa por consola para que sea visible.
    """
    if not day_prices:
        return 0, 0
    history = read_file_history()
    history.setdefault(day, {}).update(day_prices)
    write_file_history(history)
    try:
        from . import db
        db.set_prices(day, day_prices)
        return len(day_prices), len(day_prices)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! No pude guardar los valores en la base de datos: {exc}")
        return len(day_prices), 0


# ---------------------------------------------------------------------------
# El patrimonio entero como una serie más
# ---------------------------------------------------------------------------
def portfolio_points(snapshots, holdings=None):
    """Punto del patrimonio de hoy: total, cada categoría y cada acción/ETF.

    `snapshots` es el histórico mensual ({mes: {categoría: valor}}) y `holdings`
    el registro de posiciones. Se usa el último valor conocido de cada categoría
    —igual que hace el resumen—, de modo que la serie semanal del patrimonio
    refleja lo mismo que el mensaje de WhatsApp.
    """
    from .patrimonio import latest_categories

    points = {}
    view = latest_categories(snapshots or {})
    for category, (value, _month) in view.items():
        points[f"cat:{category}"] = round(float(value), 2)
    if view:
        points[TOTAL_KEY] = round(sum(v for v, _ in view.values()), 2)
    for holding in holdings or []:
        name = (holding.get("name") or "").strip()
        unit = holding.get("unit_value")
        if name and unit:
            points[f"stock:{name}"] = round(float(unit), 2)
    return points


def record_portfolio(day=None, snapshots=None, holdings=None):
    """Registra el punto de hoy de TODO el patrimonio en el mismo histórico.

    Sin datos que registrar no escribe nada (y lo dice devolviendo 0): un día
    en blanco falsearía la serie semanal.
    """
    from . import db

    day = day or datetime.date.today().isoformat()
    if snapshots is None:
        snapshots = db.get_snapshots()
    if holdings is None:
        months = db.holdings_months()
        holdings = db.get_holdings(month=months[0]) if months else []
    points = portfolio_points(snapshots, holdings)
    if not points:
        return 0
    record(day, points)
    return len(points)


def history(days=None):
    """Histórico combinado de base de datos y fichero.

    Ambos almacenes contienen el mismo dato real; se fusionan porque el cron
    escribe el fichero y la web lee la base de datos, y cada uno puede llevar
    algún día de ventaja al otro. `days` acota la ventana consultada.
    """
    since = None
    if days:
        since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    merged = {}
    try:
        from . import db
        merged.update(db.get_price_history(since=since))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! No pude leer el histórico de precios de la base de datos: {exc}")
    for day, prices in read_file_history().items():
        if since and day < since:
            continue
        merged.setdefault(day, {}).update(prices)
    return merged


# ---------------------------------------------------------------------------
# Serie semanal
# ---------------------------------------------------------------------------
def _week_of(day):
    y, w, _ = datetime.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def weekly_series(hist):
    """Serie semanal por elemento: el ÚLTIMO precio observado de cada semana ISO.

    Devuelve { item_key: [{'week', 'date', 'price'}, …] } en orden cronológico.
    """
    series = {}
    for day in sorted(hist):
        week = _week_of(day)
        for key, price in (hist[day] or {}).items():
            if price is None:
                continue
            points = series.setdefault(key, [])
            point = {"week": week, "date": day, "price": round(float(price), 2)}
            if points and points[-1]["week"] == week:
                points[-1] = point          # el último día de la semana manda
            else:
                points.append(point)
    return series


def weekly_table(hist, kinds=None):
    """Resumen por clave para la web: último valor y variación semanal.

    [{key, kind, kind_label, name, price, prev, delta, pct, week, prev_week,
    points}] ordenado por variación absoluta (lo que más se ha movido, primero).
    `kinds` acota a unos tipos concretos (p. ej. solo el patrimonio agregado).
    """
    out = []
    for key, points in weekly_series(hist).items():
        kind, name = split_key(key)
        if kinds and kind not in kinds:
            continue
        last = points[-1]
        prev = points[-2] if len(points) > 1 else None
        pct = None
        if prev and prev["price"]:
            pct = round((last["price"] - prev["price"]) / prev["price"] * 100, 1)
        out.append({
            "key": key, "kind": kind, "kind_label": KIND_LABEL.get(kind, "Otro"),
            "name": name,
            "price": last["price"], "week": last["week"], "date": last["date"],
            "prev": prev["price"] if prev else None,
            "prev_week": prev["week"] if prev else None,
            "delta": round(last["price"] - prev["price"], 2) if prev else None,
            "pct": pct,
            "points": points,
        })
    out.sort(key=lambda r: (abs(r["pct"]) if r["pct"] is not None else -1), reverse=True)
    return out


# ---------------------------------------------------------------------------
# Movimientos de la semana (subidas Y bajadas)
# ---------------------------------------------------------------------------
def _reference_day(days_sorted, window):
    """Día con el que comparar: el más reciente anterior a la ventana.

    Si el histórico es más corto que la ventana se usa el día más antiguo que
    hay — sigue siendo un dato real, solo que el periodo comparado es menor
    (por eso `movers` devuelve también el número de días comparados).
    """
    last = datetime.date.fromisoformat(days_sorted[-1])
    limit = (last - datetime.timedelta(days=window)).isoformat()
    earlier = [d for d in days_sorted[:-1] if d <= limit]
    return earlier[-1] if earlier else (days_sorted[0] if len(days_sorted) > 1 else None)


def movers(hist, threshold=THRESHOLD, window=WINDOW_DAYS, kinds=None):
    """Lo que se ha movido ≥ `threshold` % en los últimos `window` días.

    Vale para cualquier clave del histórico: una carta, una acción, una
    categoría entera o el patrimonio total. Devuelve [{key, kind, kind_label,
    name, pct, delta, price_from, price_to, date_from, date_to, direction,
    days}] ordenado de lo más agregado a lo más concreto y, dentro de cada
    tipo, por variación absoluta. Incluye subidas y bajadas: el umbral se
    aplica al valor absoluto. `kinds` acota a unos tipos concretos.
    """
    days_sorted = sorted(d for d in hist if hist.get(d))
    if len(days_sorted) < 2:
        return []
    day_to = days_sorted[-1]
    day_from = _reference_day(days_sorted, window)
    if not day_from:
        return []
    spanned = (datetime.date.fromisoformat(day_to)
               - datetime.date.fromisoformat(day_from)).days
    before, after = hist[day_from], hist[day_to]
    out = []
    for key, price in after.items():
        old = before.get(key)
        if price is None or old is None or old <= 0:
            continue
        kind, name = split_key(key)
        if kinds and kind not in kinds:
            continue
        pct = (price - old) / old * 100
        if abs(pct) < threshold:
            continue
        out.append({
            "key": key, "kind": kind, "kind_label": KIND_LABEL.get(kind, "Otro"),
            "name": name,
            "pct": round(pct, 1), "delta": round(price - old, 2),
            "price_from": round(old, 2), "price_to": round(price, 2),
            "date_from": day_from, "date_to": day_to,
            "direction": "up" if pct > 0 else "down",
            "days": spanned,
        })
    out.sort(key=lambda m: (_kind_rank(m["kind"]), -abs(m["pct"])))
    return out


def coverage(hist):
    """Estado del seguimiento: qué se está siguiendo y desde cuándo.

    Sirve para avisar EN EL MENSAJE cuando el histórico está vacío o parado, en
    vez de mandar semana tras semana las mismas cifras sin explicación. Separa
    los artículos sueltos del patrimonio agregado porque cada uno lo alimenta un
    trabajo distinto y pueden fallar por separado.
    """
    days_sorted = sorted(d for d in hist if hist.get(d))
    if not days_sorted:
        return {"days": 0, "items": 0, "portfolio_items": 0, "tracks_portfolio": False,
                "last_day": None, "stale_days": None, "first_day": None}
    last = days_sorted[-1]
    kinds_last = [split_key(k)[0] for k in hist[last]]
    stale = (datetime.date.today() - datetime.date.fromisoformat(last)).days
    return {
        "days": len(days_sorted),
        "items": sum(1 for k in kinds_last if k in ITEM_KINDS),
        "portfolio_items": sum(1 for k in kinds_last if k in PORTFOLIO_KINDS),
        "tracks_portfolio": TOTAL_KEY in hist[last],
        "first_day": days_sorted[0],
        "last_day": last,
        "stale_days": stale,
    }
