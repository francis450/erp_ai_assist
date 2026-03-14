"""Sales tools for the ERP AI Assistant."""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_date_range


@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_summary(period: str) -> dict:
    """Get a sales summary — total revenue, invoice count, and top customers.

    Use for questions like 'how did we do this month', 'what are total sales
    this week', 'revenue last month', 'show me today's sales'.

    Args:
        period: Time period. One of: today, yesterday, this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    totals = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS total_revenue,
            SUM(net_total) AS net_revenue,
            AVG(grand_total) AS avg_invoice_value
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        """,
        (start, end),
        as_dict=True,
    )
    top_customers = frappe.db.sql(
        """
        SELECT customer, SUM(grand_total) AS revenue, COUNT(*) AS invoices
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        GROUP BY customer
        ORDER BY revenue DESC
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
        "top_customers": top_customers,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_top_selling_items(period: str, limit: int = 5, by: str = "amount") -> dict:
    """Get the top selling items by quantity or revenue for a given period.

    Use when asked about best sellers, most popular items, or top products.

    Args:
        period: Time period. One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: How many top items to return. Defaults to 5.
        by: Rank by 'qty' (quantity sold) or 'amount' (revenue). Defaults to amount.
    """
    start, end = get_date_range(period)
    order_field = "total_qty" if by == "qty" else "total_revenue"
    items = frappe.db.sql(
        f"""
        SELECT
            sii.item_code,
            sii.item_name,
            SUM(sii.qty) AS total_qty,
            SUM(sii.amount) AS total_revenue
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        GROUP BY sii.item_code, sii.item_name
        ORDER BY {order_field} DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {"period": period, "ranked_by": by, "items": items}


@mcp.tool(annotations={"readOnlyHint": True})
def get_pending_orders(customer: str = None, limit: int = 10) -> dict:
    """Get a list of pending or open sales orders.

    Use when asked about outstanding orders, orders to fulfil, what's in
    the pipeline, or which customers have pending orders.

    Args:
        customer: Filter by customer name (partial match). Optional.
        limit: Max number of orders to return. Defaults to 10.
    """
    filters = {
        "docstatus": 1,
        "status": ["in", ["To Deliver and Bill", "To Bill", "To Deliver"]],
    }
    if customer:
        filters["customer"] = ["like", f"%{customer}%"]

    orders = frappe.db.get_all(
        "Sales Order",
        filters=filters,
        fields=[
            "name", "customer", "transaction_date", "delivery_date",
            "grand_total", "per_delivered", "per_billed", "status",
        ],
        order_by="delivery_date asc",
        limit=limit,
    )
    return {"count": len(orders), "orders": orders}


@mcp.tool(annotations={"readOnlyHint": True})
def get_customer_outstanding(customer: str) -> dict:
    """Get all outstanding (unpaid) sales invoices for a customer.

    Use when asked about a customer's balance, how much they owe,
    overdue invoices, or accounts receivable for a specific customer.

    Args:
        customer: Customer name (partial match supported).
    """
    rows = frappe.db.sql(
        """
        SELECT
            name, customer, posting_date, due_date,
            grand_total, outstanding_amount,
            DATEDIFF(CURDATE(), due_date) AS days_overdue
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          AND customer LIKE %(customer)s
        ORDER BY due_date ASC
        LIMIT 20
        """,
        {"customer": f"%{customer}%"},
        as_dict=True,
    )
    total_outstanding = sum(r["outstanding_amount"] for r in rows)
    return {
        "customer_filter": customer,
        "invoices": rows,
        "count": len(rows),
        "total_outstanding": total_outstanding,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_open_quotations(customer: str = None, limit: int = 10) -> dict:
    """Get open (submitted, not yet ordered) sales quotations.

    Use when asked about pending quotes, proposals, or pricing offered
    to customers that haven't been converted to orders yet.

    Args:
        customer: Filter by customer or party name. Optional.
        limit: Max number of quotations to return. Defaults to 10.
    """
    filters = {"docstatus": 1, "status": ["in", ["Open", "Replied"]]}
    if customer:
        filters["party_name"] = ["like", f"%{customer}%"]

    rows = frappe.db.get_all(
        "Quotation",
        filters=filters,
        fields=[
            "name", "party_name", "transaction_date", "valid_till",
            "grand_total", "status",
        ],
        order_by="transaction_date desc",
        limit=limit,
    )
    return {"count": len(rows), "quotations": rows}


@mcp.tool(annotations={"readOnlyHint": True})
def get_delivery_status(limit: int = 10) -> dict:
    """Get recent delivery notes and their status.

    Use when asked about deliveries, what has been shipped, what is
    pending delivery, or fulfilment status.

    Args:
        limit: Max number of delivery notes to return. Defaults to 10.
    """
    rows = frappe.db.get_all(
        "Delivery Note",
        filters={"docstatus": ["in", [0, 1]]},
        fields=[
            "name", "customer", "posting_date", "status",
            "grand_total", "per_billed",
        ],
        order_by="posting_date desc",
        limit=limit,
    )
    return {"count": len(rows), "deliveries": rows}
