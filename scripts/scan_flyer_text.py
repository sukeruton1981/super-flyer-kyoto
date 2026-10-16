#!/usr/bin/env python3
"""OCR flyer images for a HUMAN REVIEW QUEUE, never publish sale prices.

Usage (repository root):
  python scripts/scan_flyer_text.py --local path/to/flyer.jpg
  python scripts/scan_flyer_text.py --max-images 2

Requirements: tesseract with jpn+eng language packs, Pillow optional.
Output: data/flyer_ocr_review.json and flyer_ocr_review.html.
"""
import argparse
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
AGENT = 'SuperFlyerKyoto/0.2 (review-only OCR)'
MAX_BYTES = 8_000_000
ALLOWED_HOST = 'chirashi-guide.com'
PRICE_TOKEN = re.compile(r'(?<!\d)(?:[1-9]\d{1,3}|\d{1,2},\d{3})(?!\d)')


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
    # Respect publisher crawler policy; network errors do not imply permission.
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url('https://' + ALLOWED_HOST + '/robots.txt')
    rp.read(); print("OCR CHECK: robots.txt completed", flush=True) 
    if not rp.can_fetch(AGENT, url):
        raise PermissionError('Publisher robots policy disallows this image')
    req = urllib.request.Request(url, headers={'User-Agent': AGENT})
    with urllib.request.urlopen(req, timeout=18) as resp:
        final = resp.geturl()
        if not safe_image_url(final):
            raise ValueError('Unexpected redirect')
        if not resp.headers.get('Content-Type', '').lower().startswith('image/'):
            raise ValueError('Response is not an image')
        blob = resp.read(MAX_BYTES+1)
    if len(blob)>MAX_BYTES:
        raise ValueError('Image exceeds size limit')
    if not (blob.startswith(b'\xff\xd8\xff') or blob.startswith(b'\x89PNG\r\n\x1a\n') or blob[:4] == b'RIFF'):
        raise ValueError('Unsupported image signature')
    return blob


def recognize(path):
    try:
        result = subprocess.run(['tesseract', str(path), 'stdout', '-l', 'jpn+eng', '--psm', '11'],
                                capture_output=True, text=True, timeout=55, check=True)
    except FileNotFoundError as exc:
        raise RuntimeError('Tesseract not installed') from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or '')[:200]) from exc
    lines = [s.strip() for s in result.stdout.splitlines() if s.strip()]
    # Deliberately no automatic pairing of OCR prices with products.
    price_like_lines = [{'text': line[:180], 'numbers': PRICE_TOKEN.findall(line)[:8]}
                        for line in lines if PRICE_TOKEN.search(line)]
    return lines, price_like_lines


def run(local, limit):
    period_by_url = {}
    if PERIODS.exists():
        p = json.loads(PERIODS.read_text(encoding='utf-8'))
        period_by_url = {v['url']: v for v in p.get('flyers', [])}
    if local:
        targets = [{'url': '', 'label': Path(s).name, 'local_path':s} for s in local]
    else:
        discovery = json.loads(DISCOVERED.read_text(encoding='utf-8'))
        targets = [dict(url=x['url'], label=x.get('shop', '未確認')) for x in discovery.get('flyers', [])]
        targets.sort(key=lambda x: (0 if x['url'] in period_by_url else 1, x['url']))
        targets = targets[:limit]
    results=[]
    for entry in targets:
        url=entry['url']
        item = {'label':entry['label'], 'image_url':url or None, 'status':'needs_human_review',
                'price_verified':False,'offer_import_allowed':False}
        if url in period_by_url:
            meta=period_by_url[url]
            item['flyer_valid_from']=meta['flyer_valid_from']
            item['flyer_valid_to']=meta['flyer_valid_to']
            item['note']='チラシ全体の期間。個別商品の有効期限ではない'
        try:
            if entry.get('local_path'):
                image_path=Path(entry['local_path'])
                lines, candidates=recognize(image_path)
            else:
                blob=fetch_image(url)
                with tempfile.TemporaryDirectory() as tmp:
                    image_path=Path(tmp)/'flyer.jpg'
                    image_path.write_bytes(blob)
                    lines,candidates=recognize(image_path)
            item.update(status='ocr_generated_unverified', recognized_line_count=len(lines),
                        price_like_line_count=len(candidates),
                        raw_text='\n'.join(lines)[:30000], price_like_lines=candidates[:250])
        except Exception as exc:
            item.update(status='error', error=f'{type(exc).__name__}: {exc}'[:240])
        results.append(item)
    now=datetime.now(JST).isoformat(timespec='seconds')
    report={'generated_at_jst':now, 'stage':'OCR_DRAFT_REVIEW_ONLY',
            'automatically_verified_products':0, 'published_offers':0,
            'items':results}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cards=[]
    for x in results:
        link=x.get('image_url')
        source=(f'<a href="{escape(link,quote=True)}" target="_blank" rel="noopener noreferrer">元画像を開く</a>' if link else '<span>ローカルテスト画像</span>')
        preview=escape('\n'.join(z['text'] for z in x.get('price_like_lines',[])[:100]))
        err=escape(x.get('error',''))
        cards.append(f'<section><h2>{escape(x["label"])}</h2><p>{escape(x["status"])}・価格の自動確定なし</p>{source}<p>{err}</p><details><summary>OCRで拾った価格らしい行 ({x.get("price_like_line_count",0)}件・未確認)</summary><pre>{preview}</pre></details></section>')
    html='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR確認待ち一覧</title><style>body{font-family:system-ui,sans-serif;max-width:960px;margin:auto;padding:20px;background:#f6f7fa;color:#19232e}section{background:white;border:1px solid #ddd;border-radius:12px;padding:16px;margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#12549d}</style><h1>OCR確認待ち一覧</h1><p>自動認識テキストは誤読の可能性があります。商品名と価格を対応付けておらず、価格比較サイトへ自動登録しません。</p>'''+''.join(cards)+'</html>'
    PAGE.write_text(html,encoding='utf-8')
    print(f'OCR review: {len(results)} images; successful {sum(x["status"]=="ocr_generated_unverified" for x in results)}; published 0')
    for x in results:
        if x['status']=='error': print('ERROR:',x['label'],x['error'])
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--local',action='append',default=[],help='Local image file for dry-run OCR')
    parser.add_argument('--max-images',type=int,default=2)
    args=parser.parse_args()
    if not (1<=args.max_images<=15): parser.error('max-images must be 1-15')
    run(args.local,args.max_images)

if __name__=='__main__':main()
