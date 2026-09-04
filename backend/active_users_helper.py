"""Active-clients tracking: per-IP activity buffered in memory and flushed to
PostgreSQL so all uvicorn workers share one view.

The ASGI middleware in main.py calls record_activity() on every /api request
(except health checks); flush_activity_loop() runs once per worker and batches
the buffer into active_clients every FLUSH_INTERVAL seconds, so the DB pool
never sees per-request write load.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import text

from database import db_session

FLUSH_INTERVAL = 10
SESSION_GAP_MINUTES = 30
PRUNE_AFTER_HOURS = 24

# ip -> {"first": datetime, "last": datetime, "count": int, "section": str|None}
# Mutated only on the event loop, so no lock is needed.
_activity_buffer = {}

# First path segment after /api/ -> sidebar section name. Unknown segments fall
# back to a title-cased version of the segment so new features still show up.
_SECTION_MAP = {
    "upc": "UPC Search",
    "analysis": "Orphan UPC Audit",
    "price-updates": "Price Updates",
    "item-tracker": "Item Tracker",
    "sales": "Sales",
    "shopify-sales": "Shopify Sales",
    "shopify-analytics": "Shopify Analytics",
    "shopify-sync": "Data Sync",
    "shopify": "Shopify Sales",
    "quotations": "In Progress",
    "business-overview": "Business Overview",
    "quickbooks": "QuickBooks",
    "inventory-time": "Inventory Time",
    "checked-orders": "Checked Orders",
    "history": "History",
    "dashboard": "Dashboard",
    "stores": "Settings",
    "settings": "Settings",
    "store-mirrors": "Settings",
    "exclusions": "Settings",
    "config": "Settings",
    "test": "Settings",
    "easyship": "Settings",
    "active-users": "Settings",
}

_UPSERT_SQL = text(f"""
    INSERT INTO active_clients (ip, first_seen, last_seen, request_count, last_section)
    VALUES (:ip, :first, :last, :count, :section)
    ON CONFLICT (ip) DO UPDATE SET
        first_seen = CASE
            WHEN active_clients.last_seen < now() - interval '{SESSION_GAP_MINUTES} minutes'
            THEN EXCLUDED.first_seen
            ELSE active_clients.first_seen
        END,
        request_count = active_clients.request_count + EXCLUDED.request_count,
        last_section = CASE
            WHEN EXCLUDED.last_seen >= active_clients.last_seen AND EXCLUDED.last_section IS NOT NULL
            THEN EXCLUDED.last_section
            ELSE active_clients.last_section
        END,
        last_seen = GREATEST(active_clients.last_seen, EXCLUDED.last_seen)
""")

_PRUNE_SQL = text(f"""
    DELETE FROM active_clients
    WHERE last_seen < now() - interval '{PRUNE_AFTER_HOURS} hours'
""")


def resolve_client_ip(scope) -> str | None:
    # X-Real-IP is set by nginx from $remote_addr and cannot be spoofed through
    # the proxy; direct hits on the published backend port carry no header, so
    # the socket peer is the real client there. X-Forwarded-For is deliberately
    # ignored (its first element is client-controlled).
    for name, value in scope.get("headers") or []:
        if name == b"x-real-ip":
            ip = value.decode("latin-1").strip()
            return ip or None
    client = scope.get("client")
    return client[0] if client else None


def section_for_path(path: str) -> str | None:
    segment = path[len("/api/"):].split("/", 1)[0] if path.startswith("/api/") else ""
    if not segment:
        return None
    return _SECTION_MAP.get(segment) or segment.replace("-", " ").title()


def record_activity(ip: str, section: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    entry = _activity_buffer.get(ip)
    if entry is None:
        _activity_buffer[ip] = {"first": now, "last": now, "count": 1, "section": section}
    else:
        entry["last"] = now
        entry["count"] += 1
        if section is not None:
            entry["section"] = section


def _flush_snapshot(snapshot: dict) -> None:
    with db_session() as db:
        for ip, entry in snapshot.items():
            db.execute(_UPSERT_SQL, {
                "ip": ip,
                "first": entry["first"],
                "last": entry["last"],
                "count": entry["count"],
                "section": entry.get("section"),
            })
        db.execute(_PRUNE_SQL)
        db.commit()


async def flush_activity_buffer() -> None:
    global _activity_buffer
    if not _activity_buffer:
        return
    snapshot, _activity_buffer = _activity_buffer, {}
    try:
        await asyncio.to_thread(_flush_snapshot, snapshot)
    except Exception as e:
        print(f"[ACTIVE-USERS] flush failed, will retry: {e}")
        # Merge the snapshot back so the activity isn't lost on a DB hiccup.
        for ip, entry in snapshot.items():
            current = _activity_buffer.get(ip)
            if current is None:
                _activity_buffer[ip] = entry
            else:
                current["first"] = min(current["first"], entry["first"])
                current["count"] += entry["count"]


async def flush_activity_loop() -> None:
    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL)
            await flush_activity_buffer()
        except asyncio.CancelledError:
            # Final flush so the last few seconds of activity survive a deploy.
            await flush_activity_buffer()
            raise
        except Exception as e:
            print(f"[ACTIVE-USERS] flush loop error: {e}")
