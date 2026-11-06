from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
D0 = datetime(2027, 1, 4, tzinfo=IST)
DAY = 1440


def fmt_minute(m: int) -> str:
    """Sim minute -> 'D3 14:00' (negative minutes are history days)."""
    d, r = divmod(int(m), DAY)
    return f"D{d} {r // 60:02d}:{r % 60:02d}"


def ts_to_minute(ts: str) -> int:
    return int((datetime.fromisoformat(ts) - D0).total_seconds() // 60)


def day_hour(ts: str):
    """ISO ts -> (sim day, hour). Cheap path: parse the fixed-format string ourselves (hot loop)."""
    m = ts_to_minute(ts)
    d, r = divmod(m, DAY)
    return d, r // 60
