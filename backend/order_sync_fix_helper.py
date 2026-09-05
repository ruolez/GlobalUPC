"""
Order Sync — "Fix in Shopify": apply the plan produced by
order_sync_helper.plan_order_fix to a live Shopify order.

Every order the report lists is FULFILLED, and Shopify's order-edit API only
touches unfulfilled line items, so the executor combines three APIs:

  refund   refundCreate with transactions: [] — a $0, records-only refund of
           N units (restockType NO_RESTOCK); currentQuantity drops.
  add      orderEditBegin → orderEditAddVariant (allowDuplicates) → bring the
           line to the invoice price (orderEditAddLineItemDiscount when the
           invoice price is below the variant price; when it is above, the
           variant price is raised for the duration of the edit and restored
           in a finally block) → verify the calculated unit price BEFORE
           committing → orderEditCommit → fulfillmentCreate on the new OPEN
           fulfillment order (so the order returns to FULFILLED) →
           orderMarkAsPaid for the created balance.
  tracking fulfillmentTrackingInfoUpdate on fulfillments lacking a number.

The customer is never notified. Steps run refund → edit → fulfill → mark paid
→ tracking; the first failure stops the chain, and the caller re-fetches the
order so the reported row (and any later re-run) reflects what actually
happened — a re-run plans only what is still different.
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

import order_sync_helper as osync
from shopify_helper import (
    ShopifyFetchError,
    _money,
    _shopify_graphql,
    fetch_order_for_sync,
    find_variants_by_barcode,
)

REQUIRED_SCOPES = [
    "write_order_edits",
    "write_orders",
    "write_merchant_managed_fulfillment_orders",
    "write_products",
]

# A calculated unit price this far from the invoice price is a failed
# discount, and the edit is abandoned uncommitted.
_PRICE_TOL = 0.011


@dataclass
class ShopifyCtx:
    session: aiohttp.ClientSession
    shop_domain: str
    admin_api_key: str
    api_version: str
    currency: str = "USD"


class FixStepError(Exception):
    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step
        self.message = message


async def _gql(ctx: ShopifyCtx, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    data, _warnings = await _shopify_graphql(
        ctx.session, ctx.shop_domain, ctx.admin_api_key, ctx.api_version,
        query, variables, op_name="order_fix",
    )
    return data or {}


def _payload(data: Dict[str, Any], field: str, step: str) -> Dict[str, Any]:
    """Unwrap a mutation payload and turn its userErrors into a FixStepError."""
    payload = data.get(field)
    if payload is None:
        raise FixStepError(step, f"{field}: empty response")
    errors = payload.get("userErrors") or []
    if errors:
        msgs = "; ".join(
            (("/".join(e.get("field") or []) + ": ") if e.get("field") else "") + (e.get("message") or "")
            for e in errors
        )
        raise FixStepError(step, msgs)
    return payload


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

async def check_write_scopes(ctx: ShopifyCtx) -> Tuple[List[str], Optional[str]]:
    """(missing scopes, warning). Legacy tokens may not expose the
    installation — then nothing is reported missing, only a warning."""
    query = """
    query orderFixScopes {
      currentAppInstallation { accessScopes { handle } }
      shop { currencyCode }
    }
    """
    try:
        data = await _gql(ctx, query, {})
    except ShopifyFetchError as e:
        return [], f"Could not verify API scopes: {e}"
    shop = data.get("shop") or {}
    if shop.get("currencyCode"):
        ctx.currency = shop["currencyCode"]
    scopes = {s.get("handle") for s in ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])}
    if not scopes:
        return [], "Could not verify API scopes (no app installation visible for this token)"
    missing = [s for s in REQUIRED_SCOPES if s not in scopes]
    # Either fulfillment-order scope family satisfies fulfillmentCreate.
    if "write_merchant_managed_fulfillment_orders" in missing and (
        "write_assigned_fulfillment_orders" in scopes or "write_third_party_fulfillment_orders" in scopes
    ):
        missing.remove("write_merchant_managed_fulfillment_orders")
    return missing, None


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

async def refund_units(ctx: ShopifyCtx, order_gid: str, refunds: List[Dict[str, Any]],
                       note: str) -> Tuple[str, float]:
    """One $0 refund covering every planned refund line. Returns (refund id,
    amount refunded — expected 0.0)."""
    mutation = """
    mutation orderFixRefund($input: RefundInput!) {
      refundCreate(input: $input) {
        refund { id totalRefundedSet { shopMoney { amount } } }
        userErrors { field message }
      }
    }
    """
    line_items = [
        {"lineItemId": li["line_item_id"], "quantity": int(li["quantity"]), "restockType": "NO_RESTOCK"}
        for a in refunds for li in a.get("line_items", [])
    ]
    data = await _gql(ctx, mutation, {"input": {
        "orderId": order_gid,
        "note": note,
        "notify": False,
        "refundLineItems": line_items,
        "transactions": [],
    }})
    payload = _payload(data, "refundCreate", "refund")
    refund = payload.get("refund") or {}
    return refund.get("id") or "", _money(refund.get("totalRefundedSet"))


_CALC_LINE_FIELDS = """
      id
      quantity
      originalUnitPriceSet { shopMoney { amount } }
      discountedUnitPriceSet { shopMoney { amount } }
      calculatedDiscountAllocations { discountApplication { id } }
