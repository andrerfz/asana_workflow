"""Task routes: list, classify, sync, clusters, scope config."""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel

from ..services.asana_client import fetch_tasks, update_task
from ..services.classifier import classify_task
from ..config import CLUSTER_COLORS, STORY_POINT_FIELD_GID
from ..services.storage import load_overrides, save_overrides
from ..services.task_cache import get_cached_tasks, get_cached_sections, refresh_cache

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
async def get_tasks():
    """Serve tasks from cache. Cache is refreshed by background poller."""
    tasks, last_refresh = get_cached_tasks()
    if not tasks:
        # First request before poller finishes — fetch directly
        await refresh_cache()
        tasks, last_refresh = get_cached_tasks()
    return {"tasks": tasks, "count": len(tasks), "last_refresh": last_refresh, "sections": get_cached_sections()}


@router.post("/tasks/refresh")
async def force_refresh():
    """Force an immediate cache refresh (manual Refresh button)."""
    await refresh_cache()
    tasks, last_refresh = get_cached_tasks()
    return {"tasks": tasks, "count": len(tasks), "last_refresh": last_refresh, "sections": get_cached_sections()}


class UpdateClassification(BaseModel):
    scope_score: Optional[int] = None
    cluster_id: Optional[str] = None
    cluster_name: Optional[str] = None
    priority: Optional[int] = None


@router.put("/tasks/{task_gid}/classify")
async def update_classification(task_gid: str, body: UpdateClassification):
    local_data = load_overrides()
    overrides = local_data.setdefault("overrides", {})
    current = overrides.get(task_gid, {})

    if body.scope_score is not None:
        current["scope_score"] = body.scope_score
    if body.cluster_id is not None:
        current["cluster_id"] = body.cluster_id
        if body.cluster_name:
            current["cluster_name"] = body.cluster_name
    if body.priority is not None:
        current["priority"] = body.priority

    overrides[task_gid] = current
    local_data["overrides"] = overrides
    save_overrides(local_data)

    # Re-apply overrides to cache so UI updates immediately
    await refresh_cache()
    return {"status": "ok", "overrides": current}


@router.post("/sync")
async def sync_to_asana():
    raw_tasks = await fetch_tasks()
    local_data = load_overrides()
    overrides = local_data.get("overrides", {})

    synced, errors = [], []
    for task in raw_tasks:
        if task.get("completed"):
            continue
        gid = task["gid"]
        result = classify_task(task)
        score = overrides.get(gid, {}).get("scope_score", result["scope_score"])
        try:
            await update_task(gid, {STORY_POINT_FIELD_GID: str(score)})
            synced.append({"gid": gid, "name": task["name"], "score": score})
        except Exception as e:
            errors.append({"gid": gid, "name": task["name"], "error": str(e)})

    # Auto-snapshot on sync
    from routes.history import _take_snapshot
    await _take_snapshot(raw_tasks, overrides)

    # Refresh cache after sync
    await refresh_cache()

    return {"synced": len(synced), "errors": len(errors), "details": synced, "error_details": errors}


@router.get("/debug/sections")
async def debug_sections():
    """Temporary debug: show raw section data."""
    from asana_client import fetch_sections, fetch_tasks
    sections = await fetch_sections()
    raw_tasks = await fetch_tasks()
    sample = []
    for t in raw_tasks[:5]:
        sample.append({
            "gid": t["gid"],
            "name": t.get("name", ""),
            "_section_name": t.get("_section_name", "NOT SET"),
            "memberships": t.get("memberships", []),
        })
    return {"sections": sections, "task_samples": sample, "total_tasks": len(raw_tasks)}


@router.get("/clusters")
async def get_clusters():
    """Build cluster stats from cached tasks."""
    tasks, _ = get_cached_tasks()
    clusters = {}
    for t in tasks:
        cid = t["cluster"]["id"]
        if cid not in clusters:
            clusters[cid] = {
                "id": cid, "name": t["cluster"]["name"],
                "color": t["cluster"].get("color", "#888"),
                "count": 0, "total_scope": 0,
            }
        clusters[cid]["count"] += 1
        clusters[cid]["total_scope"] += t["scope_score"]

    for c in clusters.values():
        c["avg_scope"] = round(c["total_scope"] / c["count"], 1) if c["count"] > 0 else 0

    return {"clusters": list(clusters.values())}


@router.get("/scope-config")
async def get_scope_config():
    local_data = load_overrides()
    defaults = {
        "1": {"label": "Tiny", "description": "Single query fix, filter bug, one-line change", "color": "#22c55e"},
        "2": {"label": "Small", "description": "Single file logic fix, simple UI tweak", "color": "#3b82f6"},
        "3": {"label": "Medium", "description": "Multi-file change, API + frontend coordination", "color": "#f59e0b"},
        "4": {"label": "Large", "description": "New endpoint with logic + tests, significant refactor", "color": "#f97316"},
        "5": {"label": "XL", "description": "Cross-system feature, database migration, new module", "color": "#ef4444"},
    }
    return local_data.get("scope_config", defaults)


class ScopeConfig(BaseModel):
    label: str
    description: str
    color: str


@router.put("/scope-config/{level}")
async def update_scope_config(level: str, body: ScopeConfig):
    local_data = load_overrides()
    config = local_data.setdefault("scope_config", {})
    config[level] = {"label": body.label, "description": body.description, "color": body.color}
    local_data["scope_config"] = config
    save_overrides(local_data)
    return {"status": "ok"}
