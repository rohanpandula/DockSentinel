"""Tiny, dependency-free Markdown → HTML converter for LLM-generated reports.

Supports: ATX headings (#..######), unordered (-, *, +) and ordered (1.) lists,
fenced ``` code blocks, inline `code`, **bold**, *italic*, and paragraphs.
All text is HTML-escaped first, so model output can never inject markup.
"""
from __future__ import annotations

import re
from html import escape

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_FENCE = re.compile(r"^\s*```")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")


def _inline(text: str) -> str:
    """Escape, then apply inline code / bold / italic."""
    text = escape(text, quote=False)
    # Protect inline code from bold/italic substitution.
    codes: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        codes.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = _INLINE_CODE.sub(_stash, text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    for i, code in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", code)
    return text


def render_markdown(source: str | None) -> str:
    if not source:
        return ""

    out: list[str] = []
    paragraph: list[str] = []
    list_tag: str | None = None
    code: list[str] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append(f"<p>{_inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in source.splitlines():
        line = raw.rstrip("\n")

        if code is not None:
            if _FENCE.match(line):
                out.append(f"<pre><code>{escape(chr(10).join(code), quote=False)}</code></pre>")
                code = None
            else:
                code.append(line)
            continue

        if _FENCE.match(line):
            flush_paragraph()
            close_list()
            code = []
            continue

        if not line.strip():
            flush_paragraph()
            close_list()
            continue

        heading = _HEADING.match(line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = _BULLET.match(line)
        ordered = _ORDERED.match(line) if not bullet else None
        if bullet or ordered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            item = (bullet or ordered).group(1)  # type: ignore[union-attr]
            out.append(f"<li>{_inline(item)}</li>")
            continue

        # Continuation of a list item (indented text) stays inside the item.
        if list_tag and raw.startswith((" ", "\t")):
            out[-1] = out[-1][: -len("</li>")] + " " + _inline(line.strip()) + "</li>"
            continue

        close_list()
        paragraph.append(line.strip())

    if code is not None:  # unterminated fence
        out.append(f"<pre><code>{escape(chr(10).join(code), quote=False)}</code></pre>")
    flush_paragraph()
    close_list()
    return "\n".join(out)
