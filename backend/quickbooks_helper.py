"""
QuickBooks Online (Intuit) integration.

OAuth 2.0 authorization-code flow with a *paste-back* callback: the app runs on
a plain-HTTP LAN address and Intuit only accepts https redirect URIs in
production, so the user approves in a new tab, lands on a placeholder page
they registered in the Intuit portal, and pastes the resulting URL
(`?code=…&state=…&realmId=…`) into Settings. Tokens live on the singleton
`quickbooks_connection` row; Bank / Credit Card balances are cached in
`quickbooks_accounts` and refreshed on demand when older than
`refresh_minutes`.

Every network call here is synchronous `requests` — always invoke the
DB-touching entry points via `asyncio.to_thread` (or from sync endpoints).
Refresh tokens rotate on every token call, so a refresh is serialised across
uvicorn workers with a row lock and the latest refresh token is always
persisted.
"""

import asyncio
import base64
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from sqlalchemy import text as sa_text

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
API_BASE = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}
SCOPE = "com.intuit.quickbooks.accounting"
MINOR_VERSION = "75"
ACCOUNT_QUERY = (
    "SELECT * FROM Account WHERE AccountType IN ('Bank','Credit Card') "
    "AND Active = true MAXRESULTS 1000"
)
STATE_TTL_SECONDS = 600
TOKEN_REFRESH_MARGIN_SECONDS = 300
HTTP_TIMEOUT = 15
KEEPALIVE_LOOP_SECONDS = 6 * 3600
KEEPALIVE_IF_OLDER_THAN = timedelta(days=6)

STATUS_DISCONNECTED = "disconnected"
STATUS_CONNECTED = "connected"
STATUS_NEEDS_RECONNECT = "needs_reconnect"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Pure helpers (no DB, no network)
# ---------------------------------------------------------------------------

def build_authorize_url(conn, state: str) -> str:
    if not conn.client_id:
        raise ValueError("Client ID is not set")
    if not conn.redirect_uri:
        raise ValueError("Redirect URI is not set")
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": conn.client_id,
        "response_type": "code",
        "scope": SCOPE,
        "redirect_uri": conn.redirect_uri,
        "state": state,
    })


