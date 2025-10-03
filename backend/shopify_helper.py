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

                # Extract variants
                variants = []
                edges = data.get("data", {}).get("productVariants", {}).get("edges", [])

                for edge in edges:
                    node = edge.get("node", {})
                    product = node.get("product", {})

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
