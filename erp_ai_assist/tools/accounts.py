"""Accounting / finance tools for the ERP AI Assistant."""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_date_range


@mcp.tool(annotations={"readOnlyHint": True})
def get_accounts_receivable(customer: str = None, limit: int = 20) -> dict:
    """Get outstanding accounts receivable — who owes us money.

    Use when asked about total money owed to the business, AR aging,
    overdue customers, or receivables summary.

    Args:
        customer: Filter by customer name (partial match). Optional.
        limit: Max number of invoices to return. Defaults to 20.
    """
    customer_condition = "AND customer LIKE %(customer)s" if customer else ""
    params = {"customer": f"%{customer}%", "limit": limit} if customer else {"limit": limit}

    rows = frappe.db.sql(
        f"""
        SELECT
            customer,
            SUM(outstanding_amount) AS total_outstanding,
            COUNT(*) AS invoice_count,
            MIN(due_date) AS oldest_due_date,
            SUM(CASE WHEN due_date < CURDATE() THEN outstanding_amount ELSE 0 END) AS overdue_amount
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          {customer_condition}
        GROUP BY customer
        ORDER BY total_outstanding DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    total = sum(r["total_outstanding"] for r in rows)
    total_overdue = sum(r["overdue_amount"] for r in rows)
    return {
        "receivables": rows,
        "count": len(rows),
        "total_outstanding": total,
        "total_overdue": total_overdue,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_accounts_payable(supplier: str = None, limit: int = 20) -> dict:
    """Get outstanding accounts payable — what we owe to suppliers.

    Use when asked about total payables, what the business owes suppliers,
    AP aging, or overdue supplier invoices.

    Args:
        supplier: Filter by supplier name (partial match). Optional.
        limit: Max number of entries to return. Defaults to 20.
    """
    supplier_condition = "AND supplier LIKE %(supplier)s" if supplier else ""
    params = {"supplier": f"%{supplier}%", "limit": limit} if supplier else {"limit": limit}

    rows = frappe.db.sql(
        f"""
        SELECT
            supplier,
            SUM(outstanding_amount) AS total_outstanding,
            COUNT(*) AS invoice_count,
            MIN(due_date) AS oldest_due_date,
            SUM(CASE WHEN due_date < CURDATE() THEN outstanding_amount ELSE 0 END) AS overdue_amount
        FROM `tabPurchase Invoice`
        WHERE docstatus = 1
          AND outstanding_amount > 0
          {supplier_condition}
        GROUP BY supplier
        ORDER BY total_outstanding DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    total = sum(r["total_outstanding"] for r in rows)
    total_overdue = sum(r["overdue_amount"] for r in rows)
    return {
        "payables": rows,
        "count": len(rows),
        "total_outstanding": total,
        "total_overdue": total_overdue,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_cash_position() -> dict:
    """Get current balances of all cash and bank accounts.

    Use when asked about available cash, bank balances, liquidity,
    or how much money is in the accounts.
    """
    rows = frappe.db.sql(
        """
        SELECT
            a.name AS account,
            a.account_type,
            a.account_currency,
            SUM(
                CASE
                    WHEN gl.debit_in_account_currency IS NOT NULL
                    THEN gl.debit_in_account_currency - gl.credit_in_account_currency
                    ELSE gl.debit - gl.credit
                END
            ) AS balance
        FROM `tabAccount` a
        LEFT JOIN `tabGL Entry` gl
            ON gl.account = a.name AND gl.is_cancelled = 0
        WHERE a.account_type IN ('Cash', 'Bank')
          AND a.is_group = 0
        GROUP BY a.name, a.account_type, a.account_currency
        ORDER BY balance DESC
        """,
        as_dict=True,
    )
    total_cash = sum(r["balance"] or 0 for r in rows if r["account_type"] == "Cash")
    total_bank = sum(r["balance"] or 0 for r in rows if r["account_type"] == "Bank")
    return {
        "accounts": rows,
        "total_cash": total_cash,
        "total_bank": total_bank,
        "total_liquid": total_cash + total_bank,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_profit_loss_summary(period: str) -> dict:
    """Get a profit and loss summary from GL entries for a period.

    Use when asked about profit, net income, revenue vs expenses,
    or business performance for a time period.

    Args:
        period: Time period. One of: today, yesterday, this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            a.root_type,
            SUM(gl.debit - gl.credit) AS net_amount
        FROM `tabGL Entry` gl
        JOIN `tabAccount` a ON a.name = gl.account
        WHERE gl.posting_date BETWEEN %s AND %s
          AND gl.is_cancelled = 0
          AND a.root_type IN ('Income', 'Expense')
        GROUP BY a.root_type
        """,
        (start, end),
        as_dict=True,
    )
    summary = {r["root_type"]: r["net_amount"] for r in rows}
    income = summary.get("Income", 0) or 0
    expense = summary.get("Expense", 0) or 0
    # Income accounts: credit increases → net = credit - debit, so negate
    net_income = (-income) - expense
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "gross_income": -income,
        "total_expenses": expense,
        "net_profit": net_income,
    }


# ── new extended accounts tools ───────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_expense_breakdown(period: str, limit: int = 20) -> dict:
    """Get expenses broken down by account for a period.

    Use when asked about what we spent money on, expense categories,
    cost breakdown, where money went, or top expense accounts.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max accounts to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            gl.account,
            a.account_type,
            SUM(gl.debit - gl.credit) AS amount
        FROM `tabGL Entry` gl
        JOIN `tabAccount` a ON a.name = gl.account
        WHERE gl.posting_date BETWEEN %s AND %s
          AND gl.is_cancelled = 0
          AND a.root_type = 'Expense'
          AND a.is_group = 0
        GROUP BY gl.account, a.account_type
        HAVING amount > 0
        ORDER BY amount DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    total = sum(r["amount"] or 0 for r in rows)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "expenses": rows,
        "total_expenses": total,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_tax_summary(period: str) -> dict:
    """Get tax collected (output VAT) and tax paid (input VAT) for a period.

    Use when asked about VAT, tax liability, tax collected from customers,
    tax paid to suppliers, or net tax payable.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
    """
    start, end = get_date_range(period)

    output_tax = frappe.db.sql(
        """
        SELECT
            stc.account_head,
            SUM(stc.tax_amount) AS tax_collected
        FROM `tabSales Taxes and Charges` stc
        JOIN `tabSales Invoice` si ON si.name = stc.parent
        WHERE si.docstatus = 1
          AND si.posting_date BETWEEN %s AND %s
        GROUP BY stc.account_head
        ORDER BY tax_collected DESC
        """,
        (start, end),
        as_dict=True,
    )
    input_tax = frappe.db.sql(
        """
        SELECT
            ptc.account_head,
            SUM(ptc.tax_amount) AS tax_paid
        FROM `tabPurchase Taxes and Charges` ptc
        JOIN `tabPurchase Invoice` pi ON pi.name = ptc.parent
        WHERE pi.docstatus = 1
          AND pi.posting_date BETWEEN %s AND %s
        GROUP BY ptc.account_head
        ORDER BY tax_paid DESC
        """,
        (start, end),
        as_dict=True,
    )
    total_output = sum(r["tax_collected"] or 0 for r in output_tax)
    total_input  = sum(r["tax_paid"]      or 0 for r in input_tax)
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "output_tax_collected": total_output,
        "input_tax_paid": total_input,
        "net_tax_payable": total_output - total_input,
        "output_tax_by_account": output_tax,
        "input_tax_by_account": input_tax,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_journal_entries(period: str, account: str = None, limit: int = 20) -> dict:
    """Get manual journal entries posted in a period.

    Use when asked about journal entries, manual GL postings, adjusting entries,
    or accruals posted in a given period.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        account: Filter by account name (partial match). Optional.
        limit: Max rows. Defaults to 20.
    """
    start, end = get_date_range(period)
    conditions = [
        "je.docstatus = 1",
        "je.posting_date BETWEEN %(start)s AND %(end)s",
    ]
    params: dict = {"start": start, "end": end, "limit": limit}
    if account:
        conditions.append(
            "EXISTS (SELECT 1 FROM `tabJournal Entry Account` jea "
            "WHERE jea.parent = je.name AND jea.account LIKE %(account)s)"
        )
        params["account"] = f"%{account}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            je.name,
            je.posting_date,
            je.voucher_type,
            je.total_debit,
            je.user_remark,
            je.cheque_no,
            je.cheque_date
        FROM `tabJournal Entry` je
        WHERE {where}
        ORDER BY je.posting_date DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "journal_entries": rows,
        "count": len(rows),
        "total_value": sum(r["total_debit"] or 0 for r in rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_cost_center_expenses(period: str, limit: int = 20) -> dict:
    """Get expenses broken down by cost center for a period.

    Use when asked about department costs, cost centre spending, which
    department spent the most, or cost allocation by business unit.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max cost centers to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            gl.cost_center,
            SUM(gl.debit - gl.credit) AS expenses,
            COUNT(DISTINCT gl.voucher_no) AS transaction_count
        FROM `tabGL Entry` gl
        JOIN `tabAccount` a ON a.name = gl.account
        WHERE gl.posting_date BETWEEN %s AND %s
          AND gl.is_cancelled = 0
          AND a.root_type = 'Expense'
          AND gl.cost_center IS NOT NULL
        GROUP BY gl.cost_center
        HAVING expenses > 0
        ORDER BY expenses DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_cost_center": rows,
        "total_expenses": sum(r["expenses"] or 0 for r in rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_budget_vs_actual(fiscal_year: str = None, cost_center: str = None, limit: int = 20) -> dict:
    """Get budget vs actual spend comparison by account.

    Use when asked about budget utilisation, how much of the budget has been used,
    over-budget accounts, or variance analysis.

    Args:
        fiscal_year: Fiscal year name (e.g. '2025-2026'). Defaults to current year.
        cost_center: Filter by cost center name. Optional.
        limit: Max accounts to return. Defaults to 20.
    """
    if not fiscal_year:
        fiscal_year = frappe.db.get_value(
            "Fiscal Year", {"is_fiscal_year_closing": 0}, "name", order_by="year_start_date desc"
        ) or str(frappe.utils.getdate().year)

    fy = frappe.db.get_value("Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True)
    if not fy:
        return {"error": f"Fiscal year '{fiscal_year}' not found"}

    cc_condition = "AND b.cost_center LIKE %(cost_center)s" if cost_center else ""
    params = {
        "fy": fiscal_year,
        "start": fy["year_start_date"],
        "end": fy["year_end_date"],
        **({"cost_center": f"%{cost_center}%"} if cost_center else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            b.account,
            SUM(b.budget_amount) AS budget_amount,
            COALESCE((
                SELECT SUM(gl.debit - gl.credit)
                FROM `tabGL Entry` gl
                WHERE gl.account = b.account
                  AND gl.fiscal_year = %(fy)s
                  AND gl.is_cancelled = 0
            ), 0) AS actual_amount
        FROM `tabBudget Account` ba
        JOIN `tabBudget` b ON b.name = ba.parent
        WHERE b.docstatus = 1
          AND b.fiscal_year = %(fy)s
          {cc_condition}
        GROUP BY b.account
        ORDER BY budget_amount DESC
        LIMIT %(limit)s
        """,
        {**params, "limit": limit},
        as_dict=True,
    )
    for r in rows:
        r["variance"] = (r["budget_amount"] or 0) - (r["actual_amount"] or 0)
        r["utilisation_pct"] = round(
            (r["actual_amount"] or 0) / r["budget_amount"] * 100, 1
        ) if r["budget_amount"] else 0
    return {
        "fiscal_year": fiscal_year,
        "from": str(fy["year_start_date"]),
        "to": str(fy["year_end_date"]),
        "budget_vs_actual": rows,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_balance_sheet_summary() -> dict:
    """Get a current balance sheet snapshot — assets, liabilities, and equity.

    Use when asked about the balance sheet, net worth, total assets,
    total liabilities, or the financial position of the business.
    """
    rows = frappe.db.sql(
        """
        SELECT
            a.root_type,
            SUM(
                CASE
                    WHEN a.root_type IN ('Asset', 'Expense') THEN gl.debit - gl.credit
                    ELSE gl.credit - gl.debit
                END
            ) AS balance
        FROM `tabAccount` a
        LEFT JOIN `tabGL Entry` gl ON gl.account = a.name AND gl.is_cancelled = 0
        WHERE a.root_type IN ('Asset', 'Liability', 'Equity')
          AND a.is_group = 0
        GROUP BY a.root_type
        """,
        as_dict=True,
    )
    summary = {r["root_type"]: r["balance"] or 0 for r in rows}
    assets      = summary.get("Asset",     0)
    liabilities = summary.get("Liability", 0)
    equity      = summary.get("Equity",    0)
    return {
        "total_assets": assets,
        "total_liabilities": liabilities,
        "total_equity": equity,
        "net_worth": equity,
        "debt_to_equity": round(liabilities / equity, 2) if equity else None,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_payment_made(period: str, supplier: str = None, limit: int = 30) -> dict:
    """Get payments made to suppliers in a period.

    Use when asked about payments sent out, supplier payments, how much we
    paid suppliers, or cash outflows to vendors.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        supplier: Filter by supplier name. Optional.
        limit: Max rows. Defaults to 30.
    """
    start, end = get_date_range(period)
    conditions = [
        "pe.docstatus = 1",
        "pe.payment_type = 'Pay'",
        "pe.party_type = 'Supplier'",
        "pe.posting_date BETWEEN %(start)s AND %(end)s",
    ]
    params: dict = {"start": start, "end": end, "limit": limit}
    if supplier:
        conditions.append("pe.party LIKE %(supplier)s")
        params["supplier"] = f"%{supplier}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            pe.name,
            pe.party AS supplier,
            pe.posting_date,
            pe.paid_amount,
            pe.mode_of_payment,
            pe.reference_no
        FROM `tabPayment Entry` pe
        WHERE {where}
        ORDER BY pe.posting_date DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    by_mode = frappe.db.sql(
        f"""
        SELECT mode_of_payment, COUNT(*) AS count, SUM(paid_amount) AS total
        FROM `tabPayment Entry` pe
        WHERE {where}
        GROUP BY mode_of_payment
        ORDER BY total DESC
        """,
        params,
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "payments": rows,
        "count": len(rows),
        "total_paid": sum(r["paid_amount"] or 0 for r in rows),
        "by_mode_of_payment": by_mode,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_income_by_account(period: str, limit: int = 20) -> dict:
    """Get income/revenue broken down by GL account for a period.

    Use when asked about revenue streams, income accounts, which income
    account earned the most, or detailed revenue breakdown.

    Args:
        period: One of: today, yesterday, this_week, this_month, last_month, this_year.
        limit: Max accounts to return. Defaults to 20.
    """
    start, end = get_date_range(period)
    rows = frappe.db.sql(
        """
        SELECT
            gl.account,
            SUM(gl.credit - gl.debit) AS income
        FROM `tabGL Entry` gl
        JOIN `tabAccount` a ON a.name = gl.account
        WHERE gl.posting_date BETWEEN %s AND %s
          AND gl.is_cancelled = 0
          AND a.root_type = 'Income'
          AND a.is_group = 0
        GROUP BY gl.account
        HAVING income > 0
        ORDER BY income DESC
        LIMIT %s
        """,
        (start, end, limit),
        as_dict=True,
    )
    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "income_accounts": rows,
        "total_income": sum(r["income"] or 0 for r in rows),
    }