def parse_callback_input(text: str) -> Dict[str, Optional[str]]:
    """Accept the full redirected URL or just its query string."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Paste the URL Intuit redirected you to")
    query = raw
    if "://" in raw:
        parts = urlsplit(raw)
        query = parts.query or ""
        if "code=" not in query and "code=" in (parts.fragment or ""):
            query = parts.fragment.lstrip("?/")
    query = query.lstrip("?")
    qs = parse_qs(query, keep_blank_values=False)
    code = (qs.get("code") or [None])[0]
    if not code:
        raise ValueError(
            "No authorization code found in what you pasted — copy the full URL "
            "from the address bar after approving in QuickBooks"
        )
    realm = (qs.get("realmId") or qs.get("realmid") or [None])[0]
    return {"code": code, "state": (qs.get("state") or [None])[0], "realm_id": realm}


def normalize_account(raw: Dict[str, Any]) -> Dict[str, Any]:
    def num(v):
        try:
            return round(float(v), 2) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "qbo_id": str(raw.get("Id")),
        "name": raw.get("Name") or "",
        "fully_qualified_name": raw.get("FullyQualifiedName"),
        "account_type": raw.get("AccountType") or "",
        "account_sub_type": raw.get("AccountSubType"),
        "current_balance": num(raw.get("CurrentBalance")) or 0.0,
        "current_balance_with_sub_accounts": num(raw.get("CurrentBalanceWithSubAccounts")),
        "sub_account": bool(raw.get("SubAccount")),
        "parent_qbo_id": (raw.get("ParentRef") or {}).get("value"),
        "currency": (raw.get("CurrencyRef") or {}).get("value"),
        "active": raw.get("Active", True) is not False,
    }


# ---------------------------------------------------------------------------
# Intuit OAuth + QBO API (sync requests)
# ---------------------------------------------------------------------------

def _basic_auth_headers(client_id: str, client_secret: str) -> Dict[str, str]:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _request_error(e: Exception) -> str:
    if isinstance(e, requests.exceptions.Timeout):
        return "Connection timeout - QuickBooks did not respond"
    if isinstance(e, requests.exceptions.ConnectionError):
        return "Connection error - QuickBooks unreachable"
    return f"Request error: {e}"


def _token_request(client_id: str, client_secret: str, body: Dict[str, str]) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """POST to the token endpoint. Error strings start with Intuit's error code."""
    if not client_id or not client_secret:
        return False, "invalid_client: Client ID / Client Secret are not set", None
    try:
        resp = requests.post(TOKEN_URL, headers=_basic_auth_headers(client_id, client_secret),
                             data=body, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return False, _request_error(e), None
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    if resp.status_code == 200:
        if not data.get("access_token"):
            return False, "Intuit returned no access token", None
        return True, None, data
    code = str(data.get("error") or "")
    desc = str(data.get("error_description") or "")
    if code == "invalid_client" or resp.status_code == 401:
        return False, "invalid_client: Invalid client ID or client secret", None
    if code:
        return False, f"{code}: {desc}".strip(": "), None
    return False, f"HTTP {resp.status_code}: {resp.reason}", None


def exchange_code(conn, code: str):
    return _token_request(conn.client_id, conn.client_secret, {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": conn.redirect_uri or "",
    })


def refresh_access_token(conn):
    return _token_request(conn.client_id, conn.client_secret, {
        "grant_type": "refresh_token",
        "refresh_token": conn.refresh_token or "",
    })


def apply_token(conn, data: Dict[str, Any]) -> None:
    """Write a token response onto the row (no commit). Always keeps the newest refresh token."""
    now = _utcnow()
    conn.access_token = data["access_token"]
    conn.access_token_expires_at = now + timedelta(seconds=int(data.get("expires_in") or 3600))
    conn.refresh_token = data.get("refresh_token") or conn.refresh_token
    rt_exp = data.get("x_refresh_token_expires_in")
    if rt_exp:
        try:
            conn.refresh_token_expires_at = now + timedelta(seconds=int(rt_exp))
        except (TypeError, ValueError):
            pass
    conn.last_error = None


def revoke(conn) -> Tuple[bool, Optional[str]]:
    if not conn.refresh_token or not conn.client_id or not conn.client_secret:
        return False, "Nothing to revoke"
    headers = _basic_auth_headers(conn.client_id, conn.client_secret)
    headers["Content-Type"] = "application/json"
    try:
        resp = requests.post(REVOKE_URL, headers=headers, json={"token": conn.refresh_token}, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return False, _request_error(e)
    if resp.status_code in (200, 204):
        return True, None
    return False, f"HTTP {resp.status_code}: {resp.reason}"


def _fault_message(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    fault = body.get("Fault") or body.get("fault")
    if not isinstance(fault, dict):
        return None
    errs = fault.get("Error") or fault.get("error") or []
    if isinstance(errs, list) and errs and isinstance(errs[0], dict):
        e = errs[0]
        msg = e.get("Message") or e.get("message") or ""
        detail = e.get("Detail") or e.get("detail") or ""
        text = f"{msg}: {detail}".strip(": ")
        return text or None
    return None


def _api_get(conn, path: str, params: Optional[Dict[str, str]] = None) -> Tuple[int, Optional[Dict[str, Any]], Optional[str]]:
    base = API_BASE.get(conn.environment or "production")
    if not base:
        return 0, None, f"Unknown QuickBooks environment: {conn.environment}"
    if not conn.realm_id:
        return 0, None, "No QuickBooks company (realmId) connected"
    url = f"{base}/v3/company/{conn.realm_id}{path}"
    query = dict(params or {})
    query["minorversion"] = MINOR_VERSION
    headers = {"Authorization": f"Bearer {conn.access_token or ''}", "Accept": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params=query, timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as e:
        return 0, None, _request_error(e)
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = None
    if resp.status_code == 200 and isinstance(body, dict):
        return 200, body, None
    err = _fault_message(body) or f"HTTP {resp.status_code}: {resp.reason}"
    return resp.status_code, None, err


def fetch_accounts(conn) -> Tuple[bool, Optional[str], List[Dict[str, Any]], bool]:
    """Returns (ok, error, normalized_rows, unauthorized)."""
    status, body, err = _api_get(conn, "/query", {"query": ACCOUNT_QUERY})
    if status == 401:
        return False, err or "Unauthorized", [], True
    if status != 200 or body is None:
        return False, err or f"HTTP {status}", [], False
    rows = (body.get("QueryResponse") or {}).get("Account") or []
    return True, None, [normalize_account(r) for r in rows if isinstance(r, dict)], False


def fetch_company_name(conn) -> Optional[str]:
    try:
        status, body, _ = _api_get(conn, f"/companyinfo/{conn.realm_id}")
        if status == 200 and body:
            return (body.get("CompanyInfo") or {}).get("CompanyName")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# DB-touching (sync)
# ---------------------------------------------------------------------------

def get_conn(db):
    from models import QuickBooksConnection
    return db.query(QuickBooksConnection).first()


def get_or_create_conn(db):
    from models import QuickBooksConnection
    conn = db.query(QuickBooksConnection).first()
    if conn is None:
        conn = QuickBooksConnection(environment="production", status=STATUS_DISCONNECTED, refresh_minutes=15)
        db.add(conn)
        db.flush()
    return conn


def is_configured(conn) -> bool:
    return bool(conn and conn.client_id and conn.client_secret)


def _token_fresh(conn, now: datetime) -> bool:
    exp = conn.access_token_expires_at
    return bool(conn.access_token and exp and exp > now + timedelta(seconds=TOKEN_REFRESH_MARGIN_SECONDS))


def ensure_access_token(db, conn) -> Tuple[bool, Optional[str]]:
    """Refresh the access token if it is missing / about to expire.

    Serialised across workers with a row lock: the refresh token rotates on
    every use, so two concurrent refreshes would burn one and make the loser
    look like a revoked connection.
    """
    from models import QuickBooksConnection
    now = _utcnow()
    if _token_fresh(conn, now):
        return True, None
    locked = (
        db.query(QuickBooksConnection)
        .filter(QuickBooksConnection.id == conn.id)
        .populate_existing()
        .with_for_update()
        .one()
    )
    try:
        if _token_fresh(locked, now):
            db.commit()
            return True, None
        if locked.status != STATUS_CONNECTED or not locked.refresh_token:
            db.commit()
            return False, locked.last_error or "QuickBooks is not connected"
        ok, err, data = refresh_access_token(locked)
        if ok:
            apply_token(locked, data)
            db.commit()
            print(f"[QUICKBOOKS] Access token refreshed (expires {locked.access_token_expires_at})")
            return True, None
        locked.last_error = err
        if err and err.startswith("invalid_grant"):
            locked.status = STATUS_NEEDS_RECONNECT
            print(f"[QUICKBOOKS] Refresh token rejected — reconnect required: {err}")
        else:
            print(f"[QUICKBOOKS] Token refresh failed: {err}")
        db.commit()
        return False, err
    except Exception:
        db.rollback()
        raise


def _upsert_accounts(db, rows: List[Dict[str, Any]], synced_at: datetime) -> None:
    stmt = sa_text(
        """
        INSERT INTO quickbooks_accounts
            (qbo_id, name, fully_qualified_name, account_type, account_sub_type,
             current_balance, current_balance_with_sub_accounts, sub_account,
             parent_qbo_id, currency, active, synced_at)
        VALUES
            (:qbo_id, :name, :fully_qualified_name, :account_type, :account_sub_type,
             :current_balance, :current_balance_with_sub_accounts, :sub_account,
             :parent_qbo_id, :currency, :active, :synced_at)
        ON CONFLICT (qbo_id) DO UPDATE SET
            name = EXCLUDED.name,
            fully_qualified_name = EXCLUDED.fully_qualified_name,
            account_type = EXCLUDED.account_type,
            account_sub_type = EXCLUDED.account_sub_type,
            current_balance = EXCLUDED.current_balance,
            current_balance_with_sub_accounts = EXCLUDED.current_balance_with_sub_accounts,
            sub_account = EXCLUDED.sub_account,
            parent_qbo_id = EXCLUDED.parent_qbo_id,
            currency = EXCLUDED.currency,
            active = EXCLUDED.active,
            synced_at = EXCLUDED.synced_at
        """
    )
    for r in rows:
        db.execute(stmt, {**r, "synced_at": synced_at})
    db.execute(
        sa_text("DELETE FROM quickbooks_accounts WHERE synced_at IS NULL OR synced_at < :synced_at"),
        {"synced_at": synced_at},
    )


def _refresh_cache(db, conn, now: datetime) -> Optional[str]:
    """Pull balances from QBO into the cache. Returns an error string on failure."""
    ok, err = ensure_access_token(db, conn)
    if not ok:
        return err
    ok, err, rows, unauthorized = fetch_accounts(conn)
    if unauthorized:
        # Token looked valid locally but QBO rejected it — force one refresh and retry.
        conn.access_token_expires_at = None
        db.commit()
        ok2, err2 = ensure_access_token(db, conn)
        if not ok2:
            return err2
        ok, err, rows, unauthorized = fetch_accounts(conn)
    if not ok:
        conn.last_error = err
        db.commit()
        print(f"[QUICKBOOKS] Balance sync failed: {err}")
        return err
    _upsert_accounts(db, rows, now)
    conn.last_synced_at = now
    conn.last_error = None
    db.commit()
    print(f"[QUICKBOOKS] Synced {len(rows)} account balance(s)")
    return None


def _account_dict(a) -> Dict[str, Any]:
    return {
        "qbo_id": a.qbo_id,
        "name": a.name,
        "fully_qualified_name": a.fully_qualified_name,
        "account_type": a.account_type,
        "account_sub_type": a.account_sub_type,
        "balance": float(a.current_balance or 0),
        "balance_with_sub_accounts": (float(a.current_balance_with_sub_accounts)
                                      if a.current_balance_with_sub_accounts is not None else None),
        "sub_account": bool(a.sub_account),
        "parent_qbo_id": a.parent_qbo_id,
        "currency": a.currency,
        "active": bool(a.active),
        "hidden": bool(a.hidden),
        "synced_at": a.synced_at,
    }


def list_accounts(db) -> List[Dict[str, Any]]:
    from models import QuickBooksAccount
    rows = (
        db.query(QuickBooksAccount)
        .order_by(QuickBooksAccount.account_type, QuickBooksAccount.fully_qualified_name, QuickBooksAccount.name)
        .all()
    )
    return [_account_dict(a) for a in rows]


def set_accounts_hidden(db, changes: Dict[str, bool]) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Apply hidden flags in one transaction. Returns (missing_ids, full account list)."""
    from models import QuickBooksAccount
    ids = list(changes.keys())
    rows = db.query(QuickBooksAccount).filter(QuickBooksAccount.qbo_id.in_(ids)).all()
    found = {r.qbo_id: r for r in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        return missing, []
    for qbo_id, hidden in changes.items():
        found[qbo_id].hidden = bool(hidden)
    db.commit()
    return [], list_accounts(db)


def _block_from_cache(db, conn, error: Optional[str]) -> Dict[str, Any]:
    accounts = list_accounts(db)
    visible = [a for a in accounts if not a["hidden"]]
    # Sum per-row CurrentBalance so a parent and its sub-accounts aren't double counted.
    cash = sum(a["balance"] for a in visible if a["account_type"] == "Bank")
    debt = sum(a["balance"] for a in visible if a["account_type"] == "Credit Card")
    err = error or conn.last_error
    stale = bool(err) or conn.status != STATUS_CONNECTED or conn.last_synced_at is None
    return {
        "configured": True,
        "status": conn.status,
        "company_name": conn.company_name,
        "environment": conn.environment,
        "realm_id": conn.realm_id,
        "refresh_minutes": int(conn.refresh_minutes or 15),
        "synced_at": conn.last_synced_at.isoformat() if conn.last_synced_at else None,
        "stale": stale,
        "error": err,
        "accounts": accounts,
        "totals": {
            "cash": round(cash, 2),
            "credit_card_debt": round(debt, 2),
            "net": round(cash - debt, 2),
            "hidden_count": len(accounts) - len(visible),
        },
    }


def sync_balances(db, force: bool = False, max_age_minutes: Optional[float] = None) -> Dict[str, Any]:
    conn = get_conn(db)
    if not is_configured(conn):
        return {"configured": False, "status": STATUS_DISCONNECTED}
    if conn.status == STATUS_DISCONNECTED or not conn.realm_id:
        return {"configured": False, "status": STATUS_DISCONNECTED}
    now = _utcnow()
    max_age = float(conn.refresh_minutes or 15) if max_age_minutes is None else float(max_age_minutes)
    due = force or conn.last_synced_at is None or (now - conn.last_synced_at) > timedelta(minutes=max_age)
    error = None
    if due and conn.status == STATUS_CONNECTED:
        error = _refresh_cache(db, conn, now)
    return _block_from_cache(db, conn, error)


def get_balances_block(max_age_minutes: Optional[float] = None, force: bool = False) -> Dict[str, Any]:
    """Thread entry point for the Business Overview widget. Never raises."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        return sync_balances(db, force=force, max_age_minutes=max_age_minutes)
    except Exception as e:
        db.rollback()
        print(f"[QUICKBOOKS] get_balances_block error: {e}")
        try:
            conn = get_conn(db)
            if is_configured(conn) and conn.status != STATUS_DISCONNECTED and conn.realm_id:
                return _block_from_cache(db, conn, str(e))
            return {"configured": False, "status": STATUS_DISCONNECTED}
        except Exception as e2:
            return {"configured": True, "status": STATUS_CONNECTED, "error": f"{e} / {e2}", "stale": True,
                    "accounts": [], "totals": {"cash": 0, "credit_card_debt": 0, "net": 0, "hidden_count": 0}}
    finally:
        db.close()


def complete_connection(db, conn, parsed: Dict[str, Optional[str]]) -> Tuple[bool, Optional[str]]:
    now = _utcnow()
    if not conn.oauth_state:
        return False, "No pending connection — click Connect to QuickBooks first"
    if not parsed.get("state"):
        return False, "The pasted URL has no state parameter — paste the full URL from the address bar"
    if parsed["state"] != conn.oauth_state:
        return False, "State mismatch — click Connect to QuickBooks again and paste the newest URL"
    if conn.oauth_state_created_at and (now - conn.oauth_state_created_at) > timedelta(seconds=STATE_TTL_SECONDS):
        return False, "Connect link expired (10 minutes) — click Connect to QuickBooks again"
    if not parsed.get("realm_id"):
        return False, "The pasted URL has no realmId — paste the full URL from the address bar"
    ok, err, data = exchange_code(conn, parsed["code"] or "")
    if not ok:
        if err and err.startswith("invalid_grant"):
            err = "Authorization code already used or expired — click Connect to QuickBooks again"
        elif err and "redirect" in err.lower():
            err = f"Redirect URI mismatch — the Redirect URI changed after Connect was started, or it differs from the Intuit portal ({err})"
        conn.last_error = err
        db.commit()
        return False, err
    apply_token(conn, data)
    conn.realm_id = parsed["realm_id"]
    conn.status = STATUS_CONNECTED
    conn.connected_at = now
    conn.oauth_state = None
    conn.oauth_state_created_at = None
    conn.last_error = None
    conn.company_name = None
    db.commit()
    conn.company_name = fetch_company_name(conn)
    db.commit()
    print(f"[QUICKBOOKS] Connected to realm {conn.realm_id} ({conn.company_name or 'name unknown'})")
    _refresh_cache(db, conn, _utcnow())
    return True, None


def disconnect(db, conn, revoke_remote: bool = True) -> None:
    if revoke_remote and conn.refresh_token:
        ok, err = revoke(conn)
        print(f"[QUICKBOOKS] Revoke {'ok' if ok else 'failed: ' + str(err)}")
    conn.access_token = None
    conn.access_token_expires_at = None
    conn.refresh_token = None
    conn.refresh_token_expires_at = None
    conn.realm_id = None
    conn.company_name = None
    conn.oauth_state = None
    conn.oauth_state_created_at = None
    conn.connected_at = None
    conn.last_synced_at = None
    conn.last_error = None
    conn.status = STATUS_DISCONNECTED
    db.execute(sa_text("DELETE FROM quickbooks_accounts"))
    db.commit()


def _keepalive_pass() -> None:
    """Rotate the refresh token when the dashboard hasn't been viewed for days."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        conn = get_conn(db)
        if not conn or conn.status != STATUS_CONNECTED or not conn.refresh_token:
            return
        last = conn.access_token_expires_at
        if last is None or last < _utcnow() - KEEPALIVE_IF_OLDER_THAN:
            ok, err = ensure_access_token(db, conn)
            print(f"[QUICKBOOKS] Keep-alive refresh {'ok' if ok else 'failed: ' + str(err)}")
    except Exception as e:
        db.rollback()
        print(f"[QUICKBOOKS] Keep-alive error: {e}")
    finally:
        db.close()


async def keepalive_loop() -> None:
    await asyncio.sleep(random.uniform(0, 60))
    while True:
        try:
            await asyncio.to_thread(_keepalive_pass)
        except Exception as e:
            print(f"[QUICKBOOKS] Keep-alive pass failed: {e}")
        await asyncio.sleep(KEEPALIVE_LOOP_SECONDS)
