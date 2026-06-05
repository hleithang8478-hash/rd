import base64
import gzip
import io
import json
import logging
import os
import secrets
import time
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pandas as pd
from flask import jsonify, request


logger = logging.getLogger(__name__)

BRIDGE_PATH_PREFIX = "/internal/juyuan_bridge"
_APP_DB_CONNECT = None
_APP_DB_BACKEND = "sqlite"
_TABLES_ENSURED: set[str] = set()  # cache per db_path so DDL only runs once per process
_CLEANUP_LOCK = threading.Lock()
_LAST_CLEANUP_AT = 0.0


def configure_juyuan_bridge_database(connect_func=None, *, backend: str = "sqlite") -> None:
    """Let the main app provide its configured database connection."""
    global _APP_DB_CONNECT, _APP_DB_BACKEND
    _APP_DB_CONNECT = connect_func
    _APP_DB_BACKEND = (backend or "sqlite").strip().lower()
    _TABLES_ENSURED.clear()


def _use_app_database() -> bool:
    return _APP_DB_CONNECT is not None and _APP_DB_BACKEND in ("mysql", "mysql8")


def _is_mysql_backend() -> bool:
    return _APP_DB_BACKEND in ("mysql", "mysql8")


def _connect_bridge_db(db_path: Optional[str] = None, *, isolation_level: Optional[str] = None):
    if _use_app_database():
        return _APP_DB_CONNECT()
    raise RuntimeError(
        "juyuan_bridge: MySQL 连接函数未注入，请先调用 configure_juyuan_bridge_database()。"
        " SQLite 回退已停用，当前仅支持 MySQL 后端。"
    )


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_db_path() -> str:
    root = os.path.dirname(os.path.abspath(__file__))
    raw = os.environ.get("APP_DATABASE_FILE") or os.path.join(root, "database.db")
    return raw if os.path.isabs(raw) else os.path.join(root, raw)


def _json_default(value: Any) -> Any:
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _params_to_json(params: Any) -> str:
    if params is None:
        data = []
    elif isinstance(params, tuple):
        data = list(params)
    elif isinstance(params, list):
        data = params
    else:
        data = [params]
    return json.dumps(data, ensure_ascii=False, default=_json_default)


def _params_from_json(raw: Optional[str]) -> list:
    if not raw:
        return []
    data = json.loads(raw)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data]


