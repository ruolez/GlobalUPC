"""Regression snapshot: call read-only endpoints on two backends and diff them.

    python3 backend/tests/smoke/snapshot_endpoints.py \
        --old http://localhost:8012 --new http://localhost:8011 --out /tmp/snap

Every request goes to OLD then NEW back to back, so live MSSQL / Shopify data
has the least time to drift between the two answers. SSE streams are compared
by their event names and their final payload. Lists whose items only differ in
order are reported separately ("order-only"): store fan-outs complete in
arbitrary order on both versions.

Standard library only, so it runs from the host without a virtualenv.
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

PERIOD = ("2026-10-01", "2026-10-31")
SHORT = ("2026-10-20", "2026-10-21")
VOLATILE = re.compile(
    r"(^|_)(timings?|elapsed|duration|ms|seconds|generated_at|server_time|now|"
    r"expires_at|token|last_tick|uptime|request_id)$"
)


def call(base, method, path, body=None, headers=None, timeout=900):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status, ctype = e.code, e.headers.get("Content-Type", "")
    except Exception as e:  # network error / timeout
        return {"status": "EXC", "error": f"{type(e).__name__}: {e}", "secs": round(time.time() - started, 1)}
    out = {"status": status, "secs": round(time.time() - started, 1)}
    if "text/event-stream" in ctype:
        out["sse"] = parse_sse(raw)
    else:
        try:
            out["json"] = json.loads(raw)
        except ValueError:
            out["text"] = raw[:500]
    return out


def parse_sse(raw):
    events, final = [], {}
    for block in raw.split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if not data and name == "message":
            continue
        if name in ("heartbeat", "ping", "progress", "status", "log"):
            continue
        try:
            payload = json.loads("\n".join(data)) if data else None
        except ValueError:
            payload = "\n".join(data)
        events.append(name)
        final[name] = payload  # last payload per event name
    return {"events": sorted(set(events)), "last": final}


def strip(obj):
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in obj.items() if not VOLATILE.search(k)}
    if isinstance(obj, list):
        return [strip(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 4)
    return obj


def diff(a, b, path="$", out=None):
    out = [] if out is None else out
    if type(a) is not type(b):
        out.append((path, "type", repr(a)[:120], repr(b)[:120]))
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((f"{path}.{k}", "added", "", repr(b[k])[:120]))
            elif k not in b:
                out.append((f"{path}.{k}", "removed", repr(a[k])[:120], ""))
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((path, "len", len(a), len(b)))
        elif a != b:
            key = lambda v: json.dumps(v, sort_keys=True, default=str)
            if sorted(a, key=key) == sorted(b, key=key):
                out.append((path, "order-only", "", ""))
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append((path, "value", repr(a)[:120], repr(b)[:120]))
    return out


def build_cases(base, bov_headers):
    """Discover sample ids from the OLD backend so both sides get identical input."""
    get = lambda p, h=None: call(base, "GET", p, headers=h).get("json")
    stores = get("/api/stores") or []
    stores = stores if isinstance(stores, list) else stores.get("stores", [])
    mssql = [s["id"] for s in stores if s.get("store_type") == "mssql" and s.get("is_active", True)]
    shopify = [s["id"] for s in stores if s.get("store_type") == "shopify" and s.get("is_active", True)]
    sync = get("/api/shopify-sync/status") or {}
    synced = [s.get("store_id") for s in (sync.get("stores") or []) if s.get("last_completed_at") or s.get("completed_at")]
    shop = synced[0] if synced else (shopify[-1] if shopify else None)

    rng = f"date_from={PERIOD[0]}&date_to={PERIOD[1]}"
    products = get(f"/api/business-overview/products?{rng}", bov_headers) or {}
    rows = products.get("rows") or products.get("products") or []
    upc = next((r.get("upc") for r in rows if r.get("upc")), None) or "0"
    prod_row = next((r for r in rows if r.get("upc") and r.get("store_id")), None)
    inv = get(f"/api/business-overview/invoices/period?{rng}", bov_headers) or {}
    inv_rows = inv.get("invoices") or inv.get("rows") or []
    pos = get(f"/api/business-overview/purchases/purchased?{rng}", bov_headers) or {}
    po_rows = pos.get("purchase_orders") or pos.get("rows") or []
    qip = call(base, "POST", "/api/quotations/in-progress", {}).get("json") or {}
    qn = next((q.get("quotation_number") for q in qip.get("quotations", []) if q.get("quotation_number")), None)
    itu = get(f"/api/inventory-time/users?{rng}") or {}
    users = itu.get("users") or []
    chk = get(f"/api/checked-orders/users?{rng}") or {}
    checkers = chk.get("users") or chk.get("checkers") or []
    sales_cfg = get("/api/sales/config") or {}

    G, P = "GET", "POST"
    cases = [
        (G, "/api/stores", None, None),
        (G, "/api/settings", None, None),
        (G, "/api/dashboard/stats", None, None),
        (G, "/api/item-tracker/config", None, None),
        (G, "/api/item-tracker/exclusions", None, None),
        (G, "/api/sales/config", None, None),
        (G, "/api/sales/exclusions", None, None),
        (G, "/api/sales/business-names", None, None),
        (G, "/api/exclusions", None, None),
        (G, "/api/history/updates", None, None),
        (G, "/api/price-updates/history", None, None),
        (G, "/api/store-mirrors", None, None),
        (G, "/api/shopify-sync/status", None, None),
        (G, "/api/shopify/fulfillment-status", None, None),
        (G, "/api/order-sync/config", None, None),
        (G, "/api/order-sync/auto/config", None, None),
        (G, "/api/order-sync/auto/runs", None, None),
        (G, "/api/order-sync/auto/status", None, None),
        (G, "/api/order-sync/created-products", None, None),
        (G, "/api/order-sync/cancelled-duplicates", None, None),
        (G, "/api/quickbooks/connection", None, None),
        (G, "/api/quickbooks/accounts", None, None),
        (G, f"/api/inventory-time/users?{rng}", None, None),
        (G, f"/api/checked-orders/users?{rng}", None, None),
        (G, f"/api/item-tracker/summary?upc={upc}&from={PERIOD[0]}&to={PERIOD[1]}", None, None),
        (G, f"/api/order-sync/report?date_from={SHORT[0]}&date_to={SHORT[1]}", None, None),
        (G, f"/api/order-sync/report/stream?date_from={SHORT[0]}&date_to={SHORT[1]}", None, None),
        (P, "/api/upc/search", {"upc": upc}, None),
        (P, "/api/upc/search/stream", {"upc": upc}, None),
        (P, "/api/item-tracker/search/stream", {"upc": upc, "date_from": PERIOD[0], "date_to": PERIOD[1]}, None),
        (P, "/api/item-tracker/description/autocomplete", {"query": "candy"}, None),
        (P, f"/api/price-updates/description/autocomplete?store_id={mssql[0] if mssql else 0}", {"query": "candy"}, None),
        (P, "/api/price-updates/fetch-prices/stream", {"upc": upc, "store_ids": mssql + shopify}, None),
        (P, "/api/quotations/in-progress", {}, None),
        (P, "/api/quotations/in-progress", {"scan_filter": "in", "sort_by": "quotation_number", "sort_order": "asc"}, None),
        (P, "/api/quotations/in-progress/search-products", {"search": "a"}, None),
        (P, "/api/sales/report/stream", {
            "mssql_store_ids": sales_cfg.get("mssql_store_ids") or sales_cfg.get("sales_store_ids") or mssql,
            "shopify_store_ids": sales_cfg.get("shopify_store_ids") or [],
            "date_from": PERIOD[0], "date_to": PERIOD[1]}, None),
    ]
    if qn:
        cases += [
            (G, f"/api/quotations/in-progress/{qn}/products", None, None),
            (G, f"/api/quotations/in-progress/{qn}/products?cost_mode=sale", None, None),
        ]
    if users:
        name = users[0].get("username") if isinstance(users[0], dict) else users[0]
        cases.append((P, "/api/inventory-time", {"username": name, "date_from": PERIOD[0], "date_to": PERIOD[1]}, None))
    if checkers:
        cid = checkers[0].get("id") or checkers[0].get("checker_id")
        cases.append((P, "/api/checked-orders", {"checker_id": cid, "date_from": PERIOD[0], "date_to": PERIOD[1]}, None))
    if shop:
        cases += [
            (P, "/api/shopify-sales/stream", {"store_ids": [shop], "start_date": PERIOD[0], "end_date": PERIOD[1]}, None),
            (P, "/api/shopify-analytics/lost-customers/stream", {"store_ids": [shop], "history_from": "2025-01-01"}, None),
            (P, "/api/shopify-analytics/new-customers-by-month/stream", {"store_ids": [shop], "start_date": "2026-07-01", "end_date": PERIOD[1]}, None),
            (P, "/api/shopify-analytics/first-customer-returns/stream", {"store_id": shop, "start_date": "2026-07-01", "end_date": PERIOD[1]}, None),
        ]
    bov = [
        "/config", "/config/options", "/alerts", "/bank-balances",
        "/purchases/exclusions", "/shopify/exclusions",
        f"/quotations?{rng}", f"/invoices/open?{rng}", f"/invoices/shipped?{rng}",
        f"/invoices/period?{rng}", f"/purchases/incoming?{rng}", f"/purchases/purchased?{rng}",
        f"/purchases/received?{rng}", f"/sales/breakdown?{rng}", f"/shopify/orders?{rng}",
        f"/shopify/orders/list?{rng}", f"/shopify/missing-cost?{rng}",
    ]
    for mode in ("sale", "current", "s2s"):
        bov += [
            f"/summary?{rng}&cost_mode={mode}", f"/sales/trend?{rng}&cost_mode={mode}",
            f"/products?{rng}&cost_mode={mode}", f"/month-end?{rng}&cost_mode={mode}",
        ]
    bov.append(f"/month-end/stream?{rng}")
    if inv_rows:
        iid = inv_rows[0].get("invoice_id") or inv_rows[0].get("id")
        sid = inv_rows[0].get("store_id")
        bov.append(f"/invoices/{iid}?store_id={sid}")
    if po_rows:
        pid = po_rows[0].get("po_id") or po_rows[0].get("id")
        bov.append(f"/purchases/{pid}?store_id={po_rows[0].get('store_id') or pos.get('store_id')}")
    if prod_row:
        bov.append(f"/products/lines?store_id={prod_row['store_id']}&upc={prod_row['upc']}&{rng}")
    cases += [(G, "/api/business-overview" + p, None, bov_headers) for p in bov]
    return cases


def unlock(base):
    r = call(base, "POST", "/api/business-overview/unlock", {"password": os.environ.get("BOV_PASSWORD", "admin1972")})
    tok = (r.get("json") or {}).get("token")
    return {"X-BOV-Token": tok} if tok else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="regex on path")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    old_h, new_h = unlock(args.old), unlock(args.new)
    cases = build_cases(args.old, old_h)
    if args.only:
        cases = [c for c in cases if re.search(args.only, c[1])]
    report, failures = [], 0
    for i, (method, path, body, hdrs) in enumerate(cases):
        a = call(args.old, method, path, body, old_h if hdrs else None)
        b = call(args.new, method, path, body, new_h if hdrs else None)
        d = diff(strip({k: v for k, v in a.items() if k != "secs"}),
                 strip({k: v for k, v in b.items() if k != "secs"}))
        real = [x for x in d if x[1] != "order-only"]
        tag = "OK  " if not real else "DIFF"
        failures += bool(real)
        line = f"{tag} {a.get('status')}/{b.get('status')} {a.get('secs'):>6}s/{b.get('secs'):>6}s {method} {path}"
        print(line, flush=True)
        report.append({"case": [method, path, body], "old": a, "new": b, "diff": d})
        for x in real[:15]:
            print("      ", *x)
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"\n{len(cases)} cases, {failures} with differences -> {args.out}/report.json")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
