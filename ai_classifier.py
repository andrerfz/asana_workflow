"""
AI-powered classifier using Claude API.
Sends task data to Claude and gets back structured classification.
Caches results locally to avoid redundant API calls.
"""

import json
import hashlib
import logging
from typing import Optional

import httpx

from config import ANTHROPIC_API_KEY, ANTHROPIC_BASE, CLAUDE_MODEL

log = logging.getLogger(__name__)
from storage import load_ai_cache, save_ai_cache, clear_ai_cache as _clear_cache_file

KNOWN_CLUSTERS = [
    {"id": "ebitda", "name": "EBITDA Reports", "color": "#e74c3c",
     "description": "Financial EBITDA reports, purchase/income discrepancies, cuenta de explotacion"},
    {"id": "trazabilidad", "name": "Trazabilidad", "color": "#9b59b6",
     "description": "Traceability reports, product tracking, lot tracking, traceability filters"},
    {"id": "turnos", "name": "Planificacion Turnos", "color": "#3498db",
     "description": "Shift planning, employee scheduling, shift visibility in app"},
    {"id": "pedidos", "name": "Pedidos / Albaranes", "color": "#f39c12",
     "description": "Orders, delivery notes, order formats, quantities, order finalization"},
    {"id": "almacen", "name": "Almacen", "color": "#1abc9c",
     "description": "Warehouse, storage locations, product location management"},
    {"id": "sentry", "name": "Sentry / Monitoring", "color": "#95a5a6",
     "description": "Sentry errors, monitoring, automated error detection"},
    {"id": "integracion", "name": "Integraciones", "color": "#e67e22",
     "description": "Third-party integrations, external system connections"},
    {"id": "standalone", "name": "Standalone", "color": "#7f8c8d",
     "description": "Tasks that don't fit any cluster above"},
]

SYSTEM_PROMPT = """You are a task classification engine for a SaaS product (restaurant/hospitality management platform called Yurest).

You classify development tasks (bugs, features, improvements) into clusters, scope scores, and priority.

CLUSTERS (pick the best match):
{clusters}

SCOPE SCORE (1-5):
1 = Tiny: single query fix, filter bug, one-line change
2 = Small: single file logic fix, simple UI tweak, straightforward bug
3 = Medium: multi-file change, API + frontend coordination, moderate complexity
4 = Large: new endpoint with logic + tests, significant refactor
5 = XL: cross-system feature, database migration, new module

PRIORITY (1-10, 10=most urgent):
Consider: error vs feature, client-reported vs internal, financial impact, number of affected clients, operational impact, quick-win potential (low scope + high impact = higher priority).

AREA (pick one):
backend_clientes, backend_proveedor, backend_api, mobile_app, monitoring, other

CRITICAL RULES:
- Data integrity errors in financial reports (EBITDA) or traceability reports = ALWAYS P10. Incorrect data in reports is the highest priority.
- Errors showing wrong amounts, missing data, or mismatched values in any report = P10.
- Client-reported errors in operational features (orders, shifts) = P8-9.
- Quick wins (scope 1-2 + high impact) should get priority boost.
- Tasks with a due date get priority boost: overdue = +3, due in ≤2 days = +2, due this week = +1.

Respond ONLY with valid JSON, no markdown, no explanation:
{{"cluster_id": "...", "cluster_name": "...", "cluster_color": "...", "scope_score": N, "priority": N, "area": "...", "reasoning": "one sentence why", "summary": "2-3 sentence actionable summary in Spanish: what is broken, probable root cause, what to fix"}}"""


def _build_system_prompt() -> str:
    clusters_text = "\n".join(
        f"- {c['id']}: {c['name']} — {c['description']}"
        for c in KNOWN_CLUSTERS
    )
    return SYSTEM_PROMPT.format(clusters=clusters_text)


