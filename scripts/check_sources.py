"""Check flyer reference pages without treating them as price feeds.

Run: python scripts/check_sources.py
This script NEVER extracts or publishes prices.
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'data' / 'sources.json'
REPORT = ROOT / 'data' / 'source_health.json'
JST = timezone(timedelta(hours=9))


def check_reference(source):
    url = source.get('url', '')
    shop = source.get('shop', '不明')
    item = {'shop': shop, 'url': url, 'kind': 'reference_only', 'price_imported': False}
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        return {**item, 'status': 'invalid_url'}
    # Do not send requests to arbitrary private or loopback hosts.
    host = (parsed.hostname or '').lower()
    if host in ('localhost',) or host.endswith('.local') or host.startswith(('127.', '10.', '192.168.', '169.254.')):
        return {**item, 'status': 'disallowed_host'}
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'SuperFlyerSourceCheck/1.0'})
        with urllib.request.urlopen(req, timeout=12) as response:
            code = response.status
            final_url = response.geturl()
        item['http_status'] = code
        item['status'] = 'reachable' if 200 <= code < 400 else 'http_error'
        if final_url != url:
            item['redirected_to'] = final_url
    except urllib.error.HTTPError as exc:
        item.update(status='http_error', http_status=exc.code)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        item.update(status='connection_error', detail=str(exc)[:160])
    return item


def main():
    cfg = json.loads(CONFIG.read_text(encoding='utf-8'))
    references = cfg.get('reference_pages', [])
    if not isinstance(references, list):
        raise ValueError('reference_pages must be a list')
    results = [check_reference(x) for x in references if isinstance(x, dict)]
    checked_at = datetime.now(JST).isoformat(timespec='seconds')
    report = {
        'checked_at_jst': checked_at,
        'purpose': 'reference_page_reachability_only',
        'price_acquisition_enabled': False,
        'configured_csv_count': len(cfg.get('csv_urls', [])),
        'checked_reference_count': len(results),
        'results': results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Checked {len(results)} reference pages; this is NOT a price update.')
    for item in results:
        print(f"{item['shop']}: {item['status']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
