"""Time is injected, never ambient.

Invariant 1: live and replay share one code path and differ only by the injected
`Clock` and `ExecutorPort`. Any `datetime.now()` call inside `agent/` breaks that.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class VirtualClock:
    """Replay clock. Advancing it is the only way time passes during evaluation."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        self._now = self._now + delta
        return self._now

    def set(self, when: datetime) -> datetime:
        if when < self._now:
            raise ValueError(f"virtual clock cannot move backwards: {when} < {self._now}")
        self._now = when
        return self._now
