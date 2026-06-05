# -*- coding: utf-8 -*-
"""Repository for stock valuation cases and work papers.

The repository keeps the full valuation process, not only the final price.
It is intentionally database-helper based so it can run against the app's
SQLite/MySQL compatibility connection.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Callable


SCHEMA_VERSION = "valuation_case_v1"


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


def _column_map(c: Any, table_name: str) -> dict[str, dict[str, Any]]:
    c.execute(f"PRAGMA table_info({table_name})")
    return {str(row[1]): {"type": str(row[2] or ""), "default": row[4]} for row in c.fetchall()}


def _repair_short_text_defaults(c: Any) -> None:
    """Repair older MySQL-compatible tables that lost defaults on LONGTEXT columns."""
    try:
        columns = _column_map(c, "stock_valuation_cases")
    except Exception:
        return
    repair_sql = {
        "status": "ALTER TABLE stock_valuation_cases MODIFY COLUMN status VARCHAR(64) NOT NULL DEFAULT 'draft'",
        "current_tab": "ALTER TABLE stock_valuation_cases MODIFY COLUMN current_tab VARCHAR(64) NOT NULL DEFAULT 'profile'",
        "schema_version": (
            "ALTER TABLE stock_valuation_cases MODIFY COLUMN schema_version "
            "VARCHAR(64) NOT NULL DEFAULT 'valuation_case_v1'"
        ),
    }
    for column_name, sql in repair_sql.items():
        meta = columns.get(column_name) or {}
        if "longtext" not in meta.get("type", "").lower() or meta.get("default") is not None:
            continue
        try:
            c.execute(sql)
        except Exception:
            pass


def ensure_valuation_case_schema(connect_db: Callable[..., Any]) -> None:
    conn = connect_db()
    try:
        c = conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_cases (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   owner_user_id INTEGER,
                   stock_code VARCHAR(64) NOT NULL,
                   stock_name VARCHAR(191),
                   valuation_date VARCHAR(32),
                   title TEXT,
                   status VARCHAR(64) NOT NULL DEFAULT 'draft',
                   current_tab VARCHAR(64) NOT NULL DEFAULT 'profile',
                   schema_version VARCHAR(64) NOT NULL DEFAULT 'valuation_case_v1',
                   state_json TEXT NOT NULL DEFAULT '{}',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        _repair_short_text_defaults(c)
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_svc_owner_stock_updated ON "
            "stock_valuation_cases(owner_user_id, stock_code, updated_at DESC)"
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_case_facts (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   source VARCHAR(64) NOT NULL DEFAULT 'juyuan',
                   as_of VARCHAR(32),
                   completeness_score REAL,
                   facts_json TEXT NOT NULL,
                   warnings_json TEXT NOT NULL DEFAULT '[]',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_facts_case ON stock_valuation_case_facts(case_id, created_at DESC)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_method_decisions (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   methods_json TEXT NOT NULL,
                   weights_json TEXT NOT NULL DEFAULT '{}',
                   excluded_json TEXT NOT NULL DEFAULT '[]',
                   selected_primary VARCHAR(64),
                   rationale_json TEXT NOT NULL DEFAULT '[]',
                   source VARCHAR(64) NOT NULL DEFAULT 'rules',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_methods_case ON stock_valuation_method_decisions(case_id, updated_at DESC)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_assumptions (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   scenario_key VARCHAR(64) NOT NULL DEFAULT 'base',
                   assumption_key VARCHAR(128) NOT NULL,
                   label TEXT,
                   value REAL,
                   unit VARCHAR(32),
                   source VARCHAR(64) NOT NULL DEFAULT 'user',
                   evidence_text TEXT,
                   user_logic TEXT,
                   ai_challenge TEXT,
                   user_response TEXT,
                   status VARCHAR(64) NOT NULL DEFAULT 'draft',
                   confidence REAL,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(case_id, scenario_key, assumption_key))"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_assumptions_case ON stock_valuation_assumptions(case_id, scenario_key)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_scenarios (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   scenario_key VARCHAR(64) NOT NULL,
                   name TEXT NOT NULL,
                   assumptions_json TEXT NOT NULL DEFAULT '{}',
                   notes TEXT,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   UNIQUE(case_id, scenario_key))"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_scenarios_case ON stock_valuation_scenarios(case_id)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_scenario_results (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   scenario_key VARCHAR(64) NOT NULL,
                   engine_version VARCHAR(64),
                   result_json TEXT NOT NULL,
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_results_case ON stock_valuation_scenario_results(case_id, scenario_key, created_at DESC)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_ai_messages (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   turn_group VARCHAR(64),
                   tab_key VARCHAR(64),
                   role VARCHAR(32) NOT NULL,
                   content TEXT NOT NULL,
                   payload_json TEXT NOT NULL DEFAULT '{}',
                   related_field VARCHAR(128),
                   model VARCHAR(64),
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_ai_case ON stock_valuation_ai_messages(case_id, created_at)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_counter_evidence (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   title TEXT NOT NULL,
                   trigger_condition TEXT,
                   linked_assumption_key VARCHAR(128),
                   severity VARCHAR(32) DEFAULT 'medium',
                   status VARCHAR(64) DEFAULT 'open',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_counter_case ON stock_valuation_counter_evidence(case_id, status)")
        c.execute(
            """CREATE TABLE IF NOT EXISTS stock_valuation_case_events (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   case_id INTEGER NOT NULL,
                   event_type VARCHAR(64) NOT NULL,
                   payload_json TEXT NOT NULL DEFAULT '{}',
                   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_svc_events_case ON stock_valuation_case_events(case_id, created_at DESC)")
        conn.commit()
    finally:
        conn.close()


class ValuationCaseRepository:
    def __init__(self, connect_db: Callable[..., Any]):
        self.connect_db = connect_db

    def ensure_schema(self) -> None:
        ensure_valuation_case_schema(self.connect_db)

    def create_case(
        self,
        *,
        owner_user_id: int | None,
        stock_code: str,
        stock_name: str = "",
        valuation_date: str = "",
        title: str = "",
        facts: dict[str, Any] | None = None,
        warnings: list[Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        conn = self.connect_db()
        try:
            c = conn.cursor()
            case_state = state or default_case_state(stock_code=stock_code, stock_name=stock_name, valuation_date=valuation_date)
            c.execute(
                """INSERT INTO stock_valuation_cases
                   (owner_user_id, stock_code, stock_name, valuation_date, title, state_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (owner_user_id, stock_code, stock_name, valuation_date, title or f"{stock_code} {stock_name}".strip(), _json_dumps(case_state)),
            )
            case_id = int(c.lastrowid)
            if facts is not None:
                c.execute(
                    """INSERT INTO stock_valuation_case_facts
                       (case_id, source, as_of, completeness_score, facts_json, warnings_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        case_id,
                        "juyuan",
                        valuation_date,
                        float((case_state.get("data_quality") or {}).get("score") or 0),
                        _json_dumps(facts),
                        _json_dumps(warnings or []),
                    ),
                )
            c.execute(
                "INSERT INTO stock_valuation_case_events (case_id, event_type, payload_json) VALUES (?, ?, ?)",
                (case_id, "case_created", _json_dumps({"stock_code": stock_code, "valuation_date": valuation_date})),
            )
            conn.commit()
            return self.get_case(case_id, owner_user_id=owner_user_id) or {"id": case_id}
        finally:
            conn.close()

    def list_cases(self, *, owner_user_id: int | None, stock_code: str = "", limit: int = 30) -> list[dict[str, Any]]:
        self.ensure_schema()
        conn = self.connect_db(sqlite3.Row)
        try:
            c = conn.cursor()
            where = ["owner_user_id=?"]
            params: list[Any] = [owner_user_id]
            if stock_code:
                where.append("stock_code=?")
                params.append(stock_code)
            c.execute(
                f"""SELECT id, stock_code, stock_name, valuation_date, title, status, current_tab, created_at, updated_at
                    FROM stock_valuation_cases
                    WHERE {" AND ".join(where)}
                    ORDER BY updated_at DESC
                    LIMIT ?""",
                params + [max(1, min(int(limit or 30), 100))],
            )
            return [_row_to_dict(row) for row in c.fetchall()]
        finally:
            conn.close()

    def get_case(self, case_id: int, *, owner_user_id: int | None = None) -> dict[str, Any] | None:
        self.ensure_schema()
        conn = self.connect_db(sqlite3.Row)
        try:
            c = conn.cursor()
            where = ["id=?"]
            params: list[Any] = [case_id]
            if owner_user_id is not None:
                where.append("owner_user_id=?")
                params.append(owner_user_id)
            c.execute(
                f"""SELECT id, owner_user_id, stock_code, stock_name, valuation_date, title, status,
                           current_tab, schema_version, state_json, created_at, updated_at
                    FROM stock_valuation_cases
                    WHERE {" AND ".join(where)}
                    LIMIT 1""",
                params,
            )
            row = c.fetchone()
            if not row:
                return None
            case = _row_to_dict(row)
            case["state"] = _json_loads(case.pop("state_json", "{}"), {})
            case["facts_history"] = self._facts_history(c, case_id)
            case["method_decision"] = self._latest_method_decision(c, case_id)
            case["assumptions"] = self._assumptions(c, case_id)
            case["scenarios"] = self._scenarios(c, case_id)
            case["latest_results"] = self._latest_results(c, case_id)
            case["ai_messages"] = self._ai_messages(c, case_id)
            case["counter_evidence"] = self._counter_evidence(c, case_id)
            return case
        finally:
            conn.close()

    def delete_case(self, case_id: int, *, owner_user_id: int | None = None) -> bool:
        self.ensure_schema()
        conn = self.connect_db()
        try:
            c = conn.cursor()
            where = ["id=?"]
            params: list[Any] = [case_id]
            if owner_user_id is not None:
                where.append("owner_user_id=?")
                params.append(owner_user_id)
            c.execute(f"SELECT id FROM stock_valuation_cases WHERE {' AND '.join(where)} LIMIT 1", params)
            row = c.fetchone()
            if not row:
                return False
            child_tables = [
                "stock_valuation_case_facts",
                "stock_valuation_method_decisions",
                "stock_valuation_assumptions",
                "stock_valuation_scenarios",
                "stock_valuation_scenario_results",
                "stock_valuation_ai_messages",
                "stock_valuation_counter_evidence",
                "stock_valuation_case_events",
            ]
            for table in child_tables:
                c.execute(f"DELETE FROM {table} WHERE case_id=?", (case_id,))
            c.execute("DELETE FROM stock_valuation_cases WHERE id=?", (case_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    def save_state(self, case_id: int, state: dict[str, Any], *, owner_user_id: int | None = None, current_tab: str | None = None) -> dict[str, Any] | None:
        self.ensure_schema()
        conn = self.connect_db()
        try:
            c = conn.cursor()
            where = ["id=?"]
            params: list[Any] = [case_id]
            if owner_user_id is not None:
                where.append("owner_user_id=?")
                params.append(owner_user_id)
            tab = current_tab or (state or {}).get("ui", {}).get("active_tab") or "profile"
            c.execute(
                f"""UPDATE stock_valuation_cases
                    SET state_json=?, current_tab=?, updated_at=CURRENT_TIMESTAMP
                    WHERE {" AND ".join(where)}""",
                [_json_dumps(state or {}), tab] + params,
            )
            conn.commit()
            return self.get_case(case_id, owner_user_id=owner_user_id)
        finally:
            conn.close()

    def append_facts(self, case_id: int, *, facts: dict[str, Any], warnings: list[Any] | None = None, source: str = "juyuan", as_of: str = "", completeness_score: float = 0) -> None:
        self.ensure_schema()
        conn = self.connect_db()
        try:
            c = conn.cursor()
            c.execute(
                """INSERT INTO stock_valuation_case_facts
                   (case_id, source, as_of, completeness_score, facts_json, warnings_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (case_id, source, as_of, completeness_score, _json_dumps(facts), _json_dumps(warnings or [])),
            )
            c.execute(
                "INSERT INTO stock_valuation_case_events (case_id, event_type, payload_json) VALUES (?, ?, ?)",
                (case_id, "facts_appended", _json_dumps({"source": source, "as_of": as_of, "completeness_score": completeness_score})),
            )
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
        finally:
            conn.close()

    def save_method_decision(self, case_id: int, decision: dict[str, Any], *, source: str = "rules") -> None:
        self.ensure_schema()
        conn = self.connect_db()
        try:
            method_decision = decision.get("method_decision") or decision
            c = conn.cursor()
            c.execute(
                """INSERT INTO stock_valuation_method_decisions
                   (case_id, methods_json, weights_json, excluded_json, selected_primary, rationale_json, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    case_id,
                    _json_dumps(method_decision.get("secondary_methods") or method_decision.get("methods") or []),
                    _json_dumps(method_decision.get("weights") or {}),
                    _json_dumps(method_decision.get("unsuitable_methods") or method_decision.get("excluded") or []),
                    method_decision.get("primary_method") or "",
                    _json_dumps(method_decision.get("rationale") or []),
                    source,
                ),
            )
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
        finally:
            conn.close()

    def upsert_assumption(self, case_id: int, assumption: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        scenario_key = str(assumption.get("scenario_key") or "base")
        key = str(assumption.get("assumption_key") or assumption.get("key") or "").strip()
        if not key:
            raise ValueError("assumption_key is required")
        conn = self.connect_db(sqlite3.Row)
        try:
            c = conn.cursor()
            payload = {
                "label": assumption.get("label") or key,
                "value": assumption.get("value"),
                "unit": assumption.get("unit") or "",
                "source": assumption.get("source") or "user",
                "evidence_text": assumption.get("evidence_text") or "",
                "user_logic": assumption.get("user_logic") or "",
                "ai_challenge": assumption.get("ai_challenge") or "",
                "user_response": assumption.get("user_response") or "",
                "status": assumption.get("status") or "draft",
                "confidence": assumption.get("confidence"),
            }
            c.execute(
                "SELECT id FROM stock_valuation_assumptions WHERE case_id=? AND scenario_key=? AND assumption_key=?",
                (case_id, scenario_key, key),
            )
            existing = c.fetchone()
            if existing:
                c.execute(
                    """UPDATE stock_valuation_assumptions
                       SET label=?, value=?, unit=?, source=?, evidence_text=?, user_logic=?,
                           ai_challenge=?, user_response=?, status=?, confidence=?, updated_at=CURRENT_TIMESTAMP
                       WHERE case_id=? AND scenario_key=? AND assumption_key=?""",
                    (
                        payload["label"],
                        payload["value"],
                        payload["unit"],
                        payload["source"],
                        payload["evidence_text"],
                        payload["user_logic"],
                        payload["ai_challenge"],
                        payload["user_response"],
                        payload["status"],
                        payload["confidence"],
                        case_id,
                        scenario_key,
                        key,
                    ),
                )
            else:
                c.execute(
                    """INSERT INTO stock_valuation_assumptions
                       (case_id, scenario_key, assumption_key, label, value, unit, source, evidence_text,
                        user_logic, ai_challenge, user_response, status, confidence, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (
                        case_id,
                        scenario_key,
                        key,
                        payload["label"],
                        payload["value"],
                        payload["unit"],
                        payload["source"],
                        payload["evidence_text"],
                        payload["user_logic"],
                        payload["ai_challenge"],
                        payload["user_response"],
                        payload["status"],
                        payload["confidence"],
                    ),
                )
            c.execute(
                "INSERT INTO stock_valuation_case_events (case_id, event_type, payload_json) VALUES (?, ?, ?)",
                (case_id, "assumption_upserted", _json_dumps({"scenario_key": scenario_key, "assumption_key": key})),
            )
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
            c.execute(
                "SELECT * FROM stock_valuation_assumptions WHERE case_id=? AND scenario_key=? AND assumption_key=?",
                (case_id, scenario_key, key),
            )
            return _row_to_dict(c.fetchone())
        finally:
            conn.close()

    def add_ai_message(self, case_id: int, message: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        conn = self.connect_db(sqlite3.Row)
        try:
            c = conn.cursor()
            c.execute(
                """INSERT INTO stock_valuation_ai_messages
                   (case_id, turn_group, tab_key, role, content, payload_json, related_field, model)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    case_id,
                    message.get("turn_group") or "",
                    message.get("tab_key") or "assumptions",
                    message.get("role") or "assistant",
                    message.get("content") or "",
                    _json_dumps(message.get("payload") or {}),
                    message.get("related_field") or "",
                    message.get("model") or "",
                ),
            )
            msg_id = int(c.lastrowid)
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
            c.execute("SELECT * FROM stock_valuation_ai_messages WHERE id=?", (msg_id,))
            row = _row_to_dict(c.fetchone())
            row["payload"] = _json_loads(row.pop("payload_json", "{}"), {})
            return row
        finally:
            conn.close()

    def add_counter_evidence(self, case_id: int, item: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")
        conn = self.connect_db(sqlite3.Row)
        try:
            c = conn.cursor()
            c.execute(
                """INSERT INTO stock_valuation_counter_evidence
                   (case_id, title, trigger_condition, linked_assumption_key, severity, status, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    case_id,
                    title,
                    item.get("trigger_condition") or "",
                    item.get("linked_assumption_key") or "",
                    item.get("severity") or "medium",
                    item.get("status") or "open",
                ),
            )
            item_id = int(c.lastrowid)
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
            c.execute("SELECT * FROM stock_valuation_counter_evidence WHERE id=?", (item_id,))
            return _row_to_dict(c.fetchone())
        finally:
            conn.close()

    def save_scenario_result(self, case_id: int, scenario_key: str, result: dict[str, Any], *, engine_version: str = "") -> None:
        self.ensure_schema()
        conn = self.connect_db()
        try:
            c = conn.cursor()
            c.execute(
                """INSERT INTO stock_valuation_scenario_results
                   (case_id, scenario_key, engine_version, result_json)
                   VALUES (?, ?, ?, ?)""",
                (case_id, scenario_key, engine_version, _json_dumps(result)),
            )
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
        finally:
            conn.close()

    def upsert_scenario(self, case_id: int, scenario: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        scenario_key = str(scenario.get("scenario_key") or scenario.get("key") or "").strip()
        if not scenario_key:
            raise ValueError("scenario_key is required")
        conn = self.connect_db(sqlite3.Row)
        try:
            c = conn.cursor()
            name = scenario.get("name") or scenario_key
            assumptions = scenario.get("assumptions") or {}
            notes = scenario.get("notes") or ""
            c.execute(
                "SELECT id FROM stock_valuation_scenarios WHERE case_id=? AND scenario_key=?",
                (case_id, scenario_key),
            )
            if c.fetchone():
                c.execute(
                    """UPDATE stock_valuation_scenarios
                       SET name=?, assumptions_json=?, notes=?, updated_at=CURRENT_TIMESTAMP
                       WHERE case_id=? AND scenario_key=?""",
                    (name, _json_dumps(assumptions), notes, case_id, scenario_key),
                )
            else:
                c.execute(
                    """INSERT INTO stock_valuation_scenarios
                       (case_id, scenario_key, name, assumptions_json, notes, updated_at)
                       VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                    (case_id, scenario_key, name, _json_dumps(assumptions), notes),
                )
            c.execute(
                "INSERT INTO stock_valuation_case_events (case_id, event_type, payload_json) VALUES (?, ?, ?)",
                (case_id, "scenario_upserted", _json_dumps({"scenario_key": scenario_key})),
            )
            c.execute("UPDATE stock_valuation_cases SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
            conn.commit()
            c.execute(
                "SELECT * FROM stock_valuation_scenarios WHERE case_id=? AND scenario_key=?",
                (case_id, scenario_key),
            )
            row = _row_to_dict(c.fetchone())
            row["assumptions"] = _json_loads(row.pop("assumptions_json", "{}"), {})
            return row
        finally:
            conn.close()

    def _facts_history(self, c: Any, case_id: int) -> list[dict[str, Any]]:
        c.execute(
            """SELECT id, source, as_of, completeness_score, facts_json, warnings_json, created_at
               FROM stock_valuation_case_facts WHERE case_id=? ORDER BY created_at DESC LIMIT 10""",
            (case_id,),
        )
        rows = []
        for row in c.fetchall():
            item = _row_to_dict(row)
            item["facts"] = _json_loads(item.pop("facts_json", "{}"), {})
            item["warnings"] = _json_loads(item.pop("warnings_json", "[]"), [])
            rows.append(item)
        return rows

    def _latest_method_decision(self, c: Any, case_id: int) -> dict[str, Any]:
        c.execute(
            """SELECT * FROM stock_valuation_method_decisions
               WHERE case_id=? ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (case_id,),
        )
        row = c.fetchone()
        if not row:
            return {}
        item = _row_to_dict(row)
        item["methods"] = _json_loads(item.pop("methods_json", "[]"), [])
        item["weights"] = _json_loads(item.pop("weights_json", "{}"), {})
        item["excluded"] = _json_loads(item.pop("excluded_json", "[]"), [])
        item["rationale"] = _json_loads(item.pop("rationale_json", "[]"), [])
        return item

    def _assumptions(self, c: Any, case_id: int) -> list[dict[str, Any]]:
        c.execute(
            """SELECT * FROM stock_valuation_assumptions
               WHERE case_id=? ORDER BY scenario_key, assumption_key""",
            (case_id,),
        )
        return [_row_to_dict(row) for row in c.fetchall()]

    def _scenarios(self, c: Any, case_id: int) -> list[dict[str, Any]]:
        c.execute(
            "SELECT * FROM stock_valuation_scenarios WHERE case_id=? ORDER BY scenario_key",
            (case_id,),
        )
        rows = []
        for row in c.fetchall():
            item = _row_to_dict(row)
            item["assumptions"] = _json_loads(item.pop("assumptions_json", "{}"), {})
            rows.append(item)
        return rows

    def _latest_results(self, c: Any, case_id: int) -> list[dict[str, Any]]:
        c.execute(
            """SELECT r.*
               FROM stock_valuation_scenario_results r
               INNER JOIN (
                   SELECT scenario_key, MAX(id) AS id
                   FROM stock_valuation_scenario_results
                   WHERE case_id=?
                   GROUP BY scenario_key
               ) latest ON latest.id = r.id
               ORDER BY r.scenario_key""",
            (case_id,),
        )
        rows = []
        for row in c.fetchall():
            item = _row_to_dict(row)
            item["result"] = _json_loads(item.pop("result_json", "{}"), {})
            rows.append(item)
        return rows

    def _ai_messages(self, c: Any, case_id: int) -> list[dict[str, Any]]:
        c.execute(
            """SELECT * FROM stock_valuation_ai_messages
               WHERE case_id=? ORDER BY created_at ASC, id ASC LIMIT 200""",
            (case_id,),
        )
        rows = []
        for row in c.fetchall():
            item = _row_to_dict(row)
            item["payload"] = _json_loads(item.pop("payload_json", "{}"), {})
            rows.append(item)
        return rows

    def _counter_evidence(self, c: Any, case_id: int) -> list[dict[str, Any]]:
        c.execute(
            """SELECT * FROM stock_valuation_counter_evidence
               WHERE case_id=? ORDER BY created_at ASC, id ASC""",
            (case_id,),
        )
        return [_row_to_dict(row) for row in c.fetchall()]


def default_case_state(*, stock_code: str = "", stock_name: str = "", valuation_date: str = "") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ui": {"active_tab": "profile", "dirty": False},
        "identity": {"stock_code": stock_code, "stock_name": stock_name, "valuation_date": valuation_date},
        "workflow": {
            "completed_tabs": [],
            "unlocked_tabs": ["profile"],
            "last_completed_tab": "",
        },
        "tabs": {
            "profile": {"loaded": False, "notes": "", "manual_fields": {}},
            "methods": {"selected_primary": "", "weights": {}, "excluded": [], "generated_at": ""},
            "assumptions": {"active_scenario": "base", "items": {}, "logic": "", "saved_at": ""},
            "scenarios": {"active": "base", "items": ["bear", "base", "bull"], "drafts": {}, "last_run_at": ""},
            "conclusion": {"stance": "draft", "summary": "", "counter_evidence_ids": []},
            "cases": {"compare_case_ids": []},
        },
        "data_quality": {"score": 0, "missing_fields": [], "dates": {}},
    }
