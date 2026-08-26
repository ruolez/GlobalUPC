# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Global UPC** is an operations dashboard for businesses running multiple MSSQL backends (e.g. BackOffice / S2S systems) plus Shopify storefronts. It centralizes UPC management, price updates, in-progress shipment tracking, sales reporting, and orphan-UPC reconciliation across every configured store.

There is **no automated test suite** — verification is manual via the running app and ad-hoc curl smoke tests.

## Stack & runtime

Three Docker services:

| Service | Container | Tech | Port |
|---|---|---|---|
| `db` | `globalupc_db` | PostgreSQL 15 | 5433 (host) |
| `backend` | `globalupc_backend` | FastAPI + SQLAlchemy + pyodbc/FreeTDS | 8001 |
| `frontend` | `globalupc_frontend` | Nginx serving static files | 80 (prod) / 8080 (dev) |

**Dev (`docker-compose.yml`)**: backend mounts `./backend` so Python edits hot-reload (single `uvicorn --reload` worker). Frontend mounts `./frontend/src` — JS/HTML/CSS edits are visible after a hard refresh (Cmd-Shift-R) since aggressive no-cache headers are set.

**Prod (`docker-compose.prod.yml`)**: 4 uvicorn workers, healthchecks, restart policy. Resource limits applied to all three services. Deployed by `install.sh` to `/opt/globalupc/`.

## Common commands

```bash
docker-compose up -d --build backend frontend   # rebuild + start
docker-compose logs -f backend                  # tail backend
docker-compose restart backend                  # restart after non-Python edits

docker exec -it globalupc_db psql -U globalupc -d globalupc
docker exec -it globalupc_backend bash
docker exec globalupc_backend python -c "import main; print('ok')"   # smoke imports

curl -s http://localhost:8001/openapi.json | python3 -m json.tool | less
curl -s http://localhost:8001/api/health
```

Production deploys via `sudo ./install.sh` (option 2 = update preserving data; option 4 = remove + reinstall). The installer runs every `backend/migrations/*.sql` against the live PostgreSQL volume — keep migrations idempotent.

## High-level architecture

### Two databases

- **PostgreSQL** holds *configuration* only — Stores, MSSQLConnection, ShopifyConnection, Settings, ItemTrackerConfig, SalesConfig, StoreMirror — plus *audit history* (UPCUpdateHistory, PriceUpdateHistory, UPCExclusion).
- **MSSQL stores** hold the *operational data*. Each `Store` of type `mssql` has an `MSSQLConnection` row. The app fans out to every active MSSQL store in parallel for searches/audits using `asyncio.as_completed()`.

### Two MSSQL "store roles"

Some features rely on a *specific* MSSQL store being designated as a centralized source. Both are referenced by store id via either a row in `settings` or a column on a config table.

| Role | Where configured | Used by |
|---|---|---|
| **DB_ADMIN** | `settings` row keyed `admin_store_id` | In Progress (`QuotationsInProgress`, `QuotationsStatus`, `ManualInventoryUpdate`) |
| **Item Tracker S2S / Primary** | `item_tracker_config.s2s_store_id` | Item Tracker (`Items_tbl` lookups, sales/inventory cross-checks), In Progress (price = `Items_tbl.UnitCost * 1.05`), Shopify Sales (cost lookup) |
| **Business Overview sales / purchases** | `business_overview_config.sales_store_id` / `purchases_store_id` (+ `shopify_store_ids`, `quotation_statuses`, `timezone`) | Business Overview (invoices, sales/margin trend, purchase orders; Shopify cost always from Item Tracker S2S `Items_tbl.UnitPriceC`, and everything from S2S `Items_tbl.UnitCost` in the "S2S Cost" mode) |

When adding a feature that needs one of these stores, **prefer a "soft" resolver** (returns `None` if unconfigured) over the existing strict resolvers (`get_item_tracker_stores`, `_resolve_admin_store`) that raise `HTTPException`. Examples: `_resolve_item_tracker_s2s_conn` (in `main.py`) — lets the calling page degrade gracefully instead of 400-ing the user.

