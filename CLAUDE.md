# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Global UPC** is a barcode management application designed to maintain accurate UPC barcodes across multiple databases and stores. It provides a centralized interface to manage connections to MSSQL databases and Shopify stores, enabling bulk UPC updates across all configured locations.

## Architecture

This is a Docker-based multi-container application with three services:

### Services
- **db** (PostgreSQL 15): Application database storing store configurations and settings
- **backend** (FastAPI/Python): REST API server with MSSQL and Shopify integration
- **frontend** (Nginx/Vanilla JS): Single-page application with dark mode theme system

### Port Mappings
- **8080**: Frontend (Nginx)
- **8001**: Backend API (FastAPI/Uvicorn)
- **5433**: PostgreSQL database (mapped from container port 5432)

### Container Names
- `globalupc_frontend`
- `globalupc_backend`
- `globalupc_db`

## Development Commands

### Starting and Stopping
```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Restart specific service
docker-compose restart backend
```

### Building
```bash
# Rebuild all containers
docker-compose build

# Rebuild specific service
docker-compose build backend

# Rebuild and start
docker-compose up -d --build
```

### Logs
```bash
# View all logs
docker-compose logs

# Follow logs for specific service
docker-compose logs -f backend

# View last N lines
docker-compose logs backend --tail 50

# View all service status
docker-compose ps
```

### Database Access
```bash
# Access PostgreSQL CLI
docker exec -it globalupc_db psql -U globalupc -d globalupc

# Run SQL query directly
docker exec globalupc_db psql -U globalupc -d globalupc -c "SELECT * FROM stores;"
```

### Backend Development
```bash
# Access backend container shell
docker exec -it globalupc_backend bash

# Check Python dependencies
docker exec globalupc_backend pip list

# View FreeTDS ODBC configuration
docker exec globalupc_backend cat /etc/odbcinst.ini

# Test FreeTDS installation
docker exec globalupc_backend tsql -C
```

### Volume Mounts and Live Reload
The backend and frontend directories are mounted as volumes, enabling live reload during development:
- **Backend**: `./backend:/app` - Python files auto-reload via `--reload` flag
- **Frontend**: `./frontend/src:/usr/share/nginx/html:ro` - Static files served directly (requires browser refresh)
- **Database init**: `./backend/init.sql:/docker-entrypoint-initdb.d/init.sql` - Runs only on first container start

Changes to Python files in `backend/` trigger automatic backend restart. Frontend changes are immediately visible after browser refresh (no container rebuild needed).

## Database Schema

### Core Tables

**stores**: Central registry of all configured connections
- `id`, `name`, `store_type` (enum: 'mssql' | 'shopify'), `is_active`
- One-to-one relationship with either `mssql_connections` or `shopify_connections`

**mssql_connections**: MSSQL database connection details
- `store_id` (FK to stores), `host`, `port`, `database_name`, `username`, `password`
- Uses FreeTDS driver for legacy SQL Server support

**shopify_connections**: Shopify store connection details
- `store_id` (FK to stores), `shop_domain`, `admin_api_key`, `api_version`
- `update_sku_with_barcode` (boolean): When enabled, SKU will be updated to match barcode during UPC updates
- Uses Shopify Admin API (not OAuth)

**settings**: Key-value application settings
- `key` (unique), `value`, `description`

All tables have auto-updating `created_at` and `updated_at` timestamps via PostgreSQL triggers.

## Backend Structure

### Core Files
- **main.py**: FastAPI application with all API endpoints
- **models.py**: SQLAlchemy ORM models
- **schemas.py**: Pydantic request/response schemas
- **database.py**: Database connection and session management
- **mssql_helper.py**: FreeTDS connection utilities and testing
- **shopify_helper.py**: Shopify Admin API connection utilities and testing
- **init.sql**: Database schema initialization script
- **freetds.conf**: FreeTDS configuration for TDS protocol settings

### API Endpoints

**Health Check**
- `GET /api/health` - Service health status

**Stores**
- `GET /api/stores` - List all stores
- `GET /api/stores/{id}` - Get store details
- `POST /api/stores/mssql` - Create MSSQL store
- `POST /api/stores/shopify` - Create Shopify store
- `DELETE /api/stores/{id}` - Delete store
- `PATCH /api/stores/{id}/toggle` - Toggle store active status

