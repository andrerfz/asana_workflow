"""Agent memory — per-repo knowledge base that improves over time."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from ..config import DATA_DIR

log = logging.getLogger(__name__)

MEMORY_DIR = DATA_DIR / "agent_memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

MAX_MEMORY_ENTRIES = 50  # per repo
MAX_CONTEXT_CHARS = 3000  # max chars to inject into agent prompt


def _memory_file(repo_id: str) -> Path:
    """Get the memory file path for a repo."""
    return MEMORY_DIR / f"{repo_id}.json"


def load_memory(repo_id: str) -> dict:
    """Load memory for a repo. Returns empty structure if not found."""
    f = _memory_file(repo_id)
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning(f"Failed to load memory for {repo_id}")
    return {
        "repo_id": repo_id,
        "entries": [],
        "patterns": {},  # {pattern_name: description}
        "updated_at": None,
    }


def save_memory(repo_id: str, memory: dict):
    """Save memory for a repo."""
    try:
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        _memory_file(repo_id).write_text(json.dumps(memory, indent=2, ensure_ascii=False))
    except Exception as e:
        log.error(f"Failed to save memory for {repo_id}: {e}")


def add_memory_entry(repo_id: str, entry_type: str, content: str, task_gid: str = ""):
    """Add a memory entry for a repo.

    Args:
        repo_id: Repository identifier
        entry_type: "success" | "error_fix" | "pattern" | "note"
        content: Entry content (will be truncated to 500 chars)
        task_gid: Optional Asana task GID
    """
    try:
        memory = load_memory(repo_id)
        memory["entries"].append({
            "type": entry_type,
            "content": content[:500],
            "task_gid": task_gid,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # Keep only recent entries
        if len(memory["entries"]) > MAX_MEMORY_ENTRIES:
            memory["entries"] = memory["entries"][-MAX_MEMORY_ENTRIES:]
        save_memory(repo_id, memory)
    except Exception as e:
        log.error(f"Failed to add memory entry for {repo_id}: {e}")


def get_memory_context(repo_id: str) -> str:
    """Get formatted memory context to inject into agent prompts.

    Returns a formatted string with patterns and successful approaches.
    Will be truncated to MAX_CONTEXT_CHARS to stay within token budget.
    """
    try:
        memory = load_memory(repo_id)
        if not memory["entries"] and not memory["patterns"]:
            return ""

        parts = [f"\n## Agent Memory for {repo_id}"]

        # Patterns first (most useful)
        if memory.get("patterns"):
            parts.append("### Known Patterns")
            for name, desc in list(memory["patterns"].items())[:10]:
                parts.append(f"- {name}: {desc}")

        # Recent successful approaches
        successes = [e for e in memory["entries"] if e["type"] == "success"][-5:]
        if successes:
            parts.append("### What worked before")
            for e in successes:
                parts.append(f"- {e['content']}")

        # Common error fixes
        fixes = [e for e in memory["entries"] if e["type"] == "error_fix"][-5:]
        if fixes:
            parts.append("### Common error fixes")
            for e in fixes:
                parts.append(f"- {e['content']}")

        result = "\n".join(parts)
        return result[:MAX_CONTEXT_CHARS]
    except Exception as e:
        log.error(f"Failed to get memory context for {repo_id}: {e}")
        return ""


def update_memory_after_run(repo_id: str, task_gid: str, run: dict):
    """Auto-update memory after a completed agent run.

    Extracts useful info from the run to build the knowledge base.
    This is best-effort and should never fail the agent.
    """
    try:
        phase = run.get("phase", "")
        plan = run.get("plan", "")
        task_name = run.get("task_name", "")

        if phase == "done" and plan:
            # Record successful approach
            summary = f"Task '{task_name[:80]}': {plan[:200]}"
            add_memory_entry(repo_id, "success", summary, task_gid)

        if phase == "error":
            error = run.get("error", "")
            if error:
                add_memory_entry(repo_id, "error_fix",
                               f"Error on '{task_name[:60]}': {error[:200]}", task_gid)

        # Check if tests failed and were fixed (retries > 0 but ended in done)
        if phase == "done" and run.get("retries", 0) > 0:
            add_memory_entry(
                repo_id, "error_fix",
                f"Tests failed {run['retries']}x on '{task_name[:60]}' but were auto-fixed",
                task_gid,
            )
    except Exception as e:
        log.error(f"Failed to update memory after run for {repo_id}: {e}")


def clear_memory(repo_id: str) -> bool:
    """Clear all memory for a repo. Returns True if successful."""
    try:
        f = _memory_file(repo_id)
        if f.exists():
            f.unlink()
        return True
    except Exception as e:
        log.error(f"Failed to clear memory for {repo_id}: {e}")
        return False


def get_all_memory_repos() -> list[str]:
    """Get list of all repos with stored memory."""
    try:
        return [f.stem for f in MEMORY_DIR.glob("*.json")]
    except Exception as e:
        log.error(f"Failed to list memory repos: {e}")
        return []
