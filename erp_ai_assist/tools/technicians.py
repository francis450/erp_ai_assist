"""
erp_ai_assist/tools/technicians.py
Tools for querying technician performance from the custom_technicians_table
on Sales Invoice (tabTechnician child doctype).
"""

import frappe
from erp_ai_assist.mcp import mcp
from erp_ai_assist.tools.utils import get_currency, get_date_range


@mcp.tool(annotations={"readOnlyHint": True})
def get_technician_performance(period: str, technician: str = None) -> dict:
    """Get performance summary per technician — services performed and invoice count.

    Use when asked how many services a technician did, who is the busiest
    technician, or a technician's performance over a period.

    Args:
        period: Named: today, yesterday, this_week, last_week, this_month,
                last_month, this_year. Rolling window: last_N_days
                (e.g. last_7_days). Explicit range: YYYY-MM-DD:YYYY-MM-DD.
        technician: Filter to a specific technician name (partial match). Optional.
    """
    start, end = get_date_range(period)
    currency = get_currency()

    tech_condition = "AND t.technician LIKE %(technician)s" if technician else ""
    params = {
        "start": start,
        "end": end,
        **({"technician": f"%{technician}%"} if technician else {}),
    }

    rows = frappe.db.sql(
        f"""
        SELECT
            t.technician,
            COUNT(*)                                                      AS total_services,
            SUM(CASE WHEN t.type = 'Installation' THEN 1 ELSE 0 END)     AS installations,
            SUM(CASE WHEN t.type = 'Sales'        THEN 1 ELSE 0 END)     AS sales_services,
            COUNT(DISTINCT t.parent)                                      AS invoice_count
        FROM `tabTechnician` t
        INNER JOIN `tabSales Invoice` si
            ON si.name = t.parent AND si.docstatus = 1
        WHERE si.posting_date BETWEEN %(start)s AND %(end)s
          {tech_condition}
        GROUP BY t.technician
        ORDER BY total_services DESC
        """,
        params,
        as_dict=True,
    )

    return {
        "currency": currency,
        "period": period,
        "from": str(start),
        "to": str(end),
        "technicians": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_technician_service_breakdown(period: str, technician: str = None) -> dict:
    """Get a breakdown of which services each technician performed and how many times.

    Use when asked what services a technician did, which service is most
    popular per technician, or a detailed view of technician activity.

    Args:
        period: Named: today, yesterday, this_week, last_week, this_month,
                last_month, this_year. Rolling window: last_N_days.
                Explicit range: YYYY-MM-DD:YYYY-MM-DD.
        technician: Filter to a specific technician (partial match). Optional —
                    omit to get breakdown for all technicians.
    """
    start, end = get_date_range(period)
    currency = get_currency()

    tech_condition = "AND t.technician LIKE %(technician)s" if technician else ""
    params = {
        "start": start,
        "end": end,
        **({"technician": f"%{technician}%"} if technician else {}),
    }

    rows = frappe.db.sql(
        f"""
        SELECT
            t.technician,
            t.service,
            t.type,
            COUNT(*)                 AS times_performed,
            COUNT(DISTINCT t.parent) AS invoice_count
        FROM `tabTechnician` t
        INNER JOIN `tabSales Invoice` si
            ON si.name = t.parent AND si.docstatus = 1
        WHERE si.posting_date BETWEEN %(start)s AND %(end)s
          {tech_condition}
        GROUP BY t.technician, t.service, t.type
        ORDER BY t.technician, times_performed DESC
        """,
        params,
        as_dict=True,
    )

    # Group by technician for a cleaner structure
    by_technician = {}
    for row in rows:
        name = row["technician"]
        if name not in by_technician:
            by_technician[name] = {"technician": name, "services": [], "total_services": 0}
        by_technician[name]["services"].append({
            "service": row["service"],
            "type": row["type"],
            "times_performed": row["times_performed"],
            "invoice_count": row["invoice_count"],
        })
        by_technician[name]["total_services"] += row["times_performed"]

    return {
        "currency": currency,
        "period": period,
        "from": str(start),
        "to": str(end),
        "by_technician": list(by_technician.values()),
        "technician_count": len(by_technician),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_top_technicians(period: str, limit: int = 10, by: str = "services") -> dict:
    """Get top-performing technicians ranked by services performed or invoices.

    Use when asked who the top technicians are, who performed the most
    services, or a leaderboard of technician activity.

    Args:
        period: Named: today, yesterday, this_week, last_week, this_month,
                last_month, this_year. Rolling window: last_N_days.
                Explicit range: YYYY-MM-DD:YYYY-MM-DD.
        limit: Number of technicians to return. Defaults to 10.
        by: Rank by 'services' (total service count) or 'invoices'
            (distinct invoices worked on). Defaults to services.
    """
    start, end = get_date_range(period)
    currency = get_currency()

    order_field = "total_services" if by != "invoices" else "invoice_count"

    rows = frappe.db.sql(
        """
        SELECT
            t.technician,
            COUNT(*)                                                  AS total_services,
            SUM(CASE WHEN t.type = 'Installation' THEN 1 ELSE 0 END) AS installations,
            SUM(CASE WHEN t.type = 'Sales'        THEN 1 ELSE 0 END) AS sales_services,
            COUNT(DISTINCT t.parent)                                  AS invoice_count,
            COUNT(DISTINCT t.service)                                 AS distinct_services
        FROM `tabTechnician` t
        INNER JOIN `tabSales Invoice` si
            ON si.name = t.parent AND si.docstatus = 1
        WHERE si.posting_date BETWEEN %(start)s AND %(end)s
        GROUP BY t.technician
        ORDER BY {order_field} DESC
        LIMIT %(limit)s
        """.format(order_field=order_field),
        {"start": start, "end": end, "limit": limit},
        as_dict=True,
    )

    return {
        "currency": currency,
        "period": period,
        "from": str(start),
        "to": str(end),
        "ranked_by": by,
        "technicians": rows,
        "count": len(rows),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def get_service_technician_map(period: str, service: str = None) -> dict:
    """Get which technicians performed each service and how many times.

    Use when asked who does a specific service the most, which technicians
    are assigned to a particular treatment, or service-level staffing.

    Args:
        period: Named: today, yesterday, this_week, last_week, this_month,
                last_month, this_year. Rolling window: last_N_days.
                Explicit range: YYYY-MM-DD:YYYY-MM-DD.
        service: Filter to a specific service/item name (partial match). Optional.
    """
    start, end = get_date_range(period)

    svc_condition = "AND t.service LIKE %(service)s" if service else ""
    params = {
        "start": start,
        "end": end,
        **({"service": f"%{service}%"} if service else {}),
    }

    rows = frappe.db.sql(
        f"""
        SELECT
            t.service,
            t.type,
            t.technician,
            COUNT(*) AS times_performed
        FROM `tabTechnician` t
        INNER JOIN `tabSales Invoice` si
            ON si.name = t.parent AND si.docstatus = 1
        WHERE si.posting_date BETWEEN %(start)s AND %(end)s
          {svc_condition}
        GROUP BY t.service, t.type, t.technician
        ORDER BY t.service, times_performed DESC
        """,
        params,
        as_dict=True,
    )

    # Group by service
    by_service = {}
    for row in rows:
        svc = row["service"]
        if svc not in by_service:
            by_service[svc] = {
                "service": svc,
                "type": row["type"],
                "technicians": [],
                "total_performed": 0,
            }
        by_service[svc]["technicians"].append({
            "technician": row["technician"],
            "times_performed": row["times_performed"],
        })
        by_service[svc]["total_performed"] += row["times_performed"]

    return {
        "period": period,
        "from": str(start),
        "to": str(end),
        "services": list(by_service.values()),
        "service_count": len(by_service),
    }
