"""Repository registry — manages repo configs for agent workers."""
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR, PROJECTS_DIR

log = logging.getLogger(__name__)

REPOS_FILE = DATA_DIR / "repos.json"
TASK_REPO_OVERRIDES_FILE = DATA_DIR / "task_repo_overrides.json"

# Area → repo auto-mapping (from classifier area detection)
AREA_REPO_MAP: dict[str, list[str]] = {
    "backend_clientes": ["back-clientes"],
    "backend_proveedor": ["back-proveedores"],
    "backend_api": ["back-clientes", "back-proveedores"],
    "mobile_app": ["app-mobile"],
    "monitoring": ["back-clientes"],
}


def _default_data() -> dict:
    return {"repos": {}, "area_repo_map": AREA_REPO_MAP}


def load_repos() -> dict:
    """Load repo registry from disk."""
    if REPOS_FILE.exists():
        try:
            data = json.loads(REPOS_FILE.read_text())
            # Ensure area_repo_map exists
            if "area_repo_map" not in data:
                data["area_repo_map"] = AREA_REPO_MAP
            return data
        except (json.JSONDecodeError, OSError):
            return _default_data()
    return _default_data()


def save_repos(data: dict):
    """Save repo registry to disk."""
    REPOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPOS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_repo(repo_id: str) -> Optional[dict]:
    """Get a single repo config by ID."""
    data = load_repos()
    repo = data["repos"].get(repo_id)
    if repo:
        repo["id"] = repo_id
    return repo


def list_repos() -> list[dict]:
    """List all configured repos with health status."""
    data = load_repos()
    result = []
    for repo_id, repo in data["repos"].items():
        entry = {**repo, "id": repo_id}
        entry["health"] = check_repo_health(repo["path"])
        result.append(entry)
    return result


def scan_projects_dir() -> list[dict]:
    """Scan PROJECTS_DIR for git repositories."""
    if not PROJECTS_DIR:
        return []
    root = Path(PROJECTS_DIR)
    if not root.exists():
        return []
    repos = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / ".git").exists():
            repos.append({
                "name": d.name,
                "path": str(d),
                "language": detect_language(str(d)),
            })
    return repos


def validate_repo_path(path: str) -> str:
    """Ensure repo path is under PROJECTS_DIR. Returns resolved path."""
    if not PROJECTS_DIR:
        raise ValueError("PROJECTS_DIR not configured in .env")
    resolved = str(Path(path).resolve())
    projects_resolved = str(Path(PROJECTS_DIR).resolve())
    # Append os.sep to prevent sibling directory bypass (e.g. /projects-evil matching /projects)
    if not (resolved + os.sep).startswith(projects_resolved + os.sep):
        raise ValueError(f"Repo path must be under PROJECTS_DIR ({PROJECTS_DIR})")
    return resolved


def add_repo(repo_id: str, config: dict) -> dict:
    """Add or update a repo in the registry."""
    data = load_repos()

    # Validate required fields
    if not config.get("path"):
        raise ValueError("path is required")

    # Validate path is under PROJECTS_DIR
    if PROJECTS_DIR:
        validate_repo_path(config["path"])

    # Build repo entry with defaults
    entry = {
        "path": config["path"],
        "default_branch": config.get("default_branch", "master"),
        "test_cmd": config.get("test_cmd"),
        "test_docker_cmd": config.get("test_docker_cmd"),
        "test_worktree_cmd": config.get("test_worktree_cmd"),
        "test_worktree_cmd_fast": config.get("test_worktree_cmd_fast"),
        "test_description": config.get("test_description"),
        "build_cmd": config.get("build_cmd"),
        "lint_cmd": config.get("lint_cmd"),
        "language": config.get("language", "auto"),
        "context_files": config.get("context_files", []),
    }

    data["repos"][repo_id] = entry
    save_repos(data)
    return {**entry, "id": repo_id, "health": check_repo_health(entry["path"])}


def remove_repo(repo_id: str) -> bool:
    """Remove a repo from the registry."""
    data = load_repos()
    if repo_id in data["repos"]:
        del data["repos"][repo_id]
        save_repos(data)
        return True
    return False


