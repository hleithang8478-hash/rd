# -*- coding: utf-8 -*-
"""ReviewsDaily Flask application entrypoint.

The legacy application used to live entirely in this file. It is now split into
`app_modules/sections/` for core/bootstrap code and `app_modules/routes/` for
business routes. Legacy-compatible files are still executed in this module's
global namespace and original dependency order. That keeps endpoint names,
decorators, globals, and project-root paths compatible with the old app.py.
"""
from pathlib import Path

from env_loader import load_env_file


_APP_ENTRY_FILE = Path(__file__).resolve()
load_env_file(_APP_ENTRY_FILE.parent / ".env")
_APP_SECTION_DIR = _APP_ENTRY_FILE.parent / "app_modules" / "sections"
_APP_ROUTE_DIR = _APP_ENTRY_FILE.parent / "app_modules" / "routes"
_APP_SECTION_FILES = (
    "00_imports_logging_ai.py",
    "01_plan_text_research_helpers.py",
    "02_app_config_db_compat.py",
    "03_security_rbac_init_db.py",
)
_APP_ROUTE_FILES = (
    "base_reviews.py",
    "calendar_daily_dashboard.py",
    "plans_graph_market.py",
    "reports_pdf_reader.py",
    "reports_compare_links.py",
    "concepts_sentiment_jobs.py",
    "topics_inventory.py",
    "data_query.py",
    "portfolio_analysis.py",
    "crawler_morning_brief.py",
    "crawler_dashboard_wordcloud.py",
    "ai_settings.py",
)


def _exec_legacy_files(base_dir, file_names):
    """Execute split legacy files inside this module, preserving root paths."""
    global __file__
    original_file = __file__
    __file__ = str(_APP_ENTRY_FILE)
    try:
        for file_name in file_names:
            file_path = base_dir / file_name
            source = file_path.read_text(encoding="utf-8")
            code = compile(source, str(file_path), "exec")
            exec(code, globals(), globals())
    finally:
        __file__ = original_file


_exec_legacy_files(_APP_SECTION_DIR, _APP_SECTION_FILES)
_exec_legacy_files(_APP_ROUTE_DIR, _APP_ROUTE_FILES)

from app_modules.routes.admin_rbac import register_admin_rbac_routes
from app_modules.routes.ai_research_assistant import register_ai_research_assistant_routes
from app_modules.routes.ai_settings import register_ai_settings_routes
from app_modules.routes.data_center import register_data_center_routes
from app_modules.routes.gru_tasks import register_gru_task_routes
from app_modules.routes.iching_divination import register_iching_divination_routes
from app_modules.routes.epub_reader import register_epub_reader_routes
from app_modules.routes.experience_lessons import register_experience_lessons_routes
from app_modules.routes.momentum_scores import register_momentum_score_routes
from app_modules.routes.screening_tasks import register_screening_task_routes
from app_modules.routes.stock_holding_costs import register_stock_holding_cost_routes
from app_modules.routes.stock_valuation import register_stock_valuation_routes
from app_modules.routes.thinking_kelly import register_thinking_kelly_routes
from app_modules.routes.timeline_search_export import register_timeline_search_export_routes
from app_modules.routes.trading_agents import register_trading_agent_routes

register_screening_task_routes(app, globals())
register_admin_rbac_routes(app, globals())
register_ai_research_assistant_routes(app, globals())
register_ai_settings_routes(app, globals())
register_iching_divination_routes(app, globals())
register_epub_reader_routes(app, globals())
register_experience_lessons_routes(app, globals())
register_data_center_routes(app, globals())
register_momentum_score_routes(app, globals())
register_stock_holding_cost_routes(app, globals())
register_stock_valuation_routes(app, globals())
register_gru_task_routes(app, globals())
register_thinking_kelly_routes(app, globals())
register_timeline_search_export_routes(app, globals())
register_trading_agent_routes(app, globals())

try:
    from screening_tasks import configure_app_db_connect as _configure_screening_db
    from screening_tasks import ensure_screening_storage as _ensure_screening_storage

    _configure_screening_db(get_sqlite_connection)
    _ensure_screening_storage()
except Exception as _screening_init_err:  # pragma: no cover - 启动诊断
    import logging as _screening_logging

    _screening_logging.warning("初始化 screening_tasks 数据库存储失败：%s", _screening_init_err, exc_info=True)

# GRU 任务（功能 19 子模块 5/6/7/10）依赖注入：复用主库连接和默认 owner 兜底
def _gru_tasks_default_owner_user_id():
    """Return the project's default owner_user_id by reusing the existing helper."""
    fn = globals().get("_default_owner_user_id_from_cursor")
    if not callable(fn):
        return None
    conn_factory = globals().get("get_sqlite_connection")
    if not callable(conn_factory):
        return None
    try:
        conn = conn_factory()
        try:
            return fn(conn.cursor())
        finally:
            conn.close()
    except Exception:
        return None


try:
    from gru_tasks import configure_gru_tasks as _configure_gru_tasks

    _configure_gru_tasks(
        connect_db=get_sqlite_connection,
        app_mysql_config=globals().get("APP_MYSQL_CONFIG", {}),
        default_owner_user_id=_gru_tasks_default_owner_user_id,
    )
except Exception as _gru_init_err:  # pragma: no cover - 启动诊断
    import logging as _gru_logging

    _gru_logging.warning("初始化 gru_tasks 失败（功能 19 子模块将不可用）: %s", _gru_init_err)


if __name__ == "__main__":
    _main_path = _APP_SECTION_DIR / "99_main.py"
    _main_code = compile(_main_path.read_text(encoding="utf-8"), str(_main_path), "exec")
    exec(_main_code, globals(), globals())
