#!/usr/bin/env python3
"""Generate unverified OCR product/price pairing suggestions for human review.

Input: data/flyer_fulltext_layout_review.json (scan_flyer_layout_v2.py)
Output: data/product_price_pairs_review.json and product_price_pairs_review.html
This script NEVER publishes verified prices or modifies price_history.json.
"""
import json
import math
import re
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/flyer_fulltext_layout_review.json'
DEST = ROOT / 'data/product_price_pairs_review.json'
PAGE = ROOT / 'product_price_pairs_review.html'
JST = timezone(timedelta(hours=9))
# Restrict to numeric-looking text, but treat all as unverified potential prices.
MONEY = re.compile(r'(?<![\d,])(?:[1-9]\d{1,3}|[1-9]\d?,\d{3})(?![\d,])')
CURRENCY = re.compile(r'円|税込|税抜|本体|価格|¥|￥')
OTHER_NUMERIC = re.compile(r'\d{1,2}[月/日:]\d{1,2}|\d{4}年|TEL|電話|FAX|%|％', re.I)


def looks_like_name(s):
    s = s.strip()
    letters = sum(c.isalpha() for c in s)
    return 2 <= letters and len(s) >= 3 and not OTHER_NUMERIC.search(s) and not CURRENCY.fullmatch(s)


def center(box):
    return box['left'] + box['width']/2, box['top'] + box['height']/2


def match(flyer):
    lines = [x for x in flyer.get('lines', []) if isinstance(x.get('box'), dict) and x.get('text')]
    priced = []
    named = []
    for i, x in enumerate(lines):
        t = x['text']
        if MONEY.search(t) and not OTHER_NUMERIC.search(t):
            priced.append((i, x))
        if looks_like_name(t):
            named.append((i, x))
    candidates=[]
    for _, price in priced:
        px,py=center(price['box'])
        closest=[]
        for _, name in named:
            if name is price: continue
            nx,ny=center(name['box'])
            dx,dy=abs(nx-px),abs(ny-py)
            if dx>440 or dy>240: continue
            # Prefer labels nearby, especially above or to the left of the numeric text.
            dist=math.hypot(dx,dy*1.25)
            if ny > py+30: dist+=60
            conf=name.get('average_ocr_confidence')
            closest.append((round(dist,1),name,conf))
        closest.sort(key=lambda x:x[0])
        if not closest: continue
        candidates.append({
            'price_text_unverified':price['text'][:160],
            'price_numbers_unverified':MONEY.findall(price['text'])[:8],
            'price_box':price['box'],
            'price_ocr_confidence':price.get('average_ocr_confidence'),
            'nearby_text_candidates':[
                {'text_unverified':x['text'][:180], 'box':x['box'],
                 'distance_score':distance, 'ocr_confidence':conf}
                for distance,x,conf in closest[:3]
            ],
            'verified':False, 'publish_allowed':False,
        })
    return candidates


def main():
    data=json.loads(SOURCE.read_text(encoding='utf-8'))
    out={'generated_at_jst':datetime.now(JST).isoformat(timespec='seconds'),
         'stage':'OCR_PRODUCT_PRICE_PAIR_SUGGESTIONS_UNVERIFIED',
         'verified_products':0,'published_offers':0,'flyers':[]}
    for flyer in data.get('items',[]):
        out['flyers'].append({'shop':flyer.get('shop','不明'),
            'source_url':flyer.get('source_url'),
            'source_status':flyer.get('status'),
            'suggestions':match(flyer) if flyer.get('status')=='ocr_generated_unverified' else []})
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sections=[]
    for f in out['flyers']:
        entries=[]
        for p in f['suggestions']:
            options=' / '.join(escape(c['text_unverified']) for c in p['nearby_text_candidates'])
            entries.append(f'<li><b>数字候補:</b> {escape(p["price_text_unverified"])} <small>→ 近接文字候補: {options}</small></li>')
        link=f.get('source_url') or ''
        sections.append(f'<section><h2>{escape(f["shop"])}</h2><p>候補 {len(f["suggestions"])} 件（全件未確認）</p><a href="{escape(link,quote=True)}" rel="noopener noreferrer" target="_blank">元画像</a><ol>{"".join(entries)}</ol></section>')
    html='<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>商品名と数字の組み合わせ候補</title><style>body{font-family:system-ui,sans-serif;background:#f6f7fb;color:#1d2430;max-width:950px;margin:auto;padding:20px}section{background:white;border:1px solid #ddd;border-radius:12px;padding:14px;margin:18px 0}li{margin:12px 0}small{display:block;color:#505e71;overflow-wrap:anywhere}</style><h1>商品名と数字の組み合わせ候補</h1><p><strong>すべて未確認。</strong>商品名・価格・税込区分・対象日などは未検証です。数字は値段とは限らず、近接文字も商品名とは限りません。自動販売価格として使用しないでください。</p>'+''.join(sections)+'</html>'
    PAGE.write_text(html,encoding='utf-8')
    print('Unverified pairs:',sum(len(x['suggestions']) for x in out['flyers']),'published:',out['published_offers'])

if __name__=='__main__':
    main()
