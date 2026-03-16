"""Agent worker API routes."""
import re
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional

from ..agent import (
    start_agent, stop_agent, answer_question, guide_agent,
    get_agent_status, list_active_agents,
    check_claude_code_status, clear_agent_run,
    get_workflow_graph, get_worktree_diff, load_agent_run,
    load_agent_settings, save_agent_settings,
    trigger_manual_qa, run_manual_tests,
    AGENT_RUNS_DIR,
    agent_queue,
    load_memory, clear_memory, get_all_memory_repos,
)
from ..services.asana_client import fetch_task_stories, fetch_subtasks
from ..services.task_cache import get_cached_tasks
from ..services.repo_manager import (
    get_task_repo_override, set_task_repo_override,
    load_task_repo_overrides,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# Regex to detect git branch names in comments/subtask names
_BRANCH_RE = re.compile(
    r'(?:branch[:\s]+|rama[:\s]+|merge[:\s]+|(?:^|\s))'
    r'((?:feature|fix|bugfix|hotfix|release|chore|refactor)/[\w./-]+)',
    re.IGNORECASE | re.MULTILINE,
)


class StartAgent(BaseModel):
    branch_slug: str
    base_branch: Optional[str] = None

    @field_validator("branch_slug")
    @classmethod
    def validate_branch_slug(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9._/-]{1,80}$', v) or '..' in v:
            raise ValueError("branch_slug must be 1-80 alphanumeric/._/- chars, no '..'")
        return v


class AnswerQuestion(BaseModel):
    answer: str

    @property
    def clean_answer(self) -> str:
        return self.answer.strip()


class QueueConfig(BaseModel):
    max_parallel: Optional[int] = None
    token_budget_per_task: Optional[int] = None


class ReorderQueue(BaseModel):
    task_gids: list[str]


class TaskRepoOverride(BaseModel):
    repo_ids: list[str]


@router.get("")
async def get_agents():
    """List all agent runs (active and completed)."""
    agents = list_active_agents()
    return {"agents": agents, "count": len(agents)}


@router.get("/cli-status")
async def claude_cli_status():
    """Check if Claude Code CLI is installed and authenticated."""
    return check_claude_code_status()


@router.get("/workflow")
async def workflow_graph():
    """Return the agent workflow graph for UI visualization."""
    return get_workflow_graph()


@router.get("/branch-suggestions/{task_gid}")
async def get_branch_suggestions(task_gid: str):
    """Detect branch names in Asana comments and subtask names."""
    branches = []
    seen = set()

    # Scan comments
    try:
        stories = await fetch_task_stories(task_gid)
        for story in reversed(stories):  # most recent first
            text = story.get("text", "")
            for match in _BRANCH_RE.finditer(text):
                branch = match.group(1).strip().rstrip("/")
                if branch not in seen:
                    seen.add(branch)
                    author = story.get("created_by", {}).get("name", "?")
                    branches.append({"branch": branch, "author": author})
    except Exception:
        pass

    # Scan subtask names (e.g. "Merge: feature/xxx/yyy")
    try:
        subtasks = await fetch_subtasks(task_gid)
        for st in subtasks:
            name = st.get("name", "")
            for match in _BRANCH_RE.finditer(name):
                branch = match.group(1).strip().rstrip("/")
                if branch not in seen:
                    seen.add(branch)
                    branches.append({"branch": branch, "author": "subtask"})
    except Exception:
        pass

    return {"branches": branches}


@router.post("/start/{task_gid}")
async def start_task_agent(task_gid: str, body: StartAgent):
    """Start an AI agent for a task."""
    # Find the task in cache
    tasks, _ = get_cached_tasks()
    task = next((t for t in tasks if t["task_gid"] == task_gid), None)
    if not task:
        raise HTTPException(404, f"Task {task_gid} not found in cache")

    try:
        run = await start_agent(task_gid, task, body.branch_slug, base_branch=body.base_branch)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return run


@router.post("/stop/{task_gid}")
async def stop_task_agent(task_gid: str):
    """Stop a running agent."""
    if not await stop_agent(task_gid):
        raise HTTPException(404, "No active agent for this task")
    return {"status": "ok", "task_gid": task_gid}


@router.get("/status/{task_gid}")
async def agent_status(task_gid: str):
    """Get agent run status for a task."""
    status = get_agent_status(task_gid)
    if not status:
        raise HTTPException(404, "No agent run found for this task")
    return status


@router.delete("/clear/{task_gid}")
async def clear_agent(task_gid: str):
    """Remove an agent run record (dismiss from UI)."""
    if not clear_agent_run(task_gid):
        raise HTTPException(404, "No agent run found for this task")
    return {"status": "ok", "task_gid": task_gid}


@router.post("/answer/{task_gid}")
async def answer_agent_question(task_gid: str, body: AnswerQuestion):
    """Answer a question from a paused agent."""
    if not body.answer.strip():
        raise HTTPException(400, "Answer cannot be empty")
    if not await answer_question(task_gid, body.answer.strip()):
        raise HTTPException(400, "Agent is not in paused/question state or no question pending")
    return {"status": "ok", "answer": body.answer.strip()}


class GuideAgent(BaseModel):
    feedback: str

    @field_validator("feedback")
    @classmethod
    def validate_feedback(cls, v):
        if not v or not v.strip():
            raise ValueError("Feedback cannot be empty")
        return v.strip()


@router.post("/guide/{task_gid}")
async def guide_task_agent(task_gid: str, body: GuideAgent):
    """Send real-time feedback to a running agent coding session."""
    result = await guide_agent(task_gid, body.feedback)
    if not result:
        raise HTTPException(409, "Agent must be in coding phase with an active worker")
    return {"status": "ok", "task_gid": task_gid}


@router.post("/test/{task_gid}")
async def run_tests(task_gid: str):
    """Manually run tests on a task's worktree(s)."""
    try:
        result = await run_manual_tests(task_gid)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/qa/{task_gid}")
async def run_qa_review(task_gid: str):
    """Manually trigger QA review on a completed task."""
    try:
        tasks, _ = get_cached_tasks()
        task = next((t for t in tasks if t["task_gid"] == task_gid), None)
        if not task:
            raise HTTPException(404, f"Task {task_gid} not found")
        result = await trigger_manual_qa(task_gid, task)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/history")
async def agent_history():
    """Return all past agent runs (current + archived) with stats."""
    runs = []
    # Current runs
    if AGENT_RUNS_DIR.exists():
        for f in AGENT_RUNS_DIR.glob("*.json"):
            try:
                run = json.loads(f.read_text())
                runs.append(run)
            except (json.JSONDecodeError, OSError):
                continue
    # Archived runs
    archive_dir = AGENT_RUNS_DIR / "history"
    if archive_dir.exists():
        for f in archive_dir.glob("*.json"):
            try:
                run = json.loads(f.read_text())
                runs.append(run)
            except (json.JSONDecodeError, OSError):
                continue
    # Normalize to summary format
    summaries = []
    for run in runs:
        summaries.append({
            "task_gid": run.get("task_gid"),
            "task_name": run.get("task_name", ""),
            "phase": run.get("phase"),
            "created_at": run.get("created_at"),
            "completed_at": run.get("completed_at"),
            "duration_seconds": run.get("duration_seconds"),
            "cost_usd": run.get("cost_usd", 0),
            "tokens": run.get("tokens", {}),
            "retries": run.get("retries", 0),
            "repos": [{"id": r["id"], "commits": r.get("commits", 0), "branch": r.get("branch")} for r in run.get("repos", [])],
            "error": run.get("error"),
            "quality_checks": run.get("quality_checks", []),
        })
    runs = summaries
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)

    # Aggregate stats
    completed = [r for r in runs if r["phase"] == "done"]
    failed = [r for r in runs if r["phase"] == "error"]
    total_cost = sum(r.get("cost_usd", 0) for r in runs)
    avg_duration = sum(r.get("duration_seconds", 0) or 0 for r in completed) / max(len(completed), 1)

    return {
        "runs": runs,
        "stats": {
            "total_runs": len(runs),
            "completed": len(completed),
            "failed": len(failed),
            "success_rate": round(len(completed) / max(len(runs), 1) * 100, 1),
            "total_cost_usd": round(total_cost, 4),
            "avg_duration_seconds": round(avg_duration, 1),
        }
    }


