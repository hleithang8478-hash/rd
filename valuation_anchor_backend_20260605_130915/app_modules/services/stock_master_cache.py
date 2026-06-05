# -*- coding: utf-8 -*-
"""Local cache for Juyuan stock master data."""
from __future__ import annotations

import logging
import math
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Callable


STOCK_MASTER_TABLE = "stock_master_cache"
STOCK_MASTER_META_TABLE = "stock_master_cache_meta"
STOCK_CODE_RE = re.compile(r"(\d{6})")
DEFAULT_REFRESH_HOURS = 24


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_stock_code(value: Any) -> str:
    match = STOCK_CODE_RE.search(str(value or ""))
    return match.group(1) if match else ""


def normalize_stock_item(item: dict[str, Any] | Any) -> dict[str, Any]:
    row = item if isinstance(item, dict) else _row_to_dict(item)
    code = normalize_stock_code(
        row.get("stock_code")
        or row.get("code")
        or row.get("SecuCode")
        or row.get("secu_code")
    )
    if not code:
        return {}
    name = _clean_scalar(
        row.get("stock_name")
        or row.get("name")
        or row.get("SecuAbbr")
        or row.get("SecuAbbrName")
        or row.get("secu_abbr")
    )
    return {
        "code": code,
        "name": name,
        "inner_code": _clean_scalar(row.get("inner_code") or row.get("InnerCode")),
        "company_code": _clean_scalar(row.get("company_code") or row.get("CompanyCode")),
        "third_industry": _clean_scalar(row.get("third_industry") or row.get("ThirdIndustryName")),
        "second_industry": _clean_scalar(row.get("second_industry") or row.get("SecondIndustryName")),
        "first_industry": _clean_scalar(row.get("first_industry") or row.get("FirstIndustryName")),
    }


