from datetime import date, timedelta


def current_month_range() -> tuple[date, date]:
    today = date.today()
    start = today.replace(day=1)
    # First day of next month minus one day
    if today.month == 12:
        end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    return start, end


def current_year_range() -> tuple[date, date]:
    today = date.today()
    return today.replace(month=1, day=1), today.replace(month=12, day=31)
