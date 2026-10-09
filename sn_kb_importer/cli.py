"""Command line entry point: ``sn-kb-import``."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys

from .extractor import Article, extract_article, source_footer
from .fetcher import FetchError, Fetcher
from .servicenow import ServiceNowClient, ServiceNowError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sn-kb-import",
        description="Fetch public HTML pages and create ServiceNow knowledge articles from them.",
    )
    p.add_argument("urls", nargs="*", help="Page URLs to import")
    p.add_argument("-f", "--url-file", help="File with one URL per line ('#' starts a comment)")
    p.add_argument("--instance", default=os.environ.get("SN_INSTANCE"),
                   help="ServiceNow instance, e.g. dev12345 or https://acme.service-now.com [SN_INSTANCE]")
    p.add_argument("--user", default=os.environ.get("SN_USER"), help="Username [SN_USER]")
    p.add_argument("--password", default=os.environ.get("SN_PASSWORD"),
                   help="Password [SN_PASSWORD]; prefer the environment variable")
    p.add_argument("--token", default=os.environ.get("SN_TOKEN"),
                   help="OAuth bearer token, used instead of user/password [SN_TOKEN]")
    p.add_argument("--kb", default=os.environ.get("SN_KB"),
                   help="Knowledge base title or sys_id [SN_KB]")
    p.add_argument("--category", default=os.environ.get("SN_CATEGORY"),
                   help="Category label or sys_id within the knowledge base [SN_CATEGORY]")
    p.add_argument("--selector", help="CSS selector for the main content (default: auto-detect)")
    p.add_argument("--title", help="Override the article title (only with a single URL)")
    p.add_argument("--publish", action="store_true",
                   help="Set workflow_state to 'published' instead of 'draft'")
    p.add_argument("--on-duplicate", choices=("skip", "update", "create"), default="skip",
                   help="What to do when an article from the same URL exists (default: skip)")
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch and extract only; print the article payloads as JSON")
    p.add_argument("--ignore-robots", action="store_true", help="Do not consult robots.txt")
    p.add_argument("--allow-private", action="store_true",
                   help="Allow URLs that resolve to private/internal addresses")
    return p


def read_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.urls)
    if args.url_file:
        with open(args.url_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    urls.append(line)
    return urls


def article_fields(article: Article, kb_sys_id: str | None, category_sys_id: str | None,
                   publish: bool) -> dict:
    fields = {
        "short_description": article.title,
        "text": f"{article.body_html}\n{source_footer(article.source_url)}",
        "workflow_state": "published" if publish else "draft",
    }
    if article.description:
        fields["meta_description"] = article.description
    if kb_sys_id:
        fields["kb_knowledge_base"] = kb_sys_id
    if category_sys_id:
        fields["kb_category"] = category_sys_id
    return fields


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    urls = read_urls(args)
    if not urls:
        parser.error("no URLs given")
    if args.title and len(urls) > 1:
        parser.error("--title can only be used with a single URL")

    client = None
    kb_sys_id = category_sys_id = None
    if not args.dry_run:
        missing = [n for n, v in (("--instance", args.instance), ("--kb", args.kb)) if not v]
        if not (args.token or (args.user and args.password)):
            missing.append("--token or --user/--password")
        if missing:
            parser.error("missing required settings: " + ", ".join(missing))
        try:
            client = ServiceNowClient(args.instance, args.user, args.password, args.token)
            kb_sys_id = client.resolve_knowledge_base(args.kb)
            if args.category:
                category_sys_id = client.resolve_category(args.category, kb_sys_id)
        except ServiceNowError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    fetcher = Fetcher(respect_robots=not args.ignore_robots, allow_private=args.allow_private)
    failures = 0
    dry_run_output = []

    for url in urls:
        try:
            page = fetcher.fetch(url)
            article = extract_article(page.html, page.url, args.selector, args.title)
            fields = article_fields(article, kb_sys_id, category_sys_id, args.publish)

            if client is None:
                dry_run_output.append({"url": page.url, "fields": fields})
                continue

            existing = None
            if args.on_duplicate != "create":
                # The footer stores the URL HTML-escaped, so search for that form.
                existing = client.find_article_by_text(kb_sys_id, html.escape(page.url, quote=True))
            if existing and args.on_duplicate == "skip":
                print(f"SKIP    {url} -> already imported as {existing['number']}")
                continue
            if existing:
                record = client.update_article(existing["sys_id"], fields)
                action = "UPDATE "
            else:
                record = client.create_article(fields)
                action = "CREATE "
            print(f"{action} {url} -> {record['number']} {client.article_url(record['sys_id'])}")
        except (FetchError, ServiceNowError, ValueError) as exc:
            failures += 1
            print(f"FAIL    {url}: {exc}", file=sys.stderr)

    if args.dry_run:
        json.dump(dry_run_output, sys.stdout, indent=2, ensure_ascii=False)
        print()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