def _date_param_text(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip().strip('"').strip("'")
    if len(text) >= 10:
        candidate = text[:10]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass
    if len(text) == 8 and text.isdigit():
        try:
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        except ValueError:
            return None
    return None


def normalize_juyuan_bridge_params(sql: str, params: Any) -> list:
    if params is None:
        fixed: list[Any] = []
    elif isinstance(params, tuple):
        fixed = list(params)
    elif isinstance(params, list):
        fixed = list(params)
    else:
        fixed = [params]

    sql_upper = (sql or "").upper()
    date_pos = sql_upper.find("CAST(? AS DATE)")
    in_pos = sql_upper.find(" IN (")
    if fixed and date_pos >= 0 and in_pos >= 0:
        first_dates = [_date_param_text(value) for value in fixed[:2]]
        last_dates = [_date_param_text(value) for value in fixed[-2:]]
        date_params_should_be_first = date_pos < in_pos
        if date_params_should_be_first:
            if len(fixed) >= 4 and all(last_dates) and not all(first_dates):
                logger.warning("Juyuan bridge fixed param order: date params were at the end")
                fixed = last_dates + fixed[:-2]
            elif all(first_dates):
                fixed[:2] = first_dates
            else:
                logger.warning(
                    "Juyuan bridge date params look invalid: first2=%r last2=%r",
                    fixed[:2],
                    fixed[-2:],
                )
        elif len(fixed) >= 4 and all(first_dates) and not all(last_dates):
            logger.warning("Juyuan bridge fixed param order: date params were at the front")
            fixed = fixed[2:] + first_dates
        elif all(last_dates):
            fixed[-2:] = last_dates
        else:
            logger.warning(
                "Juyuan bridge date params look invalid: first2=%r last2=%r",
                fixed[:2],
                fixed[-2:],
            )
    return fixed


def serialize_dataframe(df: pd.DataFrame) -> str:
    if df is None:
        df = pd.DataFrame()
    json_text = df.to_json(orient="split", date_format="iso", force_ascii=False, default_handler=str)
    compressed = gzip.compress(json_text.encode("utf-8"))
    return base64.b64encode(compressed).decode("ascii")


def deserialize_dataframe(payload: str) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame()
    raw = gzip.decompress(base64.b64decode(payload.encode("ascii"))).decode("utf-8")
    return pd.read_json(io.StringIO(raw), orient="split")


def _assemble_result_payload(c, job_id: int, inline_payload: Optional[str] = None) -> str:
    if inline_payload:
        return inline_payload
    c.execute(
        """SELECT chunk_text FROM juyuan_bridge_result_chunks
           WHERE job_id=? ORDER BY chunk_index ASC""",
        (job_id,),
    )
    return "".join(str(row[0] or "") for row in c.fetchall())


def _delete_result_chunks(c, job_id: int) -> int:
    c.execute("DELETE FROM juyuan_bridge_result_chunks WHERE job_id=?", (job_id,))
    return int(c.rowcount or 0)


def _execute_bridge_index_ddl(c, sql: str) -> None:
    try:
        c.execute(sql)
    except Exception as exc:
        msg = str(exc).lower()
        if any(token in msg for token in ("duplicate key name", "already exists", "duplicate column name")):
            return
        raise


def ensure_juyuan_bridge_tables_with_cursor(c) -> None:
    if _is_mysql_backend():
        c.execute(
            """CREATE TABLE IF NOT EXISTS juyuan_bridge_jobs (
                   id BIGINT NOT NULL AUTO_INCREMENT,
                   status VARCHAR(32) NOT NULL DEFAULT 'pending',
                   sql_text LONGTEXT NOT NULL,
                   params_json LONGTEXT NULL,
                   result_payload LONGTEXT NULL,
                   error_message LONGTEXT NULL,
                   row_count BIGINT NULL,
                   worker_id VARCHAR(128) NULL,
                   attempt_count INT NOT NULL DEFAULT 0,
                   timeout_seconds INT NOT NULL DEFAULT 900,
                   client_label VARCHAR(128) NULL,
                   created_at VARCHAR(32) NOT NULL,
                   picked_at VARCHAR(32) NULL,
                   finished_at VARCHAR(32) NULL,
                   updated_at VARCHAR(32) NOT NULL,
                   PRIMARY KEY (id)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS juyuan_bridge_result_chunks (
                   job_id BIGINT NOT NULL,
                   chunk_index INT NOT NULL,
                   chunk_text LONGTEXT NOT NULL,
                   created_at VARCHAR(32) NOT NULL,
                   PRIMARY KEY (job_id, chunk_index)
               ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
        )
        _execute_bridge_index_ddl(c, "CREATE INDEX idx_juyuan_bridge_status ON juyuan_bridge_jobs(status, created_at)")
        _execute_bridge_index_ddl(c, "CREATE INDEX idx_juyuan_bridge_claim ON juyuan_bridge_jobs(status, id)")
        _execute_bridge_index_ddl(c, "CREATE INDEX idx_juyuan_bridge_worker ON juyuan_bridge_jobs(worker_id, status)")
        _execute_bridge_index_ddl(c, "CREATE INDEX idx_juyuan_bridge_stale ON juyuan_bridge_jobs(status, picked_at)")
        _execute_bridge_index_ddl(c, "CREATE INDEX idx_juyuan_bridge_chunks_job ON juyuan_bridge_result_chunks(job_id)")
        return

    c.execute(
        """CREATE TABLE IF NOT EXISTS juyuan_bridge_jobs (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               status TEXT NOT NULL DEFAULT 'pending',
               sql_text TEXT NOT NULL,
               params_json TEXT,
               result_payload TEXT,
               error_message TEXT,
               row_count INTEGER,
               worker_id TEXT,
               attempt_count INTEGER NOT NULL DEFAULT 0,
               timeout_seconds INTEGER NOT NULL DEFAULT 900,
               client_label TEXT,
               created_at TEXT NOT NULL,
               picked_at TEXT,
               finished_at TEXT,
               updated_at TEXT NOT NULL
           )"""
    )
    c.execute(
        """CREATE TABLE IF NOT EXISTS juyuan_bridge_result_chunks (
               job_id INTEGER NOT NULL,
               chunk_index INTEGER NOT NULL,
               chunk_text TEXT NOT NULL,
               created_at TEXT NOT NULL,
               PRIMARY KEY (job_id, chunk_index)
           )"""
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_juyuan_bridge_status ON juyuan_bridge_jobs(status, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_juyuan_bridge_claim ON juyuan_bridge_jobs(status, id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_juyuan_bridge_worker ON juyuan_bridge_jobs(worker_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_juyuan_bridge_stale ON juyuan_bridge_jobs(status, picked_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_juyuan_bridge_chunks_job ON juyuan_bridge_result_chunks(job_id)")


def ensure_juyuan_bridge_tables(db_path: Optional[str] = None) -> None:
    db = db_path or _default_db_path()
    if db in _TABLES_ENSURED:
        return
    conn = _connect_bridge_db(db)
    try:
        c = conn.cursor()
        ensure_juyuan_bridge_tables_with_cursor(c)
        conn.commit()
    finally:
        conn.close()
    _TABLES_ENSURED.add(db)


def enqueue_query(
    sql: str,
    params: Any = None,
    *,
    db_path: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    client_label: str = "main-app",
) -> int:
    db = db_path or _default_db_path()
    ensure_juyuan_bridge_tables(db)
    params = normalize_juyuan_bridge_params(sql, params)
    timeout_seconds = int(timeout_seconds or os.getenv("JUYUAN_BRIDGE_TIMEOUT_SECONDS", "900"))
    conn = _connect_bridge_db(db)
    try:
        c = conn.cursor()
        now = _now_text()
        c.execute(
            """INSERT INTO juyuan_bridge_jobs
               (status, sql_text, params_json, timeout_seconds, client_label, created_at, updated_at)
               VALUES ('pending', ?, ?, ?, ?, ?, ?)""",
            (sql, _params_to_json(params), timeout_seconds, client_label, now, now),
        )
        conn.commit()
        return int(c.lastrowid)
    finally:
        conn.close()


def wait_for_job(job_id: int, *, db_path: Optional[str] = None, timeout_seconds: Optional[int] = None) -> pd.DataFrame:
    db = db_path or _default_db_path()
    timeout_seconds = int(timeout_seconds or os.getenv("JUYUAN_BRIDGE_TIMEOUT_SECONDS", "900"))
    poll_interval = float(os.getenv("JUYUAN_BRIDGE_RESULT_POLL_SECONDS", "0.5"))
    deadline = time.time() + timeout_seconds
    last_status = None
    while time.time() < deadline:
        conn = _connect_bridge_db(db)
        try:
            c = conn.cursor()
            c.execute(
                "SELECT status, result_payload, error_message FROM juyuan_bridge_jobs WHERE id=?",
                (job_id,),
            )
            row = c.fetchone()
        finally:
            conn.close()
        if not row:
            raise RuntimeError(f"Juyuan bridge job {job_id} not found")
        status, result_payload, error_message = row
        if status != last_status:
            logger.debug("Juyuan bridge job %s status=%s", job_id, status)
            last_status = status
        if status == "success":
            conn = _connect_bridge_db(db)
            try:
                c = conn.cursor()
                payload = _assemble_result_payload(c, job_id, result_payload)
                df = deserialize_dataframe(payload)
                try:
                    deleted_chunks = _delete_result_chunks(c, job_id)
                    if deleted_chunks:
                        conn.commit()
                        logger.debug("Deleted Juyuan bridge result chunks job_id=%s chunks=%s", job_id, deleted_chunks)
                except Exception as exc:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logger.warning("Failed to delete Juyuan bridge result chunks job_id=%s: %s", job_id, exc)
            finally:
                conn.close()
            return df
        if status == "error":
            raise RuntimeError(error_message or f"Juyuan bridge job {job_id} failed")
        time.sleep(poll_interval)

    conn = _connect_bridge_db(db)
    try:
        c = conn.cursor()
        c.execute(
            """UPDATE juyuan_bridge_jobs
               SET status='error', error_message=?, updated_at=?
               WHERE id=? AND status IN ('pending', 'running')""",
            (f"Timed out waiting {timeout_seconds}s for Juyuan worker", _now_text(), job_id),
        )
        conn.commit()
    finally:
        conn.close()
    raise TimeoutError(f"Timed out waiting {timeout_seconds}s for Juyuan worker")


def execute_query_via_bridge(sql: str, params: Any = None, *, timeout_seconds: Optional[int] = None) -> pd.DataFrame:
    db = _default_db_path()
    job_id = enqueue_query(sql, params, db_path=db, timeout_seconds=timeout_seconds)
    logger.info("Queued Juyuan bridge job %s", job_id)
    return wait_for_job(job_id, db_path=db, timeout_seconds=timeout_seconds)


def claim_next_job(db_path: str, worker_id: str) -> Optional[dict]:
    ensure_juyuan_bridge_tables(db_path)
    stale_seconds = int(os.getenv("JUYUAN_BRIDGE_STALE_SECONDS", "1800"))
    stale_before = (datetime.now() - timedelta(seconds=stale_seconds)).isoformat(timespec="seconds")
    now = _now_text()
    conn = _connect_bridge_db(db_path, isolation_level=None)
    try:
        c = conn.cursor()
        if not _use_app_database():
            c.execute("BEGIN IMMEDIATE")
        else:
            c.execute("START TRANSACTION")
        c.execute(
            """UPDATE juyuan_bridge_jobs
               SET status='pending', worker_id=NULL, updated_at=?
               WHERE status='running' AND picked_at IS NOT NULL AND picked_at < ?""",
            (now, stale_before),
        )
        if _use_app_database():
            select_sql = """SELECT id, sql_text, params_json, timeout_seconds
                            FROM juyuan_bridge_jobs FORCE INDEX (idx_juyuan_bridge_claim)
                            WHERE status='pending'
                            ORDER BY id ASC
                            LIMIT 1"""
            select_sql += " FOR UPDATE SKIP LOCKED"
        else:
            select_sql = """SELECT id, sql_text, params_json, timeout_seconds
                            FROM juyuan_bridge_jobs
                            WHERE status='pending'
                            ORDER BY id ASC
                            LIMIT 1"""
        c.execute(select_sql)
        row = c.fetchone()
        if not row:
            conn.commit()
            return None
        job_id, sql_text, params_json, timeout_seconds = row
        c.execute(
            """UPDATE juyuan_bridge_jobs
               SET status='running', worker_id=?, picked_at=?, updated_at=?,
                   attempt_count=attempt_count + 1
               WHERE id=?""",
            (worker_id, now, now, job_id),
        )
        conn.commit()
        return {
            "id": int(job_id),
            "sql": sql_text,
            "params": normalize_juyuan_bridge_params(sql_text, _params_from_json(params_json)),
            "timeout_seconds": int(timeout_seconds or 900),
        }
    except Exception as exc:
        if _use_app_database():
            msg = str(exc).lower()
            transient_tokens = (
                "deadlock",
                "try restarting transaction",
                "lost connection",
                "timed out",
                "timeout",
                "lock wait timeout",
                "server has gone away",
            )
            if any(token in msg for token in transient_tokens):
                logger.warning("Juyuan bridge claim transient database error, will retry: %s", exc)
                try:
                    conn.rollback()
                except Exception:
                    pass
                return None
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def complete_job(
    db_path: str,
    job_id: int,
    *,
    success: bool,
    result_payload: Optional[str] = None,
    error_message: Optional[str] = None,
    row_count: Optional[int] = None,
    worker_id: Optional[str] = None,
) -> None:
    ensure_juyuan_bridge_tables(db_path)
    status = "success" if success else "error"
    conn = _connect_bridge_db(db_path)
    try:
        c = conn.cursor()
        c.execute(
            """UPDATE juyuan_bridge_jobs
               SET status=?, result_payload=?, error_message=?, row_count=?,
                   worker_id=COALESCE(?, worker_id), finished_at=?, updated_at=?
               WHERE id=?""",
            (status, result_payload, error_message, row_count, worker_id, _now_text(), _now_text(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def store_result_chunk(
    db_path: str,
    job_id: int,
    *,
    chunk_index: int,
    chunk_text: str,
    worker_id: Optional[str] = None,
) -> None:
    ensure_juyuan_bridge_tables(db_path)
    conn = _connect_bridge_db(db_path)
    try:
        c = conn.cursor()
        now = _now_text()
        c.execute(
            """INSERT OR REPLACE INTO juyuan_bridge_result_chunks
               (job_id, chunk_index, chunk_text, created_at)
               VALUES (?, ?, ?, ?)""",
            (job_id, int(chunk_index), chunk_text or "", now),
        )
        c.execute(
            """UPDATE juyuan_bridge_jobs
               SET worker_id=COALESCE(?, worker_id), updated_at=?
               WHERE id=?""",
            (worker_id, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _chunks(seq: list[int], size: int):
    for start in range(0, len(seq), size):
        yield seq[start:start + size]


def cleanup_old_jobs(
    db_path: Optional[str] = None,
    keep_days: Optional[int] = None,
    *,
    batch_size: Optional[int] = None,
) -> int:
    db = db_path or _default_db_path()
    ensure_juyuan_bridge_tables(db)
    keep_days = int(keep_days or os.getenv("JUYUAN_BRIDGE_KEEP_DAYS", "7"))
    batch_size = max(1, int(batch_size or os.getenv("JUYUAN_BRIDGE_CLEANUP_BATCH_JOBS", "500")))
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    conn = _connect_bridge_db(db)
    try:
        c = conn.cursor()
        deleted = 0
        while True:
            c.execute(
                """SELECT id FROM juyuan_bridge_jobs
                   WHERE status IN ('success', 'error') AND updated_at < ?
                   ORDER BY id ASC
                   LIMIT ?""",
                (cutoff, batch_size),
            )
            ids = [int(row[0]) for row in c.fetchall()]
            if not ids:
                break
            placeholders = ",".join(["?"] * len(ids))
            c.execute(f"DELETE FROM juyuan_bridge_result_chunks WHERE job_id IN ({placeholders})", tuple(ids))
            c.execute(f"DELETE FROM juyuan_bridge_jobs WHERE id IN ({placeholders})", tuple(ids))
            deleted += int(c.rowcount or 0)
            conn.commit()

        while True:
            c.execute(
                """SELECT c.job_id
                   FROM juyuan_bridge_result_chunks c
                   LEFT JOIN juyuan_bridge_jobs j ON j.id = c.job_id
                   WHERE j.id IS NULL
                   GROUP BY c.job_id
                   LIMIT ?""",
                (batch_size,),
            )
            ids = [int(row[0]) for row in c.fetchall()]
            if not ids:
                break
            for part in _chunks(ids, batch_size):
                placeholders = ",".join(["?"] * len(part))
                c.execute(
                    f"DELETE FROM juyuan_bridge_result_chunks WHERE job_id IN ({placeholders})",
                    tuple(part),
                )
            conn.commit()
        return deleted
    finally:
        conn.close()


def cleanup_old_jobs_maybe(db_path: Optional[str] = None) -> None:
    interval = int(os.getenv("JUYUAN_BRIDGE_CLEANUP_INTERVAL_SECONDS", "3600") or 3600)
    if interval <= 0:
        return
    global _LAST_CLEANUP_AT
    now = time.time()
    if now - _LAST_CLEANUP_AT < interval:
        return

    with _CLEANUP_LOCK:
        if now - _LAST_CLEANUP_AT < interval:
            return
        _LAST_CLEANUP_AT = now

    def _run():
        try:
            deleted = cleanup_old_jobs(db_path)
            if deleted:
                logger.info("Cleaned old Juyuan bridge jobs: deleted_jobs=%s", deleted)
        except Exception as exc:
            logger.warning("Juyuan bridge background cleanup failed: %s", exc, exc_info=True)

    threading.Thread(target=_run, name="juyuan-bridge-cleanup", daemon=True).start()


def get_queue_status(db_path: Optional[str] = None) -> dict:
    db = db_path or _default_db_path()
    ensure_juyuan_bridge_tables(db)
    conn = _connect_bridge_db(db)
    try:
        c = conn.cursor()
        c.execute("SELECT status, COUNT(*) FROM juyuan_bridge_jobs GROUP BY status")
        counts = {str(k): int(v or 0) for k, v in c.fetchall()}
        c.execute("SELECT MAX(updated_at) FROM juyuan_bridge_jobs")
        row = c.fetchone()
        return {
            "counts": counts,
            "last_updated_at": row[0] if row else None,
        }
    finally:
        conn.close()


def _bridge_auth_error():
    token = os.getenv("JUYUAN_BRIDGE_TOKEN", "").strip()
    if not token:
        return jsonify({"success": False, "error": "JUYUAN_BRIDGE_TOKEN is not configured"}), 503
    provided = (
        request.headers.get("X-Juyuan-Bridge-Token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.args.get("token", "")
    )
    if not provided or not secrets.compare_digest(provided, token):
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return None


def register_juyuan_bridge_routes(app, db_path: str) -> None:
    @app.route(f"{BRIDGE_PATH_PREFIX}/health", methods=["GET"])
    def juyuan_bridge_health():
        auth = _bridge_auth_error()
        if auth:
            return auth
        return jsonify({
            "success": True,
            "time": _now_text(),
            "queue": get_queue_status(db_path),
            "capabilities": {
                "result_chunk": True,
                "result_chunk_table": "juyuan_bridge_result_chunks",
            },
        })

    @app.route(f"{BRIDGE_PATH_PREFIX}/jobs/next", methods=["GET"])
    def juyuan_bridge_next_job():
        auth = _bridge_auth_error()
        if auth:
            return auth
        cleanup_old_jobs_maybe(db_path)
        worker_id = (request.args.get("worker_id") or "worker").strip()[:128]
        job = claim_next_job(db_path, worker_id)
        return jsonify({"success": True, "job": job})

    @app.route(f"{BRIDGE_PATH_PREFIX}/jobs/<int:job_id>/result", methods=["POST"])
    def juyuan_bridge_post_result(job_id: int):
        auth = _bridge_auth_error()
        if auth:
            return auth
        body = request.get_json(silent=True) or {}
        worker_id = (body.get("worker_id") or "").strip()[:128] or None
        success = bool(body.get("success"))
        complete_job(
            db_path,
            job_id,
            success=success,
            result_payload=body.get("result_payload"),
            error_message=body.get("error_message"),
            row_count=body.get("row_count"),
            worker_id=worker_id,
        )
        return jsonify({"success": True})

    @app.route(f"{BRIDGE_PATH_PREFIX}/jobs/<int:job_id>/result_chunk", methods=["POST"])
    def juyuan_bridge_post_result_chunk(job_id: int):
        auth = _bridge_auth_error()
        if auth:
            return auth
        body = request.get_json(silent=True) or {}
        worker_id = (body.get("worker_id") or "").strip()[:128] or None
        store_result_chunk(
            db_path,
            job_id,
            chunk_index=int(body.get("chunk_index") or 0),
            chunk_text=body.get("chunk_text") or "",
            worker_id=worker_id,
        )
        return jsonify({"success": True})
