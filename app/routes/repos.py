"""Repo registry API routes."""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import PROJECTS_DIR
from ..services.repo_manager import (
    list_repos, get_repo, add_repo, remove_repo,
    check_repo_health, detect_language, load_repos,
    update_area_mapping, scan_projects_dir,
)

router = APIRouter(prefix="/api/repos", tags=["repos"])


class RepoConfig(BaseModel):
    path: str
    default_branch: str = "master"
    test_cmd: Optional[str] = None
    test_docker_cmd: Optional[str] = None
    build_cmd: Optional[str] = None
    lint_cmd: Optional[str] = None
    language: str = "auto"
    context_files: list[str] = []


class AreaMapping(BaseModel):
    repo_ids: list[str]


@router.get("")
async def get_repos():
    """List all configured repos with health status."""
    repos = list_repos()
    return {"repos": repos, "count": len(repos)}


# Static routes BEFORE dynamic {repo_id} routes
@router.get("/config")
async def get_projects_config():
    """Get PROJECTS_DIR config for the frontend."""
    return {
        "projects_dir": PROJECTS_DIR,
        "configured": bool(PROJECTS_DIR),
    }


@router.get("/scan")
async def scan_repos():
    """Scan PROJECTS_DIR for git repositories."""
    if not PROJECTS_DIR:
        raise HTTPException(400, "PROJECTS_DIR not configured in .env")
    repos = scan_projects_dir()
    return {"projects_dir": PROJECTS_DIR, "repos": repos, "count": len(repos)}


@router.get("/list")
async def list_repo_ids():
    """List all configured repo IDs (for dropdowns)."""
    repos = list_repos()
    return {"repos": [{"id": r["id"], "path": r.get("path", ""), "language": r.get("language", "unknown")} for r in repos]}


@router.get("/mapping/areas")
async def get_area_mapping():
    """Get area-to-repo auto-mapping config."""
    data = load_repos()
    return {"area_repo_map": data.get("area_repo_map", {})}


@router.put("/mapping/areas/{area}")
async def set_area_mapping(area: str, body: AreaMapping):
    """Update area-to-repo mapping for a specific area."""
    update_area_mapping(area, body.repo_ids)
    return {"status": "ok", "area": area, "repo_ids": body.repo_ids}


# Dynamic routes
@router.get("/{repo_id}")
async def get_repo_detail(repo_id: str):
    """Get a single repo config with health check."""
    repo = get_repo(repo_id)
    if not repo:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    repo["health"] = check_repo_health(repo["path"])
    return repo


@router.post("/{repo_id}")
async def create_repo(repo_id: str, body: RepoConfig):
    """Add or update a repo in the registry."""
    config = body.model_dump()

    # Auto-detect language if set to "auto"
    if config["language"] == "auto":
        config["language"] = detect_language(config["path"])

    try:
        repo = add_repo(repo_id, config)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return repo


@router.delete("/{repo_id}")
async def delete_repo(repo_id: str):
    """Remove a repo from the registry."""
    if not remove_repo(repo_id):
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    return {"status": "ok", "removed": repo_id}


@router.get("/{repo_id}/health")
async def repo_health(repo_id: str):
    """Check repo health (exists, is git, clean/dirty)."""
    repo = get_repo(repo_id)
    if not repo:
        raise HTTPException(404, f"Repo '{repo_id}' not found")
    return check_repo_health(repo["path"])
