# CLI Backends

Each backend script follows the same contract:

- Reads one prompt from `stdin`
- Writes the model response to `stdout`
- Returns non-zero on failure

DockSentinel resolves backends by script name from this directory, e.g. backend `codex` maps to `llm-backends/codex.sh`.
