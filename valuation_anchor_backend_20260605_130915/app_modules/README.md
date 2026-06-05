# app.py split map

Generated: 2026-05-12 14:39:18
Source backup: `C:/Users/tanjiarong/Desktop/ReviewsDaily/back/app_split_backups/app_before_split_20260512_143313.py`

The root `app.py` first loads core files from `sections/`, then loads legacy-compatible
business route files from `routes/` in the root app module namespace. Files that have
already been cleaned into explicit registration functions are also kept in `routes/`.
Endpoint names, globals, decorators, and project-root path behavior are preserved.

## Sections

- `sections/00_imports_logging_ai.py`: imports, logging, env helpers, DeepSeek helpers. Original lines 1-404.
- `sections/01_plan_text_research_helpers.py`: plan text normalization, research links, Thor quick-add helpers. Original lines 405-1585.
- `sections/02_app_config_db_compat.py`: Flask app creation, project paths, DB backend compatibility, base hooks. Original lines 1586-2603.
- `sections/03_security_rbac_init_db.py`: security tables, login helpers, RBAC, tenant migration, init_db, health checks. Original lines 2604-4864.
- `routes/base_reviews.py`: momentum storage helpers, score query helpers, reviews and essays routes. Migrated from original lines 4865-6280.
- `legacy_sections/04_scores_reviews_base_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/calendar_daily_dashboard.py`: calendar routes, dashboard payloads, market context helpers. Migrated from original lines 6281-8261.
- `legacy_sections/05_calendar_daily_dashboard.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/plans_graph_market.py`: investment plans, plan APIs, research graph, market tone, index trend. Migrated from original lines 8262-9066.
- `legacy_sections/06_plans_graph_market_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/thinking_kelly.py`: deep thinking routes and Kelly calculator page. Migrated from original lines 9067-9362.
- `legacy_sections/07_thinking_kelly_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/reports_pdf_reader.py`: deep reports, PDF library, upload, reader, PDF download. Migrated from original lines 9363-10282.
- `legacy_sections/08_reports_pdf_reader.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/reports_compare_links.py`: PDF compare extraction, compare API, annotations, report linking. Migrated from original lines 10283-11236.
- `legacy_sections/09_reports_compare_links.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/concepts_sentiment_jobs.py`: concept stocks, market sentiment pages, sentiment job wiring. Migrated from original lines 11237-12381.
- `legacy_sections/10_concepts_sentiment_jobs.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/topics_inventory.py`: mind map topics and industry inventory routes. Migrated from original lines 12382-13098.
- `legacy_sections/11_topics_inventory_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/data_query.py`: data query builder, SQL templates, query execution, table recognition. Migrated from original lines 13099-14819.
- `legacy_sections/12_data_query_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/screening_tasks.py`: screening task pages and APIs. Migrated from original lines 14820-15112.
- `legacy_sections/13_screening_tasks_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/momentum_scores.py`: momentum score pages and APIs. Migrated from original lines 15113-15585.
- `legacy_sections/14_momentum_scores_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/portfolio_analysis.py`: portfolio import and analysis APIs. Migrated from original lines 15586-16826.
- `legacy_sections/15_portfolio_analysis_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/admin_rbac.py`: RBAC admin page and APIs. Migrated from original lines 16827-17210.
- `legacy_sections/16_admin_rbac_routes.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/crawler_morning_brief.py`: crawler DB helpers and daily morning brief generation/routes. Migrated from original lines 17211-18771.
- `legacy_sections/17_crawler_morning_brief.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/crawler_dashboard_wordcloud.py`: timeline page, crawler dashboard APIs, wordcloud, theme analysis. Migrated from original lines 18772-20646.
- `legacy_sections/18_crawler_dashboard_wordcloud.py.bak`: backup of the mechanical split section before second-stage migration.
- `routes/timeline_search_export.py`: timeline APIs, crawler search, crawler export. Migrated from original lines 20647-20862.
- `legacy_sections/19_timeline_search_export.py.bak`: backup of the mechanical split section before second-stage migration.
- `sections/99_main.py`: local development server entrypoint. Original lines 20863-20872.