**Connection Testing**
- `POST /api/test/mssql` - Test MSSQL connection before saving
- `POST /api/test/shopify` - Test Shopify connection before saving

**Settings**
- `GET /api/settings` - List all settings
- `GET /api/settings/{key}` - Get specific setting
- `POST /api/settings` - Create setting
- `PATCH /api/settings/{key}` - Update setting
- `DELETE /api/settings/{key}` - Delete setting

**UPC Search and Update (Server-Sent Events)**
- `POST /api/upc/search/stream` - Search for UPC across all active stores (SSE streaming)
- `POST /api/upc/search` - Search for UPC (non-streaming version)
- `POST /api/upc/update/stream` - Update UPC across stores (SSE streaming)

**Configuration Import/Export**
- `GET /api/config/export` - Export all store configurations as JSON
- `POST /api/config/import` - Import store configurations from JSON

**SQL UPC Audit (MSSQL Only)**
- `POST /api/analysis/orphaned-upcs/stream` - Audit MSSQL store for orphaned UPCs (SSE streaming)

**Items Check (Store Comparison)**
- `GET /api/stores/mssql/{store_id}/categories` - Get categories for MSSQL store
- `GET /api/stores/mssql/{store_id}/subcategories` - Get subcategories for MSSQL store (optional category_id filter)
- `POST /api/comparison/stores/stream` - Compare Items_tbl between two MSSQL stores (SSE streaming)

## FreeTDS Configuration (MSSQL)

This application uses **FreeTDS** for MSSQL connectivity to support legacy SQL Server versions.

### TDS Protocol Versions
- **7.0**: SQL Server 7.0
- **7.1**: SQL Server 2000
- **7.2**: SQL Server 2005
- **7.3**: SQL Server 2008
- **7.4**: SQL Server 2012+ (default)

### Architecture Detection
The Dockerfile automatically detects the container architecture and configures the correct ODBC driver path:
- ARM64/aarch64: `/usr/lib/aarch64-linux-gnu/odbc/libtdsodbc.so`
- x86_64/amd64: `/usr/lib/x86_64-linux-gnu/odbc/libtdsodbc.so`

This is critical because `dpkg --print-architecture` returns `arm64` but the actual library path uses `aarch64`.

### Helper Functions
```python
from mssql_helper import get_mssql_connection_string, test_mssql_connection

# Generate connection string
conn_str = get_mssql_connection_string(
    host="192.168.1.100",
    port=1433,
    database="MyDatabase",
    username="sa",
    password="password",
    tds_version="7.4"  # Optional, defaults to 7.4
)

# Test connection
success, error = test_mssql_connection(
    host="192.168.1.100",
    port=1433,
    database="MyDatabase",
    username="sa",
    password="password"
)
```

## Shopify Integration

### Authentication
Uses **Shopify Admin API** with access tokens (not OAuth). Connections require:
- `shop_domain`: Store domain (e.g., `mystore.myshopify.com`)
- `admin_api_key`: Shopify Admin API access token
- `api_version`: API version (default: `2025-01`)

### Helper Functions
```python
from shopify_helper import test_shopify_connection, validate_shop_domain

# Test connection
success, error, shop_info = test_shopify_connection(
    shop_domain="mystore.myshopify.com",
    admin_api_key="shpat_xxxxx",
    api_version="2025-01"
)

# Validate and normalize domain
normalized = validate_shop_domain("mystore")  # Returns: mystore.myshopify.com
```

### API Requests
All Shopify requests use the Admin REST API:
```
https://{shop_domain}/admin/api/{api_version}/{resource}.json
```

Headers:
```
X-Shopify-Access-Token: {admin_api_key}
Content-Type: application/json
```

## Frontend Structure

### Files
- **index.html**: Single-page application markup with modals
- **app.js**: Application logic, API calls, theme switching
- **styles.css**: Dark mode theme system with 6 theme variations
- **nginx.conf**: Nginx configuration with no-cache headers

### Theme System
CSS custom properties (`--bg-primary`, `--accent-primary`, etc.) with 6 pre-configured themes:
- **current**: Default purple accent theme
- **monochrome**: Pure grayscale
- **charcoal**: Warm gray tones
- **steel**: Cool blue-gray
- **minimal**: Low contrast
- **graphite**: True black, high contrast

Theme switching persists to `localStorage`.

