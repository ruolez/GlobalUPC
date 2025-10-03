# Global UPC

A centralized barcode management application for maintaining accurate UPC barcodes across multiple MSSQL databases and Shopify stores.

## Features

- **Multi-Store Management**: Connect and manage multiple MSSQL databases and Shopify stores from a single interface
- **Real-Time Search**: Search for UPC barcodes across all connected stores with live progress updates
- **Bulk Updates**: Update UPC barcodes across all stores simultaneously
- **Configuration Export/Import**: Save and restore store configurations as JSON
- **Dark Mode Themes**: Choose from 6 carefully crafted dark mode color schemes
- **Collapsible Results**: Space-efficient search results with expandable store details

## Architecture

Docker-based multi-container application:
- **Backend**: FastAPI (Python) with MSSQL (FreeTDS) and Shopify Admin API integration
- **Frontend**: Single-page application (Vanilla JS) with modern dark UI
- **Database**: PostgreSQL 15 for storing store configurations

## Quick Start

### Prerequisites
- Docker and Docker Compose
- For MSSQL connections: Access to SQL Server databases
- For Shopify connections: Shopify Admin API access tokens

### Installation

1. Clone the repository:
```bash
git clone https://github.com/ruolez/GlobalUPC.git
cd GlobalUPC
```

2. Start the application:
```bash
docker-compose up -d
```

3. Access the application:
- Frontend: http://localhost:8080
- Backend API: http://localhost:8001
- API Documentation: http://localhost:8001/docs

### Configuration

1. Navigate to **Settings** in the web interface
2. Add your stores:
   - **MSSQL**: Click "Add MSSQL Database" and enter connection details
   - **Shopify**: Click "Add Shopify Store" and enter shop domain and API key
3. Test connections before saving
4. Enable/disable stores as needed

## Usage

### Search for UPC
1. Go to **Update UPC** page
2. Enter a UPC/barcode
3. Click **Search**
4. View results grouped by store (click to expand details)

### Update UPC
1. After searching, enter the new UPC in the second input field
2. Click **Update All**
3. Monitor real-time progress
4. Review update summary

### Export/Import Configuration
- **Export**: Settings → Store Connections → Export (saves JSON file)
- **Import**: Settings → Store Connections → Import (select JSON file)

## Development

See [CLAUDE.md](CLAUDE.md) for detailed development documentation including:
- Docker commands and debugging
- Database schema
- API endpoints
- FreeTDS configuration
- Shopify integration details
- Frontend architecture

### Common Commands

```bash
# View logs
docker-compose logs -f backend

# Restart service
docker-compose restart backend

# Rebuild containers
docker-compose up -d --build

# Access database
docker exec -it globalupc_db psql -U globalupc -d globalupc
```

## MSSQL Integration

Uses FreeTDS for broad SQL Server compatibility (SQL Server 7.0 through 2022). The application searches across multiple tables in each connected database:
- Items_tbl
- QuotationsDetails_tbl
- PurchaseOrdersDetails_tbl
- InvoicesDetails_tbl
- And more...

See [MSSQL_SETUP.md](MSSQL_SETUP.md) for detailed configuration.

## Shopify Integration

Uses Shopify Admin REST API with access tokens. Supports:
- Barcode search across all product variants
- Bulk barcode updates
- Optional SKU synchronization with barcode values

## Theme System

Six dark mode themes available:
- **Current** (default): Purple accent with rainbow gradients
- **Monochrome**: Pure grayscale, corporate feel
- **Charcoal**: Warm gray tones
- **Steel**: Cool blue-gray
- **Minimal**: Low contrast, easy on eyes
- **Graphite**: True black, maximum contrast

## Port Configuration

- `8080` - Frontend (Nginx)
- `8001` - Backend API (FastAPI)
- `5433` - PostgreSQL (mapped from container port 5432)

## License

MIT

## Support

For issues, questions, or contributions, please open an issue on GitHub.