### Backend layout (`backend/`)

| File | Responsibility |
|---|---|
| `main.py` | All FastAPI endpoints; ~5k lines, keep adding sections at the bottom. Endpoint helpers live next to the endpoints they serve. |
| `models.py` | SQLAlchemy ORM. Core entity is `Store` (with `store_type` enum + `store_category`); other tables either belong to a store (FK) or to a feature config. |
| `schemas.py` | Pydantic request/response models. **Use attribute access**, not `dict["key"]`. |
| `database.py` | SQLAlchemy engine setup. Pool size 5 / overflow 10 / `pool_pre_ping` / `pool_recycle=300`. |
| `init.sql` | Bootstrapped on first container start. Subsequent schema changes go in `migrations/*.sql`. |
| `mssql_helper.py` | All MSSQL queries that fan out across stores. Owns `_mssql_executor` (4 threads), the `CHUNK_SIZE` constant for chunked operations, and `get_item_prices_batch_async` for UPC→cost lookups. |
| `item_tracker_helper.py` | Single-store MSSQL queries used by Item Tracker (purchases, sales, customer/vendor returns, inventory recounts). Owns `_item_tracker_executor`. |
| `quotations_in_progress_helper.py` | DB_ADMIN aggregations for the In Progress section. Owns `_qip_executor`. |
| `shopify_helper.py` | Shopify Admin API (REST + GraphQL). Used for barcode search/update, price updates, fulfilled-orders sales reports. |
| `shopify_sync_helper.py` | Per-store local mirror of Shopify customers/orders into PostgreSQL. Full sync via Bulk Operations API (JSONL download, `__parentId` reassembly for line items), incremental via `updated_at` cursor pagination; both write through the same batch upserts (`execute_values`, per-batch dedupe). The `shopify_sync_state` row doubles as the cross-worker claim (conditional UPDATE + heartbeat staleness takeover). Owns `_sync_executor`. |
| `lost_customers_local.py` | Local-SQL twins of every Shopify fetch the Lost Customers report makes (scan, first orders, cross-store email/name+ZIP probes, customer detail, lost-products line items). Each returns the exact shape of its live counterpart so the report orchestration runs unchanged. Completed-order rule in SQL: `cancelled_at IS NULL AND financial_status IS DISTINCT FROM 'REFUNDED'` plus no `banned`/`fraud` tag (exact match, case-insensitive — mirrors `ANALYSIS_ORDER_FILTER` in `shopify_helper.py`, which also drops customers carrying those tags); window comparisons via `AT TIME ZONE`. |
| `business_overview_helper.py` | Business Overview: pure period/bucket math (`resolve_period`, `previous_period`, `rollup_daily`), single-store MSSQL queries for open/shipped invoices, purchase orders, daily sales + credit-memo returns, breakdowns and drill-ins (optional lookup tables `Employees_tbl`/`Shippers_tbl`/`Terms_tbl`/`Suppliers_tbl` guarded via `INFORMATION_SCHEMA`), plus Postgres-mirror Shopify series. Owns `_bov_executor`. |
| `freetds.conf` | FreeTDS settings. TDS version defaults to 7.4 (SQL Server 2012+). |

The lifespan handler in `main.py` shuts down each thread-pool executor on app exit — when adding a new helper file with its own `ThreadPoolExecutor`, register a `shutdown_*_executor()` and call it from the lifespan.

### Major feature areas

Every large feature follows the same shape: a config table or settings entry, a helper file with sync MSSQL queries plus async wrappers, endpoints in `main.py`, a page section in the frontend SPA, and Pydantic schemas. Use this when adding the next one.

