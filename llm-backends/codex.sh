#!/usr/bin/env bash
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI is not installed or not in PATH" >&2
  exit 1
fi

prompt="$(cat)"
out_file="$(mktemp)"
trap 'rm -f "$out_file"' EXIT

codex exec \
  --skip-git-repo-check \
  --ephemeral \
  --sandbox read-only \
  --output-last-message "$out_file" \
  "$prompt" >/dev/null

cat "$out_file"