@router.get("/diff/{task_gid}/{repo_id}")
async def get_diff(task_gid: str, repo_id: str):
    """Get diff preview for a task's repo worktree."""
    return get_worktree_diff(task_gid, repo_id)


@router.get("/diff/{task_gid}/{repo_id}/file")
async def get_file_diff(task_gid: str, repo_id: str, path: str = ""):
    """Get full diff for a specific file."""
    import subprocess
    from repo_manager import get_repo

    run = load_agent_run(task_gid)
    if not run:
        raise HTTPException(404, "No agent run")
    repo_entry = next((r for r in run.get("repos", []) if r["id"] == repo_id), None)
    if not repo_entry or not repo_entry.get("worktree_path"):
        raise HTTPException(404, "No worktree")

    wt_path = repo_entry["worktree_path"]
    repo = get_repo(repo_id)
    default_branch = repo.get("default_branch", "master") if repo else "master"

    cmd = ["git", "diff", f"origin/{default_branch}...HEAD"]
    if path:
        cmd.extend(["--", path])

    try:
        result = subprocess.run(cmd, cwd=wt_path, capture_output=True, text=True, timeout=10)
        return {"diff": result.stdout[:50000]}  # Limit to 50KB
    except Exception as e:
        raise HTTPException(500, f"Diff error: {str(e)}")


