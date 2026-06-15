"""AI classification routes."""
import os
import logging
from fastapi import APIRouter, HTTPException

from ..services.asana_client import fetch_tasks
from ..services.ai_classifier import ai_classify_task, ai_classify_batch, clear_cache
from ..services.storage import load_overrides, save_overrides
from ..services.task_cache import refresh_cache

log = logging.getLogger(__name__)

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
            "areas": classification.get("areas", []),
            "ai_reasoning": classification.get("reasoning", ""),
            "ai_summary": classification.get("summary", ""),
            "source": "ai",
        }
        applied += 1

    local_data["overrides"] = overrides
    save_overrides(local_data)
    try:
        await refresh_cache()
    except Exception as e:
        log.warning("Cache refresh failed after classify-all (results saved): %s", e)
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
        "areas": result.get("areas", []),
        "ai_reasoning": result.get("reasoning", ""),
        "ai_summary": result.get("summary", ""),
        "source": "ai",
    }
    local_data["overrides"] = overrides
    save_overrides(local_data)
    try:
        await refresh_cache()
    except Exception as e:
        log.warning("Cache refresh failed after classify (result saved): %s", e)
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
        f"for this task. Return ONLY the slug, nothing else. Use hyphens not underscores.\n\n"
        f"Task: {task.get('name', '')}\n"
        f"Description: {(task.get('notes', '') or '')[:200]}"
    )

    proxy_url = __import__('os').environ.get("HTTPS_PROXY") or __import__('os').environ.get("https_proxy")
    async with httpx.AsyncClient(trust_env=False, proxy=proxy_url or None) as client:
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
    slug = slug.strip("`/ \n").replace(" ", "-").replace("_", "-")
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


@router.get("/usage")
async def ai_usage():
    """Today's real classification spend (paid ANTHROPIC_API_KEY), computed from
    the usage returned on each API call. Spend, not remaining account credit —
    the Messages API exposes no balance endpoint."""
    from ..services.usage_tracker import today_usage
    return {
        "model": os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
        "today": today_usage(),
    }


@router.get("/claude-usage")
async def claude_usage():
    """Local, honest Claude Code subscription usage insights for the last 24h
    (what's contributing to limit usage). NOT a quota % — the real /status
    figures need the user:profile OAuth scope the headless token lacks."""
    from ..services.claude_usage import usage_insights
    return usage_insights()


@router.get("/oauth-usage")
async def oauth_usage():
    """Real subscription quota (session 5h + weekly), as shown by `/status`.
    Sourced from /api/oauth/usage via the interactive token, which only the host
    can read (macOS Keychain) — the Electron app writes it to data/ for us."""
    import json
    from datetime import datetime, timezone
    from ..config import DATA_DIR
    f = (DATA_DIR / "oauth_usage.json") if hasattr(DATA_DIR, "__truediv__") else None
    try:
        blob = json.loads(f.read_text())
        fetched = datetime.fromisoformat(blob["fetched_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        return {"available": True, "stale": age > 600, "fetched_at": blob["fetched_at"], "usage": blob["usage"]}
    except Exception:
        return {"available": False, "stale": True, "fetched_at": None, "usage": None}
