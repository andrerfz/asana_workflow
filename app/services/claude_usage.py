"""Local, honest insights into Claude Code *subscription* usage, read from the
session files at ~/.claude/projects/**/*.jsonl.

The exact quota % shown by `/status` (e.g. "20% used, resets 4:49pm") comes from
the server endpoint /api/oauth/usage, which requires the `user:profile` OAuth
scope. The headless setup-token used here does NOT have that scope, and the
interactive token lives in the macOS Keychain (unreachable from the container).
So we do NOT fake a quota %. Instead we surface the same *local* breakdown the
CLI shows under "What's contributing to your limits usage?" — these are real
characteristics of the last 24h of usage on this machine, not a quota.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_WINDOW_HOURS = 24
_HIGH_CONTEXT = 150_000      # prompt size threshold for "long context"
_LONG_SESSION = timedelta(hours=8)
_PARALLEL_SLOT = timedelta(minutes=5)
_PARALLEL_MIN = 4            # N+ sessions active in the same slot = "parallel"
_CACHE_TTL = timedelta(seconds=60)
_cache: dict = {"at": None, "data": None}


def _projects_dir() -> Path:
    base = os.getenv("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(base) / "projects"


def _parse_ts(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _collect(since: datetime) -> list:
    """Deduplicated entries from recent session files. Each entry:
    {ts, tokens, context, session, sidechain}."""
    pdir = _projects_dir()
    if not pdir.exists():
        return []
    cutoff = since.timestamp()
    seen: set = set()
    out: list = []

    for jf in pdir.rglob("*.jsonl"):
        try:
            if jf.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        try:
            with jf.open("r", errors="ignore") as fh:
                for line in fh:
                    if '"usage"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    msg = d.get("message")
                    if not isinstance(msg, dict):
                        continue
                    u = msg.get("usage")
                    if not isinstance(u, dict):
                        continue
                    ts = _parse_ts(d.get("timestamp", ""))
                    if not ts or ts < since:
                        continue
                    key = f"{msg.get('id')}:{d.get('requestId')}"
                    if key in seen:
                        continue
                    seen.add(key)
                    inp = u.get("input_tokens") or 0
                    out_t = u.get("output_tokens") or 0
                    cw = u.get("cache_creation_input_tokens") or 0
                    cr = u.get("cache_read_input_tokens") or 0
                    out.append({
                        "ts": ts,
                        "tokens": inp + out_t + cw + cr,
                        "context": inp + cw + cr,   # prompt size for this call
                        "session": d.get("sessionId") or jf.stem,
                        "sidechain": bool(d.get("isSidechain")),
                    })
        except OSError:
            continue

    out.sort(key=lambda e: e["ts"])
    return out


def usage_insights() -> dict:
    now = datetime.now(timezone.utc)
    if _cache["at"] and now - _cache["at"] < _CACHE_TTL:
        return _cache["data"]

    since = now - timedelta(hours=_WINDOW_HOURS)
    entries = _collect(since)
    total = sum(e["tokens"] for e in entries) or 0

    insights: list = []
    if total:
        # Sessions active in each 5-min slot, for parallel detection.
        slots: dict = {}
        for e in entries:
            slot = int(e["ts"].timestamp() // _PARALLEL_SLOT.total_seconds())
            slots.setdefault(slot, set()).add(e["session"])

        # Session durations, for the long-session breakdown.
        span: dict = {}
        for e in entries:
            s = span.setdefault(e["session"], [e["ts"], e["ts"]])
            if e["ts"] < s[0]:
                s[0] = e["ts"]
            if e["ts"] > s[1]:
                s[1] = e["ts"]
        long_sessions = {sid for sid, (a, b) in span.items() if b - a >= _LONG_SESSION}

        # "Subagent-heavy" attributes the whole session that spawned subagents,
        # matching how the CLI reports it (not just the sidechain messages).
        subagent_sessions = {e["session"] for e in entries if e["sidechain"]}

        hi_ctx = sum(e["tokens"] for e in entries if e["context"] >= _HIGH_CONTEXT)
        longs = sum(e["tokens"] for e in entries if e["session"] in long_sessions)
        sub = sum(e["tokens"] for e in entries if e["session"] in subagent_sessions)
        par = sum(
            e["tokens"] for e in entries
            if len(slots.get(int(e["ts"].timestamp() // _PARALLEL_SLOT.total_seconds()), ())) >= _PARALLEL_MIN
        )

        def pct(x):
            return round(100 * x / total)

        insights = [
            {"key": "context", "label": ">150k context", "pct": pct(hi_ctx),
             "hint": "Longer sessions cost more even when cached — /compact mid-task."},
            {"key": "long", "label": "8h+ sessions", "pct": pct(longs),
             "hint": "Often background/loop sessions — continuous use adds up."},
            {"key": "parallel", "label": f"{_PARALLEL_MIN}+ in parallel", "pct": pct(par),
             "hint": "All sessions share one limit — queue if you don't need them at once."},
            {"key": "subagent", "label": "subagent-heavy", "pct": pct(sub),
             "hint": "Each subagent runs its own requests — spawn deliberately."},
        ]
        insights = [i for i in insights if i["pct"] > 0]
        insights.sort(key=lambda i: -i["pct"])

    data = {
        "tokens_24h": total,
        "sessions_24h": len({e["session"] for e in entries}),
        "insights": insights,
        "note": "Local estimate from this machine's sessions — not your Anthropic quota.",
    }
    _cache["at"] = now
    _cache["data"] = data
    return data
