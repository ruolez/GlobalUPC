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
