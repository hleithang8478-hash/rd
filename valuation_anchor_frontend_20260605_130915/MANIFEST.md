# Valuation Anchor Frontend Package

Generated: 20260605_130915
Project root: C:\Users\tanjiarong\Desktop\ReviewsDaily

Purpose: frontend files for the ReviewsDaily stock valuation / valuation anchor page (/stock_valuation).

Included files:
- templates\stock_valuation.html
- static\stock_valuation.css
- static\stock_valuation.js
- static\app_shell.css
- static\app_minimal_theme.css
- static\app_responsive_overrides.css
- templates\components\workspace_shell.html
- templates\base.html
- templates\index.html
- static\app_shell.js
- static\thor_frame_bridge.js

Notes:
- 	emplates/stock_valuation.html is the valuation page shell and loads static/stock_valuation.css plus static/stock_valuation.js.
- static/stock_valuation.js calls /api/stock_valuation/* and /api/data_query/search_stock.
- Shared app shell files are included only as context for navigation, global layout, and iframe/workspace behavior.
- Runtime data, databases, uploads, logs, cache, .env, and secrets are intentionally excluded.