### No-Cache Configuration
The frontend is configured with aggressive no-cache headers to ensure immediate updates:
```nginx
add_header Cache-Control "no-store, no-cache, must-revalidate";
add_header Pragma "no-cache";
add_header Expires "0";
```

## Important Implementation Details

### When Rebuilding Containers
If you modify:
- `backend/Dockerfile` or `backend/requirements.txt`: Rebuild backend
- `frontend/Dockerfile` or `frontend/nginx.conf`: Rebuild frontend
- `backend/init.sql`: Drop and recreate database volume

### Connection Testing Flow
1. User fills out connection form (MSSQL or Shopify)
2. User clicks "Test Connection" button
3. Frontend calls `/api/test/{mssql|shopify}` endpoint
4. Backend validates credentials and returns success/error
5. User sees colored status message (green success, red error, blue loading)
6. User can then save the connection if test succeeds

### Database Migrations
Schema is initialized via `backend/init.sql` which runs on first database container start. If you modify the schema:
```bash
# Drop database and recreate
docker-compose down
docker volume rm globalupc_postgres_data
docker-compose up -d
```

### MSSQL Table Discovery and Search
The application automatically searches **all configured tables** across **all MSSQL connections**, regardless of database name. Each MSSQL connection attempts to query all tables, and tables that don't exist are gracefully skipped.

**Currently Configured Tables** (`mssql_helper.py` lines 112-148):
1. `Items_tbl` - Primary key: `ProductID`
2. `QuotationsDetails_tbl` - Primary key: `LineID`
3. `PurchaseOrdersDetails_tbl` - Primary key: `LineID`
4. `InvoicesDetails_tbl` - Primary key: `LineID`
5. `CreditMemosDetails_tbl` - Primary key: `LineID`
6. `PurchasesReturnsDetails_tbl` - Primary key: `LineID`
7. `QuotationDetails` - Primary key: `id` (DB_Admin database)

**Table-Based Discovery (Not Database-Name-Based)**:
- System tries all tables on every MSSQL connection
- Missing tables are silently skipped via try/except in search loop
- Different databases can have different subsets of these tables
- No configuration mapping needed between database names and tables

**Adding New Tables**:
1. Add table definition to `mssql_helper.py` tables list with name, primary key field, and description field
2. Update primary key logic in `main.py` (lines 399-405) if the new table uses a different PK naming convention
3. All existing MSSQL connections will automatically start searching the new table

**Legacy Database Schemas**:
The `db_schema.MD` file contains reference schemas for understanding the structure of tables in connected MSSQL databases.

## Critical Implementation Notes

### Server-Sent Events (SSE) Format
When working with SSE endpoints (`/api/upc/search/stream`, `/api/upc/update/stream`), event strings MUST use actual newlines `\n\n`, NOT escaped newlines `\\n\\n`:

```python
# ✅ Correct - uses actual newlines
yield f"event: progress\ndata: {json.dumps(data)}\n\n"

# ❌ Wrong - uses escaped newlines (will break frontend parsing)
yield f"event: progress\ndata: {json.dumps(data)}\\n\\n"
```

### Pydantic Model Access
`ProductVariantMatch` and other Pydantic models must be accessed using attribute syntax, not dictionary syntax:

```python
# ✅ Correct - attribute access
store_id = match.store_id
store_name = match.store_name

# ❌ Wrong - dictionary access (will cause TypeError)
store_id = match["store_id"]
store_name = match["store_name"]
```

### UPC Search and Update Flow
1. **Search Phase**: Frontend calls `/api/upc/search/stream` with UPC
2. Backend searches all active stores (Shopify and MSSQL) in parallel
3. Results stream back via SSE with progress events
4. Frontend displays results in a table
5. **Update Phase**: User enters new UPC and clicks "Update All"
6. Frontend calls `/api/upc/update/stream` with old UPC, new UPC, and matches
7. Backend groups updates by store and executes updates
8. Progress streams back via SSE showing per-store results

### Shopify SKU Update Feature
When `update_sku_with_barcode` is enabled for a Shopify store:
- **Implementation**: Uses Shopify REST API (`PUT /admin/api/{version}/variants/{id}.json`)
- **NOT GraphQL**: The `productVariantsBulkUpdate` mutation does NOT support `sku` field
- **Individual Updates**: Makes separate PUT requests for each variant to update both `barcode` and `sku`
- **Payload Example**:
  ```python
  {
      "variant": {
          "id": 12345,
          "barcode": "012345678901",
          "sku": "012345678901"
      }
  }
  ```
