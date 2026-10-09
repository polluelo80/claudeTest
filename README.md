# sn-kb-importer

A command line tool that downloads publicly available HTML pages, extracts their
main content, and creates **knowledge articles** (`kb_knowledge`) in a ServiceNow
instance through the REST Table API.

## What it does

1. **Fetches** each URL over http(s): it reads `robots.txt`, follows up to 5
   redirects, and refuses non-HTML responses, pages over 5 MB, and hosts that
   resolve to private, loopback or link-local addresses.
2. **Extracts** the article. The title comes from `og:title`, then `<title>`,
   then the first `<h1>`, cut to 160 characters. The body comes from `<article>`,
   then `<main>`, then `[role=main]`, then `#content`/`.content`, then `<body>`,
   unless you pass `--selector`.
3. **Sanitizes** the HTML. It removes scripts, styles, navigation, headers,
   footers, forms, iframes and comments. It keeps only an allowlist of tags and
   attributes and drops `javascript:` and other unsafe links. Relative links and
   images become absolute URLs.
4. **Creates** the article in the chosen knowledge base (and category, if
   given) as a `draft`, or as `published` with `--publish`. A
   `Source: <url>` line is added to every article. The tool also uses that line
   to spot pages it has already imported.

## Install

```bash
pip install .            # or: pip install -e '.[test]' for development
```

## Usage

```bash
export SN_INSTANCE=dev12345            # or https://acme.service-now.com
export SN_USER=kb.importer
export SN_PASSWORD='…'                 # or: export SN_TOKEN=<OAuth bearer token>
export SN_KB="IT"                      # knowledge base title or sys_id

# Preview what would be created (needs no ServiceNow access)
sn-kb-import --dry-run https://example.com/help/reset-password

# Import a single page into a category
sn-kb-import --category "Network" https://example.com/help/vpn

# Import a list of URLs (one per line, '#' comments allowed) and update
# articles that were imported from the same URLs before
sn-kb-import -f urls.txt --on-duplicate update
```

| Option | Description |
| --- | --- |
| `-f, --url-file` | Read URLs from a file |
| `--instance / --user / --password / --token` | Connection settings (or `SN_*` environment variables) |
| `--kb` | Knowledge base title or sys_id (`SN_KB`) |
| `--category` | Category label or sys_id in that knowledge base (`SN_CATEGORY`) |
| `--selector` | CSS selector for the main content when auto-detection picks the wrong part |
| `--title` | Override the title (single URL only) |
| `--publish` | Create as `published` instead of `draft` |
| `--on-duplicate {skip,update,create}` | What to do when the URL was already imported (default `skip`) |
| `--dry-run` | Print the article payloads as JSON and don't contact ServiceNow |
| `--ignore-robots` | Don't check `robots.txt` |
| `--allow-private` | Allow internal/private hosts (off by default) |

Exit code: `0` = every URL succeeded, `1` = at least one URL failed,
`2` = bad usage or configuration.

## ServiceNow requirements

- The account needs read access to `kb_knowledge_base` and `kb_category`, and
  read/create/write access to `kb_knowledge`. The `knowledge` role plus the
  `rest_api_explorer`/web-service access your instance requires is usually
  enough.
- `--publish` writes `workflow_state=published` directly. If your knowledge base
  uses an approval workflow, the instance may override this. In that case,
  import as draft and publish through the workflow.

## Development

```bash
pip install -e '.[test]'
pytest
```

Only import content you have the right to reuse, and check each site's terms of
use.