"""


async def _discount_line(ctx: ShopifyCtx, calc_id: str, line_id: str, amount: float,
                         description: str) -> Dict[str, Any]:
    mutation = f"""
    mutation orderFixDiscount($id: ID!, $lineItemId: ID!, $discount: OrderEditAppliedDiscountInput!) {{
      orderEditAddLineItemDiscount(id: $id, lineItemId: $lineItemId, discount: $discount) {{
        calculatedLineItem {{ {_CALC_LINE_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    data = await _gql(ctx, mutation, {
        "id": calc_id, "lineItemId": line_id,
        "discount": {"description": description,
                     "fixedValue": {"amount": f"{amount:.2f}", "currencyCode": ctx.currency}},
    })
    return _payload(data, "orderEditAddLineItemDiscount", "edit").get("calculatedLineItem") or {}


async def set_variant_price(ctx: ShopifyCtx, product_id: str, variant_id: str, price: str) -> None:
    mutation = """
    mutation orderFixVariantPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id price }
        userErrors { field message }
      }
    }
    """
    data = await _gql(ctx, mutation, {"productId": product_id, "variants": [{"id": variant_id, "price": price}]})
    _payload(data, "productVariantsBulkUpdate", "edit")


async def add_lines(ctx: ShopifyCtx, order_gid: str, adds: List[Dict[str, Any]],
                    note: str) -> Dict[str, Any]:
    """Begin an edit, add every planned line at the invoice price, verify,
    commit. Nothing changes on the order unless the commit runs. Variants
    whose price had to be raised are restored afterwards no matter what."""
    bumped: List[Dict[str, Any]] = []
    try:
        return await _add_lines(ctx, order_gid, adds, note, bumped)
    finally:
        restore_errors: List[str] = []
        for b in bumped:
            try:
                await set_variant_price(ctx, b["product_id"], b["variant_id"], b["price"])
            except Exception as e:  # keep restoring the others
                restore_errors.append(f"{b.get('barcode')}: {e}")
        if restore_errors:
            raise FixStepError(
                "edit",
                "VARIANT PRICE NOT RESTORED — set it back manually in Shopify: " + "; ".join(restore_errors),
            )


async def _add_lines(ctx: ShopifyCtx, order_gid: str, adds: List[Dict[str, Any]],
                     note: str, bumped: List[Dict[str, Any]]) -> Dict[str, Any]:
    begin = """
    mutation orderFixBegin($id: ID!) {
      orderEditBegin(id: $id) {
        calculatedOrder { id }
        userErrors { field message }
      }
    }
    """
    add_variant = f"""
    mutation orderFixAddVariant($id: ID!, $variantId: ID!, $quantity: Int!) {{
      orderEditAddVariant(id: $id, variantId: $variantId, quantity: $quantity, allowDuplicates: true) {{
        calculatedLineItem {{ {_CALC_LINE_FIELDS} }}
        userErrors {{ field message }}
      }}
    }}
    """
    commit = """
    mutation orderFixCommit($id: ID!, $note: String) {
      orderEditCommit(id: $id, notifyCustomer: false, staffNote: $note) {
        order {
          id
          totalOutstandingSet { shopMoney { amount } }
          fulfillmentOrders(first: 20) { nodes { id status } }
        }
        userErrors { field message }
      }
    }
    """
    data = await _gql(ctx, begin, {"id": order_gid})
    calc_id = (_payload(data, "orderEditBegin", "edit").get("calculatedOrder") or {}).get("id")
    if not calc_id:
        raise FixStepError("edit", "orderEditBegin returned no calculated order")

    added: List[Dict[str, Any]] = []
    for a in adds:
        qty = int(a["qty"])
        target = float(a["unit_price"])
        if a.get("bump_price"):
            if not a.get("product_id") or a.get("variant_price_raw") is None:
                raise FixStepError("edit", f"{a.get('barcode')}: cannot raise the variant price (product unknown)")
            await set_variant_price(ctx, a["product_id"], a["variant_id"], f"{target:.2f}")
            bumped.append({"product_id": a["product_id"], "variant_id": a["variant_id"],
                           "price": str(a["variant_price_raw"]), "barcode": a.get("barcode")})
        data = await _gql(ctx, add_variant, {"id": calc_id, "variantId": a["variant_id"], "quantity": qty})
        line = _payload(data, "orderEditAddVariant", "edit").get("calculatedLineItem") or {}
        line_id = line.get("id")
        if not line_id:
            raise FixStepError("edit", f"orderEditAddVariant returned no line for {a.get('barcode')}")
        unit = _money(line.get("discountedUnitPriceSet")) or _money(line.get("originalUnitPriceSet"))
        if unit + _PRICE_TOL < target:
            raise FixStepError("edit", f"{a.get('barcode')}: Shopify price {unit:.2f} is below invoice price {target:.2f}")
        if unit - target > _PRICE_TOL:
            # fixedValue is applied PER UNIT (verified on a staged edit:
            # 4.55 − 0.46 → 4.09 on a 3-unit line).
            line = await _discount_line(ctx, calc_id, line_id, round(unit - target, 2),
                                        f"Order Sync: invoice price {target:.2f}")
            got = _money(line.get("discountedUnitPriceSet"))
            if abs(got - target) > _PRICE_TOL:
                raise FixStepError(
                    "edit",
                    f"{a.get('barcode')}: could not set unit price to {target:.2f} (Shopify calculated {got:.2f}); edit abandoned",
                )
        added.append({"barcode": a.get("barcode"), "qty": qty, "unit_price": target, "calculated_line_id": line_id})

    data = await _gql(ctx, commit, {"id": calc_id, "note": note})
    order = _payload(data, "orderEditCommit", "edit").get("order") or {}
    open_fos = [fo.get("id") for fo in ((order.get("fulfillmentOrders") or {}).get("nodes") or [])
                if fo.get("id") and fo.get("status") in ("OPEN", "IN_PROGRESS", "SCHEDULED")]
    return {
        "calculated_order_id": calc_id,
        "added": added,
        "open_fulfillment_order_ids": open_fos,
        "outstanding": _money(order.get("totalOutstandingSet")),
    }


async def fulfill_open(ctx: ShopifyCtx, fulfillment_order_ids: List[str],
                       tracking_numbers: Optional[List[str]] = None) -> List[str]:
    mutation = """
    mutation orderFixFulfill($fulfillment: FulfillmentInput!) {
      fulfillmentCreate(fulfillment: $fulfillment) {
        fulfillment { id status }
        userErrors { field message }
      }
    }
    """
    ids: List[str] = []
    fulfillment: Dict[str, Any] = {
        "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": fo} for fo in fulfillment_order_ids],
        "notifyCustomer": False,
    }
    if tracking_numbers:
        fulfillment["trackingInfo"] = {"numbers": tracking_numbers}
    data = await _gql(ctx, mutation, {"fulfillment": fulfillment})
    f = _payload(data, "fulfillmentCreate", "fulfill").get("fulfillment") or {}
    if f.get("id"):
        ids.append(f["id"])
    return ids


async def mark_paid(ctx: ShopifyCtx, order_gid: str) -> Optional[str]:
    mutation = """
    mutation orderFixMarkPaid($input: OrderMarkAsPaidInput!) {
      orderMarkAsPaid(input: $input) {
        order { id displayFinancialStatus }
        userErrors { field message }
      }
    }
    """
    data = await _gql(ctx, mutation, {"input": {"id": order_gid}})
    return (_payload(data, "orderMarkAsPaid", "mark_paid").get("order") or {}).get("displayFinancialStatus")


async def push_tracking(ctx: ShopifyCtx, fulfillment_ids: List[str], numbers: List[str]) -> int:
    mutation = """
    mutation orderFixTracking($fulfillmentId: ID!, $trackingInfoInput: FulfillmentTrackingInput!) {
      fulfillmentTrackingInfoUpdate(fulfillmentId: $fulfillmentId, trackingInfoInput: $trackingInfoInput, notifyCustomer: false) {
        fulfillment { id }
        userErrors { field message }
      }
    }
    """
    done = 0
    for fid in fulfillment_ids:
        data = await _gql(ctx, mutation, {"fulfillmentId": fid, "trackingInfoInput": {"numbers": numbers}})
        _payload(data, "fulfillmentTrackingInfoUpdate", "tracking")
        done += 1
    return done


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _editable_guard(order: Dict[str, Any]) -> Optional[str]:
    if order.get("cancelled"):
        return "Order is cancelled in Shopify"
    if order.get("financial_status") == "REFUNDED":
        return "Order is fully refunded in Shopify"
    if order.get("fulfillment_status") != "FULFILLED":
        return f"Order is {order.get('fulfillment_status') or 'not fulfilled'} in Shopify — fix it there first"
    return None


def _barcodes_needing_variants(order: Dict[str, Any], invoice: Dict[str, Any]) -> List[str]:
    _kinds, diffs = osync.compare_lines(order, invoice)
    out: List[str] = []
    for d in diffs:
        issues = d.get("issues") or []
        needs_add = ("missing_in_shopify" in issues or "price" in issues
                     or ("qty" in issues and (d.get("sh_qty") or 0) < (d.get("bo_qty") or 0)))
        if needs_add and d.get("barcode"):
            out.append(d["barcode"])
    return out


async def prepare_target(ctx: ShopifyCtx, tz: Optional[str], target: Dict[str, Any],
                         invoice_conn: Dict[str, Any], push_tracking_numbers: bool = True) -> Dict[str, Any]:
    """Fresh order + invoice + plan for one target. `status` is one of
    ready | noop | skipped | error; `order`/`invoice` are present when fetched."""
    order_gid, invoice_id = target["sh_order_id"], int(target["bo_invoice_id"])
    (ok_o, err_o, order), (ok_i, err_i, invoice) = await asyncio.gather(
        fetch_order_for_sync(ctx.shop_domain, ctx.admin_api_key, order_gid,
                             api_version=ctx.api_version, tz=tz, session=ctx.session),
        osync.fetch_invoice_async(**invoice_conn, invoice_id=invoice_id),
    )
    base = {"sh_order_id": order_gid, "bo_invoice_id": invoice_id,
            "sh_name": (order or {}).get("name"), "bo_invoice_number": (invoice or {}).get("invoice_number")}
    if not ok_o:
        return {**base, "status": "error", "message": f"Shopify: {err_o}"}
    if not ok_i:
        return {**base, "status": "error", "message": f"BackOffice: {err_i}"}

    guard = _editable_guard(order)
    if guard:
        return {**base, "status": "skipped", "message": guard, "order": order, "invoice": invoice}

    variants: Dict[str, Dict[str, Any]] = {}
    barcodes = _barcodes_needing_variants(order, invoice)
    if barcodes:
        try:
            variants = await find_variants_by_barcode(
                ctx.session, ctx.shop_domain, ctx.admin_api_key, ctx.api_version, barcodes)
        except ShopifyFetchError as e:
            return {**base, "status": "error", "message": f"Variant lookup failed: {e}", "order": order, "invoice": invoice}

    plan = osync.plan_order_fix(order, invoice, variants, push_tracking=push_tracking_numbers)
    return {
        **base,
        "status": "noop" if plan["noop"] else "ready",
        "message": None if not plan["noop"] else (
            "Nothing to change" if not plan["unsupported"] else "Only unsupported differences remain"),
        "order": order, "invoice": invoice, "plan": plan,
    }


def _rebuild_row(order: Dict[str, Any], invoice: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    return osync.build_pair_row([order], [invoice], target.get("match_method"),
                                bool(target.get("ambiguous")), None)


async def apply_order_fix(ctx: ShopifyCtx, tz: Optional[str], target: Dict[str, Any],
                          invoice_conn: Dict[str, Any], note: str) -> Dict[str, Any]:
    """Plan from fresh data, execute, re-fetch, rebuild the row. Never raises
    for a per-order failure — the outcome is in `status`/`steps`."""
    prep = await prepare_target(ctx, tz, target, invoice_conn)
    result: Dict[str, Any] = {
        "sh_order_id": prep["sh_order_id"], "sh_name": prep.get("sh_name"),
        "bo_invoice_id": prep["bo_invoice_id"], "bo_invoice_number": prep.get("bo_invoice_number"),
        "status": prep["status"], "message": prep.get("message"),
        "steps": [], "unsupported": (prep.get("plan") or {}).get("unsupported", []),
        "actions": (prep.get("plan") or {}).get("actions", []),
        "status_before": None, "row": None,
    }
    order, invoice = prep.get("order"), prep.get("invoice")
    if order and invoice:
        result["status_before"] = _rebuild_row(order, invoice, target)["status"]
    if prep["status"] != "ready":
        if order and invoice:
            result["row"] = _rebuild_row(order, invoice, target)
        return result

    plan = prep["plan"]
    actions = plan["actions"]
    refunds = [a for a in actions if a["kind"] == "refund"]
    adds = [a for a in actions if a["kind"] == "add"]
    tracking = next((a for a in actions if a["kind"] == "tracking"), None)
    steps: List[Dict[str, Any]] = result["steps"]
    bo_numbers, _ = osync.split_routes(osync.split_tracking(invoice.get("tracking_no")))

    def step(name: str, ok: bool, message: Optional[str] = None, ids: Optional[List[str]] = None):
        steps.append({"step": name, "ok": ok, "message": message, "ids": [i for i in (ids or []) if i]})

    failed: Optional[str] = None
    try:
        if refunds:
            units = sum(a["qty"] for a in refunds)
            refund_id, amount = await refund_units(ctx, order["id"], refunds, note)
            step("refund", True, f"Refunded {units} unit(s), ${amount:.2f} returned", [refund_id])

        if adds:
            edit = await add_lines(ctx, order["id"], adds, note)
            units = sum(a["qty"] for a in adds)
            step("edit", True, f"Added {units} unit(s) across {len(adds)} line(s)", [edit["calculated_order_id"]])

            fo_ids = edit["open_fulfillment_order_ids"]
            if fo_ids:
                fids = await fulfill_open(ctx, fo_ids, bo_numbers or None)
                step("fulfill", True, f"Fulfilled {len(fo_ids)} new fulfillment order(s)", fids)
            else:
                step("fulfill", True, "No open fulfillment order after the edit", [])

            if edit["outstanding"] > 0.004:
                status = await mark_paid(ctx, order["id"])
                step("mark_paid", True, f"Marked ${edit['outstanding']:.2f} as paid ({status})", [])
            else:
                step("mark_paid", True, "No outstanding balance", [])

        if tracking:
            n = await push_tracking(ctx, tracking["fulfillment_ids"], tracking["numbers"])
            step("tracking", True, f"Tracking {', '.join(tracking['numbers'])} set on {n} fulfillment(s)", [])

    except FixStepError as e:
        failed = e.step
        step(e.step, False, e.message, [])
    except ShopifyFetchError as e:
        failed = "shopify"
        step("shopify", False, str(e), [])
    except Exception as e:  # never let one order abort the batch
        failed = "unexpected"
        step("unexpected", False, str(e), [])

    if failed:
        done = [s for s in steps if s["ok"]]
        result["status"] = "partial" if done else "failed"
        result["message"] = steps[-1]["message"]
        if failed == "fulfill" or (failed == "mark_paid" and adds):
            result["message"] = (result["message"] or "") + " — added items are UNFULFILLED in Shopify; fulfill them there or the order drops out of Month End"
    else:
        result["status"] = "applied"
        result["message"] = None

    ok, err, fresh = await fetch_order_for_sync(ctx.shop_domain, ctx.admin_api_key, order["id"],
                                                api_version=ctx.api_version, tz=tz, session=ctx.session)
    if ok and fresh:
        row = _rebuild_row(fresh, invoice, target)
        result["row"] = row
        result["status_after"] = row["status"]
    else:
        result["row"] = None
        result["status_after"] = None
        result["message"] = (result["message"] or "Applied") + f" (re-fetch failed: {err})"
    return result
