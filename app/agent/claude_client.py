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


# Best model detected for the current token — set at startup / token change
_best_model: str = "claude-sonnet-4-6"


def get_best_model() -> str:
    """Return the best model available for the current token."""
    return _best_model


def _probe_model(cli: str, cli_env: dict, model: str, timeout: int = 20) -> bool:
    """Return True if the given model responds without auth/capacity errors."""
    try:
        r = subprocess.run(
            [cli, "-p", "ok", "--max-turns", "1", "--output-format", "text",
             "--model", model, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=timeout, env=cli_env,
        )
        if r.returncode == 0:
            return True
        combined = (r.stderr + r.stdout).lower()
        # Hard auth failures → not authenticated at all
        if "not logged in" in combined or "please run" in combined:
            return False
        # Capacity/credits errors → model unavailable but token is valid
        # Treat as "model not available" but don't fail auth
        return False
    except subprocess.TimeoutExpired:
        return True  # responded = available
    except Exception:
        return False


def _check_claude_auth() -> dict:
    """Check authentication and detect the best available model for the current token."""
    global _best_model
    cli = _find_claude_cli()
    if not cli:
        return {"authenticated": False, "detail": "CLI not found"}

    cli_env = {k: v for k, v in os.environ.items() if k in _ALLOWED_ENV_KEYS}

    # Try models best → fallback
    candidates = [
        ("claude-sonnet-4-6",        "Sonnet 4.6"),
        ("claude-haiku-4-5-20251001", "Haiku 4.5"),
    ]

    for model_id, model_label in candidates:
        if _probe_model(cli, cli_env, model_id):
            _best_model = model_id
            log.info("[claude] Auth OK — best available model: %s (%s)", model_label, model_id)
            return {"authenticated": True, "best_model": model_id, "best_model_label": model_label}

    # Nothing worked — check if it's a hard auth failure
    try:
        r = subprocess.run(
            [cli, "-p", "ok", "--max-turns", "1", "--output-format", "text",
             "--model", "claude-haiku-4-5-20251001", "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=20, env=cli_env,
        )
        combined = (r.stderr + r.stdout).strip()
        return {"authenticated": False, "detail": combined[:200] if combined else "CLI returned non-zero"}
    except subprocess.TimeoutExpired:
        return {"authenticated": True, "detail": "CLI slow but responding"}
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
            "best_model": auth.get("best_model", _best_model),
            "best_model_label": auth.get("best_model_label", ""),
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
                          model: str = None,
                          subprocess_timeout: float = None,
                          on_text_chunk=None) -> dict:
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

    log.info("[claude] Subprocess starting — task=%s model=%s max_turns=%d prompt_len=%d",
             task_gid or "?", model or "default", max_turns, len(prompt))
    if task_gid:
        add_log(task_gid, f"[claude] Subprocess starting (model={model or 'default'}, max_turns={max_turns})", "debug")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=cli_env,
        stdin=asyncio.subprocess.PIPE if use_stdin else asyncio.subprocess.DEVNULL,
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
    saw_rate_limit = False

    async def _stream_stdout():
        nonlocal result_text, final_result, captured_session_id, saw_rate_limit
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
                _handle_stream_event_tracking(event, task_gid)
                if event.get("type") == "rate_limit_event":
                    saw_rate_limit = True
                    log.info("[claude] rate_limit_event raw payload: %s", event)
                # Stream text chunks to caller if requested
                if on_text_chunk and event.get("type") == "assistant":
                    content = event.get("message", {}).get("content", [])
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            chunk = block.get("text", "")
                            if chunk:
                                asyncio.get_event_loop().create_task(on_text_chunk(chunk))
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

    # Track last meaningful action for heartbeat context
    last_action: list[str] = ["(starting...)"]

    original_handle = _handle_stream_event

    def _handle_stream_event_tracking(event: dict, tgid: str | None):
        original_handle(event, tgid)
        etype = event.get("type", "")
        if etype == "tool_use":
            name = event.get("name", "?")
            inp = event.get("input", {})
            detail = inp.get("file_path") or inp.get("command", "")[:60] or inp.get("pattern", "")
            last_action[0] = f"{name}: {detail}" if detail else name
        elif etype == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        last_action[0] = text[:80].replace("\n", " ")
                    break
        elif etype == "rate_limit_event":
            last_action[0] = "⏳ rate limit — waiting for API quota..."
            if tgid:
                # Extract everything Anthropic sends in the event
                retry_ms = event.get("retry_after_ms") or event.get("retryAfterMs")
                limit_type = event.get("limit_type") or event.get("limitType") or event.get("type_")
                remaining = event.get("remaining") or event.get("requests_remaining")
                reset_at = event.get("reset_at") or event.get("resetAt")
                # Build informative message from whatever fields are present
                parts = ["[claude] Rate limit hit"]
                if limit_type and limit_type != "rate_limit_event":
                    parts.append(f"type={limit_type}")
                if retry_ms:
                    parts.append(f"retry_after={int(retry_ms/1000)}s")
                if remaining is not None:
                    parts.append(f"remaining={remaining}")
                if reset_at:
                    parts.append(f"resets_at={reset_at}")
                # Log full raw event at debug level so nothing is hidden
                unknown_keys = {k: v for k, v in event.items() if k not in ("type", "retry_after_ms", "retryAfterMs", "limit_type", "limitType", "type_", "remaining", "requests_remaining", "reset_at", "resetAt")}
                if unknown_keys:
                    parts.append(f"raw={unknown_keys}")
                add_log(tgid, " — ".join(parts), "warning")

    # Heartbeat: log "still working..." every 30s + kill if rate-limited too long
    # Max time to wait on a rate limit before giving up (avoids all-night hangs)
    MAX_RATE_LIMIT_WAIT = 20 * 60  # 20 minutes
    rate_limit_seconds: list[int] = [0]  # mutable for closure

    async def _heartbeat():
        last_count = 0
        silent_seconds = 0
        while process.returncode is None:
            await asyncio.sleep(30)
            silent_seconds += 30
            if process.returncode is not None:
                break
            if len(stdout_lines) == last_count:
                if task_gid:
                    add_log(task_gid, f"[claude] Still working... ({silent_seconds}s silent) — last: {last_action[0]}", "debug")
            else:
                last_count = len(stdout_lines)
                silent_seconds = 0  # reset after non-rate-limit activity

            # Track consecutive rate-limit-only time
            if "rate limit" in last_action[0].lower():
                rate_limit_seconds[0] += 30
                if rate_limit_seconds[0] >= MAX_RATE_LIMIT_WAIT:
                    if task_gid:
                        add_log(task_gid,
                            f"[claude] Rate limit persisted {rate_limit_seconds[0]//60}min — killing subprocess to avoid all-night hang",
                            "warning")
                    log.warning("Rate limit kill after %ds for task %s", rate_limit_seconds[0], task_gid)
                    process.kill()
                    break
            else:
                rate_limit_seconds[0] = 0  # reset when non-rate-limit activity happens

    heartbeat_task = asyncio.create_task(_heartbeat())
    timed_out = False
    try:
        streams = asyncio.gather(_stream_stdout(), _stream_stderr())
        if subprocess_timeout:
            try:
                await asyncio.wait_for(streams, timeout=subprocess_timeout)
            except asyncio.TimeoutError:
                timed_out = True
                if task_gid:
                    stderr_so_far = "".join(stderr_chunks)[:500]
                    add_log(task_gid, f"[claude] Subprocess timeout after {int(subprocess_timeout)}s — killing process. stderr={stderr_so_far!r}", "warning")
                process.kill()
        else:
            await streams
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        process.kill()
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

    # Detect rate limit errors from stderr, stdout, or stream events
    combined = error_text + raw_output
    if "rate limit" in combined.lower() or "Rate limit" in combined:
        raise RuntimeError("API Error: Rate limit reached — wait a moment and retry")
    if saw_rate_limit and task_gid:
        add_log(task_gid, "[claude] Rate limit event detected during stream", "warning")

    # If no "result" event was captured, extract from stream-json events
    if not result_text:
        if task_gid:
            event_types = {}
            sample_assistant = None
            for line in stdout_lines:
                try:
                    ev = json.loads(line)
                    et = ev.get("type", "unknown")
                    event_types[et] = event_types.get(et, 0) + 1
                    # Capture first assistant event structure for debugging
                    if et == "assistant" and not sample_assistant:
                        sample_assistant = str(ev)[:500]
                except (json.JSONDecodeError, KeyError):
                    pass
            log.info("Stream event types for %s: %s", task_gid, event_types)
            if sample_assistant:
                log.info("Sample assistant event for %s: %s", task_gid, sample_assistant)
            add_log(task_gid, f"[claude] Stream fallback: events={event_types}", "debug")
        result_text = extract_result_from_stream_lines(stdout_lines)

    result = {
        "returncode": process.returncode,
        "raw_output": raw_output,
        "stderr": error_text,
        "text": result_text or "",
        "timed_out": timed_out,
        "rate_limited": saw_rate_limit,
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
