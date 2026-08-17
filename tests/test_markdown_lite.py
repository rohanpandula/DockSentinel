from __future__ import annotations

from app.web.markdown_lite import render_markdown


def test_headings_and_paragraphs():
    html = render_markdown("## Executive Summary\n\nAll quiet.\nSecond line.\n\n### Sub")
    assert "<h2>Executive Summary</h2>" in html
    assert "<p>All quiet. Second line.</p>" in html
    assert "<h3>Sub</h3>" in html


def test_lists_bold_italic_code():
    html = render_markdown("- **bold** item with `code`\n- *it*\n\n1. first\n2. second")
    assert "<ul>" in html and "</ul>" in html
    assert "<li><strong>bold</strong> item with <code>code</code></li>" in html
    assert "<li><em>it</em></li>" in html
    assert "<ol>" in html and "<li>first</li>" in html and "<li>second</li>" in html


def test_fenced_code_block_and_escaping():
    src = "```\ndocker ps <all>\n```\n\n<script>alert(1)</script> & **x<y**"
    html = render_markdown(src)
    assert "<pre><code>docker ps &lt;all&gt;</code></pre>" in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; <strong>x&lt;y</strong>" in html


def test_empty_and_none():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


def test_inline_code_protects_asterisks():
    html = render_markdown("use `a**b**c` here")
    assert "<code>a**b**c</code>" in html
    assert "<strong>" not in html
