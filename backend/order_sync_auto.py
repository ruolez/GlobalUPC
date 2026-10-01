"""
Order Sync automation — pure rules (no database, no network).

One daily job compares a day's BackOffice invoices with the Shopify orders —
the day before the run, or the run's own day (`check_day`) — and runs the
switched-on steps. This module decides WHEN a run is due
and WHAT it may touch; main.py does the I/O. The selection rules deliberately
mirror what the Order Sync page pre-ticks, so the automation never does
anything a person would have had to tick by hand.
"""
from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from order_sync_helper import FIX_STEPS

CANCEL_STEPS = ("cancel_online_store", "cancel_duplicates")
CHECK_STEPS = ("missing_check",)
STEP_KEYS = FIX_STEPS + CANCEL_STEPS + CHECK_STEPS

DEFAULT_RUN_TIME = "06:00"
# Which day a scheduled run checks: the day before it, or its own day.
CHECK_DAYS = ("previous", "same")
DEFAULT_CHECK_DAY = "previous"
DEFAULT_DAYS = [0, 1, 2, 3, 4, 5, 6]          # Python weekday(): 0 = Monday
DEFAULT_TIMEZONE = "America/Chicago"

# A run that starts this long after its slot is labelled a catch-up.
CATCH_UP_AFTER = timedelta(minutes=5)
# Days looked back for slots that never ran (server down all day).
MISSED_LOOKBACK_DAYS = 14


def normalize_steps(raw: Optional[Dict[str, Any]]) -> Dict[str, bool]:
    raw = raw or {}
    return {k: bool(raw.get(k)) for k in STEP_KEYS}


def any_fix_step(steps: Dict[str, bool]) -> bool:
    return any(steps.get(k) for k in FIX_STEPS)


def parse_run_time(value: str) -> Tuple[int, int]:
    """"HH:MM" (24 h) → (hour, minute); ValueError otherwise."""
    parts = (value or "").strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError("run_time must be HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("run_time must be HH:MM")
    return hour, minute


def normalize_days(days: Iterable[Any]) -> List[int]:
    out = sorted({int(d) for d in days or []})
    if any(d < 0 or d > 6 for d in out):
        raise ValueError("days must be weekday numbers 0 (Mon) – 6 (Sun)")
    return out


def slot_at(day: date, run_time: str, tz: str) -> datetime:
    hour, minute = parse_run_time(run_time)
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(tz))


def _slot_counts(day: date, cfg: Dict[str, Any]) -> bool:
    """Is `day` a scheduled day whose slot falls after the schedule took effect?"""
    if day.weekday() not in (cfg.get("days") or []):
        return False
    effective_from = cfg.get("effective_from")
    return not effective_from or slot_at(day, cfg["run_time"], cfg["timezone"]) >= effective_from


def due_slot(now: datetime, cfg: Dict[str, Any], recorded: Set[date]) -> Optional[date]:
    """Today's slot when it is due and has no run yet, else None. `now` is
    aware; `recorded` holds the slot dates that already have a run row. The
    same rule serves the on-time run and the same-day catch-up after a
    restart — a slot is only ever runnable on its own day."""
    if not cfg.get("enabled"):
        return None
    today = now.astimezone(ZoneInfo(cfg["timezone"])).date()
    if today in recorded or not _slot_counts(today, cfg):
        return None
    return today if now >= slot_at(today, cfg["run_time"], cfg["timezone"]) else None


def missed_slots(now: datetime, cfg: Dict[str, Any], recorded: Set[date]) -> List[date]:
    """Earlier scheduled days that never got a run (the server was down all
    day), oldest first, so the log shows the gap."""
    if not cfg.get("enabled"):
        return []
    today = now.astimezone(ZoneInfo(cfg["timezone"])).date()
    days = [today - timedelta(days=n) for n in range(MISSED_LOOKBACK_DAYS, 0, -1)]
    return [d for d in days if d not in recorded and _slot_counts(d, cfg)]


def next_run_at(now: datetime, cfg: Dict[str, Any], recorded: Set[date]) -> Optional[datetime]:
    """When the next run will start (a due slot counts as "now")."""
    if not cfg.get("enabled") or not cfg.get("days"):
        return None
    today = now.astimezone(ZoneInfo(cfg["timezone"])).date()
    for n in range(0, 8):
        day = today + timedelta(days=n)
        if day in recorded or not _slot_counts(day, cfg):
            continue
        slot = slot_at(day, cfg["run_time"], cfg["timezone"])
        if n == 0 and now >= slot:
            return now
        if slot > now:
            return slot
    return None


def slot_trigger(now: datetime, slot_day: date, cfg: Dict[str, Any]) -> str:
    slot = slot_at(slot_day, cfg["run_time"], cfg["timezone"])
    return "catch_up" if now - slot > CATCH_UP_AFTER else "scheduled"


def scan_date(day: date, check_day: str = DEFAULT_CHECK_DAY) -> date:
    """The day a run on `day` reconciles: its own day for "same", otherwise
    the one before it."""
    return day if check_day == "same" else day - timedelta(days=1)


# ---------------------------------------------------------------------------
# What a run may touch — twins of the page's pre-ticked selections
# ---------------------------------------------------------------------------

LINE_ISSUES = ("product", "qty", "price")


