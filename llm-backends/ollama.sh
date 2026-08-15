#!/usr/bin/env bash
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is not installed or not in PATH" >&2
  exit 1
fi

prompt="$(cat)"
model="${OLLAMA_MODEL:-llama3}"
exec ollama run "$model" "$prompt"
