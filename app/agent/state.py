"""Agent run state persistence, logging, and broadcasting."""
import asyncio
import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from ..config import DATA_DIR
from .phases import AgentPhase
from .queue import agent_queue
from ..services.repo_manager import get_repo
from ..services.worktree_manager import WORKTREE_BASE, get_worktree_status

log = logging.getLogger(__name__)

AGENT_RUNS_DIR = DATA_DIR / "agent_runs"
AGENT_RUNS_DIR.mkdir(parents=True, exist_ok=True)

# Token pricing (Claude models via CLI - approximate)
TOKEN_PRICING = {
    "input": 3.0 / 1_000_000,   # $3 per 1M input tokens
    "output": 15.0 / 1_000_000,  # $15 per 1M output tokens
}

# Safety blocklist for dangerous commands
BASH_BLOCKLIST = "NEVER run these commands: rm -rf, git push, git push --force, docker rm, docker rmi, DROP TABLE, DROP DATABASE, shutdown, reboot, mkfs, dd if="


# ─── Active Workers ───

_active_workers: dict[str, asyncio.Task] = {}
_event_callbacks: list[Callable] = []


def register_event_callback(cb: Callable):
    """Register a callback for agent events (for WebSocket broadcasting)."""
    _event_callbacks.append(cb)


async def _emit_event(event: str, data: dict):
    for cb in _event_callbacks:
        try:
            await cb(event, data)
        except Exception as e:
            log.warning("Event callback error: %s", e)


async def _broadcast_state(task_gid: str):
    """Push full agent run state to all WS clients."""
    run = load_agent_run(task_gid)
    if not run:
        return
    run["is_active"] = task_gid in _active_workers and not _active_workers[task_gid].done()
    await _emit_event("agent:state", {"task_gid": task_gid, "state": run})


# ─── Run File I/O ───

def _run_file(task_gid: str) -> Path:
    return AGENT_RUNS_DIR / f"{task_gid}.json"


def load_agent_run(task_gid: str) -> Optional[dict]:
    f = _run_file(task_gid)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_agent_run(task_gid: str, data: dict):
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    _run_file(task_gid).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def add_log(task_gid: str, message: str, level: str = "info"):
    run = load_agent_run(task_gid)
    if not run:
        return
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    run["logs"].append(entry)
    if len(run["logs"]) > 200:
        run["logs"] = run["logs"][-200:]
    save_agent_run(task_gid, run)
    # Broadcast log to connected WS clients
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit_event("agent:log", {"task_gid": task_gid, "log": entry}))
    except RuntimeError:
        pass  # no event loop running (e.g. called from sync context at startup)


def update_phase(task_gid: str, phase: AgentPhase, **kwargs):
    run = load_agent_run(task_gid)
    if not run:
        return
    run["phase"] = phase.value
    for k, v in kwargs.items():
        run[k] = v
    if phase == AgentPhase.DONE:
        run["completed_at"] = datetime.now(timezone.utc).isoformat()
        # Calculate duration in seconds
        if run.get("created_at"):
            try:
                created = datetime.fromisoformat(run["created_at"])
                run["duration_seconds"] = (datetime.now(timezone.utc) - created).total_seconds()
            except (ValueError, TypeError):
                pass
    save_agent_run(task_gid, run)
    add_log(task_gid, f"Phase → {phase.value}")
    # Broadcast state update so UI badge refreshes immediately
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_emit_event("agent:state", {"task_gid": task_gid, "state": run}))
    except RuntimeError:
        pass


def clear_agent_run(task_gid: str) -> bool:
    """Delete an agent run file (dismiss from UI)."""
    f = _run_file(task_gid)
    if f.exists():
        f.unlink()
        # Also cancel if still active
        if task_gid in _active_workers:
            _active_workers[task_gid].cancel()
            del _active_workers[task_gid]
        # Dequeue if waiting
        agent_queue.dequeue(task_gid)
        return True
    return False