- **UPC Search & Update** (`/api/upc/*`) — fans out to every active store; per-store duplicate validation skips conflicts non-blockingly.
- **Orphan UPC Audit** (`/api/analysis/orphaned-upcs/*`) — MSSQL-only; chunked processing, reconciliation by ProductID or Description, per-store UPC exclusions persisted in `upc_exclusions`.
- **Price Updates** — Cross-store price/cost reconciliation. History batched by `batch_id` in `price_update_history`.
- **Item Tracker** — UPC-centric ledger across the configured S2S, sales, and inventory MSSQL stores. Excludes specific business names via `item_tracker_exclusions`.
- **Sales / Shopify Sales** — Period reports built from `SalesConfig` (which MSSQL stores + Shopify stores to include). SKU-prefix exclusions stored in `settings`.
- **In Progress** (`/api/quotations/in-progress*`) — DB_ADMIN-backed shipment tracker. Two-pane SPA section with scan-status filter, multiselect dropdowns, search-summary mode, sortable products table, prices from Item Tracker S2S `Items_tbl.UnitCost * 1.05`.
- **Shopify Data Sync** (`/api/shopify-sync/*`) — per-store local mirror of Shopify customers + orders (account state, tags, notes, statuses, addresses, line items incl. barcode, fulfillments; full payloads kept in `raw JSONB`) in `shopify_customers` / `shopify_orders` / `shopify_order_line_items`, state in `shopify_sync_state`. Manual trigger only, from the Data Sync tab in Shopify Analytics: first sync is a full Bulk Operations export, repeat syncs are incremental deltas (seconds), "Full resync" re-downloads and prunes rows deleted in Shopify (`synced_at < run_started`). Stores with a completed sync serve the Lost Customers report (and its customer-detail / lost-products sub-reports) from local SQL — routed per fetch-primitive in the endpoint, `data_source: "local"|"live"` on the SSE events — while unsynced stores keep the live path, including per-shop within the cross-store probes.
- **Business Overview** (`/api/business-overview/*`) — owner dashboard: KPI strip, revenue/profit/margin trend (BackOffice `InvoicesDetails` revenue = `ExtendedPrice`, cost = `QtyShipped` × that store's own `Items_tbl.UnitCost` by UPC, line `UnitCost` fallback; totals profit additionally subtracts per-day `Invoices_tbl.ShippingCost` (`shipping_cost` on `BOVSalesSourceTotals`; margin_pct stays product-based, Shopify unaffected); Shopify from the local mirror by order `created_at`, cost = units × Item Tracker S2S `Items_tbl.UnitPriceC` by barcode; `cost_mode=s2s` (topbar "S2S Cost" toggle) re-costs both from S2S `Items_tbl.UnitCost` — BackOffice via per-(day, UPC) units + `recost_backoffice_days`, customer/rep breakdown cost unavailable in that mode), quotations in progress (DB_ADMIN, configurable statuses), open/shipped invoices (shipped = non-blank `TrackingNo`, dated by `COALESCE(ShipDate, InvoiceDate)`), purchase orders (incoming = `Status = 0 AND TotQtyRcv < TotQtyOrd`; purchased by `PoDate`; received by `PurchaseOrdersDetails.DateReceived`), drill-in modals for quotations/invoices/POs; quotation/invoice lists carry a sortable margin column (invoice: per-invoice `InvoicesDetails` revenue vs local `Items_tbl.UnitCost`; quotation: `QuotationTotal` vs the SourceDB store's `Items_tbl.UnitCost` by UPC; both re-costed from S2S in `cost_mode=s2s`); invoice lists and the invoice modal also carry a sortable Profit column of `net_profit` = product profit − `Invoices_tbl.ShippingCost`, recomputed after every re-cost path. Config singleton `business_overview_config`; BackOffice sales totals honour the Sales `sales_exclusions` list; DB_ADMIN via the soft admin-store resolver. Configuration UI = the tabbed **settings modal** (`#bov-config-modal`, opened from the topbar "Sources" pill or any `data-bov-action="config|exclusions|bank-accounts|settings-roles"`): left rail with live badges (`bovCfgRenderBadges`), tabs Sources / Bank accounts / Alerts / Exclusions (`bovCfgSetTab`, remembered in `bov_prefs.cfgTab`), one Save (`bovSaveConfig`) with dirty tracking (`bovState.cfgDirty`, `confirm()` on Cancel/×/backdrop/Escape — the generic `.modal` backdrop handler is intercepted in the capture phase); no separate read-only mode. First run = same modal with Cancel hidden. Bank accounts tab stages `quickbooks_accounts.hidden` toggles in `bovState.cfgBank.dirty` and applies them on Save via `PUT /api/quickbooks/accounts/visibility` (the Settings → QuickBooks card keeps immediate `PATCH`es); both render the same grouped list through `qbAccountsListHtml`. Exclusions save immediately (their own endpoints) and never mark the modal dirty. Per-widget endpoints + one `/summary`; every block carries `configured`/`error` so one bad store never blanks the page. `/alerts` evaluates the operational alert rules (unshipped past cutoff, open-invoice age, stuck quotations, overdue POs, Shopify on-hold / unfulfilled aging / stale sync) against thresholds stored in `business_overview_config.alert_rules` (defaults + merge/validation in `schemas.py`: `BOV_DEFAULT_ALERT_RULES`, `bov_merge_alert_rules`, `bov_validate_alert_rules`); money rules are evaluated client-side: revenue drop from the summary; margin floor per PRODUCT from the Products widget (`/products` local margin vs the global floor or the store override in `alert_rules.margin_floor.stores`, incl. Shopify) — clicking it deep-links to the Products tab filtered/sorted with the below-floor rows tinted and scrolled into view. Each operational alert action carries a `match` predicate the lists use to tint the alerted rows (`bov-row-alert`) after the user opens an alert. Previous-period math lives only in the backend (`period` is echoed to the client). Frontend: `bov*` section in `app.js`, hand-rolled SVG charts.
- **Month End** (`/api/business-overview/month-end`) — combined month-close order list: BackOffice invoices (via `invoices_in_period_async`, profit = existing `net_profit`) merged with Shopify mirror orders (completed + `fulfillment_status='FULFILLED'`; product cost = Item Tracker S2S `UnitPriceC` by barcode; profit = product profit + `total_shipping` collected − Σ shipper-store `parcels.cost` joined on order name via `normalize_order_number`, `#`-insensitive, multi-box summed). Stores come from the Business Overview config; shipper store via `_resolve_shipper_store_soft` — missing parcels flag the row (`shipping_missing`) and count as $0. Period AND store filter = the Business Overview topbar (`bovRangeParams` + `bovStoreParams` → `store_ids` narrows the fan-out server-side, `filtered_out` when it excludes everything; a full `bovFetchAll` invalidates/refetches the tab); one fetch per period, served over SSE (`/month-end/stream`: `progress` events → one `result`, plain JSON twin kept as fallback). Shipper parcels resolve via one date-bounded window aggregate (`_parcel_costs_window_sync`, period + 45-day pad) with an exact `IN(...)` sweep over only the unmatched names; `timings` on the response names the slow stage. Rows drill in via the shared BOV modals (`data-bov-open` on each row): BackOffice → the invoice modal, Shopify → the Shopify order modal, whose detail endpoint now enriches every line with S2S `UnitPriceC` cost/profit/margin (header `product_profit`/`cost_coverage`); Month End rows pass the parcels shipping cost via `data-me-ship-*` attrs so that modal adds Shipping cost + Real profit rows. Both modals' line tables are sortable (`bovState.sort.invoiceLines`/`shopifyOrderLines` re-rendered through `bovRenderCard`). Type/store/search filtering, sorting (`bovState.sort.monthEnd`, via the BOV page's th delegation → `bovRenderCard("monthEnd")`), and totals (top tiles + tfoot) are client-side over the returned rows. Lives as the "Month End" tab of the Business Overview page (`BOV_SECTIONS` entry + `.bov-panel[data-bov-panel="month-end"]`; `bovSetSection` lazy-loads it); frontend `monthEndState`/`me*` section at the bottom of `app.js`, prefs in localStorage `month_end_prefs`.
- **Inventory** — Sales-report clone as a Business Overview tab (`BOV_SECTIONS` "inventory", `.bov-panel[data-bov-panel="inventory"]`, `inv*` section at the bottom of `app.js`, prefs in localStorage `inv_*`). Reuses `POST /api/sales/report/stream` + `GET /api/sales/config` read-only — the Sales config (primary/S2S store, sales stores, excluded subcategories) and exclusions stay managed on the Sales page. Adds a sortable "S2S Cost" column (`Items_tbl.UnitCost` from the Sales S2S store, selected in `get_active_products` and streamed as `s2s_cost` on each product). Period is bound to the BOV topbar (`bovRangeParams`; invalidated/refetched via the `bovFetchAll` block, with an AbortController for mid-stream period changes); the BOV store filter is deliberately ignored. Totals are client-side over the filtered rows: top tiles (`me-tile` reuse) + tfoot — Products, On Hand units, Inventory Value = Σ On Hand × S2S Cost (rendered in the S2S Cost foot cell), plus Sold/Returns/Net Sold.
- **QuickBooks Online / Bank balances** (`/api/quickbooks/*`, `/api/business-overview/bank-balances`) — one QBO company connected via OAuth 2.0 authorization code with a **paste-back callback** (Intuit requires https redirect URIs and the app runs on plain-HTTP LAN: Settings → Roles & Mirrors "QuickBooks Online" card → Connect opens Intuit in a new tab, the user pastes the URL they land on, `quickbooks_helper.parse_callback_input` + `complete_connection` exchange the code). Singleton `quickbooks_connection` (Intuit client id/secret, `environment` production|sandbox, redirect URI, realm, rotating refresh token — `apply_token` always persists the newest one; `ensure_access_token` refreshes under `SELECT … FOR UPDATE` so the 4 prod workers never race; `invalid_grant` → `status=needs_reconnect`) + `quickbooks_accounts` cache of `AccountType IN ('Bank','Credit Card')` rows (`hidden` user toggle survives the upsert; totals sum per-row `CurrentBalance` so parents/sub-accounts aren't double counted; credit-card balance positive = owed, net = cash − debt). `get_balances_block` (via `asyncio.to_thread`) re-syncs when the cache is older than `refresh_minutes`, and on any failure serves the cache with `stale: true` + the error — the widget never blanks. Frontend: `bankBalances` BOV widget (own endpoint, not part of `/summary`; ignores period/store filters; `bovRenderBankBalances`, `bovRefreshQuickBooks`, `data-bov-action="quickbooks-sync"|"settings-quickbooks"`) as a `.bov-grid-ops` row under the KPI strip; Settings JS in the `QuickBooks Online settings` block (`qb*` functions). A 6-hourly `keepalive_loop` (lifespan) refreshes the token when the dashboard hasn't been viewed for ~6 days. Not part of config export/import.
- **Inventory Time** (`/api/inventory-time*`) — DB_ADMIN-backed recount-time estimator. Reads `ManualInventoryUpdate` (`Username`, `DateCreated`) for one user + date range, sessionizes the timestamp stream (gaps over the configured break timeout split sessions), and credits each session `span * N/(N-1)` plus an isolated-recount fallback for lone items. Pure math in `inventory_time_helper.compute_inventory_time`; two `settings` keys `inventory_recount_timeout_minutes` / `isolated_product_recount_minutes`. Uses the soft admin-store resolver so the page degrades gracefully when DB_ADMIN is unset.

### Frontend (`frontend/src/`)

Single-page app, no build step. Three files do everything:

- `index.html` — every page section is a `<div class="page" data-page-id="..." style="display:none">` inside `.main-content`. Sidebar nav items have `data-page="..."`; clicking calls `navigateTo(page)` which toggles display.
- `app.js` — ~11k lines, organized by feature area in roughly the order the features were added. State is held in feature-scoped objects (`historyState`, `qipState`, etc.). There is **no framework** — DOM is built via `innerHTML` strings. Reuse the global `escapeHtml(text)` (around line 4836) for any user-controlled string before injecting.
- `styles.css` — Themes are CSS variables (`--bg-primary`, `--bg-secondary`, `--bg-tertiary`, `--bg-hover`, `--text-primary/secondary/tertiary`, `--accent-primary`, `--success/warning/danger`, `--border-color`, `--radius-*`, `--shadow-*`). Switching theme = swap one root-level rule. There are 8 themes today (Default, Monochrome, Charcoal, Steel, Minimal, Graphite, Nord, Author's Light) — any new feature should consume only existing variables (use `color-mix(in srgb, var(--accent-primary) X%, var(--bg-primary))` for accent-tinted derivations) so it adapts to all themes for free.

Filter and table patterns to mirror when building new sections (see the In Progress section as the most current reference):

- **Custom multiselect popover** (`.qip-multiselect` / `.qip-ms-trigger` / `.qip-ms-popover`) — replaces native `<select multiple>` with a chip-style dropdown showing a checked-count badge.
- **Sortable column headers** — `<th class="qip-sortable" data-sort="key">`. A delegated click handler on the parent table cycles `asc → desc → none` and applies `qip-sort-asc` / `qip-sort-desc` classes; CSS chevrons handle the visual.
- **All-checked = no filter** semantic on multiselects: when every option is checked, send `[]` to the backend so rows whose corresponding column is `NULL` aren't excluded by `WHERE IN (...)` (which evaluates to `UNKNOWN` for `NULL`). The In Progress fetch payload transform shows the pattern.

## MSSQL patterns to know

- **`pyodbc` + FreeTDS** with the connection string from `mssql_helper.get_mssql_connection_string`. ARM64/x86_64 driver paths are auto-detected.
- **Parallel store fan-out**: every cross-store endpoint uses `asyncio.as_completed()` over per-store coroutines so total latency = max(store time), not sum.
- **Chunking**: SQL Server's parameter limit is ~2100. `mssql_helper.py` uses `MAX_PARAMS = 2000` for `IN (...)` batches; `CHUNK_SIZE = 1000` is used for paged scans of large detail tables.
- **`HAVING` for filters on aggregates**: when a query `GROUP BY` a parent (e.g. `QuotationNumber`) and you need to filter on `MAX(qs.SomeCol)`, put the predicate in `HAVING`, not `WHERE`. Putting it in `WHERE` filters joined rows pre-aggregation and gives wrong results when there are multiple matching rows per group. See `_build_scan_having` in `quotations_in_progress_helper.py`.
- **Sorting `varchar` dates**: legacy fields like `QuotationsStatus.Dop2/Dop3` store datetimes as `"MM/DD/YYYY HH:MM AM/PM"` strings; lexicographic sort is wrong. Use `TRY_CONVERT(datetime, qs.DopX)` before aggregating/sorting.
- **Empty-string vs NULL**: legacy varchar fields may contain whitespace strings instead of `NULL`. Treat both as "missing" with `(col IS NULL OR LTRIM(RTRIM(col)) = '')`.

## Server-Sent Events

Long-running cross-store operations stream progress to the client. Always use **literal newlines**, not escaped:

```python
yield f"event: progress\ndata: {json.dumps(payload)}\n\n"   # ✅
yield f"event: progress\ndata: {json.dumps(payload)}\\n\\n" # ❌ breaks the stream
```

Heartbeat every ~15s on long streams to keep the client connection alive. Listen for `GeneratorExit` to cancel pending `asyncio.create_task(...)` operations on client disconnect.

## When rebuilding containers

| Edit | Required action |
|---|---|
| `backend/Dockerfile` or `requirements.txt` | `docker-compose build backend` |
| `frontend/Dockerfile` or `nginx.conf` | `docker-compose build frontend` |
| `backend/init.sql` | Drop the `globalupc_postgres_data` volume + recreate (destructive) |
| `backend/migrations/*.sql` | Lands automatically on prod via `install.sh` option 2; in dev apply manually |
| Python source under `backend/` | Auto-reload (`uvicorn --reload`) |
| `frontend/src/*` | Hard refresh in browser |
