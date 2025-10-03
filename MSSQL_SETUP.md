# MSSQL FreeTDS Configuration

This application uses **FreeTDS** for MSSQL/SQL Server connectivity, providing excellent support for older SQL Server versions.

## What is FreeTDS?

FreeTDS is a free, open-source implementation of the TDS (Tabular Data Stream) protocol used by Microsoft SQL Server and Sybase. It provides better compatibility with older SQL Server versions compared to Microsoft's proprietary drivers.

## Supported SQL Server Versions

FreeTDS supports all SQL Server versions through TDS protocol versions:

| TDS Version | SQL Server Version(s) |
|-------------|----------------------|
| 7.0 | SQL Server 7.0 |
| 7.1 | SQL Server 2000 |
| 7.2 | SQL Server 2005 |
| 7.3 | SQL Server 2008 |
| 7.4 | SQL Server 2012/2014/2016/2017/2019/2022 |

**Default**: TDS 7.4 (supports newest versions and maintains backward compatibility)

## Configuration Files

### `/etc/freetds/freetds.conf`
Main FreeTDS configuration file with global settings:
- TDS protocol version
- Character encoding
- Timeout settings
- Encryption options

### `/etc/odbcinst.ini`
ODBC driver registration (auto-configured in Docker)

## Connection Helper

The `mssql_helper.py` module provides:

### `get_mssql_connection_string()`
Generates FreeTDS ODBC connection strings with proper settings.

```python
from mssql_helper import get_mssql_connection_string

conn_str = get_mssql_connection_string(
    host="192.168.1.100",
    port=1433,
    database="MyDatabase",
    username="sa",
    password="MyPassword",
    tds_version="7.4"  # Optional, defaults to 7.4
)
```

### `test_mssql_connection()`
Test MSSQL connectivity before saving configuration.

```python
from mssql_helper import test_mssql_connection

success, error = test_mssql_connection(
    host="192.168.1.100",
    port=1433,
    database="MyDatabase",
    username="sa",
    password="MyPassword"
)

if success:
    print("Connection successful!")
else:
    print(f"Connection failed: {error}")
```

## Using with Older SQL Server Versions

If connecting to SQL Server 2000 or 2005, update the TDS version when adding the store:

1. Add MSSQL Database in the UI
2. Change API Version field to match your SQL Server:
   - SQL Server 2000: `7.1`
   - SQL Server 2005: `7.2`
   - SQL Server 2008: `7.3`
   - SQL Server 2012+: `7.4` (default)

## Troubleshooting

### Connection Issues

1. **Check FreeTDS is installed:**
   ```bash
   docker exec globalupc_backend tsql -C
   ```

2. **Test connection from container:**
   ```bash
   docker exec -it globalupc_backend bash
   tsql -H your-server -p 1433 -U username -P password
   ```

3. **View available ODBC drivers:**
   ```python
   from mssql_helper import get_available_drivers
   print(get_available_drivers())
   ```

### Enable Debug Logging

Edit `backend/freetds.conf`:
```ini
[global]
    dump file = /tmp/freetds.log
    debug flags = 0xffff
```

Then check logs:
```bash
docker exec globalupc_backend cat /tmp/freetds.log
```

## Docker Setup

FreeTDS packages are automatically installed in the backend container:
- `freetds-dev` - Development libraries
- `freetds-bin` - Command-line tools (tsql, freebcp)
- `tdsodbc` - ODBC driver
- `unixodbc` - ODBC driver manager

No additional setup required!

## References

- [FreeTDS Official Site](https://www.freetds.org/)
- [FreeTDS User Guide](https://www.freetds.org/userguide/)
- [TDS Protocol Versions](https://www.freetds.org/userguide/choosingtdsprotocol.html)
