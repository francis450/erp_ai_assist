"""Shared helpers for erp_ai_assist tools."""

import datetime
import frappe


def get_currency() -> str:
    """Return the default currency of the default company (e.g. 'KES')."""
    company = frappe.defaults.get_global_default("company")
    if company:
        cur = frappe.db.get_value("Company", company, "default_currency")
        if cur:
            return cur
    return frappe.db.get_single_value("Global Defaults", "default_currency") or "KES"


def get_date_range(period: str):
    """Return (start_date, end_date) for a named period."""
    today = datetime.date.today()
    if period == "today":
        return today, today
    elif period == "yesterday":
        yesterday = today - datetime.timedelta(days=1)
        return yesterday, yesterday
    elif period == "this_week":
        start = today - datetime.timedelta(days=today.weekday())
        return start, today
    elif period == "this_month":
        return today.replace(day=1), today
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_last = first_this - datetime.timedelta(days=1)
        return last_last.replace(day=1), last_last
    elif period == "this_year":
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today
