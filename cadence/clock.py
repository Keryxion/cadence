"""The only production source of wall and elapsed time."""
from datetime import datetime, timezone, tzinfo
from typing import Protocol
import time


class Clock(Protocol):
    def now(self) -> float: ...
    def monotonic(self) -> float: ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


try:
    from hermes_time import format_timestamp
except ImportError:
    # Hermes releases predating the shared formatter still load this plugin.
    def format_timestamp(epoch: float, zone: tzinfo | None = None) -> str:
        value = datetime.fromtimestamp(epoch, timezone.utc if zone is None else zone)
        text = value.isoformat(timespec="seconds")
        return text.removesuffix("+00:00") + "Z" if zone is None else text
