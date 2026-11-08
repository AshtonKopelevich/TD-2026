"""Freeze the current dashboard into a self-contained static judging edition.

Run: uv run --extra dashboard python export_dashboard.py
No Flask server or database is required to view the generated site.
"""
from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import shutil
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dashboard.app import BUILDERS, PLOTLY_JS, app
from dashboard.data import DB_PATH, is_placeholder

ROOT = Path(__file__).resolve().parent
NOTICE = ('<div class="filters filters-off" role="note"><strong>Judging edition.</strong> '
          'Saved findings for January–June 2025, whole floor. Charts and tables are interactive; '
          'date and segment filters are fixed in this static edition.</div>')


def output_path(route: str) -> str:
    if route.startswith(("/static/", "/vendor/")):
        return route.lstrip("/")
    return route.strip("/") + "/index.html" if route != "/" else "index.html"


def relative_url(value: str, route: str) -> str:
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/"):
        return value
    target = output_path(parts.path)
    relative = posixpath.relpath(target, posixpath.dirname(output_path(route)) or ".")
    return relative + ("#" + parts.fragment if parts.fragment else "")


def rewrite_spec(value, route: str):
    if isinstance(value, dict):
        return {k: rewrite_spec(v, route) for k, v in value.items()}
    if isinstance(value, list):
        return [rewrite_spec(v, route) for v in value]
    if isinstance(value, str) and value.startswith("/machines/"):
        return relative_url(value, route)
    return value


def freeze_page(document: str, route: str) -> str:
    document = re.sub(r'<form\b[^>]*\bid="filters"[^>]*>.*?</form>', NOTICE,
                      document, flags=re.S)
    # Use the existing CSS font fallbacks so the export has no third-party requests.
    document = re.sub(r'<link\b[^>]*href="https://fonts\.[^"]*"[^>]*>\s*', '', document)
    if route == "/":
        document = document.replace('<main id="content">', '<main id="content">' + NOTICE)

    def attribute(match):
        name, quote, value = match.groups()
        return name + '=' + quote + html.escape(relative_url(html.unescape(value), route), quote=True) + quote

    document = re.sub(r'\b(href|src)=(\")([^\"]*)\2', attribute, document)

    def spec(match):
        data = rewrite_spec(json.loads(match.group(2)), route)
        return match.group(1) + json.dumps(data, ensure_ascii=False).replace('</', '<\\/') + match.group(3)

    return re.sub(r'(<script\b[^>]*type="application/json"[^>]*>)(.*?)(</script>)', spec,
                  document, flags=re.S)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(v for k, v in attrs if k in ("href", "src") and v)


def validate(directory: Path) -> int:
    count = 0
    for path in directory.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        links = Links()
        links.feed(text)
        for url in links.urls:
            parts = urlsplit(url)
            if parts.scheme or parts.netloc or not parts.path:
                continue
            target = path.parent / unquote(parts.path)
            if not target.is_file():
                raise RuntimeError(f"Broken static link in {path}: {url}")
        if 'id="filters"' in text:
            raise RuntimeError(f"Server filter remains in {path}")
        def check_spec(value):
            if isinstance(value, dict):
                for item in value.values():
                    check_spec(item)
            elif isinstance(value, list):
                for item in value:
                    check_spec(item)
            elif isinstance(value, str) and re.search(r'(?:^|/)M-[^/]+/index\.html$', value):
                if not (path.parent / value).is_file():
                    raise RuntimeError(f'Broken machine chart link in {path}: {value}')
        for spec in re.findall(r'<script\b[^>]*type="application/json"[^>]*>(.*?)</script>', text, re.S):
            check_spec(json.loads(spec))
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'sites/gilded-ace/dist')
    parser.add_argument('--check', action='store_true', help='Validate an existing export without rebuilding')
    args = parser.parse_args()
    directory = args.output.resolve()
    if args.check:
        print(f'Validated {validate(directory)} static pages.')
        return
    directory.mkdir(parents=True, exist_ok=True)
    if is_placeholder():
        raise SystemExit('Refusing to publish placeholder findings. Build the real marts first.')
    shutil.copytree(ROOT / 'dashboard/static', directory / 'static', dirs_exist_ok=True)
    (directory / 'vendor').mkdir(exist_ok=True)
    shutil.copy2(PLOTLY_JS, directory / 'vendor/plotly.min.js')
    js_path = directory / 'static/app.js'
    js = js_path.read_text(encoding='utf-8')
    js = js.replace(r'/^\/machines\/[^/?]+(?:\?|$)/.test(href)',
                    r'/^(?:\.\.\/)*(?:machines\/)?[^/?]+\/index\.html(?:#.*)?$/.test(href)')
    js_path.write_text(js, encoding='utf-8')
    app.config['TESTING'] = True
    queue = deque(['/'] + ['/' + route for route in BUILDERS])
    visited = set()
    client = app.test_client()
    while queue:
        route = queue.popleft()
        if route in visited:
            continue
        response = client.get(route)
        if response.status_code != 200:
            raise RuntimeError(f'Cannot export {route}: HTTP {response.status_code}')
        original = response.get_data(as_text=True)
        # Include every machine linked from either tables or Plotly figure data.
        for link in re.findall(r'/machines/[A-Za-z0-9_.%-]+', original):
            if link not in visited:
                queue.append(link)
        destination = directory / output_path(route)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(freeze_page(original, route), encoding='utf-8')
        visited.add(route)
        print(f'[{len(visited)}] {route}', flush=True)
    count = validate(directory)
    manifest = {'generated_at': datetime.now(timezone.utc).isoformat(),
                'database_modified_at': datetime.fromtimestamp(DB_PATH.stat().st_mtime, timezone.utc).isoformat(),
                'scope': 'January–June 2025, whole floor; saved findings',
                'pages': sorted(visited), 'html_files_validated': count}
    (directory / 'export-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (directory / '.nojekyll').touch()
    print(f'Validated {count} pages. Static site: {directory}', flush=True)


if __name__ == '__main__':
    main()
