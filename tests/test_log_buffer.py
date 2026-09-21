from __future__ import annotations

from app.services.log_buffer import LogBuffer


def test_log_buffer_flushes_on_keyword_hit():
    buffer = LogBuffer(max_input_chars=1000, max_input_tokens=200, reserved_output_tokens=50)
    chunks = buffer.add_line("abc", "all good", keyword_hit=False)
    assert chunks == []

    chunks = buffer.add_line("abc", "fatal error found", keyword_hit=True)
    assert len(chunks) == 1
    assert "fatal error found" in chunks[0].text


def test_log_buffer_flushes_on_max_chars():
    buffer = LogBuffer(max_input_chars=20, max_input_tokens=9999, reserved_output_tokens=50)
    chunks = buffer.add_line("abc", "1234567890", keyword_hit=False)
    assert chunks == []
    chunks = buffer.add_line("abc", "1234567890", keyword_hit=False)
    assert len(chunks) == 1


def test_log_buffer_flushes_on_window_expiry():
    buffer = LogBuffer(max_input_chars=1000, max_input_tokens=9999, reserved_output_tokens=50, flush_window_seconds=0)
    chunks = buffer.add_line("abc", "line-one", keyword_hit=False)
    assert chunks == []

    chunks = buffer.add_line("abc", "line-two", keyword_hit=False)
    assert len(chunks) == 1
    assert "line-one" in chunks[0].text


def test_log_buffer_keyword_delayed_flush():
    """With keyword_flush_delay_lines=3, buffer waits for 3 more lines after keyword."""
    buffer = LogBuffer(
        max_input_chars=10000,
        max_input_tokens=9999,
        reserved_output_tokens=50,
        keyword_flush_delay_lines=3,
    )
    # Keyword hit — should NOT flush yet
    chunks = buffer.add_line("abc", "fatal error found", keyword_hit=True)
    assert chunks == []

    # Lines 1 and 2 after keyword — still no flush
    chunks = buffer.add_line("abc", "context line 1", keyword_hit=False)
    assert chunks == []
    chunks = buffer.add_line("abc", "context line 2", keyword_hit=False)
    assert chunks == []

    # Line 3 after keyword — should flush now
    chunks = buffer.add_line("abc", "context line 3", keyword_hit=False)
    assert len(chunks) == 1
    assert "fatal error found" in chunks[0].text
    assert "context line 3" in chunks[0].text


def test_log_buffer_keyword_delay_zero_is_immediate():
    """With keyword_flush_delay_lines=0, behavior matches legacy (immediate flush)."""
    buffer = LogBuffer(
        max_input_chars=10000,
        max_input_tokens=9999,
        reserved_output_tokens=50,
        keyword_flush_delay_lines=0,
    )
    chunks = buffer.add_line("abc", "fatal error found", keyword_hit=True)
    assert len(chunks) == 1


# --- REVIEW item 12 / track-b additions -------------------------------------
import threading
from datetime import timedelta

from app.services.log_buffer import _BufferState, is_continuation_line
from app.time_utils import utcnow_naive


def test_flush_pops_state_and_drop_container_discards():
    buffer = LogBuffer(max_input_chars=1000, max_input_tokens=9999, reserved_output_tokens=50)
    buffer.add_line("abc", "hello", keyword_hit=False)
    assert "abc" in buffer._buffers
    chunk = buffer.flush_container("abc")
    assert chunk is not None and "hello" in chunk.text
    assert "abc" not in buffer._buffers  # popped, not re-inserted empty
    assert buffer.flush_container("abc") is None

    buffer.add_line("xyz", "quiet", keyword_hit=False)
    buffer.drop_container("xyz")
    assert "xyz" not in buffer._buffers
    assert buffer.flush_container("xyz") is None


def test_add_line_is_thread_safe():
    buffer = LogBuffer(max_input_chars=10**9, max_input_tokens=10**9, reserved_output_tokens=50, flush_window_seconds=3600)
    n_threads, per_thread = 8, 500

    def worker(i):
        for j in range(per_thread):
            buffer.add_line("shared", f"t{i}-{j}", keyword_hit=False)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    chunk = buffer.flush_container("shared")
    assert chunk is not None
    assert chunk.text.count("\n") == n_threads * per_thread
    assert chunk.input_chars == len(chunk.text)


def test_running_token_estimate_matches_exact_and_is_incremental(monkeypatch):
    buffer = LogBuffer(max_input_chars=10**6, max_input_tokens=10**6, reserved_output_tokens=50, flush_window_seconds=3600)
    calls = []
    orig = buffer.estimate_tokens

    def spy(text):
        calls.append(len(text))
        return orig(text)

    monkeypatch.setattr(buffer, "estimate_tokens", spy)
    for i in range(50):
        buffer.add_line("abc", "x" * 40, keyword_hit=False)
    # No whole-buffer estimate per line (that was the O(n^2) path).
    assert calls == []
    state = buffer._buffers["abc"]
    assert state.tokens == buffer.estimate_tokens("".join(state.lines))
    chunk = buffer.flush_container("abc")
    assert chunk.estimated_tokens == state.tokens


