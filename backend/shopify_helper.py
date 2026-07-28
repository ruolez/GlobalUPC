import requests
import aiohttp
import asyncio
import random
import time
from typing import Optional, Dict, Any, List, Tuple

def test_shopify_connection(
    shop_domain: str,
    admin_api_key: str,
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
    """
    Test Shopify connection using Admin API.

    Args:
        shop_domain: Shop domain (e.g., mystore.myshopify.com)
        admin_api_key: Shopify Admin API access token
        api_version: API version (e.g., 2025-01)

    Returns:
        Tuple of (success: bool, error_message: Optional[str], shop_info: Optional[Dict])
    """
    try:
        # Ensure shop domain is properly formatted
        if not shop_domain:
            return False, "Shop domain is required", None

        # Remove https:// if present
        shop_domain = shop_domain.replace("https://", "").replace("http://", "")

        # Ensure .myshopify.com suffix if not present
        if not shop_domain.endswith(".myshopify.com"):
            shop_domain = f"{shop_domain}.myshopify.com"

        # Build API endpoint
        url = f"https://{shop_domain}/admin/api/{api_version}/shop.json"

        # Make request
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers, timeout=10)

        # Check response
        if response.status_code == 200:
            shop_data = response.json().get("shop", {})
            shop_info = {
                "name": shop_data.get("name"),
                "email": shop_data.get("email"),
                "domain": shop_data.get("domain"),
                "myshopify_domain": shop_data.get("myshopify_domain"),
                "plan_name": shop_data.get("plan_name"),
                "currency": shop_data.get("currency"),
                "timezone": shop_data.get("timezone")
            }
            return True, None, shop_info
        elif response.status_code == 401:
            return False, "Invalid API key or unauthorized access", None
        elif response.status_code == 404:
            return False, f"Shop not found or API version '{api_version}' not available", None
        elif response.status_code == 403:
            return False, "Access forbidden - check API key permissions", None
        else:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get("errors", f"HTTP {response.status_code}: {response.reason}")
            return False, str(error_msg), None

    except requests.exceptions.Timeout:
        return False, "Connection timeout - shop may be unreachable", None
    except requests.exceptions.ConnectionError:
        return False, "Connection error - check shop domain and network", None
    except requests.exceptions.RequestException as e:
        return False, f"Request error: {str(e)}", None
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", None

def validate_shop_domain(shop_domain: str) -> str:
    """
    Validate and normalize shop domain.

    Args:
        shop_domain: Shop domain to validate

    Returns:
        Normalized shop domain
    """
    if not shop_domain:
        raise ValueError("Shop domain is required")

    # Remove protocol
    shop_domain = shop_domain.replace("https://", "").replace("http://", "")

    # Remove trailing slash
    shop_domain = shop_domain.rstrip("/")

    # Ensure .myshopify.com suffix
    if not shop_domain.endswith(".myshopify.com"):
        # Check if it's just the store name
        if "." not in shop_domain:
            shop_domain = f"{shop_domain}.myshopify.com"
        else:
            raise ValueError("Invalid shop domain. Use format: storename.myshopify.com")

    return shop_domain

