"""Agent queue manager — limits concurrent agents and priority-orders tasks."""
import asyncio
import logging
import json
from typing import Optional, Callable
from pathlib import Path
from ..config import DATA_DIR

log = logging.getLogger(__name__)

# Queue config file
QUEUE_CONFIG_FILE = DATA_DIR / "agent_queue_config.json"

DEFAULT_CONFIG = {
    "max_parallel": 2,
    "token_budget_per_task": 200000,  # max tokens per agent run
}


class AgentQueue:
    """Priority queue for managing concurrent agent execution."""

    def __init__(self):
        self._queue: list[dict] = []  # [{task_gid, priority, task, branch_slug, base_branch}]
        self._running: dict[str, asyncio.Task] = {}
        self._config = self._load_config()
        self._start_callback: Optional[Callable] = None

    def _load_config(self) -> dict:
        """Load queue config from disk or return defaults."""
        if QUEUE_CONFIG_FILE.exists():
            try:
                return json.loads(QUEUE_CONFIG_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return dict(DEFAULT_CONFIG)

    def save_config(self, config: dict):
        """Update and persist queue configuration."""
        self._config.update(config)
        QUEUE_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUEUE_CONFIG_FILE.write_text(json.dumps(self._config, indent=2))
        log.info("Queue config saved: %s", self._config)

    @property
    def config(self) -> dict:
        """Return current queue config (copy)."""
        return dict(self._config)

    def set_start_callback(self, cb: Callable):
        """Set the callback that actually starts an agent.

        Callback signature: async cb(task_gid, task, branch_slug, base_branch)
        """
        self._start_callback = cb

    def enqueue(self, task_gid: str, priority: int, task: dict, branch_slug: str,
                base_branch: str = None):
        """Add a task to the queue."""
        # Don't double-queue
        if any(q["task_gid"] == task_gid for q in self._queue):
            log.info("Task %s already in queue, skipping", task_gid)
            return
        if task_gid in self._running:
            log.info("Task %s already running, skipping", task_gid)
            return

        self._queue.append({
            "task_gid": task_gid,
            "priority": priority,
            "task": task,
            "branch_slug": branch_slug,
            "base_branch": base_branch,
        })
        # Sort by priority descending (highest first)
        self._queue.sort(key=lambda q: -q["priority"])
        log.info("Queued task %s (priority %d), queue size: %d", task_gid, priority,
                 len(self._queue))

    def dequeue(self, task_gid: str):
        """Remove a task from the queue."""
        original_len = len(self._queue)
        self._queue = [q for q in self._queue if q["task_gid"] != task_gid]
        if len(self._queue) < original_len:
            log.info("Dequeued task %s", task_gid)

    def reorder(self, task_gids: list[str]):
        """Reorder the queue to match the given GID order."""
        gid_order = {gid: i for i, gid in enumerate(task_gids)}
        self._queue.sort(key=lambda q: gid_order.get(q["task_gid"], 999))
        log.info("Queue reordered")

    def register_running(self, task_gid: str, worker: asyncio.Task):
        """Register a directly-started agent (bypassing queue)."""
        self._running[task_gid] = worker
        log.info("Registered running task %s", task_gid)

    def unregister_running(self, task_gid: str):
        """Called when an agent finishes. Triggers processing of next queued task."""
        self._running.pop(task_gid, None)
        log.info("Unregistered task %s, running count: %d", task_gid, len(self._running))
        # Try to start next queued task
        asyncio.ensure_future(self._process_queue())

    async def _process_queue(self):
        """Start queued tasks if slots are available."""
        while self._queue and len(self._running) < self._config["max_parallel"]:
            if not self._start_callback:
                log.warning("No start callback registered, cannot process queue")
                break
            item = self._queue.pop(0)
            task_gid = item["task_gid"]
            log.info("Dequeuing task %s (priority %d) to start", task_gid,
                     item["priority"])
            # Reserve the slot immediately to prevent TOCTOU race:
            # another _process_queue could run during the await and see a stale count
            _placeholder = asyncio.get_event_loop().create_future()
            self._running[task_gid] = _placeholder
            try:
                await self._start_callback(
                    task_gid, item["task"], item["branch_slug"],
                    item["base_branch"]
                )
            except Exception as e:
                # Release placeholder on failure (start_agent may not have registered)
                if self._running.get(task_gid) is _placeholder:
                    del self._running[task_gid]
                log.error("Failed to start queued task %s: %s", task_gid, e)

    @property
    def queue_list(self) -> list[dict]:
        """Return current queue state for API."""
        return [
            {
                "task_gid": q["task_gid"],
                "priority": q["priority"],
                "task_name": q["task"].get("name", "")
            } for q in self._queue
        ]

    @property
    def running_count(self) -> int:
        """Return count of currently running agents."""
        # Clean up finished tasks
        finished = [gid for gid, t in self._running.items() if t.done()]
        for gid in finished:
            del self._running[gid]
        return len(self._running)

    @property
    def slots_available(self) -> int:
        """Return number of available execution slots."""
        return max(0, self._config["max_parallel"] - self.running_count)


# Global singleton instance
agent_queue = AgentQueue()
