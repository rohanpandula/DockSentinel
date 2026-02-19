from __future__ import annotations

import threading
import time

from app.services.cli_backends import CLIBackendRunner


def _write_backend_script(path, body: str):
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_cli_backend_runner_executes_backend(tmp_path):
    backends_dir = tmp_path / "llm-backends"
    backends_dir.mkdir()
    script = backends_dir / "codex.sh"
    _write_backend_script(
        script,
        "#!/usr/bin/env bash\nset -euo pipefail\ncat\n",
    )

    runner = CLIBackendRunner(backends_dir=backends_dir, max_concurrent_calls=1)
    result = runner.run(backend="codex", prompt="hello", timeout_seconds=5, max_retries=0)

    assert result.content == "hello"
    assert result.backend == "codex"
    assert result.latency_ms >= 0


def test_cli_backend_runner_single_concurrency_lock(tmp_path):
    backends_dir = tmp_path / "llm-backends"
    backends_dir.mkdir()
    script = backends_dir / "codex.sh"
    _write_backend_script(
        script,
        "#!/usr/bin/env bash\nset -euo pipefail\ncat >/dev/null\nsleep 0.35\necho done\n",
    )

    runner = CLIBackendRunner(backends_dir=backends_dir, max_concurrent_calls=1)
    results: list[str] = []
    errors: list[str] = []

    def worker():
        try:
            outcome = runner.run(backend="codex", prompt="x", timeout_seconds=5, max_retries=0)
            results.append(outcome.content)
        except Exception as exc:  # pragma: no cover - defensive for thread visibility
            errors.append(str(exc))

    started = time.monotonic()
    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    elapsed = time.monotonic() - started

    assert errors == []
    assert sorted(results) == ["done", "done"]
    # If calls were concurrent this would be ~0.35s. With lock we expect serialized runtime.
    assert elapsed >= 0.6
