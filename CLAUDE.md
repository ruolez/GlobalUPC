# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Global UPC** is a barcode management application for maintaining accurate UPC barcodes across multiple MSSQL databases and Shopify stores. Provides centralized interface for bulk UPC updates across all configured locations.

## Architecture

Docker-based multi-container application:
- **db** (PostgreSQL 15): Store configurations and settings
- **backend** (FastAPI/Python): REST API with MSSQL and Shopify integration
- **frontend** (Nginx/Vanilla JS): SPA with dark mode themes

**Ports**: Frontend (80/8080), Backend API (8001), PostgreSQL (5433)

**Container Names**: `globalupc_frontend`, `globalupc_backend`, `globalupc_db`

**Development Mode** (`docker-compose.yml`): Live reload, volume mounts, single worker
**Production Mode** (`docker-compose.prod.yml`): 4 workers, healthchecks, restart policy

## Database Schema

**stores**: `id`, `name`, `store_type` (mssql|shopify), `is_active`
**mssql_connections**: `store_id`, `host`, `port`, `database_name`, `username`, `password`
**shopify_connections**: `store_id`, `shop_domain`, `admin_api_key`, `api_version`, `update_sku_with_barcode`
**settings**: `key`, `value`, `description`
**upc_update_history**: `batch_id`, `store_id`, `old_upc`, `new_upc`, `success`, `items_updated_count` - Tracks all UPC updates
**upc_exclusions**: `store_id`, `upc`, `excluded_at`, `notes` - UPCs excluded from orphaned UPC audits (unique per store+UPC)

All tables have auto-updating `created_at` and `updated_at` timestamps.

## Backend Structure

**Core Files**:
- `main.py`: FastAPI app with all endpoints
- `models.py`: SQLAlchemy ORM models
- `schemas.py`: Pydantic request/response schemas
- `mssql_helper.py`: FreeTDS connection utilities
- `shopify_helper.py`: Shopify Admin API utilities
- `init.sql`: Database schema initialization
- `freetds.conf`: TDS protocol settings

**Key API Endpoints**:
- `GET /api/health` - Health check
- `GET/POST/DELETE /api/stores/*` - Store management
- `POST /api/test/{mssql|shopify}` - Connection testing
- `POST /api/upc/search/stream` - UPC search (SSE)
- `POST /api/upc/update/stream` - UPC update (SSE)
- `POST /api/upc/validate` - Validate UPC for duplicates
- `GET /api/config/export` - Export configurations
- `POST /api/config/import` - Import configurations
- `POST /api/analysis/orphaned-upcs/stream` - Audit orphaned UPCs (SSE)
- `POST /api/comparison/stores/stream` - Compare Items_tbl (SSE)
- `POST /api/exclusions` - Add UPC exclusion
- `GET /api/exclusions?store_id={id}` - List exclusions (optionally filtered by store)
- `DELETE /api/exclusions/{id}` - Remove UPC exclusion

## Critical Implementation Notes

### Server-Sent Events (SSE)
MUST use actual newlines `\n\n`, NOT escaped `\\n\\n`:
```python
# ✅ Correct
yield f"event: progress\ndata: {json.dumps(data)}\n\n"

# ❌ Wrong
yield f"event: progress\ndata: {json.dumps(data)}\\n\\n"
```

### Pydantic Models
Use attribute syntax, NOT dictionary syntax:
```python
# ✅ Correct
store_id = match.store_id

# ❌ Wrong
store_id = match["store_id"]
```

### UPC Validation
Before updating UPCs:
1. Check old UPC ≠ new UPC (client-side)
2. Call `POST /api/upc/validate` to check for duplicates
3. Hard block if duplicate found (show modal with existing products)
4. Show loading indicator: "⏳ Checking for duplicate barcodes..." (min 500ms display)

### MSSQL Table Discovery
Searches all configured tables across all MSSQL connections. Tables gracefully skipped if missing:
- `Items_tbl` (PK: ProductID)
- `QuotationsDetails_tbl` (PK: LineID)
- `PurchaseOrdersDetails_tbl` (PK: LineID)
- `InvoicesDetails_tbl` (PK: LineID)
- `CreditMemosDetails_tbl` (PK: LineID)
- `PurchasesReturnsDetails_tbl` (PK: LineID)
- `QuotationDetails` (PK: id)

