"""Download publicly available HTML pages."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import UnicodeDammit

USER_AGENT = "sn-kb-importer/0.1 (+https://github.com/polluelo80/claudeTest)"
DEFAULT_TIMEOUT = 20
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5


class FetchError(Exception):
    """Raised when a page cannot be fetched."""


@dataclass
class FetchedPage:
    url: str  # final URL after redirects
    html: str


def _assert_public_host(url: str) -> None:
    """Reject URLs that resolve to private, loopback or link-local addresses.

    The tool is meant for *publicly available* pages; this stops it from being
    pointed at internal services (e.g. cloud metadata endpoints).
    """
    host = urlparse(url).hostname
    if not host:
        raise FetchError(f"URL has no host: {url}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Cannot resolve host {host!r}: {exc}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise FetchError(f"Refusing non-public address {ip} for host {host!r}")


class Fetcher:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        respect_robots: bool = True,
        allow_private: bool = False,
    ) -> None:
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.respect_robots = respect_robots
        self.allow_private = allow_private
        self._robots: dict[str, RobotFileParser | None] = {}

    def _check_url(self, url: str) -> None:
        if urlparse(url).scheme not in ("http", "https"):
            raise FetchError(f"Only http(s) URLs are supported: {url}")
        if not self.allow_private:
            _assert_public_host(url)

    def _robots_allows(self, url: str) -> bool:
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = self.session.get(origin + "/robots.txt", timeout=self.timeout)
                if resp.status_code >= 400:
                    parser = None  # no robots.txt -> everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except requests.RequestException:
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(USER_AGENT, url)

    def fetch(self, url: str) -> FetchedPage:
        current = url
        # Follow redirects manually so every hop is checked against the
        # public-address rule.
        for _ in range(MAX_REDIRECTS + 1):
            self._check_url(current)
            if self.respect_robots and not self._robots_allows(current):
                raise FetchError(f"Disallowed by robots.txt: {current}")
            try:
                resp = self.session.get(
                    current, timeout=self.timeout, stream=True, allow_redirects=False
                )
            except requests.RequestException as exc:
                raise FetchError(f"Request to {current} failed: {exc}") from exc
            if resp.is_redirect:
                location = resp.headers.get("Location", "")
                resp.close()
                current = urljoin(current, location)
                continue
            break
        else:
            raise FetchError(f"Too many redirects fetching {url}")

        with resp:
            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code} fetching {current}")
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype.lower():
                raise FetchError(f"Not an HTML page ({ctype or 'no content type'}): {current}")
            body = bytearray()
            for chunk in resp.iter_content(64 * 1024):
                body.extend(chunk)
                if len(body) > self.max_bytes:
                    raise FetchError(f"Page larger than {self.max_bytes} bytes: {current}")
        # Only trust a charset the server declared explicitly; otherwise let the
        # document's <meta charset> (or byte sniffing) decide. requests would
        # default text/html to ISO-8859-1, which garbles UTF-8 pages.
        declared = [] if "charset=" not in ctype.lower() else [resp.encoding]
        decoded = UnicodeDammit(bytes(body), declared, is_html=True).unicode_markup
        return FetchedPage(url=current, html=decoded or bytes(body).decode("utf-8", "replace"))
