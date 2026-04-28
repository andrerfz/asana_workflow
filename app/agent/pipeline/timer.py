"""Work-time budget tracker — pauses during human waits."""
import time as _time
from typing import Optional

from ..phases import AgentPhase
from ..state import update_phase, add_log

# Active timers keyed by task_gid
agent_timers: dict[str, "AgentTimer"] = {}


class AgentTimer:
    """Tracks active work time, excluding pauses for human input."""

    def __init__(self, budget_seconds: float):
        self.budget = budget_seconds
        self.elapsed = 0.0
        self._started_at: Optional[float] = _time.monotonic()

    def pause(self):
        """Pause the timer (entering human-wait phase)."""
        if self._started_at is not None:
            self.elapsed += _time.monotonic() - self._started_at
            self._started_at = None

    def resume(self):
        """Resume the timer (exiting human-wait phase)."""
        if self._started_at is None:
            self._started_at = _time.monotonic()

    @property
    def remaining(self) -> float:
        """Seconds of work budget remaining."""
        current = self.elapsed
        if self._started_at is not None:
            current += _time.monotonic() - self._started_at
        return max(0, self.budget - current)

    @property
    def exceeded(self) -> bool:
        return self.remaining <= 0

    @property
    def elapsed_minutes(self) -> int:
        current = self.elapsed
        if self._started_at is not None:
            current += _time.monotonic() - self._started_at
        return int(current / 60)


def check_timeout(task_gid: str) -> bool:
    """Check if the agent has exceeded its work-time budget. Returns True if timed out."""
    timer = agent_timers.get(task_gid)
    if timer and timer.exceeded:
        mins = timer.elapsed_minutes
        update_phase(task_gid, AgentPhase.ERROR, error=f"Agent work-time timeout ({mins} minutes of active work)")
        add_log(task_gid, f"Agent timeout exceeded ({mins} min active work)", "error")
        return True
    return False
