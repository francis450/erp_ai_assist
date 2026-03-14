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


# ── new extended purchase tools ───────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_by_item_group(period: str, limit: int = 20) -> dict:
    """Get purchase spend broken down by item group / product category.

    Use when asked about what categories of items we buy the most,
    procurement breakdown by product type, or category-level spend.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max categories. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            i.item_group,
            COUNT(DISTINCT pi.name) AS invoice_count,
            SUM(pii.qty) AS total_qty,
            SUM(pii.amount) AS total_spend
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        JOIN `tabItem` i ON i.name = pii.item_code
        WHERE pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
        GROUP BY i.item_group
        ORDER BY total_spend DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_item_group": rows,
        "total_spend": sum(r["total_spend"] or 0 for r in rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_supplier_ranking(period: str, limit: int = 20) -> dict:
    """Get suppliers ranked by total purchase spend for a period.

    Use when asked about top suppliers, which vendor we buy from most,
    supplier spend analysis, or vendor ranking.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Number of suppliers to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            supplier,
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS total_spend,
            AVG(grand_total) AS avg_invoice_value,
            SUM(outstanding_amount) AS outstanding
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND posting_date BETWEEN %s AND %s
        GROUP BY supplier
        ORDER BY total_spend DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    grand_total = sum(r["total_spend"] or 0 for r in rows)
    for r in rows:
        r["spend_share_pct"] = round(
            (r["total_spend"] or 0) / grand_total * 100, 1
        ) if grand_total else 0
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "suppliers": rows,
        "total_spend": grand_total,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_trend(months: int = 6) -> dict:
    """Get month-by-month purchase trend showing spend, invoice count, and top supplier.

    Use when asked about purchase trends, monthly procurement spend,
    how purchasing has changed over time, or spend patterns.

    Args:
        months: How many past months to include. Defaults to 6.
    """
    rows = frappe.db.sql(
        """
        SELECT
            DATE_FORMAT(posting_date, '%%Y-%%m') AS month,
            COUNT(*) AS invoice_count,
            SUM(grand_total) AS total_spend,
            AVG(grand_total) AS avg_invoice_value,
            COUNT(DISTINCT supplier) AS unique_suppliers
        FROM `tabPurchase Invoice`
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
def get_purchase_returns(period: str, supplier: str = None, limit: int = 20) -> dict:
    """Get purchase returns (debit notes) raised in a period.

    Use when asked about goods returned to suppliers, debit notes,
    purchase returns, or how much stock was sent back.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        supplier: Filter by supplier name. Optional.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    filters = {
        "docstatus": 1,
        "is_return": 1,
        "posting_date": ["between", [start, end]],
    }
    if supplier:
        filters["supplier"] = ["like", f"%{supplier}%"]

    rows = frappe.db.get_all(
        "Purchase Invoice",
        filters=filters,
        fields=[
            "name", "supplier", "posting_date",
            "grand_total", "return_against", "remarks",
        ],
        order_by="posting_date desc",
        limit=limit,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "returns": rows,
        "count": len(rows),
        "total_value_returned": sum(abs(r["grand_total"] or 0) for r in rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_supplier_history(supplier: str, period: str = "this_year") -> dict:
    """Get full purchase history for a specific supplier — invoices, items, spend.

    Use when asked what we have bought from a supplier, their invoice history,
    total spend with a vendor, or items procured from a supplier.

    Args:
        supplier: Supplier name (partial match supported).
        period: One of: this_week, this_month, last_month, this_year. Defaults to this_year.
    """
    start, end = get_date_range(period)
    invoices = frappe.db.sql(
        """
        SELECT name, posting_date, grand_total, outstanding_amount, status
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND supplier LIKE %(supplier)s
          AND posting_date BETWEEN %(start)s AND %(end)s
        ORDER BY posting_date DESC
        LIMIT 30
        """,
        {"supplier": f"%{supplier}%", "start": start, "end": end},
        as_dict=True,
    )
    top_items = frappe.db.sql(
        """
        SELECT
            pii.item_code, pii.item_name,
            SUM(pii.qty) AS total_qty,
            SUM(pii.amount) AS total_spend
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.docstatus = 1
          AND pi.supplier LIKE %(supplier)s
          AND pi.posting_date BETWEEN %(start)s AND %(end)s
        GROUP BY pii.item_code, pii.item_name
        ORDER BY total_spend DESC
        LIMIT 10
        """,
        {"supplier": f"%{supplier}%", "start": start, "end": end},
        as_dict=True,
    )
    return {
        "supplier_filter": supplier,
        "period": period,
        "invoice_count": len(invoices),
        "total_spend": sum(i["grand_total"] or 0 for i in invoices),
        "total_outstanding": sum(i["outstanding_amount"] or 0 for i in invoices),
        "invoices": invoices,
        "top_items_purchased": top_items,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_overdue_payables(supplier: str = None, min_days_overdue: int = 1, limit: int = 30) -> dict:
    """Get overdue purchase invoices with aging buckets — what we're late paying.

    Use when asked about overdue supplier payments, late bills, AP aging,
    or which suppliers we owe money that is past due.

    Args:
        supplier: Filter by supplier name. Optional.
        min_days_overdue: Only include invoices overdue by at least this many days. Defaults to 1.
        limit: Max rows. Defaults to 30.
    """
    sup_condition = "AND supplier LIKE %(supplier)s" if supplier else ""
    params = {
        "min_days": min_days_overdue,
        "limit": limit,
        **({"supplier": f"%{supplier}%"} if supplier else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            name, supplier, posting_date, due_date,
            grand_total, outstanding_amount,
            DATEDIFF(CURDATE(), due_date) AS days_overdue,
            CASE
                WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 1  AND 30  THEN '1-30 days'
                WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 31 AND 60  THEN '31-60 days'
                WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 61 AND 90  THEN '61-90 days'
                ELSE '90+ days'
            END AS aging_bucket
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          AND due_date < CURDATE()
          AND DATEDIFF(CURDATE(), due_date) >= %(min_days)s
          {sup_condition}
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
        "overdue_payables": rows,
        "count": len(rows),
        "total_overdue": total_overdue,
        "aging_buckets": buckets,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_top_purchased_items(period: str, limit: int = 10, by: str = "amount") -> dict:
    """Get the most purchased items by quantity or spend for a period.

    Use when asked about what items we buy most, top procured items,
    or which products have the highest procurement spend.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: How many items to return. Defaults to 10.
        by: Rank by 'qty' (quantity bought) or 'amount' (spend). Defaults to amount.
    """
    start, end = get_date_range(period)
    order_field = "total_qty" if by == "qty" else "total_spend"
    rows = frappe.db.sql(
        f"""
        SELECT
            pii.item_code,
            pii.item_name,
            i.item_group,
            SUM(pii.qty) AS total_qty,
            SUM(pii.amount) AS total_spend,
            AVG(pii.rate) AS avg_rate,
            COUNT(DISTINCT pi.supplier) AS supplier_count
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        JOIN `tabItem` i ON i.name = pii.item_code
        WHERE pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
        GROUP BY pii.item_code, pii.item_name, i.item_group
        ORDER BY {order_field} DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {"period": period, "ranked_by": by, "items": rows}


@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_order_vs_received(period: str, supplier: str = None, limit: int = 20) -> dict:
    """Compare what was ordered vs what has actually been received per PO.

    Use when asked about partially received orders, delivery shortfalls,
    receiving gaps, or how much of each PO has arrived.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        supplier: Filter by supplier name. Optional.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    filters = {
        "docstatus": 1,
        "transaction_date": ["between", [start, end]],
    }
    if supplier:
        filters["supplier"] = ["like", f"%{supplier}%"]

    rows = frappe.db.get_all(
        "Purchase Order",
        filters=filters,
        fields=[
            "name", "supplier", "transaction_date", "schedule_date",
            "grand_total", "per_received", "per_billed", "status",
        ],
        order_by="transaction_date desc",
        limit=limit,
    )
    for r in rows:
        r["receipt_gap_pct"] = round(100 - (r["per_received"] or 0), 1)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "orders": rows,
        "count": len(rows),
        "fully_received": sum(1 for r in rows if (r["per_received"] or 0) >= 100),
        "partially_received": sum(1 for r in rows if 0 < (r["per_received"] or 0) < 100),
        "not_received": sum(1 for r in rows if (r["per_received"] or 0) == 0),
    }


# ── end-to-end buying tools ───────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_requisition_stats(period: str = "this_month", department: str = None) -> dict:
    """Get material request / requisition analytics — volumes, status breakdown, and cycle times.

    Use when asked about requisition pipeline, how many MRs were raised, which
    department raises the most requests, or how quickly MRs are being processed.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        department: Filter by department name (partial match). Optional.
    """
    start, end = get_date_range(period)
    dept_condition = "AND mr.department LIKE %(department)s" if department else ""
    params = {
        "start": start, "end": end,
        **({"department": f"%{department}%"} if department else {}),
    }

    by_status = frappe.db.sql(
        f"""
        SELECT
            mr.status,
            mr.material_request_type,
            COUNT(*) AS count
        FROM `tabMaterial Request` mr
        WHERE mr.docstatus IN (0, 1)
          AND mr.transaction_date BETWEEN %(start)s AND %(end)s
          {dept_condition}
        GROUP BY mr.status, mr.material_request_type
        ORDER BY count DESC
        """,
        params,
        as_dict=True,
    )

    by_dept = frappe.db.sql(
        f"""
        SELECT
            COALESCE(mr.department, 'Unassigned') AS department,
            COUNT(*) AS request_count,
            SUM(CASE WHEN mr.docstatus = 1 THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN mr.docstatus = 0 THEN 1 ELSE 0 END) AS pending_approval
        FROM `tabMaterial Request` mr
        WHERE mr.transaction_date BETWEEN %(start)s AND %(end)s
          {dept_condition}
        GROUP BY mr.department
        ORDER BY request_count DESC
        """,
        params,
        as_dict=True,
    )

    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_status_and_type": by_status,
        "by_department": by_dept,
        "total_requests": sum(r["count"] for r in by_status),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_rfq_summary(period: str = "this_month", supplier: str = None, limit: int = 20) -> dict:
    """Get Request for Quotation (RFQ) status — sent, responded, and conversion to PO.

    Use when asked about RFQs, supplier quote requests, how many suppliers
    responded to RFQs, or quote request status.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        supplier: Filter by supplier name. Optional.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    conditions = ["rfq.docstatus = 1", "rfq.transaction_date BETWEEN %(start)s AND %(end)s"]
    params: dict = {"start": start, "end": end, "limit": limit}
    if supplier:
        conditions.append("rfqs.supplier LIKE %(supplier)s")
        params["supplier"] = f"%{supplier}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            rfq.name,
            rfq.transaction_date,
            rfq.status,
            rfqs.supplier,
            rfqs.quote_status,
            rfq.message_for_supplier
        FROM `tabRequest for Quotation` rfq
        JOIN `tabRequest for Quotation Supplier` rfqs ON rfqs.parent = rfq.name
        WHERE {where}
        ORDER BY rfq.transaction_date DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )

    by_status = frappe.db.sql(
        f"""
        SELECT rfqs.quote_status, COUNT(*) AS count
        FROM `tabRequest for Quotation` rfq
        JOIN `tabRequest for Quotation Supplier` rfqs ON rfqs.parent = rfq.name
        WHERE {where}
        GROUP BY rfqs.quote_status
        """,
        params,
        as_dict=True,
    )

    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "rfqs": rows,
        "count": len(rows),
        "by_quote_status": by_status,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_supplier_quotation_comparison(item_name: str, limit: int = 10) -> dict:
    """Compare supplier quotes for the same item — price, lead time, and supplier.

    Use when asked which supplier offers the best price for an item,
    comparing quotes, or evaluating vendor bids for a product.

    Args:
        item_name: Partial or full item name or item code.
        limit: Max quotation lines to return. Defaults to 10.
    """
    rows = frappe.db.sql(
        """
        SELECT
            sqi.item_code,
            sqi.item_name,
            sq.supplier,
            sq.transaction_date,
            sq.valid_till,
            sqi.qty,
            sqi.rate,
            sqi.uom,
            sq.name AS quotation_no,
            sq.status
        FROM `tabSupplier Quotation Item` sqi
        JOIN `tabSupplier Quotation` sq ON sq.name = sqi.parent
        WHERE sq.docstatus = 1
          AND sq.status NOT IN ('Cancelled', 'Expired')
          AND (sqi.item_name LIKE %(item_name)s OR sqi.item_code LIKE %(item_name)s)
        ORDER BY sqi.rate ASC
        LIMIT %(limit)s
        """,
        {"item_name": f"%{item_name}%", "limit": limit},
        as_dict=True,
    )
    if not rows:
        return {"error": f"No supplier quotations found for '{item_name}'"}

    lowest = rows[0] if rows else None
    return {
        "item_filter": item_name,
        "quotes": rows,
        "count": len(rows),
        "lowest_price_quote": lowest,
        "price_range": {
            "min": min(r["rate"] or 0 for r in rows),
            "max": max(r["rate"] or 0 for r in rows),
        },
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_supplier_performance(supplier: str = None, period: str = "this_year") -> dict:
    """Get supplier delivery performance — on-time rate, receipt vs order gap, return rate.

    Use when asked about supplier reliability, which supplier delivers on time,
    vendor scorecards, or supplier performance metrics.

    Args:
        supplier: Filter by supplier name (partial match). Optional — omit for all suppliers.
        period: One of: this_month, last_month, this_year. Defaults to this_year.
    """
    start, end = get_date_range(period)
    sup_condition = "AND po.supplier LIKE %(supplier)s" if supplier else ""
    params = {
        "start": start, "end": end,
        **({"supplier": f"%{supplier}%"} if supplier else {}),
    }

    delivery = frappe.db.sql(
        f"""
        SELECT
            po.supplier,
            COUNT(DISTINCT po.name) AS total_pos,
            SUM(CASE WHEN po.per_received >= 100 THEN 1 ELSE 0 END) AS fully_delivered,
            AVG(po.per_received) AS avg_receipt_pct,
            AVG(
                DATEDIFF(
                    COALESCE((
                        SELECT MIN(pr.posting_date)
                        FROM `tabPurchase Receipt` pr
                        JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
                        JOIN `tabPurchase Order Item` poi ON poi.name = pri.purchase_order_item
                        WHERE poi.parent = po.name AND pr.docstatus = 1
                    ), CURDATE()),
                    po.schedule_date
                )
            ) AS avg_delivery_delay_days
        FROM `tabPurchase Order` po
        WHERE po.docstatus = 1
          AND po.transaction_date BETWEEN %(start)s AND %(end)s
          {sup_condition}
        GROUP BY po.supplier
        ORDER BY avg_receipt_pct DESC
        LIMIT 20
        """,
        params,
        as_dict=True,
    )

    returns = frappe.db.sql(
        f"""
        SELECT
            pi.supplier,
            COUNT(*) AS return_count,
            SUM(ABS(pi.grand_total)) AS returned_value
        FROM `tabPurchase Invoice` pi
        WHERE pi.docstatus = 1
          AND pi.is_return = 1
          AND pi.posting_date BETWEEN %(start)s AND %(end)s
          {sup_condition}
        GROUP BY pi.supplier
        """,
        params,
        as_dict=True,
    )
    return_map = {r["supplier"]: r for r in returns}

    for row in delivery:
        ret = return_map.get(row["supplier"], {})
        row["return_count"]   = ret.get("return_count", 0)
        row["returned_value"] = ret.get("returned_value", 0)
        row["on_time_rate_pct"] = round(
            (row["fully_delivered"] or 0) / (row["total_pos"] or 1) * 100, 1
        )

    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "supplier_performance": delivery,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_price_variance(period: str = "this_month", supplier: str = None, limit: int = 20) -> dict:
    """Compare purchase order prices vs actual invoice prices — identify over-billing.

    Use when asked about price discrepancies, invoice vs PO price differences,
    over-billing by suppliers, or purchase price variance.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        supplier: Filter by supplier name. Optional.
        limit: Max line items to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    sup_condition = "AND pi.supplier LIKE %(supplier)s" if supplier else ""
    params = {
        "start": start, "end": end, "limit": limit,
        **({"supplier": f"%{supplier}%"} if supplier else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            pi.supplier,
            pi.name AS invoice_no,
            pi.posting_date,
            pii.item_code,
            pii.item_name,
            pii.qty,
            pii.rate AS invoice_rate,
            pii.purchase_order_item,
            poi.rate AS po_rate,
            (pii.rate - COALESCE(poi.rate, pii.rate)) AS rate_variance,
            ((pii.rate - COALESCE(poi.rate, pii.rate)) * pii.qty) AS total_variance
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        LEFT JOIN `tabPurchase Order Item` poi ON poi.name = pii.purchase_order_item
        WHERE pi.docstatus = 1
          AND pi.posting_date BETWEEN %(start)s AND %(end)s
          AND poi.rate IS NOT NULL
          AND ABS(pii.rate - poi.rate) > 0.01
          {sup_condition}
        ORDER BY ABS(total_variance) DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    total_variance = sum(r["total_variance"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "variances": rows,
        "count": len(rows),
        "total_overbilling": total_variance,
        "note": "Positive variance = invoiced higher than PO rate",
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_cycle_time(period: str = "this_year", supplier: str = None) -> dict:
    """Get average time (days) from Purchase Order to Goods Receipt per supplier.

    Use when asked about lead times, how long suppliers take to deliver,
    procurement cycle time, or supply chain efficiency.

    Args:
        period: One of: this_month, last_month, this_year. Defaults to this_year.
        supplier: Filter by supplier name. Optional.
    """
    start, end = get_date_range(period)
    sup_condition = "AND po.supplier LIKE %(supplier)s" if supplier else ""
    params = {
        "start": start, "end": end,
        **({"supplier": f"%{supplier}%"} if supplier else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            po.supplier,
            COUNT(DISTINCT po.name) AS po_count,
            AVG(DATEDIFF(pr.posting_date, po.transaction_date)) AS avg_lead_days,
            MIN(DATEDIFF(pr.posting_date, po.transaction_date)) AS min_lead_days,
            MAX(DATEDIFF(pr.posting_date, po.transaction_date)) AS max_lead_days
        FROM `tabPurchase Order` po
        JOIN `tabPurchase Receipt Item` pri ON pri.purchase_order = po.name
        JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent AND pr.docstatus = 1
        WHERE po.docstatus = 1
          AND po.transaction_date BETWEEN %(start)s AND %(end)s
          {sup_condition}
        GROUP BY po.supplier
        ORDER BY avg_lead_days ASC
        """,
        params,
        as_dict=True,
    )
    overall_avg = (
        sum(r["avg_lead_days"] or 0 for r in rows) / len(rows)
    ) if rows else 0
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "overall_avg_lead_days": round(overall_avg, 1),
        "by_supplier": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_three_way_match_exceptions(period: str = "this_month", limit: int = 20) -> dict:
    """Find purchase invoices where billed qty or amount does not match the PO or receipt.

    Use when asked about three-way match failures, billing discrepancies,
    invoices not matching POs or GRNs, or procurement audit exceptions.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            pi.name AS invoice_no,
            pi.supplier,
            pi.posting_date,
            pi.grand_total AS invoice_total,
            pii.item_code,
            pii.item_name,
            pii.qty AS billed_qty,
            pii.rate AS billed_rate,
            poi.qty AS ordered_qty,
            poi.rate AS ordered_rate,
            pri.qty AS received_qty,
            (pii.qty - COALESCE(pri.qty, 0)) AS qty_vs_receipt,
            (pii.rate - COALESCE(poi.rate, pii.rate)) AS rate_vs_po
        FROM `tabPurchase Invoice Item` pii
        JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        LEFT JOIN `tabPurchase Order Item` poi ON poi.name = pii.purchase_order_item
        LEFT JOIN `tabPurchase Receipt Item` pri ON pri.name = pii.pr_detail
        WHERE pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
          AND (
              ABS(pii.qty - COALESCE(pri.qty, pii.qty)) > 0.001
              OR ABS(pii.rate - COALESCE(poi.rate, pii.rate)) > 0.01
          )
        ORDER BY ABS(pii.qty - COALESCE(pri.qty, 0)) DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "exceptions": rows,
        "count": len(rows),
        "note": "qty_vs_receipt > 0 means invoiced more than received; rate_vs_po > 0 means billed above PO rate",
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_ap_aging_full(limit: int = 30) -> dict:
    """Get full accounts payable aging — all outstanding payables bucketed by age.

    Use when asked about the AP aging report, full payables breakdown,
    how much is due in 30/60/90 days, or total outstanding by age.

    Args:
        limit: Max suppliers to return. Defaults to 30.
    """
    rows = frappe.db.sql(
        """
        SELECT
            supplier,
            SUM(outstanding_amount) AS total_outstanding,
            SUM(CASE WHEN due_date >= CURDATE() THEN outstanding_amount ELSE 0 END) AS current_not_due,
            SUM(CASE WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 1  AND 30  THEN outstanding_amount ELSE 0 END) AS overdue_1_30,
            SUM(CASE WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 31 AND 60  THEN outstanding_amount ELSE 0 END) AS overdue_31_60,
            SUM(CASE WHEN DATEDIFF(CURDATE(), due_date) BETWEEN 61 AND 90  THEN outstanding_amount ELSE 0 END) AS overdue_61_90,
            SUM(CASE WHEN DATEDIFF(CURDATE(), due_date) > 90              THEN outstanding_amount ELSE 0 END) AS overdue_90_plus,
            MIN(due_date) AS oldest_due_date
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
        GROUP BY supplier
        ORDER BY total_outstanding DESC
        LIMIT %s
        """,
        (limit,),
        as_dict=True,
    )
    totals = {
        "total_outstanding": sum(r["total_outstanding"] or 0 for r in rows),
        "current_not_due":   sum(r["current_not_due"]   or 0 for r in rows),
        "overdue_1_30":      sum(r["overdue_1_30"]       or 0 for r in rows),
        "overdue_31_60":     sum(r["overdue_31_60"]      or 0 for r in rows),
        "overdue_61_90":     sum(r["overdue_61_90"]      or 0 for r in rows),
        "overdue_90_plus":   sum(r["overdue_90_plus"]    or 0 for r in rows),
    }
    return {"aging": rows, "supplier_count": len(rows), "totals": totals}


@mcp.tool(annotations={"readOnlyHint": True})
def get_landed_cost_summary(period: str = "this_month", limit: int = 20) -> dict:
    """Get landed cost vouchers — additional charges applied to purchase receipts.

    Use when asked about landed costs, freight charges, customs duties,
    additional procurement costs, or total cost of goods received.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.get_all(
        "Landed Cost Voucher",
        filters={
            "docstatus": 1,
            "posting_date": ["between", [start, end]],
        },
        fields=[
            "name", "posting_date", "company",
            "total_taxes_and_charges", "distribute_charges_based_on",
        ],
        order_by="posting_date desc",
        limit=limit,
    )
    total_charges = sum(r["total_taxes_and_charges"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "landed_cost_vouchers": rows,
        "count": len(rows),
        "total_additional_charges": total_charges,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_purchase_invoice_vs_order(period: str = "this_month", supplier: str = None, limit: int = 20) -> dict:
    """Find purchase invoices and check whether they were backed by a Purchase Order.

    Use when asked about maverick spending, invoices without POs,
    unapproved purchases, or billing compliance.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year. Defaults to this_month.
        supplier: Filter by supplier name. Optional.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    sup_condition = "AND pi.supplier LIKE %(supplier)s" if supplier else ""
    params = {
        "start": start, "end": end, "limit": limit,
        **({"supplier": f"%{supplier}%"} if supplier else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            pi.name AS invoice_no,
            pi.supplier,
            pi.posting_date,
            pi.grand_total,
            SUM(CASE WHEN pii.purchase_order IS NOT NULL AND pii.purchase_order != '' THEN pii.amount ELSE 0 END) AS po_backed_amount,
            SUM(CASE WHEN pii.purchase_order IS NULL  OR  pii.purchase_order  = '' THEN pii.amount ELSE 0 END) AS no_po_amount,
            COUNT(DISTINCT pii.purchase_order) AS linked_pos
        FROM `tabPurchase Invoice` pi
        JOIN `tabPurchase Invoice Item` pii ON pii.parent = pi.name
        WHERE pi.docstatus = 1
          AND pi.posting_date BETWEEN %(start)s AND %(end)s
          {sup_condition}
        GROUP BY pi.name
        ORDER BY no_po_amount DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    maverick_count = sum(1 for r in rows if (r["no_po_amount"] or 0) > 0)
    maverick_value = sum(r["no_po_amount"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "invoices": rows,
        "count": len(rows),
        "maverick_invoices": maverick_count,
        "total_maverick_spend": maverick_value,
        "note": "no_po_amount = invoice value with no linked Purchase Order (maverick spend)",
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_pending_supplier_payments(due_in_days: int = 7, limit: int = 30) -> dict:
    """Get supplier invoices due for payment in the next N days.

    Use when asked about upcoming payments, what we need to pay soon,
    payment schedule, or cash outflow forecast.

    Args:
        due_in_days: Include invoices due within this many days. Defaults to 7.
        limit: Max rows. Defaults to 30.
    """
    rows = frappe.db.sql(
        """
        SELECT
            name AS invoice_no,
            supplier,
            posting_date,
            due_date,
            grand_total,
            outstanding_amount,
            DATEDIFF(due_date, CURDATE()) AS days_until_due
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          AND due_date >= CURDATE()
          AND due_date <= DATE_ADD(CURDATE(), INTERVAL %s DAY)
        ORDER BY due_date ASC
        LIMIT %s
        """,
        (due_in_days, limit),
        as_dict=True,
    )
    total_due = sum(r["outstanding_amount"] or 0 for r in rows)
    return {
        "due_within_days": due_in_days,
        "upcoming_payments": rows,
        "count": len(rows),
        "total_amount_due": total_due,
    }
