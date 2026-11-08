from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
D0 = datetime(2027, 1, 4, tzinfo=IST)
DAY = 1440


def fmt_minute(m: int) -> str:
    """Sim minute -> 'D3 14:00' (negative minutes are history days)."""
    d, r = divmod(int(m), DAY)
    return f"D{d} {r // 60:02d}:{r % 60:02d}"


def set_origin(ts: str, sim_minute: int) -> None:
    """Derive D0 from the simulator itself (its ts minus its sim_minute), so a scenario with another start
    date can't silently shift every time window."""
    global D0
    D0 = datetime.fromisoformat(ts) - timedelta(minutes=int(sim_minute))


def ts_to_minute(ts: str) -> int:
    return int((datetime.fromisoformat(ts) - D0).total_seconds() // 60)

