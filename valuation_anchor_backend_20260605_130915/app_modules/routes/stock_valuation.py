# -*- coding: utf-8 -*-
"""Stock valuation workspace routes and calculation helpers."""
from __future__ import annotations

import bisect
import json
import logging
import math
import re
import sqlite3
from datetime import date, datetime
from datetime import timedelta
from typing import Any, Callable

from flask import jsonify, render_template, request, session

from app_modules.services.valuation_ai_coach import (
    call_assumption_review,
    call_ai_coach,
    fallback_assumption_review_response,
    fallback_ai_coach_response,
)
from app_modules.services.valuation_engine import dcf_detail_from_assumptions
from app_modules.services.valuation_fact_cache import (
    DEFAULT_FACT_TTL_HOURS,
    cached_or_fetch_valuation_facts,
    field_config_hash,
)
from app_modules.services.valuation_repository import (
    ValuationCaseRepository,
    default_case_state,
    ensure_valuation_case_schema,
)


CALC_VERSION = "stock_valuation_v1"
STOCK_CODE_RE = re.compile(r"(\d{6})")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


DEFAULT_FIELD_CONFIG: dict[str, dict[str, str]] = {
    "stock_table": {
        "table": "SecuMain",
        "code_field": "SecuCode",
        "name_field": "SecuAbbr",
        "inner_code_field": "InnerCode",
        "company_code_field": "CompanyCode",
    },
    "quote_table": {
        "table": "QT_StockPerformance",
        "date_field": "TradingDay",
        "inner_code_field": "InnerCode",
        "close_field": "ClosePrice",
        "volume_field": "TurnoverVolume",
        "turnover_value_field": "",
        "market_cap_field": "NegotiableMV",
    },
    "valuation_table": {
        "table": "DZ_DIndicesForValuation",
        "date_field": "TradingDay",
        "inner_code_field": "InnerCode",
        "pe_field": "PETTMCut",
        "pb_field": "PB",
        "ps_field": "PSTTM",
        "pcf_field": "PCFTTM",
    },
    "financial_table": {
        "table": "LC_MainIndexNew",
        "date_field": "EndDate",
        "company_code_field": "CompanyCode",
        "roe_field": "ROETTM",
        "revenue_growth_field": "OperatingRevenueGrowRate",
        "revenue_ps_field": "TotalOperatingRevenuePS",
        "dividend_ps_field": "DividendPS",
        "dividend_payout_field": "DividendPaidRatio",
        "operating_cash_ps_growth_field": "OperCashPSGrowRate",
    },
    "income_table": {
        "table": "LC_QIncomeStatementNew",
        "date_field": "EndDate",
        "company_code_field": "CompanyCode",
        "revenue_field": "TotalOperatingRevenue",
    },
    "dividend_table": {
        "table": "LC_Dividend",
        "date_field": "EndDate",
        "inner_code_field": "InnerCode",
        "dividend_ps_field": "CashDiviRMB",
        "event_procedure_field": "EventProcedure",
        "if_dividend_field": "IfDividend",
    },
}


METHOD_DEFINITIONS = [
    {
        "key": "dcf",
        "name": "DCF",
        "title": "现金流折现",
        "description": "用未来自由现金流按折现率折成当前价值，适合经营稳定、现金流可预测的公司。",
        "anchor": "自由现金流、增长率、折现率、终值倍数",
    },
    {
        "key": "pe",
        "name": "PE",
        "title": "市盈率",
        "description": "用每股收益乘目标市盈率估算价值，适合盈利质量稳定或周期位置可识别的公司。",
        "anchor": "EPS、目标 PE、盈利增速、行业可比估值",
    },
    {
        "key": "pb",
        "name": "PB",
        "title": "市净率",
        "description": "用每股净资产乘目标 PB 估算价值，适合银行、保险、地产、周期资产和重资产行业。",
        "anchor": "每股净资产、ROE、资产质量、杠杆与减值风险",
    },
    {
        "key": "ps",
        "name": "PS",
        "title": "市销率",
        "description": "用每股收入乘目标 PS 估算价值，适合利润暂时波动但收入口径可信的成长公司。",
        "anchor": "每股收入、收入增速、毛利率路径、商业模式可兑现性",
    },
    {
        "key": "pcf",
        "name": "PCF",
        "title": "市现率",
        "description": "用经营现金流口径约束估值，适合账面利润和现金流差异较大的公司。",
        "anchor": "经营现金流、现金含量、营运资本占用",
    },
    {
        "key": "dividend",
        "name": "股息率",
        "title": "股息/收益率",
        "description": "用每股股息除以目标收益率估算价值，适合高分红、公用事业和成熟现金牛。",
        "anchor": "每股分红、分红稳定性、目标股息率",
    },
]


INDUSTRY_METHOD_HINTS = [
    (("银行", "保险", "证券", "多元金融", "金融"), ["pb", "dividend", "pe"]),
    (("房地产", "建筑", "建材", "钢铁", "煤炭", "有色", "石油", "化工", "电力", "公用"), ["pb", "pe", "dividend"]),
    (("医药", "食品", "家电", "消费", "白酒", "饮料", "农业"), ["pe", "dcf", "dividend"]),
    (("软件", "半导体", "电子", "通信", "互联网", "传媒", "计算机", "AI", "人工智能"), ["ps", "pe", "dcf"]),
    (("新能源", "电池", "光伏", "汽车", "军工", "机械", "设备"), ["pe", "ps", "dcf"]),
]


INDUSTRY_PEER_METRICS = [
    {"key": "pe_ttm", "label": "PE TTM", "format": "number", "positive_only": True},
    {"key": "pb", "label": "PB", "format": "number", "positive_only": True},
    {"key": "ps_ttm", "label": "PS TTM", "format": "number", "positive_only": True},
    {"key": "pcf_ttm", "label": "PCF TTM", "format": "number", "positive_only": True},
    {"key": "roe_ttm", "label": "ROE TTM", "format": "pct", "positive_only": False},
    {"key": "revenue_growth", "label": "收入增速", "format": "pct", "positive_only": False},
]


def _normalize_stock_code(value: Any) -> str:
    match = STOCK_CODE_RE.search(str(value or ""))
    return match.group(1) if match else ""