- **Per-Store Setting**: Controlled by `shopify_connections.update_sku_with_barcode` column
- **Code Location**: `shopify_helper.py` lines 292-339 in `update_barcodes_for_product()`

### Backend Auto-Reload
The backend runs with `--reload` flag in development, which auto-restarts when Python files change. Watch logs to confirm reload:
```
WARNING:  WatchFiles detected changes in 'main.py'. Reloading...
```

## Configuration Import/Export

### Export Format
Configuration exports are JSON files with the following structure:
```json
{
  "version": "1.0",
  "exported_at": "2025-10-03T10:30:00Z",
  "mssql_stores": [
    {
      "name": "Store Name",
      "is_active": true,
      "connection": {
        "host": "192.168.1.100",
        "port": 1433,
        "database_name": "MyDB",
        "username": "user",
        "password": "pass"
      }
    }
  ],
  "shopify_stores": [
    {
      "name": "My Shopify",
      "is_active": true,
      "connection": {
        "shop_domain": "mystore.myshopify.com",
        "admin_api_key": "shpat_xxx",
        "api_version": "2025-01",
        "update_sku_with_barcode": false
      }
    }
  ]
}
```

### Usage
- **Export**: Navigate to Settings → Store Connections → Click "Export" button
- **Import**: Navigate to Settings → Store Connections → Click "Import" button → Select JSON file
- **Duplicate Handling**:
  - MSSQL stores with duplicate `host + port + database_name` are automatically skipped
  - Shopify stores with duplicate `shop_domain` are automatically skipped
- **Filename Format**: Exports are saved as `globalupc-config-YYYY-MM-DD-HHMMSS.json`

## Items Check (Store Comparison) Feature

### Overview
The Items Check tool compares `Items_tbl` between two MSSQL databases to identify products that exist in one store but not another. This is useful for:
- Verifying inventory consistency across multiple locations
- Identifying missing products when setting up new stores
- Auditing product catalogs between production and test databases
- Finding gaps in product distribution

### How It Works
1. User selects a **primary store** (the store being checked)
2. User selects a **comparison store** (the reference store to compare against)
3. System compares all products in primary store's `Items_tbl` against comparison store
4. Returns products that exist in primary but are missing from comparison store
5. Supports filtering by categories, subcategories, and discontinued status

### API Endpoints

**Category and Subcategory Retrieval**:
```python
GET /api/stores/mssql/{store_id}/categories
# Returns: List[CategoryResponse]
# Example: [{"category_id": 11, "category_name": "TOBACCO"}]

GET /api/stores/mssql/{store_id}/subcategories?category_id={id}
# Optional category_id filter
# Returns: List[SubCategoryResponse]
# Example: [{"subcategory_id": 101, "subcategory_name": "Cigarettes", "category_id": 11}]
```

**Comparison Endpoint** (SSE Streaming):
```python
POST /api/comparison/stores/stream
Request Body:
{
    "primary_store_id": 1,
    "comparison_store_id": 2,
    "filters": {
        "category_ids": [11, 13],  # Optional: filter by categories
        "subcategory_ids": [101],   # Optional: filter by subcategories
        "include_discontinued": false  # Default: false (active products only)
    }
}

Response Events:
- "starting": Initial event with total products and chunks
- "chunk_progress": Progress updates during processing
- "complete": Final results with missing products
- "error": Error information if comparison fails
```

### Implementation Details

**Chunked Processing** (`mssql_helper.py`):
- Processes products in chunks of 5,000 (configurable via `CHUNK_SIZE`)
- Uses `ROW_NUMBER()` window function for efficient pagination
- Joins with `Categories_tbl` and `SubCategories_tbl` for filter support

**SQL Server Parameter Limit**:
SQL Server has a **maximum of 2,100 parameters per query**. The comparison function handles this by:
1. Collecting up to 5,000 UPCs per chunk from primary store
2. Batching comparison queries into sub-batches of 2,000 UPCs max
3. Combining results from multiple batches into a single set

**Example**: For a chunk of 5,000 products:
- Batch 1: Check UPCs 1-2,000 against comparison store
- Batch 2: Check UPCs 2,001-4,000 against comparison store
- Batch 3: Check UPCs 4,001-5,000 against comparison store
- Merge all results into `existing_upcs` set

