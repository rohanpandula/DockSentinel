#!/usr/bin/env bash
set -euo pipefail

if ! command -v claude >/dev/null 2>&1; then
  echo "claude CLI is not installed or not in PATH" >&2
  exit 1
fi

prompt="$(cat)"
claude -p "$prompt"
