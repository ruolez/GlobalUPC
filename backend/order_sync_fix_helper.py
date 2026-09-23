"""
Order Sync — "Fix in Shopify": apply the plan produced by
order_sync_helper.plan_order_fix to a live Shopify order.

Every order the report lists is FULFILLED, and Shopify's order-edit API only
touches unfulfilled line items, so the executor combines three APIs:

  create_product
           productSet: the UPC carries no variant in this store, so the
           product is created from the BackOffice item (barcode = the UPC,
           active, on no sales channel, inventory untracked) and the `add`
           below uses it. Opt-in per run; runs FIRST so the edit has a
           variant to add.
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
  variant_price
           productVariantsBulkUpdate: for every repriced line, the variant's
           storefront price is set to the BackOffice item price
           (Items_tbl.UnitPrice by ProductUPC = barcode) so future orders come
           in at that price. Runs LAST — the edit step restores the temporary
           price bump in a finally block and would undo an earlier write.

The customer is never notified. Steps run create product → refund → edit →
fulfill → mark paid → tracking → store price; the first failure stops the chain, and the caller
re-fetches the order so the reported row (and any later re-run) reflects what
actually happened — a re-run plans only what is still different (so a failed
store-price step is not retried: the order no longer shows a price difference).
"""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

import order_sync_helper as osync
from mssql_helper import get_item_prices_batch_async
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
_PRICE_TOL = osync.PRICE_TOL


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


# Right after a refund / edit / fulfillment Shopify briefly locks the order
# ("Order is temporarily unavailable to be modified") while it settles; the
# next step must wait it out rather than fail.
_TRANSIENT_MARKERS = ("temporarily unavailable", "try again", "currently being modified")
_RETRY_DELAYS = (1.5, 2.5, 4.0, 6.0, 8.0)


def _is_already_paid(message: str) -> bool:
    return "cannot be marked as paid" in (message or "").lower()


def _is_transient(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in _TRANSIENT_MARKERS)


async def _with_retry(coro_factory):
    """Run a step, retrying only on Shopify's transient order lock."""
    for i, delay in enumerate(_RETRY_DELAYS):
        try:
            return await coro_factory()
        except FixStepError as e:
            if not _is_transient(e.message):
                raise
            await asyncio.sleep(delay)
    return await coro_factory()


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


async def set_variant_price(ctx: ShopifyCtx, product_id: str, variant_id: str, price: str,
                            step: str = "edit") -> None:
    mutation = """
    mutation orderFixVariantPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
      productVariantsBulkUpdate(productId: $productId, variants: $variants) {
        productVariants { id price }
        userErrors { field message }
      }
    }
    """
    data = await _gql(ctx, mutation, {"productId": product_id, "variants": [{"id": variant_id, "price": price}]})
    _payload(data, "productVariantsBulkUpdate", step)


# A raised variant price is store-wide state. Two orders fixed in parallel
# that both bump the same variant interleave bump / add / restore and one of
# them adds its line at the other's price (seen live: 53.55 instead of the
# bumped 56.50), so edits that need a bump run one at a time. Edits with no
# bump never touch the catalog and stay parallel.
_bump_lock = asyncio.Lock()

_BUMP_READBACK_ATTEMPTS = 5
_BUMP_READBACK_DELAY_SECONDS = 1.0


async def _read_variant_price(ctx: ShopifyCtx, variant_id: str) -> Optional[float]:
    query = """
    query orderFixVariantPrice($id: ID!) {
      productVariant(id: $id) { id price }
    }
    """
    data = await _gql(ctx, query, {"id": variant_id})
    try:
        return float(((data or {}).get("productVariant") or {}).get("price"))
    except (TypeError, ValueError):
        return None


