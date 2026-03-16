"""Inventory / stock tools for the ERP AI Assistant."""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_date_range


# ── helpers ──────────────────────────────────────────────────────────────────

def _resolve_item(item_name: str, limit: int = 5) -> list:
    """Return Item rows matching item_name or item_code (LIKE search)."""
    rows = frappe.db.get_all(
        "Item",
        filters=[["item_name", "like", f"%{item_name}%"]],
        fields=["name", "item_name", "stock_uom", "item_group"],
        limit=limit,
    )
    if not rows:
        rows = frappe.db.get_all(
            "Item",
            filters=[["name", "like", f"%{item_name}%"]],
            fields=["name", "item_name", "stock_uom", "item_group"],
            limit=limit,
        )
    return rows


# ── existing tools (kept intact) ─────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_balance(item_name: str, warehouse: str = None) -> dict:
    """Get current stock balance (quantity on hand) for an item.

    Use when the user asks how much stock is left, how many units are
    available, or wants to check inventory levels. Can filter by warehouse.

    Args:
        item_name: Partial or full item name or item code. Uses LIKE search.
        warehouse: Specific warehouse name. Omit to show all warehouses.
    """
    items = _resolve_item(item_name)
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
        {"warehouse": f"%{warehouse}%"} if warehouse else {},
        as_dict=True,
    )
    return {"low_stock_items": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_movement(item_name: str, days: int = 30) -> dict:
    """Get recent stock ledger entries (ins and outs) for an item.

    Use when asked about stock history, recent transactions, how many units
    were added or removed, usage rate, or how fast an item is moving.

    Args:
        item_name: Partial or full item name or item code.
        days: Number of past days to look back. Defaults to 30.
    """
    items = _resolve_item(item_name, limit=3)
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    item_codes = [i["name"] for i in items]
    rows = frappe.db.sql(
        """
        SELECT
            item_code, item_name, warehouse, posting_date,
            actual_qty AS qty_change,
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
            SUM(b.stock_value) AS stock_value
        FROM `tabBin` b
        WHERE b.actual_qty > 0
        GROUP BY b.warehouse
        ORDER BY stock_value DESC
        """,
        as_dict=True,
    )
    total_value = sum(r["stock_value"] or 0 for r in rows)
    return {"warehouses": rows, "count": len(rows), "total_stock_value": total_value}


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


# ── new extended stock tools ──────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_in_out_summary(period: str, warehouse: str = None) -> dict:
    """Get total stock received (in) vs issued (out) for a period.

    Use when asked how much stock was added vs consumed, total goods received,
    total issues, or net stock change over a time period.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        warehouse: Filter to a specific warehouse. Optional.
    """
    start, end = get_date_range(period)
    wh_condition = "AND warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "start": start, "end": end,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            voucher_type,
            SUM(CASE WHEN actual_qty > 0 THEN actual_qty ELSE 0 END) AS total_in,
            SUM(CASE WHEN actual_qty < 0 THEN ABS(actual_qty) ELSE 0 END) AS total_out,
            COUNT(*) AS entry_count
        FROM `tabStock Ledger Entry`
        WHERE posting_date BETWEEN %(start)s AND %(end)s
          AND is_cancelled = 0
          {wh_condition}
        GROUP BY voucher_type
        ORDER BY total_in DESC
        """,
        params,
        as_dict=True,
    )
    total_in  = sum(r["total_in"]  for r in rows)
    total_out = sum(r["total_out"] for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_voucher_type": rows,
        "total_received": total_in,
        "total_issued": total_out,
        "net_change": total_in - total_out,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_slow_moving_items(days: int = 60, warehouse: str = None, limit: int = 20) -> dict:
    """Find items with little or no stock movement in the past N days.

    Use when asked about slow-moving stock, dead stock, items not selling,
    or items that have been sitting in the warehouse too long.

    Args:
        days: Look-back window. Items with no movement in this many days are flagged. Defaults to 60.
        warehouse: Filter to a specific warehouse. Optional.
        limit: Max number of items to return. Defaults to 20.
    """
    wh_condition = "AND b.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "days": days, "limit": limit,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            b.warehouse,
            b.actual_qty,
            b.stock_value AS stock_value,
            MAX(sle.posting_date) AS last_movement_date,
            DATEDIFF(CURDATE(), MAX(sle.posting_date)) AS days_since_movement
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        LEFT JOIN `tabStock Ledger Entry` sle
            ON sle.item_code = b.item_code
            AND sle.warehouse = b.warehouse
            AND sle.is_cancelled = 0
        WHERE b.actual_qty > 0
          {wh_condition}
        GROUP BY b.item_code, b.warehouse
        HAVING days_since_movement >= %(days)s OR last_movement_date IS NULL
        ORDER BY days_since_movement DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    total_value = sum((r["stock_value"] or 0) for r in rows)
    return {
        "slow_moving_items": rows,
        "count": len(rows),
        "days_threshold": days,
        "total_idle_stock_value": total_value,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_valuation_by_group(warehouse: str = None) -> dict:
    """Get total stock value broken down by item group.

    Use when asked about the value of stock by category, which product
    category has the most capital tied up, or stock composition.

    Args:
        warehouse: Filter to a specific warehouse. Optional.
    """
    wh_condition = "AND b.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {"warehouse": f"%{warehouse}%"} if warehouse else {}
    rows = frappe.db.sql(
        f"""
        SELECT
            i.item_group,
            COUNT(DISTINCT b.item_code) AS item_count,
            SUM(b.actual_qty) AS total_qty,
            SUM(b.stock_value) AS stock_value
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE b.actual_qty > 0
          {wh_condition}
        GROUP BY i.item_group
        ORDER BY stock_value DESC
        """,
        params,
        as_dict=True,
    )
    total = sum(r["stock_value"] or 0 for r in rows)
    return {"by_item_group": rows, "count": len(rows), "total_stock_value": total}


@mcp.tool(annotations={"readOnlyHint": True})
def get_reorder_suggestions(warehouse: str = None) -> dict:
    """Get reorder suggestions for items below their reorder level, with suggested order qty.

    Use when asked what to order, purchase suggestions, restocking plan,
    or how much of each item to buy.

    Args:
        warehouse: Filter to a specific warehouse. Optional.
    """
    wh_condition = "AND b.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {"warehouse": f"%{warehouse}%"} if warehouse else {}
    rows = frappe.db.sql(
        f"""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            b.warehouse,
            b.actual_qty,
            i.reorder_level,
            i.reorder_qty,
            GREATEST(
                COALESCE(i.reorder_qty, 0),
                COALESCE(i.reorder_level, 0) - b.actual_qty
            ) AS suggested_order_qty,
            (
                SELECT s.supplier_name
                FROM `tabItem Default` id2
                JOIN `tabSupplier` s ON s.name = id2.default_supplier
                WHERE id2.parent = b.item_code
                LIMIT 1
            ) AS default_supplier,
            (
                SELECT ip.price_list_rate
                FROM `tabItem Price` ip
                WHERE ip.item_code = b.item_code AND ip.buying = 1
                LIMIT 1
            ) AS last_purchase_rate
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE i.reorder_level IS NOT NULL
          AND i.reorder_level > 0
          AND b.actual_qty <= i.reorder_level
          {wh_condition}
        ORDER BY (i.reorder_level - b.actual_qty) DESC
        LIMIT 30
        """,
        params,
        as_dict=True,
    )
    return {"reorder_suggestions": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_reserved(item_name: str = None, warehouse: str = None) -> dict:
    """Get reserved vs available (free) stock from open Sales Orders.

    Use when asked about reserved stock, how much is committed to orders,
    or what quantity is actually free to sell.

    Args:
        item_name: Filter by item name or code. Optional.
        warehouse: Filter to a specific warehouse. Optional.
    """
    conditions = ["b.actual_qty > 0 OR b.reserved_qty > 0"]
    params = {}
    if item_name:
        conditions.append("(i.item_name LIKE %(item_name)s OR b.item_code LIKE %(item_name)s)")
        params["item_name"] = f"%{item_name}%"
    if warehouse:
        conditions.append("b.warehouse LIKE %(warehouse)s")
        params["warehouse"] = f"%{warehouse}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            b.item_code,
            i.item_name,
            b.warehouse,
            b.actual_qty,
            b.reserved_qty,
            b.indented_qty,
            b.ordered_qty,
            (b.actual_qty - b.reserved_qty) AS free_qty
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE {where}
        ORDER BY b.reserved_qty DESC
        LIMIT 30
        """,
        params,
        as_dict=True,
    )
    return {"reserved_stock": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_goods_received(period: str, supplier: str = None, limit: int = 20) -> dict:
    """Get Purchase Receipts (GRNs) submitted in a period.

    Use when asked what stock was received, what deliveries came in,
    goods received from a supplier, or recent purchase receipts.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        supplier: Filter by supplier name (partial match). Optional.
        limit: Max rows to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    filters = {
        "docstatus": 1,
        "posting_date": ["between", [start, end]],
    }
    if supplier:
        filters["supplier"] = ["like", f"%{supplier}%"]

    receipts = frappe.db.get_all(
        "Purchase Receipt",
        filters=filters,
        fields=["name", "supplier", "posting_date", "total_qty", "grand_total", "status"],
        order_by="posting_date desc",
        limit=limit,
    )
    total_value = sum(r["grand_total"] or 0 for r in receipts)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "receipts": receipts,
        "count": len(receipts),
        "total_value": total_value,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_transfers(period: str, from_warehouse: str = None, to_warehouse: str = None, limit: int = 20) -> dict:
    """Get inter-warehouse stock transfers for a period.

    Use when asked about stock moved between warehouses, internal transfers,
    or which warehouse sent/received stock.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        from_warehouse: Filter by source warehouse (partial match). Optional.
        to_warehouse: Filter by destination warehouse (partial match). Optional.
        limit: Max rows to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    conditions = [
        "se.docstatus = 1",
        "se.purpose = 'Material Transfer'",
        "se.posting_date BETWEEN %(start)s AND %(end)s",
    ]
    params: dict = {"start": start, "end": end}
    if from_warehouse:
        conditions.append("se.from_warehouse LIKE %(from_wh)s")
        params["from_wh"] = f"%{from_warehouse}%"
    if to_warehouse:
        conditions.append("se.to_warehouse LIKE %(to_wh)s")
        params["to_wh"] = f"%{to_warehouse}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            se.name,
            se.posting_date,
            se.from_warehouse,
            se.to_warehouse,
            se.total_outgoing_value AS transfer_value,
            COUNT(sed.name) AS line_items
        FROM `tabStock Entry` se
        LEFT JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE {where}
        GROUP BY se.name
        ORDER BY se.posting_date DESC
        LIMIT %(limit)s
        """,
        {**params, "limit": limit},
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "transfers": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_item_price_list(item_name: str) -> dict:
    """Get all buying and selling prices for an item across all price lists.

    Use when asked about the price of an item, what it costs to buy,
    selling price, or price differences between price lists.

    Args:
        item_name: Partial or full item name or item code.
    """
    items = _resolve_item(item_name, limit=3)
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    result = []
    for item in items:
        prices = frappe.db.get_all(
            "Item Price",
            filters={"item_code": item["name"]},
            fields=[
                "price_list", "price_list_rate", "currency",
                "buying", "selling", "valid_from", "valid_upto",
            ],
            order_by="selling desc, price_list_rate asc",
        )
        result.append({
            "item_code": item["name"],
            "item_name": item["item_name"],
            "uom": item["stock_uom"],
            "prices": prices,
        })
    return {"items": result}


@mcp.tool(annotations={"readOnlyHint": True})
def get_top_stocked_items(warehouse: str = None, by: str = "value", limit: int = 20) -> dict:
    """Get items with the highest stock quantity or value.

    Use when asked which items have the most stock, highest inventory value,
    what we are overstocked on, or top items by value in a warehouse.

    Args:
        warehouse: Filter to a specific warehouse. Optional.
        by: Rank by 'value' (stock value) or 'qty' (quantity). Defaults to value.
        limit: Number of items to return. Defaults to 20.
    """
    wh_condition = "AND b.warehouse LIKE %(warehouse)s" if warehouse else ""
    order_field = "stock_value" if by != "qty" else "b.actual_qty"
    params = {
        "limit": limit,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            b.warehouse,
            b.actual_qty,
            i.stock_uom,
            b.stock_value AS stock_value
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        WHERE b.actual_qty > 0
          {wh_condition}
        ORDER BY {order_field} DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {"items": rows, "count": len(rows), "ranked_by": by}


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_shortage_risk(days_cover: int = 7, warehouse: str = None, limit: int = 20) -> dict:
    """Identify items at risk of running out within N days based on recent consumption rate.

    Use when asked about stockout risk, which items will run out soon,
    demand planning, or days of cover remaining.

    Args:
        days_cover: Flag items with fewer than this many days of stock remaining. Defaults to 7.
        warehouse: Filter to a specific warehouse. Optional.
        limit: Max items to return. Defaults to 20.
    """
    wh_condition = "AND b.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "days_cover": days_cover,
        "limit": limit,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            b.item_code,
            i.item_name,
            i.item_group,
            b.warehouse,
            b.actual_qty,
            i.stock_uom,
            ABS(SUM(CASE WHEN sle.actual_qty < 0 THEN sle.actual_qty ELSE 0 END)) / 30.0
                AS avg_daily_consumption,
            CASE
                WHEN ABS(SUM(CASE WHEN sle.actual_qty < 0 THEN sle.actual_qty ELSE 0 END)) > 0
                THEN b.actual_qty /
                     (ABS(SUM(CASE WHEN sle.actual_qty < 0 THEN sle.actual_qty ELSE 0 END)) / 30.0)
                ELSE NULL
            END AS days_of_cover
        FROM `tabBin` b
        JOIN `tabItem` i ON i.name = b.item_code
        LEFT JOIN `tabStock Ledger Entry` sle
            ON sle.item_code = b.item_code
            AND sle.warehouse = b.warehouse
            AND sle.is_cancelled = 0
            AND sle.posting_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
        WHERE b.actual_qty > 0
          {wh_condition}
        GROUP BY b.item_code, b.warehouse
        HAVING days_of_cover IS NOT NULL AND days_of_cover <= %(days_cover)s
        ORDER BY days_of_cover ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {
        "at_risk_items": rows,
        "count": len(rows),
        "days_cover_threshold": days_cover,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_ageing(warehouse: str = None, limit: int = 20) -> dict:
    """Get items by how long they have been sitting in stock (age of oldest batch received).

    Use when asked about stock age, how long items have been in the warehouse,
    FIFO ageing, or identifying stock that has been held the longest.

    Args:
        warehouse: Filter to a specific warehouse. Optional.
        limit: Max items to return. Defaults to 20.
    """
    wh_condition = "AND sle.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "limit": limit,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            sle.item_code,
            i.item_name,
            i.item_group,
            sle.warehouse,
            MIN(sle.posting_date) AS oldest_receipt_date,
            DATEDIFF(CURDATE(), MIN(sle.posting_date)) AS age_days,
            b.actual_qty AS current_qty,
            b.stock_value AS stock_value
        FROM `tabStock Ledger Entry` sle
        JOIN `tabItem` i ON i.name = sle.item_code
        JOIN `tabBin` b
            ON b.item_code = sle.item_code AND b.warehouse = sle.warehouse
        WHERE sle.actual_qty > 0
          AND sle.is_cancelled = 0
          AND b.actual_qty > 0
          {wh_condition}
        GROUP BY sle.item_code, sle.warehouse
        ORDER BY age_days DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {"aged_stock": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_batch_stock(item_name: str, warehouse: str = None) -> dict:
    """Get stock levels broken down by batch number for a batch-tracked item.

    Use when asked about batch quantities, lot numbers, batch expiry,
    or how much of each batch is remaining.

    Args:
        item_name: Partial or full item name or item code.
        warehouse: Filter to a specific warehouse. Optional.
    """
    items = _resolve_item(item_name, limit=3)
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    item_codes = [i["name"] for i in items]
    wh_condition = "AND sle.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "codes": item_codes,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            sle.item_code,
            sle.item_name,
            sle.batch_no,
            b2.expiry_date,
            sle.warehouse,
            SUM(sle.actual_qty) AS batch_qty
        FROM `tabStock Ledger Entry` sle
        LEFT JOIN `tabBatch` b2 ON b2.name = sle.batch_no
        WHERE sle.item_code IN %(codes)s
          AND sle.batch_no IS NOT NULL
          AND sle.batch_no != ''
          AND sle.is_cancelled = 0
          {wh_condition}
        GROUP BY sle.item_code, sle.batch_no, sle.warehouse
        HAVING batch_qty > 0
        ORDER BY b2.expiry_date ASC
        LIMIT 30
        """,
        params,
        as_dict=True,
    )
    return {"batch_stock": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_additions(item_name: str, warehouse: str = None, period: str = "this_month") -> dict:
    """Get all stock inbound transactions (additions) for an item — purchases, receipts, returns.

    Use when asked how many units of an item were added, received, or restocked
    at a specific warehouse over a period. Shows voucher type so you can see
    if it came from a Purchase Receipt, Stock Entry, or Sales Return.

    Args:
        item_name: Partial or full item name or item code.
        warehouse: Specific warehouse name (partial match). Optional — omit for all warehouses.
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
    """
    start, end = get_date_range(period)
    items = _resolve_item(item_name, limit=3)
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    item_codes = [i["name"] for i in items]
    wh_condition = "AND sle.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "codes": item_codes,
        "start": start,
        "end": end,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            sle.item_code,
            sle.item_name,
            sle.warehouse,
            sle.posting_date,
            sle.actual_qty AS qty_added,
            sle.qty_after_transaction,
            sle.voucher_type,
            sle.voucher_no,
            sle.stock_value
        FROM `tabStock Ledger Entry` sle
        WHERE sle.item_code IN %(codes)s
          AND sle.actual_qty > 0
          AND sle.posting_date BETWEEN %(start)s AND %(end)s
          AND sle.is_cancelled = 0
          {wh_condition}
        ORDER BY sle.posting_datetime DESC
        LIMIT 50
        """,
        params,
        as_dict=True,
    )
    total_added = sum(r["qty_added"] or 0 for r in rows)
    return {
        "item_filter": item_name,
        "warehouse_filter": warehouse,
        "period": period,
        "from": str(start),
        "to": str(end),
        "additions": rows,
        "count": len(rows),
        "total_qty_added": total_added,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_issues(item_name: str, warehouse: str = None, period: str = "this_month") -> dict:
    """Get all stock outbound transactions (issues) for an item — sales, consumption, transfers out.

    Use when asked how many units were sold, consumed, issued, or removed
    from a warehouse, and what voucher type caused the reduction.

    Args:
        item_name: Partial or full item name or item code.
        warehouse: Specific warehouse name (partial match). Optional.
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
    """
    start, end = get_date_range(period)
    items = _resolve_item(item_name, limit=3)
    if not items:
        return {"error": f"No items found matching '{item_name}'"}

    item_codes = [i["name"] for i in items]
    wh_condition = "AND sle.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "codes": item_codes,
        "start": start,
        "end": end,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            sle.item_code,
            sle.item_name,
            sle.warehouse,
            sle.posting_date,
            ABS(sle.actual_qty) AS qty_issued,
            sle.qty_after_transaction,
            sle.voucher_type,
            sle.voucher_no,
            ABS(sle.stock_value) AS stock_value
        FROM `tabStock Ledger Entry` sle
        WHERE sle.item_code IN %(codes)s
          AND sle.actual_qty < 0
          AND sle.posting_date BETWEEN %(start)s AND %(end)s
          AND sle.is_cancelled = 0
          {wh_condition}
        ORDER BY sle.posting_datetime DESC
        LIMIT 50
        """,
        params,
        as_dict=True,
    )
    total_issued = sum(r["qty_issued"] or 0 for r in rows)
    return {
        "item_filter": item_name,
        "warehouse_filter": warehouse,
        "period": period,
        "from": str(start),
        "to": str(end),
        "issues": rows,
        "count": len(rows),
        "total_qty_issued": total_issued,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_receipt_items(period: str, item_name: str = None, supplier: str = None, warehouse: str = None, limit: int = 30) -> dict:
    """Get line-item detail of what was received via Purchase Receipts (GRNs).

    Use when asked what specific items were received, how many units arrived
    from a supplier, which items came in on a GRN, or receipt quantities per item.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        item_name: Filter by item name or code. Optional.
        supplier: Filter by supplier name. Optional.
        warehouse: Filter by destination warehouse. Optional.
        limit: Max rows. Defaults to 30.
    """
    start, end = get_date_range(period)
    conditions = [
        "pr.docstatus = 1",
        "pr.posting_date BETWEEN %(start)s AND %(end)s",
    ]
    params: dict = {"start": start, "end": end, "limit": limit}
    if item_name:
        conditions.append("(pri.item_name LIKE %(item_name)s OR pri.item_code LIKE %(item_name)s)")
        params["item_name"] = f"%{item_name}%"
    if supplier:
        conditions.append("pr.supplier LIKE %(supplier)s")
        params["supplier"] = f"%{supplier}%"
    if warehouse:
        conditions.append("pri.warehouse LIKE %(warehouse)s")
        params["warehouse"] = f"%{warehouse}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            pr.name AS receipt_no,
            pr.supplier,
            pr.posting_date,
            pri.item_code,
            pri.item_name,
            pri.qty AS received_qty,
            pri.uom,
            pri.rate,
            pri.amount,
            pri.warehouse
        FROM `tabPurchase Receipt Item` pri
        JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
        WHERE {where}
        ORDER BY pr.posting_date DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    total_qty = sum(r["received_qty"] or 0 for r in rows)
    total_value = sum(r["amount"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "items_received": rows,
        "count": len(rows),
        "total_qty": total_qty,
        "total_value": total_value,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_entry_by_type(purpose: str, period: str = "this_month", warehouse: str = None, limit: int = 20) -> dict:
    """Get stock entries filtered by purpose/type for a period.

    Use when asked about specific stock operations: material issues, receipts,
    transfers, manufacture, repack, send-to-subcontract, or write-offs.

    Args:
        purpose: Stock Entry purpose. One of: Material Issue, Material Receipt, Material Transfer,
                 Material Transfer for Manufacture, Manufacture, Repack, Send to Subcontractor,
                 Material Consumption for Manufacture.
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        warehouse: Filter by from_warehouse or to_warehouse (partial match). Optional.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    wh_condition = "AND (se.from_warehouse LIKE %(warehouse)s OR se.to_warehouse LIKE %(warehouse)s)" if warehouse else ""
    params = {
        "purpose": purpose,
        "start": start,
        "end": end,
        "limit": limit,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            se.name,
            se.posting_date,
            se.purpose,
            se.from_warehouse,
            se.to_warehouse,
            se.total_outgoing_value,
            se.total_incoming_value,
            COUNT(sed.name) AS line_count
        FROM `tabStock Entry` se
        LEFT JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
        WHERE se.docstatus = 1
          AND se.purpose = %(purpose)s
          AND se.posting_date BETWEEN %(start)s AND %(end)s
          {wh_condition}
        GROUP BY se.name
        ORDER BY se.posting_date DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {
        "purpose": purpose,
        "period": period,
        "from": str(start),
        "to": str(end),
        "entries": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_opening_closing_stock(period: str, warehouse: str = None, item_group: str = None) -> dict:
    """Get opening and closing stock value for a period.

    Use when asked about opening stock, closing stock, how much stock changed
    in value over a period, or beginning vs ending inventory value.

    Args:
        period: One of: this_week, this_month, last_month, this_year.
        warehouse: Filter to a specific warehouse. Optional.
        item_group: Filter by item category. Optional.
    """
    start, end = get_date_range(period)
    wh_condition = "AND sle.warehouse LIKE %(warehouse)s" if warehouse else ""
    grp_condition = "AND i.item_group LIKE %(item_group)s" if item_group else ""
    params = {
        "start": start,
        "end": end,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
        **({"item_group": f"%{item_group}%"} if item_group else {}),
    }

    opening = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(sle.stock_value_difference), 0) AS value
        FROM `tabStock Ledger Entry` sle
        JOIN `tabItem` i ON i.name = sle.item_code
        WHERE sle.posting_date < %(start)s
          AND sle.is_cancelled = 0
          {wh_condition}
          {grp_condition}
        """,
        params,
        as_dict=True,
    )
    closing = frappe.db.sql(
        f"""
        SELECT COALESCE(SUM(sle.stock_value_difference), 0) AS value
        FROM `tabStock Ledger Entry` sle
        JOIN `tabItem` i ON i.name = sle.item_code
        WHERE sle.posting_date <= %(end)s
          AND sle.is_cancelled = 0
          {wh_condition}
          {grp_condition}
        """,
        params,
        as_dict=True,
    )
    opening_value = opening[0]["value"] or 0 if opening else 0
    closing_value = closing[0]["value"] or 0 if closing else 0
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "opening_stock_value": opening_value,
        "closing_stock_value": closing_value,
        "net_change": closing_value - opening_value,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_stock_consumption_by_item_group(period: str, warehouse: str = None) -> dict:
    """Get total stock consumed (issued) by item group for a period.

    Use when asked about material consumption, what categories of items
    are being used the most, or issue analysis by product group.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        warehouse: Filter to a specific warehouse. Optional.
    """
    start, end = get_date_range(period)
    wh_condition = "AND sle.warehouse LIKE %(warehouse)s" if warehouse else ""
    params = {
        "start": start, "end": end,
        **({"warehouse": f"%{warehouse}%"} if warehouse else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            i.item_group,
            COUNT(DISTINCT sle.item_code) AS distinct_items,
            ABS(SUM(sle.actual_qty)) AS total_qty_consumed,
            ABS(SUM(sle.stock_value)) AS total_value_consumed
        FROM `tabStock Ledger Entry` sle
        JOIN `tabItem` i ON i.name = sle.item_code
        WHERE sle.posting_date BETWEEN %(start)s AND %(end)s
          AND sle.actual_qty < 0
          AND sle.is_cancelled = 0
          {wh_condition}
        GROUP BY i.item_group
        ORDER BY total_value_consumed DESC
        """,
        params,
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_item_group": rows,
    }
