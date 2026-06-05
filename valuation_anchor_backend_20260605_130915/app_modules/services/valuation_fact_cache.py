# -*- coding: utf-8 -*-
"""Local cache for stock valuation Juyuan fact snapshots."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Callable


VALUATION_FACT_CACHE_TABLE = "stock_valuation_fact_cache"
DEFAULT_FACT_TTL_HOURS = 12


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any, fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def field_config_hash(config: dict[str, Any] | None) -> str:
    payload = _json_dumps(config or {})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def ensure_valuation_fact_cache_schema(connect_db: Callable[..., Any]) -> None:
    conn = connect_db()
    try:
        c = conn.cursor()
        c.execute(
            f"""CREATE TABLE IF NOT EXISTS {VALUATION_FACT_CACHE_TABLE} (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   stock_code VARCHAR(32) NOT NULL,
                   as_of VARCHAR(32) NOT NULL,
                   field_config_hash VARCHAR(64) NOT NULL,
                   facts_json TEXT NOT NULL,
                   warnings_json TEXT NOT NULL DEFAULT '[]',
                   source VARCHAR(64) NOT NULL DEFAULT 'juyuan',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(stock_code, as_of, field_config_hash))"""
        )
        c.execute(
            f"CREATE INDEX IF NOT EXISTS idx_svfc_stock_updated ON "
            f"{VALUATION_FACT_CACHE_TABLE}(stock_code, updated_at DESC)"
        )
        c.execute(
            f"CREATE INDEX IF NOT EXISTS idx_svfc_asof ON "
            f"{VALUATION_FACT_CACHE_TABLE}(as_of, updated_at DESC)"
        )
        conn.commit()
    finally:
        conn.close()


def get_cached_valuation_facts(
    connect_db: Callable[..., Any],
    *,
    stock_code: str,
    as_of: str,
    config_hash: str,
    ttl_hours: int = DEFAULT_FACT_TTL_HOURS,
) -> dict[str, Any] | None:
    ensure_valuation_fact_cache_schema(connect_db)
    conn = connect_db(sqlite3.Row)
    try:
        c = conn.cursor()
        c.execute(
            f"""SELECT facts_json, warnings_json, source, updated_at
                  FROM {VALUATION_FACT_CACHE_TABLE}
                 WHERE stock_code=? AND as_of=? AND field_config_hash=?
                 LIMIT 1""",
            (stock_code, as_of, config_hash),
        )
        row = _row_to_dict(c.fetchone())
        if not row:
            return None
        updated_at = str(row.get("updated_at") or "")
        try:
            updated = datetime.strptime(updated_at[:19], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - updated > timedelta(hours=max(1, int(ttl_hours or DEFAULT_FACT_TTL_HOURS))):
                return None
        except ValueError:
            return None
        return {
            "success": True,
            "facts": _json_loads(row.get("facts_json"), {}) or {},
            "warnings": _json_loads(row.get("warnings_json"), []) or [],
            "source": row.get("source") or "cache",
            "cache": {"hit": True, "updated_at": updated_at, "ttl_hours": ttl_hours},
        }
    finally:
        conn.close()


def save_valuation_facts_cache(
    connect_db: Callable[..., Any],
    *,
    stock_code: str,
    as_of: str,
    config_hash: str,
    facts: dict[str, Any],
    warnings: list[Any] | None = None,
    source: str = "juyuan",
) -> None:
    ensure_valuation_fact_cache_schema(connect_db)
    conn = connect_db()
    try:
        c = conn.cursor()
        c.execute(
            f"""INSERT INTO {VALUATION_FACT_CACHE_TABLE}
                   (stock_code, as_of, field_config_hash, facts_json, warnings_json, source, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                 ON CONFLICT(stock_code, as_of, field_config_hash) DO UPDATE SET
                   facts_json=excluded.facts_json,
                   warnings_json=excluded.warnings_json,
                   source=excluded.source,
                   updated_at=CURRENT_TIMESTAMP""",
            (
                stock_code,
                as_of,
                config_hash,
                _json_dumps(facts or {}),
                _json_dumps(warnings or []),
                source,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def cached_or_fetch_valuation_facts(
    connect_db: Callable[..., Any],
    fetcher: Callable[[], dict[str, Any]],
    *,
    stock_code: str,
    as_of: str,
    config_hash: str,
    force_refresh: bool = False,
    ttl_hours: int = DEFAULT_FACT_TTL_HOURS,
) -> dict[str, Any]:
    if not force_refresh:
        cached = get_cached_valuation_facts(
            connect_db,
            stock_code=stock_code,
            as_of=as_of,
            config_hash=config_hash,
            ttl_hours=ttl_hours,
        )
        if cached is not None:
            return cached
    result = fetcher()
    if result.get("success"):
        save_valuation_facts_cache(
            connect_db,
            stock_code=stock_code,
            as_of=as_of,
            config_hash=config_hash,
            facts=result.get("facts") or {},
            warnings=result.get("warnings") or [],
            source="juyuan",
        )
        result = dict(result)
        result["cache"] = {"hit": False, "updated_at": _now_iso(), "ttl_hours": ttl_hours}
    return result
