from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


# Environment handed to CLI backends. The prompt contains attacker-influenced
# container logs and the CLIs are tool-capable agents, so they must not see the
# app's own secrets (SECRET_KEY, DATABASE_URL, TELEGRAM_*, BASIC_AUTH_*, ...).
# Only what a CLI needs to run and authenticate is passed through.
_ENV_PASSTHROUGH_EXACT = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "LANG", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "TZ", "NODE_OPTIONS", "NO_COLOR",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT",
})
_ENV_PASSTHROUGH_PREFIXES = ("XDG_", "OLLAMA_", "CLAUDE_", "CODEX_", "GEMINI_", "DOCKSENTINEL_CLI_")
_ENV_EXTRA_VAR = "DOCKSENTINEL_CLI_ENV_PASSTHROUGH"  # comma-separated extra names


def build_backend_env(source: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    extra = {name.strip() for name in (source.get(_ENV_EXTRA_VAR) or "").split(",") if name.strip()}
    env: dict[str, str] = {}
    for key, value in source.items():
        if key in _ENV_PASSTHROUGH_EXACT or key in extra or key.startswith(_ENV_PASSTHROUGH_PREFIXES):
            env[key] = value
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


@dataclass(slots=True)
class CLIBackendResult:
    content: str
    backend: str
    latency_ms: int


class CLIBackendRunner:
    _BACKEND_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

    def __init__(self, backends_dir: str | Path, max_concurrent_calls: int = 1) -> None:
        self.backends_dir = Path(backends_dir)
        self.max_concurrent_calls = max(1, max_concurrent_calls)
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent_calls)

    def _resolve_script(self, backend: str) -> Path:
        candidate = backend.strip()
        if not self._BACKEND_NAME_RE.match(candidate):
            raise RuntimeError("invalid backend name")
        script = self.backends_dir / f"{candidate}.sh"
        if not script.exists():
            raise RuntimeError(f"backend script not found: {script}")
        if not os.access(script, os.X_OK):
            raise RuntimeError(f"backend script is not executable: {script}")
        return script

    @staticmethod
    def _run_script(script: Path, prompt: str, timeout: int, env: dict[str, str]) -> subprocess.CompletedProcess:
        """Run the wrapper in its own process group so a timeout kills the real
        CLI too (subprocess.run's timeout only kills the bash wrapper, leaving
        claude/gemini/codex running — and still spending tokens)."""
        proc = subprocess.Popen(
            [str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.wait(timeout=5)
            raise
        return subprocess.CompletedProcess([str(script)], proc.returncode, stdout, stderr)

    def run(
        self,
        *,
        backend: str,
        prompt: str,
        timeout_seconds: int,
        max_retries: int,
    ) -> CLIBackendResult:
        script = self._resolve_script(backend)
        effective_timeout = max(1, int(timeout_seconds))
        retries = max(0, int(max_retries))
        last_error: str | None = None

        for _ in range(retries + 1):
            acquired = self._semaphore.acquire(timeout=effective_timeout + 5)
            if not acquired:
                last_error = "cli backend call queue timeout (single-call lock busy)"
                continue

            started = time.monotonic()
            try:
                env = build_backend_env()
                env["DOCKSENTINEL_BACKEND"] = backend
                completed = self._run_script(script, prompt, effective_timeout, env)
            except subprocess.TimeoutExpired:
                last_error = f"backend '{backend}' timed out after {effective_timeout}s"
                continue
            finally:
                self._semaphore.release()

            latency_ms = int((time.monotonic() - started) * 1000)
            if completed.returncode != 0:
                stderr = (completed.stderr or "").strip()
                stdout = (completed.stdout or "").strip()
                last_error = stderr or stdout or f"backend '{backend}' failed with exit code {completed.returncode}"
                continue

            response = (completed.stdout or "").strip()
            if not response:
                last_error = f"backend '{backend}' returned empty output"
                continue

            return CLIBackendResult(content=response, backend=backend, latency_ms=latency_ms)

        raise RuntimeError(last_error or "cli backend failed")

