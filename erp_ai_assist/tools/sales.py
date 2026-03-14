"""Sales tools for the ERP AI Assistant."""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_date_range, get_currency


# ── existing tools (kept intact) ─────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_summary(period: str) -> dict:
    """Get a sales summary — total revenue, invoice count, and top customers.

    Use for questions like 'how did we do this month', 'what are total sales
    this week', 'revenue last month', 'show me today's sales',
    'how many invoices did we create yesterday'.

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
            AVG(grand_total) AS avg_invoice_value,
            SUM(outstanding_amount) AS total_outstanding
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
        "currency": get_currency(),
        "period": period,
        "from": str(start),
        "to": str(end),
        "summary": totals[0] if totals else {},
        "top_customers": top_customers,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_top_selling_items(period: str, limit: int = 10, by: str = "amount") -> dict:
    """Get the top selling items by quantity or revenue for a given period.

    Use when asked about best sellers, most popular items, or top products.

    Args:
        period: Time period. One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: How many top items to return. Defaults to 10.
        by: Rank by 'qty' (quantity sold) or 'amount' (revenue). Defaults to amount.
    """
    start, end = get_date_range(period)
    order_field = "total_qty" if by == "qty" else "total_revenue"
    items = frappe.db.sql(
        f"""
        SELECT
            sii.item_code,
            sii.item_name,
            i.item_group,
            SUM(sii.qty) AS total_qty,
            SUM(sii.amount) AS total_revenue,
            AVG(sii.rate) AS avg_rate
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        JOIN `tabItem` i ON i.name = sii.item_code
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        GROUP BY sii.item_code, sii.item_name, i.item_group
        ORDER BY {order_field} DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {"period": period, "ranked_by": by, "items": items}


@mcp.tool(annotations={"readOnlyHint": True})
def get_pending_orders(customer: str = None, limit: int = 20) -> dict:
    """Get a list of pending or open sales orders.

    Use when asked about outstanding orders, orders to fulfil, what's in
    the pipeline, or which customers have pending orders.

    Args:
        customer: Filter by customer name (partial match). Optional.
        limit: Max number of orders to return. Defaults to 20.
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
    total_value = sum(o["grand_total"] or 0 for o in orders)
    return {"count": len(orders), "total_value": total_value, "orders": orders}


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
        "currency": get_currency(),
        "customer_filter": customer,
        "invoices": rows,
        "count": len(rows),
        "total_outstanding": total_outstanding,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_open_quotations(customer: str = None, limit: int = 20) -> dict:
    """Get open (submitted, not yet ordered) sales quotations.

    Use when asked about pending quotes, proposals, or pricing offered
    to customers that haven't been converted to orders yet.

    Args:
        customer: Filter by customer or party name. Optional.
        limit: Max number of quotations to return. Defaults to 20.
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
def get_delivery_status(customer: str = None, limit: int = 20) -> dict:
    """Get recent delivery notes and their status.

    Use when asked about deliveries, what has been shipped, what is
    pending delivery, or fulfilment status.

    Args:
        customer: Filter by customer name. Optional.
        limit: Max number of delivery notes to return. Defaults to 20.
    """
    filters = {"docstatus": ["in", [0, 1]]}
    if customer:
        filters["customer"] = ["like", f"%{customer}%"]

    rows = frappe.db.get_all(
        "Delivery Note",
        filters=filters,
        fields=[
            "name", "customer", "posting_date", "status",
            "grand_total", "per_billed",
        ],
        order_by="posting_date desc",
        limit=limit,
    )
    return {"count": len(rows), "deliveries": rows}


