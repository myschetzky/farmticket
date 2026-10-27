"""Dato-hjælpere. Alle tider gemmes som lokal tid i formatet 'YYYY-MM-DD HH:MM'."""

from datetime import date, datetime, timedelta

DT_FORMAT = "%Y-%m-%d %H:%M"

WEEKDAYS = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
WEEKDAYS_SHORT = ["man", "tir", "ons", "tor", "fre", "lør", "søn"]
MONTHS = [
    "januar", "februar", "marts", "april", "maj", "juni",
    "juli", "august", "september", "oktober", "november", "december",
]


def now_str() -> str:
    return datetime.now().strftime(DT_FORMAT)


def parse_dt(value: str) -> datetime:
    return datetime.strptime(value, DT_FORMAT)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return parse_date(value[:10])
    return None


def fmt_date(value, with_weekday=True, with_year=None) -> str:
    """'tirsdag 27. oktober' (årstal med, hvis det ikke er i år)."""
    d = _as_date(value)
    if d is None:
        return ""
    text = f"{d.day}. {MONTHS[d.month - 1]}"
    if with_year or (with_year is None and d.year != date.today().year):
        text += f" {d.year}"
    if with_weekday:
        text = f"{WEEKDAYS[d.weekday()]} {text}"
    return text


def fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if isinstance(value, str) and len(value) >= 16:
        return value[11:16]
    return ""


def fmt_datetime(value) -> str:
    if not value:
        return ""
    return f"{fmt_date(value)} kl. {fmt_time(value)}"


def fmt_hours(value) -> str:
    """1.5 -> '1,5 t'"""
    if value is None:
        return ""
    value = round(float(value), 1)
    text = f"{value:g}".replace(".", ",")
    return f"{text} t"