def _enrich_repos_from_disk(run: dict):
    """Discover worktrees on disk that aren't tracked in the run's repos array.

    This handles cases where a worktree was created during coding (e.g., Claude
    Code ran `git worktree add`) but the agent state wasn't updated to include it.
    """
    task_gid = run.get("task_gid")
    if not task_gid:
        return
    task_dir = WORKTREE_BASE / task_gid
    if not task_dir.exists():
        return

    tracked_ids = {r["id"] for r in run.get("repos", [])}

    for repo_dir in task_dir.iterdir():
        if not repo_dir.is_dir() or repo_dir.name in tracked_ids:
            continue
        # Found an untracked worktree on disk — add it to repos
        status = get_worktree_status(task_gid, repo_dir.name)
        if status:
            run.setdefault("repos", []).append({
                "id": repo_dir.name,
                "status": "done" if status.get("commit_count", 0) > 0 else "ready",
                "commits": status.get("commit_count", 0),
                "worktree_path": status["path"],
                "branch": status.get("branch"),
            })


def get_agent_status(task_gid: str) -> Optional[dict]:
    """Get current agent run status."""
    run = load_agent_run(task_gid)
    if not run:
        return None
    run["is_active"] = task_gid in _active_workers and not _active_workers[task_gid].done()
    _enrich_repos_from_disk(run)
    return run


def list_active_agents() -> list[dict]:
    """List all agent runs."""
    results = []
    if not AGENT_RUNS_DIR.exists():
        return results
    for f in AGENT_RUNS_DIR.glob("*.json"):
        try:
            run = json.loads(f.read_text())
            gid = run.get("task_gid", f.stem)
            run["is_active"] = gid in _active_workers and not _active_workers[gid].done()
            _enrich_repos_from_disk(run)
            results.append(run)
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(results, key=lambda r: r.get("created_at", ""), reverse=True)


# ─── Run Lifecycle ───

def _archive_previous_run(task_gid: str):
    """Archive existing run to history before starting a new one."""
    prev = load_agent_run(task_gid)
    if not prev or prev.get("phase") in (AgentPhase.QUEUED.value, None):
        return  # nothing meaningful to archive

    archive_dir = AGENT_RUNS_DIR / "history"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Filename: {task_gid}_{timestamp}.json
    ts = prev.get("created_at", "unknown").replace(":", "-").replace("+", "")[:19]
    archive_file = archive_dir / f"{task_gid}_{ts}.json"
    archive_file.write_text(json.dumps(prev, indent=2, ensure_ascii=False))
    log.info("Archived previous run for %s → %s", task_gid, archive_file.name)


def load_run_history(task_gid: str) -> list[dict]:
    """Load all archived runs for a task, sorted by date (newest first)."""
    archive_dir = AGENT_RUNS_DIR / "history"
    if not archive_dir.exists():
        return []
    runs = []
    for f in archive_dir.glob(f"{task_gid}_*.json"):
        try:
            runs.append(json.loads(f.read_text()))
        except Exception:
            pass
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs


def create_agent_run(task_gid: str, task_name: str, repos: list[dict]) -> dict:
    # Archive any existing run before overwriting
    _archive_previous_run(task_gid)

    run = {
        "task_gid": task_gid,
        "task_name": task_name,
        "phase": AgentPhase.QUEUED.value,
        "repos": [{"id": r["id"], "status": "pending", "commits": 0, "worktree_path": None} for r in repos],
        "logs": [],
        "plan": None,
        "question": None,
        "tokens": {"input": 0, "output": 0},
        "token_budget": agent_queue.config["token_budget_per_task"],
        "cost_usd": 0.0,
        "num_api_calls": 0,
        "duration_seconds": None,
        "retries": 0,
        "max_retries": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
        "error": None,
    }
    save_agent_run(task_gid, run)
    return run


