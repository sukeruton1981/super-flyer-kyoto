"""Discover flyer image links on configured public pages (no price extraction).

Run: python scripts/discover_flyers.py
Writes data/discovered_flyers.json with observed URL history and checked time.
Use permitted public pages only; obey robots.txt. Failures are reported, not invented.
"""
import json
import re
import urllib.robotparser
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data' / 'flyer_discovery_sources.json'
OUTPUT = ROOT / 'data' / 'discovered_flyers.json'
JST = timezone(timedelta(hours=9))
USER_AGENT = 'SuperFlyerKyoto/0.1 (flyer URL discovery, no image download)'
MAX_BYTES = 2_000_000


def safe_https(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    return p.scheme == 'https' and host and p.port in (None, 443) and not p.username and not p.password and not (host == 'localhost' or host.endswith('.local') or host.startswith(('127.', '10.', '192.168.', '169.254.', '172.16.')))


def extract_links(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    urls = set()
    for el in soup.select('a[href]'):
        raw = el.get('href', '')
        u = urljoin(base_url, raw)
        path = urlsplit(u).path.lower()
        if safe_https(u) and '/chirashi-file/' in path and re.search(r'\.(?:jpe?g|png|webp)$', path):
            urls.add(u)
    return sorted(urls)


def main():
    sources = json.loads(CONFIG.read_text(encoding='utf-8'))['sources']
    previous = json.loads(OUTPUT.read_text(encoding='utf-8')) if OUTPUT.exists() else {}
    old = {x['url'] for x in previous.get('flyers', [])}
    known = {x['url']: x for x in previous.get('flyers', [])}
    checks = []
    now = datetime.now(JST).isoformat(timespec='seconds')
    for source in sources:
        shop, url = source['shop'], source['url']
        item = {'shop': shop, 'url': url}
        try:
            if not safe_https(url):
                raise ValueError('URL must be public HTTPS')
            p = urlsplit(url)
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f'{p.scheme}://{p.netloc}/robots.txt')
            rp.read()
            if not rp.can_fetch(USER_AGENT, url):
                raise PermissionError('robots.txt disallows crawling')
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as res:
                final = res.geturl()
                if not safe_https(final) or urlsplit(final).hostname != p.hostname:
                    raise ValueError('unexpected redirect host')
                if 'text/html' not in res.headers.get('Content-Type', '').lower():
                    raise ValueError('not an HTML page')
                blob = res.read(MAX_BYTES + 1)
            if len(blob) > MAX_BYTES:
                raise ValueError('HTML exceeds size limit')
            html = blob.decode('utf-8', errors='replace')
            found = extract_links(html, final)
            for flyer_url in found:
                if flyer_url not in known:
                    known[flyer_url] = {'shop': shop, 'url': flyer_url, 'first_seen_at_jst': now, 'status': 'unverified'}
            item.update(status='ok', found_links=len(found), new_links=sum(x not in old for x in found))
        except Exception as exc:
            item.update(status='error', detail=f'{type(exc).__name__}: {exc}'[:180])
        checks.append(item)
    report = {'last_checked_at_jst': now, 'checks': checks,
              'flyers': sorted(known.values(), key=lambda x: (x['shop'], x['url'])),
              'price_extraction_enabled': False,
              'note': 'Image links are candidates, not verified current sales or prices.'}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for result in checks:
        print(result)
    print('Known image links:', len(known), 'new:', len(set(known)-old))


if __name__ == '__main__':
    main()