### FreeTDS Configuration
- Default TDS version: 7.4 (SQL Server 2012+)
- Auto-detects architecture (ARM64/x86_64) for ODBC driver path
- Uses pyodbc with ThreadPoolExecutor for async operations

### Shopify Integration
- Admin API with access tokens (not OAuth)
- API version: `2025-01`
- SKU update feature uses REST API (`PUT /admin/api/{version}/variants/{id}.json`)
- GraphQL used for barcode validation queries

### Performance Optimizations

**Parallel Store Processing**: All stores searched simultaneously using `asyncio.as_completed()`
- Before: 10 stores × 3s = 30s
- After: max(store times) = 3-5s
- Result: ~6-10x faster

**Chunked Processing**: Large datasets processed in 5,000 record chunks
- SQL Server parameter limit: 2,100 max → batches use 2,000 params
- SSE heartbeat every 15s to prevent timeout
- Real-time progress updates

## Development Commands

```bash
# Start/stop services
docker-compose up -d
docker-compose down
docker-compose restart backend

# View logs
docker-compose logs -f backend
docker-compose logs backend --tail 50

# Database access
docker exec -it globalupc_db psql -U globalupc -d globalupc

# Backend shell
docker exec -it globalupc_backend bash
```

**Volume Mounts**: Backend and frontend auto-reload on changes. Frontend requires browser hard refresh (Cmd+Shift+R).

## Production Deployment

**Initial Install**:
```bash
wget https://raw.githubusercontent.com/ruolez/GlobalUPC/main/install.sh
sudo chmod +x install.sh
sudo ./install.sh
```

**Location**: `/opt/globalupc/`

**Update**: Run `sudo ./install.sh` → Option 2 (preserves data)

**Commands**: Use `docker compose -f docker-compose.prod.yml` for all operations

**Environment**: Configure via `.env` file (SERVER_IP, POSTGRES_*, ports)

## Key Features

### UPC Search & Update
1. Search UPC across all active stores (parallel)
2. Enter new UPC value
3. Validation checks for duplicates
4. Bulk update with real-time progress

### Orphan UPC Audit (MSSQL only)
- Finds UPCs in detail tables not in Items_tbl
- Chunked processing for large tables
- Date-range filtering support
- Table filtering and statistics
- Reconciliation by ProductID or Description
- **UPC Exclusions**: Permanently exclude specific UPCs from audit results
  - Scoped per Store + UPC combination
  - Managed via Settings page or inline exclude button (🚫) in audit results
  - Server-side filtering ensures excluded UPCs never appear in results

### Items Check (Store Comparison)
- Compare Items_tbl between two MSSQL stores
- Find products missing from comparison store
- Category/subcategory filtering
- Chunked processing with real-time progress
- Export to CSV

### Configuration Import/Export
- JSON format with version tracking
- Duplicate detection (host+port+db for MSSQL, domain for Shopify)
- Filename: `globalupc-config-YYYY-MM-DD-HHMMSS.json`

## Frontend Features

**Themes**: 6 dark mode themes (current, monochrome, charcoal, steel, minimal, graphite)
**Search Results**: Collapsible store rows with expand/collapse icons
**Progress**: Real-time SSE streaming with chunk-level updates
**Safeguards**: Prevents concurrent searches, disables buttons during operations
**No-Cache**: Aggressive headers ensure immediate updates

## Troubleshooting

**Backend won't start**: Check logs `docker-compose logs backend --tail 100`

**MSSQL "file not found"**: Verify ODBC driver path in `/etc/odbcinst.ini`

**Shopify "Invalid API key"**: Check domain (must end `.myshopify.com`) and key validity

**Frontend not updating**: Browser cache issue - hard refresh (Cmd+Shift+R)

**Database connection refused**: Check PostgreSQL health and port 5433 availability

**Timeout errors**: Reduce CHUNK_SIZE in `mssql_helper.py`, check network latency, verify indexes on ProductUPC

**Empty audit results**: Verify Items_tbl exists, check ProductUPC field names match

**Health checks timeout**: Verify ports available, check firewall, ensure curl installed in containers

## When Rebuilding Containers

- `backend/Dockerfile` or `requirements.txt` → Rebuild backend
- `frontend/Dockerfile` or `nginx.conf` → Rebuild frontend
- `backend/init.sql` → Drop database volume and recreate
