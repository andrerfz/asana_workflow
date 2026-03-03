"""In-memory cache for Asana tasks. Refreshed by background poller."""
import logging
from datetime import datetime, timezone

from asana_client import fetch_tasks, fetch_sections
from classifier import classify_task
from config import DEFAULT_SECTION
from storage import load_overrides

log = logging.getLogger(__name__)

_cached_tasks: list[dict] = []
_cached_sections: list[dict] = []
_last_refresh: str | None = None


async def refresh_cache():
    """Fetch from Asana, classify, apply overrides, store in memory."""
    global _cached_tasks, _cached_sections, _last_refresh

    # Fetch all project tasks (all sections) + section list
    raw_tasks = await fetch_tasks()  # no section_gid → all project tasks
    sections = await fetch_sections()

    local_data = load_overrides()
    overrides = local_data.get("overrides", {})

    classified = []
    for task in raw_tasks:
        if task.get("completed"):
            continue
        result = classify_task(task)
        result = _apply_overrides(result, overrides, task["gid"])
        classified.append(result)

    classified.sort(key=lambda t: (-t["priority"], t["scope_score"]))
    for i, task in enumerate(classified):
        task["rank"] = i + 1

    # Build section counts
    section_counts = {}
    for t in classified:
        sn = t.get("section_name", "Unassigned")
        section_counts[sn] = section_counts.get(sn, 0) + 1

    # Preserve Asana section order, add counts
    ordered_sections = []
    for s in sections:
        count = section_counts.pop(s["name"], 0)
        ordered_sections.append({
            "gid": s["gid"],
            "name": s["name"],
            "count": count,
            "is_default": s["name"] == DEFAULT_SECTION,
        })
    # Add any leftover sections not in the API list
    for name, count in section_counts.items():
        ordered_sections.append({"gid": None, "name": name, "count": count, "is_default": name == DEFAULT_SECTION})

    _cached_tasks = classified
    _cached_sections = ordered_sections
    _last_refresh = datetime.now(timezone.utc).isoformat()
    log.info("Cache refreshed: %d tasks across %d sections", len(classified), len(ordered_sections))


def get_cached_tasks() -> tuple[list[dict], str | None]:
    """Return (tasks, last_refresh_iso). Empty list if never refreshed."""
    return _cached_tasks, _last_refresh


def get_cached_sections() -> list[dict]:
    """Return cached section list with counts."""
    return _cached_sections


def _apply_overrides(result: dict, overrides: dict, gid: str) -> dict:
    """Apply local overrides to a classified task (same logic as routes/tasks.py)."""
    from config import CLUSTER_COLORS
    if gid in overrides:
        ov = overrides[gid]
        if "scope_score" in ov:
            result["scope_score"] = ov["scope_score"]
        if "cluster_id" in ov:
            result["cluster"]["id"] = ov["cluster_id"]
            result["cluster"]["name"] = ov.get("cluster_name", ov["cluster_id"])
            if ov["cluster_id"] in CLUSTER_COLORS:
                result["cluster"]["color"] = CLUSTER_COLORS[ov["cluster_id"]]
        if "priority" in ov:
            result["priority"] = ov["priority"]
        if "ai_reasoning" in ov:
            result["ai_reasoning"] = ov["ai_reasoning"]
        if "ai_summary" in ov:
            result["ai_summary"] = ov["ai_summary"]
        if "source" in ov:
            result["classification_source"] = ov["source"]
    return result
