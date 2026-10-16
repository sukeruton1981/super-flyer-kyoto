#!/usr/bin/env python3
"""Conservative Japanese flyer OCR with positional review candidates.

No extracted text, price or product is ever auto-verified or published.
Run: python scripts/scan_flyer_text.py --max-images 2
Requires: tesseract-ocr, tesseract-ocr-jpn (already in refresh.yml).
"""
import argparse
import csv
import io
import json
import re
import subprocess
import tempfile
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'data' / 'flyer_ocr_review.json'
PAGE = ROOT / 'flyer_ocr_review.html'
DISCOVERED = ROOT / 'data' / 'discovered_flyers.json'
PERIODS = ROOT / 'data' / 'verified_flyer_periods.json'
JST = timezone(timedelta(hours=9))
AGENT = 'SuperFlyerKyoto/0.3 (review-only OCR)'
MAX_BYTES = 8_000_000
ALLOWED_HOST = 'chirashi-guide.com'
# Potential prices, not dates or product-validating evidence.
PRICE_TOKEN = re.compile(r'(?<![\d,])(?:[1-9]\d{1,3}|[1-9]\d?,\d{3})(?![\d,])')


def safe_image_url(url):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.hostname == ALLOWED_HOST and
                p.port in (None, 443) and not p.username and not p.password and
                re.search(r'\.(jpe?g|png|webp)$', p.path, re.I) is not None)
    except ValueError:
        return False


def fetch_image(url):
    if not safe_image_url(url):
        raise ValueError('Not an approved HTTPS flyer image URL')
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url('https://' + ALLOWED_HOST + '/robots.txt')
    rp.read()
    print('OCR CHECK: robots.txt completed', flush=True)
    if not rp.can_fetch(AGENT, url):
        raise PermissionError('Publisher robots policy disallows this image')
    req = urllib.request.Request(url, headers={'User-Agent': AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        if not safe_image_url(resp.geturl()):
            raise ValueError('Unexpected redirect')
        if not resp.headers.get('Content-Type', '').lower().startswith('image/'):
            raise ValueError('Response is not an image')
        blob = resp.read(MAX_BYTES + 1)
    if len(blob) > MAX_BYTES:
        raise ValueError('Image exceeds size limit')
    if not (blob.startswith(b'\xff\xd8\xff') or blob.startswith(b'\x89PNG\r\n\x1a\n') or blob[:4] == b'RIFF'):
        raise ValueError('Unsupported image signature')
    return blob


def recognize(path):
    """Use Tesseract TSV to retain word boxes and confidence (not product links)."""
    try:
        result = subprocess.run(
            ['tesseract', str(path), 'stdout', '-l', 'jpn+eng', '--psm', '11', 'tsv'],
            capture_output=True, text=True, timeout=100, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError('Tesseract not installed') from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or '')[:200]) from exc
    groups = {}
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter='\t'):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        try:
            word = {'text': row['text'].strip(), 'left': int(row['left']),
                    'top': int(row['top']), 'width': int(row['width']),
                    'height': int(row['height']), 'confidence': round(float(row['conf']), 1)}
        except (ValueError, KeyError):
            continue
        key = (row.get('page_num'), row.get('block_num'), row.get('par_num'), row.get('line_num'))
        groups.setdefault(key, []).append(word)
    lines = []
    candidates = []
    for words in groups.values():
        words.sort(key=lambda w: w['left'])
        line = ' '.join(w['text'] for w in words)
        if not line.strip():
            continue
        lines.append(line)
        nums = PRICE_TOKEN.findall(line)
        if not nums:
            continue
        # Bounding rectangle covers the whole OCR line; not an exact product/price rectangle.
        left = min(w['left'] for w in words)
        top = min(w['top'] for w in words)
        right = max(w['left'] + w['width'] for w in words)
        bottom = max(w['top'] + w['height'] for w in words)
        confs = [w['confidence'] for w in words if w['confidence'] >= 0]
        candidates.append({'text': line[:180], 'numbers': nums[:8],
                           'box': {'left': left, 'top': top, 'width': right-left, 'height': bottom-top},
                           'average_ocr_confidence': round(sum(confs)/len(confs), 1) if confs else None,
                           'verification': 'unverified_not_a_product'})
    return lines, candidates


