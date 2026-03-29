"""CLAUDE.md guide editor API routes."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import PROJECTS_DIR
from ..services.repo_manager import list_repos

router = APIRouter(prefix="/api/guides", tags=["guides"])


class GuideUpdate(BaseModel):
    content: str


@router.get("")
async def get_guides():
    """List all CLAUDE.md guides (global + per-repo) with their content."""
    guides = []

    # Global guide
    global_path = Path(PROJECTS_DIR) / "CLAUDE.md" if PROJECTS_DIR else None
    guides.append({
        "id": "global",
        "type": "global",
        "label": "Global Project Guide",
        "path": str(global_path) if global_path else None,
        "content": _read_guide(global_path),
    })

    # Per-repo guides
    for repo in list_repos():
        repo_path = repo.get("path", "")
        if not repo_path:
            continue
        md_path = Path(repo_path) / "CLAUDE.md"
        guides.append({
            "id": repo["id"],
            "type": "repo",
            "label": repo["id"],
            "path": str(md_path),
            "content": _read_guide(md_path),
        })

    return guides


@router.put("/{guide_id}")
async def update_guide(guide_id: str, body: GuideUpdate):
    """Save content to a CLAUDE.md file."""
    if guide_id == "global":
        if not PROJECTS_DIR:
            raise HTTPException(400, "PROJECTS_DIR not configured")
        path = Path(PROJECTS_DIR) / "CLAUDE.md"
    else:
        repos = list_repos()
        repo = next((r for r in repos if r["id"] == guide_id), None)
        if not repo:
            raise HTTPException(404, f"Repo '{guide_id}' not found")
        path = Path(repo["path"]) / "CLAUDE.md"

    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok", "path": str(path)}


def _read_guide(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None