def _task_hash(task: dict) -> str:
    """Hash task name+notes for cache key."""
    content = f"{task.get('name', '')}|{task.get('notes', '')}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _build_task_prompt(task: dict) -> str:
    name = task.get("name") or ""
    notes = task.get("notes") or ""
    tipo = "Unknown"
    canal = "Unknown"
    for cf in task.get("custom_fields", []):
        if cf.get("name") == "Tipo" and cf.get("display_value"):
            tipo = cf["display_value"]
        if cf.get("name") == "Canal" and cf.get("display_value"):
            canal = cf["display_value"]

    tags = ", ".join(t.get("name", "") for t in task.get("tags", []))

    due_on = task.get("due_on") or "none"

    return f"""Classify this task:

Name: {name}
Type: {tipo}
Channel: {canal}
Due date: {due_on}
Tags: {tags or "none"}
Description: {notes[:1000] if notes else "none"}"""


async def ai_classify_task(task: dict, force: bool = False) -> Optional[dict]:
    """
    Classify a single task using Claude API.
    Returns classification dict or None on error.
    Uses cache unless force=True.
    """
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set — skipping AI classification")
        return None

    # Check cache
    task_hash = _task_hash(task)
    if not force:
        cache = load_ai_cache()
        if task_hash in cache:
            return cache[task_hash]

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 512,
        "system": _build_system_prompt(),
        "messages": [{"role": "user", "content": _build_task_prompt(task)}],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(ANTHROPIC_BASE, headers=headers, json=payload)
            if resp.status_code != 200:
                log.error("Claude API %s: %s", resp.status_code, resp.text[:500])
                return None

            body = resp.json()
            text = body["content"][0]["text"].strip()

            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            result = json.loads(text)

            # Validate
            result["scope_score"] = max(1, min(5, int(result.get("scope_score", 2))))
            result["priority"] = max(1, min(10, int(result.get("priority", 5))))

            # Ensure cluster fields
            if "cluster_id" not in result:
                result["cluster_id"] = "standalone"
            if "cluster_name" not in result:
                for c in KNOWN_CLUSTERS:
                    if c["id"] == result["cluster_id"]:
                        result["cluster_name"] = c["name"]
                        result["cluster_color"] = c["color"]
                        break
            if "cluster_color" not in result:
                result["cluster_color"] = "#7f8c8d"

            # Cache result
            cache = load_ai_cache()
            cache[task_hash] = result
            save_ai_cache(cache)

            return result

    except Exception as exc:
        log.exception("AI classify failed for task '%s': %s", task.get("name", "?"), exc)
        return None


async def ai_classify_batch(tasks: list[dict], force: bool = False) -> dict:
    """
    Classify multiple tasks. Returns {task_gid: classification}.
    Skips already-cached tasks unless force=True.
    Retries failed tasks once.
    """
    import asyncio
    results = {}
    cache = load_ai_cache()
    to_classify = []

    for task in tasks:
        task_hash = _task_hash(task)
        if not force and task_hash in cache:
            results[task["gid"]] = cache[task_hash]
        else:
            to_classify.append(task)

    log.info("AI batch: %d to classify, %d from cache", len(to_classify), len(results))

    failed = []
    for i, task in enumerate(to_classify):
        log.info("AI classifying %d/%d: %s", i + 1, len(to_classify), task.get("name", "?")[:60])
        result = await ai_classify_task(task, force=True)
        if result:
            results[task["gid"]] = result
        else:
            failed.append(task)
        if i < len(to_classify) - 1:
            await asyncio.sleep(0.5)

    # Retry failed tasks once
    if failed:
        log.info("Retrying %d failed tasks...", len(failed))
        await asyncio.sleep(2)
        for task in failed:
            result = await ai_classify_task(task, force=True)
            if result:
                results[task["gid"]] = result
                log.info("Retry OK: %s", task.get("name", "?")[:60])
            else:
                log.warning("Retry failed: %s", task.get("name", "?")[:60])

    log.info("AI batch done: %d/%d classified", len(results), len(tasks))
    return results


def clear_cache():
    """Clear the AI classification cache."""
    _clear_cache_file()