def _safe_identifier(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if IDENTIFIER_RE.fullmatch(text):
        return text
    return fallback


def _safe_table(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if TABLE_RE.fullmatch(text):
        return text
    return fallback


def _quote_identifier(value: str) -> str:
    safe = _safe_identifier(value)
    if not safe:
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return f"[{safe}]"


def _quote_table(value: str) -> str:
    safe = _safe_table(value)
    if not safe:
        raise ValueError(f"invalid SQL table: {value!r}")
    return ".".join(_quote_identifier(part) for part in safe.split("."))


def _clean_number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _clean_pct(value: Any, default: float | None = None) -> float | None:
    number = _clean_number(value, default)
    if number is None:
        return default
    # Juyuan fields often store percentage values as 12.3 instead of 0.123.
    if abs(number) > 1.5:
        return number / 100.0
    return number


def _round(value: Any, digits: int = 4) -> float | None:
    number = _clean_number(value)
    if number is None:
        return None
    return round(number, digits)


def _date_str(value: Any) -> str:
    if value is None or value == "":
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text[:10]


def _today() -> str:
    return date.today().strftime("%Y-%m-%d")


def _deep_merge(default: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(default, ensure_ascii=False))
    for group, values in (override or {}).items():
        if not isinstance(values, dict):
            continue
        if group not in merged or not isinstance(merged[group], dict):
            merged[group] = {}
        for key, value in values.items():
            if value is not None:
                merged[group][key] = str(value).strip()
    return merged


def _sanitize_field_config(raw: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    merged = _deep_merge(DEFAULT_FIELD_CONFIG, raw or {})
    clean: dict[str, dict[str, str]] = {}
    for group, values in merged.items():
        clean[group] = {}
        defaults = DEFAULT_FIELD_CONFIG.get(group, {})
        for key, value in values.items():
            if key == "table":
                clean[group][key] = _safe_table(value, defaults.get(key, ""))
            else:
                clean[group][key] = _safe_identifier(value, defaults.get(key, ""))
    return clean


def _row_get(row: Any, *names: str) -> Any:
    if row is None:
        return None
    for name in names:
        if hasattr(row, "get"):
            try:
                if name in row:
                    return row.get(name)
            except Exception:
                pass
        try:
            return row[name]
        except Exception:
            pass
    return None


def _df_first_dict(df: Any) -> dict[str, Any]:
    try:
        if df is None or df.empty:
            return {}
        return df.iloc[0].to_dict()
    except Exception:
        return {}


def _df_records(df: Any) -> list[dict[str, Any]]:
    try:
        if df is None or df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception:
        return []


def _safe_query(fetcher: Any, sql: str, params: list[Any], warnings: list[str], label: str) -> dict[str, Any]:
    try:
        df = fetcher.query(sql, params=params)
        return _df_first_dict(df)
    except Exception as exc:
        warnings.append(f"{label} 聚源查询失败：{exc}")
        logging.warning("valuation %s query failed: %s", label, exc, exc_info=True)
        return {}


def _safe_query_records(fetcher: Any, sql: str, params: list[Any], warnings: list[str], label: str) -> list[dict[str, Any]]:
    try:
        df = fetcher.query(sql, params=params)
        return _df_records(df)
    except Exception as exc:
        warnings.append(f"{label} 聚源查询失败：{exc}")
        logging.warning("valuation %s query failed: %s", label, exc, exc_info=True)
        return []


def _as_sql_date(value: Any, fallback: str | None = None) -> str:
    text = _date_str(value)
    if text:
        return text
    return fallback or _today()


def _years_before(as_of: str, years: int) -> str:
    end = datetime.strptime(_as_sql_date(as_of), "%Y-%m-%d").date()
    try:
        return end.replace(year=end.year - years).strftime("%Y-%m-%d")
    except ValueError:
        return (end - timedelta(days=365 * years)).strftime("%Y-%m-%d")


def _percentile(values: list[float], q: float) -> float | None:
    clean = sorted(value for value in values if value is not None and value > 0)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pos = (len(clean) - 1) * q
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return clean[int(pos)]
    return clean[lower] + (clean[upper] - clean[lower]) * (pos - lower)


def build_pb_history_stats(rows: list[dict[str, Any]], *, current_pb: Any = None, years: int = 10) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    for row in rows or []:
        value = _clean_number(row.get("pb"))
        if value is None or value <= 0:
            continue
        day = _date_str(row.get("date") or row.get("valuation_date") or row.get("TradingDay"))
        points.append({"date": day, "pb": value})
    points.sort(key=lambda item: item.get("date") or "")
    values = [float(item["pb"]) for item in points]
    current = _clean_number(current_pb)
    if current is None and values:
        current = values[-1]
    percentile = None
    if current is not None and values:
        sorted_values = sorted(values)
        lower = bisect.bisect_left(sorted_values, current)
        upper = bisect.bisect_right(sorted_values, current)
        percentile = (lower + (upper - lower) * 0.5) / len(sorted_values)
    sample_count = len(values)
    status = "missing"
    interpretation = "未取得历史 PB 数据，目标 PB 只能算临时假设。"
    if sample_count >= 120 and percentile is not None:
        if percentile <= 0.30:
            status = "low"
            interpretation = "当前 PB 处于自身历史偏低区域，允许把低估作为候选假设，但仍要过周期和资产质量两关。"
        elif percentile >= 0.70:
            status = "high"
            interpretation = "当前 PB 处于自身历史偏高区域，目标 PB 上调需要强证据。"
        else:
            status = "middle"
            interpretation = "当前 PB 处于自身历史中部区域，不能只靠 PB 分位得出便宜结论。"
    elif sample_count:
        status = "thin"
        interpretation = "历史 PB 样本偏少，只能作弱参考。"
    return {
        "years": years,
        "sample_count": sample_count,
        "start_date": points[0]["date"] if points else "",
        "end_date": points[-1]["date"] if points else "",
        "current_pb": _round(current, 4),
        "percentile": _round(percentile, 4) if percentile is not None else None,
        "percentile_label": f"{percentile * 100:.1f}%" if percentile is not None else "",
        "min": _round(min(values), 4) if values else None,
        "p25": _round(_percentile(values, 0.25), 4),
        "median": _round(_percentile(values, 0.50), 4),
        "p75": _round(_percentile(values, 0.75), 4),
        "max": _round(max(values), 4) if values else None,
        "avg": _round(sum(values) / len(values), 4) if values else None,
        "status": status,
        "interpretation": interpretation,
        "recent_points": points[-30:],
    }


def _select_pb_history(
    fetcher: Any,
    inner_code: Any,
    config: dict[str, dict[str, str]],
    as_of: str,
    warnings: list[str],
    *,
    years: int = 10,
    current_pb: Any = None,
) -> dict[str, Any]:
    if not inner_code:
        return build_pb_history_stats([], years=years)
    val = config["valuation_table"]
    start = _years_before(as_of, years)
    sql = f"""
    SELECT
        v.{_quote_identifier(val['date_field'])} AS valuation_date,
        v.{_quote_identifier(val['pb_field'])} AS pb
    FROM {_quote_table(val['table'])} v
    WHERE v.{_quote_identifier(val['inner_code_field'])} = ?
      AND v.{_quote_identifier(val['date_field'])} >= ?
      AND v.{_quote_identifier(val['date_field'])} <= ?
      AND v.{_quote_identifier(val['pb_field'])} IS NOT NULL
      AND v.{_quote_identifier(val['pb_field'])} > 0
    ORDER BY v.{_quote_identifier(val['date_field'])}
    """
    rows = _safe_query_records(fetcher, sql, [inner_code, start, as_of], warnings, "历史 PB")
    return build_pb_history_stats(rows, current_pb=current_pb, years=years)


def _ensure_table(get_sqlite_connection: Callable[..., Any]) -> None:
    conn = get_sqlite_connection()
    try:
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_field_configs
               (owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL DEFAULT 'default',
                config_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (owner_user_id, name))"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_snapshots
               (id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER,
                stock_code TEXT NOT NULL,
                stock_name TEXT,
                valuation_date TEXT,
                payload_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_stock_valuation_snapshots_owner_stock ON "
            "stock_valuation_snapshots(owner_user_id, stock_code, created_at DESC)"
        )
        conn.commit()
    finally:
        conn.close()
    ensure_valuation_case_schema(get_sqlite_connection)


def _load_config(get_sqlite_connection: Callable[..., Any], owner_id: int | None) -> dict[str, dict[str, str]]:
    if owner_id is None:
        return _sanitize_field_config(None)
    _ensure_table(get_sqlite_connection)
    conn = get_sqlite_connection()
    try:
        c = conn.cursor()
        c.execute(
            "SELECT config_json FROM stock_valuation_field_configs WHERE owner_user_id=? AND name='default'",
            (owner_id,),
        )
        row = c.fetchone()
        if not row:
            return _sanitize_field_config(None)
        try:
            return _sanitize_field_config(json.loads(row[0] or "{}"))
        except json.JSONDecodeError:
            return _sanitize_field_config(None)
    finally:
        conn.close()


def _save_config(get_sqlite_connection: Callable[..., Any], owner_id: int, config: dict[str, Any]) -> dict[str, dict[str, str]]:
    clean = _sanitize_field_config(config)
    _ensure_table(get_sqlite_connection)
    conn = get_sqlite_connection()
    try:
        c = conn.cursor()
        payload = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        c.execute(
            "SELECT 1 FROM stock_valuation_field_configs WHERE owner_user_id=? AND name='default'",
            (owner_id,),
        )
        if c.fetchone():
            c.execute(
                """UPDATE stock_valuation_field_configs
                   SET config_json=?, updated_at=CURRENT_TIMESTAMP
                   WHERE owner_user_id=? AND name='default'""",
                (payload, owner_id),
            )
        else:
            c.execute(
                """INSERT INTO stock_valuation_field_configs (owner_user_id, name, config_json, updated_at)
                   VALUES (?, 'default', ?, CURRENT_TIMESTAMP)""",
                (owner_id, payload),
            )
        conn.commit()
        return clean
    finally:
        conn.close()


def _select_latest_quote(fetcher: Any, code: str, config: dict[str, dict[str, str]], as_of: str, warnings: list[str]) -> dict[str, Any]:
    stock = config["stock_table"]
    quote = config["quote_table"]
    select_parts = [
        f"s.{_quote_identifier(stock['code_field'])} AS stock_code",
        f"s.{_quote_identifier(stock['name_field'])} AS stock_name",
        f"s.{_quote_identifier(stock['inner_code_field'])} AS inner_code",
        f"s.{_quote_identifier(stock['company_code_field'])} AS company_code",
        f"q.{_quote_identifier(quote['date_field'])} AS quote_date",
        f"q.{_quote_identifier(quote['close_field'])} AS close_price",
        f"q.{_quote_identifier(quote['volume_field'])} AS volume",
        f"q.{_quote_identifier(quote['market_cap_field'])} AS market_cap",
    ]
    if quote.get("turnover_value_field"):
        select_parts.append(f"q.{_quote_identifier(quote['turnover_value_field'])} AS turnover_value")
    sql = f"""
    SELECT TOP 1 {", ".join(select_parts)}
    FROM {_quote_table(stock['table'])} s
    LEFT JOIN {_quote_table(quote['table'])} q
      ON s.{_quote_identifier(stock['inner_code_field'])} = q.{_quote_identifier(quote['inner_code_field'])}
     AND q.{_quote_identifier(quote['date_field'])} <= ?
    WHERE s.{_quote_identifier(stock['code_field'])} = ?
      AND s.SecuCategory = 1
    ORDER BY q.{_quote_identifier(quote['date_field'])} DESC
    """
    return _safe_query(fetcher, sql, [as_of, code], warnings, "行情")


def _select_latest_industry(fetcher: Any, company_code: Any, warnings: list[str]) -> dict[str, Any]:
    if not company_code:
        return {}
    sql = """
    SELECT TOP 1 FirstIndustryName, SecondIndustryName, ThirdIndustryName
    FROM LC_ExgIndustry
    WHERE CompanyCode = ?
      AND Standard = '38'
      AND IfPerformed = 1
    ORDER BY IfPerformed DESC
    """
    return _safe_query(fetcher, sql, [company_code], warnings, "行业")


def _select_latest_valuation(fetcher: Any, inner_code: Any, config: dict[str, dict[str, str]], as_of: str, warnings: list[str]) -> dict[str, Any]:
    if not inner_code:
        return {}
    val = config["valuation_table"]
    select_parts = [
        f"v.{_quote_identifier(val['date_field'])} AS valuation_date",
        f"v.{_quote_identifier(val['pe_field'])} AS pe_ttm",
        f"v.{_quote_identifier(val['pb_field'])} AS pb",
    ]
    optional_fields = [
        ("ps_field", "ps_ttm"),
        ("pcf_field", "pcf_ttm"),
    ]
    for field_key, alias in optional_fields:
        field = val.get(field_key)
        if field:
            select_parts.append(f"v.{_quote_identifier(field)} AS {alias}")
    sql = f"""
    SELECT TOP 1 {", ".join(select_parts)}
    FROM {_quote_table(val['table'])} v
    WHERE v.{_quote_identifier(val['inner_code_field'])} = ?
      AND v.{_quote_identifier(val['date_field'])} <= ?
    ORDER BY v.{_quote_identifier(val['date_field'])} DESC
    """
    return _safe_query(fetcher, sql, [inner_code, as_of], warnings, "估值指标")


def _select_latest_financial(fetcher: Any, company_code: Any, config: dict[str, dict[str, str]], as_of: str, warnings: list[str]) -> dict[str, Any]:
    if not company_code:
        return {}
    fin = config["financial_table"]
    select_parts = [
        f"f.{_quote_identifier(fin['date_field'])} AS report_date",
        f"f.{_quote_identifier(fin['roe_field'])} AS roe_ttm",
        f"f.{_quote_identifier(fin['revenue_growth_field'])} AS revenue_growth",
        f"f.{_quote_identifier(fin['revenue_ps_field'])} AS revenue_ps",
        f"f.{_quote_identifier(fin['dividend_ps_field'])} AS dividend_ps",
        f"f.{_quote_identifier(fin['dividend_payout_field'])} AS dividend_payout",
        f"f.{_quote_identifier(fin['operating_cash_ps_growth_field'])} AS operating_cash_ps_growth",
    ]
    sql = f"""
    SELECT TOP 1 {", ".join(select_parts)}
    FROM {_quote_table(fin['table'])} f
    WHERE f.{_quote_identifier(fin['company_code_field'])} = ?
      AND f.{_quote_identifier(fin['date_field'])} <= ?
    ORDER BY f.{_quote_identifier(fin['date_field'])} DESC
    """
    return _safe_query(fetcher, sql, [company_code, as_of], warnings, "财务指标")


def _select_latest_income(fetcher: Any, company_code: Any, config: dict[str, dict[str, str]], as_of: str, warnings: list[str]) -> dict[str, Any]:
    if not company_code:
        return {}
    inc = config["income_table"]
    sql = f"""
    SELECT TOP 1
        i.{_quote_identifier(inc['date_field'])} AS income_report_date,
        i.{_quote_identifier(inc['revenue_field'])} AS total_revenue
    FROM {_quote_table(inc['table'])} i
    WHERE i.{_quote_identifier(inc['company_code_field'])} = ?
      AND i.{_quote_identifier(inc['date_field'])} <= ?
    ORDER BY i.{_quote_identifier(inc['date_field'])} DESC
    """
    return _safe_query(fetcher, sql, [company_code, as_of], warnings, "利润表")


def _select_latest_dividend(fetcher: Any, inner_code: Any, config: dict[str, dict[str, str]], as_of: str, warnings: list[str]) -> dict[str, Any]:
    if not inner_code:
        return {}
    div = config["dividend_table"]
    event_field = div.get("event_procedure_field")
    if_dividend_field = div.get("if_dividend_field")
    where_parts = [
        f"d.{_quote_identifier(div['inner_code_field'])} = ?",
        f"d.{_quote_identifier(div['date_field'])} <= ?",
    ]
    params: list[Any] = [inner_code, as_of]
    if if_dividend_field:
        where_parts.append(f"d.{_quote_identifier(if_dividend_field)} = 1")
    if event_field:
        where_parts.append(f"d.{_quote_identifier(event_field)} IN (1004, 3131)")
    sql = f"""
    SELECT TOP 1
        d.{_quote_identifier(div['date_field'])} AS dividend_date,
        d.{_quote_identifier(div['dividend_ps_field'])} AS dividend_ps,
        {f"d.{_quote_identifier(event_field)} AS dividend_event_procedure" if event_field else "NULL AS dividend_event_procedure"},
        {f"d.{_quote_identifier(if_dividend_field)} AS dividend_if_dividend" if if_dividend_field else "NULL AS dividend_if_dividend"}
    FROM {_quote_table(div['table'])} d
    WHERE {" AND ".join(where_parts)}
    ORDER BY d.{_quote_identifier(div['date_field'])} DESC
    """
    return _safe_query(fetcher, sql, params, warnings, "分红")


def build_industry_peer_stats(
    rows: list[dict[str, Any]],
    *,
    industry_level: str = "",
    industry_name: str = "",
    as_of: str = "",
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for metric in INDUSTRY_PEER_METRICS:
        key = metric["key"]
        values: list[float] = []
        for row in rows or []:
            value = _clean_number(row.get(key))
            if value is None:
                continue
            if metric.get("positive_only") and value <= 0:
                continue
            values.append(value)
        if not values:
            continue
        items.append(
            {
                "key": key,
                "label": metric["label"],
                "format": metric["format"],
                "min": _round(min(values), 4),
                "max": _round(max(values), 4),
                "avg": _round(sum(values) / len(values), 4),
                "count": len(values),
            }
        )
    sample_codes = []
    for row in rows[:8]:
        code = str(row.get("stock_code") or "").strip()
        name = str(row.get("stock_name") or "").strip()
        if code:
            sample_codes.append(f"{code} {name}".strip())
    return {
        "industry_level": industry_level,
        "industry_name": industry_name,
        "as_of": as_of,
        "sample_count": len(rows or []),
        "metrics": items,
        "sample_stocks": sample_codes,
    }


def _select_industry_peer_stats(
    fetcher: Any,
    facts: dict[str, Any],
    config: dict[str, dict[str, str]],
    as_of: str,
    warnings: list[str],
) -> dict[str, Any]:
    industry_candidates = [
        ("third", "ThirdIndustryName", facts.get("third_industry")),
        ("second", "SecondIndustryName", facts.get("second_industry")),
        ("first", "FirstIndustryName", facts.get("first_industry")),
    ]
    industry_level, industry_field, industry_name = next(
        ((level, field, name) for level, field, name in industry_candidates if str(name or "").strip()),
        ("", "", ""),
    )
    if not industry_name:
        return {}
    stock = config["stock_table"]
    val = config["valuation_table"]
    fin = config["financial_table"]
    select_parts = [
        f"s.{_quote_identifier(stock['code_field'])} AS stock_code",
        f"s.{_quote_identifier(stock['name_field'])} AS stock_name",
        f"v.{_quote_identifier(val['pe_field'])} AS pe_ttm",
        f"v.{_quote_identifier(val['pb_field'])} AS pb",
        f"f.{_quote_identifier(fin['roe_field'])} AS roe_ttm",
        f"f.{_quote_identifier(fin['revenue_growth_field'])} AS revenue_growth",
    ]
    if val.get("ps_field"):
        select_parts.append(f"v.{_quote_identifier(val['ps_field'])} AS ps_ttm")
    else:
        select_parts.append("NULL AS ps_ttm")
    if val.get("pcf_field"):
        select_parts.append(f"v.{_quote_identifier(val['pcf_field'])} AS pcf_ttm")
    else:
        select_parts.append("NULL AS pcf_ttm")

    sql = f"""
    SELECT TOP 240 {", ".join(select_parts)}
    FROM {_quote_table(stock['table'])} s
    INNER JOIN LC_ExgIndustry i
      ON s.{_quote_identifier(stock['company_code_field'])} = i.CompanyCode
     AND i.Standard = '38'
     AND i.IfPerformed = 1
     AND i.{_quote_identifier(industry_field)} = ?
    OUTER APPLY (
        SELECT TOP 1 *
        FROM {_quote_table(val['table'])} vv
        WHERE vv.{_quote_identifier(val['inner_code_field'])} = s.{_quote_identifier(stock['inner_code_field'])}
          AND vv.{_quote_identifier(val['date_field'])} <= ?
        ORDER BY vv.{_quote_identifier(val['date_field'])} DESC
    ) v
    OUTER APPLY (
        SELECT TOP 1 *
        FROM {_quote_table(fin['table'])} ff
        WHERE ff.{_quote_identifier(fin['company_code_field'])} = s.{_quote_identifier(stock['company_code_field'])}
          AND ff.{_quote_identifier(fin['date_field'])} <= ?
        ORDER BY ff.{_quote_identifier(fin['date_field'])} DESC
    ) f
    WHERE s.SecuCategory = 1
      AND ISNULL(s.{_quote_identifier(stock['name_field'])}, '') NOT LIKE '%ST%'
    ORDER BY s.{_quote_identifier(stock['code_field'])}
    """
    rows = _safe_query_records(fetcher, sql, [industry_name, as_of, as_of], warnings, "同行业参考")
    return build_industry_peer_stats(
        rows,
        industry_level=industry_level,
        industry_name=str(industry_name or ""),
        as_of=as_of,
    )


def fetch_juyuan_snapshot(code: str, config: dict[str, dict[str, str]], as_of: str | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        from data_fetcher import JuyuanDataFetcher
    except Exception as exc:
        return {"success": False, "error": f"无法加载聚源数据模块：{exc}", "warnings": warnings}
    as_of = as_of or _today()
    fetcher = JuyuanDataFetcher(lazy_init_pool=True)
    quote = _select_latest_quote(fetcher, code, config, as_of, warnings)
    if not quote:
        return {
            "success": False,
            "error": f"聚源未查到 {code} 的证券主表/行情数据",
            "warnings": warnings,
        }
    inner_code = _row_get(quote, "inner_code")
    company_code = _row_get(quote, "company_code")
    industry = _select_latest_industry(fetcher, company_code, warnings)
    valuation = _select_latest_valuation(fetcher, inner_code, config, as_of, warnings)
    pb_history = _select_pb_history(fetcher, inner_code, config, as_of, warnings, current_pb=_row_get(valuation, "pb"))
    financial = _select_latest_financial(fetcher, company_code, config, as_of, warnings)
    income = _select_latest_income(fetcher, company_code, config, as_of, warnings)
    dividend = _select_latest_dividend(fetcher, inner_code, config, as_of, warnings)
    dividend_ps = _row_get(dividend, "dividend_ps")
    if dividend_ps is None:
        dividend_ps = _row_get(financial, "dividend_ps")

    facts = {
        "stock_code": str(_row_get(quote, "stock_code") or code).zfill(6),
        "stock_name": _row_get(quote, "stock_name") or "",
        "inner_code": inner_code,
        "company_code": company_code,
        "quote_date": _date_str(_row_get(quote, "quote_date")),
        "valuation_date": _date_str(_row_get(valuation, "valuation_date")),
        "report_date": _date_str(_row_get(financial, "report_date")),
        "income_report_date": _date_str(_row_get(income, "income_report_date")),
        "dividend_date": _date_str(_row_get(dividend, "dividend_date")),
        "close_price": _round(_row_get(quote, "close_price"), 4),
        "market_cap": _round(_row_get(quote, "market_cap"), 4),
        "volume": _round(_row_get(quote, "volume"), 4),
        "turnover_value": _round(_row_get(quote, "turnover_value"), 4),
        "pe_ttm": _round(_row_get(valuation, "pe_ttm"), 4),
        "pb": _round(_row_get(valuation, "pb"), 4),
        "ps_ttm": _round(_row_get(valuation, "ps_ttm"), 4),
        "pcf_ttm": _round(_row_get(valuation, "pcf_ttm"), 4),
        "roe_ttm": _round(_row_get(financial, "roe_ttm"), 4),
        "revenue_growth": _round(_row_get(financial, "revenue_growth"), 4),
        "revenue_ps": _round(_row_get(financial, "revenue_ps"), 4),
        "dividend_ps": _round(dividend_ps, 4),
        "dividend_payout": _round(_row_get(financial, "dividend_payout"), 4),
        "dividend_event_procedure": _round(_row_get(dividend, "dividend_event_procedure"), 4),
        "dividend_if_dividend": _round(_row_get(dividend, "dividend_if_dividend"), 4),
        "operating_cash_ps_growth": _round(_row_get(financial, "operating_cash_ps_growth"), 4),
        "total_revenue": _round(_row_get(income, "total_revenue"), 4),
        "first_industry": _row_get(industry, "FirstIndustryName") or "",
        "second_industry": _row_get(industry, "SecondIndustryName") or "",
        "third_industry": _row_get(industry, "ThirdIndustryName") or "",
    }
    facts["pb_history"] = pb_history
    facts["industry_peer_stats"] = _select_industry_peer_stats(fetcher, facts, config, as_of, warnings)
    return {"success": True, "facts": facts, "warnings": warnings}


def _merge_manual(base: dict[str, Any], manual: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    result = dict(base or {})
    overrides: list[str] = []
    for key, value in (manual or {}).items():
        if value is None or value == "":
            continue
        if key in {
            "stock_code", "stock_name", "quote_date", "valuation_date", "report_date",
            "first_industry", "second_industry", "third_industry",
        }:
            result[key] = str(value).strip()
        else:
            result[key] = _clean_number(value)
        overrides.append(key)
    return result, overrides


def _derive_inputs(facts: dict[str, Any], assumptions: dict[str, Any] | None) -> dict[str, Any]:
    ass = assumptions or {}
    price = _clean_number(facts.get("close_price"))
    pe = _clean_number(facts.get("pe_ttm"))
    pb = _clean_number(facts.get("pb"))
    ps = _clean_number(facts.get("ps_ttm"))
    pcf = _clean_number(facts.get("pcf_ttm"))
    revenue_ps = _clean_number(facts.get("revenue_ps"))
    dividend_ps = _clean_number(facts.get("dividend_ps"))

    eps = _clean_number(ass.get("eps"))
    bvps = _clean_number(ass.get("bvps"))
    cashflow_ps = _clean_number(ass.get("cashflow_ps"))
    fcf_ps = _clean_number(ass.get("fcf_ps"))

    if eps is None and price and pe and pe > 0:
        eps = price / pe
    if bvps is None and price and pb and pb > 0:
        bvps = price / pb
    if revenue_ps is None and price and ps and ps > 0:
        revenue_ps = price / ps
    if cashflow_ps is None and price and pcf and pcf > 0:
        cashflow_ps = price / pcf
    if fcf_ps is None:
        fcf_ps = cashflow_ps if cashflow_ps is not None else eps

    return {
        "price": price,
        "eps": eps,
        "bvps": bvps,
        "revenue_ps": revenue_ps,
        "cashflow_ps": cashflow_ps,
        "fcf_ps": fcf_ps,
        "dividend_ps": dividend_ps,
        "pe": pe,
        "pb": pb,
        "ps": ps,
        "pcf": pcf,
        "roe": _clean_pct(facts.get("roe_ttm")),
        "revenue_growth": _clean_pct(facts.get("revenue_growth")),
    }


def _price_result(method: str, name: str, price: float | None, fair: float | None, inputs: dict[str, Any], notes: list[str]) -> dict[str, Any]:
    margin = None
    if price and fair:
        margin = fair / price - 1.0
    band_low = fair * 0.85 if fair is not None else None
    band_high = fair * 1.15 if fair is not None else None
    return {
        "method": method,
        "name": name,
        "fair_price": _round(fair, 4),
        "band_low": _round(band_low, 4),
        "band_high": _round(band_high, 4),
        "margin_of_safety": _round(margin, 4),
        "inputs": {key: _round(value, 6) if isinstance(value, (int, float)) else value for key, value in inputs.items()},
        "notes": notes,
        "available": fair is not None,
    }


def _dcf_value(fcf_ps: float | None, growth: float, discount: float, terminal_growth: float, years: int) -> float | None:
    if fcf_ps is None or fcf_ps <= 0 or discount <= terminal_growth or years <= 0:
        return None
    total = 0.0
    current = fcf_ps
    for year in range(1, years + 1):
        current *= 1.0 + growth
        total += current / ((1.0 + discount) ** year)
    terminal = current * (1.0 + terminal_growth) / (discount - terminal_growth)
    total += terminal / ((1.0 + discount) ** years)
    return total


def calculate_valuation(facts: dict[str, Any], assumptions: dict[str, Any] | None = None) -> dict[str, Any]:
    assumptions = assumptions or {}
    inputs = _derive_inputs(facts, assumptions)
    price = inputs["price"]
    target_pe = _clean_number(assumptions.get("target_pe"), _clean_number(inputs.get("pe"), 18.0))
    target_pb = _clean_number(assumptions.get("target_pb"), _clean_number(inputs.get("pb"), 2.0))
    target_ps = _clean_number(assumptions.get("target_ps"), _clean_number(inputs.get("ps"), 3.0))
    target_pcf = _clean_number(assumptions.get("target_pcf"), _clean_number(inputs.get("pcf"), 12.0))
    target_dividend_yield = _clean_pct(assumptions.get("target_dividend_yield"), 0.03)
    growth = _clean_pct(assumptions.get("dcf_growth"), inputs.get("revenue_growth") or 0.05)
    discount = _clean_pct(assumptions.get("discount_rate"), 0.10)
    terminal_growth = _clean_pct(assumptions.get("terminal_growth"), 0.025)
    years = int(_clean_number(assumptions.get("dcf_years"), 5) or 5)

    results = [
        _price_result(
            "dcf",
            "DCF",
            price,
            _dcf_value(inputs["fcf_ps"], growth, discount, terminal_growth, years),
            {
                "fcf_ps": inputs["fcf_ps"],
                "growth": growth,
                "discount_rate": discount,
                "terminal_growth": terminal_growth,
                "years": years,
            },
            ["把每股自由现金流逐年折现，再加终值；对增长率和折现率最敏感。"],
        ),
        _price_result(
            "pe",
            "PE",
            price,
            inputs["eps"] * target_pe if inputs["eps"] is not None and target_pe else None,
            {"eps": inputs["eps"], "target_pe": target_pe, "current_pe": inputs["pe"]},
            ["投资锚在盈利能力：EPS 是否真实、可持续，以及目标 PE 是否配得上增长和质量。"],
        ),
        _price_result(
            "pb",
            "PB",
            price,
            inputs["bvps"] * target_pb if inputs["bvps"] is not None and target_pb else None,
            {"bvps": inputs["bvps"], "target_pb": target_pb, "current_pb": inputs["pb"], "roe": inputs["roe"]},
            ["投资锚在资产质量：账面净资产能否转化为稳定 ROE。"],
        ),
        _price_result(
            "ps",
            "PS",
            price,
            inputs["revenue_ps"] * target_ps if inputs["revenue_ps"] is not None and target_ps else None,
            {"revenue_ps": inputs["revenue_ps"], "target_ps": target_ps, "current_ps": inputs["ps"]},
            ["投资锚在收入规模：要同时确认毛利率、费用率和利润兑现路径。"],
        ),
        _price_result(
            "pcf",
            "PCF",
            price,
            inputs["cashflow_ps"] * target_pcf if inputs["cashflow_ps"] is not None and target_pcf else None,
            {"cashflow_ps": inputs["cashflow_ps"], "target_pcf": target_pcf, "current_pcf": inputs["pcf"]},
            ["投资锚在现金流：适合校验利润有没有变成真现金。"],
        ),
        _price_result(
            "dividend",
            "股息率",
            price,
            inputs["dividend_ps"] / target_dividend_yield if inputs["dividend_ps"] is not None and target_dividend_yield else None,
            {"dividend_ps": inputs["dividend_ps"], "target_dividend_yield": target_dividend_yield},
            ["投资锚在分红：核心是分红稳定性，而不是一次性高派息。"],
        ),
    ]
    available = [row for row in results if row["available"]]
    fair_values = [row["fair_price"] for row in available if row.get("fair_price") is not None]
    blended = sum(fair_values) / len(fair_values) if fair_values else None
    detailed_dcf = dcf_detail_from_assumptions(assumptions)
    return {
        "facts": facts,
        "inputs": {key: _round(value, 6) if isinstance(value, (int, float)) else value for key, value in inputs.items()},
        "assumptions": {
            "target_pe": target_pe,
            "target_pb": target_pb,
            "target_ps": target_ps,
            "target_pcf": target_pcf,
            "target_dividend_yield": target_dividend_yield,
            "dcf_growth": growth,
            "discount_rate": discount,
            "terminal_growth": terminal_growth,
            "dcf_years": years,
        },
        "methods": results,
        "dcf_detail": detailed_dcf,
        "summary": {
            "current_price": _round(price, 4),
            "blended_fair_price": _round(blended, 4),
            "blended_margin_of_safety": _round((blended / price - 1.0) if blended and price else None, 4),
            "available_methods": len(available),
            "calc_version": CALC_VERSION,
        },
    }


def recommend_methods(facts: dict[str, Any], valuation: dict[str, Any]) -> list[dict[str, Any]]:
    industry_text = " ".join(
        str(facts.get(key) or "") for key in ("first_industry", "second_industry", "third_industry")
    )
    preferred: list[str] = []
    for keywords, methods in INDUSTRY_METHOD_HINTS:
        if any(keyword.lower() in industry_text.lower() for keyword in keywords):
            preferred.extend(methods)
            break
    if not preferred:
        preferred = ["pe", "dcf", "pb"]

    inputs = valuation.get("inputs") or {}
    scores = {method["key"]: 45 for method in METHOD_DEFINITIONS}
    reasons: dict[str, list[str]] = {method["key"]: [] for method in METHOD_DEFINITIONS}
    for idx, key in enumerate(preferred):
        scores[key] += max(10, 35 - idx * 8)
        reasons[key].append("行业属性更匹配")
    availability_checks = {
        "dcf": inputs.get("fcf_ps"),
        "pe": inputs.get("eps"),
        "pb": inputs.get("bvps"),
        "ps": inputs.get("revenue_ps"),
        "pcf": inputs.get("cashflow_ps"),
        "dividend": inputs.get("dividend_ps"),
    }
    for key, value in availability_checks.items():
        if value is not None and _clean_number(value) is not None and _clean_number(value) > 0:
            scores[key] += 16
            reasons[key].append("当前数据可直接计算")
        else:
            scores[key] -= 22
            reasons[key].append("关键字段缺失，建议先手填或调整字段映射")
    roe = _clean_pct(facts.get("roe_ttm"))
    growth = _clean_pct(facts.get("revenue_growth"))
    if roe is not None and roe >= 0.12:
        scores["pe"] += 6
        scores["pb"] += 8
        reasons["pb"].append("ROE 较高，PB 可以结合 ROE 看资产回报")
    if growth is not None and growth >= 0.15:
        scores["ps"] += 8
        scores["dcf"] += 6
        reasons["ps"].append("收入增长较快，PS 可作为成长阶段锚")
    dividend_ps = _clean_number(facts.get("dividend_ps"))
    price = _clean_number(facts.get("close_price"))
    if dividend_ps and price and dividend_ps / price >= 0.025:
        scores["dividend"] += 14
        reasons["dividend"].append("当前股息率已有锚定价值")

    method_meta = {method["key"]: method for method in METHOD_DEFINITIONS}
    rows = []
    for key, score in scores.items():
        meta = method_meta[key]
        rows.append({
            "method": key,
            "name": meta["name"],
            "title": meta["title"],
            "score": max(0, min(100, round(score))),
            "anchor": meta["anchor"],
            "description": meta["description"],
            "reasons": reasons[key][:3],
        })
    rows.sort(key=lambda item: item["score"], reverse=True)
    return rows


ASSUMPTION_UI_KEYS = {
    "target_pe",
    "target_pb",
    "target_ps",
    "target_pcf",
    "target_dividend_yield",
    "dcf_growth",
    "discount_rate",
    "terminal_growth",
    "eps",
    "bvps",
    "cashflow_ps",
    "dcf_years",
}

PERCENT_UI_KEYS = {"target_dividend_yield", "dcf_growth", "discount_rate", "terminal_growth"}

METHOD_ASSUMPTION_FIELDS = {
    "dcf": {
        "primary": ["dcf_growth", "discount_rate", "terminal_growth", "dcf_years"],
        "supporting": ["cashflow_ps"],
        "secondary": ["target_pe", "target_pcf"],
    },
    "pe": {
        "primary": ["target_pe", "eps"],
        "supporting": ["dcf_growth"],
        "secondary": ["target_pb", "target_ps"],
    },
    "pb": {
        "primary": ["target_pb", "bvps"],
        "supporting": [],
        "secondary": ["target_pe", "target_dividend_yield"],
    },
    "ps": {
        "primary": ["target_ps", "revenue_ps"],
        "supporting": ["dcf_growth"],
        "secondary": ["target_pe", "target_pcf"],
    },
    "pcf": {
        "primary": ["target_pcf", "cashflow_ps"],
        "supporting": [],
        "secondary": ["target_pe", "dcf_growth"],
    },
    "dividend": {
        "primary": ["target_dividend_yield", "dividend_ps"],
        "supporting": [],
        "secondary": ["target_pb", "target_pe"],
    },
}


def _bounded_number(value: Any, low: float, high: float, default: float) -> float:
    number = _clean_number(value, default)
    if number is None:
        number = default
    return max(low, min(high, number))


def _ui_pct(value: Any, default: float) -> float:
    rate = _clean_pct(value, default)
    if rate is None:
        rate = default
    return round(rate * 100.0, 2)


def _method_meta_map() -> dict[str, dict[str, Any]]:
    return {method["key"]: method for method in METHOD_DEFINITIONS}


def _method_label(key: str) -> str:
    meta = _method_meta_map().get(key) or {}
    return str(meta.get("name") or key).upper()


def _fmt_anchor_number(value: Any, *, pct: bool = False, digits: int = 2) -> str:
    number = _clean_number(value)
    if number is None:
        return "-"
    if pct:
        if abs(number) <= 1.5:
            number *= 100.0
        return f"{number:.{digits}f}%"
    return f"{number:.{digits}f}"


def _peer_metric_avg(facts: dict[str, Any], key: str) -> float | None:
    peer = facts.get("industry_peer_stats")
    if not isinstance(peer, dict):
        return None
    for item in peer.get("metrics") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return _clean_number(item.get("avg"))
    return None


def _peer_metric_summary(facts: dict[str, Any], key: str) -> dict[str, Any]:
    peer = facts.get("industry_peer_stats")
    if not isinstance(peer, dict):
        return {}
    for item in peer.get("metrics") or []:
        if isinstance(item, dict) and item.get("key") == key:
            return dict(item)
    return {}


def _method_assumption_fields(method_key: str) -> dict[str, list[str]]:
    fallback = {"primary": ["target_pe"], "supporting": [], "secondary": ["target_pb", "dcf_growth"]}
    fields = METHOD_ASSUMPTION_FIELDS.get(method_key) or fallback
    return {
        "primary": list(fields.get("primary") or []),
        "supporting": list(fields.get("supporting") or []),
        "secondary": list(fields.get("secondary") or []),
    }


def _anchor_formula(method_key: str) -> str:
    return {
        "dcf": "合理价 = 未来自由现金流折现 + 终值",
        "pe": "合理价 = EPS × 目标 PE",
        "pb": "合理价 = 每股净资产 × 目标 PB",
        "ps": "合理价 = 每股收入 × 目标 PS",
        "pcf": "合理价 = 每股现金流 × 目标 PCF",
        "dividend": "合理价 = 每股分红 ÷ 目标股息率",
    }.get(method_key, "合理价 = 核心经营指标 × 目标估值锚")


def _anchor_field(method_key: str) -> str:
    return {
        "dcf": "dcf_growth",
        "pe": "target_pe",
        "pb": "target_pb",
        "ps": "target_ps",
        "pcf": "target_pcf",
        "dividend": "target_dividend_yield",
    }.get(method_key, "target_pe")


def _build_pb_anchor_plan(
    *,
    facts: dict[str, Any],
    inputs: dict[str, Any],
    ui_assumptions: dict[str, Any],
    quality: dict[str, Any],
    industry: str,
) -> dict[str, Any]:
    current_pb = _clean_number(inputs.get("pb"))
    peer_pb = _peer_metric_avg(facts, "pb")
    peer_pb_summary = _peer_metric_summary(facts, "pb")
    pb_history = facts.get("pb_history") if isinstance(facts.get("pb_history"), dict) else {}
    current_roe = _clean_pct(facts.get("roe_ttm"))
    peer_roe = _clean_pct(_peer_metric_avg(facts, "roe_ttm"))
    growth = _clean_pct(facts.get("revenue_growth"))
    peer_growth = _clean_pct(_peer_metric_avg(facts, "revenue_growth"))
    current_pe = _clean_number(inputs.get("pe"))
    current_ps = _clean_number(inputs.get("ps"))
    current_pcf = _clean_number(inputs.get("pcf"))
    target_pb = _clean_number(ui_assumptions.get("target_pb"))
    history_median = _clean_number(pb_history.get("median"))
    base_candidates = [value for value in (history_median, current_pb, peer_pb) if value is not None and value > 0]
    base_pb = sum(base_candidates) / len(base_candidates) if base_candidates else target_pb
    base_pb = _bounded_number(base_pb, 0.2, 15.0, 1.0)
    data_score = _clean_number(quality.get("score"), 0) or 0
    factors = [
        {
            "key": "roe",
            "label": "ROE 与稳定性",
            "weight": 25,
            "direction": "ROE 高且稳定，PB 可以相对同行上调；ROE 低或波动大，要折价。",
            "evidence": f"当前 ROE {_fmt_anchor_number(current_roe, pct=True)}；同行 ROE 均值 {_fmt_anchor_number(peer_roe, pct=True)}",
            "pricing_rule": "先用 3-5 年 ROE 中枢和杜邦分解核对，ROE ≥ 12% 且稳定可给溢价；ROE < 8% 时优先压低目标 PB。",
            "ai_prompt": "追问 ROE 是经营能力、杠杆、周期位置还是一次性因素造成的，并要求补 ROIC 对照。",
        },
        {
            "key": "asset_quality",
            "label": "净资产质量/可靠性",
            "weight": 20,
            "direction": "资产真实、拨备/减值充分则维持基准；资产质量不透明则折价。",
            "evidence": f"每股净资产 {_fmt_anchor_number(inputs.get('bvps'), digits=4)}；数据完整度 {quality.get('score', '-')}%",
            "pricing_rule": "拆固定资产、在建工程、存货、应收、商誉/无形资产和资本化项目；存在高减值或重估风险时目标 PB 低于基准。",
            "ai_prompt": "追问净资产里哪些资产最可能需要折价，最近财报有没有减值、折旧、存货跌价或应收异常。",
        },
        {
            "key": "cycle_position",
            "label": "周期定位/正常化利润",
            "weight": 20,
            "direction": "周期低位且资产仍能赚钱可提高结论质量；景气高点的低 PB/低 PE 可能是周期陷阱。",
            "evidence": f"行业：{industry}；当前 PE {_fmt_anchor_number(current_pe)}、PB {_fmt_anchor_number(current_pb)}、PS {_fmt_anchor_number(current_ps)}、PCF {_fmt_anchor_number(current_pcf)}",
            "pricing_rule": "用产品价格、价差、开工率和库存确认当前利润是正常化利润还是景气高点超额利润；景气高点不因低倍数直接上调。",
            "ai_prompt": "追问收入增长来自量、价、份额还是周期，并要求把利润还原到中性景气情景。",
        },
        {
            "key": "growth",
            "label": "成长与再投资能力",
            "weight": 10,
            "direction": "增长能转化为 ROE 改善时上调；只增长不赚钱时不应抬 PB。",
            "evidence": f"收入增速 {_fmt_anchor_number(growth, pct=True)}；同行均值 {_fmt_anchor_number(peer_growth, pct=True)}",
            "pricing_rule": "增长是次要调整项，不能单独把 PB 推高；资本开支/折旧、ROIC 和研发投入必须能支持未来回报。",
            "ai_prompt": "追问增长来自扩产、涨价、并表还是新业务，并验证它是否能改善资产回报。",
        },
        {
            "key": "peer_position",
            "label": "同行/历史分位",
            "weight": 15,
            "direction": "相对同行更优可小幅溢价；低于同行质量则折价。",
            "evidence": f"历史 PB 分位 {pb_history.get('percentile_label') or '-'}；历史中位 {_fmt_anchor_number(history_median)}；同行 PB 均值 {_fmt_anchor_number(peer_pb)}；同行区间 {_fmt_anchor_number(peer_pb_summary.get('min'))}-{_fmt_anchor_number(peer_pb_summary.get('max'))}",
            "pricing_rule": "先看公司 5-10 年 PB 每日历史分位，再用同行中位/均值校验；不要用 min/max 简化成百分位。",
            "ai_prompt": "追问可比公司是否真的同质，样本是否包含周期高点或低点。",
        },
        {
            "key": "data_risk",
            "label": "数据质量与反证",
            "weight": 10,
            "direction": "数据缺口越多，目标 PB 越应保守，结论强度也要下降。",
            "evidence": f"缺失字段 {len(quality.get('missing_fields') or [])} 个；缺失日期 {len(quality.get('missing_dates') or [])} 个",
            "pricing_rule": "数据完整度低于 70% 时，不宜上调主锚；先补字段或把结论标为待验证。",
            "ai_prompt": "追问哪些缺口会直接改变每股净资产、ROE 或资产质量判断。",
        },
    ]
    research_framework = [
        {
            "key": "quality",
            "title": "质地判断",
            "checks": [
                "盈利质量：经营现金流/净利润、应收周转、毛利率/净利率稳定性。",
                "财务健康：资产负债率、有息负债/总资产、利息保障倍数。",
                "成长持续性：资本开支/折旧、ROIC、研发费用率和新业务回报。",
                "竞争壁垒：市场份额、成本曲线、产品结构和客户黏性。",
            ],
            "question": "低估值 + 高 ROE/成长只能形成初步好质地结论，必须补现金流、负债、ROIC 和壁垒证据。",
            "output": "质地结论强度：优秀/较好/一般/待验证，并写清楚最薄弱证据。",
        },
        {
            "key": "cycle",
            "title": "周期定位",
            "checks": [
                "核心产品价格/价差位于历史什么分位。",
                "产能利用率、库存、下游需求和新增供给处在景气上行还是下行。",
                "当前利润是正常化利润，还是景气高点的超额利润。",
            ],
            "question": "周期股最危险的是在景气高点看到低 PE/PB；先把利润还原到中性景气。",
            "output": "景气位置：低位/中性/高位，并给出正常化 ROE 或正常化 EPS。",
        },
        {
            "key": "pb_anchor",
            "title": "PB 定锚",
            "checks": [
                "当前 PB 在自身 5-10 年每日 PB 数据中的历史分位。",
                "同行 PB 中位/均值、样本同质性和周期阶段是否可比。",
                "每股净资产是否稳定，净资产增长来自留存收益、增发、重估还是并表。",
                "净资产质量是否需要折价：固定资产、在建工程、存货、应收、商誉/无形资产、减值准备。",
            ],
            "question": "PB 高低不能只看行业均值，要同时看历史分位、同行质量差异和净资产可靠性。",
            "output": "基准 PB、质量调整、周期调整、最终目标 PB 和反证条件。",
        },
        {
            "key": "cross_check",
            "title": "交叉验证",
            "checks": [
                "EV/EBITDA：重资产公司跨资本结构和折旧政策对照。",
                "DCF：用中性景气自由现金流做敏感性测试。",
                "PEG/PE：用利润增速而不是收入增速做辅助校验。",
                "产能重置成本法：对照现有产能重建成本与市值/EV。",
            ],
            "question": "至少用两种侧面方法检查 PB 结论是否方向一致。",
            "output": "主锚与交叉验证一致/分歧，并解释分歧来源。",
        },
        {
            "key": "execution",
            "title": "催化剂与安全边际",
            "checks": [
                "重新定价催化剂：产品涨价、产能投产、行业出清、新业务验证或资产负债表修复。",
                "安全边际：目标价、保守情景、最大可承受回撤和仓位上限。",
                "失效条件：核心产品价格、ROE、减值、负债、同行估值中枢或需求假设被证伪。",
            ],
            "question": "质地好和低估不等于立刻重估，必须写清催化剂和什么情况下认错。",
            "output": "观察清单、反证条件和结论有效期。",
        },
    ]
    pb_diagnostics = [
        {
            "title": "PB 高低怎么量化",
            "detail": "优先用公司 5-10 年每日 PB 排序计算历史分位；当前值低于 30% 分位通常算相对偏低，高于 70% 分位需解释溢价。",
        },
        {
            "title": "净资产是否稳定",
            "detail": "看近 5 年每股净资产波动、净资产增长来源和资产构成；重估、并表、增发或大额在建工程会让账面值不够稳定。",
        },
        {
            "title": "净资产质量怎么判",
            "detail": "用 ROE/ROIC、杜邦分解、现金流含金量和减值充分性判断资产能否持续创造利润。",
        },
        {
            "title": "PB 结论的风险",
            "detail": "周期下行、固定资产/存货减值、技术替代、在建工程转固后回报低、折旧或减值政策偏乐观，都会让账面净资产失真。",
        },
    ]
    cross_checks = [
        {"method": "EV/EBITDA", "use": "重资产公司优先侧验，减少折旧政策和资本结构差异。"},
        {"method": "DCF", "use": "用中性景气自由现金流和折现率做敏感性，不让周期高点利润外推。"},
        {"method": "PE/PEG", "use": "只作辅助，用利润增速替代收入增速，避免把规模增长误当盈利增长。"},
        {"method": "产能重置成本", "use": "估算现有产能重建成本，对照 EV/市值检验 PB 的实物含义。"},
    ]
    return {
        "primary_method": "pb",
        "primary_method_name": "PB",
        "anchor_field": "target_pb",
        "anchor_label": "目标 PB",
        "headline": "目标 PB 不是继续假设 PE，而是围绕净资产质量、ROE、周期位置和历史分位推出来。",
        "formula": _anchor_formula("pb"),
        "base_anchor": {
            "label": "基准 PB",
            "value": round(base_pb, 2),
            "source": f"历史 PB 中位数 {_fmt_anchor_number(history_median)}、当前 PB {_fmt_anchor_number(current_pb)}、同行 PB 均值 {_fmt_anchor_number(peer_pb)}；历史分位 {pb_history.get('percentile_label') or '-'}。",
        },
        "suggested_anchor": {
            "label": "建议目标 PB",
            "value": round(_bounded_number(target_pb, 0.2, 15.0, 1.0), 2),
            "source": "由基准 PB 按 ROE、净资产质量、周期位置、成长、同行位置和数据风险调整。",
        },
        "primary_fields": ["target_pb", "bvps"],
        "supporting_fields": [],
        "secondary_fields": ["target_pe", "target_dividend_yield", "target_pcf"],
        "program_role": "程序固定方法映射、基础公式、可用字段、同行参考和硬性校验。",
        "ai_role": "AI 负责把质地、周期、PB 定锚、交叉验证和反证条件拆成可追问的研究问题。",
        "derivation_steps": [
            {
                "title": "先判断公司质地",
                "detail": "低估值、高 ROE 和高成长只是初步信号，先补现金流含金量、负债、ROIC、毛利稳定性和壁垒证据。",
            },
            {
                "title": "再定位周期",
                "detail": "确认核心产品价格、价差、库存和产能利用率处于低位/中性/高位，避免把景气高点利润当常态。",
            },
            {
                "title": "定 PB 基准与质量折溢价",
                "detail": "用历史 PB 分位和同行中枢定基准，再按 ROE/ROIC、净资产可靠性和资产减值风险调整。",
            },
            {
                "title": "侧面验证与失效条件",
                "detail": "用 EV/EBITDA、DCF、PE/PEG 或产能重置成本复核，并写清什么事实出现后 PB 锚必须重算。",
            },
        ],
        "factors": factors,
        "process_steps": [
            {
                "key": "history_percentile",
                "title": "历史 PB 分位",
                "status": "done" if (pb_history.get("sample_count") or 0) >= 120 and pb_history.get("percentile") is not None else "blocked",
                "owner": "program",
                "result": pb_history.get("interpretation") or "未取得历史 PB 数据。",
                "data": pb_history,
                "blocks_scenario": True,
            },
            {"key": "quality", "title": "质地结论", "status": "todo", "owner": "user", "blocks_scenario": True},
            {"key": "cycle", "title": "周期定位", "status": "todo", "owner": "user", "blocks_scenario": True},
            {"key": "asset_quality", "title": "净资产质量", "status": "todo", "owner": "user", "blocks_scenario": True},
            {"key": "cross_check", "title": "侧面印证", "status": "todo", "owner": "user", "blocks_scenario": True},
            {"key": "target_pb", "title": "目标 PB 定稿", "status": "todo", "owner": "user", "blocks_scenario": True},
        ],
        "research_framework": research_framework,
        "pb_diagnostics": pb_diagnostics,
        "cross_checks": cross_checks,
        "next_questions": [
            "这家公司质地较好的结论，除了估值和 ROE，还缺哪些现金流、负债、ROIC 和壁垒证据？",
            f"{industry} 里这家公司为什么应该高于或低于同行 PB？",
            "当前 ROE 能否持续，还是由周期、杠杆或一次性因素推高？",
            "账面净资产里最需要折价或重新确认的资产是什么？",
            "当前利润处在景气高点、中性位置还是低位修复？",
            "PB 结论能否被 EV/EBITDA、DCF、PE/PEG 或产能重置成本侧面印证？",
        ],
        "counter_evidence": [
            "ROE 连续两个报告期低于目标 PB 所需水平。",
            "出现大额减值、拨备不足、资产重估下修或资本补充压力。",
            "核心产品价格/价差从高位回落，正常化 ROE 明显低于当前 ROE。",
            "在建工程转固后回报率低于资本成本，新增净资产稀释 ROE。",
            "同行 PB 中枢明显下移，而本公司质量没有改善证据。",
        ],
    }


def _build_generic_anchor_plan(
    *,
    method_key: str,
    facts: dict[str, Any],
    inputs: dict[str, Any],
    ui_assumptions: dict[str, Any],
    quality: dict[str, Any],
    industry: str,
) -> dict[str, Any]:
    field_map = _method_assumption_fields(method_key)
    anchor = _anchor_field(method_key)
    label_map = {
        "target_pe": "目标 PE",
        "target_pb": "目标 PB",
        "target_ps": "目标 PS",
        "target_pcf": "目标 PCF",
        "target_dividend_yield": "股息率锚",
        "dcf_growth": "DCF 增长率",
    }
    evidence = {
        "pe": f"当前 PE {_fmt_anchor_number(inputs.get('pe'))}；ROE {_fmt_anchor_number(facts.get('roe_ttm'), pct=True)}；收入增速 {_fmt_anchor_number(facts.get('revenue_growth'), pct=True)}",
        "dcf": f"每股现金流 {_fmt_anchor_number(inputs.get('fcf_ps'), digits=4)}；收入增速 {_fmt_anchor_number(facts.get('revenue_growth'), pct=True)}",
        "ps": f"当前 PS {_fmt_anchor_number(inputs.get('ps'))}；同行 PS 均值 {_fmt_anchor_number(_peer_metric_avg(facts, 'ps_ttm'))}",
        "pcf": f"当前 PCF {_fmt_anchor_number(inputs.get('pcf'))}；每股现金流 {_fmt_anchor_number(inputs.get('cashflow_ps'), digits=4)}",
        "dividend": f"每股分红 {_fmt_anchor_number(inputs.get('dividend_ps'), digits=4)}；现价 {_fmt_anchor_number(inputs.get('price'))}",
    }
    return {
        "primary_method": method_key,
        "primary_method_name": _method_label(method_key),
        "anchor_field": anchor,
        "anchor_label": label_map.get(anchor, anchor),
        "headline": f"03 假设应围绕 {_method_label(method_key)} 主锚展开，其他方法只做交叉验证。",
        "formula": _anchor_formula(method_key),
        "base_anchor": {
            "label": "基准锚",
            "value": ui_assumptions.get(anchor),
            "source": evidence.get(method_key, "参考当前估值、同行均值、历史分位和财报事实。"),
        },
        "suggested_anchor": {
            "label": label_map.get(anchor, anchor),
            "value": ui_assumptions.get(anchor),
            "source": "由主方法所需的核心事实和数据质量约束生成。",
        },
        "primary_fields": field_map["primary"],
        "supporting_fields": field_map["supporting"],
        "secondary_fields": field_map["secondary"],
        "program_role": "程序固定公式、字段、上下限、同行参考和硬性错误。",
        "ai_role": "AI 负责解释假设来源、追问证据、比较同行和生成反证条件。",
        "derivation_steps": [
            {"title": "确认主锚字段", "detail": f"本轮主方法是 {_method_label(method_key)}，核心参数是 {label_map.get(anchor, anchor)}。"},
            {"title": "找基准", "detail": "先取当前估值、同行均值或历史分位作为起点。"},
            {"title": "按质量/成长/风险调整", "detail": "只有能被财报、行业和可比公司证明的差异，才允许改变锚值。"},
        ],
        "factors": [
            {
                "key": "business_fit",
                "label": "方法匹配度",
                "weight": 35,
                "direction": "商业模式越贴合主方法，主锚权重越高。",
                "evidence": f"行业：{industry}",
                "pricing_rule": "方法匹配弱时，降低主锚结论强度，并提高辅助验证权重。",
                "ai_prompt": "追问公司价值到底来自利润、资产、收入、现金流还是分红。",
            },
            {
                "key": "peer_history",
                "label": "同行/历史分位",
                "weight": 30,
                "direction": "相对同行质量更好可溢价，质量更弱则折价。",
                "evidence": evidence.get(method_key, ""),
                "pricing_rule": "优先用中位数或合理分位，不直接取极端高低值。",
                "ai_prompt": "追问可比样本是否同质，以及历史区间是否处在周期极端。",
            },
            {
                "key": "data_quality",
                "label": "数据质量",
                "weight": 20,
                "direction": "数据缺口越多，锚值越保守。",
                "evidence": f"数据完整度 {quality.get('score', '-')}%",
                "pricing_rule": "关键字段缺失时，先补数据或只给临时结论。",
                "ai_prompt": "追问哪些字段缺失会改变估值结论。",
            },
            {
                "key": "counter_evidence",
                "label": "反证条件",
                "weight": 15,
                "direction": "反证越清晰，假设越可复盘。",
                "evidence": "需要写入工作纸。",
                "pricing_rule": "无法写反证时，不提高结论强度。",
                "ai_prompt": "追问什么事实出现后，本次估值锚必须失效。",
            },
        ],
        "next_questions": [
            "这个主锚的基准来自当前值、同行、历史分位还是研报？",
            "为什么这家公司应高于或低于基准？",
            "哪个后续事实会推翻这个估值锚？",
        ],
        "counter_evidence": ["主锚对应的核心财务指标连续两个报告期恶化。", "同行估值中枢下移且公司质量没有改善证据。"],
    }


def _build_anchor_plan(
    *,
    primary_method: str,
    facts: dict[str, Any],
    inputs: dict[str, Any],
    ui_assumptions: dict[str, Any],
    quality: dict[str, Any],
    industry: str,
) -> dict[str, Any]:
    if primary_method == "pb":
        return _build_pb_anchor_plan(
            facts=facts,
            inputs=inputs,
            ui_assumptions=ui_assumptions,
            quality=quality,
            industry=industry,
        )
    return _build_generic_anchor_plan(
        method_key=primary_method,
        facts=facts,
        inputs=inputs,
        ui_assumptions=ui_assumptions,
        quality=quality,
        industry=industry,
    )


def _assumption_steps_from_anchor(anchor_plan: dict[str, Any], ui_assumptions: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    factor_text = "；".join(
        f"{item.get('label')} {item.get('weight')}%"
        for item in (anchor_plan.get("factors") or [])[:4]
        if isinstance(item, dict)
    )
    for field in anchor_plan.get("primary_fields") or []:
        if field not in ASSUMPTION_UI_KEYS:
            continue
        steps.append({
            "key": field,
            "label": {
                "target_pb": "目标 PB",
                "bvps": "每股净资产",
                "target_pe": "目标 PE",
                "eps": "EPS",
                "target_ps": "目标 PS",
                "revenue_ps": "每股收入",
                "target_pcf": "目标 PCF",
                "cashflow_ps": "每股现金流",
                "target_dividend_yield": "股息率锚",
                "dcf_growth": "DCF 增长率",
                "discount_rate": "折现率",
                "terminal_growth": "终值增长",
                "dcf_years": "DCF 年数",
            }.get(field, field),
            "suggested_value": ui_assumptions.get(field),
            "unit": "%" if field in PERCENT_UI_KEYS else "倍" if field.startswith("target_") and field != "target_dividend_yield" else "",
            "why": f"这是 {anchor_plan.get('primary_method_name')} 主锚会直接使用的参数；调整依据：{factor_text or '同行/历史/财报证据'}。",
            "question": "这个数字的基准、上调/下调原因和反证条件分别是什么？",
            "risk": "主锚参数没有证据时，后续情景测算会显得精确但不可复盘。",
        })
    for field in anchor_plan.get("secondary_fields") or []:
        if field not in ASSUMPTION_UI_KEYS or field in {step["key"] for step in steps}:
            continue
        steps.append({
            "key": field,
            "label": {
                "target_pe": "目标 PE",
                "target_pb": "目标 PB",
                "target_ps": "目标 PS",
                "target_pcf": "目标 PCF",
                "target_dividend_yield": "股息率锚",
                "dcf_growth": "DCF 增长率",
            }.get(field, field),
            "suggested_value": ui_assumptions.get(field),
            "unit": "%" if field in PERCENT_UI_KEYS else "倍" if field.startswith("target_") and field != "target_dividend_yield" else "",
            "why": "这是辅助验证项，用来检查主锚是否过于乐观或过于保守，不应该抢主方法的位置。",
            "question": "这个辅助方法和主锚是否给出相近结论？差异来自哪里？",
            "risk": "把辅助验证当成主锚，会让假设体系混乱。",
        })
    return steps[:6]


def _calc_assumptions_from_ui(ui: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in (ui or {}).items():
        if key not in ASSUMPTION_UI_KEYS:
            continue
        number = _clean_number(value)
        if number is None:
            continue
        result[key] = number / 100.0 if key in PERCENT_UI_KEYS else number
    return result


def _clean_ui_assumptions(raw: dict[str, Any] | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    cleaned = dict(fallback or {})
    for key, value in (raw or {}).items():
        if key not in ASSUMPTION_UI_KEYS:
            continue
        number = _clean_number(value)
        if number is not None:
            cleaned[key] = round(number, 4)
    return cleaned


def _clean_assumption_evidence(raw: dict[str, Any] | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in (raw or {}).items():
        if key not in ASSUMPTION_UI_KEYS and not str(key).startswith("pb_step_"):
            continue
        text = str(value or "").strip()
        if text:
            cleaned[key] = text[:4000]
    return cleaned


def _scenario_assumptions(base: dict[str, Any], mode: str) -> dict[str, Any]:
    out = dict(base or {})
    if mode == "conservative":
        for key in ("target_pe", "target_pb", "target_ps", "target_pcf"):
            if _clean_number(out.get(key)) is not None:
                out[key] = round(max(0.1, float(out[key]) * 0.85), 4)
        if _clean_number(out.get("dcf_growth")) is not None:
            out["dcf_growth"] = round(max(-5.0, float(out["dcf_growth"]) - 2.0), 4)
        if _clean_number(out.get("discount_rate")) is not None:
            out["discount_rate"] = round(float(out["discount_rate"]) + 1.0, 4)
        if _clean_number(out.get("target_dividend_yield")) is not None:
            out["target_dividend_yield"] = round(float(out["target_dividend_yield"]) + 0.5, 4)
    elif mode == "optimistic":
        for key in ("target_pe", "target_pb", "target_ps", "target_pcf"):
            if _clean_number(out.get(key)) is not None:
                out[key] = round(float(out[key]) * 1.12, 4)
        if _clean_number(out.get("dcf_growth")) is not None:
            out["dcf_growth"] = round(min(30.0, float(out["dcf_growth"]) + 2.0), 4)
        if _clean_number(out.get("discount_rate")) is not None:
            out["discount_rate"] = round(max(6.0, float(out["discount_rate"]) - 0.8), 4)
        if _clean_number(out.get("target_dividend_yield")) is not None:
            out["target_dividend_yield"] = round(max(1.0, float(out["target_dividend_yield"]) - 0.3), 4)
    return out


def _missing_valuation_fields(facts: dict[str, Any], valuation: dict[str, Any]) -> list[dict[str, str]]:
    inputs = valuation.get("inputs") or {}
    checks = [
        ("close_price", "现价", facts.get("close_price")),
        ("pe_ttm", "PE TTM", facts.get("pe_ttm")),
        ("pb", "PB", facts.get("pb")),
        ("ps_ttm", "PS TTM", facts.get("ps_ttm")),
        ("pcf_ttm", "PCF TTM", facts.get("pcf_ttm")),
        ("roe_ttm", "ROE TTM", facts.get("roe_ttm")),
        ("revenue_ps", "每股收入", inputs.get("revenue_ps")),
        ("cashflow_ps", "每股现金流", inputs.get("cashflow_ps")),
        ("dividend_ps", "每股分红", inputs.get("dividend_ps")),
    ]
    missing = []
    for key, label, value in checks:
        number = _clean_number(value)
        if number is None or number <= 0:
            missing.append({"key": key, "label": label})
    return missing


def _data_quality(facts: dict[str, Any], valuation: dict[str, Any]) -> dict[str, Any]:
    missing = _missing_valuation_fields(facts, valuation)
    dates = {
        "quote": facts.get("quote_date") or "",
        "valuation": facts.get("valuation_date") or "",
        "financial": facts.get("report_date") or "",
        "income": facts.get("income_report_date") or "",
        "dividend": facts.get("dividend_date") or "",
    }
    missing_dates = [label for label, value in dates.items() if not value]
    score = 100 - len(missing) * 7 - len(missing_dates) * 5
    return {
        "score": max(0, min(100, score)),
        "missing_fields": missing,
        "dates": dates,
        "missing_dates": missing_dates,
    }


def build_rule_based_valuation_guide(
    facts: dict[str, Any],
    valuation: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic valuation workflow when AI is unavailable."""
    recs = recommendations or recommend_methods(facts, valuation)
    inputs = valuation.get("inputs") or {}
    quality = _data_quality(facts, valuation)
    primary = recs[0] if recs else {"method": "pe", "name": "PE", "score": 0, "reasons": []}
    primary_method = str(primary.get("method") or "pe")
    secondary = [item for item in recs[1:3] if item.get("score", 0) >= 45]
    unsuitable = [item for item in recs[-3:] if item.get("score", 0) < 45]
    industry = facts.get("third_industry") or facts.get("second_industry") or facts.get("first_industry") or "未识别行业"
    roe = _clean_pct(facts.get("roe_ttm"))
    growth = _clean_pct(facts.get("revenue_growth"))
    current_pe = _clean_number(inputs.get("pe"))
    current_pb = _clean_number(inputs.get("pb"))
    current_ps = _clean_number(inputs.get("ps"))
    current_pcf = _clean_number(inputs.get("pcf"))
    dividend_ps = _clean_number(inputs.get("dividend_ps"))
    price = _clean_number(inputs.get("price"))

    pe_base = current_pe if current_pe and current_pe > 0 else 18.0
    if roe is not None and roe < 0.06:
        pe_base *= 0.75
    if growth is not None and growth > 0.15:
        pe_base *= 1.10
    if growth is not None and growth < 0:
        pe_base *= 0.82

    pb_history = facts.get("pb_history") if isinstance(facts.get("pb_history"), dict) else {}
    pb_history_median = _clean_number(pb_history.get("median"))
    pb_history_percentile = _clean_number(pb_history.get("percentile"))
    pb_base = current_pb if current_pb and current_pb > 0 else 2.0
    if pb_history_median and pb_history_median > 0 and current_pb and current_pb > 0:
        if pb_history_percentile is not None and pb_history_percentile <= 0.30:
            pb_base = (current_pb + pb_history_median) / 2.0
        elif pb_history_percentile is not None and pb_history_percentile >= 0.70:
            pb_base = min(current_pb, pb_history_median)
        else:
            pb_base = pb_history_median * 0.55 + current_pb * 0.45
    if roe is not None:
        if roe >= 0.15:
            pb_base *= 1.10
        elif roe < 0.08:
            pb_base *= 0.78

    ps_base = current_ps if current_ps and current_ps > 0 else 3.0
    if growth is not None and growth >= 0.20:
        ps_base *= 1.15
    elif growth is not None and growth <= 0:
        ps_base *= 0.75

    pcf_base = current_pcf if current_pcf and current_pcf > 0 else 12.0
    dcf_growth = growth if growth is not None else 0.05
    discount = 0.10
    if primary.get("method") in {"ps", "dcf"}:
        discount = 0.115
    if primary.get("method") in {"pb", "dividend"}:
        discount = 0.095
    if quality["score"] < 70:
        discount += 0.01
    dividend_yield = 0.03
    if dividend_ps and price and price > 0:
        current_yield = dividend_ps / price
        if current_yield >= 0.04:
            dividend_yield = 0.04
        elif current_yield >= 0.025:
            dividend_yield = 0.035

    ui_assumptions = {
        "target_pe": round(_bounded_number(pe_base, 4.0, 80.0, 18.0), 2),
        "target_pb": round(_bounded_number(pb_base, 0.2, 15.0, 2.0), 2),
        "target_ps": round(_bounded_number(ps_base, 0.2, 40.0, 3.0), 2),
        "target_pcf": round(_bounded_number(pcf_base, 2.0, 80.0, 12.0), 2),
        "dcf_growth": _ui_pct(_bounded_number(dcf_growth, -0.05, 0.25, 0.05), 0.05),
        "discount_rate": _ui_pct(_bounded_number(discount, 0.06, 0.18, 0.10), 0.10),
        "terminal_growth": 2.0,
        "target_dividend_yield": _ui_pct(dividend_yield, 0.03),
        "dcf_years": 5,
    }
    if _clean_number(inputs.get("eps")) and _clean_number(inputs.get("eps")) > 0:
        ui_assumptions["eps"] = _round(inputs.get("eps"), 4)
    if _clean_number(inputs.get("bvps")) and _clean_number(inputs.get("bvps")) > 0:
        ui_assumptions["bvps"] = _round(inputs.get("bvps"), 4)
    if _clean_number(inputs.get("cashflow_ps")) and _clean_number(inputs.get("cashflow_ps")) > 0:
        ui_assumptions["cashflow_ps"] = _round(inputs.get("cashflow_ps"), 4)

    anchor_plan = _build_anchor_plan(
        primary_method=primary_method,
        facts=facts,
        inputs=inputs,
        ui_assumptions=ui_assumptions,
        quality=quality,
        industry=industry,
    )
    assumption_steps = _assumption_steps_from_anchor(anchor_plan, ui_assumptions)
    if not assumption_steps:
        assumption_steps = [
            {
                "key": anchor_plan.get("anchor_field") or "target_pe",
                "label": anchor_plan.get("anchor_label") or "主估值锚",
                "suggested_value": anchor_plan.get("suggested_anchor", {}).get("value"),
                "why": anchor_plan.get("headline") or "围绕主估值方法补关键假设。",
                "question": "这个估值锚的基准、调整原因和反证条件分别是什么？",
                "risk": "缺少证据的主锚不能支撑正式结论。",
            }
        ]
    method_step = [
        {
            "key": "method",
            "label": "估值方法",
            "suggested_value": _method_label(str(primary.get("method") or "")),
            "why": f"{industry} 与 {primary.get('name')} 匹配度最高；先用它做主锚，其他方法只做交叉验证。",
            "question": "这家公司主要价值来自利润、资产、收入规模、现金流，还是分红？",
            "risk": "方法选错会让后面的倍数和 DCF 参数看起来精确但方向错误。",
        }
    ]
    assumption_steps = method_step + assumption_steps

    scenarios = []
    for mode, name in (("conservative", "保守"), ("base", "基准"), ("optimistic", "乐观")):
        scenario_ui = ui_assumptions if mode == "base" else _scenario_assumptions(ui_assumptions, mode)
        scenario_valuation = calculate_valuation(facts, _calc_assumptions_from_ui(scenario_ui))
        scenarios.append({
            "name": name,
            "ui_assumptions": scenario_ui,
            "summary": scenario_valuation.get("summary") or {},
        })

    return {
        "source": "rules",
        "summary": f"先把主估值方法定为 {_method_label(str(primary.get('method') or ''))}，再围绕该方法补关键假设；估值结论必须用数据完整度和反证条件约束。",
        "method_decision": {
            "primary_method": primary.get("method"),
            "primary_name": primary.get("name"),
            "score": primary.get("score"),
            "rationale": primary.get("reasons") or [],
            "secondary_methods": secondary,
            "unsuitable_methods": unsuitable,
        },
        "data_quality": quality,
        "ui_assumptions": ui_assumptions,
        "anchor_plan": anchor_plan,
        "assumption_steps": assumption_steps,
        "scenarios": scenarios,
        "final_checklist": [
            "先确认主估值方法是否匹配商业模式，再看估值数字。",
            "所有目标倍数都要有证据来源：历史分位、可比公司、研报或你自己的验证框架。",
            "如果关键数据日期缺失或滞后，本次结论只能标为临时结论。",
            "结论必须写反证条件：哪个指标恶化时，估值锚失效。",
        ],
        "conclusion": {
            "stance": "待验证",
            "text": "当前只形成估值路径和初始假设，套用建议并计算后，再结合安全边际、数据缺口和反证条件给出有效结论。",
            "watch_items": ["补齐缺失字段", "确认目标倍数证据", "核对最新财报/分红日期"],
        },
    }


def _normalize_ai_valuation_guide(raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return fallback
    guide = dict(fallback)
    for key in ("summary", "method_decision", "data_quality", "anchor_plan", "assumption_steps", "scenarios", "final_checklist", "conclusion"):
        value = raw.get(key)
        if value:
            guide[key] = value
    if isinstance(fallback.get("anchor_plan"), dict) and isinstance(guide.get("anchor_plan"), dict):
        anchor = dict(fallback.get("anchor_plan") or {})
        for key, value in (guide.get("anchor_plan") or {}).items():
            if isinstance(value, dict) and isinstance(anchor.get(key), dict):
                nested = dict(anchor.get(key) or {})
                nested.update({inner_key: inner_value for inner_key, inner_value in value.items() if inner_value not in (None, "", [], {})})
                anchor[key] = nested
            elif value not in (None, "", [], {}):
                anchor[key] = value
        guide["anchor_plan"] = anchor
    guide["ui_assumptions"] = _clean_ui_assumptions(raw.get("ui_assumptions"), fallback.get("ui_assumptions") or {})
    guide["source"] = "ai"
    return guide


def _call_ai_valuation_guide(
    call_json: Callable[..., Any],
    facts: dict[str, Any],
    valuation: dict[str, Any],
    recommendations: list[dict[str, Any]],
    fallback: dict[str, Any],
) -> dict[str, Any]:
    schema = {
        "summary": "一句话说明估值路径，不超过80字",
        "method_decision": {
            "primary_method": "dcf/pe/pb/ps/pcf/dividend",
            "primary_name": "方法中文名",
            "score": 0,
            "rationale": ["为什么这个公司先用这个方法"],
            "secondary_methods": [{"method": "pe", "name": "PE", "reason": "交叉验证原因"}],
            "unsuitable_methods": [{"method": "dcf", "name": "DCF", "reason": "暂不适合原因"}],
        },
        "data_quality": "沿用或修正输入中的数据质量判断",
        "ui_assumptions": {
            "target_pe": "数字，倍数",
            "target_pb": "数字，倍数",
            "target_ps": "数字，倍数",
            "target_pcf": "数字，倍数",
            "dcf_growth": "数字，百分比，例如5表示5%",
            "discount_rate": "数字，百分比",
            "terminal_growth": "数字，百分比",
            "target_dividend_yield": "数字，百分比",
            "dcf_years": "数字",
        },
        "anchor_plan": {
            "primary_method": "主估值方法 key",
            "primary_method_name": "主估值方法名",
            "anchor_field": "03 假设页真正应该优先填写的字段，例如 target_pb",
            "anchor_label": "目标 PB",
            "headline": "说明 02 方法如何约束 03 假设",
            "formula": "合理价公式",
            "base_anchor": {"label": "基准锚", "value": "数字", "source": "基准来源"},
            "suggested_anchor": {"label": "建议锚", "value": "数字", "source": "推导来源"},
            "primary_fields": ["主方法直接字段"],
            "supporting_fields": ["主方法辅助字段"],
            "secondary_fields": ["交叉验证字段，不是主锚"],
            "program_role": "程序固定什么",
            "ai_role": "AI 负责什么",
            "derivation_steps": [{"title": "步骤", "detail": "如何推导"}],
            "factors": [
                {
                    "label": "影响因素",
                    "weight": 35,
                    "direction": "什么情况下上调/下调",
                    "evidence": "当前证据",
                    "pricing_rule": "定价规则",
                    "ai_prompt": "AI 应追问什么",
                }
            ],
            "research_framework": [
                {
                    "title": "质地判断/周期定位/PB定锚/交叉验证/催化剂与安全边际",
                    "checks": ["具体检查项"],
                    "question": "需要回答的问题",
                    "output": "本步骤应形成的结论",
                }
            ],
            "pb_diagnostics": [{"title": "PB 高低怎么量化", "detail": "历史分位、净资产稳定性、净资产质量和失效风险"}],
            "cross_checks": [{"method": "EV/EBITDA/DCF/PE-PEG/产能重置成本", "use": "侧面验证用途"}],
            "next_questions": ["下一步问题"],
            "counter_evidence": ["反证条件"],
        },
        "assumption_steps": [
            {
                "key": "target_pe",
                "label": "目标 PE",
                "suggested_value": "数字或文本",
                "unit": "倍/%/元",
                "why": "为什么这么假设",
                "question": "用户下一步要验证的问题",
                "risk": "这个假设最容易错在哪里",
            }
        ],
        "scenarios": [
            {"name": "保守/基准/乐观", "ui_assumptions": {}, "summary": "可以沿用本地测算summary或文字说明"}
        ],
        "final_checklist": ["给出有效结论前必须检查的事项"],
        "conclusion": {"stance": "待验证/偏低估/合理/偏高估/不可判断", "text": "结论", "watch_items": ["反证指标"]},
    }
    payload = {
        "task": "为单只股票生成一步步估值路径：先判断估值方法，再给出假设，再给出估值结论框架",
        "facts": facts,
        "valuation_inputs": valuation.get("inputs") or {},
        "current_calculation": valuation,
        "method_recommendations": recommendations,
        "fallback_rule_guide": fallback,
        "output_schema": schema,
        "constraints": [
            "必须先判断估值方法，不能直接拍目标倍数",
            "每个假设都要说明证据、下一步验证问题和主要风险",
            "如果主方法是 PB，03 的主假设必须聚焦 target_pb 和 bvps，PE/PEG、EV/EBITDA、DCF、PCF、产能重置成本只能作为辅助验证或反证",
            "如果主方法是 PB，anchor_plan 必须包含 research_framework、pb_diagnostics 和 cross_checks；研究框架至少覆盖质地判断、周期定位、PB定锚、交叉验证、催化剂与安全边际",
            "PB 的高低必须优先追问自身 5-10 年历史 PB 分位，再用同行中位/均值校验；不能只用行业平均 PB 下结论",
            "PB 假设必须检查净资产稳定性和质量：固定资产、在建工程、存货、应收、商誉/无形资产、减值准备、ROE/ROIC、杜邦分解、现金流含金量",
            "周期股或重资产公司必须检查核心产品价格/价差、开工率、库存、供需和正常化利润，避免景气高点低估值陷阱",
            "anchor_plan 必须解释主锚从基准值到建议值的推导、因素权重、上调/下调条件、程序和 AI 的分工",
            "不要给买卖建议，不要承诺收益；只能给估值路径、假设和反证条件",
            "ui_assumptions 里的百分比用人类输入格式，例如 10 表示 10%",
            "证据不足时必须降低结论强度，stance 用 待验证 或 不可判断",
            "只输出 JSON 对象，不要 markdown",
        ],
    }
    messages = [
        {
            "role": "system",
            "content": "你是严谨的股票估值教练。你的任务是把估值从拍脑袋输入，改造成可验证的假设推导流程。只输出 JSON 对象。",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]
    raw = call_json(
        messages,
        temperature=0.18,
        max_tokens=4200,
        timeout=150,
        max_attempts=2,
        max_input_tokens=26000,
        log_prefix="stock_valuation_guide",
    )
    return _normalize_ai_valuation_guide(raw, fallback)


def _case_state_from_guide(
    *,
    stock_code: str,
    stock_name: str,
    valuation_date: str,
    facts: dict[str, Any],
    valuation: dict[str, Any],
    recommendations: list[dict[str, Any]],
    guide: dict[str, Any],
) -> dict[str, Any]:
    state = default_case_state(stock_code=stock_code, stock_name=stock_name, valuation_date=valuation_date)
    quality = guide.get("data_quality") or {}
    method_decision = guide.get("method_decision") or {}
    state["facts"] = facts or {}
    state["valuation"] = valuation or {}
    state["recommendations"] = recommendations or []
    state["guide"] = guide or {}
    state["data_quality"] = quality
    state["workflow"] = {
        "completed_tabs": ["profile", "methods"],
        "unlocked_tabs": ["profile", "methods", "assumptions", "cases"],
        "last_completed_tab": "methods",
    }
    state["tabs"]["profile"]["loaded"] = bool(facts)
    state["tabs"]["profile"]["manual_fields"] = {}
    state["tabs"]["methods"]["selected_primary"] = method_decision.get("primary_method") or ""
    state["tabs"]["methods"]["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["tabs"]["assumptions"]["items"] = guide.get("ui_assumptions") or {}
    state["tabs"]["scenarios"]["items"] = guide.get("scenarios") or ["bear", "base", "bull"]
    state["tabs"]["conclusion"]["summary"] = (guide.get("conclusion") or {}).get("text") or ""
    return state


def register_stock_valuation_routes(app, ctx):
    login_required = ctx["login_required"]
    current_user_id_required = ctx.get("current_user_id_required")
    get_sqlite_connection = ctx["get_sqlite_connection"]
    log_access = ctx.get("log_access")
    call_deepseek_json_chat = ctx.get("call_deepseek_json_chat")
    case_repo = ValuationCaseRepository(get_sqlite_connection)

    def owner_id() -> int | None:
        if callable(current_user_id_required):
            try:
                return int(current_user_id_required())
            except Exception:
                return None
        return None

    def fetch_cached_juyuan_snapshot(
        code: str,
        config: dict[str, dict[str, str]],
        as_of: str | None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        safe_as_of = _as_sql_date(as_of or _today(), _today())
        cfg_hash = field_config_hash(config)
        return cached_or_fetch_valuation_facts(
            get_sqlite_connection,
            lambda: fetch_juyuan_snapshot(code, config, safe_as_of),
            stock_code=code,
            as_of=safe_as_of,
            config_hash=cfg_hash,
            force_refresh=force_refresh,
            ttl_hours=DEFAULT_FACT_TTL_HOURS,
        )

    def _prepare_case_material(data: dict[str, Any], *, allow_ai: bool = False) -> dict[str, Any]:
        code = _normalize_stock_code(data.get("stock_code") or data.get("code"))
        if not code:
            raise ValueError("请输入 6 位股票代码")
        config = _sanitize_field_config(data.get("field_config") or _load_config(get_sqlite_connection, owner_id()))
        facts: dict[str, Any] = {}
        warnings: list[str] = []
        source = str(data.get("source") or "juyuan").strip().lower()
        if source != "manual":
            fetched = fetch_cached_juyuan_snapshot(
                code,
                config,
                data.get("as_of") or _today(),
                force_refresh=bool(data.get("force_refresh")),
            )
            warnings.extend(fetched.get("warnings") or [])
            if fetched.get("success"):
                facts.update(fetched.get("facts") or {})
            elif source == "juyuan_only":
                raise RuntimeError(fetched.get("error") or "聚源数据缺失")
            else:
                warnings.append(fetched.get("error") or "聚源数据缺失，已使用手工字段")
        facts.setdefault("stock_code", code)
        facts, overrides = _merge_manual(facts, data.get("manual_fields") or {})
        valuation = calculate_valuation(facts, data.get("assumptions") or {})
        recommendations = recommend_methods(facts, valuation)
        guide = build_rule_based_valuation_guide(facts, valuation, recommendations)
        use_ai = bool(data.get("use_ai")) and allow_ai
        if use_ai:
            if callable(call_deepseek_json_chat):
                try:
                    guide = _call_ai_valuation_guide(call_deepseek_json_chat, facts, valuation, recommendations, guide)
                except Exception as exc:
                    logging.warning("stock valuation AI guide failed: %s", exc, exc_info=True)
                    warnings.append(f"AI 估值路径生成失败，已使用规则向导：{exc}")
            else:
                warnings.append("AI 估值路径不可用，未找到 AI JSON 调用函数，已使用规则向导")
        return {
            "code": code,
            "config": config,
            "facts": facts,
            "warnings": warnings,
            "source": source,
            "manual_overrides": overrides,
            "valuation": valuation,
            "recommendations": recommendations,
            "guide": guide,
        }

    @app.route("/stock_valuation", endpoint="stock_valuation_page")
    @login_required
    def stock_valuation_page():
        username = session.get("username")
        if callable(log_access):
            try:
                log_access(username, "/stock_valuation", "GET")
            except Exception:
                pass
        return render_template("stock_valuation.html", method_definitions=METHOD_DEFINITIONS)

    @app.route("/api/stock_valuation/config", methods=["GET"])
    @login_required
    def api_stock_valuation_config():
        config = _load_config(get_sqlite_connection, owner_id())
        return jsonify({"success": True, "config": config, "defaults": DEFAULT_FIELD_CONFIG})

    @app.route("/api/stock_valuation/config", methods=["POST"])
    @login_required
    def api_stock_valuation_config_save():
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        data = request.get_json(silent=True) or {}
        config = _save_config(get_sqlite_connection, oid, data.get("config") or data)
        return jsonify({"success": True, "config": config})

    @app.route("/api/stock_valuation/methods", methods=["GET"])
    @login_required
    def api_stock_valuation_methods():
        return jsonify({"success": True, "methods": METHOD_DEFINITIONS})

    @app.route("/api/stock_valuation/fetch", methods=["POST"])
    @login_required
    def api_stock_valuation_fetch():
        data = request.get_json(silent=True) or {}
        code = _normalize_stock_code(data.get("stock_code") or data.get("code"))
        if not code:
            return jsonify({"success": False, "error": "请输入 6 位股票代码"}), 400
        config = _sanitize_field_config(data.get("field_config") or _load_config(get_sqlite_connection, owner_id()))
        result = fetch_cached_juyuan_snapshot(
            code,
            config,
            data.get("as_of") or _today(),
            force_refresh=bool(data.get("force_refresh")),
        )
        return jsonify(result)

    @app.route("/api/stock_valuation/calculate", methods=["POST"])
    @login_required
    def api_stock_valuation_calculate():
        data = request.get_json(silent=True) or {}
        code = _normalize_stock_code(data.get("stock_code") or data.get("code"))
        if not code:
            return jsonify({"success": False, "error": "请输入 6 位股票代码"}), 400
        config = _sanitize_field_config(data.get("field_config") or _load_config(get_sqlite_connection, owner_id()))
        facts: dict[str, Any] = {}
        warnings: list[str] = []
        source = str(data.get("source") or "juyuan").strip().lower()
        if source != "manual":
            fetched = fetch_cached_juyuan_snapshot(
                code,
                config,
                data.get("as_of") or _today(),
                force_refresh=bool(data.get("force_refresh")),
            )
            warnings.extend(fetched.get("warnings") or [])
            if fetched.get("success"):
                facts.update(fetched.get("facts") or {})
            elif source == "juyuan_only":
                return jsonify(fetched)
            else:
                warnings.append(fetched.get("error") or "聚源数据缺失，已使用手工字段")
        facts.setdefault("stock_code", code)
        facts, overrides = _merge_manual(facts, data.get("manual_fields") or {})
        valuation = calculate_valuation(facts, data.get("assumptions") or {})
        recommendations = recommend_methods(facts, valuation)
        payload = {
            "success": True,
            "source": source,
            "manual_overrides": overrides,
            "warnings": warnings,
            "valuation": valuation,
            "recommendations": recommendations,
            "methods": METHOD_DEFINITIONS,
        }
        if data.get("save_snapshot"):
            oid = owner_id()
            if oid is not None:
                try:
                    _ensure_table(get_sqlite_connection)
                    conn = get_sqlite_connection()
                    c = conn.cursor()
                    c.execute(
                        """INSERT INTO stock_valuation_snapshots
                           (owner_user_id, stock_code, stock_name, valuation_date, payload_json)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            oid,
                            code,
                            facts.get("stock_name") or "",
                            data.get("as_of") or _today(),
                            json.dumps(payload, ensure_ascii=False, default=str),
                        ),
                    )
                    conn.commit()
                    conn.close()
                except Exception as exc:
                    logging.warning("save valuation snapshot failed: %s", exc, exc_info=True)
                    payload["warnings"].append(f"保存估值快照失败：{exc}")
        return jsonify(payload)

    @app.route("/api/stock_valuation/guide", methods=["POST"])
    @login_required
    def api_stock_valuation_guide():
        data = request.get_json(silent=True) or {}
        try:
            material = _prepare_case_material(data, allow_ai=True)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        return jsonify({
            "success": True,
            "source": material["source"],
            "manual_overrides": material["manual_overrides"],
            "warnings": material["warnings"],
            "facts": material["facts"],
            "valuation": material["valuation"],
            "recommendations": material["recommendations"],
            "guide": material["guide"],
            "methods": METHOD_DEFINITIONS,
        })

    @app.route("/api/stock_valuation/cases", methods=["GET"])
    @login_required
    def api_stock_valuation_cases():
        oid = owner_id()
        if oid is None:
            return jsonify({"success": True, "items": []})
        code = _normalize_stock_code(request.args.get("stock_code"))
        try:
            limit = max(1, min(int(request.args.get("limit", 30)), 100))
        except (TypeError, ValueError):
            limit = 30
        return jsonify({"success": True, "items": case_repo.list_cases(owner_user_id=oid, stock_code=code, limit=limit)})

    @app.route("/api/stock_valuation/cases", methods=["POST"])
    @login_required
    def api_stock_valuation_case_create():
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        data = request.get_json(silent=True) or {}
        try:
            material = _prepare_case_material(data, allow_ai=bool(data.get("use_ai")))
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        facts = material["facts"]
        guide = material["guide"]
        valuation_date = data.get("as_of") or facts.get("quote_date") or _today()
        state = _case_state_from_guide(
            stock_code=material["code"],
            stock_name=facts.get("stock_name") or "",
            valuation_date=valuation_date,
            facts=facts,
            valuation=material["valuation"],
            recommendations=material["recommendations"],
            guide=guide,
        )
        case = case_repo.create_case(
            owner_user_id=oid,
            stock_code=material["code"],
            stock_name=facts.get("stock_name") or "",
            valuation_date=valuation_date,
            title=data.get("title") or "",
            facts=facts,
            warnings=material["warnings"],
            state=state,
        )
        case_repo.save_method_decision(case["id"], guide, source=guide.get("source") or "rules")
        for key, value in (guide.get("ui_assumptions") or {}).items():
            try:
                case_repo.upsert_assumption(
                    case["id"],
                    {
                        "scenario_key": "base",
                        "assumption_key": key,
                        "label": key,
                        "value": value,
                        "source": guide.get("source") or "rules",
                        "evidence_text": "由估值路径生成的初始假设，需研究员确认。",
                        "status": "draft",
                    },
                )
            except Exception:
                logging.warning("seed valuation assumption failed case=%s key=%s", case["id"], key, exc_info=True)
        for item in (guide.get("conclusion") or {}).get("watch_items") or []:
            try:
                case_repo.add_counter_evidence(
                    case["id"],
                    {"title": str(item), "trigger_condition": str(item), "severity": "medium", "status": "open"},
                )
            except Exception:
                logging.warning("seed counter evidence failed case=%s", case["id"], exc_info=True)
        case = case_repo.get_case(case["id"], owner_user_id=oid)
        return jsonify({
            "success": True,
            "case": case,
            "warnings": material["warnings"],
            "valuation": material["valuation"],
            "recommendations": material["recommendations"],
            "guide": guide,
        })

    @app.route("/api/stock_valuation/cases/<int:case_id>", methods=["GET"])
    @login_required
    def api_stock_valuation_case_detail(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        case = case_repo.get_case(case_id, owner_user_id=oid)
        if not case:
            return jsonify({"success": False, "error": "估值案例不存在或无权访问"}), 404
        return jsonify({"success": True, "case": case})

    @app.route("/api/stock_valuation/cases/<int:case_id>", methods=["DELETE"])
    @login_required
    def api_stock_valuation_case_delete(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        deleted = case_repo.delete_case(case_id, owner_user_id=oid)
        if not deleted:
            return jsonify({"success": False, "error": "估值案例不存在或无权删除"}), 404
        return jsonify({"success": True, "deleted_id": case_id})

    @app.route("/api/stock_valuation/cases/<int:case_id>/state", methods=["PUT", "POST"])
    @login_required
    def api_stock_valuation_case_state(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        data = request.get_json(silent=True) or {}
        state = data.get("state") or {}
        if not isinstance(state, dict):
            return jsonify({"success": False, "error": "state 必须是对象"}), 400
        case = case_repo.save_state(case_id, state, owner_user_id=oid, current_tab=data.get("current_tab"))
        if not case:
            return jsonify({"success": False, "error": "估值案例不存在或无权访问"}), 404
        return jsonify({"success": True, "case": case})

    @app.route("/api/stock_valuation/cases/<int:case_id>/assumptions", methods=["POST"])
    @login_required
    def api_stock_valuation_case_assumption(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        if not case_repo.get_case(case_id, owner_user_id=oid):
            return jsonify({"success": False, "error": "估值案例不存在或无权访问"}), 404
        data = request.get_json(silent=True) or {}
        try:
            assumption = case_repo.upsert_assumption(case_id, data)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        return jsonify({"success": True, "assumption": assumption})

    @app.route("/api/stock_valuation/cases/<int:case_id>/scenarios", methods=["POST"])
    @login_required
    def api_stock_valuation_case_scenarios(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        case = case_repo.get_case(case_id, owner_user_id=oid)
        if not case:
            return jsonify({"success": False, "error": "估值案例不存在或无权访问"}), 404
        data = request.get_json(silent=True) or {}
        raw_items = data.get("scenarios") if isinstance(data.get("scenarios"), list) else []
        if not raw_items:
            return jsonify({"success": False, "error": "scenarios 不能为空"}), 400
        facts_history = case.get("facts_history") or []
        facts = (facts_history[0] or {}).get("facts") if facts_history else (case.get("state") or {}).get("facts") or {}
        saved = []
        for idx, item in enumerate(raw_items[:5]):
            if not isinstance(item, dict):
                continue
            scenario_key = str(item.get("scenario_key") or item.get("key") or f"scenario_{idx + 1}").strip()
            name = str(item.get("name") or scenario_key).strip()
            ui_assumptions = item.get("ui_assumptions") or item.get("assumptions") or {}
            calc_assumptions = _calc_assumptions_from_ui(ui_assumptions)
            if isinstance(item.get("dcf_detail"), dict):
                calc_assumptions["dcf_detail"] = item["dcf_detail"]
            valuation = calculate_valuation(facts or {}, calc_assumptions)
            scenario = case_repo.upsert_scenario(
                case_id,
                {
                    "scenario_key": scenario_key,
                    "name": name,
                    "assumptions": ui_assumptions,
                    "notes": item.get("notes") or "",
                },
            )
            case_repo.save_scenario_result(
                case_id,
                scenario_key,
                valuation,
                engine_version=(valuation.get("summary") or {}).get("calc_version") or CALC_VERSION,
            )
            saved.append({"scenario": scenario, "valuation": valuation})
        case = case_repo.get_case(case_id, owner_user_id=oid)
        return jsonify({"success": True, "items": saved, "case": case})

    @app.route("/api/stock_valuation/cases/<int:case_id>/assumption_review", methods=["POST"])
    @login_required
    def api_stock_valuation_case_assumption_review(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        case = case_repo.get_case(case_id, owner_user_id=oid)
        if not case:
            return jsonify({"success": False, "error": "估值案例不存在或无权访问"}), 404
        data = request.get_json(silent=True) or {}
        ui_assumptions = _clean_ui_assumptions(data.get("ui_assumptions") or data.get("assumptions") or {})
        assumption_evidence = _clean_assumption_evidence(data.get("assumption_evidence") or data.get("evidence") or {})
        user_logic = str(data.get("user_logic") or "").strip()
        combined_logic = user_logic
        if assumption_evidence:
            evidence_lines = [f"{key}: {value}" for key, value in assumption_evidence.items()]
            combined_logic = "\n".join([item for item in [user_logic, *evidence_lines] if item]).strip()
            for key, value in assumption_evidence.items():
                if str(key).startswith("pb_step_") and value:
                    ui_assumptions[key] = value
        facts_history = case.get("facts_history") or []
        latest_facts = (facts_history[0] or {}).get("facts") if facts_history else (case.get("state") or {}).get("facts") or {}
        method_decision = case.get("method_decision") or {}
        state_guide = ((case.get("state") or {}).get("guide") or {}) if isinstance(case.get("state"), dict) else {}
        if isinstance(state_guide.get("anchor_plan"), dict) and not isinstance(method_decision.get("anchor_plan"), dict):
            method_decision = dict(method_decision)
            method_decision["anchor_plan"] = state_guide.get("anchor_plan")
        if not method_decision.get("primary_method") and state_guide.get("method_decision"):
            merged_decision = dict(state_guide.get("method_decision") or {})
            merged_decision.update({key: value for key, value in method_decision.items() if value not in (None, "", [], {})})
            method_decision = merged_decision
        assumptions = case.get("assumptions") or []
        fallback = fallback_assumption_review_response(
            facts=latest_facts or {},
            method_decision=method_decision,
            assumptions=assumptions,
            ui_assumptions=ui_assumptions,
            user_logic=combined_logic,
        )
        try:
            if callable(call_deepseek_json_chat) and data.get("use_ai", True):
                review = call_assumption_review(
                    call_deepseek_json_chat,
                    case_state=case.get("state") or {},
                    facts=latest_facts or {},
                    method_decision=method_decision,
                    assumptions=assumptions,
                    ui_assumptions=ui_assumptions,
                    user_logic=combined_logic,
                    fallback=fallback,
                )
                review["source"] = "online_ai"
            else:
                review = fallback
                review["source"] = "rule_fallback"
        except Exception as exc:
            logging.warning("valuation assumption review failed: %s", exc, exc_info=True)
            review = fallback
            review["source"] = "rule_fallback"
            review["ai_error"] = str(exc)
        review["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state_payload = dict(case.get("state") or {})
        tabs = dict(state_payload.get("tabs") or {})
        assumption_tab = dict(tabs.get("assumptions") or {})
        assumption_tab["review"] = review
        assumption_tab["reviewed_at"] = review["reviewed_at"]
        assumption_tab["items"] = ui_assumptions or assumption_tab.get("items") or {}
        assumption_tab["evidence"] = assumption_evidence or assumption_tab.get("evidence") or {}
        assumption_tab["logic"] = user_logic or assumption_tab.get("logic") or ""
        tabs["assumptions"] = assumption_tab
        state_payload["tabs"] = tabs
        state_payload["assumption_review"] = review
        workflow = dict(state_payload.get("workflow") or {})
        completed = list(workflow.get("completed_tabs") or [])
        unlocked = list(workflow.get("unlocked_tabs") or [])
        if "assumptions" not in completed:
            completed.append("assumptions")
        if "scenarios" not in unlocked:
            unlocked.append("scenarios")
        workflow["completed_tabs"] = completed
        workflow["unlocked_tabs"] = unlocked
        workflow["last_completed_tab"] = "assumptions"
        state_payload["workflow"] = workflow
        case_repo.save_state(case_id, state_payload, owner_user_id=oid, current_tab="assumptions")
        case_repo.add_ai_message(
            case_id,
            {
                "role": "assistant",
                "content": review.get("summary") or "",
                "tab_key": "assumptions",
                "related_field": "all",
                "payload": {"type": "assumption_review", **review},
            },
        )
        for item in review.get("counter_evidence") or []:
            try:
                case_repo.add_counter_evidence(case_id, item)
            except Exception:
                logging.warning("save review counter evidence failed case=%s", case_id, exc_info=True)
        case = case_repo.get_case(case_id, owner_user_id=oid)
        return jsonify({"success": True, "review": review, "case": case})

    @app.route("/api/stock_valuation/cases/<int:case_id>/ai_coach", methods=["POST"])
    @login_required
    def api_stock_valuation_case_ai_coach(case_id: int):
        oid = owner_id()
        if oid is None:
            return jsonify({"success": False, "error": "无法识别当前用户"}), 400
        case = case_repo.get_case(case_id, owner_user_id=oid)
        if not case:
            return jsonify({"success": False, "error": "估值案例不存在或无权访问"}), 404
        data = request.get_json(silent=True) or {}
        user_message = str(data.get("message") or "").strip()
        related_field = str(data.get("related_field") or "").strip()
        if not user_message:
            return jsonify({"success": False, "error": "请输入要让 AI Coach 追问的内容"}), 400
        case_repo.add_ai_message(
            case_id,
            {
                "role": "user",
                "content": user_message,
                "tab_key": data.get("tab_key") or "assumptions",
                "related_field": related_field,
                "payload": {"request": data},
            },
        )
        facts_history = case.get("facts_history") or []
        latest_facts = (facts_history[0] or {}).get("facts") if facts_history else (case.get("state") or {}).get("facts") or {}
        try:
            if callable(call_deepseek_json_chat) and data.get("use_ai", True):
                coach = call_ai_coach(
                    call_deepseek_json_chat,
                    case_state=case.get("state") or {},
                    facts=latest_facts or {},
                    method_decision=case.get("method_decision") or {},
                    assumptions=case.get("assumptions") or [],
                    user_message=user_message,
                    related_field=related_field,
                )
                coach["source"] = "online_ai"
            else:
                coach = fallback_ai_coach_response(user_message=user_message, related_field=related_field)
                coach["source"] = "rule_fallback"
        except Exception as exc:
            logging.warning("valuation ai coach failed: %s", exc, exc_info=True)
            coach = fallback_ai_coach_response(user_message=user_message, related_field=related_field)
            coach["ai_error"] = str(exc)
            coach["source"] = "rule_fallback"
        coach["related_field"] = related_field
        assistant_message = case_repo.add_ai_message(
            case_id,
            {
                "role": "assistant",
                "content": coach.get("summary") or "",
                "tab_key": data.get("tab_key") or "assumptions",
                "related_field": related_field,
                "payload": coach,
            },
        )
        for item in coach.get("counter_evidence") or []:
            try:
                case_repo.add_counter_evidence(case_id, item)
            except Exception:
                logging.warning("save ai counter evidence failed case=%s", case_id, exc_info=True)
        return jsonify({"success": True, "coach": coach, "message": assistant_message})

    @app.route("/api/stock_valuation/history", methods=["GET"])
    @login_required
    def api_stock_valuation_history():
        oid = owner_id()
        if oid is None:
            return jsonify({"success": True, "items": []})
        code = _normalize_stock_code(request.args.get("stock_code"))
        try:
            limit = max(1, min(int(request.args.get("limit", 20)), 100))
        except (TypeError, ValueError):
            limit = 20
        _ensure_table(get_sqlite_connection)
        conn = get_sqlite_connection(sqlite3.Row)
        try:
            c = conn.cursor()
            where = ["owner_user_id=?"]
            params: list[Any] = [oid]
            if code:
                where.append("stock_code=?")
                params.append(code)
            c.execute(
                f"""SELECT id, stock_code, stock_name, valuation_date, created_at
                    FROM stock_valuation_snapshots
                    WHERE {" AND ".join(where)}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                params + [limit],
            )
            items = [dict(row) for row in c.fetchall()]
            return jsonify({"success": True, "items": items})
        finally:
            conn.close()
