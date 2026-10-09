import pytest

from sn_kb_importer.extractor import extract_article, source_footer

PAGE = """
<html><head>
  <title>Fallback title</title>
  <meta property="og:title" content="Reset   your password">
  <meta name="description" content="How to reset a password.">
  <script>alert(1)</script>
</head><body>
  <header><nav><a href="/">Home</a></nav></header>
  <main>
    <h1 class="hero" onclick="evil()">Reset your password</h1>
    <!-- comment -->
    <p style="color:red">Go to <a href="/settings?x=1" onclick="x()">settings</a>.</p>
    <p><a href="javascript:alert(1)">bad link</a></p>
    <img src="img/step1.png" alt="Step 1" onerror="x()">
    <section><p>Inside a section</p></section>
    <div><span></span></div>
    <form><input name="q"></form>
  </main>
  <footer>Copyright</footer>
</body></html>
"""


def test_extracts_main_content_and_sanitizes():
    art = extract_article(PAGE, "https://example.com/help/reset")
    assert art.title == "Reset your password"
    assert art.description == "How to reset a password."
    body = art.body_html
    assert "<h1>Reset your password</h1>" in body
    assert 'href="https://example.com/settings?x=1"' in body
    assert 'src="https://example.com/help/img/step1.png"' in body
    assert "Inside a section" in body and "<section>" not in body
    for banned in ("script", "onclick", "onerror", "style=", "javascript:", "<form",
                   "Copyright", "Home", "comment", "<span>", "class="):
        assert banned not in body
    assert "<a>bad link</a>" in body


def test_title_fallbacks_and_truncation():
    art = extract_article("<html><body><h1>Only heading</h1><p>x</p></body></html>",
                          "https://e.com/a")
    assert art.title == "Only heading"
    long = "<title>" + "A" * 300 + "</title><p>text</p>"
    assert len(extract_article(long, "https://e.com/").title) == 160


def test_selector_and_override():
    html = "<body><div id='doc'><p>wanted</p></div><p>unwanted</p></body>"
    art = extract_article(html, "https://e.com/", selector="#doc", title_override="T")
    assert art.title == "T"
    assert "wanted" in art.body_html and "unwanted" not in art.body_html
    with pytest.raises(ValueError):
        extract_article(html, "https://e.com/", selector="#missing")


def test_empty_page_raises():
    with pytest.raises(ValueError):
        extract_article("<html><body><script>x</script></body></html>", "https://e.com/")


def test_source_footer_escapes():
    assert source_footer('https://e.com/?a=1&b="2"') == (
        '<p class="kb-source">Source: <a href="https://e.com/?a=1&amp;b=&quot;2&quot;">'
        "https://e.com/?a=1&amp;b=&quot;2&quot;</a></p>"
    )