def ensure_stock_master_cache_schema(connect_db: Callable[..., Any]) -> None:
    conn = connect_db()
    try:
        c = conn.cursor()
        c.execute(
            f"""CREATE TABLE IF NOT EXISTS {STOCK_MASTER_TABLE} (
                   stock_code VARCHAR(32) NOT NULL PRIMARY KEY,
                   stock_name VARCHAR(191),
                   inner_code VARCHAR(64),
                   company_code VARCHAR(64),
                   first_industry VARCHAR(191),
                   second_industry VARCHAR(191),
                   third_industry VARCHAR(191),
                   source VARCHAR(64) NOT NULL DEFAULT 'juyuan',
                   is_active INTEGER NOT NULL DEFAULT 1,
                   last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute(
            f"""CREATE TABLE IF NOT EXISTS {STOCK_MASTER_META_TABLE} (
                   meta_key VARCHAR(64) NOT NULL PRIMARY KEY,
                   meta_value VARCHAR(191),
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_stock_master_name ON {STOCK_MASTER_TABLE}(stock_name)")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_stock_master_company ON {STOCK_MASTER_TABLE}(company_code)")
        c.execute(f"CREATE INDEX IF NOT EXISTS idx_stock_master_updated ON {STOCK_MASTER_TABLE}(updated_at)")
        conn.commit()
    finally:
        conn.close()


def _set_meta(c: Any, key: str, value: Any) -> None:
    c.execute(
        f"""INSERT INTO {STOCK_MASTER_META_TABLE} (meta_key, meta_value, updated_at)
             VALUES (?, ?, CURRENT_TIMESTAMP)
             ON CONFLICT(meta_key) DO UPDATE SET
               meta_value=excluded.meta_value,
               updated_at=CURRENT_TIMESTAMP""",
        (key, str(value)),
    )


def _get_meta(connect_db: Callable[..., Any], key: str) -> str:
    conn = connect_db(sqlite3.Row)
    try:
        c = conn.cursor()
        c.execute(f"SELECT meta_value FROM {STOCK_MASTER_META_TABLE} WHERE meta_key=?", (key,))
        row = _row_to_dict(c.fetchone())
        return str(row.get("meta_value") or "")
    finally:
        conn.close()


def _cache_count(connect_db: Callable[..., Any]) -> int:
    conn = connect_db()
    try:
        c = conn.cursor()
        c.execute(f"SELECT COUNT(*) FROM {STOCK_MASTER_TABLE} WHERE is_active=1")
        return int((c.fetchone() or [0])[0] or 0)
    finally:
        conn.close()


def stock_master_cache_status(connect_db: Callable[..., Any]) -> dict[str, Any]:
    ensure_stock_master_cache_schema(connect_db)
    refreshed_at = _get_meta(connect_db, "full_refreshed_at")
    count = _cache_count(connect_db)
    stale = True
    if refreshed_at:
        try:
            refreshed = datetime.strptime(refreshed_at[:19], "%Y-%m-%d %H:%M:%S")
            stale = datetime.now() - refreshed > timedelta(hours=DEFAULT_REFRESH_HOURS)
        except ValueError:
            stale = True
    return {
        "count": count,
        "full_refreshed_at": refreshed_at,
        "stale": stale,
        "refresh_hours": DEFAULT_REFRESH_HOURS,
    }


def _stock_from_cache_row(row: Any) -> dict[str, Any]:
    data = _row_to_dict(row)
    code = normalize_stock_code(data.get("stock_code"))
    if not code:
        return {}
    return {
        "code": code,
        "name": data.get("stock_name") or "",
        "inner_code": data.get("inner_code") or "",
        "company_code": data.get("company_code") or "",
        "third_industry": data.get("third_industry") or "",
        "second_industry": data.get("second_industry") or "",
        "first_industry": data.get("first_industry") or "",
    }


def upsert_stock_master_cache(
    connect_db: Callable[..., Any],
    stocks: list[dict[str, Any]],
    *,
    source: str = "juyuan",
    replace_full: bool = False,
) -> int:
    ensure_stock_master_cache_schema(connect_db)
    normalized = [normalize_stock_item(item) for item in stocks or []]
    normalized = [item for item in normalized if item.get("code")]
    if not normalized:
        return 0
    conn = connect_db()
    try:
        c = conn.cursor()
        if replace_full:
            c.execute(f"UPDATE {STOCK_MASTER_TABLE} SET is_active=0, updated_at=CURRENT_TIMESTAMP WHERE source=?", (source,))
        c.executemany(
            f"""INSERT INTO {STOCK_MASTER_TABLE}
                   (stock_code, stock_name, inner_code, company_code,
                    first_industry, second_industry, third_industry,
                    source, is_active, last_seen_at, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                 ON CONFLICT(stock_code) DO UPDATE SET
                   stock_name=excluded.stock_name,
                   inner_code=excluded.inner_code,
                   company_code=excluded.company_code,
                   first_industry=excluded.first_industry,
                   second_industry=excluded.second_industry,
                   third_industry=excluded.third_industry,
                   source=excluded.source,
                   is_active=1,
                   last_seen_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP""",
            [
                (
                    item["code"],
                    item.get("name") or "",
                    item.get("inner_code") or "",
                    item.get("company_code") or "",
                    item.get("first_industry") or "",
                    item.get("second_industry") or "",
                    item.get("third_industry") or "",
                    source,
                )
                for item in normalized
            ],
        )
        if replace_full:
            _set_meta(c, "full_refreshed_at", _now_iso())
            _set_meta(c, "full_count", len(normalized))
        conn.commit()
        return len(normalized)
    finally:
        conn.close()


def search_cached_stocks(connect_db: Callable[..., Any], query: str, *, limit: int = 50) -> list[dict[str, Any]]:
    ensure_stock_master_cache_schema(connect_db)
    q = str(query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 50), 200))
    code = normalize_stock_code(q)
    q_lower = q.lower()
    like_any = f"%{q_lower}%"
    code_like_any = f"%{code or q}%"
    code_like_prefix = f"{code or q}%"
    conn = connect_db(sqlite3.Row)
    try:
        c = conn.cursor()
        c.execute(
            f"""SELECT stock_code, stock_name, inner_code, company_code,
                       first_industry, second_industry, third_industry
                  FROM {STOCK_MASTER_TABLE}
                 WHERE is_active=1
                   AND (
                        stock_code LIKE ?
                        OR LOWER(COALESCE(stock_name, '')) LIKE ?
                   )
                 ORDER BY
                   CASE
                     WHEN stock_code = ? THEN 0
                     WHEN stock_code LIKE ? THEN 1
                     WHEN LOWER(COALESCE(stock_name, '')) = ? THEN 2
                     WHEN LOWER(COALESCE(stock_name, '')) LIKE ? THEN 3
                     ELSE 4
                   END,
                   stock_code ASC
                 LIMIT ?""",
            (code_like_any, like_any, code or q, code_like_prefix, q_lower, f"{q_lower}%", limit),
        )
        return [item for item in (_stock_from_cache_row(row) for row in c.fetchall()) if item]
    finally:
        conn.close()


