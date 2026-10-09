import json
from urllib.parse import parse_qs, urlparse

import pytest

from sn_kb_importer import cli
from sn_kb_importer.fetcher import FetchedPage

from .fakes import FakeResponse, FakeSession

KB_ID = "a" * 32
CAT_ID = "c" * 32
PAGE_HTML = """<html><head><title>How to VPN</title>
<meta name="description" content="VPN setup"></head>
<body><article><h2>Steps</h2><p>Install the client.</p></article></body></html>"""


class StubFetcher:
    def __init__(self, **kwargs):
        pass

    def fetch(self, url):
        return FetchedPage(url=url, html=PAGE_HTML)


class FakeInstance:
    """Simulates the parts of the ServiceNow Table API the tool uses."""

    def __init__(self, existing=None):
        self.existing = existing or []
        self.created = []
        self.updated = []

    def __call__(self, method, url, kw):
        path = urlparse(url).path
        params = kw.get("params") or {}
        if method == "GET" and path.endswith("/kb_knowledge_base"):
            assert params["sysparm_query"] == "title=IT"
            return FakeResponse(json_body={"result": [{"sys_id": KB_ID}]})
        if method == "GET" and path.endswith("/kb_category"):
            assert params["sysparm_query"] == f"label=Network^kb_knowledge_base={KB_ID}"
            return FakeResponse(json_body={"result": [{"sys_id": CAT_ID}]})
        if method == "GET" and path.endswith("/kb_knowledge"):
            q = params["sysparm_query"]
            hits = [r for r in self.existing if q.split("textLIKE", 1)[1] in r["text"]]
            return FakeResponse(json_body={"result": hits[:1]})
        if method == "POST":
            self.created.append(kw["json"])
            return FakeResponse(201, json_body={"result": {"sys_id": "1" * 32, "number": "KB0010001"}})
        if method == "PATCH":
            self.updated.append((path.rsplit("/", 1)[1], kw["json"]))
            return FakeResponse(json_body={"result": {"sys_id": "e" * 32, "number": "KB0000001"}})
        return FakeResponse(404, json_body={"error": {"message": "not found"}})


@pytest.fixture
def instance(monkeypatch):
    inst = FakeInstance()
    monkeypatch.setattr(cli, "Fetcher", StubFetcher)
    real_init = cli.ServiceNowClient.__init__

    def init(self, *a, **k):
        real_init(self, *a, session=FakeSession(inst), **k)

    monkeypatch.setattr(cli.ServiceNowClient, "__init__", init)
    return inst


BASE_ARGS = ["--instance", "dev123", "--user", "u", "--password", "p", "--kb", "IT"]


def test_creates_article(instance, capsys):
    rc = cli.main(BASE_ARGS + ["--category", "Network", "https://docs.example/vpn?a=1&b=2"])
    assert rc == 0
    [fields] = instance.created
    assert fields["short_description"] == "How to VPN"
    assert fields["kb_knowledge_base"] == KB_ID
    assert fields["kb_category"] == CAT_ID
    assert fields["workflow_state"] == "draft"
    assert fields["meta_description"] == "VPN setup"
    assert "<h2>Steps</h2>" in fields["text"]
    assert 'href="https://docs.example/vpn?a=1&amp;b=2"' in fields["text"]
    out = capsys.readouterr().out
    assert "KB0010001" in out and "https://dev123.service-now.com/kb_knowledge.do?sys_id=" in out


def test_duplicate_handling(instance, capsys):
    url = "https://docs.example/vpn?a=1&b=2"
    cli.main(BASE_ARGS + [url])
    instance.existing.append({"sys_id": "e" * 32, "number": "KB0000001",
                              "text": instance.created[0]["text"]})

    assert cli.main(BASE_ARGS + [url]) == 0
    assert "SKIP" in capsys.readouterr().out and len(instance.created) == 1

    assert cli.main(BASE_ARGS + ["--on-duplicate", "update", "--publish", url]) == 0
    [(sys_id, fields)] = instance.updated
    assert sys_id == "e" * 32 and fields["workflow_state"] == "published"

    assert cli.main(BASE_ARGS + ["--on-duplicate", "create", url]) == 0
    assert len(instance.created) == 2


def test_dry_run_needs_no_credentials(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "Fetcher", StubFetcher)
    url_file = tmp_path / "urls.txt"
    url_file.write_text("# comment\nhttps://a.example/1\n\nhttps://a.example/2  # trailing\n")
    assert cli.main(["--dry-run", "-f", str(url_file)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [d["url"] for d in data] == ["https://a.example/1", "https://a.example/2"]
    assert "kb_knowledge_base" not in data[0]["fields"]


def test_missing_settings_is_usage_error(monkeypatch):
    for var in ("SN_INSTANCE", "SN_USER", "SN_PASSWORD", "SN_TOKEN", "SN_KB"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["https://a.example/"])
    assert exc.value.code == 2


def test_fetch_failure_returns_nonzero(instance, monkeypatch, capsys):
    class Failing(StubFetcher):
        def fetch(self, url):
            raise cli.FetchError("boom")

    monkeypatch.setattr(cli, "Fetcher", Failing)
    assert cli.main(BASE_ARGS + ["https://a.example/"]) == 1
    assert "FAIL" in capsys.readouterr().err
