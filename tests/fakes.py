"""Tiny stand-in for requests.Session used by the tests."""

import json as jsonlib

import requests


class FakeResponse:
    def __init__(self, status=200, body="", headers=None, json_body=None):
        self.status_code = status
        if json_body is not None:
            body = jsonlib.dumps(json_body)
        self.text = body
        self.content = body.encode()
        self.headers = headers or {}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    ok = property(lambda self: self.status_code < 400)
    is_redirect = property(lambda self: self.status_code in (301, 302, 303, 307, 308))

    def json(self):
        return jsonlib.loads(self.text)

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession(requests.Session):
    """Routes requests to a handler ``(method, url, kwargs) -> FakeResponse``."""

    def __init__(self, handler):
        super().__init__()
        self.handler = handler
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)
