"""
Asana Task Workflow Dashboard - FastAPI Backend
Fetches tasks, auto-classifies, allows manual overrides, syncs back to Asana.
"""

import json
import os
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from classifier import classify_task
from ai_classifier import ai_classify_task, ai_classify_batch, clear_cache

load_dotenv()

# --- Config ---
ASANA_PAT = os.getenv("ASANA_PAT", "")
PROJECT_GID = os.getenv("ASANA_PROJECT_GID", "1120029023219792")
SECTION_GID = os.getenv("ASANA_SECTION_GID", "1204812858137872")
STORY_POINT_FIELD_GID = os.getenv("ASANA_STORY_POINT_FIELD_GID", "1204816034572110")

ASANA_BASE = "https://app.asana.com/api/1.0"
DATA_FILE = Path(__file__).parent / "data" / "classifications.json"

TASK_OPT_FIELDS = ",".join([
    "name", "notes", "assignee.name", "due_on", "completed",
    "tags.name", "custom_fields.name", "custom_fields.display_value",
    "permalink_url", "memberships.section.name",
])

app = FastAPI(title="Asana Workflow Dashboard")


# --- Persistence ---
def _load_local_data() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return {"overrides": {}, "last_sync": None}


def _save_local_data(data: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# --- Asana API helpers ---
def _headers():
    if not ASANA_PAT:
        raise HTTPException(401, "ASANA_PAT not configured. Add it to .env file.")
    return {"Authorization": f"Bearer {ASANA_PAT}"}


async def _fetch_tasks() -> list[dict]:
    """Fetch all tasks from the configured section."""
    headers = _headers()  # Check PAT before creating client
    url = f"{ASANA_BASE}/tasks"
    params = {"section": SECTION_GID, "opt_fields": TASK_OPT_FIELDS, "limit": 100}
    tasks = []
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, f"Asana API error: {resp.text}")
            body = resp.json()
            tasks.extend(body.get("data", []))
            next_page = body.get("next_page")
            if next_page:
                url = next_page["uri"]
                params = {}
            else:
                break
    return tasks


