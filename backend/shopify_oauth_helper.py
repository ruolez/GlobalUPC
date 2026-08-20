"""
Shopify OAuth client credentials grant.

For stores configured with auth_method='client_credentials', the app exchanges
the per-store Dev Dashboard app credentials (client_id + client_secret) for a
24h Admin API access token and caches it in shopify_connections.admin_api_key,
so every existing call site keeps reading the same column. A background loop
started from the FastAPI lifespan keeps cached tokens fresh.
"""

import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import requests

from shopify_helper import validate_shop_domain

# Refresh tokens with less than 6h validity left; long-running bulk syncs
# snapshot the token once, so keep a generous floor.
REFRESH_MARGIN_SECONDS = 6 * 3600
LOOP_INTERVAL_SECONDS = 30 * 60


def fetch_client_credentials_token(
    shop_domain: str,
    client_id: str,
    client_secret: str,
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Exchange app credentials for a 24h Admin API access token.

    Returns:
        (success, error_message, token_data) where token_data is Shopify's
        response: {"access_token", "scope", "expires_in"}.
    """
    try:
        domain = validate_shop_domain(shop_domain)
    except ValueError as e:
        return False, str(e), None

    url = f"https://{domain}/admin/oauth/access_token"
    try:
        response = requests.post(
            url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=10,
        )
    except requests.exceptions.Timeout:
        return False, "Connection timeout - shop may be unreachable", None
    except requests.exceptions.ConnectionError:
        return False, "Connection error - check shop domain and network", None
    except requests.exceptions.RequestException as e:
        return False, f"Request error: {str(e)}", None

    if response.status_code == 200:
        try:
            data = response.json()
        except ValueError:
            return False, "Shopify returned an unreadable token response", None
        if not data.get("access_token"):
            return False, "Shopify returned no access token", None
        return True, None, data

    error_code = ""
    try:
        body = response.json() if response.content else {}
        error_code = str(body.get("error") or body.get("errors") or "")
    except ValueError:
        pass

    if "shop_not_permitted" in error_code:
        return False, (
            "Store is not in the same Shopify organization as the app, "
            "or the app is not installed on this store"
        ), None
    if response.status_code == 401 or "invalid_client" in error_code:
        return False, "Invalid client ID or client secret", None
    if response.status_code == 404:
        return False, "Shop not found - check shop domain", None
    return False, error_code or f"HTTP {response.status_code}: {response.reason}", None


def apply_token(conn, token_data: Dict[str, Any]) -> None:
    """Write a freshly issued token onto a ShopifyConnection row (no commit)."""
    conn.admin_api_key = token_data["access_token"]
    expires_in = int(token_data.get("expires_in") or 86399)
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)


def _refresh_due_tokens() -> None:
    """One refresh pass over every client_credentials connection nearing expiry."""
    from database import SessionLocal
    from models import ShopifyConnection

    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) + timedelta(seconds=REFRESH_MARGIN_SECONDS)
        due = (
            db.query(ShopifyConnection)
            .filter(ShopifyConnection.auth_method == "client_credentials")
            .filter(
                (ShopifyConnection.token_expires_at.is_(None))
                | (ShopifyConnection.token_expires_at < cutoff)
            )
            .all()
        )
        for conn in due:
            try:
                success, error, token_data = fetch_client_credentials_token(
                    conn.shop_domain, conn.client_id, conn.client_secret
                )
                if success:
                    apply_token(conn, token_data)
                    db.commit()
                    print(f"[SHOPIFY-OAUTH] Refreshed token for {conn.shop_domain} (expires {conn.token_expires_at})")
                else:
                    # Old token (if any) stays in place until its own expiry.
                    db.rollback()
                    print(f"[SHOPIFY-OAUTH] Token refresh failed for {conn.shop_domain}: {error}")
            except Exception as e:
                db.rollback()
                print(f"[SHOPIFY-OAUTH] Token refresh error for {conn.shop_domain}: {e}")
    finally:
        db.close()


async def token_refresh_loop() -> None:
    """Background task: periodic refresh of OAuth access tokens."""
    # Stagger the prod workers so 4 loops don't fire in lockstep (races are
    # harmless anyway - every issued token is independently valid).
    await asyncio.sleep(random.uniform(0, 30))
    while True:
        try:
            await asyncio.to_thread(_refresh_due_tokens)
        except Exception as e:
            print(f"[SHOPIFY-OAUTH] Refresh pass failed: {e}")
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
