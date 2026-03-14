"""Inventory / stock tools for the ERP AI Assistant."""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_date_range


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_balance(item_name: str, warehouse: str = None) -> dict:
    """Get current stock balance (quantity on hand) for an item.

    Use when the user asks how much stock is left, how many units are
    available, or wants to check inventory levels. Can filter by warehouse.

    Args:
        item_name: Partial or full item name or item code. Uses LIKE search.
        warehouse: Specific warehouse name. Omit to show all warehouses.
    """
    items = frappe.db.get_all(
        "Item",
        filters=[["item_name", "like", f"%{item_name}%"]],
        fields=["name", "item_name", "stock_uom"],
        limit=5,
    )
    if not items:
        items = frappe.db.get_all(
            "Item",
            filters=[["name", "like", f"%{item_name}%"]],
            fields=["name", "item_name", "stock_uom"],
            limit=5,
        )
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    results = []
    for item in items:
        bin_filters = {"item_code": item["name"]}
        if warehouse:
            bin_filters["warehouse"] = ["like", f"%{warehouse}%"]
        bins = frappe.db.get_all(
            "Bin",
            filters=bin_filters,
            fields=["warehouse", "actual_qty", "reserved_qty", "ordered_qty"],
            order_by="actual_qty desc",
        )
        results.append({
            "item_code": item["name"],
            "item_name": item["item_name"],
            "uom": item["stock_uom"],
            "warehouses": bins,
            "total_qty": sum(b["actual_qty"] for b in bins),
        })
    return {"items": results}


@mcp.tool(annotations={"readOnlyHint": True})
def get_low_stock_items(warehouse: str = None) -> dict:
    """Find items whose stock is at or below their reorder level.

    Use when asked what needs to be reordered, what is running low, or
    what items are critically short on stock.

    Args:
        warehouse: Filter to a specific warehouse. Optional.
    """
    wh_condition = "AND b.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {"warehouse": f"%{warehouse}%" if warehouse else None}

    rows = frappe.db.sql(
        f"""
        SELECT
            b.item_code,
            i.item_name,
            b.warehouse,
            b.actual_qty,
            i.reorder_level,
            (b.actual_qty - COALESCE(i.reorder_level, 0)) AS qty_vs_reorder
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE i.reorder_level IS NOT NULL
          AND i.reorder_level > 0
          AND b.actual_qty <= i.reorder_level
          {wh_condition}
        ORDER BY qty_vs_reorder ASC
        LIMIT 20
        """,
        params if warehouse else {},
        as_dict=True,
    )
    return {"low_stock_items": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_movement(item_name: str, days: int = 30) -> dict:
    """Get recent stock ledger entries (ins and outs) for an item.

    Use when asked about stock history, recent transactions, usage rate,
    or how fast an item is moving.

    Args:
        item_name: Partial or full item name or item code.
        days: Number of past days to look back. Defaults to 30.
    """
    items = frappe.db.get_all(
        "Item",
        filters=[["item_name", "like", f"%{item_name}%"]],
        fields=["name", "item_name"],
        limit=3,
    )
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    item_codes = [i["name"] for i in items]
    rows = frappe.db.sql(
        """
        SELECT
            item_code, item_name, warehouse, posting_date,
            actual_qty_after_transaction,
            qty_after_transaction,
            voucher_type, voucher_no
        FROM `tabStock Ledger Entry`
        WHERE item_code IN %(codes)s
          AND posting_date >= DATE_SUB(CURDATE(), INTERVAL %(days)s DAY)
          AND is_cancelled = 0
        ORDER BY posting_datetime DESC
        LIMIT 50
        """,
        {"codes": item_codes, "days": days},
        as_dict=True,
    )
    return {"movements": rows, "count": len(rows), "days": days}


@mcp.tool(annotations={"readOnlyHint": True})
def get_warehouse_summary() -> dict:
    """Get a summary of stock value and item count across all warehouses.

    Use when asked for an overview of all warehouses, total stock value,
    or which warehouse holds the most stock.
    """
    rows = frappe.db.sql(
        """
        SELECT
            b.warehouse,
            COUNT(DISTINCT b.item_code) AS item_count,
            SUM(b.actual_qty) AS total_qty,
            SUM(b.actual_qty * COALESCE(item.valuation_rate, 0)) AS stock_value
        FROM `tabBin` b
        JOIN `tabItem` item ON item.name = b.item_code
        WHERE b.actual_qty > 0
        GROUP BY b.warehouse
        ORDER BY stock_value DESC
        """,
        as_dict=True,
    )
    return {"warehouses": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_item_details(item_name: str) -> dict:
    """Get full details for an item including price, description, and stock UOM.

    Use when asked about a specific item's details, selling price,
    or item configuration.

    Args:
        item_name: Partial or full item name or item code.
    """
    items = frappe.db.get_all(
        "Item",
        filters=[["item_name", "like", f"%{item_name}%"]],
        fields=[
            "name", "item_name", "item_group", "stock_uom",
            "description", "is_stock_item", "valuation_rate",
            "standard_rate", "reorder_level",
        ],
        limit=5,
    )
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    result = []
    for item in items:
        prices = frappe.db.get_all(
            "Item Price",
            filters={"item_code": item["name"], "selling": 1},
            fields=["price_list", "price_list_rate", "currency"],
            limit=3,
        )
        item["selling_prices"] = prices
        result.append(item)
    return {"items": result}
