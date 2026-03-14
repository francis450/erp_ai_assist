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
