"""History routes: diff-based tracking of resolved tasks from sync snapshots."""
from datetime import datetime, timezone
from fastapi import APIRouter

from ..services.asana_client import fetch_tasks
from ..services.classifier import classify_task
from ..services.storage import load_overrides, load_history, save_history, load_resolved, save_resolved

router = APIRouter(prefix="/api/history", tags=["history"])


async def _take_snapshot(raw_tasks: list = None, overrides: dict = None):
    """
    Save a snapshot and detect resolved tasks by diffing with previous snapshot.
    A task is "resolved" when it disappears from the active list between syncs
    (reassigned to QA, moved to another section, completed, etc.).
    """
    if raw_tasks is None:
        raw_tasks = await fetch_tasks()
    if overrides is None:
        overrides = load_overrides().get("overrides", {})

    open_tasks = [t for t in raw_tasks if not t.get("completed")]
    now = datetime.now(timezone.utc).isoformat()

    # Build current task map
    current_gids = set()
    current_task_data = {}
    for task in open_tasks:
        gid = task["gid"]
        current_gids.add(gid)
        result = classify_task(task)
        if gid in overrides:
            ov = overrides[gid]
            if "scope_score" in ov:
                result["scope_score"] = ov["scope_score"]
            if "cluster_id" in ov:
                result["cluster"]["id"] = ov["cluster_id"]
                result["cluster"]["name"] = ov.get("cluster_name", ov["cluster_id"])
            if "priority" in ov:
                result["priority"] = ov["priority"]
        current_task_data[gid] = {
            "gid": gid,
            "name": task.get("name", ""),
            "tipo": result.get("tipo", "N/A"),
            "cluster_id": result["cluster"]["id"],
            "cluster_name": result["cluster"]["name"],
            "cluster_color": result["cluster"].get("color", "#888"),
            "scope_score": result["scope_score"],
            "priority": result["priority"],
            "section_name": result.get("section_name", "Unassigned"),
            "permalink_url": result.get("permalink_url", ""),
            "tags": [tag.get("name", "") for tag in task.get("tags", [])],
        }

    # Diff with previous snapshot to find resolved tasks
    history = load_history()
    resolved = load_resolved()
    resolved_gids = {r["gid"] for r in resolved}

    if history:
        prev = history[-1]
        prev_gids = {t["gid"] for t in prev.get("tasks", [])}
        disappeared = prev_gids - current_gids - resolved_gids

        for gid in disappeared:
            # Find task data from previous snapshot
            prev_task = next((t for t in prev["tasks"] if t["gid"] == gid), None)
            if prev_task:
                resolved.append({
                    "gid": gid,
                    "name": prev_task.get("name", ""),
                    "tipo": prev_task.get("tipo", "N/A"),
                    "cluster_id": prev_task.get("cluster_id", prev_task.get("cluster", "standalone")),
                    "cluster_name": prev_task.get("cluster_name", ""),
                    "cluster_color": prev_task.get("cluster_color", "#888"),
                    "scope_score": prev_task.get("scope_score", 0),
                    "priority": prev_task.get("priority", 0),
                    "permalink_url": prev_task.get("permalink_url", ""),
                    "tags": prev_task.get("tags", []),
                    "resolved_at": now,
                    "first_seen": prev_task.get("first_seen", prev.get("timestamp", now)),
                })

        if disappeared:
            save_resolved(resolved)

    # Save snapshot
    snapshot = {
        "timestamp": now,
        "open_count": len(open_tasks),
        "resolved_count": len(resolved),
        "tasks": list(current_task_data.values()),
    }
    history.append(snapshot)
    if len(history) > 100:
        history = history[-100:]
    save_history(history)
    return snapshot


@router.post("/snapshot")
async def take_snapshot_route():
    snapshot = await _take_snapshot()
    history = load_history()
    return {"status": "ok", "snapshot_count": len(history), "open_count": snapshot["open_count"]}


@router.get("")
async def get_history():
    return {"snapshots": load_history()}


@router.get("/resolved")
async def get_resolved():
    """Get all tasks that have been resolved (disappeared from active list between syncs)."""
    resolved = load_resolved()
    resolved.sort(key=lambda t: t.get("resolved_at", ""), reverse=True)
    return {"tasks": resolved, "count": len(resolved)}
