"""AI classification routes."""
import os
from fastapi import APIRouter, HTTPException

from ..services.asana_client import fetch_tasks
from ..services.ai_classifier import ai_classify_task, ai_classify_batch, clear_cache
from ..services.storage import load_overrides, save_overrides
from ..services.task_cache import refresh_cache

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/classify-all")
async def ai_classify_all(force: bool = False):
    raw_tasks = await fetch_tasks()
    active = [t for t in raw_tasks if not t.get("completed")]
    results = await ai_classify_batch(active, force=force)

    local_data = load_overrides()
    overrides = local_data.setdefault("overrides", {})
    applied = 0
    for gid, classification in results.items():
        overrides[gid] = {
            "scope_score": classification["scope_score"],
            "priority": classification["priority"],
            "cluster_id": classification["cluster_id"],
            "cluster_name": classification.get("cluster_name", ""),
            "area": classification.get("area", "other"),
            "ai_reasoning": classification.get("reasoning", ""),
            "ai_summary": classification.get("summary", ""),
            "source": "ai",
        }
        applied += 1

    local_data["overrides"] = overrides
    save_overrides(local_data)
    await refresh_cache()
    return {"classified": applied, "total": len(active)}


@router.post("/classify/{task_gid}")
async def ai_classify_single(task_gid: str, force: bool = False):
    raw_tasks = await fetch_tasks()
    task = next((t for t in raw_tasks if t["gid"] == task_gid), None)
    if not task:
        raise HTTPException(404, f"Task {task_gid} not found")

    result = await ai_classify_task(task, force=force)
    if not result:
        raise HTTPException(502, "AI classification failed. Check ANTHROPIC_API_KEY in .env")

    local_data = load_overrides()
    overrides = local_data.setdefault("overrides", {})
    overrides[task_gid] = {
        "scope_score": result["scope_score"],
        "priority": result["priority"],
        "cluster_id": result["cluster_id"],
        "cluster_name": result.get("cluster_name", ""),
        "area": result.get("area", "other"),
        "ai_reasoning": result.get("reasoning", ""),
        "ai_summary": result.get("summary", ""),
        "source": "ai",
    }
    local_data["overrides"] = overrides
    save_overrides(local_data)
    await refresh_cache()
    return {"status": "ok", "classification": result}


@router.post("/branch-name/{task_gid}")
async def generate_branch_name(task_gid: str):
    """Generate a short English branch slug from task name using AI. Cached in overrides."""
    import httpx
    from ..config import ANTHROPIC_API_KEY, ANTHROPIC_BASE, CLAUDE_MODEL

    # Check cache first
    local_data = load_overrides()
    ov = local_data.get("overrides", {}).get(task_gid, {})
    cached_branch = ov.get("branch_name")
    if cached_branch:
        return {"branch": cached_branch, "cached": True}

    raw_tasks = await fetch_tasks()
    task = next((t for t in raw_tasks if t["gid"] == task_gid), None)
    if not task:
        raise HTTPException(404, f"Task {task_gid} not found")

    tipo = "fix" if "error" in (task.get("name", "") + " " + task.get("resource_subtype", "")).lower() else "feature"
    if ov:
        src_tipo = ov.get("cluster_name", "")
        if "error" in src_tipo.lower() or "sentry" in src_tipo.lower():
            tipo = "fix"

    prompt = (
        f"Generate a short git branch slug (2-5 words, lowercase, hyphen-separated, English) "
        f"for this task. Return ONLY the slug, nothing else.\n\n"
        f"Task: {task.get('name', '')}\n"
        f"Description: {(task.get('notes', '') or '')[:200]}"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ANTHROPIC_BASE,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 50,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"AI error: {resp.text}")

    slug = resp.json()["content"][0]["text"].strip().lower()
    slug = slug.strip("`/ \n").replace(" ", "-")
    branch = f"{tipo}/{task_gid}/{slug}"

    # Save to cache
    overrides = local_data.setdefault("overrides", {})
    overrides.setdefault(task_gid, {})["branch_name"] = branch
    save_overrides(local_data)

    return {"branch": branch, "cached": False}


@router.delete("/cache")
async def clear_ai_cache_route():
    clear_cache()
    return {"status": "ok", "message": "AI cache cleared"}


@router.get("/status")
async def ai_status():
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "available": bool(api_key),
        "model": os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
    }
