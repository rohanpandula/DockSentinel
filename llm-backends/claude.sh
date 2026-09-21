#!/usr/bin/env bash
set -euo pipefail

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI is not installed or not in PATH" >&2
  exit 1
fi

prompt="$(cat)"
# The prompt contains untrusted container logs: run non-agentically (no tools)
# when the installed CLI supports it. `exec` so a timeout kills the real process.
if claude --help 2>/dev/null | grep -q -- '--tools'; then
  exec claude -p --tools "" "$prompt"
fi
exec claude -p "$prompt"