**Code Location** (`mssql_helper.py` lines 1670-1696):
```python
# SQL Server has a limit of 2100 parameters per query
MAX_PARAMS_PER_QUERY = 2000  # Safe limit below SQL Server's 2100 max

for batch_start in range(0, len(chunk_upcs), MAX_PARAMS_PER_QUERY):
    batch_end = min(batch_start + MAX_PARAMS_PER_QUERY, len(chunk_upcs))
    upc_batch = chunk_upcs[batch_start:batch_end]

    placeholders = ','.join(['?'] * len(upc_batch))
    comparison_query = f"SELECT ProductUPC FROM Items_tbl WHERE ProductUPC IN ({placeholders})"

    comparison_cursor.execute(comparison_query, upc_batch)
    batch_results = {row[0].strip() if row[0] else '' for row in comparison_cursor.fetchall()}
    existing_upcs.update(batch_results)
```

### Filter Behavior

**Categories and Subcategories**:
- Multiple categories can be selected (OR condition)
- Multiple subcategories can be selected (OR condition)
- Subcategories dropdown auto-populates based on selected categories
- If no filters selected, all products are included

**Discontinued Filter**:
The `Items_tbl.Discontinued` field indicates product status:
- `0` or `NULL` = Active product
- `1` = Discontinued product

**Checkbox behavior**:
- **Unchecked** (default): Only active products (`Discontinued = 0 OR NULL`)
- **Checked**: Both active AND discontinued products (no filter applied)

**Implementation** (`mssql_helper.py` lines 1563-1567):
```python
# If include_discontinued is False: only show active products
# If include_discontinued is True: show both active and discontinued
if not include_discontinued:
    where_clauses.append("(i.Discontinued = 0 OR i.Discontinued IS NULL)")
```

### Performance Characteristics

**Query Optimization**:
- **Old approach** (before fix): One SQL query per product → 18,750 queries for 18,750 products → 15-30 minutes
- **New approach** (optimized): 2-3 queries per 5,000-product chunk → ~10 queries total for 18,750 products → 5-10 seconds

**Expected Performance**:
- **Small comparisons** (< 5,000 products): Single chunk, completes in 1-2 seconds
- **Medium comparisons** (5,000-20,000 products): 1-4 chunks, completes in 3-8 seconds
- **Large comparisons** (20,000-100,000 products): 4-20 chunks, completes in 15-45 seconds

**Factors Affecting Performance**:
- Network latency between backend and MSSQL servers
- Database indexes on `ProductUPC` field (critical for performance)
- Number of products after filtering
- Server load on MSSQL instances

### Frontend Features

**Store Selection**:
- Dropdowns auto-populate with only MSSQL stores
- Primary and comparison stores must be different
- Category/subcategory filters load from primary store only

**Progress Indicators**:
- Real-time progress updates during comparison
- Chunk-level progress (e.g., "Chunk 2/4 (50%)")
- Product count updates (e.g., "10,000/18,750 products checked")
- Missing product count tracked in real-time

**Results Display**:
- Table with columns: #, Product ID, UPC, Description, Category, Subcategory, Status
- Category statistics badges (clickable to filter results)
- Category filter dropdown to focus on specific categories
- Export to CSV functionality
- Empty state when no missing products found

**CSV Export** (`app.js` function `exportComparisonToCSV`):
- Filename format: `comparison-{primary_store_name}-vs-{comparison_store_name}-YYYY-MM-DD.csv`
- Includes all result columns
- Automatically downloads to browser

### Schemas

**Request Schema** (`schemas.py` lines 271-279):
```python
class StoreComparisonFilters(BaseModel):
    category_ids: Optional[List[int]] = None
    subcategory_ids: Optional[List[int]] = None
    include_discontinued: bool = False

class StoreComparisonRequest(BaseModel):
    primary_store_id: int
    comparison_store_id: int
    filters: StoreComparisonFilters = StoreComparisonFilters()
```

**Response Schema** (`schemas.py` lines 282-298):
```python
class MissingProductRecord(BaseModel):
    product_id: int
    product_upc: str
    product_description: str
    category_name: str
    subcategory_name: str
    discontinued: bool

class StoreComparisonResponse(BaseModel):
    primary_store_id: int
    primary_store_name: str
    comparison_store_id: int
    comparison_store_name: str
    missing_products: List[MissingProductRecord]
    total_checked: int
    total_missing: int
    category_stats: Dict[str, int]  # category_name -> count
```