async def _bump_variant_price(ctx: ShopifyCtx, add: Dict[str, Any], target: float,
                              bumped: List[Dict[str, Any]]) -> None:
    """Raise the variant to `target` and wait until Shopify reads it back at
    that price, so the add that follows cannot be priced off a stale value."""
    await set_variant_price(ctx, add["product_id"], add["variant_id"], f"{target:.2f}")
    bumped.append({"product_id": add["product_id"], "variant_id": add["variant_id"],
                   "price": str(add["variant_price_raw"]), "barcode": add.get("barcode")})
    for attempt in range(_BUMP_READBACK_ATTEMPTS):
        price = await _read_variant_price(ctx, add["variant_id"])
        if price is not None and abs(price - target) <= _PRICE_TOL:
            return
        if attempt + 1 < _BUMP_READBACK_ATTEMPTS:
            await asyncio.sleep(_BUMP_READBACK_DELAY_SECONDS)
    raise FixStepError(
        "edit",
        f"{add.get('barcode')}: variant price did not settle at {target:.2f} after the raise (reads {price}); edit abandoned",
    )


async def add_lines(ctx: ShopifyCtx, order_gid: str, adds: List[Dict[str, Any]],
                    note: str, shipping: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Begin an edit, add every planned line at the invoice price and apply
    every shipping-line replacement, verify, commit. Nothing changes on the
    order unless the commit runs. Variants whose price had to be raised are
    restored afterwards no matter what, and such edits are serialized across
    orders (see _bump_lock)."""
    if not any(a.get("bump_price") for a in adds):
        return await _add_lines(ctx, order_gid, adds, note, [], shipping)
    async with _bump_lock:
        return await _add_lines_restoring(ctx, order_gid, adds, note, shipping)


async def _add_lines_restoring(ctx: ShopifyCtx, order_gid: str, adds: List[Dict[str, Any]],
                               note: str, shipping: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    bumped: List[Dict[str, Any]] = []
    try:
        return await _add_lines(ctx, order_gid, adds, note, bumped, shipping)
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


async def _replace_shipping_lines(ctx: ShopifyCtx, calc_id: str, action: Dict[str, Any]) -> None:
    """Drop the order's existing shipping line(s); when the invoice carries
    shipping, add one back at that amount under the same title."""
    remove = """
    mutation orderFixRemoveShipping($id: ID!, $shippingLineId: ID!) {
      orderEditRemoveShippingLine(id: $id, shippingLineId: $shippingLineId) {
        calculatedOrder { id }
        userErrors { field message }
      }
    }
    """
    add = """
    mutation orderFixAddShipping($id: ID!, $shippingLine: OrderEditAddShippingLineInput!) {
      orderEditAddShippingLine(id: $id, shippingLine: $shippingLine) {
        calculatedShippingLine { id title price { shopMoney { amount } } }
        userErrors { field message }
      }
    }
    """
    for sid in action.get("remove_ids") or []:
        data = await _gql(ctx, remove, {"id": calc_id, "shippingLineId": sid})
        _payload(data, "orderEditRemoveShippingLine", "edit")
    amount = action.get("amount")
    if amount is None:
        return
    data = await _gql(ctx, add, {"id": calc_id, "shippingLine": {
        "title": action.get("title") or "Shipping",
        "price": {"amount": f"{float(amount):.2f}", "currencyCode": ctx.currency},
    }})
    line = _payload(data, "orderEditAddShippingLine", "edit").get("calculatedShippingLine") or {}
    got = _money(line.get("price"))
    if abs(got - float(amount)) > _PRICE_TOL:
        raise FixStepError("edit", f"shipping: could not set the shipping line to {float(amount):.2f} (Shopify calculated {got:.2f}); edit abandoned")


async def _add_lines(ctx: ShopifyCtx, order_gid: str, adds: List[Dict[str, Any]],
                     note: str, bumped: List[Dict[str, Any]],
                     shipping: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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
          currentTotalPriceSet { shopMoney { amount } }
          netPaymentSet { shopMoney { amount } }
          canMarkAsPaid
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
            await _bump_variant_price(ctx, a, target, bumped)
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

    for s in shipping or []:
        await _replace_shipping_lines(ctx, calc_id, s)

    data = await _gql(ctx, commit, {"id": calc_id, "note": note})
    order = _payload(data, "orderEditCommit", "edit").get("order") or {}
    open_fos = [fo.get("id") for fo in ((order.get("fulfillmentOrders") or {}).get("nodes") or [])
                if fo.get("id") and fo.get("status") in ("OPEN", "IN_PROGRESS", "SCHEDULED")]
    return {
        "calculated_order_id": calc_id,
        "added": added,
        "open_fulfillment_order_ids": open_fos,
        "outstanding": osync.collectible_balance(
            _money(order.get("currentTotalPriceSet")), _money(order.get("netPaymentSet")), order.get("canMarkAsPaid", True)),
        "gross_outstanding": _money(order.get("totalOutstandingSet")),
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


# A backfilled product is store-wide state and two orders in the same batch
# can need the same UPC, so creation is serialized and the catalog is
# re-checked inside the lock — a barcode is never created twice.
_create_lock = asyncio.Lock()

PRODUCT_BACKFILL_TAG = "order-sync-backfill"

_PRODUCT_SET = """
mutation orderFixCreateProduct($input: ProductSetInput!) {
  productSet(synchronous: true, input: $input) {
    product {
      id
      status
      variants(first: 1) { nodes { id price barcode sku } }
    }
    userErrors { field message }
  }
}
"""


async def _create_product(ctx: ShopifyCtx, action: Dict[str, Any]) -> Dict[str, Any]:
    """Create one product carrying the UPC as its barcode. Returns the same
    shape find_variants_by_barcode yields, so the planner cannot tell the
    difference between a created variant and one that was already there."""
    variant: Dict[str, Any] = {
        "optionValues": [{"optionName": "Title", "name": "Default Title"}],
        "barcode": action["barcode"],
        "price": f"{float(action['unit_price']):.2f}",
        "inventoryPolicy": "CONTINUE",
        "inventoryItem": {"tracked": False},
    }
    if action.get("sku"):
        variant["sku"] = action["sku"]
    cost = action.get("unit_cost")
    if cost is not None and float(cost) > 0:
        variant["inventoryItem"]["cost"] = f"{float(cost):.2f}"

    data = await _gql(ctx, _PRODUCT_SET, {"input": {
        "title": action["title"],
        "status": "ACTIVE",
        "tags": [PRODUCT_BACKFILL_TAG],
        "productOptions": [{"name": "Title", "values": [{"name": "Default Title"}]}],
        "variants": [variant],
    }})
    product = _payload(data, "productSet", "create_product").get("product") or {}
    nodes = ((product.get("variants") or {}).get("nodes") or [])
    node = nodes[0] if nodes else {}
    if not product.get("id") or not node.get("id"):
        raise FixStepError("create_product", f"{action['barcode']}: productSet returned no variant")
    if (node.get("barcode") or "").strip() != action["barcode"]:
        raise FixStepError(
            "create_product",
            f"{action['barcode']}: created variant carries barcode {node.get('barcode')!r}")
    try:
        price = float(node.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    return {
        "variant_id": node["id"], "product_id": product["id"],
        "price": price, "price_raw": node.get("price"),
        "sku": (node.get("sku") or "").strip(),
        "product_title": action["title"], "variant_title": "",
        "product_status": product.get("status"),
    }


async def create_missing_products(ctx: ShopifyCtx, actions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """barcode -> variant for every planned create. A barcode that turned up
    in the catalog since the plan was built (another order in the same batch,
    or a product published meanwhile) is reused, flagged `reused`."""
    created: Dict[str, Dict[str, Any]] = {}
    for action in actions:
        barcode = (action.get("barcode") or "").strip()
        if not barcode or barcode in created:
            continue
        async with _create_lock:
            existing = await find_variants_by_barcode(
                ctx.session, ctx.shop_domain, ctx.admin_api_key, ctx.api_version, [barcode])
            found = existing.get(barcode)
            if found and found.get("variant_id"):
                created[barcode] = {**found, "reused": True}
                continue
            created[barcode] = await _create_product(ctx, action)
    return created


_PRODUCT_STATUS = """
query orderSyncCreatedProducts($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Product {
      id
      title
      status
      publishedAt
      onlineStoreUrl
      variants(first: 1) { nodes { id barcode sku price } }
    }
  }
}
"""


async def fetch_product_status(ctx: ShopifyCtx, product_gids: List[str]) -> Dict[str, Dict[str, Any]]:
    """product gid -> what the product looks like in Shopify NOW, for the
    created-products log. A gid that comes back null was deleted in Shopify
    and is absent from the result. Only read_products is needed: `publishedAt`
    / `onlineStoreUrl` answer "is it on the storefront?" without the
    read_publications scope."""
    out: Dict[str, Dict[str, Any]] = {}
    ids = [g for g in dict.fromkeys(product_gids) if g]
    for i in range(0, len(ids), 50):
        data = await _gql(ctx, _PRODUCT_STATUS, {"ids": ids[i:i + 50]})
        for node in (data or {}).get("nodes") or []:
            if not node or not node.get("id"):
                continue
            variants = ((node.get("variants") or {}).get("nodes") or [])
            v = variants[0] if variants else {}
            out[node["id"]] = {
                "title": node.get("title"),
                "status": node.get("status"),
                "published": bool(node.get("publishedAt")) or bool(node.get("onlineStoreUrl")),
                "barcode": (v.get("barcode") or "").strip(),
                "sku": (v.get("sku") or "").strip(),
                "price": v.get("price"),
            }
    return out


async def set_store_prices(ctx: ShopifyCtx, actions: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """Set each variant's storefront price to the BackOffice item price.
    Products are independent, so one failure does not stop the others;
    returns (variant ids done, error strings)."""
    done: List[str] = []
    errors: List[str] = []
    for a in actions:
        if not a.get("product_id"):
            errors.append(f"{a.get('barcode')}: product unknown")
            continue
        try:
            await set_variant_price(ctx, a["product_id"], a["variant_id"],
                                    f"{float(a['unit_price']):.2f}", step="variant_price")
            done.append(a["variant_id"])
        except (FixStepError, ShopifyFetchError) as e:
            errors.append(f"{a.get('barcode')}: {getattr(e, 'message', None) or e}")
    return done, errors


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


def _fix_barcodes(order: Dict[str, Any], invoice: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """(barcodes that need a Shopify variant, barcodes whose line is repriced)."""
    _kinds, diffs = osync.compare_lines(order, invoice)
    need_variant: List[str] = []
    repriced: List[str] = []
    for d in diffs:
        issues = d.get("issues") or []
        if not d.get("barcode"):
            continue
        needs_add = ("missing_in_shopify" in issues or "price" in issues
                     or ("qty" in issues and (d.get("sh_qty") or 0) < (d.get("bo_qty") or 0)))
        if needs_add:
            need_variant.append(d["barcode"])
        if "price" in issues and d["key"] != osync.SHIPPING_KEY:
            repriced.append(d["barcode"])
    return need_variant, repriced


async def prepare_target(ctx: ShopifyCtx, tz: Optional[str], target: Dict[str, Any],
                         invoice_conn: Dict[str, Any], push_tracking_numbers: bool = True,
                         create_products: bool = False) -> Dict[str, Any]:
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
    barcodes, repriced = _fix_barcodes(order, invoice)
    if barcodes:
        try:
            variants = await find_variants_by_barcode(
                ctx.session, ctx.shop_domain, ctx.admin_api_key, ctx.api_version, barcodes)
        except ShopifyFetchError as e:
            return {**base, "status": "error", "message": f"Variant lookup failed: {e}", "order": order, "invoice": invoice}

    # One Items_tbl read serving two purposes: the storefront price of a
    # repriced line, and the title/price/cost of a product about to be
    # created. A failed lookup must not block the order-line fix — the
    # planner turns it into a note.
    wanted = list(repriced)
    if create_products:
        wanted += [b for b in barcodes if b not in variants]
    wanted = list(dict.fromkeys(wanted))

    item_prices: Optional[Dict[str, Dict[str, Any]]] = None
    item_price_error: Optional[str] = None
    if wanted:
        ok_p, err_p, item_prices = await get_item_prices_batch_async(**invoice_conn, upcs=wanted)
        if not ok_p:
            item_prices, item_price_error = None, err_p or "unknown error"

    plan = osync.plan_order_fix(order, invoice, variants, push_tracking=push_tracking_numbers,
                                item_prices=item_prices, item_price_error=item_price_error,
                                create_products=create_products)
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
                          invoice_conn: Dict[str, Any], note: str,
                          create_products: bool = False) -> Dict[str, Any]:
    """Plan from fresh data, execute, re-fetch, rebuild the row. Never raises
    for a per-order failure — the outcome is in `status`/`steps`."""
    prep = await prepare_target(ctx, tz, target, invoice_conn, create_products=create_products)
    result: Dict[str, Any] = {
        "sh_order_id": prep["sh_order_id"], "sh_name": prep.get("sh_name"),
        "bo_invoice_id": prep["bo_invoice_id"], "bo_invoice_number": prep.get("bo_invoice_number"),
        "status": prep["status"], "message": prep.get("message"),
        "steps": [], "unsupported": (prep.get("plan") or {}).get("unsupported", []),
        "actions": (prep.get("plan") or {}).get("actions", []),
        "created_products": [],   # products this run ADDED to the catalog
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
    creates = [a for a in actions if a["kind"] == "create_product"]
    refunds = [a for a in actions if a["kind"] == "refund"]
    adds = [a for a in actions if a["kind"] == "add"]
    tracking = next((a for a in actions if a["kind"] == "tracking"), None)
    store_prices = [a for a in actions if a["kind"] == "variant_price"]
    shipping = [a for a in actions if a["kind"] == "shipping_line"]
    outstanding = float(order.get("outstanding") or 0)   # collectible balance left by an earlier partial run
    gross_outstanding = float(order.get("gross_outstanding") or 0)
    steps: List[Dict[str, Any]] = result["steps"]
    bo_numbers, _ = osync.split_routes(osync.split_tracking(invoice.get("tracking_no")))

    def step(name: str, ok: bool, message: Optional[str] = None, ids: Optional[List[str]] = None):
        steps.append({"step": name, "ok": ok, "message": message, "ids": [i for i in (ids or []) if i]})

    failed: Optional[str] = None
    try:
        if creates:
            # First: the edit below needs a variant to add. A product created
            # here outlives a later failure on purpose — the re-run finds it
            # by barcode and reuses it.
            made = await _with_retry(lambda: create_missing_products(ctx, creates))
            unresolved = osync.resolve_created_variants(actions, made)
            if unresolved:
                raise FixStepError("create_product",
                                   "no usable variant after creating " + ", ".join(unresolved))
            fresh = [b for b, v in made.items() if not v.get("reused")]
            reused = [b for b, v in made.items() if v.get("reused")]
            by_barcode = {a["barcode"]: a for a in creates}
            result["created_products"] = [
                {"barcode": b, "title": by_barcode[b].get("title"), "sku": by_barcode[b].get("sku"),
                 "price": by_barcode[b].get("unit_price"), "unit_cost": by_barcode[b].get("unit_cost"),
                 "price_source": by_barcode[b].get("price_source"),
                 "product_gid": made[b].get("product_id"), "variant_gid": made[b].get("variant_id")}
                for b in fresh if b in by_barcode
            ]
            parts = []
            if fresh:
                parts.append(f"Created {len(fresh)} product(s): " + ", ".join(fresh))
            if reused:
                parts.append(f"reused {len(reused)} existing: " + ", ".join(reused))
            step("create_product", True, "; ".join(parts), [v.get("product_id") for v in made.values()])

        if refunds:
            units = sum(a["qty"] for a in refunds)
            refund_id, amount = await _with_retry(lambda: refund_units(ctx, order["id"], refunds, note))
            step("refund", True, f"Refunded {units} unit(s), ${amount:.2f} returned", [refund_id])

        if adds or shipping:
            edit = await _with_retry(lambda: add_lines(ctx, order["id"], adds, note, shipping))
            units = sum(a["qty"] for a in adds)
            parts = []
            if adds:
                parts.append(f"Added {units} unit(s) across {len(adds)} line(s)")
            for s in shipping:
                parts.append(f"shipping line removed (${s.get('sh_amount') or 0:.2f})" if s.get("amount") is None
                             else f"shipping line set to ${float(s['amount']):.2f} (was ${s.get('sh_amount') or 0:.2f})")
            step("edit", True, "; ".join(parts), [edit["calculated_order_id"]])
            outstanding = edit["outstanding"]
            gross_outstanding = edit.get("gross_outstanding") or 0.0

            fo_ids = edit["open_fulfillment_order_ids"]
            if fo_ids:
                fids = await _with_retry(lambda: fulfill_open(ctx, fo_ids, bo_numbers or None))
                step("fulfill", True, f"Fulfilled {len(fo_ids)} new fulfillment order(s)", fids)
            else:
                step("fulfill", True, "No open fulfillment order after the edit", [])

        if outstanding > 0.004:
            try:
                status = await _with_retry(lambda: mark_paid(ctx, order["id"]))
                step("mark_paid", True, f"Marked ${gross_outstanding or outstanding:.2f} as paid ({status})", [])
            except FixStepError as e:
                if not _is_already_paid(e.message):
                    raise
                step("mark_paid", True, f"Shopify already shows the order as paid — {e.message}", [])
        elif adds or shipping:
            step("mark_paid", True,
                 "No balance to collect — Shopify shows the order as paid"
                 + (f" (earlier $0 refunds left a credit covering the ${gross_outstanding:.2f} added)" if gross_outstanding > 0.004 else ""),
                 [])

        if tracking:
            n = await _with_retry(lambda: push_tracking(ctx, tracking["fulfillment_ids"], tracking["numbers"]))
            step("tracking", True, f"Tracking {', '.join(tracking['numbers'])} set on {n} fulfillment(s)", [])

        if store_prices:
            # Last on purpose: add_lines restores any temporary price bump in
            # its finally block, which would overwrite an earlier write.
            done_ids, errors = await _with_retry(lambda: set_store_prices(ctx, store_prices))
            if errors:
                raise FixStepError(
                    "variant_price",
                    f"Store price set on {len(done_ids)} of {len(store_prices)} product(s); failed: " + "; ".join(errors),
                )
            changed = ", ".join(
                f"{a.get('barcode')} {float(a['variant_price']):.2f} → {float(a['unit_price']):.2f}"
                for a in store_prices)
            step("variant_price", True, f"Store price {changed}", done_ids)

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
        if failed == "create_product":
            result["message"] = (result["message"] or "") + " — nothing was changed on the order; any product that was created is reused when you run the fix again"
        elif failed == "fulfill":
            result["message"] = (result["message"] or "") + " — added items are UNFULFILLED in Shopify; fulfill them there or the order drops out of Month End"
        elif failed == "mark_paid":
            result["message"] = (result["message"] or "") + " — lines are corrected; run the fix again to mark the balance paid"
        elif failed == "variant_price":
            result["message"] = (result["message"] or "") + " — order lines are corrected; a re-run will not retry this, set the store price manually in Shopify"
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
