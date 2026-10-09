"""Turn a raw HTML page into clean, article-ready HTML."""

from __future__ import annotations

import html
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, Tag

# kb_knowledge.short_description is a 160 character field out of the box.
SHORT_DESCRIPTION_MAX = 160

# Elements dropped together with their content.
DROP_TAGS = {
    "script", "style", "noscript", "iframe", "object", "embed", "form", "input",
    "button", "select", "textarea", "nav", "header", "footer", "aside", "svg",
    "canvas", "template", "link", "meta",
}

# Elements kept in the article; anything else is unwrapped (content kept).
ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "code", "dd", "del", "div",
    "dl", "dt", "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "pre", "s", "samp",
    "small", "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot",
    "th", "thead", "tr", "u", "ul",
}

ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "ol": {"start"},
}

URL_ATTRS = {"href", "src"}
SAFE_SCHEMES = {"http", "https", "mailto"}


@dataclass
class Article:
    title: str
    body_html: str
    description: str
    source_url: str


def _first_meta(soup: BeautifulSoup, *selectors: str) -> str:
    for sel in selectors:
        tag = soup.select_one(sel)
        if tag and tag.get("content", "").strip():
            return tag["content"].strip()
    return ""


def _find_title(soup: BeautifulSoup) -> str:
    title = _first_meta(soup, 'meta[property="og:title"]', 'meta[name="twitter:title"]')
    if not title and soup.title and soup.title.string:
        title = soup.title.string
    if not title:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else ""
    return " ".join(title.split())


def _find_content_root(soup: BeautifulSoup, selector: str | None) -> Tag:
    if selector:
        node = soup.select_one(selector)
        if node is None:
            raise ValueError(f"CSS selector {selector!r} matched nothing")
        return node
    for sel in ("article", "main", '[role="main"]', "#content", ".content"):
        node = soup.select_one(sel)
        if node and node.get_text(strip=True):
            return node
    return soup.body or soup


def _sanitize(root: Tag, base_url: str) -> None:
    for comment in root.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in root.find_all(DROP_TAGS):
        tag.decompose()

    for tag in root.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        allowed = ALLOWED_ATTRS.get(tag.name, set())
        for attr in list(tag.attrs):
            if attr not in allowed:
                del tag[attr]
                continue
            if attr in URL_ATTRS:
                absolute = urljoin(base_url, tag[attr].strip())
                if urlparse(absolute).scheme not in SAFE_SCHEMES:
                    del tag[attr]
                else:
                    tag[attr] = absolute

    # Remove images with no usable source and empty wrapper elements.
    for img in root.find_all("img"):
        if not img.get("src"):
            img.decompose()
    for tag in reversed(root.find_all(["div", "span", "p"])):
        if not tag.get_text(strip=True) and not tag.find(["img", "br", "hr", "table"]):
            tag.decompose()


def extract_article(
    page_html: str,
    source_url: str,
    selector: str | None = None,
    title_override: str | None = None,
) -> Article:
    soup = BeautifulSoup(page_html, "html.parser")
    title = title_override or _find_title(soup) or source_url
    description = _first_meta(
        soup, 'meta[name="description"]', 'meta[property="og:description"]'
    )

    root = _find_content_root(soup, selector)
    _sanitize(root, source_url)
    body = "".join(str(child) for child in root.children).strip()
    if not BeautifulSoup(body, "html.parser").get_text(strip=True):
        raise ValueError(f"No readable content found at {source_url}")

    return Article(
        title=_truncate(title, SHORT_DESCRIPTION_MAX),
        body_html=body,
        description=description,
        source_url=source_url,
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def source_footer(source_url: str) -> str:
    """Attribution paragraph appended to every article.

    Also used as a marker to find articles previously imported from a URL.
    """
    escaped = html.escape(source_url, quote=True)
    return f'<p class="kb-source">Source: <a href="{escaped}">{escaped}</a></p>'
