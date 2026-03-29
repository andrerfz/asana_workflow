"""Asana REST API wrapper — all HTTP calls live here."""
import logging
import httpx
from fastapi import HTTPException

from ..config import ASANA_PAT, ASANA_BASE, PROJECT_GID, SECTION_GID, TASK_OPT_FIELDS, STORY_POINT_FIELD_GID

log = logging.getLogger(__name__)


def _headers() -> dict:
    """Get authorization headers for Asana API requests."""
    if not ASANA_PAT:
        raise HTTPException(401, "ASANA_PAT not configured. Add it to .env file.")
    return {"Authorization": f"Bearer {ASANA_PAT}"}


async def _paginated_get(url: str, params: dict, headers: dict, retries: int = 2) -> list[dict]:
    """Generic paginated GET helper with retry on transient connection errors."""
    import asyncio
    results = []
    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            last_exc = None
            for attempt in range(1 + retries):
                try:
                    resp = await client.get(url, headers=headers, params=params)
                    last_exc = None
                    break
                except httpx.ConnectError as e:
                    last_exc = e
                    if attempt < retries:
                        log.warning("Asana connection error (attempt %d/%d): %s", attempt + 1, retries + 1, e)
                        await asyncio.sleep(1 * (attempt + 1))
            if last_exc:
                raise last_exc
            if resp.status_code != 200:
                raise HTTPException(resp.status_code, f"Asana API error: {resp.text}")
            body = resp.json()
            results.extend(body.get("data", []))
            next_page = body.get("next_page")
            if next_page and next_page.get("offset"):
                params["offset"] = next_page["offset"]
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


async def fetch_task_stories(task_gid: str) -> list[dict]:
    """Fetch comments/stories for a task. Returns text comments (not system events)."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks/{task_gid}/stories"
    params = {"opt_fields": "text,type,resource_subtype,created_by.name,created_at", "limit": 100}
    stories = await _paginated_get(url, params, headers)
    log.info("Task %s: %d total stories from API", task_gid, len(stories))
    # Filter to human comments only (skip system-generated events)
    comments = [
        s for s in stories
        if s.get("resource_subtype") == "comment_added" and s.get("text")
    ]
    if len(stories) > 0 and len(comments) == 0:
        # Log subtypes to debug filtering
        subtypes = set(s.get("resource_subtype", "?") for s in stories)
        log.warning("Task %s: all %d stories filtered out. Subtypes found: %s", task_gid, len(stories), subtypes)
    return comments


async def fetch_subtasks(task_gid: str) -> list[dict]:
    """Fetch subtask names for a task."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks/{task_gid}/subtasks"
    params = {"opt_fields": "name,completed,notes,assignee.name", "limit": 100}
    return await _paginated_get(url, params, headers)


async def add_task_comment(task_gid: str, text: str) -> dict:
    """Post a comment on an Asana task."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks/{task_gid}/stories"
    payload = {"data": {"text": text}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            log.error("Failed to post comment on %s: %s", task_gid, resp.text[:300])
            return {}
        return resp.json().get("data", {})


async def delete_story(story_gid: str) -> bool:
    """Delete a story/comment from Asana."""
    headers = _headers()
    url = f"{ASANA_BASE}/stories/{story_gid}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.delete(url, headers=headers)
        if resp.status_code not in (200, 204):
            log.error("Failed to delete story %s: %s", story_gid, resp.text[:300])
            return False
        return True


async def complete_subtask(subtask_gid: str) -> bool:
    """Mark a subtask as completed in Asana."""
    headers = _headers()
    url = f"{ASANA_BASE}/tasks/{subtask_gid}"
    payload = {"data": {"completed": True}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.put(url, headers=headers, json=payload)
        if resp.status_code != 200:
            log.error("Failed to complete subtask %s: %s", subtask_gid, resp.text[:300])
            return False
        return True


async def move_task_to_section(task_gid: str, section_gid: str) -> bool:
    """Move a task to a different section in the project."""
    headers = _headers()
    url = f"{ASANA_BASE}/sections/{section_gid}/addTask"
    payload = {"data": {"task": task_gid}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            log.error("Failed to move task %s to section %s: %s", task_gid, section_gid, resp.text[:300])
            return False
        return True


async def create_section(name: str) -> str | None:
    """Create a new section in the project. Returns the new section GID."""
    headers = _headers()
    url = f"{ASANA_BASE}/projects/{PROJECT_GID}/sections"
    payload = {"data": {"name": name}}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code not in (200, 201):
            log.error("Failed to create section '%s': %s", name, resp.text[:300])
            return None
        return resp.json().get("data", {}).get("gid")


async def find_section_by_name(name: str, create_if_missing: bool = False) -> str | None:
    """Find a section GID by name (case-insensitive). Optionally create if missing."""
    sections = await fetch_sections()
    name_lower = name.lower().strip()
    for s in sections:
        if s["name"].lower().strip() == name_lower:
            return s["gid"]
    if create_if_missing:
        log.info("Section '%s' not found — creating it", name)
        return await create_section(name)
    return None
