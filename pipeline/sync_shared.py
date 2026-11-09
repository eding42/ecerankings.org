#!/usr/bin/env python3
"""Copy the pinned shared identity to the static site and generate the project directory."""
import html
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
shared = root / 'shared/eding'
projects = json.loads((shared / 'projects.json').read_text())
assert projects['schema_version'] == 1
ids = set()
items = []
for project in projects['projects']:
    assert project['id'] not in ids
    ids.add(project['id'])
    assert project['url'].startswith('https://') and project['repository'].startswith('https://github.com/')
    name, url, desc, repo = (html.escape(project[k], quote=True) for k in ('name', 'url', 'description', 'repository'))
    items.append(f'<li><h2><a href="{url}">{name}</a></h2><p>{desc} <a href="{repo}">Source</a></p></li>')
(root / 'site/eding-shared.css').write_bytes((shared / 'tokens.css').read_bytes())
(root / 'hub/index.html').write_text('''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Projects — Edward Ding</title><link rel="stylesheet" href="tokens.css"><style>body{font:1rem/1.6 system-ui,sans-serif;color:#222;max-width:48rem;margin:3rem auto;padding:0 1rem}a{color:var(--eding-link)}ul{padding:0;list-style:none}li{border-top:1px solid #ddd;padding:.7rem 0}h1{font-size:2rem}h2{font-size:1.15rem;margin:0}p{margin:.3rem 0}</style></head><body><header><a class="eding-project-link" href="https://eding.dev/">Edward Ding</a></header><main><h1>Projects</h1><ul>''' + ''.join(items) + '</ul></main></body></html>\n')
(root / 'hub/tokens.css').write_bytes((shared / 'tokens.css').read_bytes())
