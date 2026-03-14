"""Purchase tools for the ERP AI Assistant."""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_date_range


@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_summary(period: str) -> dict:
    """Get a purchase summary — total spend, invoice count, and top suppliers.

    Use when asked about total purchases, how much was spent, procurement
    spend this month, or supplier payment totals.

    Args:
        period: Time period. One of: today, yesterday, this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    totals = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS total_spend,
            SUM(net_total) AS net_spend,
            AVG(grand_total) AS avg_invoice_value
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        """,
        (start, end),
        as_dict=True,
    )
    top_suppliers = frappe.db.sql(
        """
        SELECT supplier, SUM(grand_total) AS spend, COUNT(*) AS invoices
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        GROUP BY supplier
        ORDER BY spend DESC
        LIMIT 5
        """,
        (start, end),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "summary": totals[0] if totals else {},
        "top_suppliers": top_suppliers,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_pending_purchase_orders(supplier: str = None, limit: int = 10) -> dict:
    """Get open purchase orders that have not yet been fully received or billed.

    Use when asked about outstanding POs, what's on order from suppliers,
    or what goods are expected to arrive.

    Args:
        supplier: Filter by supplier name (partial match). Optional.
        limit: Max number of orders to return. Defaults to 10.
    """
    filters = {
        "docstatus": 1,
        "status": ["in", ["To Receive and Bill", "To Bill", "To Receive"]],
    }
    if supplier:
        filters["supplier"] = ["like", f"%{supplier}%"]

    orders = frappe.db.get_all(
        "Purchase Order",
        filters=filters,
        fields=[
            "name", "supplier", "transaction_date", "schedule_date",
            "grand_total", "per_received", "per_billed", "status",
        ],
        order_by="schedule_date asc",
        limit=limit,
    )
    return {"count": len(orders), "orders": orders}


@mcp.tool(annotations={"readOnlyHint": True})
def get_supplier_outstanding(supplier: str) -> dict:
    """Get all outstanding (unpaid) purchase invoices for a supplier.

    Use when asked how much is owed to a supplier, accounts payable for
    a specific vendor, or overdue supplier payments.

    Args:
        supplier: Supplier name (partial match supported).
    """
    rows = frappe.db.sql(
        """
        SELECT
            name, supplier, posting_date, due_date,
            grand_total, outstanding_amount,
            DATEDIFF(CURDATE(), due_date) AS days_overdue
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          AND supplier LIKE %(supplier)s
        ORDER BY due_date ASC
        LIMIT 20
        """,
        {"supplier": f"%{supplier}%"},
        as_dict=True,
    )
    total_outstanding = sum(r["outstanding_amount"] for r in rows)
    return {
        "supplier_filter": supplier,
        "invoices": rows,
        "count": len(rows),
        "total_outstanding": total_outstanding,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_material_requests(status: str = "Pending", limit: int = 10) -> dict:
    """Get open material requests (internal purchase/transfer requests).

    Use when asked about pending stock requests, items requested by
    departments, or what is waiting to be purchased or transferred.

    Args:
        status: Filter by status. One of: Pending, Partially Ordered, Ordered. Defaults to Pending.
        limit: Max number of requests to return. Defaults to 10.
    """
    rows = frappe.db.get_all(
        "Material Request",
        filters={"docstatus": 1, "status": status},
        fields=[
            "name", "material_request_type", "transaction_date",
            "schedule_date", "status", "company",
        ],
        order_by="transaction_date desc",
        limit=limit,
    )
    return {"count": len(rows), "material_requests": rows}
