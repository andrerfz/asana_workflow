#!/usr/bin/env bash
# Setup Claude Code agent auth token for headless Docker container.
# Generates an OAuth token via `claude setup-token` and saves it to .env.
#
# Usage: ./scripts/setup-agent.sh   (or: make setup-agent)
set -euo pipefail

ENV_FILE="${1:-.env}"
TMPFILE=$(mktemp /tmp/claude-token.XXXXXX)
LOGFILE=$(mktemp /tmp/claude-token-log.XXXXXX)

cleanup() { rm -f "$TMPFILE" "$LOGFILE"; }
trap cleanup EXIT

# --- Pre-checks ---
if ! command -v claude &>/dev/null; then
  echo "  ✗ Claude Code CLI not found."
  echo "  Install: npm install -g @anthropic-ai/claude-code"
  exit 1
fi

if ! claude auth status &>/dev/null; then
  echo "  ✗ Not logged in to Claude Code."
  echo "  Run: claude login"
  exit 1
fi

echo ""
echo "  Generating OAuth token (valid 1 year)..."
echo ""

# `claude setup-token` uses Ink (React TUI) which requires a PTY.
# Use `expect` to allocate a real PTY and capture output to a log file.
if command -v expect &>/dev/null; then
  expect -c "
    log_file $LOGFILE
    spawn claude setup-token
    set timeout 30
    expect {
      \"Store this token\" {}
      \"token\" { exp_continue }
      timeout { puts \"TIMEOUT\" }
      eof {}
    }
    # Give Ink a moment to finish rendering
    sleep 1
    expect eof
  " >/dev/null 2>&1 || true
else
  # Fallback: try `script` (less reliable but available everywhere).
  # macOS and Linux have different `script` syntax.
  if [[ "$(uname)" == "Darwin" ]]; then
    script -q "$LOGFILE" bash -c 'claude setup-token; exit 0' 2>/dev/null || true
  else
    script -qc "claude setup-token" "$LOGFILE" 2>/dev/null || true
  fi
fi

# --- Token extraction ---
# Ink renders the token across multiple terminal lines with ANSI escape codes
# and cursor movement sequences between fragments. Strategy:
#   1. Strip ANSI sequences but keep \r as line delimiters
#   2. Starting from the sk-ant-oat line, grab it and continuation lines
#      (lines that are purely [A-Za-z0-9_-]+, i.e. token fragments)
#   3. Concatenate the fragments into the full token
TOKEN=$(
  cat "$LOGFILE" \
    | sed 's/\x1b\[[0-9;]*[a-zA-Z]//g' \
    | sed 's/\x1b\][^\x07]*\x07//g' \
    | tr '\r' '\n' \
    | sed -n '/sk-ant-oat/,/[^A-Za-z0-9_-]/p' \
    | grep -oE 'sk-ant-oat[A-Za-z0-9_-]+|^[A-Za-z0-9_-]+$' \
    | tr -d '\n'
)

if [ -z "$TOKEN" ]; then
  echo "  ✗ Could not extract token automatically."
  echo ""
  echo "  Run this manually:"
  echo "    claude setup-token"
  echo ""
  echo "  Then paste the token into $ENV_FILE:"
  echo "    CLAUDE_CODE_OAUTH_TOKEN=<your-token>"
  exit 1
fi

# Validate token length (they're typically 90+ chars)
if [ ${#TOKEN} -lt 80 ]; then
  echo "  ⚠ Token looks short (${#TOKEN} chars). It may be truncated."
  echo "  If auth fails, run 'claude setup-token' manually and paste into $ENV_FILE."
fi

echo "  Token: ${TOKEN:0:20}...${TOKEN: -10} (${#TOKEN} chars)"

# Save to .env
if grep -q '^CLAUDE_CODE_OAUTH_TOKEN=' "$ENV_FILE" 2>/dev/null; then
  # Use a temp file for portable sed -i
  sed "s|^CLAUDE_CODE_OAUTH_TOKEN=.*|CLAUDE_CODE_OAUTH_TOKEN=$TOKEN|" "$ENV_FILE" > "$TMPFILE"
  mv "$TMPFILE" "$ENV_FILE"
else
  echo "" >> "$ENV_FILE"
  echo "# Claude Code CLI OAuth token for headless auth (valid 1 year)" >> "$ENV_FILE"
  echo "CLAUDE_CODE_OAUTH_TOKEN=$TOKEN" >> "$ENV_FILE"
fi

echo ""
echo "  ✓ Token saved to $ENV_FILE"
echo "  ✓ Run 'make recreate' to apply"
echo ""
