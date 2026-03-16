"""Shared helpers for erp_ai_assist tools."""

import datetime
import re
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
    """Return (start_date, end_date) for a named period or flexible pattern.

    Supports:
    - Named shortcuts: today, yesterday, this_week, last_week, this_month,
      last_month, this_year
    - Dynamic rolling window: last_N_days  (e.g. last_5_days, last_90_days)
    - Explicit range: YYYY-MM-DD:YYYY-MM-DD  (e.g. 2026-01-01:2026-03-16)
    """
    today = datetime.date.today()

    # ── Explicit date range: "2026-01-01:2026-03-16" ────────────────────────
    if re.match(r"^\d{4}-\d{2}-\d{2}:\d{4}-\d{2}-\d{2}$", period):
        start_str, end_str = period.split(":")
        return datetime.date.fromisoformat(start_str), datetime.date.fromisoformat(end_str)

    # ── Dynamic rolling window: "last_N_days" ───────────────────────────────
    match = re.match(r"^last_(\d+)_days$", period)
    if match:
        n = int(match.group(1))
        return today - datetime.timedelta(days=n - 1), today

    # ── Named shortcuts ──────────────────────────────────────────────────────
    if period == "today":
        return today, today
    elif period == "yesterday":
        yesterday = today - datetime.timedelta(days=1)
        return yesterday, yesterday
    elif period == "this_week":
        start = today - datetime.timedelta(days=today.weekday())
        return start, today
    elif period == "last_week":
        start_this_week = today - datetime.timedelta(days=today.weekday())
        end_last = start_this_week - datetime.timedelta(days=1)
        start_last = end_last - datetime.timedelta(days=6)
        return start_last, end_last
    elif period == "this_month":
        return today.replace(day=1), today
    elif period == "last_month":
        first_this = today.replace(day=1)
        last_last = first_this - datetime.timedelta(days=1)
        return last_last.replace(day=1), last_last
    elif period == "this_year":
        return today.replace(month=1, day=1), today

    # fallback
    return today.replace(day=1), today