### Common Issues

**Timeout Errors During Comparison**:
- Likely caused by slow database queries or network latency
- Check database has indexes on `ProductUPC` in `Items_tbl`
- Reduce `CHUNK_SIZE` in `mssql_helper.py` (default: 5000)
- Verify network connectivity between backend and MSSQL servers

**SQL Parameter Error** (`Invalid descriptor index (0)`):
- This was the original bug caused by exceeding 2,100 parameter limit
- Should be fixed by batching logic (2,000 params per query)
- If still occurring, reduce `MAX_PARAMS_PER_QUERY` constant

**Frontend Not Starting After Restart**:
- Nginx may fail to resolve "backend" hostname if backend isn't ready
- Solution: `docker-compose restart frontend` after backend is healthy
- Check logs: `docker-compose logs frontend --tail 50`

**Empty Results When Products Should Be Missing**:
- Verify both stores have `Items_tbl` with `ProductUPC` field
- Check if filters are too restrictive (try with no filters)
- Verify UPC values don't have leading/trailing whitespace (handled by normalization)

**Categories Not Loading**:
- Ensure `Categories_tbl` exists in MSSQL database
- Check store connection is active and credentials are correct
- Review backend logs for SQL errors

## Troubleshooting

### Backend won't start
```bash
# Check logs for Python errors
docker-compose logs backend --tail 100

# Verify database is healthy
docker-compose ps
```

### MSSQL connection fails with "file not found"
The ODBC driver path is incorrect. Verify:
```bash
docker exec globalupc_backend cat /etc/odbcinst.ini
docker exec globalupc_backend ls -la /usr/lib/*/odbc/libtdsodbc.so
```

If paths don't match, rebuild the backend container.

### Shopify connection fails with "Invalid API key"
- Verify the shop domain is correct (must end with `.myshopify.com`)
- Verify the Admin API key is valid and has proper permissions
- Check the API version is supported (currently `2025-01`)

### Frontend changes not reflecting
Due to no-cache headers, this should not happen. If it does:
```bash
# Hard refresh in browser (Cmd+Shift+R or Ctrl+Shift+R)
# Or rebuild frontend container
docker-compose build frontend && docker-compose up -d frontend
```

### Database connection refused
Check that PostgreSQL is healthy and port 5433 is not in use:
```bash
docker-compose ps
lsof -i :5433
```

## Frontend UI Features

### Collapsible Search Results
Search results display stores in a collapsible format to save vertical space:
- **Collapsed view** (default): One row per store showing total products and matches
- **Expanded view**: Click store row to see individual product details
- **Visual indicators**:
  - Row numbers (gray, muted)
  - Expand/collapse icon (▶/▼)
  - Store names (accent color)
  - Product count (green, bold)
  - Total matches (orange, bold)

Implementation details in `frontend/src/app.js` (`displayUPCResults` function) and `frontend/src/styles.css` (`.store-row`, `.product-detail-row` classes).

### Search Progress Safeguards
The search function includes protection against multiple simultaneous searches:
- Global `isSearching` flag prevents concurrent search requests
- Search button disabled during active search
- Flag resets on completion, error, or via `finally` block

This prevents search loops caused by rapid button clicks or held Enter key.

### Theme System
Six dark mode themes available, all using CSS custom properties. Theme selection persists to `localStorage`. Themes range from purple accent (default) to pure grayscale to true black high-contrast.

## SQL UPC Audit Feature

### Overview
The SQL UPC Audit tool validates data integrity across MSSQL databases by checking if UPCs in detail tables exist in the master Items_tbl. This is MSSQL-specific and does not apply to Shopify stores.

### How It Works
1. User selects an MSSQL store to audit
2. System checks all detail tables (excluding Items_tbl) for UPCs
3. For each UPC found, verifies it exists in Items_tbl
4. Reports any "orphaned" UPCs (UPCs in detail tables but not in Items_tbl)
5. Shows real-time progress via SSE streaming

### Detail Tables Checked
- QuotationsDetails_tbl
- PurchaseOrdersDetails_tbl
- InvoicesDetails_tbl
- CreditMemosDetails_tbl
- PurchasesReturnsDetails_tbl
- QuotationDetails

