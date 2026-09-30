"""
Pure Lost Customers rules that need no database, network or FastAPI app, so
they can be unit-tested without importing main.
"""
from typing import Any, Dict, List


def merge_reregistered(moved: List[Dict[str, Any]],
                       customers: List[Dict[str, Any]]) -> int:
    """
    Date each same-store re-registration from the person's first purchase.

    `moved` holds old accounts the moved check proved were replaced by a new
    account at the same shop (`moved_to_customer_id`). Every customer in
    `customers` that is such a new account gets `merged_first_local` = the
    earliest known first order across it and its old account(s), which is what
    the "new" series and the arrivals cohort bucket by. `first_order_local` is
    left alone so the table still shows each account's own date.

    Returns how many customers were stamped.
    """
    earliest_old: Dict[Any, Any] = {}
    for c in moved:
        dest = c.get("moved_to_customer_id")
        if not (c.get("moved_same_store") and dest):
            continue
        dates = [d for d in (earliest_old.get(dest), c.get("first_order_local")) if d]
        earliest_old[dest] = min(dates) if dates else None

    stamped = 0
    for c in customers:
        cid = c.get("customer_id")
        if cid not in earliest_old:
            continue
        dates = [d for d in (c.get("first_order_local"), earliest_old[cid]) if d]
        c["merged_first_local"] = min(dates) if dates else None
        stamped += 1
    return stamped
