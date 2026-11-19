"""One simulated clock for the whole run (END_TO_END_ITSM.md §7.6).

The orchestrator holds the simulated UTC now and passes it on: to the change graph as `simulated_now` (the change
repository's `cm_agents.clock.pin`, via `pinned()`), and to pm-agent's window functions as arguments. ServiceNow
date-times are UTC strings with `display_value=false` (DISCOVERY item 12).
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

SN_FORMAT = "%Y-%m-%d %H:%M:%S"


class ClockError(ValueError):
    pass


def parse_sn(value: str) -> datetime:
    """A ServiceNow UTC date-time string as an aware datetime."""
    try:
        return datetime.strptime(value.strip(), SN_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        raise ClockError(f"not a ServiceNow UTC date-time: {value!r}") from None


class Clock:
    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ClockError("the clock needs an aware datetime (UTC)")
        self._now = start.astimezone(UTC)

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, hours: float = 1) -> datetime:
        """Move forward one tick (an hour by default). The clock never goes back."""
        if hours <= 0:
            raise ClockError("the clock only moves forward")
        self._now += timedelta(hours=hours)
        return self._now

    def sn(self, moment: datetime | None = None) -> str:
        """`moment` (default now) as a ServiceNow UTC string."""
        m = moment or self._now
        if m.tzinfo is None:
            raise ClockError("refusing a naive datetime")
        return m.astimezone(UTC).strftime(SN_FORMAT)

    @contextmanager
    def pinned(self) -> Iterator[datetime]:
        """Pin the change repository's clock to this clock's now for the block, then unpin it."""
        from cm_agents import clock as cm_clock

        cm_clock.pin(self._now)
        try:
            yield self._now
        finally:
            cm_clock.pin(None)