def test_token_limit_flush_uses_running_estimate():
    # 40 chars/line -> 10 tokens/line; limit 25 tokens -> flush on 3rd line.
    buffer = LogBuffer(max_input_chars=10**6, max_input_tokens=25, reserved_output_tokens=50, flush_window_seconds=3600)
    assert buffer.add_line("abc", "x" * 39, keyword_hit=False) == []
    assert buffer.add_line("abc", "x" * 39, keyword_hit=False) == []
    assert len(buffer.add_line("abc", "x" * 39, keyword_hit=False)) == 1


def test_flush_idle_flushes_primed_after_window_and_others_after_double_window():
    buffer = LogBuffer(
        max_input_chars=10000, max_input_tokens=9999, reserved_output_tokens=50,
        flush_window_seconds=15, keyword_flush_delay_lines=5,
    )
    assert buffer.add_line("err", "fatal error found", keyword_hit=True, container_name="web") == []
    assert buffer.add_line("quiet", "just chatter", keyword_hit=False, container_name="db") == []
    now = utcnow_naive()

    assert buffer.flush_idle(now=now + timedelta(seconds=5)) == []
    chunks = buffer.flush_idle(now=now + timedelta(seconds=16))
    assert [c.container_id for c in chunks] == ["err"]
    assert chunks[0].container_name == "web"
    assert "fatal error found" in chunks[0].text
    assert "err" not in buffer._buffers

    assert buffer.flush_idle(now=now + timedelta(seconds=20)) == []
    chunks = buffer.flush_idle(now=now + timedelta(seconds=31))
    assert [c.container_id for c in chunks] == ["quiet"]
    assert chunks[0].container_name == "db"
    assert buffer.flush_idle(now=now + timedelta(seconds=60)) == []


def test_is_continuation_line_patterns():
    for line in ["    foo()", "\tat com.example.Foo.bar(Foo.java:1)", "at com.x.Y", 'File "x.py", line 3',
                 "Traceback (most recent call last):", "Caused by: java.io.IOException", "... 12 more"]:
        assert is_continuation_line(line), line
    for line in ["ValueError: boom", "INFO ok", "attention: fine", "", "Filesystem full"]:
        assert not is_continuation_line(line), line


def test_python_traceback_not_split_by_keyword_delay():
    buffer = LogBuffer(max_input_chars=10000, max_input_tokens=9999, reserved_output_tokens=50, keyword_flush_delay_lines=2)
    tb = [
        ("Traceback (most recent call last):", True),
        ('  File "/app/main.py", line 10, in <module>', False),
        ("    main()", False),
        ('  File "/app/main.py", line 7, in main', False),
        ("    raise ValueError('boom')", False),
        ("ValueError: boom", False),
    ]
    for line, hit in tb:
        assert buffer.add_line("py", line, keyword_hit=hit) == [], line
    # "ValueError: boom" was context line 1; the next normal line is line 2 -> flush.
    chunks = buffer.add_line("py", "INFO next request", keyword_hit=False)
    assert len(chunks) == 1
    text = chunks[0].text
    assert "Traceback (most recent call last):" in text
    assert "ValueError: boom" in text
    assert "INFO next request" in text


def test_java_stack_trace_delays_flush_until_normal_line():
    buffer = LogBuffer(max_input_chars=10000, max_input_tokens=9999, reserved_output_tokens=50, keyword_flush_delay_lines=1)
    trace = [
        ("Exception in thread \"main\" java.lang.RuntimeException: db down", True),
        ("\tat com.example.Repo.load(Repo.java:42)", False),
        ("\tat com.example.Main.main(Main.java:9)", False),
        ("Caused by: java.net.ConnectException: Connection refused", True),
        ("\tat java.base/sun.nio.ch.Net.connect(Net.java:579)", False),
        ("\t... 2 more", False),
    ]
    for line, hit in trace:
        assert buffer.add_line("jv", line, keyword_hit=hit) == [], line
    chunks = buffer.add_line("jv", "INFO server still up", keyword_hit=False)
    assert len(chunks) == 1
    assert "Caused by" in chunks[0].text and "... 2 more" in chunks[0].text


def test_java_stack_trace_delay_zero_flushes_on_keyword_line():
    """delay=0 keeps legacy immediate flush on the keyword line itself."""
    buffer = LogBuffer(max_input_chars=10000, max_input_tokens=9999, reserved_output_tokens=50, keyword_flush_delay_lines=0)
    assert len(buffer.add_line("jv", "ERROR boom", keyword_hit=True)) == 1


def test_continuation_still_bounded_by_size():
    buffer = LogBuffer(max_input_chars=60, max_input_tokens=9999, reserved_output_tokens=50, keyword_flush_delay_lines=3)
    buffer.add_line("c", "ERROR start", keyword_hit=True)
    chunks = []
    for _ in range(10):
        chunks += buffer.add_line("c", "\tat com.example.Deep.frame(Deep.java:1)", keyword_hit=False)
    assert chunks  # size limit still forces flushes mid-trace


def test_buffer_state_default_has_no_container_name():
    assert _BufferState().container_name is None