# ── new extended sales tools ──────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_by_item_group(period: str, limit: int = 20) -> dict:
    """Get sales revenue and quantity broken down by item group / product category.

    Use when asked about which product category sells the most, category
    performance, or sales breakdown by product type.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max categories to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            i.item_group,
            COUNT(DISTINCT si.name) AS invoice_count,
            SUM(sii.qty) AS total_qty,
            SUM(sii.amount) AS total_revenue
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        JOIN `tabItem` i ON i.name = sii.item_code
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        GROUP BY i.item_group
        ORDER BY total_revenue DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    total = sum(r["total_revenue"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_item_group": rows,
        "grand_total": total,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_customer_sales_history(customer: str, period: str = "this_year") -> dict:
    """Get full sales history for a specific customer — invoices, total spend, items bought.

    Use when asked about what a customer has bought, their purchase history,
    total spend, or invoice history for a customer.

    Args:
        customer: Customer name (partial match supported).
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_year.
    """
    start, end = get_date_range(period)
    invoices = frappe.db.sql(
        """
        SELECT
            name, posting_date, grand_total, outstanding_amount,
            status, payment_terms_template
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND customer LIKE %(customer)s
          AND posting_date BETWEEN %(start)s AND %(end)s
        ORDER BY posting_date DESC
        LIMIT 30
        """,
        {"customer": f"%{customer}%", "start": start, "end": end},
        as_dict=True,
    )
    top_items = frappe.db.sql(
        """
        SELECT
            sii.item_code, sii.item_name,
            SUM(sii.qty) AS total_qty,
            SUM(sii.amount) AS total_spend
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
          AND si.customer LIKE %(customer)s
          AND si.posting_date BETWEEN %(start)s AND %(end)s
        GROUP BY sii.item_code, sii.item_name
        ORDER BY total_spend DESC
        LIMIT 10
        """,
        {"customer": f"%{customer}%", "start": start, "end": end},
        as_dict=True,
    )
    total_spend = sum(i["grand_total"] or 0 for i in invoices)
    total_outstanding = sum(i["outstanding_amount"] or 0 for i in invoices)
    return {
        "customer_filter": customer,
        "period": period,
        "invoice_count": len(invoices),
        "total_spend": total_spend,
        "total_outstanding": total_outstanding,
        "invoices": invoices,
        "top_items_bought": top_items,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_trend(months: int = 6) -> dict:
    """Get month-by-month sales trend showing revenue, invoices, and avg order value.

    Use when asked about sales growth, monthly performance, trends over time,
    or how sales compare month to month.

    Args:
        months: How many past months to include. Defaults to 6.
    """
    rows = frappe.db.sql(
        """
        SELECT
            DATE_FORMAT(posting_date, '%%Y-%%m') AS month,
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS total_revenue,
            AVG(grand_total) AS avg_order_value,
            COUNT(DISTINCT customer) AS unique_customers
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
        GROUP BY DATE_FORMAT(posting_date, '%%Y-%%m')
        ORDER BY month ASC
        """,
        (months,),
        as_dict=True,
    )
    return {"months": months, "trend": rows}


@mcp.tool(annotations={"readOnlyHint": True})
def get_overdue_invoices(customer: str = None, min_days_overdue: int = 1, limit: int = 30) -> dict:
    """Get all overdue unpaid sales invoices with aging buckets.

    Use when asked about overdue invoices, late payments, aging report,
    who hasn't paid, or collections follow-up list.

    Args:
        customer: Filter by customer name. Optional.
        min_days_overdue: Only include invoices overdue by at least this many days. Defaults to 1.
        limit: Max rows to return. Defaults to 30.
    """
    customer_condition = "AND customer LIKE %(customer)s" if customer else ""
    params = {
        "min_days": min_days_overdue,
        "limit": limit,
        **({"customer": f"%{customer}%"} if customer else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            name,
            customer,
            posting_date,
            due_date,
            grand_total,
            outstanding_amount,
            DATEDIFF(CURDATE(), due_date) AS days_overdue,
            CASE
                WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 1  AND 30  THEN '1-30 days'
                WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 31 AND 60  THEN '31-60 days'
                WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 61 AND 90  THEN '61-90 days'
                ELSE '90+ days'
            END AS aging_bucket
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          AND due_date < CURDATE()
          AND DATEDIFF(CURDATE(), due_date) >= %(min_days)s
          {customer_condition}
        ORDER BY days_overdue DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    total_overdue = sum(r["outstanding_amount"] or 0 for r in rows)
    buckets: dict = {}
    for r in rows:
        b = r["aging_bucket"]
        buckets[b] = buckets.get(b, 0) + (r["outstanding_amount"] or 0)
    return {
        "currency": get_currency(),
        "overdue_invoices": rows,
        "count": len(rows),
        "total_overdue": total_overdue,
        "aging_buckets": buckets,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_by_sales_person(period: str, limit: int = 20) -> dict:
    """Get sales performance broken down by sales person / representative.

    Use when asked about sales rep performance, who is selling the most,
    team performance, or sales person targets vs achievement.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max sales persons to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            st.sales_person,
            COUNT(DISTINCT si.name) AS invoice_count,
            COUNT(DISTINCT si.customer) AS customer_count,
            SUM(si.grand_total * st.allocated_percentage / 100) AS attributed_revenue,
            SUM(si.grand_total) AS total_invoice_value
        FROM `tabSales Team` st
        JOIN `tabSales Invoice` si ON si.name = st.parent AND st.parenttype = 'Sales Invoice'
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        GROUP BY st.sales_person
        ORDER BY attributed_revenue DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_sales_person": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_returns(period: str, customer: str = None, limit: int = 20) -> dict:
    """Get sales returns (credit notes) raised in a period.

    Use when asked about returns, credit notes, refunds, goods returned
    by customers, or how much was returned.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        customer: Filter by customer name. Optional.
        limit: Max rows to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    filters = {
        "docstatus": 1,
        "is_return": 1,
        "posting_date": ["between", [start, end]],
    }
    if customer:
        filters["customer"] = ["like", f"%{customer}%"]

    rows = frappe.db.get_all(
        "Sales Invoice",
        filters=filters,
        fields=[
            "name", "customer", "posting_date",
            "grand_total", "return_against", "remarks",
        ],
        order_by="posting_date desc",
        limit=limit,
    )
    total_returned = sum(abs(r["grand_total"] or 0) for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "returns": rows,
        "count": len(rows),
        "total_value_returned": total_returned,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_payment_collections(period: str, limit: int = 30) -> dict:
    """Get payments received against sales invoices in a period.

    Use when asked about payments collected, cash received, money paid by
    customers, or collection performance for a period.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max rows to return. Defaults to 30.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            pe.name,
            pe.party AS customer,
            pe.posting_date,
            pe.paid_amount,
            pe.mode_of_payment,
            pe.reference_no
        FROM `tabPayment Entry` pe
        WHERE pe.docstatus = 1
          AND pe.payment_type = 'Receive'
          AND pe.party_type = 'Customer'
          AND pe.posting_date BETWEEN %s AND %s
        ORDER BY pe.posting_date DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    total_collected = sum(r["paid_amount"] or 0 for r in rows)

    by_mode = frappe.db.sql(
        """
        SELECT
            mode_of_payment,
            COUNT(*) AS count,
            SUM(paid_amount) AS total
        FROM `tabPayment Entry`
        WHERE docstatus = 1
          AND payment_type = 'Receive'
          AND party_type = 'Customer'
          AND posting_date BETWEEN %s AND %s
        GROUP BY mode_of_payment
        ORDER BY total DESC
        """,
        (start, end),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "payments": rows,
        "count": len(rows),
        "total_collected": total_collected,
        "by_mode_of_payment": by_mode,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_customer_ranking(period: str, limit: int = 20) -> dict:
    """Get customers ranked by revenue, with invoice count and average order value.

    Use when asked about top customers, best clients, customer contribution,
    or which customers drive the most revenue.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Number of customers to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            customer,
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS total_revenue,
            AVG(grand_total) AS avg_order_value,
            SUM(outstanding_amount) AS outstanding
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        GROUP BY customer
        ORDER BY total_revenue DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    grand_total = sum(r["total_revenue"] or 0 for r in rows)
    for r in rows:
        r["revenue_share_pct"] = round(
            (r["total_revenue"] or 0) / grand_total * 100, 1
        ) if grand_total else 0
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "customers": rows,
        "total_revenue": grand_total,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_quotation_conversion(period: str) -> dict:
    """Get quotation-to-order conversion rate — how many quotes became sales orders.

    Use when asked about quote conversion, win rate, how effective quoting is,
    or how many quotations resulted in actual orders.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    totals = frappe.db.sql(
        """
        SELECT
            status,
            COUNT(*) AS count,
            SUM(grand_total) AS value
        FROM `tabQuotation`
        WHERE docstatus = 1
          AND transaction_date BETWEEN %s AND %s
        GROUP BY status
        """,
        (start, end),
        as_dict=True,
    )
    by_status = {r["status"]: {"count": r["count"], "value": r["value"]} for r in totals}
    ordered = by_status.get("Ordered", {}).get("count", 0)
    total_submitted = sum(r["count"] for r in totals)
    conversion_rate = round(ordered / total_submitted * 100, 1) if total_submitted else 0
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "total_quotations": total_submitted,
        "converted_to_order": ordered,
        "conversion_rate_pct": conversion_rate,
        "by_status": by_status,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_order_fulfilment_rate(period: str) -> dict:
    """Get delivery fulfilment rate — what % of sales orders were fully delivered.

    Use when asked about fulfilment performance, delivery rate, how many orders
    were completed, or operational efficiency.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            status,
            COUNT(*) AS count,
            SUM(grand_total) AS value
        FROM `tabSales Order`
        WHERE docstatus = 1
          AND transaction_date BETWEEN %s AND %s
        GROUP BY status
        """,
        (start, end),
        as_dict=True,
    )
    by_status = {r["status"]: {"count": r["count"], "value": r["value"]} for r in rows}
    total = sum(r["count"] for r in rows)
    completed = by_status.get("Completed", {}).get("count", 0)
    rate = round(completed / total * 100, 1) if total else 0
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "total_orders": total,
        "fully_completed": completed,
        "fulfilment_rate_pct": rate,
        "by_status": by_status,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_new_customers(period: str, limit: int = 20) -> dict:
    """Get customers who placed their first-ever order in a given period.

    Use when asked about new customers acquired, first-time buyers,
    new business won, or customer acquisition in a period.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max number of customers to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            si.customer,
            MIN(si.posting_date) AS first_invoice_date,
            SUM(si.grand_total) AS total_spend,
            COUNT(*) AS invoice_count
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
        GROUP BY si.customer
        HAVING first_invoice_date BETWEEN %s AND %s
        ORDER BY first_invoice_date DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "new_customers": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_inactive_customers(days: int = 90, limit: int = 30) -> dict:
    """Get customers who have not purchased in the last N days (lapsed / at-risk).

    Use when asked about inactive customers, who hasn't bought recently,
    customer churn, lapsed accounts, or retention risk.

    Args:
        days: Flag customers with no purchase in this many days. Defaults to 90.
        limit: Max customers to return. Defaults to 30.
    """
    rows = frappe.db.sql(
        """
        SELECT
            customer,
            MAX(posting_date) AS last_purchase_date,
            DATEDIFF(CURDATE(), MAX(posting_date)) AS days_since_purchase,
            COUNT(*) AS total_invoices,
            SUM(grand_total) AS lifetime_revenue
        FROM `tabSales Invoice`
        WHERE docstatus = 1
        GROUP BY customer
        HAVING days_since_purchase >= %s
        ORDER BY days_since_purchase DESC
        LIMIT %s
        """,
        (days, limit),
        as_dict=True,
    )
    return {
        "inactive_days_threshold": days,
        "inactive_customers": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_daily_sales_trend(period: str) -> dict:
    """Get day-by-day sales figures for a period.

    Use when asked for a daily breakdown of sales, daily revenue chart data,
    which day had the most sales, or day-level detail within a period.

    Args:
        period: One of: this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            posting_date,
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS revenue,
            COUNT(DISTINCT customer) AS unique_customers
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        GROUP BY posting_date
        ORDER BY posting_date ASC
        """,
        (start, end),
        as_dict=True,
    )
    total = sum(r["revenue"] or 0 for r in rows)
    best_day = max(rows, key=lambda r: r["revenue"] or 0) if rows else None
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "daily": rows,
        "total_revenue": total,
        "best_day": best_day,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_average_days_to_pay(period: str) -> dict:
    """Get the average number of days customers take to pay invoices (DSO).

    Use when asked about days sales outstanding, how long customers take to pay,
    payment speed, or cash conversion cycle.

    Args:
        period: One of: this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            si.customer,
            AVG(DATEDIFF(pe_ref.modified, si.posting_date)) AS avg_days_to_pay,
            COUNT(DISTINCT si.name) AS paid_invoices
        FROM `tabSales Invoice` si
        JOIN `tabPayment Entry Reference` per ON per.reference_name = si.name
        JOIN `tabPayment Entry` pe_ref ON pe_ref.name = per.parent
            AND pe_ref.docstatus = 1
            AND pe_ref.payment_type = 'Receive'
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        GROUP BY si.customer
        HAVING avg_days_to_pay IS NOT NULL
        ORDER BY avg_days_to_pay DESC
        LIMIT 20
        """,
        (start, end),
        as_dict=True,
    )
    overall = frappe.db.sql(
        """
        SELECT AVG(DATEDIFF(pe_ref.modified, si.posting_date)) AS overall_dso
        FROM `tabSales Invoice` si
        JOIN `tabPayment Entry Reference` per ON per.reference_name = si.name
        JOIN `tabPayment Entry` pe_ref ON pe_ref.name = per.parent
            AND pe_ref.docstatus = 1
            AND pe_ref.payment_type = 'Receive'
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        """,
        (start, end),
        as_dict=True,
    )
    return {
        "period": period,
        "overall_dso_days": round(overall[0]["overall_dso"] or 0, 1) if overall else None,
        "by_customer": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_undelivered_orders(customer: str = None, overdue_only: bool = False, limit: int = 20) -> dict:
    """Get sales orders where delivery is pending or overdue.

    Use when asked about undelivered orders, what hasn't been shipped,
    delivery backlog, or overdue deliveries.

    Args:
        customer: Filter by customer name. Optional.
        overdue_only: If True, only return orders past their delivery date. Defaults to False.
        limit: Max rows to return. Defaults to 20.
    """
    filters = {
        "docstatus": 1,
        "per_delivered": ["<", 100],
        "status": ["in", ["To Deliver and Bill", "To Deliver"]],
    }
    if customer:
        filters["customer"] = ["like", f"%{customer}%"]
    if overdue_only:
        filters["delivery_date"] = ["<", frappe.utils.today()]

    rows = frappe.db.get_all(
        "Sales Order",
        filters=filters,
        fields=[
            "name", "customer", "transaction_date", "delivery_date",
            "grand_total", "per_delivered", "status",
        ],
        order_by="delivery_date asc",
        limit=limit,
    )
    for r in rows:
        if r["delivery_date"]:
            import datetime
            delta = (frappe.utils.getdate(r["delivery_date"]) - datetime.date.today()).days
            r["days_until_due"] = delta  # negative = overdue
    return {"count": len(rows), "orders": rows}


@mcp.tool(annotations={"readOnlyHint": True})
def get_unbilled_deliveries(customer: str = None, limit: int = 20) -> dict:
    """Get delivery notes that have been dispatched but not yet invoiced.

    Use when asked about unbilled deliveries, goods shipped but not billed,
    revenue not yet captured, or billing backlog.

    Args:
        customer: Filter by customer name. Optional.
        limit: Max rows to return. Defaults to 20.
    """
    filters = {
        "docstatus": 1,
        "per_billed": ["<", 100],
        "status": ["in", ["To Bill"]],
    }
    if customer:
        filters["customer"] = ["like", f"%{customer}%"]

    rows = frappe.db.get_all(
        "Delivery Note",
        filters=filters,
        fields=[
            "name", "customer", "posting_date",
            "grand_total", "per_billed", "status",
        ],
        order_by="posting_date asc",
        limit=limit,
    )
    total_unbilled = sum(
        (r["grand_total"] or 0) * (1 - (r["per_billed"] or 0) / 100) for r in rows
    )
    return {
        "count": len(rows),
        "estimated_unbilled_value": round(total_unbilled, 2),
        "deliveries": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_sales_by_territory(period: str, limit: int = 20) -> dict:
    """Get sales revenue broken down by territory / region.

    Use when asked about regional sales, which territory is performing best,
    geographic breakdown of revenue, or area-wise sales.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max territories to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            si.territory,
            COUNT(*) AS invoice_count,
            COUNT(DISTINCT si.customer) AS customer_count,
            SUM(si.grand_total) AS total_revenue
        FROM `tabSales Invoice` si
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
          AND si.territory IS NOT NULL
        GROUP BY si.territory
        ORDER BY total_revenue DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_territory": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_cancelled_invoices(period: str, limit: int = 20) -> dict:
    """Get cancelled sales invoices for a period.

    Use when asked about cancellations, voided invoices,
    or how much revenue was cancelled.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max rows to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.get_all(
        "Sales Invoice",
        filters={
            "docstatus": 2,
            "posting_date": ["between", [start, end]],
        },
        fields=[
            "name", "customer", "posting_date",
            "grand_total", "amended_from",
        ],
        order_by="posting_date desc",
        limit=limit,
    )
    total_cancelled = sum(r["grand_total"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "cancelled_invoices": rows,
        "count": len(rows),
        "total_value_cancelled": total_cancelled,
    }