**Note**: Items_tbl is NOT checked (it's the master reference table)

### Chunked Processing
The audit uses chunked processing to handle large tables (200K+ records) without timeout:
- **Chunk Size**: 5,000 records per chunk (configurable via `CHUNK_SIZE` in `mssql_helper.py`)
- **Query Strategy**: Uses CTE with ROW_NUMBER() and LEFT JOIN to check 5,000 records at a time
- **Progress Updates**: Sends SSE events after each chunk showing:
  - Chunk number (e.g., "Chunk 10/50")
  - Records checked (e.g., "50,000/246,194 records")
  - Orphans found in this chunk and total orphans
- **Heartbeat**: Sends `:ping\n\n` every 15 seconds to keep SSE connection alive

### Implementation Details

**Backend** (`mssql_helper.py`):
```python
# True chunked query using CTE
WITH numbered_records AS (
    SELECT pk, description, ProductUPC, ROW_NUMBER() OVER (ORDER BY pk) as row_num
    FROM QuotationsDetails_tbl
    WHERE ProductUPC IS NOT NULL
)
SELECT n.pk, n.description, n.ProductUPC
FROM numbered_records n
LEFT JOIN Items_tbl i ON n.ProductUPC = i.ProductUPC
WHERE n.row_num > ? AND n.row_num <= ?
AND i.ProductUPC IS NULL  -- Only orphans
```

**SSE Heartbeat** (`main.py`):
- Tracks time since last event
- Sends heartbeat ping every 15 seconds during processing
- Prevents `ERR_INCOMPLETE_CHUNKED_ENCODING` timeout error

**Frontend** (`app.js`):
- Handles `chunk_progress` events to show real-time updates
- Displays: "QuotationsDetails_tbl: Chunk 10/50 (20%) - 50,000/246,194 records - 42 orphans found"
- Color coding: orange for in-progress, green for complete (no orphans), red for orphans found

### Orphaned Records Tracking
All orphaned records are stored with complete metadata:
- `table_name`: Source table (e.g., "InvoicesDetails_tbl")
- `primary_key`: Record's LineID or ProductID
- `upc`: The orphaned UPC value
- `description`: Product description from the record

This enables future operations like:
- Bulk fixing orphaned UPCs
- Deleting orphaned records
- Exporting audit results
- Cross-referencing with other systems

### Performance Characteristics
- **Small tables** (< 5,000 records): Single chunk, completes in seconds
- **Medium tables** (5,000-50,000 records): 1-10 chunks, shows progress every few seconds
- **Large tables** (50,000-500,000 records): 10-100 chunks, continuous progress updates
- **Very large tables** (500,000+ records): 100+ chunks, each chunk processes in 1-3 seconds

### Date-Range Filtering

The audit feature supports optional date-range filtering to audit only records within a specific time period.

**Implementation** (`backend/mssql_helper.py`, `backend/schemas.py`, `backend/main.py`):
- Accepts optional `date_from` and `date_to` parameters (Python `date` type)
- Uses `DETAIL_TABLE_MAPPING` constant to map detail tables to their header tables
- Dynamically constructs SQL queries with INNER JOINs to header tables for date filtering
- Special handling for `QuotationDetails` table (has `DateCreate` directly in detail table)

**Header Table Mappings** (`mssql_helper.py:12-43`):
```python
DETAIL_TABLE_MAPPING = {
    "QuotationsDetails_tbl": {
        "header_table": "Quotations_tbl",
        "join_key": "QuotationID",
        "date_field": "QuotationDate"
    },
    "PurchaseOrdersDetails_tbl": {
        "header_table": "PurchaseOrders_tbl",
        "join_key": "PoID",
        "date_field": "PoDate"
    },
    # ... additional mappings
}
```

**Query Example** (with date filtering):
```sql
-- Joins detail table with header table and filters by date
WITH numbered_records AS (
    SELECT d.LineID, d.ProductDescription, d.ProductUPC, ROW_NUMBER() OVER (ORDER BY d.LineID)
    FROM QuotationsDetails_tbl d
    INNER JOIN Quotations_tbl h ON d.QuotationID = h.QuotationID
    WHERE d.ProductUPC IS NOT NULL
    AND h.QuotationDate >= ? AND h.QuotationDate <= ?
)
SELECT n.LineID, n.ProductDescription, n.ProductUPC
FROM numbered_records n
LEFT JOIN Items_tbl i ON n.ProductUPC = i.ProductUPC
WHERE n.row_num > ? AND n.row_num <= ?
AND i.ProductUPC IS NULL
```

**Frontend** (`frontend/src/index.html`, `frontend/src/app.js`):
- Two optional date inputs: "From Date" and "To Date"
- Dates sent as ISO format strings (`YYYY-MM-DD`)
- Leave empty to audit all records (backward compatible)

**Use Cases**:
- Audit only recent transactions (e.g., last month)
- Focus on specific date range for data migration validation
- Reduce audit scope for faster results on large databases

### Table Statistics and Filtering

Audit results display per-table statistics and support filtering by table for focused analysis.

**Statistics Badges** (`frontend/src/index.html:1110-1121`, `frontend/src/app.js:1433-1464`):
- Visual breakdown showing orphaned UPC count per table
- Badges sorted by count (highest first)
- Clickable to filter results by that table
- Example: `[Quotation Details: 50] [Invoice Details: 30] [Purchase Orders: 12]`

**Table Filter Dropdown** (`frontend/src/index.html:1123-1132`, `frontend/src/app.js:1467-1480`):
- Dropdown with "All Tables" + individual table options
- Shows count in parentheses for each table
- Automatically populated from audit results

**Dynamic Summary Text** (`frontend/src/index.html:1104-1108`, `frontend/src/app.js:1560-1609`):
- **No filter**: "42 orphaned UPCs found across 3 tables"
- **With filter**: "15 of 42 orphaned UPCs (filtered by Quotation Details)"

**Filtering Logic** (`frontend/src/app.js:1560-1609`):
- Hides non-matching rows using `row.style.display = "none"`
- Renumbers visible rows sequentially (1, 2, 3...)
- Updates selection count and button states

**CSS Styling** (`frontend/src/styles.css:977-1012`):
- Badge styles with hover effects and transitions
- Color-coded table names and counts
- Responsive layout with flexbox

### Reconciliation with Filtered Results

The "Find Matches by ProductID" and "Find Matches by Description" buttons respect table filtering and only process visible selected records.

**Implementation** (`frontend/src/app.js`):

1. **`getSelectedOrphanedRecords()` function** (lines 1683-1705):
   - Only returns checked records from visible rows
   - Filters out hidden rows using `row.style.display !== "none"`

2. **"Select All" checkbox handler** (lines 1637-1650):
   - Only checks/unchecks checkboxes in visible rows
   - Hidden rows remain unaffected by "Select All"

3. **`updateReconciliationButtons()` function** (lines 1612-1635):
   - Counts only visible checked records
   - Updates button state based on visible selection count

4. **Individual checkbox handler** (lines 1652-1676):
   - Updates "Select All" state based on visible checkboxes only
   - Filters out hidden rows when determining if all visible rows are checked

**Pattern Used**:
```javascript
const row = cb.closest("tr");
if (row && row.style.display !== "none") {
  // Only process visible rows
}
```

**User Experience**:
- Filter to specific table (e.g., "Invoice Details" with 30 records)
- Click "Select All" → Only visible 30 records get checked
- Status shows "30 selected" (accurate count)
- Click "Find Matches by ProductID" → System processes exactly 30 visible records
- Hidden records from other tables are not included in reconciliation

### Common Issues
**Timeout Errors**: If audit times out despite chunking:
- Reduce `CHUNK_SIZE` in `mssql_helper.py` (try 2,500 or 1,000)
- Check database performance (indexes on ProductUPC field recommended)
- Verify network connectivity between containers

**No Progress Updates**: If frontend doesn't show chunk progress:
- Hard refresh browser (`Cmd+Shift+R`) to clear JavaScript cache
- Check browser console for SSE connection errors
- Verify backend logs show chunk progress events being sent

**Empty Results**: If no orphans found but expected some:
- Verify Items_tbl exists in the database
- Check ProductUPC field names match across tables
- Review backend logs for `table_skipped` events (table doesn't exist)

**Date Filtering Not Working**: If date-range filtering returns unexpected results:
- Verify header table names and date fields in `DETAIL_TABLE_MAPPING` match your database schema
- Check backend logs for SQL errors indicating incorrect table/field names
- Test with no dates first to confirm tables are accessible