def run(local, limit):
    period_by_url = {}
    if PERIODS.exists():
        p = json.loads(PERIODS.read_text(encoding='utf-8'))
        period_by_url = {v['url']: v for v in p.get('flyers', [])}
    if local:
        targets = [{'url': '', 'label': Path(s).name, 'local_path': s} for s in local]
    else:
        discovery = json.loads(DISCOVERED.read_text(encoding='utf-8'))
        targets = [dict(url=x['url'], label=x.get('shop', '未確認')) for x in discovery.get('flyers', [])]
        targets.sort(key=lambda x: (0 if x['url'] in period_by_url else 1, x['url']))
        targets = targets[:limit]
    results = []
    for entry in targets:
        url = entry['url']
        item = {'label': entry['label'], 'image_url': url or None,
                'status': 'needs_human_review', 'price_verified': False,
                'offer_import_allowed': False}
        if url in period_by_url:
            meta = period_by_url[url]
            item['flyer_valid_from'] = meta['flyer_valid_from']
            item['flyer_valid_to'] = meta['flyer_valid_to']
            item['note'] = 'チラシ全体の期間。個別商品の有効期限ではない'
        try:
            if entry.get('local_path'):
                lines, candidates = recognize(Path(entry['local_path']))
            else:
                blob = fetch_image(url)
                with tempfile.TemporaryDirectory() as tmp:
                    image_path = Path(tmp) / 'flyer.jpg'
                    image_path.write_bytes(blob)
                    lines, candidates = recognize(image_path)
            item.update(status='ocr_generated_unverified', recognized_line_count=len(lines),
                        price_like_line_count=len(candidates), raw_text='\n'.join(lines)[:30000],
                        price_like_lines=candidates[:300])
        except Exception as exc:
            item.update(status='error', error=f'{type(exc).__name__}: {exc}'[:240])
        results.append(item)
    report = {'generated_at_jst': datetime.now(JST).isoformat(timespec='seconds'),
              'stage': 'OCR_POSITIONAL_DRAFT_REVIEW_ONLY', 'automatically_verified_products': 0,
              'published_offers': 0, 'items': results}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cards = []
    for x in results:
        link = x.get('image_url')
        source = (f'<a href="{escape(link, quote=True)}" target="_blank" rel="noopener noreferrer">元画像を開く</a>'
                  if link else '<span>ローカルテスト画像</span>')
        preview = '\n'.join(f'{c["text"]} [座標 {c["box"]["left"]},{c["box"]["top"]}]'
                            for c in x.get('price_like_lines', [])[:150])
        cards.append(f'<section><h2>{escape(x["label"])}</h2><p>{escape(x["status"])}：価格確定・自動掲載なし</p>'
                     f'{source}<p>{escape(x.get("error", ""))}</p>'
                     f'<details><summary>数字のある行（{x.get("price_like_line_count", 0)}件・未確認）</summary>'
                     f'<pre>{escape(preview)}</pre></details></section>')
    html = ('<!doctype html><html lang="ja"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>OCR位置情報つき確認一覧</title><style>body{font-family:system-ui,sans-serif;'
            'max-width:960px;margin:auto;padding:20px;background:#f6f7fa;color:#19232e}'
            'section{background:white;border:1px solid #ddd;border-radius:12px;padding:16px;margin:16px 0}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#12549d}</style>'
            '<h1>OCR位置情報つき確認一覧</h1><p>数字は日付や誤読も含み得ます。'
            '表示座標は行の位置であり、商品名と価格の一致を意味しません。価格は自動登録しません。</p>'
            + ''.join(cards) + '</html>')
    PAGE.write_text(html, encoding='utf-8')
    print(f'OCR positional review: {len(results)} images; successful '
          f'{sum(x["status"] == "ocr_generated_unverified" for x in results)}; published 0')
    for x in results:
        if x['status'] == 'error':
            print('ERROR:', x['label'], x['error'])
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='append', default=[])
    parser.add_argument('--max-images', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.max_images <= 15:
        parser.error('max-images must be 1-15')
    run(args.local, args.max_images)


if __name__ == '__main__':
    main()