def list_cached_stocks(connect_db: Callable[..., Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    ensure_stock_master_cache_schema(connect_db)
    conn = connect_db(sqlite3.Row)
    try:
        c = conn.cursor()
        sql = (
            f"""SELECT stock_code, stock_name, inner_code, company_code,
                       first_industry, second_industry, third_industry
                  FROM {STOCK_MASTER_TABLE}
                 WHERE is_active=1
                 ORDER BY stock_code ASC"""
        )
        params: list[Any] = []
        if limit:
            sql += " LIMIT ?"
            params.append(max(1, int(limit)))
        c.execute(sql, params)
        return [item for item in (_stock_from_cache_row(row) for row in c.fetchall()) if item]
    finally:
        conn.close()


def _juyuan_fetcher(fetcher_factory: Callable[[], Any] | None = None) -> Any:
    if callable(fetcher_factory):
        return fetcher_factory()
    from data_fetcher import JuyuanDataFetcher

    return JuyuanDataFetcher(lazy_init_pool=True)


def fetch_all_stocks_from_juyuan(fetcher_factory: Callable[[], Any] | None = None) -> list[dict[str, Any]]:
    from juyuan_config import STOCK_FILTER

    fetcher = _juyuan_fetcher(fetcher_factory)
    sql = f"""
    SELECT DISTINCT
        s.SecuCode,
        s.SecuAbbr,
        s.InnerCode,
        s.CompanyCode,
        i.ThirdIndustryName,
        i.SecondIndustryName,
        i.FirstIndustryName
    FROM SecuMain s
    LEFT JOIN LC_ExgIndustry i ON s.CompanyCode = i.CompanyCode
        AND i.Standard = '38'
        AND i.IfPerformed = 1
    WHERE s.SecuCategory = 1
      AND ({STOCK_FILTER})
      AND s.SecuCode NOT LIKE 'X%'
    ORDER BY s.SecuCode
    """
    df = fetcher.query(sql)
    records = df.to_dict(orient="records") if df is not None and not df.empty else []
    return [item for item in (normalize_stock_item(row) for row in records) if item]


def fetch_matching_stocks_from_juyuan(
    query: str,
    *,
    limit: int = 50,
    fetcher_factory: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    from juyuan_config import STOCK_FILTER

    q = str(query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 50), 200))
    fetcher = _juyuan_fetcher(fetcher_factory)
    like = f"%{q}%"
    sql = f"""
    SELECT DISTINCT TOP {limit}
        s.SecuCode,
        s.SecuAbbr,
        s.InnerCode,
        s.CompanyCode,
        i.ThirdIndustryName,
        i.SecondIndustryName,
        i.FirstIndustryName
    FROM SecuMain s
    LEFT JOIN LC_ExgIndustry i ON s.CompanyCode = i.CompanyCode
        AND i.Standard = '38'
        AND i.IfPerformed = 1
    WHERE s.SecuCategory = 1
      AND ({STOCK_FILTER})
      AND s.SecuCode NOT LIKE 'X%'
      AND (s.SecuCode LIKE ? OR s.SecuAbbr LIKE ?)
    ORDER BY s.SecuCode
    """
    df = fetcher.query(sql, params=[like, like])
    records = df.to_dict(orient="records") if df is not None and not df.empty else []
    return [item for item in (normalize_stock_item(row) for row in records) if item]


def refresh_stock_master_cache(
    connect_db: Callable[..., Any],
    *,
    fetcher_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    stocks = fetch_all_stocks_from_juyuan(fetcher_factory=fetcher_factory)
    count = upsert_stock_master_cache(connect_db, stocks, source="juyuan", replace_full=True)
    return {"source": "juyuan", "count": count, "refreshed_at": _now_iso()}


def ensure_stock_master_cache_warm(
    connect_db: Callable[..., Any],
    *,
    fetcher_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    status = stock_master_cache_status(connect_db)
    if status["count"] > 0:
        return {"warmed": False, **status}
    try:
        refreshed = refresh_stock_master_cache(connect_db, fetcher_factory=fetcher_factory)
        return {"warmed": True, **stock_master_cache_status(connect_db), **refreshed}
    except Exception as exc:
        logging.warning("stock master cache warm failed: %s", exc, exc_info=True)
        return {"warmed": False, "error": str(exc), **status}


def get_all_stock_master(
    connect_db: Callable[..., Any],
    *,
    refresh: bool = False,
    refresh_if_stale: bool = True,
    fetcher_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    status = stock_master_cache_status(connect_db)
    source = "cache"
    refresh_error = ""
    if refresh or status["count"] == 0 or (refresh_if_stale and status.get("stale")):
        try:
            refresh_stock_master_cache(connect_db, fetcher_factory=fetcher_factory)
            source = "juyuan"
            status = stock_master_cache_status(connect_db)
        except Exception as exc:
            refresh_error = str(exc)
            logging.warning("stock master full refresh failed: %s", exc, exc_info=True)
    stocks = list_cached_stocks(connect_db)
    return {"stocks": stocks, "source": source, "cache": status, "refresh_error": refresh_error}


def search_stock_master(
    connect_db: Callable[..., Any],
    query: str,
    *,
    limit: int = 50,
    fallback_juyuan: bool = True,
    warm_if_empty: bool = True,
    fetcher_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        return {"stocks": [], "source": "cache", "cache_hit": False, "cache": stock_master_cache_status(connect_db)}
    if warm_if_empty:
        ensure_stock_master_cache_warm(connect_db, fetcher_factory=fetcher_factory)
    stocks = search_cached_stocks(connect_db, q, limit=limit)
    status = stock_master_cache_status(connect_db)
    if stocks:
        return {"stocks": stocks, "source": "cache", "cache_hit": True, "cache": status}
    if not fallback_juyuan:
        return {"stocks": [], "source": "cache", "cache_hit": False, "cache": status}
    try:
        stocks = fetch_matching_stocks_from_juyuan(q, limit=limit, fetcher_factory=fetcher_factory)
        if stocks:
            upsert_stock_master_cache(connect_db, stocks, source="juyuan")
        return {
            "stocks": stocks,
            "source": "juyuan",
            "cache_hit": False,
            "cache": stock_master_cache_status(connect_db),
        }
    except Exception as exc:
        logging.warning("stock master fallback query failed: %s", exc, exc_info=True)
        return {
            "stocks": [],
            "source": "juyuan",
            "cache_hit": False,
            "cache": status,
            "error": str(exc),
        }