# ─── Queue Management Endpoints ───


@router.get("/queue")
async def get_queue_status():
    """Get queue status: running, queued, and config."""
    return {
        "queue": agent_queue.queue_list,
        "running_count": agent_queue.running_count,
        "slots_available": agent_queue.slots_available,
        "config": agent_queue.config,
    }


@router.put("/queue/config")
async def update_queue_config(body: QueueConfig):
    """Update queue configuration (max_parallel, token_budget_per_task)."""
    config_update = {}
    if body.max_parallel is not None:
        config_update["max_parallel"] = max(1, body.max_parallel)
    if body.token_budget_per_task is not None:
        config_update["token_budget_per_task"] = max(1000, body.token_budget_per_task)

    if config_update:
        agent_queue.save_config(config_update)

    return {"status": "ok", "config": agent_queue.config}


@router.delete("/queue/{task_gid}")
async def remove_from_queue(task_gid: str):
    """Remove a task from the queue (does nothing if not queued or already running)."""
    agent_queue.dequeue(task_gid)
    return {"status": "ok", "task_gid": task_gid}


@router.put("/queue/reorder")
async def reorder_queue(body: ReorderQueue):
    """Reorder the task queue to match the given GID order."""
    agent_queue.reorder(body.task_gids)
    return {"status": "ok", "queue": agent_queue.queue_list}


# ─── Task Repo Override Endpoints ───


@router.get("/task-repo-overrides")
async def get_all_task_repo_overrides():
    """Get all task repo overrides (bulk)."""
    return load_task_repo_overrides()


@router.get("/task/{task_gid}/repos")
async def get_task_repo_override_endpoint(task_gid: str):
    """Get the current repo override for a task."""
    override = get_task_repo_override(task_gid)
    return {"task_gid": task_gid, "repo_ids": override}


@router.put("/task/{task_gid}/repos")
async def set_task_repo_override_endpoint(task_gid: str, body: TaskRepoOverride):
    """Set the repo override for a task."""
    set_task_repo_override(task_gid, body.repo_ids)
    return {"task_gid": task_gid, "repo_ids": body.repo_ids, "status": "ok"}


# ─── Agent Memory Endpoints ───


@router.get("/memory")
async def list_memory():
    """List all repos with stored agent memory."""
    repos = get_all_memory_repos()
    return {"repos": repos, "count": len(repos)}


@router.get("/memory/{repo_id}")
async def get_memory(repo_id: str):
    """Get agent memory for a specific repo."""
    memory = load_memory(repo_id)
    if not memory["entries"] and not memory["patterns"]:
        raise HTTPException(404, f"No memory found for repo {repo_id}")
    return memory


@router.delete("/memory/{repo_id}")
async def clear_repo_memory(repo_id: str):
    """Clear agent memory for a specific repo."""
    if not clear_memory(repo_id):
        raise HTTPException(500, f"Failed to clear memory for repo {repo_id}")
    return {"status": "ok", "repo_id": repo_id}


# ─── Agent Settings Endpoints ───


class AgentSettings(BaseModel):
    section_on_start: Optional[str] = None
    section_on_done: Optional[str] = None
    section_on_error: Optional[str] = None


@router.get("/settings")
async def get_settings():
    """Return current agent settings."""
    return load_agent_settings()


@router.put("/settings")
async def update_settings(settings: AgentSettings):
    """Update agent settings (section mappings, etc.)."""
    current = load_agent_settings()
    updates = settings.model_dump(exclude_none=False)
    current.update(updates)
    save_agent_settings(current)
    return current
