"""Shared helpers for erp_ai_assist tools."""

import datetime


def get_date_range(period: str):
    """Return (start_date, end_date) for a named period."""
    today = datetime.date.today()
    if period == "today":
        return today, today
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