async def _update_asana_task(task_gid: str, custom_fields: dict):
    """Update custom fields on an Asana task."""
    headers = _headers()  # Check PAT before creating client
    url = f"{ASANA_BASE}/tasks/{task_gid}"
    payload = {"data": {"custom_fields": custom_fields}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Asana update error: {resp.text}")
        return resp.json()


# --- API Routes ---

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/api/tasks")
async def get_tasks():
    """Fetch tasks from Asana, classify them, apply local overrides."""
    raw_tasks = await _fetch_tasks()
    local_data = _load_local_data()
    overrides = local_data.get("overrides", {})

    classified = []
    for task in raw_tasks:
        if task.get("completed"):
            continue
        result = classify_task(task)
        # Apply local overrides
        gid = task["gid"]
        if gid in overrides:
            ov = overrides[gid]
            if "scope_score" in ov:
                result["scope_score"] = ov["scope_score"]
            if "cluster_id" in ov:
                result["cluster"]["id"] = ov["cluster_id"]
                result["cluster"]["name"] = ov.get("cluster_name", ov["cluster_id"])
                # Preserve cluster color from known clusters
                for kc in [
                    ("ebitda", "#e74c3c"), ("trazabilidad", "#9b59b6"),
                    ("turnos", "#3498db"), ("pedidos", "#f39c12"),
                    ("almacen", "#1abc9c"), ("sentry", "#95a5a6"),
                    ("integracion", "#e67e22"), ("standalone", "#7f8c8d"),
                ]:
                    if ov["cluster_id"] == kc[0]:
                        result["cluster"]["color"] = kc[1]
                        break
            if "priority" in ov:
                result["priority"] = ov["priority"]
            if "ai_reasoning" in ov:
                result["ai_reasoning"] = ov["ai_reasoning"]
            if "source" in ov:
                result["classification_source"] = ov["source"]
        classified.append(result)

    # Sort by priority desc, then scope asc
    classified.sort(key=lambda t: (-t["priority"], t["scope_score"]))
    return {"tasks": classified, "count": len(classified)}


class UpdateClassification(BaseModel):
    scope_score: Optional[int] = None
    cluster_id: Optional[str] = None
    cluster_name: Optional[str] = None
    priority: Optional[int] = None


@app.put("/api/tasks/{task_gid}/classify")
async def update_classification(task_gid: str, body: UpdateClassification):
    """Manually override classification for a task."""
    local_data = _load_local_data()
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
    _save_local_data(local_data)
    return {"status": "ok", "overrides": current}


@app.post("/api/sync")
async def sync_to_asana():
    """Push scope scores to Asana Story Point field."""
    raw_tasks = await _fetch_tasks()
    local_data = _load_local_data()
    overrides = local_data.get("overrides", {})

    synced = []
    errors = []
    for task in raw_tasks:
        if task.get("completed"):
            continue
        gid = task["gid"]
        result = classify_task(task)
        # Use override if exists
        score = overrides.get(gid, {}).get("scope_score", result["scope_score"])
        try:
            await _update_asana_task(gid, {STORY_POINT_FIELD_GID: str(score)})
            synced.append({"gid": gid, "name": task["name"], "score": score})
        except Exception as e:
            errors.append({"gid": gid, "name": task["name"], "error": str(e)})

    return {"synced": len(synced), "errors": len(errors), "details": synced, "error_details": errors}


@app.get("/api/clusters")
async def get_clusters():
    """Get cluster summary stats."""
    raw_tasks = await _fetch_tasks()
    local_data = _load_local_data()
    overrides = local_data.get("overrides", {})

    clusters = {}
    for task in raw_tasks:
        if task.get("completed"):
            continue
        result = classify_task(task)
        gid = task["gid"]
        if gid in overrides and "cluster_id" in overrides[gid]:
            cid = overrides[gid]["cluster_id"]
        else:
            cid = result["cluster"]["id"]

        if cid not in clusters:
            clusters[cid] = {
                "id": cid,
                "name": result["cluster"]["name"],
                "color": result["cluster"]["color"],
                "count": 0,
                "avg_scope": 0,
                "total_scope": 0,
            }
        clusters[cid]["count"] += 1
        score = overrides.get(gid, {}).get("scope_score", result["scope_score"])
        clusters[cid]["total_scope"] += score

    for c in clusters.values():
        c["avg_scope"] = round(c["total_scope"] / c["count"], 1) if c["count"] > 0 else 0

    return {"clusters": list(clusters.values())}


# --- AI Classification Routes ---

@app.post("/api/ai/classify-all")
async def ai_classify_all(force: bool = False):
    """Classify all pending tasks using Claude AI. Saves results as overrides."""
    raw_tasks = await _fetch_tasks()
    active = [t for t in raw_tasks if not t.get("completed")]

    results = await ai_classify_batch(active, force=force)

    # Save AI results as overrides
    local_data = _load_local_data()
    overrides = local_data.setdefault("overrides", {})
    applied = 0
    for gid, classification in results.items():
        overrides[gid] = {
            "scope_score": classification["scope_score"],
            "priority": classification["priority"],
            "cluster_id": classification["cluster_id"],
            "cluster_name": classification.get("cluster_name", ""),
            "ai_reasoning": classification.get("reasoning", ""),
            "source": "ai",
        }
        applied += 1

    local_data["overrides"] = overrides
    _save_local_data(local_data)

    return {
        "classified": applied,
        "total": len(active),
        "cached": len(active) - len([t for t in active if t["gid"] in results and results[t["gid"]].get("reasoning")]),
    }


@app.post("/api/ai/classify/{task_gid}")
async def ai_classify_single(task_gid: str, force: bool = False):
    """Classify a single task using Claude AI."""
    raw_tasks = await _fetch_tasks()
    task = next((t for t in raw_tasks if t["gid"] == task_gid), None)
    if not task:
        raise HTTPException(404, f"Task {task_gid} not found")

    result = await ai_classify_task(task, force=force)
    if not result:
        raise HTTPException(502, "AI classification failed. Check ANTHROPIC_API_KEY in .env")

    # Save as override
    local_data = _load_local_data()
    overrides = local_data.setdefault("overrides", {})
    overrides[task_gid] = {
        "scope_score": result["scope_score"],
        "priority": result["priority"],
        "cluster_id": result["cluster_id"],
        "cluster_name": result.get("cluster_name", ""),
        "ai_reasoning": result.get("reasoning", ""),
        "source": "ai",
    }
    local_data["overrides"] = overrides
    _save_local_data(local_data)

    return {"status": "ok", "classification": result}


@app.delete("/api/ai/cache")
async def clear_ai_cache():
    """Clear AI classification cache to force re-evaluation."""
    clear_cache()
    return {"status": "ok", "message": "AI cache cleared"}


@app.get("/api/ai/status")
async def ai_status():
    """Check if AI classification is available."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    return {
        "available": bool(api_key),
        "model": os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8765, reload=True)
