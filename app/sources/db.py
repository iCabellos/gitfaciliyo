"""
Capa de base de datos: persistencia compartida (móvil/PC/amigos) y caché diaria.

Usa PostgreSQL en producción (variable DATABASE_URL) y SQLite en local como
respaldo. Dos cosas:
  * snapshots: histórico mensual del patrimonio { (mes, categoría) -> valor }.
  * valuation_cache: respuestas costosas (Steam, Scryfall) cacheadas 1 vez/día.
"""

import datetime
import json
import os

from sqlalchemy import (Column, Float, MetaData, String, Table, Text,
                        create_engine, delete, insert, select, update)

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.environ.get("PATRIMONIO_DATA_DIR") or os.path.join(_HERE, "data")


def _engine_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # Render/Heroku dan 'postgres://'; SQLAlchemy quiere 'postgresql://'.
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url, False
    os.makedirs(_DATA_DIR, exist_ok=True)
    return "sqlite:///" + os.path.join(_DATA_DIR, "patrimonio.db"), True


_URL, _IS_SQLITE = _engine_url()
_engine = create_engine(
    _URL, pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _IS_SQLITE else {})

_meta = MetaData()
snapshots = Table(
    "snapshots", _meta,
    Column("month", String(7), primary_key=True),
    Column("category", String(120), primary_key=True),
    Column("value", Float, nullable=False),
    Column("updated", String(32)),
)
valuation_cache = Table(
    "valuation_cache", _meta,
    Column("cache_key", String(255), primary_key=True),
    Column("day", String(10)),
    Column("payload", Text),
)
_meta.create_all(_engine)


def backend():
    return "sqlite" if _IS_SQLITE else "postgresql"


# ---- snapshots -----------------------------------------------------------
def set_snapshot(month, category, value):
    now = datetime.datetime.utcnow().isoformat(timespec="seconds")
    value = round(float(value), 2)
    with _engine.begin() as conn:
        res = conn.execute(update(snapshots)
                           .where(snapshots.c.month == month,
                                  snapshots.c.category == category)
                           .values(value=value, updated=now))
        if res.rowcount == 0:
            conn.execute(insert(snapshots).values(
                month=month, category=category, value=value, updated=now))


def get_snapshots():
    out = {}
    with _engine.connect() as conn:
        for row in conn.execute(select(snapshots.c.month, snapshots.c.category, snapshots.c.value)):
            out.setdefault(row.month, {})[row.category] = row.value
    return out


def reset_snapshots():
    with _engine.begin() as conn:
        conn.execute(delete(snapshots))


# ---- caché diaria de valoraciones ---------------------------------------
def cache_get_today(key):
    today = datetime.date.today().isoformat()
    with _engine.connect() as conn:
        row = conn.execute(select(valuation_cache.c.day, valuation_cache.c.payload)
                           .where(valuation_cache.c.cache_key == key)).first()
    if row and row.day == today:
        try:
            return json.loads(row.payload)
        except (ValueError, TypeError):
            return None
    return None


def cache_put(key, payload):
    today = datetime.date.today().isoformat()
    blob = json.dumps(payload, ensure_ascii=False)
    with _engine.begin() as conn:
        res = conn.execute(update(valuation_cache)
                           .where(valuation_cache.c.cache_key == key)
                           .values(day=today, payload=blob))
        if res.rowcount == 0:
            conn.execute(insert(valuation_cache).values(
                cache_key=key, day=today, payload=blob))