def _accumulate_cost(task_gid: str, cli_result: dict):
    """Accumulate token usage and cost from a CLI result into the agent run."""
    run = load_agent_run(task_gid)
    if not run:
        return

    # Extract usage from parsed JSON if available
    parsed = cli_result.get("parsed", {})
    if isinstance(parsed, dict):
        usage = parsed.get("usage", {})
    else:
        usage = {}

    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    # Accumulate tokens
    run["tokens"]["input"] = run["tokens"].get("input", 0) + input_tokens
    run["tokens"]["output"] = run["tokens"].get("output", 0) + output_tokens

    # Calculate cost: prefer cost from CLI, otherwise estimate
    cost = parsed.get("cost_usd")
    if cost is None and (input_tokens or output_tokens):
        cost = input_tokens * TOKEN_PRICING["input"] + output_tokens * TOKEN_PRICING["output"]
    cost = cost or 0

    run["cost_usd"] = run.get("cost_usd", 0) + cost
    run["num_api_calls"] = run.get("num_api_calls", 0) + 1

    save_agent_run(task_gid, run)


def get_worktree_diff(task_gid: str, repo_id: str) -> dict:
    """Get changed files and diff stats for a worktree."""
    run = load_agent_run(task_gid)
    if not run:
        return {"files": [], "error": "No agent run"}

    repo_entry = next((r for r in run.get("repos", []) if r["id"] == repo_id), None)
    if not repo_entry or not repo_entry.get("worktree_path"):
        return {"files": [], "error": "No worktree"}

    wt_path = repo_entry["worktree_path"]
    repo = get_repo(repo_id)
    default_branch = repo.get("default_branch", "master") if repo else "master"

    try:
        # Get changed files with stats
        result = subprocess.run(
            ["git", "diff", "--stat", "--numstat", f"origin/{default_branch}...HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )

        files = []
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 3:
                    added = int(parts[0]) if parts[0] != "-" else 0
                    removed = int(parts[1]) if parts[1] != "-" else 0
                    filename = parts[2]
                    files.append({"file": filename, "added": added, "removed": removed})

        return {
            "files": files,
            "total_added": sum(f["added"] for f in files),
            "total_removed": sum(f["removed"] for f in files),
        }
    except Exception as e:
        return {"files": [], "error": str(e)}


def _check_secrets(wt_path: str, task_gid: str, repo_id: str):
    """Check for accidentally committed secrets."""
    SECRET_PATTERNS = [".env", "credentials", "secret", "api_key", "password", "token"]
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1..HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return
        warnings = []
        for filename in result.stdout.strip().split("\n"):
            fl = filename.lower()
            for pattern in SECRET_PATTERNS:
                if pattern in fl:
                    warnings.append(f"Suspicious file: {filename}")
                    break
        if warnings:
            add_log(task_gid, f"[{repo_id}] Warning: Secret detection: {'; '.join(warnings)}", "warning")
    except Exception:
        pass


def _sync_agent_files(project_root: str, worktree_path: str, repo_id: str, task_gid: str):
    """No-op — agent test commands are now defined directly in repos.json
    as full docker commands, so no files need to be synced to the worktree."""
    pass


# ─── Agent Settings ───

DEFAULT_AGENT_SETTINGS = {
    "section_on_start": "Desarrollo",
    "section_on_done": "Revisión de código",
    "section_on_error": None,
    "agent_timeout_minutes": 45,
}


def load_agent_settings() -> dict:
    """Load agent settings from disk, falling back to defaults."""
    from ..config import AGENT_SETTINGS_FILE
    try:
        if AGENT_SETTINGS_FILE.exists():
            return {**DEFAULT_AGENT_SETTINGS, **json.loads(AGENT_SETTINGS_FILE.read_text())}
    except Exception as e:
        log.warning("Failed to load agent settings: %s", e)
    return dict(DEFAULT_AGENT_SETTINGS)


def save_agent_settings(settings: dict):
    """Save agent settings to disk."""
    from ..config import AGENT_SETTINGS_FILE
    AGENT_SETTINGS_FILE.write_text(json.dumps(settings, indent=2))
