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
