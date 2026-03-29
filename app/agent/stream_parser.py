"""Stream-json parsing utilities for Claude CLI output.

Extracted from agent_worker.py for testability.
"""
import json
import re
from typing import Optional


# Infrastructure error patterns — only real Docker/container failures
INFRA_ERROR_PATTERNS = [
    "Cannot connect to the Docker daemon",
    "unable to find user",
    "no matching entries in passwd",
    "No such file or directory: 'docker'",
    "Error: No such container",
    r"network .* not found",
    "Error response from daemon",
]


def extract_text_from_stream(raw_text: str) -> Optional[str]:
    """Extract human-readable text from raw stream-json output.

    Handles three event types:
    - "assistant" messages with content blocks
    - "content_block_delta" with text_delta
    - "result" with result text

    Returns extracted text or None if nothing could be extracted.
    """
    if not raw_text or not raw_text.startswith("{"):
        return raw_text  # Not stream-json, return as-is

    extracted = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                ev = json.loads(line)
                if ev.get("type") == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text", "").strip()
                            if t:
                                extracted.append(t)
                elif ev.get("type") == "content_block_delta":
                    delta = ev.get("delta", {})
                    if delta.get("type") == "text_delta":
                        t = delta.get("text", "")
                        if t:
                            extracted.append(t)
                elif ev.get("type") == "result" and ev.get("result"):
                    extracted.append(ev["result"].strip())
            except (json.JSONDecodeError, KeyError):
                pass
        else:
            extracted.append(line)

    return "\n".join(extracted).strip() if extracted else None


def extract_result_from_stream_lines(stdout_lines: list[str]) -> str:
    """Extract the final result text from a list of stream-json lines.

    Priority:
    1. "result" event's result field
    2. Last "assistant" message with text content
    3. All text blocks from assistant messages (concatenated)
    4. Concatenated "content_block_delta" text fragments
    """
    # 1. Check for result event
    for line in reversed(stdout_lines):
        try:
            ev = json.loads(line)
            if ev.get("type") == "result" and ev.get("result"):
                return ev["result"]
        except (json.JSONDecodeError, KeyError):
            continue

    # 2. Try last assistant message with text
    for line in reversed(stdout_lines):
        try:
            ev = json.loads(line)
            if ev.get("type") == "assistant":
                content = ev.get("message", {}).get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            return text
        except (json.JSONDecodeError, KeyError):
            continue

    # 3. Collect ALL text blocks from all assistant messages (handles multi-turn)
    all_texts = []
    delta_texts = []
    for line in stdout_lines:
        try:
            ev = json.loads(line)
            if ev.get("type") == "assistant":
                content = ev.get("message", {}).get("content", [])
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "").strip()
                        if t:
                            all_texts.append(t)
            elif ev.get("type") == "content_block_delta":
                delta = ev.get("delta", {})
                if delta.get("type") == "text_delta":
                    t = delta.get("text", "")
                    if t:
                        delta_texts.append(t)
        except (json.JSONDecodeError, KeyError):
            continue

    # Prefer concatenated assistant texts (full blocks) over deltas
    if all_texts:
        return "\n\n".join(all_texts)

    # Fall back to concatenated deltas
    if delta_texts:
        return "".join(delta_texts).strip()

    return ""


def detect_infra_error(error_output: str) -> Optional[str]:
    """Check if test error output matches a known infrastructure error pattern.

    Returns the matched pattern string, or None if no infra error detected.
    """
    for pattern in INFRA_ERROR_PATTERNS:
        if re.search(pattern, error_output):
            return pattern
    return None


def recover_stale_runs(runs_dir, active_phases: set = None) -> list[dict]:
    """Reset any agent runs stuck in active phases.

    Returns list of recovered run summaries: [{"task_gid": ..., "old_phase": ..., "new_phase": "error"}]
    """
    if active_phases is None:
        active_phases = {"coding", "testing", "qa_review", "planning", "init", "queued"}

    recovered = []
    if not runs_dir.exists():
        return recovered

    for f in runs_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text())
            if data.get("phase") in active_phases:
                old_phase = data["phase"]
                data["phase"] = "error"
                data["error"] = f"Interrupted by container restart (was: {old_phase})"
                data["is_active"] = False
                f.write_text(json.dumps(data))
                recovered.append({
                    "task_gid": data.get("task_gid"),
                    "old_phase": old_phase,
                    "new_phase": "error",
                })
        except Exception:
            continue

    return recovered
