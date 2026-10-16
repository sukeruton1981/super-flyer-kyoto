#!/usr/bin/env python3
"""Position-aware flyer OCR, review only; never publish offers.

Uses existing scan_flyer_layout.py for safe image retrieval and constants.
This version records spatial boxes for ALL recognized text lines, not only
lines containing numerals. No product/price associations are inferred.
"""
import argparse
import csv
import io
import json
import subprocess
import tempfile
from datetime import datetime
from html import escape
from pathlib import Path

import scan_flyer_layout as previous

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'data' / 'flyer_fulltext_layout_review.json'
PAGE = ROOT / 'flyer_fulltext_layout_review.html'


def recognize(path):
    result = subprocess.run(
        ['tesseract', str(path), 'stdout', '-l', 'jpn+eng', '--psm', '11', 'tsv'],
        capture_output=True, text=True, timeout=100, check=True)
    grouped = {}
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter='\t'):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        try:
            word = {
                'text': row['text'].strip(),
                'left': int(row['left']), 'top': int(row['top']),
                'width': int(row['width']), 'height': int(row['height']),
                'confidence': float(row['conf'])
            }
        except (ValueError, KeyError):
            continue
        key = tuple(row.get(k, '') for k in ('page_num', 'block_num', 'par_num', 'line_num'))
        grouped.setdefault(key, []).append(word)
    lines = []
    for words in grouped.values():
        words.sort(key=lambda w: w['left'])
        line_text = ' '.join(w['text'] for w in words)
        if not line_text:
            continue
        left = min(w['left'] for w in words)
        top = min(w['top'] for w in words)
        right = max(w['left'] + w['width'] for w in words)
        bottom = max(w['top'] + w['height'] for w in words)
        conf = [w['confidence'] for w in words if w['confidence'] >= 0]
        lines.append({
            'text': line_text[:180],
            'box': {'left': left, 'top': top, 'width': right - left, 'height': bottom - top},
            'average_ocr_confidence': round(sum(conf)/len(conf), 1) if conf else None,
            'has_number': bool(previous.PRICE_TOKEN.search(line_text)),
            'verification': 'unverified_ocr_text'
        })
    lines.sort(key=lambda x: (x['box']['top'], x['box']['left']))
    return lines


def run(limit):
    discovery = json.loads(previous.DISCOVERED.read_text(encoding='utf-8'))
    known_periods = {}
    if previous.PERIODS.exists():
        periods = json.loads(previous.PERIODS.read_text(encoding='utf-8'))
        known_periods = {x['url']: x for x in periods.get('flyers', [])}
    targets = discovery.get('flyers', [])
    targets = sorted(targets, key=lambda x: (0 if x['url'] in known_periods else 1, x['url']))[:limit]
    items = []
    for flyer in targets:
        url = flyer['url']
        item = {'shop': flyer.get('shop', '不明'), 'source_url': url,
                'status': 'error', 'product_prices_verified': 0,
                'offer_import_allowed': False}
        try:
            blob = previous.fetch_image(url)
            with tempfile.TemporaryDirectory() as tmp:
                image_file = Path(tmp) / 'flyer.jpg'
                image_file.write_bytes(blob)
                lines = recognize(image_file)
            item.update(status='ocr_generated_unverified', line_count=len(lines),
                        lines=lines, number_line_count=sum(x['has_number'] for x in lines))
        except Exception as exc:
            item['error'] = f'{type(exc).__name__}: {exc}'[:240]
        items.append(item)
        print('FULLTEXT OCR:', item['shop'], item['status'], item.get('line_count', 0), flush=True)
    report = {'generated_at_jst': datetime.now(previous.JST).isoformat(timespec='seconds'),
              'stage': 'FULLTEXT_LAYOUT_REVIEW_ONLY', 'verified_products': 0,
              'published_offers': 0, 'items': items}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    sections = []
    for item in items:
        previews = []
        for line in item.get('lines', [])[:180]:
            b = line['box']
            previews.append(f'<li>{escape(line["text"])} <small>(x={b["left"]}, y={b["top"]}, 信頼度={line["average_ocr_confidence"]})</small></li>')
        sections.append(f'<section><h2>{escape(item["shop"])}</h2>'
                        f'<p>{escape(item["status"])}：{item.get("line_count",0)}行</p>'
                        f'<p><a href="{escape(item["source_url"], quote=True)}" target="_blank" rel="noopener noreferrer">元画像</a></p>'
                        f'<p>{escape(item.get("error", ""))}</p>'
                        f'<details><summary>全文字の位置情報（先頭180行）</summary><ol>{"".join(previews)}</ol></details></section>')
    html = ('<!doctype html><html lang="ja"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>全文字の位置確認</title><style>body{font-family:system-ui,sans-serif;max-width:960px;margin:auto;padding:20px;background:#f6f7fa}section{background:white;padding:16px;border-radius:12px;margin:16px 0}li{margin:7px 0;overflow-wrap:anywhere}small{color:#666}</style>'
            '<h1>全文字の座標確認</h1><p>OCRの誤読があります。商品名と価格は未対応付け、価格の自動登録なし。</p>'
            + ''.join(sections) + '</html>')
    PAGE.write_text(html, encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-images', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.max_images <= 15:
        parser.error('max-images must be 1-15')
    run(args.max_images)
