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


# ── new extended HR tools ─────────────────────────────────────────────────────

@mcp.tool(annotations={"readOnlyHint": True})
def get_employee_details(employee_name: str) -> dict:
    """Get profile details for an employee — department, designation, dates, contact.

    Use when asked about a specific employee, their role, department,
    joining date, or contact information.

    Args:
        employee_name: Employee name or ID (partial match supported).
    """
    rows = frappe.db.sql(
        """
        SELECT
            name, employee_name, designation, department,
            date_of_joining, date_of_birth, gender,
            cell_number, company_email, employment_type,
            status, branch, reports_to
        FROM `tabEmployee`
        WHERE (employee_name LIKE %(name)s OR name LIKE %(name)s)
        LIMIT 5
        """,
        {"name": f"%{employee_name}%"},
        as_dict=True,
    )
    if not rows:
        return {"error": f"No employee found matching '{employee_name}'"}
    return {"employees": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_payroll_summary(month: str = None) -> dict:
    """Get payroll summary — total salary paid, headcount processed, by department.

    Use when asked about payroll, total salaries paid, payroll cost,
    compensation expense, or how much was paid to employees.

    Args:
        month: Month in YYYY-MM format (e.g. 2025-03). Defaults to current month.
    """
    if month:
        try:
            year, m = map(int, month.split("-"))
            start = datetime.date(year, m, 1)
            end = (datetime.date(year, m + 1, 1) - datetime.timedelta(days=1)) if m < 12 \
                else datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        except (ValueError, AttributeError):
            today = datetime.date.today()
            start = today.replace(day=1)
            end = today
    else:
        today = datetime.date.today()
        start = today.replace(day=1)
        end = today

    totals = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS slip_count,
            COUNT(DISTINCT employee) AS employee_count,
            SUM(gross_pay) AS total_gross,
            SUM(total_deduction) AS total_deductions,
            SUM(net_pay) AS total_net_pay
        FROM `tabSalary Slip`
        WHERE docstatus = 1
          AND start_date >= %s AND end_date <= %s
        """,
        (start, end),
        as_dict=True,
    )
    by_dept = frappe.db.sql(
        """
        SELECT
            e.department,
            COUNT(*) AS headcount,
            SUM(ss.gross_pay) AS gross_pay,
            SUM(ss.net_pay) AS net_pay
        FROM `tabSalary Slip` ss
        JOIN `tabEmployee` e ON e.name = ss.employee
        WHERE ss.docstatus = 1
          AND ss.start_date >= %s AND ss.end_date <= %s
        GROUP BY e.department
        ORDER BY gross_pay DESC
        """,
        (start, end),
        as_dict=True,
    )
    return {
        "from": str(start),
        "to": str(end),
        "summary": totals[0] if totals else {},
        "by_department": by_dept,
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_pending_leave_requests(department: str = None, limit: int = 20) -> dict:
    """Get leave requests awaiting approval.

    Use when asked about pending leaves, unapproved leave requests,
    leaves to approve, or open leave applications.

    Args:
        department: Filter by department name. Optional.
        limit: Max rows. Defaults to 20.
    """
    conditions = ["la.docstatus = 0", "la.status = 'Open'"]
    params: dict = {"limit": limit}
    if department:
        conditions.append("e.department LIKE %(department)s")
        params["department"] = f"%{department}%"

    where = " AND ".join(conditions)
    rows = frappe.db.sql(
        f"""
        SELECT
            la.name,
            la.employee,
            e.employee_name,
            e.department,
            la.leave_type,
            la.from_date,
            la.to_date,
            la.total_leave_days,
            la.reason
        FROM `tabLeave Application` la
        JOIN `tabEmployee` e ON e.name = la.employee
        WHERE {where}
        ORDER BY la.from_date ASC
        LIMIT %(limit)s
        """,
        params,
        as_dict=True,
    )
    return {"pending_leaves": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_absent_today() -> dict:
    """Get employees who are absent or on leave today.

    Use when asked who is absent today, who called in sick, who is on leave,
    or today's attendance shortfall.
    """
    today = datetime.date.today()
    absent = frappe.db.sql(
        """
        SELECT
            a.employee,
            e.employee_name,
            e.department,
            a.status,
            a.leave_type
        FROM `tabAttendance` a
        JOIN `tabEmployee` e ON e.name = a.employee
        WHERE a.docstatus = 1
          AND a.attendance_date = %s
          AND a.status IN ('Absent', 'Half Day', 'On Leave')
        ORDER BY e.department, e.employee_name
        """,
        (today,),
        as_dict=True,
    )
    return {
        "date": str(today),
        "absent_employees": absent,
        "count": len(absent),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_attendance_by_employee(employee_name: str, month: str = None) -> dict:
    """Get detailed attendance record for a specific employee.

    Use when asked about an individual employee's attendance, how many days
    they were present, absent, or late for a given month.

    Args:
        employee_name: Employee name or ID (partial match).
        month: Month in YYYY-MM format. Defaults to current month.
    """
    if month:
        try:
            year, m = map(int, month.split("-"))
            start = datetime.date(year, m, 1)
            end = (datetime.date(year, m + 1, 1) - datetime.timedelta(days=1)) if m < 12 \
                else datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
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
            a.attendance_date,
            a.status,
            a.in_time,
            a.out_time,
            a.leave_type,
            e.employee_name,
            e.department
        FROM `tabAttendance` a
        JOIN `tabEmployee` e ON e.name = a.employee
        WHERE a.docstatus = 1
          AND (e.employee_name LIKE %(name)s OR a.employee LIKE %(name)s)
          AND a.attendance_date BETWEEN %(start)s AND %(end)s
        ORDER BY a.attendance_date ASC
        """,
        {"name": f"%{employee_name}%", "start": start, "end": end},
        as_dict=True,
    )
    status_counts: dict = {}
    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1
    return {
        "employee_filter": employee_name,
        "from": str(start),
        "to": str(end),
        "records": rows,
        "summary": status_counts,
        "total_days": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_work_anniversaries(days_ahead: int = 30) -> dict:
    """Get employees with upcoming work anniversaries in the next N days.

    Use when asked about upcoming anniversaries, long-service milestones,
    employees completing years of service, or retention recognition opportunities.

    Args:
        days_ahead: How many days ahead to look. Defaults to 30.
    """
    rows = frappe.db.sql(
        """
        SELECT
            name AS employee_id,
            employee_name,
            department,
            designation,
            date_of_joining,
            YEAR(CURDATE()) - YEAR(date_of_joining) AS years_of_service,
            DATE_FORMAT(date_of_joining, CONCAT(YEAR(CURDATE()), '-%%m-%%d')) AS anniversary_this_year
        FROM `tabEmployee`
        WHERE status = 'Active'
          AND date_of_joining IS NOT NULL
          AND DATE_FORMAT(date_of_joining, CONCAT(YEAR(CURDATE()), '-%%m-%%d'))
              BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL %s DAY)
        ORDER BY anniversary_this_year ASC
        """,
        (days_ahead,),
        as_dict=True,
    )
    return {
        "days_ahead": days_ahead,
        "upcoming_anniversaries": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_recruitment_pipeline(limit: int = 20) -> dict:
    """Get open job openings and their current status.

    Use when asked about open positions, hiring pipeline, job vacancies,
    how many roles are being recruited for, or recruitment status.

    Args:
        limit: Max rows. Defaults to 20.
    """
    rows = frappe.db.get_all(
        "Job Opening",
        filters={"status": "Open"},
        fields=[
            "name", "job_title", "department", "designation",
            "status", "posted_on", "expected_compensation",
        ],
        order_by="posted_on desc",
        limit=limit,
    )
    applicants = frappe.db.sql(
        """
        SELECT job_title, COUNT(*) AS applicant_count
        FROM `tabJob Applicant`
        WHERE status NOT IN ('Rejected', 'Hold')
        GROUP BY job_title
        """,
        as_dict=True,
    )
    applicant_map = {r["job_title"]: r["applicant_count"] for r in applicants}
    for r in rows:
        r["active_applicants"] = applicant_map.get(r["job_title"], 0)
    return {"open_positions": rows, "count": len(rows)}


@mcp.tool(annotations={"readOnlyHint": True})
def get_overtime_summary(month: str = None, department: str = None) -> dict:
    """Get overtime hours worked by employees for a month.

    Use when asked about overtime, extra hours, which department worked the
    most OT, or total overtime cost.

    Args:
        month: Month in YYYY-MM format. Defaults to current month.
        department: Filter by department. Optional.
    """
    if month:
        try:
            year, m = map(int, month.split("-"))
            start = datetime.date(year, m, 1)
            end = (datetime.date(year, m + 1, 1) - datetime.timedelta(days=1)) if m < 12 \
                else datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
        except (ValueError, AttributeError):
            today = datetime.date.today()
            start = today.replace(day=1)
            end = today
    else:
        today = datetime.date.today()
        start = today.replace(day=1)
        end = today

    dept_condition = "AND e.department LIKE %(department)s" if department else ""
    params = {
        "start": start,
        "end": end,
        **({"department": f"%{department}%"} if department else {}),
    }
    rows = frappe.db.sql(
        f"""
        SELECT
            e.department,
            COUNT(DISTINCT a.employee) AS employee_count,
            SUM(a.overtime_hours) AS total_overtime_hours
        FROM `tabAttendance` a
        JOIN `tabEmployee` e ON e.name = a.employee
        WHERE a.docstatus = 1
          AND a.attendance_date BETWEEN %(start)s AND %(end)s
          AND a.overtime_hours > 0
          {dept_condition}
        GROUP BY e.department
        ORDER BY total_overtime_hours DESC
        """,
        params,
        as_dict=True,
    )
    return {
        "from": str(start),
        "to": str(end),
        "by_department": rows,
        "total_overtime_hours": sum(r["total_overtime_hours"] or 0 for r in rows),
    }
