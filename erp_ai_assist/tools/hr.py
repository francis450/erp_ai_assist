"""HR tools for the ERP AI Assistant."""

import datetime
import frappe
from erp_ai_assist.mcp import mcp


@mcp.tool(annotations={"readOnlyHint": True})
def get_attendance_summary(month: str = None) -> dict:
    """Get employee attendance summary for a given month.

    Use when asked about attendance, absenteeism, who was present or absent,
    or workforce attendance rates.

    Args:
        month: Month in YYYY-MM format (e.g. 2025-03). Defaults to current month.
    """
    if month:
        try:
            year, m = map(int, month.split("-"))
            start = datetime.date(year, m, 1)
            if m == 12:
                end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                end = datetime.date(year, m + 1, 1) - datetime.timedelta(days=1)
        except (ValueError, AttributeError):
            today = datetime.date.today()
            start = today.replace(day=1)
            end = today
    else:
        today = datetime.date.today()
        start = today.replace(day=1)
        end = today

    rows = frappe.db.sql(
        """
        SELECT
            status,
            COUNT(*) AS count,
            COUNT(DISTINCT employee) AS employees
        FROM `tabAttendance`
        WHERE docstatus = 1
          AND attendance_date BETWEEN %s AND %s
        GROUP BY status
        ORDER BY count DESC
        """,
        (start, end),
        as_dict=True,
    )
    total = sum(r["count"] for r in rows)
    return {
        "from": str(start),
        "to": str(end),
        "by_status": rows,
        "total_records": total,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_leave_balance(employee_name: str = None, limit: int = 20) -> dict:
    """Get leave allocation balances for employees.

    Use when asked about remaining leave days, leave entitlements,
    how many days off an employee has left, or leave balances.

    Args:
        employee_name: Filter by employee name (partial match). Optional.
        limit: Max number of records to return. Defaults to 20.
    """
    today = datetime.date.today()
    employee_condition = "AND e.employee_name LIKE %(employee)s" if employee_name else ""
    params = {
        "today": today,
        "limit": limit,
        **({"employee": f"%{employee_name}%"} if employee_name else {}),
    }

    rows = frappe.db.sql(
        f"""
        SELECT
            la.employee,
            e.employee_name,
            la.leave_type,
            la.total_leaves_allocated,
            la.leaves_taken,
            (la.total_leaves_allocated - la.leaves_taken) AS balance
        FROM `tabLeave Allocation` la
        JOIN `tabEmployee` e ON e.name = la.employee
        WHERE la.docstatus = 1
          AND la.from_date <= %(today)s
          AND la.to_date >= %(today)s
          {employee_condition}
        ORDER BY balance DESC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {"leave_balances": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_employee_count() -> dict:
    """Get total active employee headcount broken down by department.

    Use when asked about how many employees the company has, headcount
    by department, or workforce size.
    """
    rows = frappe.db.sql(
        """
        SELECT
            COALESCE(department, 'Unassigned') AS department,
            COUNT(*) AS headcount
        FROM `tabEmployee`
        WHERE status = 'Active'
        GROUP BY department
        ORDER BY headcount DESC
        """,
        as_dict=True,
    )
    total = sum(r["headcount"] for r in rows)
    return {"departments": rows, "total_employees": total}
