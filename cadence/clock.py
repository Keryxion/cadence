"""The only production source of wall and elapsed time."""
from datetime import datetime, timezone, tzinfo
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import time


class Clock(Protocol):
    def now(self) -> float: ...
    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


def format_timestamp(epoch: float, zone: tzinfo | None = None) -> str:
    value = datetime.fromtimestamp(epoch, timezone.utc if zone is None else zone)
    text = value.isoformat(timespec="seconds")
    return text.removesuffix("+00:00") + "Z" if zone is None else text


def report_zone(name: str) -> ZoneInfo:
    if (not isinstance(name, str) or not name or name.startswith(("right/", "posix/"))
            or name in {"localtime", "posixrules", "EST", "MST", "HST", "CET", "EET", "MET", "WET"}):
        raise ValueError("Use an IANA timezone name such as America/New_York or UTC.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid IANA timezone: {name!r}") from exc
