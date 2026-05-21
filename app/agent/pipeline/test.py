"""Testing phase — run tests, detect failures, auto-fix with retries."""
import asyncio
import logging
import re as _re
import subprocess
import time
from typing import Optional

from ..phases import AgentPhase
from ..claude_client import _run_claude_cli
from ..state import BASH_BLOCKLIST, add_log, update_phase, save_agent_run, load_agent_run, _accumulate_cost
from ..stream_parser import detect_infra_error
from ...services.repo_manager import get_repo

log = logging.getLogger(__name__)


def has_migration_files(wt_path: str) -> bool:
    """Check if the agent's commits include migration files."""
    try:
        default_branch = "master"
        result = subprocess.run(
            ["git", "diff", "--name-only", f"origin/{default_branch}...HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return True  # assume yes if we can't check
        files = result.stdout.strip().split("\n")
        migration_patterns = ["migration", "migrate", "schema"]
        return any(
            any(p in f.lower() for p in migration_patterns)
            for f in files if f.strip()
        )
    except Exception:
        return True  # assume yes on error


_BACKEND_PATTERNS = (".php", ".env", "migration", "routes/", "config/", "composer.")


def has_backend_files(wt_path: str, default_branch: str = "master") -> bool:
    """True if any committed file could affect backend behaviour."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"origin/{default_branch}...HEAD"],
            cwd=wt_path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return True  # assume yes on error
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return any(
            any(p in f.lower() for p in _BACKEND_PATTERNS)
            for f in files
        )
    except Exception:
        return True  # assume yes on error


def select_test_cmd(repo: dict, wt_path: str) -> Optional[str]:
    """Pick the best test command: fast (no-migration) when safe, full otherwise."""
    default_branch = repo.get("default_branch", "master")
    full_cmd = repo.get("test_worktree_cmd") or repo.get("test_docker_cmd") or repo.get("test_cmd")

    if not has_backend_files(wt_path, default_branch):
        log.info("Frontend-only changes detected — skipping backend tests")
        return None

    fast_cmd = repo.get("test_worktree_cmd_fast")
    if fast_cmd and not has_migration_files(wt_path):
        log.info("No migration files detected — using fast test command: %s", fast_cmd)
        return fast_cmd

    return full_cmd


async def agent_test(task_gid: str, repo_entry: dict, test_cmd: str, test_cwd: str = None) -> bool:
    """Run tests in the worktree. Retry with Claude Code self-fix on failure."""
    run = load_agent_run(task_gid)
    max_retries = run.get("max_retries", 3)
    cwd = test_cwd or repo_entry["worktree_path"]
    add_log(task_gid, f"[{repo_entry['id']}] Test command: {test_cmd}")

    # Pre-check: if test command uses Docker, verify infra is available
    if "docker" in test_cmd:
        try:
            docker_check = subprocess.run(
                ["docker", "info"], capture_output=True, text=True, timeout=10,
            )
            if docker_check.returncode != 0:
                add_log(task_gid, f"[{repo_entry['id']}] Docker daemon not reachable. Skipping tests.", "warning")
                return True

            if "docker compose" in test_cmd:
                repo = get_repo(repo_entry["id"])
                compose_dir = repo["path"] if repo else cwd
                ps_check = subprocess.run(
                    ["docker", "compose", "ps", "--services", "--filter", "status=running"],
                    capture_output=True, text=True, timeout=10, cwd=compose_dir,
                )
                if "laravel.test" not in (ps_check.stdout or ""):
                    add_log(task_gid, f"[{repo_entry['id']}] Sail not running (laravel.test service down). Skipping tests.", "warning")
                    return True
            else:
                net_check = subprocess.run(
                    ["docker", "network", "ls", "--filter", "name=yurest_back_sail", "--format", "{{.Name}}"],
                    capture_output=True, text=True, timeout=10,
                )
                if "yurest_back_sail" not in (net_check.stdout or ""):
                    add_log(task_gid, f"[{repo_entry['id']}] Sail network not found. Skipping tests.", "warning")
                    return True

        except Exception as e:
            add_log(task_gid, f"[{repo_entry['id']}] Docker pre-check failed: {e}. Skipping tests.", "warning")
            return True

    for attempt in range(max_retries + 1):
        add_log(task_gid, f"[{repo_entry['id']}] Running tests (attempt {attempt + 1})...")

        try:
            returncode, full_output = await run_test_with_progress(
                task_gid, repo_entry["id"], test_cmd, cwd,
            )

            if returncode == 0:
                add_log(task_gid, f"[{repo_entry['id']}] Tests passed")
                return True

            error_output = full_output[-2000:]
            add_log(task_gid, f"[{repo_entry['id']}] Test output (last 500 chars): {error_output[-500:]}", "debug")

            matched_pattern = detect_infra_error(error_output)
            if matched_pattern:
                add_log(task_gid, f"[{repo_entry['id']}] Infrastructure issue (matched: '{matched_pattern}'). Skipping tests.", "warning")
                return True

            add_log(task_gid, f"[{repo_entry['id']}] Tests failed:\n{error_output[:500]}", "warning")

            if attempt < max_retries:
                run["retries"] = attempt + 1
                save_agent_run(task_gid, run)
                fix_success = await _agent_fix_tests(task_gid, repo_entry, error_output)
                if not fix_success:
                    break
            else:
                update_phase(task_gid, AgentPhase.ERROR,
                             error=f"Tests failed after {max_retries} retries")
                return False

        except subprocess.TimeoutExpired:
            add_log(task_gid, f"[{repo_entry['id']}] Test timeout (10 min)", "error")
            update_phase(task_gid, AgentPhase.ERROR, error="Test timeout")
            return False

    return False


async def run_test_with_progress(task_gid: str, repo_id: str, test_cmd: str, cwd: str) -> tuple[int, str]:
    """Run test command with Popen, streaming progress updates via WebSocket."""
    proc = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: subprocess.Popen(
            ["/bin/sh", "-c", test_cmd] if isinstance(test_cmd, str) else test_cmd,
            cwd=cwd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,
        ),
    )

    full_output = []
    phase = "setup"
    last_progress_pct = -1
    last_progress_time = time.monotonic()
    test_total = 0
    test_current = 0
    migration_count = 0

    progress_re = _re.compile(r'(\d+)\s*/\s*(\d+)\s*\(\s*(\d+)%\)')
    migration_re = _re.compile(r'^\s*\d{4}_\d{2}_\d{2}_\d+_\S+.*DONE', _re.MULTILINE)
    seeder_re = _re.compile(r'Database\\Seeders\\')
    summary_re = _re.compile(r'(?:Tests?:?\s*(\d+)|OK\s*\((\d+)\s*test)')

    try:
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, proc.stdout.readline)
            if not line and proc.poll() is not None:
                break
            if not line:
                continue

            full_output.append(line)

            if phase == "setup" and ("migration" in line.lower() or migration_re.search(line)):
                phase = "migrating"
                add_log(task_gid, f"[{repo_id}] Migrating database...")

            if phase != "seeding" and seeder_re.search(line):
                if phase == "migrating":
                    add_log(task_gid, f"[{repo_id}] Migrations done. Seeding...")
                phase = "seeding"

            if "ParaTest" in line or "PHPUnit" in line or "phpunit" in line.lower():
                if phase != "testing":
                    phase = "testing"
                    add_log(task_gid, f"[{repo_id}] Running tests...")

            if phase == "migrating" and "DONE" in line:
                migration_count += 1

            m = progress_re.search(line)
            if m:
                phase = "testing"
                test_current = int(m.group(1))
                test_total = int(m.group(2))
                pct = int(m.group(3))
                now = time.monotonic()
                if pct >= last_progress_pct + 10 or now - last_progress_time >= 30:
                    add_log(task_gid, f"[{repo_id}] Tests: {pct}% ({test_current}/{test_total})")
                    last_progress_pct = pct
                    last_progress_time = now

        proc.wait(timeout=600)

        output_str = "".join(full_output[-50:])
        if proc.returncode == 0:
            fail_count = output_str.count("E") + output_str.count("F")
            skip_count = output_str.count("S") + output_str.count("R")
            if test_total > 0:
                passed = test_total - fail_count - skip_count
                parts = [f"{passed} passed"]
                if skip_count > 0:
                    parts.append(f"{skip_count} skipped")
                if fail_count > 0:
                    parts.append(f"{fail_count} errors")
                add_log(task_gid, f"[{repo_id}] Results: {', '.join(parts)}")

        return proc.returncode, "".join(full_output)

    except Exception:
        proc.kill()
        proc.wait()
        raise


async def _agent_fix_tests(task_gid: str, repo_entry: dict, error_output: str) -> bool:
    """Attempt to fix failing tests using Claude Code CLI."""
    try:
        prompt = f"Tests are failing with this output:\n\n{error_output}\n\nFix the issues and commit."

        result = await _run_claude_cli(
            prompt=prompt,
            cwd=repo_entry["worktree_path"],
            max_turns=8,
            subprocess_timeout=300.0,  # 5 min cap — prevents rate-limit waiting from blocking hours
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            system_prompt=f"You are fixing failing tests. Read the error output, identify the issue, and fix it. Make minimal changes. {BASH_BLOCKLIST} NEVER modify Makefile, Dockerfile, docker-compose.yml, or any infrastructure/config files. Only fix application code and tests.",
            task_gid=task_gid,
        )

        try:
            _accumulate_cost(task_gid, result)
        except Exception as e:
            log.warning(f"Failed to accumulate cost for test fix: {e}")

        rc = result["returncode"]
        has_result = bool(result.get("text") or result.get("parsed"))
        rate_limited = result.get("rate_limited", False)

        if rc == 0 or (has_result and rate_limited):
            # Exit 1 with a captured result + rate limit event = CLI exited non-zero
            # due to the rate limit encounter, but the agent actually completed its work.
            if rc != 0:
                add_log(task_gid, f"[{repo_entry['id']}] Auto-fix exited {rc} but result captured (rate limit during run) — treating as success", "warning")
            else:
                add_log(task_gid, f"[{repo_entry['id']}] Auto-fix attempt completed")
            return True

        add_log(task_gid, f"[{repo_entry['id']}] Auto-fix failed (exit {rc}, has_result={has_result}, rate_limited={rate_limited})", "error")
        return False

    except Exception as e:
        add_log(task_gid, f"[{repo_entry['id']}] Auto-fix failed: {e}", "error")
        return False