def fixable(row: Dict[str, Any]) -> Tuple[bool, str]:
    """Server twin of osyncFixable (app.js): (can Fix in Shopify act, why not)."""
    if not row.get("sh_order_id") or not row.get("bo_invoice_id"):
        return False, "Needs a matched Shopify order and invoice"
    if row.get("combined"):
        return False, "Combined shipments need manual review"
    line_issues = any(k in LINE_ISSUES for k in row.get("issue_kinds") or [])
    tracking_fix = bool(row.get("sh_no_tracking")) and bool(row.get("bo_tracking"))
    unpaid = (row.get("sh_outstanding") or 0) > 0.004
    if not (line_issues or tracking_fix or unpaid):
        return False, ("Nothing to fix" if row.get("status") == "matched_ok"
                       else "Only the order total differs — no line-level change to make")
    return True, ""


def _row_ref(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"sh_order_id": row.get("sh_order_id"), "sh_name": row.get("sh_name"),
            "bo_invoice_id": row.get("bo_invoice_id"), "bo_invoice_number": row.get("bo_invoice_number"),
            "sh_total": row.get("sh_total"), "bo_total": row.get("bo_total"),
            "issue_kinds": row.get("issue_kinds") or []}


def select_fix_targets(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(fix targets, rows for review). An ambiguous match could be the wrong
    pairing and a combined shipment spans several orders — both are left to a
    person, exactly as the page leaves them unticked."""
    targets: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []
    for r in rows:
        if r.get("status") not in ("matched_ok", "matched_diffs"):
            continue
        if r.get("combined") and any(k in LINE_ISSUES for k in r.get("issue_kinds") or []):
            review.append({**_row_ref(r), "category": "combined",
                           "reason": "Combined shipment with line differences — fix by hand"})
            continue
        ok, _why = fixable(r)
        if not ok:
            continue
        if r.get("ambiguous"):
            review.append({**_row_ref(r), "category": "ambiguous_match",
                           "reason": "Ambiguous match — verify the pairing, then fix by hand"})
            continue
        targets.append({
            "sh_order_id": r["sh_order_id"], "bo_invoice_id": r["bo_invoice_id"],
            "bo_invoice_number": r.get("bo_invoice_number"),
            "match_method": r.get("match_method"), "ambiguous": False,
        })
    return targets, review


def select_dup_targets(rows: List[Dict[str, Any]]) -> List[str]:
    """Twin of osyncDupTargets: Shopify-only rows missing tracking."""
    return [r["sh_order_id"] for r in rows
            if r.get("status") == "shopify_unmatched" and r.get("sh_no_tracking") and r.get("sh_order_id")]


def invoice_by_order(rows: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Shopify order id → the invoice the report paired it with."""
    out: Dict[str, Optional[str]] = {}
    for r in rows:
        if r.get("status") not in ("matched_ok", "matched_diffs"):
            continue
        for o in r.get("sh_orders") or []:
            if o.get("id"):
                out[o["id"]] = r.get("bo_invoice_number")
    return out


def backoffice_only_orders(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The Missing-in-Shopify request body, as osyncMissingOpen builds it."""
    return [{
        "invoice_number": r.get("bo_invoice_number") or "", "date": r.get("bo_date") or "",
        "customer": r.get("bo_customer") or "",
        "lines": [{"barcode": d.get("barcode") or "", "sku": d.get("sku") or "",
                   "description": d.get("description") or "", "qty": d.get("bo_qty") or 0}
                  for d in r.get("line_diffs") or []],
    } for r in rows if r.get("status") == "backoffice_unmatched"]


# ---------------------------------------------------------------------------
# Report math
# ---------------------------------------------------------------------------

SUMMARY_KEYS = ("matched_ok", "matched_diffs", "shopify_unmatched", "backoffice_unmatched",
                "shopify_no_tracking", "ambiguous", "shopify_total", "backoffice_total")


def summary_snapshot(summary: Optional[Dict[str, Any]], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The counts a run report shows for one Compare, plus how many rows each
    tool could act on at that moment."""
    summary = summary or {}
    snap = {k: int(summary.get(k) or 0) for k in SUMMARY_KEYS}
    snap["issue_counts"] = dict(summary.get("issue_counts") or {})
    snap["fixable"] = sum(1 for r in rows if fixable(r)[0])
    snap["missing_tracking_shopify_only"] = len(select_dup_targets(rows))
    return snap


def summary_delta(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not before or not after:
        return {}
    keys = SUMMARY_KEYS + ("fixable", "missing_tracking_shopify_only")
    return {k: int(after.get(k) or 0) - int(before.get(k) or 0) for k in keys}


FIX_DONE = ("applied",)
FIX_FAILED = ("partial", "failed", "error")
CANCEL_DONE = ("cancelled",)


def report_counts(report: Dict[str, Any]) -> Dict[str, int]:
    """Headline numbers for the run list and the nav badge."""
    fixes = report.get("fixes") or []
    cancels = report.get("cancels") or []
    stages = (report.get("stages") or {}).values()
    return {
        "fixed": sum(1 for f in fixes if f.get("status") in FIX_DONE),
        "would_fix": sum(1 for f in fixes if f.get("status") == "would_fix"),
        "fix_failed": sum(1 for f in fixes if f.get("status") in FIX_FAILED),
        "cancelled": sum(1 for c in cancels if c.get("status") in CANCEL_DONE),
        "would_cancel": sum(1 for c in cancels if c.get("status") == "would_cancel"),
        "cancel_failed": sum(1 for c in cancels if c.get("status") == "failed"),
        "created_products": len(report.get("created_products") or []),
        "review": len(report.get("review") or []),
        "missing_products": len(report.get("missing_products") or []),
        "stage_errors": sum(1 for s in stages if s.get("status") == "failed"),
    }


def final_status(counts: Dict[str, int], stopped: bool) -> str:
    if stopped:
        return "stopped"
    if counts.get("stage_errors") or counts.get("fix_failed") or counts.get("cancel_failed"):
        return "partial"
    return "succeeded"
