# Valuation Anchor Backend Package

Generated: 20260605_130915
Project root: C:\Users\tanjiarong\Desktop\ReviewsDaily

Purpose: backend files for the ReviewsDaily stock valuation / valuation anchor module.

Included files:
- app_modules\routes\stock_valuation.py
- app_modules\services\valuation_ai_coach.py
- app_modules\services\valuation_engine.py
- app_modules\services\valuation_fact_cache.py
- app_modules\services\valuation_repository.py
- app_modules\routes\data_query.py
- app_modules\services\stock_master_cache.py
- app.py
- app_modules\README.md
- app_modules\sections\00_imports_logging_ai.py
- app_modules\sections\02_app_config_db_compat.py
- app_modules\sections\03_security_rbac_init_db.py
- data_fetcher.py
- juyuan_bridge.py
- juyuan_config.py
- config.py
- db_schema.py
- env_loader.py
- requirements.txt
- tests\test_stock_valuation.py
- tests\test_stock_cache_services.py

Primary route/API surface:
- GET /stock_valuation
- /api/stock_valuation/config
- /api/stock_valuation/methods
- /api/stock_valuation/fetch
- /api/stock_valuation/calculate
- /api/stock_valuation/guide
- /api/stock_valuation/cases*
- /api/stock_valuation/history
- supporting frontend stock search: /api/data_query/search_stock

Notes:
- pp_modules/routes/stock_valuation.py contains field config, Juyuan snapshot fetch, valuation calculation, method recommendation, guide generation, and route registration.
- pp_modules/services/valuation_* contains DCF math, AI coach/review helpers, fact cache, and valuation case repository/schema.
- pp_modules/routes/data_query.py plus pp_modules/services/stock_master_cache.py are included because the frontend stock search depends on /api/data_query/search_stock.
- data_fetcher.py, juyuan_bridge.py, juyuan_config.py, config.py, and db_schema.py are included as Juyuan data-access context.
- pp.py and section files are included to show registration, Flask app context, login/RBAC, DB helpers, CSRF, and AI helper injection.
- Runtime data, databases, uploads, logs, cache, .env, and secrets are intentionally excluded.
