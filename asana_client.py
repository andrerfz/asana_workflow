"""Asana REST API wrapper — all HTTP calls live here."""
import logging
import httpx
from fastapi import HTTPException

from config import ASANA_PAT, ASANA_BASE, PROJECT_GID, SECTION_GID, TASK_OPT_FIELDS, STORY_POINT_FIELD_GID

log = logging.getLogger(__name__)


def _headers() -> dict:
    """Get authorization headers for Asana API requests."""
    if not ASANA_PAT:
        raise HTTPException(401, "ASANA_PAT not configured. Add it to .env file.")
    return {"Authorization": f"Bearer {ASANA_PAT}"}


async def _paginated_get(url: str, params: dict, headers: dict) -> list[dict]:
    """Generic paginated GET helper."""
    results = []
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, f"Asana API error: {resp.text}")
            body = resp.json()
            results.extend(body.get("data", []))
            next_page = body.get("next_page")
            if next_page:
                url = next_page["uri"]
                params = {}  # params baked into next_page URI
            else:
                break
    return results


async def fetch_sections() -> list[dict]:
    """Fetch all sections in the project, preserving Asana order."""
    headers = _headers()
    url = f"{ASANA_BASE}/projects/{PROJECT_GID}/sections"
    raw = await _paginated_get(url, {"opt_fields": "name", "limit": 100}, headers)
    sections = []
    for s in raw:
        name = s.get("name", "").strip()
        if name:
            sections.append({"gid": s["gid"], "name": name})
    return sections


async def fetch_tasks_for_section(section_gid: str) -> list[dict]:
    """Fetch all tasks from a single section."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks"
    params = {"section": section_gid, "opt_fields": TASK_OPT_FIELDS, "limit": 100}
    return await _paginated_get(url, params, headers)


async def fetch_tasks(section_gid: str = None) -> list[dict]:
    """Fetch tasks from one section (if given) or ALL sections in the project."""
    if section_gid:
        return await fetch_tasks_for_section(section_gid)

    # Fetch all sections, then fetch tasks per section
    sections = await fetch_sections()
    if not sections:
        log.warning("No sections found, falling back to SECTION_GID")
        return await fetch_tasks_for_section(SECTION_GID)

    all_tasks = []
    seen_gids = set()
    for s in sections:
        tasks = await fetch_tasks_for_section(s["gid"])
        for t in tasks:
            if t["gid"] not in seen_gids:  # deduplicate
                seen_gids.add(t["gid"])
                t["_section_name"] = s["name"]  # tag with source section
                all_tasks.append(t)
        log.info("Fetched %d tasks from section '%s'", len(tasks), s["name"])
    log.info("Total tasks across all sections: %d", len(all_tasks))
    return all_tasks


async def fetch_completed_tasks(since: str = "2025-01-01") -> list[dict]:
    """Fetch completed tasks from Asana section."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks"
    params = {
        "section": SECTION_GID,
        "opt_fields": TASK_OPT_FIELDS + ",completed_at",
        "completed_since": since,
        "limit": 100,
    }
    tasks = await _paginated_get(url, params, headers)
    return [t for t in tasks if t.get("completed")]


async def fetch_project_tasks(since: str = "2025-01-01") -> list[dict]:
    """Fetch all tasks in the project (all sections) modified since date."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks"
    params = {
        "project": PROJECT_GID,
        "opt_fields": TASK_OPT_FIELDS + ",completed_at,modified_at",
        "completed_since": since,
        "modified_since": since,
        "limit": 100,
    }
    return await _paginated_get(url, params, headers)


async def update_task(task_gid: str, custom_fields: dict):
    """Update custom fields on an Asana task."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks/{task_gid}"
    payload = {"data": {"custom_fields": custom_fields}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Asana update error: {resp.text}")
        return resp.json()
