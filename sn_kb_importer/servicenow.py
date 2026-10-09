"""Minimal ServiceNow Table API client for knowledge articles."""

from __future__ import annotations

import re
from typing import Any

import requests

SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class ServiceNowError(Exception):
    """Raised when the ServiceNow API returns an error."""


def _escape_query_value(value: str) -> str:
    # In encoded queries '^' separates conditions; a literal caret is '^^'.
    return value.replace("^", "^^")


class ServiceNowClient:
    def __init__(
        self,
        instance: str,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        session: requests.Session | None = None,
        timeout: float = 30,
    ) -> None:
        if not instance.startswith("http"):
            instance = f"https://{instance}"
        if "." not in instance.split("//", 1)[1]:
            instance += ".service-now.com"  # allow bare instance names like "dev12345"
        self.base_url = instance.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        elif username and password:
            self.session.auth = (username, password)
        else:
            raise ValueError("Provide either an OAuth token or username and password")
        self.timeout = timeout

    def _request(self, method: str, table: str, sys_id: str | None = None, **kwargs: Any) -> Any:
        url = f"{self.base_url}/api/now/table/{table}"
        if sys_id:
            url += f"/{sys_id}"
        try:
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ServiceNowError(f"{method} {url} failed: {exc}") from exc
        if not resp.ok:
            detail = resp.text[:500]
            try:
                err = resp.json().get("error", {})
                detail = f"{err.get('message', '')} {err.get('detail', '')}".strip() or detail
            except ValueError:
                pass
            raise ServiceNowError(f"{method} {url} -> HTTP {resp.status_code}: {detail}")
        return resp.json()["result"]

    def query(self, table: str, query: str, fields: str = "sys_id", limit: int = 10) -> list[dict]:
        params = {"sysparm_query": query, "sysparm_fields": fields, "sysparm_limit": limit}
        return self._request("GET", table, params=params)

    def resolve_knowledge_base(self, kb: str) -> str:
        """Return the sys_id of a knowledge base given its sys_id or title."""
        if SYS_ID_RE.match(kb):
            return kb
        rows = self.query("kb_knowledge_base", f"title={_escape_query_value(kb)}", limit=2)
        if len(rows) != 1:
            raise ServiceNowError(f"Expected one knowledge base titled {kb!r}, found {len(rows)}")
        return rows[0]["sys_id"]

    def resolve_category(self, category: str, kb_sys_id: str) -> str:
        """Return the sys_id of a category given its sys_id or label."""
        if SYS_ID_RE.match(category):
            return category
        q = f"label={_escape_query_value(category)}^kb_knowledge_base={kb_sys_id}"
        rows = self.query("kb_category", q, limit=2)
        if len(rows) != 1:
            raise ServiceNowError(
                f"Expected one category labelled {category!r} in the knowledge base, found {len(rows)}"
            )
        return rows[0]["sys_id"]

    def find_article_by_text(self, kb_sys_id: str, marker: str) -> dict | None:
        """Find an article in the knowledge base whose body contains ``marker``."""
        q = f"kb_knowledge_base={kb_sys_id}^textLIKE{_escape_query_value(marker)}"
        rows = self.query("kb_knowledge", q, fields="sys_id,number,short_description", limit=1)
        return rows[0] if rows else None

    def create_article(self, fields: dict) -> dict:
        return self._request("POST", "kb_knowledge", json=fields)

    def update_article(self, sys_id: str, fields: dict) -> dict:
        return self._request("PATCH", "kb_knowledge", sys_id=sys_id, json=fields)

    def article_url(self, sys_id: str) -> str:
        return f"{self.base_url}/kb_knowledge.do?sys_id={sys_id}"
