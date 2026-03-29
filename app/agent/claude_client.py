"""Claude Code CLI wrapper — find, authenticate, and run the CLI."""
import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Optional

from .stream_parser import extract_result_from_stream_lines
from ..services.worktree_manager import WORKTREE_BASE
from .state import add_log

log = logging.getLogger(__name__)

# Active Claude subprocess handles — allows external termination (guide feature)
_active_claude_processes: dict[str, asyncio.subprocess.Process] = {}

# Allowlist safe env vars so CLI doesn't inherit secrets like ASANA_PAT
_ALLOWED_ENV_KEYS = {
    "PATH", "HOME", "TMPDIR", "LANG", "USER", "SHELL", "TERM",
    "CLAUDE_CODE_OAUTH_TOKEN", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
}


def _find_claude_cli() -> Optional[str]:
    """Find the claude CLI binary."""
    return shutil.which("claude")


def _check_claude_auth() -> dict:
    """Check if Claude Code is authenticated by running a quick CLI test."""
    cli = _find_claude_cli()
    if not cli:
        return {"authenticated": False, "detail": "CLI not found"}

    try:
        cli_env = {k: v for k, v in os.environ.items() if k in _ALLOWED_ENV_KEYS}
        result = subprocess.run(
            [cli, "-p", "say ok", "--max-turns", "1", "--output-format", "text",
             "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=30, env=cli_env,
        )
        if result.returncode == 0:
            return {"authenticated": True}
        stderr = result.stderr.strip()
        return {"authenticated": False, "detail": stderr[:200] if stderr else "CLI returned non-zero"}
    except subprocess.TimeoutExpired:
        return {"authenticated": True, "detail": "CLI responded (slow)"}
    except Exception as e:
        return {"authenticated": False, "detail": str(e)}


def check_claude_code_status() -> dict:
    """Check if Claude Code CLI is available and authenticated."""
    cli = _find_claude_cli()
    if not cli:
        return {
            "available": False,
            "authenticated": False,
            "error": "Claude Code CLI not found. Install: npm install -g @anthropic-ai/claude-code",
        }

    try:
        result = subprocess.run(
            [cli, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {
                "available": False,
                "authenticated": False,
                "error": f"Claude CLI error: {result.stderr.strip()}",
            }

        version = result.stdout.strip()
        auth = _check_claude_auth()

        return {
            "available": True,
            "authenticated": auth["authenticated"],
            "version": version,
            "path": cli,
            "error": None if auth["authenticated"] else (
                auth.get("detail") or "Not logged in. Run 'claude login' on your Mac."
            ),
        }

    except subprocess.TimeoutExpired:
        return {"available": False, "authenticated": False, "error": "Claude CLI timed out"}
    except Exception as e:
        return {"available": False, "authenticated": False, "error": str(e)}


async def _run_claude_cli(prompt: str, cwd: str, max_turns: int = 30,
                          allowed_tools: list[str] = None,
                          system_prompt: str = None,
                          output_format: str = "text",
                          task_gid: str = None,
                          resume_session_id: str = None,
                          model: str = None) -> dict:
    """Run Claude Code CLI as subprocess and stream output to logs in real time."""
    cli = _find_claude_cli()
    if not cli:
        raise RuntimeError("Claude Code CLI not found")

    # Worktree path sandboxing — verify cwd is within expected worktree base
    if cwd and WORKTREE_BASE:
        real_cwd = os.path.realpath(cwd)
        real_base = os.path.realpath(str(WORKTREE_BASE))
        if not real_cwd.startswith(real_base):
            raise RuntimeError(f"CWD {cwd} is outside worktree sandbox {WORKTREE_BASE}")

    # Always use stream-json for live streaming; we parse the final result ourselves
    # Use stdin piping only for large prompts (>100KB) to avoid Errno 7: Argument list too long.
    use_stdin = len(prompt.encode("utf-8")) > 100_000

    if use_stdin:
        cmd = [cli, "-p", "--output-format", "stream-json", "--verbose", "--max-turns", str(max_turns)]
    else:
        cmd = [cli, "-p", prompt, "--output-format", "stream-json", "--verbose", "--max-turns", str(max_turns)]

    # Resume an existing session (for guide feature)
    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])

    if allowed_tools is not None:
        if len(allowed_tools) == 0:
            # Empty list = no tools allowed; use a non-existent tool name to block all
            cmd.extend(["--allowedTools", "__none__"])
        else:
            for tool in allowed_tools:
                cmd.extend(["--allowedTools", tool])

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    if model:
        cmd.extend(["--model", model])

    # --dangerously-skip-permissions avoids interactive prompts in headless mode
    cmd.append("--dangerously-skip-permissions")

    cli_env = {k: v for k, v in os.environ.items() if k in _ALLOWED_ENV_KEYS}

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=cli_env,
        stdin=asyncio.subprocess.PIPE if use_stdin else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=10 * 1024 * 1024,  # 10MB line buffer (stream-json can emit large lines)
    )

    # Register process handle for external termination (guide feature)
    if task_gid:
        _active_claude_processes[task_gid] = process

    # Feed the prompt via stdin for large prompts
    if use_stdin and process.stdin:
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()

    # Stream stdout line-by-line (each line is a JSON event from stream-json)
    stdout_lines = []
    result_text = ""
    final_result = None
    captured_session_id = None

    async def _stream_stdout():
        nonlocal result_text, final_result, captured_session_id
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            stdout_lines.append(decoded)
            try:
                event = json.loads(decoded)
                _handle_stream_event(event, task_gid)
                # Capture the final result message and session_id
                if event.get("type") == "result":
                    result_text = event.get("result", "")
                    final_result = event
                    captured_session_id = event.get("session_id")
            except json.JSONDecodeError:
                pass

    # Collect stderr in background
    stderr_chunks = []

    async def _stream_stderr():
        while True:
            chunk = await process.stderr.read(4096)
            if not chunk:
                break
            stderr_chunks.append(chunk.decode("utf-8", errors="replace"))

    # Heartbeat: log "still working..." every 30s if no events received
    async def _heartbeat():
        last_count = 0
        elapsed = 0
        while process.returncode is None:
            await asyncio.sleep(30)
            elapsed += 30
            if process.returncode is not None:
                break
            if len(stdout_lines) == last_count and task_gid:
                add_log(task_gid, f"[claude] Still working... ({elapsed}s elapsed)", "debug")
            else:
                last_count = len(stdout_lines)
                elapsed = 0  # reset after activity

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        await asyncio.gather(_stream_stdout(), _stream_stderr())
        await process.wait()
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        # Deregister process handle
        if task_gid:
            _active_claude_processes.pop(task_gid, None)

    error_text = "".join(stderr_chunks)
    raw_output = "\n".join(stdout_lines)

    # If no "result" event was captured, extract from stream-json events
    if not result_text:
        if task_gid:
            event_types = {}
            for line in stdout_lines:
                try:
                    ev = json.loads(line)
                    event_types[ev.get("type", "unknown")] = event_types.get(ev.get("type", "unknown"), 0) + 1
                except (json.JSONDecodeError, KeyError):
                    pass
            log.info("Stream event types for %s: %s", task_gid, event_types)
        result_text = extract_result_from_stream_lines(stdout_lines)

    result = {
        "returncode": process.returncode,
        "raw_output": raw_output,
        "stderr": error_text,
        "text": result_text or raw_output,
    }
    if final_result:
        result["parsed"] = final_result
    if captured_session_id:
        result["session_id"] = captured_session_id

    return result