def check_repo_health(path: str) -> dict:
    """Check if a repo path exists, is a git repo, and has a clean state."""
    result = {"status": "unknown", "details": ""}
    p = Path(path)

    if not p.exists():
        result["status"] = "missing"
        result["details"] = "Directory does not exist"
        return result

    if not (p / ".git").exists():
        result["status"] = "not_git"
        result["details"] = "Not a git repository"
        return result

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path, capture_output=True, text=True, timeout=10,
        )
        if status.returncode != 0:
            result["status"] = "error"
            result["details"] = status.stderr.strip()
            return result

        uncommitted = len(status.stdout.strip().splitlines()) if status.stdout.strip() else 0

        # Get current branch
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path, capture_output=True, text=True, timeout=5,
        )
        current_branch = branch.stdout.strip() if branch.returncode == 0 else "unknown"

        if uncommitted > 0:
            result["status"] = "dirty"
            result["details"] = f"{uncommitted} uncommitted changes on {current_branch}"
        else:
            result["status"] = "clean"
            result["details"] = f"Clean on {current_branch}"

    except subprocess.TimeoutExpired:
        result["status"] = "error"
        result["details"] = "Git command timed out"
    except FileNotFoundError:
        result["status"] = "error"
        result["details"] = "Git not found"

    return result


def get_repos_for_area(area: str) -> list[dict]:
    """Get repo configs mapped to a classifier area."""
    data = load_repos()
    mapping = data.get("area_repo_map", AREA_REPO_MAP)
    repo_ids = mapping.get(area, [])

    result = []
    for rid in repo_ids:
        repo = data["repos"].get(rid)
        if repo:
            result.append({**repo, "id": rid})
    return result


def load_task_repo_overrides() -> dict:
    """Load task-to-repos overrides from disk."""
    if TASK_REPO_OVERRIDES_FILE.exists():
        try:
            return json.loads(TASK_REPO_OVERRIDES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_task_repo_overrides(data: dict):
    """Save task-to-repos overrides to disk."""
    TASK_REPO_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_REPO_OVERRIDES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def get_task_repo_override(task_gid: str) -> list[str]:
    """Get repo override for a task from the override file."""
    overrides = load_task_repo_overrides()
    return overrides.get(task_gid, [])


def set_task_repo_override(task_gid: str, repo_ids: list[str]) -> dict:
    """Set repo override for a task."""
    overrides = load_task_repo_overrides()
    if repo_ids:
        overrides[task_gid] = repo_ids
    else:
        overrides.pop(task_gid, None)
    save_task_repo_overrides(overrides)
    return overrides


def get_repos_for_task(task: dict) -> list[dict]:
    """Resolve repos for a classified task (area auto-map + manual override)."""
    task_gid = task.get("task_gid", "")

    # Check for manual override first (from task field)
    overrides = task.get("repo_override", [])
    if not overrides and task_gid:
        # Check override file
        overrides = get_task_repo_override(task_gid)

    if overrides:
        data = load_repos()
        result = []
        for rid in overrides:
            repo = data["repos"].get(rid)
            if repo:
                result.append({**repo, "id": rid})
        return result

    # Fallback to area auto-mapping
    area = task.get("area", "other")
    return get_repos_for_area(area)


def update_area_mapping(area: str, repo_ids: list[str]):
    """Update area-to-repo mapping."""
    data = load_repos()
    if "area_repo_map" not in data:
        data["area_repo_map"] = AREA_REPO_MAP
    data["area_repo_map"][area] = repo_ids
    save_repos(data)


def detect_language(path: str) -> str:
    """Auto-detect primary language from repo files."""
    p = Path(path)
    if not p.exists():
        return "unknown"

    indicators = {
        "php": ["composer.json", "artisan"],
        "python": ["requirements.txt", "setup.py", "pyproject.toml"],
        "javascript": ["package.json"],
        "typescript": ["tsconfig.json"],
        "java": ["pom.xml", "build.gradle"],
        "go": ["go.mod"],
        "rust": ["Cargo.toml"],
    }

    for lang, files in indicators.items():
        for f in files:
            if (p / f).exists():
                return lang
    return "unknown"
