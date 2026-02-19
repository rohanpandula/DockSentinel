#!/usr/bin/env bash
set -euo pipefail

if ! command -v gemini >/dev/null 2>&1; then
  echo "gemini CLI is not installed or not in PATH" >&2
  exit 1
fi

prompt="$(cat)"
gemini -p "$prompt"
