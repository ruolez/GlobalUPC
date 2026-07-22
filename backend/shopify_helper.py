import requests
import aiohttp
import asyncio
from typing import Optional, Dict, Any, List

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