async def check_barcode_exists(
    shop_domain: str,
    admin_api_key: str,
    barcode: str,
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Check if a barcode exists in Shopify store using GraphQL Admin API.

    Args:
        shop_domain: Shop domain (e.g., mystore.myshopify.com)
        admin_api_key: Shopify Admin API access token
        barcode: UPC/barcode to check
        api_version: API version (e.g., 2025-01)

    Returns:
        Tuple of (success: bool, error_message: Optional[str], variants: List[Dict])
    """
    try:
        # Normalize shop domain
        shop_domain = validate_shop_domain(shop_domain)

        # Build GraphQL query
        query = """
        query checkBarcodeExists($barcode: String!) {
          productVariants(first: 10, query: $barcode) {
            edges {
              node {
                id
                barcode
                sku
                title
                displayName
                product {
                  id
                  title
                  status
                }
              }
            }
          }
        }
        """

        variables = {
            "barcode": f"barcode:{barcode}"
        }

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return False, f"HTTP {response.status}: {error_text}", []

                data = await response.json()

                # Check for GraphQL errors
                if "errors" in data:
                    errors = data["errors"]
                    error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                    return False, f"GraphQL errors: {error_msg}", []

                # Extract variants and filter by ACTIVE status
                variants = []
                edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

                for edge in edges:
                    node = edge.get("node", {})
                    product = node.get("product", {})

                    # Only include variants from ACTIVE products
                    if product.get("status") == "ACTIVE":
                        variant_data = {
                            "variant_id": node.get("id"),
                            "product_id": product.get("id"),
                            "product_title": product.get("title"),
                            "variant_title": node.get("title") or "Default",
                            "display_name": node.get("displayName"),
                            "barcode": node.get("barcode"),
                            "sku": node.get("sku")
                        }
                        variants.append(variant_data)

                return True, None, variants

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

async def search_products_by_barcode(
    shop_domain: str,
    admin_api_key: str,
    barcode: str,
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Search for product variants by barcode using Shopify GraphQL Admin API.

    Args:
        shop_domain: Shop domain (e.g., mystore.myshopify.com)
        admin_api_key: Shopify Admin API access token
        barcode: UPC/barcode to search for
        api_version: API version (e.g., 2025-01)

    Returns:
        Tuple of (success: bool, error_message: Optional[str], variants: List[Dict])
    """
    try:
        # Normalize shop domain
        shop_domain = validate_shop_domain(shop_domain)

        # Build GraphQL query
        query = """
        query searchByBarcode($query: String!) {
          productVariants(first: 100, query: $query) {
            edges {
              node {
                id
                barcode
                sku
                displayName
                title
                product {
                  id
                  title
                  status
                }
              }
            }
            pageInfo {
              hasNextPage
              endCursor
            }
          }
        }
        """

        variables = {
            "query": f"barcode:{barcode}"
        }

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return False, f"HTTP {response.status}: {error_text}", []

                data = await response.json()

                # Check for GraphQL errors
                if "errors" in data:
                    errors = data["errors"]
                    error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                    return False, f"GraphQL errors: {error_msg}", []

                # Extract variants and filter by ACTIVE status
                variants = []
                edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

                for edge in edges:
                    node = edge.get("node", {})
                    product = node.get("product", {})

                    # Only include variants from ACTIVE products
                    if product.get("status") == "ACTIVE":
                        variant_data = {
                            "variant_id": node.get("id"),
                            "product_id": product.get("id"),
                            "product_title": product.get("title"),
                            "variant_title": node.get("title") or "Default",
                            "display_name": node.get("displayName"),
                            "barcode": node.get("barcode"),
                            "sku": node.get("sku")
                        }
                        variants.append(variant_data)

                return True, None, variants

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []

async def search_barcode_across_shopify_stores(
    stores: List[Dict[str, Any]],
    barcode: str
) -> List[Dict[str, Any]]:
    """
    Search for a barcode across multiple Shopify stores in parallel.

    Args:
        stores: List of store dictionaries with keys: id, name, shop_domain, admin_api_key, api_version
        barcode: UPC/barcode to search for

    Returns:
        List of ProductVariantMatch dictionaries
    """
    async def search_single_store(store: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search a single store and return formatted results."""
        success, error, variants = await search_products_by_barcode(
            shop_domain=store["shop_domain"],
            admin_api_key=store["admin_api_key"],
            barcode=barcode,
            api_version=store.get("api_version", "2025-01")
        )

        if not success:
            # Log error but don't fail entire search
            print(f"Error searching store {store['name']}: {error}")
            return []

        # Format results
        results = []
        for variant in variants:
            results.append({
                "store_id": store["id"],
                "store_name": store["name"],
                "store_type": "shopify",
                "product_id": variant["product_id"],
                "product_title": variant["product_title"],
                "variant_id": variant["variant_id"],
                "variant_title": variant["variant_title"],
                "current_barcode": variant["barcode"],
                "sku": variant["sku"]
            })

        return results

    # Search all stores in parallel
    tasks = [search_single_store(store) for store in stores]
    results_list = await asyncio.gather(*tasks)

    # Flatten results
    all_results = []
    for results in results_list:
        all_results.extend(results)

    return all_results

async def update_barcodes_for_product(
    shop_domain: str,
    admin_api_key: str,
    product_id: str,
    variant_updates: List[Dict[str, str]],
    api_version: str = "2025-01",
    update_sku: bool = False
) -> tuple[bool, Optional[str], int]:
    """
    Update barcodes for multiple variants of a single product using GraphQL bulk update.
    Optionally also updates SKU to match barcode value.

    Args:
        shop_domain: Shop domain (e.g., mystore.myshopify.com)
        admin_api_key: Shopify Admin API access token
        product_id: Product GID (e.g., gid://shopify/Product/123)
        variant_updates: List of dicts with 'id' (variant GID) and 'barcode' (new barcode)
        api_version: API version (e.g., 2025-01)
        update_sku: If True, also updates SKU to match barcode value

    Returns:
        Tuple of (success: bool, error_message: Optional[str], updated_count: int)
    """
    try:
        # Normalize shop domain
        shop_domain = validate_shop_domain(shop_domain)

        if update_sku:
            # Use REST API to update variants individually (supports both barcode and sku)
            updated_count = 0
            errors = []

            async with aiohttp.ClientSession() as session:
                for variant in variant_updates:
                    variant_id = variant["id"]
                    barcode_value = variant["barcode"]

                    # Extract numeric ID from GID
                    numeric_id = variant_id.split("/")[-1]

                    # REST API endpoint
                    url = f"https://{shop_domain}/admin/api/{api_version}/variants/{numeric_id}.json"
                    headers = {
                        "X-Shopify-Access-Token": admin_api_key,
                        "Content-Type": "application/json"
                    }

                    # Update both barcode and SKU
                    payload = {
                        "variant": {
                            "id": int(numeric_id),
                            "barcode": barcode_value,
                            "sku": barcode_value
                        }
                    }

                    async with session.put(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as response:
                        if response.status == 200:
                            updated_count += 1
                            print(f"DEBUG - Updated variant {variant_id} with barcode and SKU: {barcode_value}")
                        else:
                            error_text = await response.text()
                            error_msg = f"Variant {variant_id}: HTTP {response.status} - {error_text}"
                            errors.append(error_msg)
                            print(f"DEBUG - Error updating variant: {error_msg}")

            if errors:
                return False, "; ".join(errors), updated_count

            return True, None, updated_count

        else:
            # Use existing productVariantsBulkUpdate mutation (barcode only)
            mutation = """
            mutation updateVariantBarcodes($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
              productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                productVariants {
                  id
                  barcode
                }
                userErrors {
                  field
                  message
                }
              }
            }
            """

            # Build variants input array
            variants_input = []
            for variant in variant_updates:
                variants_input.append({
                    "id": variant["id"],
                    "barcode": variant["barcode"]
                })

            variables = {
                "productId": product_id,
                "variants": variants_input
            }

            url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
            headers = {
                "X-Shopify-Access-Token": admin_api_key,
                "Content-Type": "application/json"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json={"query": mutation, "variables": variables},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return False, f"HTTP {response.status}: {error_text}", 0

                    data = await response.json()

                    # Check for GraphQL errors
                    if "errors" in data:
                        errors = data["errors"]
                        error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                        return False, f"GraphQL errors: {error_msg}", 0

                    # Check for user errors
                    result = data.get("data", {}).get("productVariantsBulkUpdate", {})
                    user_errors = result.get("userErrors", [])

                    if user_errors:
                        error_msg = "; ".join([e.get("message", str(e)) for e in user_errors])
                        return False, f"Update errors: {error_msg}", 0

                    # Count successfully updated variants
                    updated_variants = result.get("productVariants", [])
                    updated_count = len(updated_variants)

                    return True, None, updated_count

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", 0

async def search_product_prices_by_barcode(
    shop_domain: str,
    admin_api_key: str,
    barcode: str,
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    try:
        shop_domain = validate_shop_domain(shop_domain)

        query = """
        query searchPricesByBarcode($query: String!) {
          productVariants(first: 100, query: $query) {
            edges {
              node {
                id
                barcode
                sku
                displayName
                title
                price
                inventoryItem {
                  id
                  unitCost { amount currencyCode }
                }
                product {
                  id
                  title
                  status
                }
              }
            }
          }
        }
        """

        variables = {
            "query": f"barcode:{barcode}"
        }

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return False, f"HTTP {response.status}: {error_text}", []

                data = await response.json()

                if "errors" in data:
                    errors = data["errors"]
                    error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                    return False, f"GraphQL errors: {error_msg}", []

                variants = []
                edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

                for edge in edges:
                    node = edge.get("node", {})
                    product = node.get("product", {})

                    if product.get("status") == "ACTIVE":
                        inventory_item = node.get("inventoryItem") or {}
                        unit_cost = inventory_item.get("unitCost") or {}

                        variants.append({
                            "variant_id": node.get("id"),
                            "product_id": product.get("id"),
                            "product_title": product.get("title"),
                            "variant_title": node.get("title") or "Default",
                            "display_name": node.get("displayName"),
                            "barcode": node.get("barcode"),
                            "sku": node.get("sku"),
                            "price": node.get("price"),
                            "cost": unit_cost.get("amount"),
                            "inventory_item_id": inventory_item.get("id"),
                        })

                return True, None, variants

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []


async def get_all_product_variant_prices(
    shop_domain: str,
    admin_api_key: str,
    product_id: str,
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    try:
        shop_domain = validate_shop_domain(shop_domain)

        query = """
        query getProductVariants($productId: ID!) {
          product(id: $productId) {
            id
            title
            status
            variants(first: 100) {
              edges {
                node {
                  id
                  barcode
                  sku
                  displayName
                  title
                  price
                  inventoryItem {
                    id
                    unitCost { amount currencyCode }
                  }
                }
              }
            }
          }
        }
        """

        variables = {"productId": product_id}

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return False, f"HTTP {response.status}: {error_text}", []

                data = await response.json()

                if "errors" in data:
                    errors = data["errors"]
                    error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                    return False, f"GraphQL errors: {error_msg}", []

                product = data.get("data", {}).get("product")
                if not product or product.get("status") != "ACTIVE":
                    return True, None, []

                variants = []
                edges = product.get("variants", {}).get("edges", [])

                for edge in edges:
                    node = edge.get("node", {})
                    inventory_item = node.get("inventoryItem") or {}
                    unit_cost = inventory_item.get("unitCost") or {}

                    variants.append({
                        "variant_id": node.get("id"),
                        "product_id": product.get("id"),
                        "product_title": product.get("title"),
                        "variant_title": node.get("title") or "Default",
                        "display_name": node.get("displayName"),
                        "barcode": node.get("barcode"),
                        "sku": node.get("sku"),
                        "price": node.get("price"),
                        "cost": unit_cost.get("amount"),
                        "inventory_item_id": inventory_item.get("id"),
                    })

                return True, None, variants

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []


async def search_product_prices_with_siblings(
    shop_domain: str,
    admin_api_key: str,
    barcodes: list[str],
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    try:
        shop_domain = validate_shop_domain(shop_domain)

        # Call 1: Search variants by barcode (lightweight — no nested product.variants)
        search_query = """
        query searchPricesByBarcodes($query: String!) {
          productVariants(first: 100, query: $query) {
            edges {
              node {
                id
                barcode
                sku
                displayName
                title
                price
                inventoryItem {
                  id
                  unitCost { amount currencyCode }
                }
                product {
                  id
                  title
                  status
                }
              }
            }
          }
        }
        """

        BATCH_SIZE = 50
        all_matched_variants = []
        unique_product_ids = {}

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            for batch_start in range(0, len(barcodes), BATCH_SIZE):
                batch = barcodes[batch_start:batch_start + BATCH_SIZE]

                if len(batch) == 1:
                    query_str = f"barcode:{batch[0]}"
                else:
                    or_parts = " OR ".join(f"barcode:{bc}" for bc in batch)
                    query_str = f"({or_parts})"

                variables = {"query": query_str}

                async with session.post(
                    url,
                    json={"query": search_query, "variables": variables},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return False, f"HTTP {response.status}: {error_text}", [], {}

                    data = await response.json()

                    if "errors" in data:
                        errors = data["errors"]
                        error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                        return False, f"GraphQL errors: {error_msg}", [], {}

                    edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

                    for edge in edges:
                        node = edge.get("node", {})
                        product = node.get("product", {})

                        if product.get("status") != "ACTIVE":
                            continue

                        inventory_item = node.get("inventoryItem") or {}
                        unit_cost = inventory_item.get("unitCost") or {}
                        product_id = product.get("id")

                        matched_variant = {
                            "variant_id": node.get("id"),
                            "product_id": product_id,
                            "product_title": product.get("title"),
                            "variant_title": node.get("title") or "Default",
                            "display_name": node.get("displayName"),
                            "barcode": node.get("barcode"),
                            "sku": node.get("sku"),
                            "price": node.get("price"),
                            "cost": unit_cost.get("amount"),
                            "inventory_item_id": inventory_item.get("id"),
                        }
                        all_matched_variants.append(matched_variant)

                        if product_id:
                            unique_product_ids[product_id] = product.get("title")

            if not all_matched_variants:
                return True, None, [], {}

            # Call 2: Batch-fetch all variants for each unique product using aliases
            variants_by_product_id: Dict[str, List[Dict[str, Any]]] = {}
            product_id_list = list(unique_product_ids.keys())
            PRODUCTS_PER_QUERY = 8

            for chunk_start in range(0, len(product_id_list), PRODUCTS_PER_QUERY):
                chunk = product_id_list[chunk_start:chunk_start + PRODUCTS_PER_QUERY]

                alias_parts = []
                for i, pid in enumerate(chunk):
                    alias_parts.append(f"""
                        p{i}: product(id: "{pid}") {{
                            id
                            title
                            status
                            variants(first: 100) {{
                                edges {{
                                    node {{
                                        id
                                        barcode
                                        sku
                                        displayName
                                        title
                                        price
                                        inventoryItem {{
                                            id
                                            unitCost {{ amount currencyCode }}
                                        }}
                                    }}
                                }}
                            }}
                        }}
                    """)

                alias_query = "query {\n" + "\n".join(alias_parts) + "\n}"

                async with session.post(
                    url,
                    json={"query": alias_query},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        continue

                    data = await response.json()

                    if "errors" in data:
                        continue

                    query_data = data.get("data", {})

                    for i, pid in enumerate(chunk):
                        product = query_data.get(f"p{i}")
                        if not product or product.get("status") != "ACTIVE":
                            continue

                        product_title = product.get("title")
                        product_variants = []
                        prod_edges = product.get("variants", {}).get("edges", [])

                        for prod_edge in prod_edges:
                            pv_node = prod_edge.get("node", {})
                            pv_inv = pv_node.get("inventoryItem") or {}
                            pv_cost = pv_inv.get("unitCost") or {}
                            product_variants.append({
                                "variant_id": pv_node.get("id"),
                                "product_id": pid,
                                "product_title": product_title,
                                "variant_title": pv_node.get("title") or "Default",
                                "display_name": pv_node.get("displayName"),
                                "barcode": pv_node.get("barcode"),
                                "sku": pv_node.get("sku"),
                                "price": pv_node.get("price"),
                                "cost": pv_cost.get("amount"),
                                "inventory_item_id": pv_inv.get("id"),
                            })

                        variants_by_product_id[pid] = product_variants

        return True, None, all_matched_variants, variants_by_product_id

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", [], {}
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", [], {}


async def update_variant_prices(
    shop_domain: str,
    admin_api_key: str,
    product_id: str,
    variant_updates: List[Dict[str, Any]],
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], int]:
    try:
        shop_domain = validate_shop_domain(shop_domain)

        mutation = """
        mutation updateVariantPrices($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
          productVariantsBulkUpdate(productId: $productId, variants: $variants) {
            productVariants {
              id
              price
            }
            userErrors { field message }
          }
        }
        """

        variants_input = []
        for v in variant_updates:
            variant_input = {"id": v["variant_id"]}
            if v.get("new_price") is not None:
                variant_input["price"] = str(v["new_price"])
            if v.get("new_cost") is not None:
                variant_input["inventoryItem"] = {"cost": float(v["new_cost"])}
            variants_input.append(variant_input)

        variables = {
            "productId": product_id,
            "variants": variants_input
        }

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        max_retries = 3
        backoff_seconds = [1, 2, 4]

        async with aiohttp.ClientSession() as session:
            for attempt in range(max_retries + 1):
                async with session.post(
                    url,
                    json={"query": mutation, "variables": variables},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 429:
                        if attempt < max_retries:
                            await asyncio.sleep(backoff_seconds[attempt])
                            continue
                        return False, "Shopify rate limit exceeded after retries", 0

                    if response.status != 200:
                        error_text = await response.text()
                        return False, f"HTTP {response.status}: {error_text}", 0

                    data = await response.json()

                    if "errors" in data:
                        errors = data["errors"]
                        error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                        if "throttl" in error_msg.lower() and attempt < max_retries:
                            await asyncio.sleep(backoff_seconds[attempt])
                            continue
                        return False, f"GraphQL errors: {error_msg}", 0

                    result = data.get("data", {}).get("productVariantsBulkUpdate", {})
                    user_errors = result.get("userErrors", [])

                    if user_errors:
                        error_msg = "; ".join([e.get("message", str(e)) for e in user_errors])
                        return False, f"Update errors: {error_msg}", 0

                    updated_variants = result.get("productVariants", [])
                    return True, None, len(updated_variants)

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", 0


async def fetch_fulfilled_orders(
    shop_domain: str,
    admin_api_key: str,
    start_date: str,
    end_date: str,
    api_version: str = "2025-01"
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    try:
        shop_domain = validate_shop_domain(shop_domain)

        query_gql = """
        query fetchFulfilledOrders($query: String!, $first: Int!, $after: String) {
          orders(first: $first, after: $after, query: $query) {
            pageInfo {
              hasNextPage
              endCursor
            }
            edges {
              node {
                id
                name
                totalShippingPriceSet {
                  shopMoney {
                    amount
                    currencyCode
                  }
                }
                fulfillments(first: 10) {
                  createdAt
                  status
                }
                lineItems(first: 100) {
                  edges {
                    node {
                      title
                      quantity
                      currentQuantity
                      variantTitle
                      sku
                      originalUnitPriceSet {
                        shopMoney {
                          amount
                          currencyCode
                        }
                      }
                      discountedUnitPriceSet {
                        shopMoney {
                          amount
                          currencyCode
                        }
                      }
                      variant {
                        barcode
                        title
                        product {
                          title
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        query_filter = f"fulfillment_status:shipped updated_at:>={start_date} updated_at:<={end_date}"
        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json"
        }

        all_line_items = []
        has_next_page = True
        cursor = None
        max_retries = 3
        backoff_seconds = [1, 2, 4]

        async with aiohttp.ClientSession() as session:
            while has_next_page:
                variables = {
                    "query": query_filter,
                    "first": 250,
                }
                if cursor:
                    variables["after"] = cursor

                response_data = None
                for attempt in range(max_retries + 1):
                    async with session.post(
                        url,
                        json={"query": query_gql, "variables": variables},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60)
                    ) as response:
                        if response.status == 429:
                            if attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, "Shopify rate limit exceeded after retries", []

                        if response.status != 200:
                            error_text = await response.text()
                            return False, f"HTTP {response.status}: {error_text}", []

                        response_data = await response.json()

                        if "errors" in response_data:
                            errors = response_data["errors"]
                            error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                            if "throttl" in error_msg.lower() and attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, f"GraphQL errors: {error_msg}", []

                        break

                if not response_data:
                    return False, "No response received", []

                orders_data = response_data.get("data", {}).get("orders", {})
                page_info = orders_data.get("pageInfo", {})
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")

                from datetime import datetime as dt

                for edge in orders_data.get("edges", []):
                    order = edge.get("node", {})
                    order_name = order.get("name", "")

                    fulfillments = order.get("fulfillments", [])
                    fulfillment_in_range = False
                    for f in fulfillments:
                        if f.get("status") != "SUCCESS":
                            continue
                        created_at = f.get("createdAt", "")
                        if created_at:
                            f_date = created_at[:10]
                            if start_date <= f_date <= end_date:
                                fulfillment_in_range = True
                                break

                    if not fulfillment_in_range:
                        continue

                    shipping_price_set = order.get("totalShippingPriceSet") or {}
                    shipping_money = shipping_price_set.get("shopMoney") or {}
                    shipping_amount = shipping_money.get("amount", "0")

                    for li_edge in order.get("lineItems", {}).get("edges", []):
                        li = li_edge.get("node", {})
                        quantity = li.get("currentQuantity", 0) or li.get("quantity", 0)
                        if quantity <= 0:
                            continue

                        variant = li.get("variant") or {}
                        product = variant.get("product") or {}

                        product_title = product.get("title") or li.get("title", "")
                        variant_title = variant.get("title") or li.get("variantTitle") or "Default Title"

                        price_set = li.get("discountedUnitPriceSet") or li.get("originalUnitPriceSet") or {}
                        shop_money = price_set.get("shopMoney") or {}
                        unit_price = shop_money.get("amount", "0")
                        currency = shop_money.get("currencyCode", "USD")

                        all_line_items.append({
                            "order_name": order_name,
                            "product_title": product_title,
                            "variant_title": variant_title,
                            "barcode": variant.get("barcode") or "",
                            "sku": li.get("sku") or "",
                            "quantity": quantity,
                            "unit_price": unit_price,
                            "currency": currency,
                            "shipping_amount": shipping_amount
                        })

        return True, None, all_line_items

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []


async def update_barcodes_across_shopify_stores(
    store_updates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Update barcodes across multiple Shopify stores in parallel.

    Args:
        store_updates: List of dicts with:
            - store_id: int
            - store_name: str
            - shop_domain: str
            - admin_api_key: str
            - api_version: str
            - update_sku: bool (optional, defaults to False)
            - products: List of dicts with:
                - product_id: str (GID)
                - variants: List of dicts with 'id' (variant GID) and 'barcode' (new barcode)

    Returns:
        List of update result dictionaries with store_id, store_name, success, updated_count, error
    """
    async def update_single_store(store_update: Dict[str, Any]) -> Dict[str, Any]:
        """Update barcodes in a single store."""
        total_updated = 0
        errors = []

        # Get update_sku setting for this store (default to False)
        update_sku = store_update.get("update_sku", False)

        # Update each product's variants
        for product in store_update.get("products", []):
            success, error, count = await update_barcodes_for_product(
                shop_domain=store_update["shop_domain"],
                admin_api_key=store_update["admin_api_key"],
                product_id=product["product_id"],
                variant_updates=product["variants"],
                api_version=store_update.get("api_version", "2025-01"),
                update_sku=update_sku
            )

            if success:
                total_updated += count
            else:
                errors.append(f"Product {product['product_id']}: {error}")

        # Return result
        return {
            "store_id": store_update["store_id"],
            "store_name": store_update["store_name"],
            "success": len(errors) == 0,
            "updated_count": total_updated,
            "error": "; ".join(errors) if errors else None
        }

    # Update all stores in parallel
    tasks = [update_single_store(store_update) for store_update in store_updates]
    results = await asyncio.gather(*tasks)

    return results


async def fetch_orders_with_tag(
    shop_domain: str,
    admin_api_key: str,
    start_date: str,
    end_date: str,
    tag: str,
    api_version: str = "2025-01",
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Fetch orders matching a tag within a created_at date range.

    Returns a list of normalized order dicts with: id, name, processed_at,
    created_at, total_amount, currency, customer_id, customer_email,
    customer_first_name, customer_last_name.
    """
    try:
        shop_domain = validate_shop_domain(shop_domain)

        query_gql = """
        query fetchTaggedOrders($query: String!, $first: Int!, $after: String) {
          orders(first: $first, after: $after, query: $query) {
            pageInfo { hasNextPage endCursor }
            edges {
              node {
                id
                name
                createdAt
                processedAt
                totalPriceSet { shopMoney { amount currencyCode } }
                customer { id email firstName lastName }
              }
            }
          }
        }
        """

        safe_tag = (tag or "").replace('"', '\\"')
        query_filter = f'tag:"{safe_tag}" created_at:>={start_date} created_at:<={end_date}'

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json",
        }

        results: List[Dict[str, Any]] = []
        has_next_page = True
        cursor: Optional[str] = None
        max_retries = 3
        backoff_seconds = [1, 2, 4]

        async with aiohttp.ClientSession() as session:
            while has_next_page:
                variables: Dict[str, Any] = {"query": query_filter, "first": 250}
                if cursor:
                    variables["after"] = cursor

                response_data = None
                for attempt in range(max_retries + 1):
                    async with session.post(
                        url,
                        json={"query": query_gql, "variables": variables},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status == 429:
                            if attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, "Shopify rate limit exceeded after retries", []

                        if response.status != 200:
                            error_text = await response.text()
                            return False, f"HTTP {response.status}: {error_text}", []

                        response_data = await response.json()

                        if "errors" in response_data:
                            errors = response_data["errors"]
                            error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                            if "throttl" in error_msg.lower() and attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, f"GraphQL errors: {error_msg}", []

                        break

                if not response_data:
                    return False, "No response received", []

                orders_data = response_data.get("data", {}).get("orders", {}) or {}
                page_info = orders_data.get("pageInfo", {}) or {}
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")

                for edge in orders_data.get("edges", []) or []:
                    order = edge.get("node") or {}
                    total_set = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
                    customer = order.get("customer") or {}
                    results.append({
                        "id": order.get("id"),
                        "name": order.get("name", ""),
                        "created_at": order.get("createdAt"),
                        "processed_at": order.get("processedAt"),
                        "total_amount": total_set.get("amount", "0"),
                        "currency": total_set.get("currencyCode", "USD"),
                        "customer_id": customer.get("id"),
                        "customer_email": customer.get("email"),
                        "customer_first_name": customer.get("firstName"),
                        "customer_last_name": customer.get("lastName"),
                    })

        return True, None, results

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []


async def fetch_customer_orders_after(
    shop_domain: str,
    admin_api_key: str,
    customer_id: str,
    after_date_iso: str,
    api_version: str = "2025-01",
) -> tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """
    Fetch all orders for a customer placed strictly after the given ISO datetime.

    Returns normalized order dicts including status fields needed to apply
    a "successful order" filter at the call site:
        id, name, processed_at, created_at, cancelled_at,
        display_financial_status, total_amount, currency,
        has_tracking (bool — at least one fulfillment with a non-empty tracking number).

    The Shopify search index uses date precision (not full datetime), so we
    pass a YYYY-MM-DD prefix and let the caller drop ties via after_date_iso
    if precise ordering matters.
    """
    try:
        shop_domain = validate_shop_domain(shop_domain)

        # Extract Shopify customer numeric ID from gid if necessary
        cid = (customer_id or "").rsplit("/", 1)[-1]

        # Shopify's `created_at:>` filter is date-resolution; use date prefix.
        after_date = (after_date_iso or "")[:10]
        if not after_date:
            return False, "Missing after_date_iso", []

        query_gql = """
        query fetchCustomerOrders($query: String!, $first: Int!, $after: String) {
          orders(first: $first, after: $after, query: $query) {
            pageInfo { hasNextPage endCursor }
            edges {
              node {
                id
                name
                createdAt
                processedAt
                cancelledAt
                displayFinancialStatus
                totalPriceSet { shopMoney { amount currencyCode } }
                fulfillments(first: 20) {
                  trackingInfo { number }
                }
              }
            }
          }
        }
        """

        query_filter = f"customer_id:{cid} created_at:>={after_date}"

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json",
        }

        results: List[Dict[str, Any]] = []
        has_next_page = True
        cursor: Optional[str] = None
        max_retries = 3
        backoff_seconds = [1, 2, 4]

        async with aiohttp.ClientSession() as session:
            while has_next_page:
                variables: Dict[str, Any] = {"query": query_filter, "first": 100}
                if cursor:
                    variables["after"] = cursor

                response_data = None
                for attempt in range(max_retries + 1):
                    async with session.post(
                        url,
                        json={"query": query_gql, "variables": variables},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status == 429:
                            if attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, "Shopify rate limit exceeded after retries", []

                        if response.status != 200:
                            error_text = await response.text()
                            return False, f"HTTP {response.status}: {error_text}", []

                        response_data = await response.json()

                        if "errors" in response_data:
                            errors = response_data["errors"]
                            error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                            if "throttl" in error_msg.lower() and attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, f"GraphQL errors: {error_msg}", []

                        break

                if not response_data:
                    return False, "No response received", []

                orders_data = response_data.get("data", {}).get("orders", {}) or {}
                page_info = orders_data.get("pageInfo", {}) or {}
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")

                for edge in orders_data.get("edges", []) or []:
                    order = edge.get("node") or {}
                    total_set = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
                    has_tracking = False
                    for f in order.get("fulfillments") or []:
                        for t in f.get("trackingInfo") or []:
                            if (t or {}).get("number"):
                                has_tracking = True
                                break
                        if has_tracking:
                            break
                    results.append({
                        "id": order.get("id"),
                        "name": order.get("name", ""),
                        "created_at": order.get("createdAt"),
                        "processed_at": order.get("processedAt"),
                        "cancelled_at": order.get("cancelledAt"),
                        "display_financial_status": order.get("displayFinancialStatus"),
                        "total_amount": total_set.get("amount", "0"),
                        "currency": total_set.get("currencyCode", "USD"),
                        "has_tracking": has_tracking,
                    })

        return True, None, results

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []


async def count_orders(
    shop_domain: str,
    admin_api_key: str,
    query: str,
    api_version: str = "2025-01",
) -> tuple[bool, Optional[str], Optional[int]]:
    """
    Return the number of orders matching a Shopify search query, using the
    lightweight `ordersCount` query (no order pagination).

    Below Shopify's default 10k cap the returned count is exact
    (precision == "EXACT"); fulfillment backlogs are far smaller, so this is
    reliable. Returns (True, None, count) on success, (False, error, None) otherwise.
    """
    try:
        shop_domain = validate_shop_domain(shop_domain)

        query_gql = """
        query OrdersFulfillmentCount($q: String!) {
          ordersCount(query: $q) { count precision }
        }
        """

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json",
        }

        max_retries = 3
        backoff_seconds = [1, 2, 4]

        async with aiohttp.ClientSession() as session:
            response_data = None
            for attempt in range(max_retries + 1):
                async with session.post(
                    url,
                    json={"query": query_gql, "variables": {"q": query}},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status == 429:
                        if attempt < max_retries:
                            await asyncio.sleep(backoff_seconds[attempt])
                            continue
                        return False, "Shopify rate limit exceeded after retries", None

                    if response.status != 200:
                        error_text = await response.text()
                        return False, f"HTTP {response.status}: {error_text}", None

                    response_data = await response.json()

                    if "errors" in response_data:
                        errors = response_data["errors"]
                        error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                        if "throttl" in error_msg.lower() and attempt < max_retries:
                            await asyncio.sleep(backoff_seconds[attempt])
                            continue
                        return False, f"GraphQL errors: {error_msg}", None

                    break

            if not response_data:
                return False, "No response received", None

            orders_count = (response_data.get("data", {}) or {}).get("ordersCount", {}) or {}
            count = orders_count.get("count")
            if count is None:
                return False, "ordersCount returned no count", None

            return True, None, int(count)

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", None
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", None


_OPEN_QUERY = "status:open"
_UNFULFILLED_OPEN_QUERY = "status:open AND fulfillment_status:unfulfilled"
_ON_HOLD_OPEN_QUERY = "status:open AND fulfillment_status:on_hold"
_CHECKED_TAG = "checked"
_PICKLIST_TAG_PREFIX = "picklist"


async def fetch_unfulfilled_order_tags(
    shop_domain: str,
    admin_api_key: str,
    api_version: str = "2025-01",
) -> tuple[bool, Optional[str], List[List[str]]]:
    """
    Fetch tags for every open, unfulfilled order (cursor-paginated).

    Returns (True, None, list_of_tag_lists). We fetch tags in Python rather than
    counting server-side because Shopify's order search does NOT support a
    trailing-wildcard tag match (`tag:picklist*` matches nothing), so the
    "picklist" prefix bucket can only be computed by inspecting each order's tags.
    The working set is bounded (the open unfulfilled backlog).
    """
    try:
        shop_domain = validate_shop_domain(shop_domain)

        query_gql = """
        query fetchUnfulfilledTags($query: String!, $first: Int!, $after: String) {
          orders(first: $first, after: $after, query: $query) {
            pageInfo { hasNextPage endCursor }
            edges { node { id tags } }
          }
        }
        """

        url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
        headers = {
            "X-Shopify-Access-Token": admin_api_key,
            "Content-Type": "application/json",
        }

        results: List[List[str]] = []
        has_next_page = True
        cursor: Optional[str] = None
        max_retries = 3
        backoff_seconds = [1, 2, 4]

        async with aiohttp.ClientSession() as session:
            while has_next_page:
                variables: Dict[str, Any] = {"query": _UNFULFILLED_OPEN_QUERY, "first": 250}
                if cursor:
                    variables["after"] = cursor

                response_data = None
                for attempt in range(max_retries + 1):
                    async with session.post(
                        url,
                        json={"query": query_gql, "variables": variables},
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status == 429:
                            if attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, "Shopify rate limit exceeded after retries", []

                        if response.status != 200:
                            error_text = await response.text()
                            return False, f"HTTP {response.status}: {error_text}", []

                        response_data = await response.json()

                        if "errors" in response_data:
                            errors = response_data["errors"]
                            error_msg = "; ".join([e.get("message", str(e)) for e in errors])
                            if "throttl" in error_msg.lower() and attempt < max_retries:
                                await asyncio.sleep(backoff_seconds[attempt])
                                continue
                            return False, f"GraphQL errors: {error_msg}", []

                        break

                if not response_data:
                    return False, "No response received", []

                orders_data = response_data.get("data", {}).get("orders", {}) or {}
                page_info = orders_data.get("pageInfo", {}) or {}
                has_next_page = page_info.get("hasNextPage", False)
                cursor = page_info.get("endCursor")

                for edge in orders_data.get("edges", []) or []:
                    order = edge.get("node") or {}
                    results.append(order.get("tags") or [])

        return True, None, results

    except aiohttp.ClientError as e:
        return False, f"Network error: {str(e)}", []
    except Exception as e:
        return False, f"Unexpected error: {str(e)}", []


async def count_fulfillment_buckets_for_store(
    store: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute the three fulfillment buckets for one Shopify store.

    `store` is a dict with keys: id, name, shop_domain, admin_api_key, api_version.
    Returns a row dict {store_id, store_name, in_process, on_picklist, to_fulfill, error}.
    On failure the counts are left None and `error` is set, so one bad store never
    fails the whole table.

    Columns (all over open orders):
      - open_orders = all open orders (any fulfillment status)
      - on_hold     = fulfillment status on hold
      - in_process  = unfulfilled AND tagged "checked"
      - on_picklist = unfulfilled AND a tag starts with "picklist" AND NOT tagged "checked"
      - to_fulfill  = total_unfulfilled + on_hold - in_process - on_picklist
                      (untouched backlog: neither already checked nor on a picklist)

    in_process / on_picklist / total_unfulfilled are derived from one paginated
    fetch of the open unfulfilled orders' tags; on_hold and open_orders are each
    a single ordersCount.
    """
    row: Dict[str, Any] = {
        "store_id": store["id"],
        "store_name": store["name"],
        "open_orders": None,
        "on_hold": None,
        "in_process": None,
        "on_picklist": None,
        "to_fulfill": None,
        "error": None,
    }

    sd = store["shop_domain"]
    key = store["admin_api_key"]
    ver = store.get("api_version", "2025-01")

    tags_result, hold_result, open_result = await asyncio.gather(
        fetch_unfulfilled_order_tags(sd, key, ver),
        count_orders(sd, key, _ON_HOLD_OPEN_QUERY, ver),
        count_orders(sd, key, _OPEN_QUERY, ver),
    )

    tags_ok, tags_err, order_tag_lists = tags_result
    hold_ok, hold_err, on_hold = hold_result
    open_ok, open_err, open_orders = open_result

    if not tags_ok:
        row["error"] = tags_err or "Unknown error"
        return row
    if not hold_ok:
        row["error"] = hold_err or "Unknown error"
        return row
    if not open_ok:
        row["error"] = open_err or "Unknown error"
        return row

    total_unfulfilled = len(order_tag_lists)
    in_process = 0
    on_picklist = 0
    for tags in order_tag_lists:
        lowered = [t.strip().lower() for t in tags]
        has_checked = _CHECKED_TAG in lowered
        if has_checked:
            in_process += 1
        elif any(t.startswith(_PICKLIST_TAG_PREFIX) for t in lowered):
            on_picklist += 1

    row["open_orders"] = open_orders
    row["on_hold"] = on_hold
    row["in_process"] = in_process
    row["on_picklist"] = on_picklist
    row["to_fulfill"] = total_unfulfilled + on_hold - in_process - on_picklist
    return row


# ============================================================================
# Shared GraphQL executor: rate limiting, retries, and honest failures
#
# Every request from the lost-customers report goes through _shopify_graphql.
# The older helpers above keep their own inline retry loops (unchanged, out of
# scope) — this is the single implementation new code should use.
# ============================================================================

# Retry ceiling. Transient classes only; see _classify_response.
_MAX_ATTEMPTS = 5
_MAX_BACKOFF_SECONDS = 30.0

# Fraction of the shop's bucket to keep in reserve. Below this we wait for the
# leaky bucket to refill rather than gambling on a 429.
_BUCKET_SAFETY_FLOOR = 0.20

# Cost assumed for the first request to a shop, before any throttleStatus has
# been observed. A 250-record page with nested fulfillments measured 57.
_ASSUMED_QUERY_COST = 60.0


class ShopifyFetchError(Exception):
    """
    Raised when a request cannot be completed.

    Carries enough context for the UI to tell the user what actually went wrong
    instead of showing an empty result that looks like "no data".
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        attempts: int = 1,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.attempts = attempts
        self.retryable = retryable

    def __str__(self) -> str:
        bits = [self.message]
        if self.status:
            bits.append(f"HTTP {self.status}")
        if self.attempts > 1:
            bits.append(f"after {self.attempts} attempts")
        return " — ".join(bits)


def _parse_graphql_errors(errors: Any) -> str:
    """
    Normalize Shopify's `errors` payload to a readable string.

    Shopify is not consistent about the shape: a 401 returns a bare string
    ("[API] Invalid API key..."), while query errors return a list of dicts.
    Iterating a string yields characters, so the usual
    `"; ".join(e.get("message") for e in errors)` raises AttributeError and the
    real cause gets buried under a confusing type error.
    """
    if errors is None:
        return ""
    if isinstance(errors, str):
        return errors
    if isinstance(errors, dict):
        return str(errors.get("message") or errors)
    if isinstance(errors, list):
        out = []
        for e in errors:
            if isinstance(e, dict):
                out.append(str(e.get("message") or e))
            else:
                out.append(str(e))
        return "; ".join(out)
    return str(errors)


def _is_throttled(errors: Any) -> bool:
    if isinstance(errors, list):
        for e in errors:
            if isinstance(e, dict):
                code = ((e.get("extensions") or {}).get("code") or "")
                if str(code).upper() == "THROTTLED":
                    return True
    return "throttl" in _parse_graphql_errors(errors).lower()


class _ShopBucket:
    """
    Mirror of one shop's leaky bucket, shared by every concurrent request to
    that shop — Shopify meters per shop, not per connection, so the shards of a
    single store must draw from one budget or they will throttle each other.

    Capacity and restore rate are learned from `extensions.cost.throttleStatus`
    rather than hardcoded: the observed values here (20000 / 1000 per second)
    are far above the documented standard-plan figures, the public docs
    contradict themselves, and it varies by plan.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.maximum = 0.0
        self.available = 0.0
        self.restore_rate = 0.0
        self.last_update = 0.0
        self.last_cost = _ASSUMED_QUERY_COST

    def _projected_available(self) -> float:
        if self.maximum <= 0:
            return 0.0
        elapsed = max(0.0, time.monotonic() - self.last_update)
        return min(self.maximum, self.available + elapsed * self.restore_rate)

    async def acquire(self) -> None:
        """Wait until the shop's bucket can absorb another query of typical cost."""
        async with self._lock:
            if self.maximum <= 0 or self.restore_rate <= 0:
                return  # nothing observed yet; the first response teaches us
            need = max(self.last_cost, _ASSUMED_QUERY_COST)
            floor = self.maximum * _BUCKET_SAFETY_FLOOR
            projected = self._projected_available()
            if projected >= need + floor:
                return
            deficit = (need + floor) - projected
            await asyncio.sleep(min(_MAX_BACKOFF_SECONDS, deficit / self.restore_rate))

    def observe(self, cost: Optional[Dict[str, Any]]) -> None:
        if not cost:
            return
        throttle = cost.get("throttleStatus") or {}
        try:
            self.maximum = float(throttle.get("maximumAvailable") or self.maximum)
            self.available = float(throttle.get("currentlyAvailable") or 0.0)
            self.restore_rate = float(throttle.get("restoreRate") or self.restore_rate)
            self.last_cost = float(cost.get("actualQueryCost") or self.last_cost)
            self.last_update = time.monotonic()
        except (TypeError, ValueError):
            pass


_shop_buckets: Dict[str, _ShopBucket] = {}


def _bucket_for(shop_domain: str) -> _ShopBucket:
    bucket = _shop_buckets.get(shop_domain)
    if bucket is None:
        bucket = _ShopBucket()
        _shop_buckets[shop_domain] = bucket
    return bucket


def _backoff_delay(attempt: int, retry_after: Optional[str]) -> float:
    """
    Exponential backoff with full jitter.

    Jitter is not cosmetic here: ~20 concurrent paginations that all get
    throttled would otherwise wake in lockstep and immediately re-throttle.
    """
    if retry_after:
        try:
            return min(_MAX_BACKOFF_SECONDS, float(retry_after))
        except (TypeError, ValueError):
            pass
    return random.uniform(0.0, min(_MAX_BACKOFF_SECONDS, 2.0 ** attempt))


async def _shopify_graphql(
    session: aiohttp.ClientSession,
    shop_domain: str,
    admin_api_key: str,
    api_version: str,
    query: str,
    variables: Optional[Dict[str, Any]] = None,
    *,
    op_name: str = "query",
    on_retry=None,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Execute one GraphQL request against a shop, with pacing and retries.

    Returns (data, warnings). Raises ShopifyFetchError when the request cannot
    be completed — callers must handle it rather than treating a failure as an
    empty result, which is the whole point of this report.

    `on_retry(attempt, max_attempts, reason)` is an optional callback so the UI
    can show "retrying (2/5) after rate limit" instead of appearing to hang.
    """
    url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
    headers = {
        "X-Shopify-Access-Token": admin_api_key,
        "Content-Type": "application/json",
    }
    bucket = _bucket_for(shop_domain)
    payload = {"query": query, "variables": variables or {}}
    last_reason = "unknown error"

    for attempt in range(_MAX_ATTEMPTS):
        await bucket.acquire()

        try:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=90),
            ) as response:
                status = response.status

                # --- Permanent failures: retrying cannot help, and retrying
                # would only bury the real cause behind five round trips.
                if status in (401, 403):
                    body = await response.text()
                    raise ShopifyFetchError(
                        f"Authentication failed for {shop_domain} — check the "
                        f"Admin API token. {body[:200]}",
                        status=status,
                        code="AUTH",
                        attempts=attempt + 1,
                    )
                if status == 404:
                    raise ShopifyFetchError(
                        f"Shop or API version not found ({shop_domain}, {api_version})",
                        status=status,
                        code="NOT_FOUND",
                        attempts=attempt + 1,
                    )

                # --- Transient: rate limited.
                if status == 429:
                    last_reason = "rate limited (HTTP 429)"
                    if attempt < _MAX_ATTEMPTS - 1:
                        if on_retry:
                            on_retry(attempt + 1, _MAX_ATTEMPTS, last_reason)
                        await asyncio.sleep(
                            _backoff_delay(attempt, response.headers.get("Retry-After"))
                        )
                        continue
                    raise ShopifyFetchError(
                        f"Still rate limited by {shop_domain}",
                        status=status,
                        code="THROTTLED",
                        attempts=attempt + 1,
                        retryable=True,
                    )

                # --- Transient: server-side wobble.
                if status >= 500:
                    last_reason = f"server error (HTTP {status})"
                    if attempt < _MAX_ATTEMPTS - 1:
                        if on_retry:
                            on_retry(attempt + 1, _MAX_ATTEMPTS, last_reason)
                        await asyncio.sleep(_backoff_delay(attempt, None))
                        continue
                    raise ShopifyFetchError(
                        f"Shopify returned HTTP {status} for {shop_domain}",
                        status=status,
                        code="SERVER",
                        attempts=attempt + 1,
                        retryable=True,
                    )

                if status != 200:
                    body = await response.text()
                    raise ShopifyFetchError(
                        f"Unexpected HTTP {status} from {shop_domain}: {body[:200]}",
                        status=status,
                        attempts=attempt + 1,
                    )

                body = await response.json()

        except ShopifyFetchError:
            raise
        except asyncio.CancelledError:
            # A cancelled report must stop calling Shopify immediately.
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_reason = f"network error ({type(e).__name__})"
            if attempt < _MAX_ATTEMPTS - 1:
                if on_retry:
                    on_retry(attempt + 1, _MAX_ATTEMPTS, last_reason)
                await asyncio.sleep(_backoff_delay(attempt, None))
                continue
            raise ShopifyFetchError(
                f"Could not reach {shop_domain}: {e}",
                code="NETWORK",
                attempts=attempt + 1,
                retryable=True,
            )

        bucket.observe(body.get("extensions", {}).get("cost"))

        errors = body.get("errors")
        data = body.get("data")

        if errors and _is_throttled(errors):
            last_reason = "throttled by Shopify"
            if attempt < _MAX_ATTEMPTS - 1:
                if on_retry:
                    on_retry(attempt + 1, _MAX_ATTEMPTS, last_reason)
                # Wait for the bucket to actually refill rather than a blind sleep.
                deficit = max(0.0, bucket.maximum * _BUCKET_SAFETY_FLOOR - bucket.available)
                wait = (
                    deficit / bucket.restore_rate
                    if bucket.restore_rate > 0
                    else _backoff_delay(attempt, None)
                )
                await asyncio.sleep(max(1.0, min(_MAX_BACKOFF_SECONDS, wait)))
                continue
            raise ShopifyFetchError(
                f"Throttled by {shop_domain} after retries",
                code="THROTTLED",
                attempts=attempt + 1,
                retryable=True,
            )

        # No data at all means the query itself is wrong — a code bug. Fail
        # loudly and immediately; retrying a malformed query is pure waste.
        if data is None:
            raise ShopifyFetchError(
                f"{op_name} failed: {_parse_graphql_errors(errors) or 'no data returned'}",
                code="QUERY",
                attempts=attempt + 1,
            )

        # Data present alongside errors = field-level denial (e.g. protected
        # customer data). The response is usable, but the caller must know the
        # result is not whole.
        warnings: List[str] = []
        if errors:
            warnings.append(_parse_graphql_errors(errors)[:300])

        return data, warnings

    raise ShopifyFetchError(
        f"{op_name} failed against {shop_domain}: {last_reason}",
        attempts=_MAX_ATTEMPTS,
        retryable=True,
    )


# ============================================================================
# Lost-customers report
# ============================================================================

_LOST_CUSTOMERS_QUERY = """
query LostCustomers($q: String!, $after: String) {
  customers(first: 250, query: $q, sortKey: ID, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      displayName
      email
      createdAt
      numberOfOrders
      amountSpent { amount currencyCode }
      lastOrder {
        id
        name
        createdAt
        displayFulfillmentStatus
        shippingLine { title carrierIdentifier }
        fulfillments(first: 5) {
          createdAt
          inTransitAt
          deliveredAt
          displayStatus
          trackingInfo { company number url }
        }
      }
    }
  }
}
"""

# Shopify refuses to paginate past 25,000 objects. Sharding keeps each cursor
# walk under that, but we still detect the ceiling so a truncated result can
# never be presented as a complete one.
_PAGINATION_OBJECT_CAP = 25000


def _normalize_carrier(name: Optional[str]) -> Optional[str]:
    """Carriers arrive as 'usps'/'USPS'/'ups'/'UPS' — collapse the casing."""
    if not name:
        return None
    return name.strip().upper() or None


def _normalize_shipping_method(title: Optional[str]) -> Optional[str]:
    """
    Group shipping-method variants that mean the same service.

    Observed on live stores: "Economy Shipping", "Economy Shipping 6-14
    Business Days" and "Economy Shipping (EST 6-14 Business Days)" are one
    service. Without this the breakdown fragments into near-duplicates.
    """
    if not title:
        return None
    import re

    t = title.strip().lower()
    t = re.sub(r"\(.*?\)", " ", t)              # drop parentheticals
    t = re.sub(r"\b(est|approx)\b", " ", t)
    t = re.sub(r"\d+\s*-\s*\d+", " ", t)        # "6-14"
    t = re.sub(r"\b(business\s+)?days?\b", " ", t)
    t = t.replace(":", " ")
    t = re.sub(r"\s+", " ", t).strip(" -–—")
    return (t or title.strip().lower()).title()


async def fetch_customers_with_last_order(
    shop_domain: str,
    admin_api_key: str,
    active_since: str,
    api_version: str = "2025-01",
    shard_start: Optional[str] = None,
    shard_end: Optional[str] = None,
    on_page=None,
    on_retry=None,
) -> Dict[str, Any]:
    """
    Page customers who ordered since `active_since`, carrying their last order's
    shipping and fulfillment timeline.

    `lastOrder` is a full Order, so the entire report's timing data comes from
    this one cheap pagination (~57 points/page) instead of a separate sweep of
    every order.

    Lost is NOT decided here. Shopify's `order_date` filter has any-order
    semantics and negating it does not invert that — verified against live
    stores, where every negated form still returned 12% customers who had
    ordered after the cutoff. The caller classifies on `last_order_created_at`.

    Returns {ok, complete, incomplete_reason, error, customers[], warnings[], pages}.
    """
    result: Dict[str, Any] = {
        "ok": False,
        "complete": False,
        "incomplete_reason": None,
        "error": None,
        "customers": [],
        "warnings": [],
        "pages": 0,
    }

    try:
        shop_domain = validate_shop_domain(shop_domain)
    except Exception as e:
        result["error"] = str(e)
        return result

    query_filter = f"order_date:>={shard_start or active_since}"
    if shard_end:
        query_filter += f" order_date:<{shard_end}"

    customers: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    pages = 0

    try:
        async with aiohttp.ClientSession() as session:
            while True:
                data, warnings = await _shopify_graphql(
                    session,
                    shop_domain,
                    admin_api_key,
                    api_version,
                    _LOST_CUSTOMERS_QUERY,
                    {"q": query_filter, "after": cursor},
                    op_name="lost customers",
                    on_retry=on_retry,
                )
                if warnings:
                    result["warnings"].extend(warnings)

                conn = data.get("customers") or {}
                for node in conn.get("nodes") or []:
                    customers.append(_normalize_lost_customer(node))

                pages += 1
                if on_page:
                    on_page(len(customers))

                page_info = conn.get("pageInfo") or {}
                if not page_info.get("hasNextPage"):
                    break
                cursor = page_info.get("endCursor")

                if len(customers) >= _PAGINATION_OBJECT_CAP:
                    # Truncating silently would understate lost — exactly the
                    # wrong direction for this report.
                    result["customers"] = customers
                    result["pages"] = pages
                    result["ok"] = True
                    result["complete"] = False
                    result["incomplete_reason"] = (
                        f"Shopify stops returning results after {_PAGINATION_OBJECT_CAP:,} "
                        f"customers, and {shop_domain} has more than that in this date "
                        f"range. Narrow the dates to see the rest."
                    )
                    return result

    except ShopifyFetchError as e:
        result["error"] = str(e)
        result["customers"] = customers  # keep what we got; caller marks partial
        result["pages"] = pages
        return result
    except asyncio.CancelledError:
        raise
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"
        result["pages"] = pages
        return result

    result["ok"] = True
    result["complete"] = not result["warnings"]
    if result["warnings"]:
        result["incomplete_reason"] = "Shopify returned partial data: " + result["warnings"][0]
    result["customers"] = customers
    result["pages"] = pages
    return result


def _normalize_lost_customer(node: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one customer node, deriving the last order's fulfillment timeline."""
    last = node.get("lastOrder") or None
    spent = node.get("amountSpent") or {}

    row: Dict[str, Any] = {
        "customer_id": node.get("id"),
        "name": node.get("displayName") or "",
        # May be null when protected customer data is not approved.
        "email": node.get("email"),
        "customer_since": node.get("createdAt"),
        # UnsignedInt64 serializes as a JSON string.
        "orders_count": int(node.get("numberOfOrders") or 0),
        "amount_spent": float(spent.get("amount") or 0),
        "currency": spent.get("currencyCode") or "USD",
        "last_order_id": None,
        "last_order_name": None,
        "last_order_created_at": None,
        "shipping_method": None,
        "shipping_method_raw": None,
        "carrier": None,
        "tracking_url": None,
        "fulfillment_status": None,
        "days_to_fulfil": None,
        "days_to_deliver": None,
        "days_total": None,
    }

    if not last:
        return row

    row["last_order_id"] = last.get("id")
    row["last_order_name"] = last.get("name")
    row["last_order_created_at"] = last.get("createdAt")
    row["fulfillment_status"] = last.get("displayFulfillmentStatus")

    ship = last.get("shippingLine") or {}
    row["shipping_method_raw"] = ship.get("title")
    row["shipping_method"] = _normalize_shipping_method(ship.get("title"))

    fulfillments = last.get("fulfillments") or []
    if fulfillments:
        # Split shipments are common (≈1.7 fulfillments per order on live data).
        # Ship time = when the first parcel left. Delivery = when the last one
        # landed, i.e. when the customer actually had the whole order.
        created = [f.get("createdAt") for f in fulfillments if f.get("createdAt")]
        delivered = [f.get("deliveredAt") for f in fulfillments if f.get("deliveredAt")]
        first_ship = min(created) if created else None
        last_deliver = max(delivered) if delivered else None

        row["days_to_fulfil"] = _days_between(last.get("createdAt"), first_ship)
        row["days_to_deliver"] = _days_between(first_ship, last_deliver)
        row["days_total"] = _days_between(last.get("createdAt"), last_deliver)

        for f in fulfillments:
            for t in f.get("trackingInfo") or []:
                if t.get("company") and not row["carrier"]:
                    row["carrier"] = _normalize_carrier(t.get("company"))
                if t.get("url") and not row["tracking_url"]:
                    row["tracking_url"] = t.get("url")

    return row


def _days_between(start_iso: Optional[str], end_iso: Optional[str]) -> Optional[float]:
    """
    Fractional days between two ISO timestamps, or None.

    None means "unknown" (unfulfilled, or a carrier that never reported
    delivery) and must never be rendered as 0 — that would silently drag every
    median toward zero and make fulfillment look faster than it is.
    """
    if not start_iso or not end_iso:
        return None
    from datetime import datetime

    try:
        a = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    delta = (b - a).total_seconds() / 86400.0
    return round(delta, 2) if delta >= 0 else None


_CUSTOMER_ORDERS_QUERY = """
query CustomerOrders($q: String!, $n: Int!) {
  orders(first: $n, query: $q, sortKey: CREATED_AT, reverse: true) {
    nodes {
      id
      name
      createdAt
      displayFulfillmentStatus
      displayFinancialStatus
      cancelledAt
      totalPriceSet { shopMoney { amount currencyCode } }
      shippingLine { title carrierIdentifier }
      fulfillments(first: 5) {
        createdAt
        inTransitAt
        deliveredAt
        displayStatus
        trackingInfo { company number url }
      }
      lineItems(first: 50) {
        nodes {
          title
          quantity
          sku
          variantTitle
          originalTotalSet { shopMoney { amount currencyCode } }
        }
      }
    }
  }
}
"""


async def fetch_customer_recent_orders(
    shop_domain: str,
    admin_api_key: str,
    customer_id: str,
    api_version: str = "2025-01",
    limit: int = 5,
) -> Dict[str, Any]:
    """
    Fetch a single customer's most recent orders with line items, for the
    click-through detail view. Raises nothing — returns {ok, error, orders[]}.
    """
    out: Dict[str, Any] = {"ok": False, "error": None, "orders": []}

    try:
        shop_domain = validate_shop_domain(shop_domain)
    except Exception as e:
        out["error"] = str(e)
        return out

    numeric_id = (customer_id or "").rsplit("/", 1)[-1]
    if not numeric_id:
        out["error"] = "Missing customer id"
        return out

    try:
        async with aiohttp.ClientSession() as session:
            data, warnings = await _shopify_graphql(
                session,
                shop_domain,
                admin_api_key,
                api_version,
                _CUSTOMER_ORDERS_QUERY,
                {"q": f"customer_id:{numeric_id}", "n": max(1, min(limit, 20))},
                op_name="customer orders",
            )
    except ShopifyFetchError as e:
        out["error"] = str(e)
        return out
    except asyncio.CancelledError:
        raise
    except Exception as e:
        out["error"] = f"Unexpected error: {e}"
        return out

    for node in (data.get("orders") or {}).get("nodes") or []:
        total = (node.get("totalPriceSet") or {}).get("shopMoney") or {}
        ship = node.get("shippingLine") or {}
        fulfillments = node.get("fulfillments") or []
        created = [f.get("createdAt") for f in fulfillments if f.get("createdAt")]
        delivered = [f.get("deliveredAt") for f in fulfillments if f.get("deliveredAt")]
        first_ship = min(created) if created else None
        last_deliver = max(delivered) if delivered else None

        carrier = None
        for f in fulfillments:
            for t in f.get("trackingInfo") or []:
                if t.get("company"):
                    carrier = _normalize_carrier(t.get("company"))
                    break
            if carrier:
                break

        out["orders"].append({
            "id": node.get("id"),
            "name": node.get("name"),
            "created_at": node.get("createdAt"),
            "cancelled_at": node.get("cancelledAt"),
            "fulfillment_status": node.get("displayFulfillmentStatus"),
            "financial_status": node.get("displayFinancialStatus"),
            "total_amount": total.get("amount") or "0",
            "currency": total.get("currencyCode") or "USD",
            "shipping_method": _normalize_shipping_method(ship.get("title")),
            "shipping_method_raw": ship.get("title"),
            "carrier": carrier,
            "days_to_fulfil": _days_between(node.get("createdAt"), first_ship),
            "days_to_deliver": _days_between(first_ship, last_deliver),
            "days_total": _days_between(node.get("createdAt"), last_deliver),
            "line_items": [
                {
                    "title": li.get("title") or "",
                    "quantity": li.get("quantity") or 0,
                    "sku": li.get("sku") or "",
                    "variant_title": li.get("variantTitle") or "",
                    "amount": ((li.get("originalTotalSet") or {}).get("shopMoney") or {}).get("amount") or "0",
                    "currency": ((li.get("originalTotalSet") or {}).get("shopMoney") or {}).get("currencyCode") or "USD",
                }
                for li in (node.get("lineItems") or {}).get("nodes") or []
            ],
        })

    out["ok"] = True
    return out


# ============================================================================
# Lost-products analysis: line items of the orders customers left after
# ============================================================================

# nodes(ids:) accepts up to 250 ids and, unlike a connection, is charged almost
# flat: 250 orders with lineItems(first:100) measured 21 points against a
# 1,000-point ceiling. That is why the whole cohort can be analysed at all.
_LINE_ITEM_BATCH = 250

# Largest basket observed across these stores is 69 items; 100 leaves headroom
# and hasNextPage reports anything that still overflows rather than silently
# truncating the counts.
_LINE_ITEMS_PER_ORDER = 100

# Backstop per baseline month; a normal month needs far fewer.
_BASELINE_MAX_PAGES_PER_WINDOW = 60

_ORDER_ITEMS_QUERY = """
query OrderItems($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Order {
      id
      name
      createdAt
      lineItems(first: %d) {
        pageInfo { hasNextPage }
        nodes {
          title
          quantity
          sku
          variantTitle
          product { id title }
        }
      }
    }
  }
}
""" % _LINE_ITEMS_PER_ORDER

_BASELINE_ITEMS_QUERY = """
query BaselineItems($q: String!, $after: String) {
  orders(first: 250, query: $q, sortKey: CREATED_AT, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      lineItems(first: %d) {
        pageInfo { hasNextPage }
        nodes {
          title
          quantity
          sku
          variantTitle
          product { id title }
        }
      }
    }
  }
}
""" % _LINE_ITEMS_PER_ORDER


def _order_gid(order_id: str) -> str:
    """Accept either a bare numeric id or a full GID."""
    s = str(order_id or "").strip()
    if not s:
        return ""
    return s if s.startswith("gid://") else f"gid://shopify/Order/{s}"


def _normalize_order_items(node: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one order's line items into the shape the aggregator wants."""
    li = node.get("lineItems") or {}
    return {
        "id": node.get("id"),
        "name": node.get("name"),
        "created_at": node.get("createdAt"),
        "truncated": bool((li.get("pageInfo") or {}).get("hasNextPage")),
        "items": [
            {
                "title": (it.get("title") or "").strip(),
                "quantity": it.get("quantity") or 0,
                "sku": (it.get("sku") or "").strip(),
                "variant_title": (it.get("variantTitle") or "").strip(),
                # product is null for deleted products — the aggregator falls
                # back to the title rather than dropping the row, since a
                # discontinued item is exactly what this report might surface.
                "product_id": ((it.get("product") or {}) or {}).get("id"),
                "product_title": ((it.get("product") or {}) or {}).get("title"),
            }
            for it in (li.get("nodes") or [])
        ],
    }


async def fetch_orders_line_items(
    shop_domain: str,
    admin_api_key: str,
    order_ids: List[str],
    api_version: str = "2025-01",
    on_batch=None,
    on_retry=None,
) -> Dict[str, Any]:
    """
    Fetch line items for a specific set of orders, in batches of 250.

    Returns {ok, error, orders[], missing, truncated, warnings}. `missing`
    counts ids Shopify returned nothing for (deleted orders) so the analysed
    total is never quietly smaller than what was asked for.
    """
    out: Dict[str, Any] = {
        "ok": False, "error": None, "orders": [],
        "missing": 0, "truncated": 0, "warnings": [],
    }

    try:
        shop_domain = validate_shop_domain(shop_domain)
    except Exception as e:
        out["error"] = str(e)
        return out

    gids = [_order_gid(o) for o in order_ids if o]
    gids = [g for g in gids if g]
    if not gids:
        out["ok"] = True
        return out

    try:
        async with aiohttp.ClientSession() as session:
            for i in range(0, len(gids), _LINE_ITEM_BATCH):
                batch = gids[i:i + _LINE_ITEM_BATCH]
                data, warnings = await _shopify_graphql(
                    session, shop_domain, admin_api_key, api_version,
                    _ORDER_ITEMS_QUERY, {"ids": batch},
                    op_name="order line items", on_retry=on_retry,
                )
                if warnings:
                    out["warnings"].extend(warnings)

                for node in data.get("nodes") or []:
                    if not node or not node.get("id"):
                        out["missing"] += 1
                        continue
                    order = _normalize_order_items(node)
                    if order["truncated"]:
                        out["truncated"] += 1
                    out["orders"].append(order)

                if on_batch:
                    on_batch(len(out["orders"]), len(gids))

    except ShopifyFetchError as e:
        out["error"] = str(e)
        return out
    except asyncio.CancelledError:
        raise
    except Exception as e:
        out["error"] = f"Unexpected error: {e}"
        return out

    out["ok"] = True
    return out


async def fetch_baseline_order_items(
    shop_domain: str,
    admin_api_key: str,
    windows: List[tuple],
    api_version: str = "2025-01",
    on_batch=None,
    on_retry=None,
) -> Dict[str, Any]:
    """
    Sample orders for the comparison baseline: one 250-order page per window.

    `windows` is a list of (start, end) date strings — complete calendar
    months, each paginated IN FULL. Reading only the first page covered just
    the opening day or two of a busy month, so every comparison inherited
    whatever was special about the start of a month.

    An exhaustive baseline over the entire range is not viable — one store has
    ~137,000 orders in two years — so the caller picks how many whole months to
    cover based on that store's volume.
    """
    out: Dict[str, Any] = {
        "ok": False, "error": None, "orders": [],
        "truncated": 0, "warnings": [], "pages": 0,
    }

    try:
        shop_domain = validate_shop_domain(shop_domain)
    except Exception as e:
        out["error"] = str(e)
        return out

    try:
        async with aiohttp.ClientSession() as session:
            for start, end in windows:
                q = f"created_at:>={start} created_at:<{end}"
                cursor = None
                # Backstop so one unexpectedly huge month cannot run away.
                for _ in range(_BASELINE_MAX_PAGES_PER_WINDOW):
                    data, warnings = await _shopify_graphql(
                        session, shop_domain, admin_api_key, api_version,
                        _BASELINE_ITEMS_QUERY, {"q": q, "after": cursor},
                        op_name="baseline line items", on_retry=on_retry,
                    )
                    if warnings:
                        out["warnings"].extend(warnings)

                    conn = data.get("orders") or {}
                    for node in conn.get("nodes") or []:
                        if not node:
                            continue
                        order = _normalize_order_items(node)
                        if order["truncated"]:
                            out["truncated"] += 1
                        out["orders"].append(order)

                    out["pages"] += 1
                    if on_batch:
                        on_batch(len(out["orders"]), len(windows))

                    page_info = conn.get("pageInfo") or {}
                    if not page_info.get("hasNextPage"):
                        break
                    cursor = page_info.get("endCursor")
    except ShopifyFetchError as e:
        out["error"] = str(e)
        return out
    except asyncio.CancelledError:
        raise
    except Exception as e:
        out["error"] = f"Unexpected error: {e}"
        return out

    out["ok"] = True
    return out


# ============================================================================
# Acquisition date: when did this customer FIRST order?
# ============================================================================

# Shopify's Customer type has no firstOrder field, and its `order_date` search
# filter matches customers with ANY order in a range — not customers who
# STARTED in it. The only way to know when someone actually began buying is to
# ask for their oldest order.
#
# orders(first: 1, sortKey: CREATED_AT) is ascending by default, i.e. the
# oldest order — verified against full order lists, not assumed. Batched via
# nodes(ids:) it costs 4 points per 250 customers, so a 25,000-customer cohort
# is ~100 cheap calls rather than 25,000.
_FIRST_ORDER_BATCH = 250
_FIRST_ORDER_CONCURRENCY = 5

_FIRST_ORDER_QUERY = """
query CustomerFirstOrders($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on Customer {
      id
      orders(first: 1, sortKey: CREATED_AT) {
        nodes { id createdAt }
      }
    }
  }
}
"""


async def fetch_customer_first_orders(
    shop_domain: str,
    admin_api_key: str,
    customer_ids: List[str],
    api_version: str = "2025-01",
    on_batch=None,
    on_retry=None,
) -> Dict[str, Any]:
    """
    Map customer GID -> ISO date of their oldest order.

    Returns {ok, error, first_orders, missing, warnings}. `missing` counts
    customers Shopify returned no order for; the caller must decide what to do
    with them rather than silently assuming a date.
    """
    out: Dict[str, Any] = {
        "ok": False, "error": None, "first_orders": {}, "missing": 0, "warnings": [],
    }

    try:
        shop_domain = validate_shop_domain(shop_domain)
    except Exception as e:
        out["error"] = str(e)
        return out

    ids = [c for c in customer_ids if c]
    if not ids:
        out["ok"] = True
        return out

    batches = [ids[i:i + _FIRST_ORDER_BATCH] for i in range(0, len(ids), _FIRST_ORDER_BATCH)]
    semaphore = asyncio.Semaphore(_FIRST_ORDER_CONCURRENCY)
    done = 0

    try:
        async with aiohttp.ClientSession() as session:

            async def run_batch(batch):
                nonlocal done
                async with semaphore:
                    # Unlike cursor pagination these batches are independent,
                    # so they can run concurrently instead of serially.
                    data, warnings = await _shopify_graphql(
                        session, shop_domain, admin_api_key, api_version,
                        _FIRST_ORDER_QUERY, {"ids": batch},
                        op_name="customer first orders", on_retry=on_retry,
                    )
                    if warnings:
                        out["warnings"].extend(warnings)
                    for node in data.get("nodes") or []:
                        if not node or not node.get("id"):
                            out["missing"] += 1
                            continue
                        nodes = ((node.get("orders") or {}).get("nodes") or [])
                        if not nodes:
                            out["missing"] += 1
                            continue
                        out["first_orders"][node["id"]] = nodes[0].get("createdAt")
                    done += len(batch)
                    if on_batch:
                        on_batch(done, len(ids))

            await asyncio.gather(*[run_batch(b) for b in batches])

    except ShopifyFetchError as e:
        out["error"] = str(e)
        return out
    except asyncio.CancelledError:
        raise
    except Exception as e:
        out["error"] = f"Unexpected error: {e}"
        return out

    out["ok"] = True
    return out


# ============================================================================
# Cross-store lookup: did this person just move to another shop?
# ============================================================================

# Shopify keeps a separate customer record per shop, so someone who stops
# buying at one store and starts at another looks like churn at the first.
# Email is the only identifier shared across shops.
#
# Batched as `email:"a" OR email:"b" OR ...`, 250 addresses cost 24 points and
# return in under a second — so checking a cohort against another store scales
# with the cohort, not with that store's size.
_EMAIL_BATCH = 250
_EMAIL_CONCURRENCY = 4

_CUSTOMERS_BY_EMAIL_QUERY = """
query CustomersByEmail($q: String!) {
  customers(first: 250, query: $q) {
    nodes {
      id
      email
      lastOrder { id createdAt }
    }
  }
}
"""


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Lowercased, trimmed. Shops store the same address with varying case."""
    if not email:
        return None
    e = email.strip().lower()
    return e or None


async def fetch_customers_by_emails(
    shop_domain: str,
    admin_api_key: str,
    emails: List[str],
    api_version: str = "2025-01",
    on_batch=None,
    on_retry=None,
) -> Dict[str, Any]:
    """
    Look up a set of email addresses in one shop.

    Returns {ok, error, last_orders, warnings} where last_orders maps a
    normalized email to the most recent order date at THIS shop, or None when
    the customer exists but has never ordered. A shop can hold more than one
    record for an address, so the latest order across duplicates wins.
    """
    out: Dict[str, Any] = {"ok": False, "error": None, "last_orders": {}, "warnings": []}

    try:
        shop_domain = validate_shop_domain(shop_domain)
    except Exception as e:
        out["error"] = str(e)
        return out

    clean = sorted({e for e in (normalize_email(x) for x in emails) if e})
    if not clean:
        out["ok"] = True
        return out

    batches = [clean[i:i + _EMAIL_BATCH] for i in range(0, len(clean), _EMAIL_BATCH)]
    semaphore = asyncio.Semaphore(_EMAIL_CONCURRENCY)
    done = 0

    try:
        async with aiohttp.ClientSession() as session:

            async def run_batch(batch):
                nonlocal done
                async with semaphore:
                    # Quotes cannot appear in a valid address, but a crafted
                    # value must not be able to break out of the query.
                    terms = " OR ".join(
                        'email:"{}"'.format(e.replace('"', "")) for e in batch
                    )
                    data, warnings = await _shopify_graphql(
                        session, shop_domain, admin_api_key, api_version,
                        _CUSTOMERS_BY_EMAIL_QUERY, {"q": terms},
                        op_name="cross-store email lookup", on_retry=on_retry,
                    )
                    if warnings:
                        out["warnings"].extend(warnings)
                    for node in (data.get("customers") or {}).get("nodes") or []:
                        em = normalize_email((node or {}).get("email"))
                        if not em:
                            continue
                        last = ((node.get("lastOrder") or {}) or {}).get("createdAt")
                        prev = out["last_orders"].get(em)
                        if last and (prev is None or last > prev):
                            out["last_orders"][em] = last
                        else:
                            out["last_orders"].setdefault(em, prev)
                    done += len(batch)
                    if on_batch:
                        on_batch(done, len(clean))

            await asyncio.gather(*[run_batch(b) for b in batches])

    except ShopifyFetchError as e:
        out["error"] = str(e)
        return out
    except asyncio.CancelledError:
        raise
    except Exception as e:
        out["error"] = f"Unexpected error: {e}"
        return out

    out["ok"] = True
    return out