async def kill_active_claude(task_gid: str) -> bool:
    """Terminate the Claude subprocess running for this task, if any.

    Sends SIGTERM first, waits 5s, then SIGKILL if needed.
    Returns True if a process was found and terminated.
    """
    proc = _active_claude_processes.pop(task_gid, None)
    if not proc or proc.returncode is not None:
        return False
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass
    return True


def _handle_stream_event(event: dict, task_gid: str | None):
    """Process a single stream-json event and log meaningful actions."""
    if not task_gid:
        return

    etype = event.get("type", "")

    if etype == "assistant" and event.get("message", {}).get("role") == "assistant":
        content = event.get("message", {}).get("content", [])
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "").strip()
                if text:
                    summary = text[:200] + ("..." if len(text) > 200 else "")
                    add_log(task_gid, f"[claude] {summary}", "debug")
                break

    elif etype == "content_block_start":
        block = event.get("content_block", {})
        if block.get("type") == "tool_use":
            tool_name = block.get("name", "?")
            add_log(task_gid, f"[claude] Using tool: {tool_name}")

    elif etype == "tool_use":
        tool_name = event.get("name", "?")
        tool_input = event.get("input", {})
        if tool_name == "Edit":
            fp = tool_input.get("file_path", "?")
            add_log(task_gid, f"[claude] Edit: {fp}")
        elif tool_name == "Write":
            fp = tool_input.get("file_path", "?")
            add_log(task_gid, f"[claude] Write: {fp}")
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "?")[:120]
            add_log(task_gid, f"[claude] Bash: {cmd}")
        elif tool_name == "Read":
            fp = tool_input.get("file_path", "?")
            add_log(task_gid, f"[claude] Read: {fp}")
        elif tool_name in ("Glob", "Grep"):
            pattern = tool_input.get("pattern", "?")
            add_log(task_gid, f"[claude] {tool_name}: {pattern}")
        else:
            add_log(task_gid, f"[claude] Tool: {tool_name}")

    elif etype == "result":
        cost = event.get("cost_usd")
        turns = event.get("num_turns")
        duration = event.get("duration_ms")
        parts = []
        if turns:
            parts.append(f"{turns} turns")
        if duration:
            parts.append(f"{duration/1000:.1f}s")
        if cost:
            parts.append(f"${cost:.4f}")
        if parts:
            add_log(task_gid, f"[claude] Done ({', '.join(parts)})")
