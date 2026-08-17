"""
Local-data twin of the Shopify Sales report fetch.

``fetch_fulfilled_orders_local`` returns exactly what
``shopify_helper.fetch_fulfilled_orders`` returns — the same
``(success, error, line_items)`` tuple with the same per-line-item keys — so the
``/api/shopify-sales/stream`` endpoint runs its exclusion / shipping /
aggregation / cost / margin pipeline unchanged. Parity with the live path is
the design goal, correctness improvements are not: the two modes must diff
clean on a freshly synced store.

Rules mirrored from the live path (shopify_helper.fetch_fulfilled_orders):

- Order prefilter ``fulfillment_status:shipped`` becomes
  ``fulfillment_status = 'FULFILLED'``. No updated_at bound on either side:
  Shopify bumps an order's updated_at on delivery/tracking events, so an
  upper bound would drop most orders of any window not ending today.
- Real filter: some fulfillment with ``status = 'SUCCESS'`` whose ``createdAt``
  UTC date slice (``createdAt[:10]``, NOT the shop's local day) is in range.
- ``quantity`` = currentQuantity when the sync captured it (0 = fully
  refunded/removed, dropped), else the ordered quantity; ``unit_price`` =
  discounted unit price, falling back to the original unit price.

Known gaps (accepted):

- ``variant_title`` is the order-time ``lineItem.variantTitle`` snapshot; live
  prefers the variant's current title.
- ``unit_price`` is derived as ``discounted_total / quantity`` and may drift
  by a cent from Shopify's own ``discountedUnitPriceSet`` on discounted
  multi-unit lines.
- Rows synced before migration 018 have NULL ``current_quantity`` /
  ``total_shipping`` and no per-fulfillment ``status``: the fallbacks are the
  ordered quantity, 0 shipping, and a ``displayStatus``-based approximation.
  A Full resync removes all three.
- ``today_price`` is always None here; the endpoint stamps it from a small
  live variant-price lookup.
"""

import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from database import engine


# created_at pruning is not part of the live semantics: a fulfillment cannot be
# created before its order, so any order with an in-range fulfillment was
# created before end + 2 days. It lets idx_shoporder_store_created cut the scan
# instead of walking every order the store ever had. If this is ever slow on a
# very large store, a GIN index on fulfillments is the escalation path.
_FULFILLED_LINES_SQL = """
SELECT o.name AS order_name,
       o.currency,
       COALESCE(o.total_shipping, 0) AS shipping_amount,
       li.title,
       li.variant_title,
       li.barcode,
       li.sku,
       li.product_title,
       li.variant_shopify_id,
       li.quantity,
       li.current_quantity,
       li.original_unit_price,
       li.discounted_total
FROM shopify_orders o
JOIN shopify_order_line_items li
  ON li.store_id = o.store_id AND li.order_shopify_id = o.shopify_id
WHERE o.store_id = :sid
  AND o.fulfillment_status = 'FULFILLED'
  AND o.created_at < ((CAST(:end AS date) + 2)::timestamp AT TIME ZONE 'UTC')
  AND EXISTS (
      SELECT 1
      FROM jsonb_array_elements(coalesce(o.fulfillments, '[]'::jsonb)) f
      WHERE (f->>'status' = 'SUCCESS'
             OR (f->>'status' IS NULL
                 AND coalesce(f->>'displayStatus', '') NOT IN ('CANCELED', 'FAILURE')))
        AND substr(f->>'createdAt', 1, 10) BETWEEN :start AND :end
  )
ORDER BY li.id
"""


def _money_str(value: Any) -> str:
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def _fetch_fulfilled_orders_local_sync(
    store_id: int, start_date: str, end_date: str
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(_FULFILLED_LINES_SQL),
                {"sid": store_id, "start": start_date, "end": end_date},
            ).mappings().all()
    except Exception as e:
        return False, f"Local data error: {e}", []

    line_items: List[Dict[str, Any]] = []
    for r in rows:
        ordered_qty = r["quantity"] or 0
        quantity = r["current_quantity"] if r["current_quantity"] is not None else ordered_qty
        if quantity <= 0:
            continue

        # discountedTotalSet covers the ORIGINAL quantity, so divide by that,
        # not by the post-refund quantity.
        if r["discounted_total"] is not None and ordered_qty > 0:
            unit_price = f"{(Decimal(r['discounted_total']) / ordered_qty):.2f}"
        else:
            unit_price = _money_str(r["original_unit_price"])

        line_items.append({
            "order_name": r["order_name"] or "",
            "product_title": r["product_title"] or r["title"] or "",
            "variant_title": r["variant_title"] or "Default Title",
            "barcode": r["barcode"] or "",
            "sku": r["sku"] or "",
            "quantity": quantity,
            "unit_price": unit_price,
            "today_price": None,
            "currency": r["currency"] or "USD",
            "shipping_amount": _money_str(r["shipping_amount"]),
            "variant_shopify_id": r["variant_shopify_id"],
        })

    return True, None, line_items


async def fetch_fulfilled_orders_local(
    store_id: int, start_date: str, end_date: str
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    return await asyncio.to_thread(
        _fetch_fulfilled_orders_local_sync, store_id, start_date, end_date
    )
