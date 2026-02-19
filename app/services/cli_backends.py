from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


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
                env = os.environ.copy()
                env["DOCKSENTINEL_BACKEND"] = backend
                completed = subprocess.run(
                    [str(script)],
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=effective_timeout,
                    env=env,
                )
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

