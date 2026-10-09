import socket

import pytest

from sn_kb_importer.fetcher import FetchError, Fetcher

from .fakes import FakeResponse, FakeSession

HTML = {"Content-Type": "text/html; charset=utf-8"}


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    table = {"public.example": "93.184.216.34", "internal.example": "10.0.0.5"}

    def getaddrinfo(host, port, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table.get(host, "127.0.0.1"), 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def make_fetcher(routes, **kwargs):
    def handler(method, url, kw):
        return routes.get(url, FakeResponse(404))
    return Fetcher(session=FakeSession(handler), **kwargs)


def test_fetches_html_page():
    f = make_fetcher({"https://public.example/a": FakeResponse(200, "<p>hi</p>", HTML)})
    page = f.fetch("https://public.example/a")
    assert page.url == "https://public.example/a"
    assert page.html == "<p>hi</p>"


def test_follows_redirects_and_checks_each_hop():
    f = make_fetcher({
        "https://public.example/old": FakeResponse(301, headers={"Location": "/new"}),
        "https://public.example/new": FakeResponse(200, "<p>x</p>", HTML),
        "https://public.example/to-internal": FakeResponse(
            302, headers={"Location": "http://internal.example/"}),
    })
    assert f.fetch("https://public.example/old").url == "https://public.example/new"
    with pytest.raises(FetchError, match="non-public"):
        f.fetch("https://public.example/to-internal")


def test_rejects_private_hosts_unless_allowed():
    routes = {"http://internal.example/": FakeResponse(200, "<p>x</p>", HTML)}
    with pytest.raises(FetchError, match="non-public"):
        make_fetcher(routes).fetch("http://internal.example/")
    assert make_fetcher(routes, allow_private=True).fetch("http://internal.example/").html


@pytest.mark.parametrize("resp,match", [
    (FakeResponse(500), "HTTP 500"),
    (FakeResponse(200, "{}", {"Content-Type": "application/json"}), "Not an HTML"),
    (FakeResponse(200, "x" * 100, HTML), "larger than"),
])
def test_errors(resp, match):
    f = make_fetcher({"https://public.example/a": resp}, max_bytes=50)
    with pytest.raises(FetchError, match=match):
        f.fetch("https://public.example/a")


def test_rejects_non_http_scheme():
    with pytest.raises(FetchError, match="http"):
        make_fetcher({}).fetch("file:///etc/passwd")


def test_respects_robots_txt():
    routes = {
        "https://public.example/robots.txt": FakeResponse(200, "User-agent: *\nDisallow: /private"),
        "https://public.example/private/x": FakeResponse(200, "<p>x</p>", HTML),
    }
    with pytest.raises(FetchError, match="robots"):
        make_fetcher(routes).fetch("https://public.example/private/x")
    assert make_fetcher(routes, respect_robots=False).fetch("https://public.example/private/x")


def test_uses_meta_charset_when_header_has_none():
    body = '<meta charset="utf-8"><p>aqu\u00ed \u2013 gu\u00eda</p>'
    resp = FakeResponse(200, body, {"Content-Type": "text/html"})
    resp.encoding = "ISO-8859-1"  # what requests assumes for text/* without charset
    f = make_fetcher({"https://public.example/a": resp})
    assert "aqu\u00ed \u2013 gu\u00eda" in f.fetch("https://public.example/a").html
