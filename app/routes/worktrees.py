"""Worktree management API routes."""
import re
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator
from typing import Optional

from ..services.worktree_manager import (
    create_worktree, delete_worktree, get_worktree_status,
    list_worktrees, cleanup_stale_worktrees,
)

router = APIRouter(prefix="/api/worktrees", tags=["worktrees"])


class CreateWorktree(BaseModel):
    repo_id: str
    branch_slug: str

    @field_validator("branch_slug")
    @classmethod
    def validate_branch_slug(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9._/-]{1,80}$', v) or '..' in v:
            raise ValueError("branch_slug must be 1-80 alphanumeric/._/- chars, no '..'")
        return v


@router.get("")
async def get_all_worktrees(task_gid: Optional[str] = None):
    """List all active worktrees, optionally filtered by task."""
    wts = list_worktrees(task_gid)
    return {"worktrees": wts, "count": len(wts)}


# Static routes BEFORE dynamic {task_gid} routes to prevent shadowing
@router.post("/cleanup")
async def cleanup_worktrees(max_age_days: int = Query(default=7, ge=1)):
    """Remove stale worktrees older than max_age_days."""
    removed = cleanup_stale_worktrees(max_age_days)
    return {"removed": removed, "count": len(removed)}


@router.post("/{task_gid}")
async def create_task_worktree(task_gid: str, body: CreateWorktree):
    """Create a worktree for a task in a specific repo."""
    try:
        result = create_worktree(task_gid, body.repo_id, body.branch_slug)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return result


@router.get("/{task_gid}")
async def get_task_worktrees(task_gid: str):
    """Get all worktrees for a specific task."""
    wts = list_worktrees(task_gid)
    return {"worktrees": wts, "count": len(wts)}


@router.get("/{task_gid}/{repo_id}")
async def get_worktree_detail(task_gid: str, repo_id: str):
    """Get detailed status of a specific worktree."""
    status = get_worktree_status(task_gid, repo_id)
    if not status:
        raise HTTPException(404, "Worktree not found")
    return status


@router.delete("/{task_gid}/{repo_id}")
async def remove_worktree(task_gid: str, repo_id: str):
    """Delete a worktree and its branch."""
    if not delete_worktree(task_gid, repo_id):
        raise HTTPException(404, "Worktree not found")
    return {"status": "ok", "removed": f"{task_gid}/{repo_id}"}
