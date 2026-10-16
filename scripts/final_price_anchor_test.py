#!/usr/bin/env python3
"""Final A/B prototype: price-first nearby product-name suggestions (review ONLY).
Input: data/flyer_fulltext_layout_review.json
Output: data/final_price_anchor_review.json, final_price_anchor_review.html
No changes to verified_offers.json / price_history.json / index.html.
Run at repository root: python scripts/final_price_anchor_test.py
"""
import json
import re
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'data/flyer_fulltext_layout_review.json'
OUTPUT = ROOT / 'data/final_price_anchor_review.json'
PAGE = ROOT / 'final_price_anchor_review.html'
JST = timezone(timedelta(hours=9))
MONEY = re.compile(r'(?<![\d,])(?:[1-9]\d{0,3}|[1-9]\d{0,2}(?:,\d{3})+)(?![\d,])')
CUE = re.compile(r'税込|税抜|税別|本体価格|販売価格|[円￥¥]')
DATE = re.compile(r'\d{1,2}\s*[/／月]\s*\d{1,2}|\d{4}年|\d{1,2}:\d{2}|\d+日限り')
UNIT_ONLY = re.compile(r'^\s*\d+(?:\.\d+)?\s*(?:g|kg|ml|mL|L|個|枚|本|袋|%|％)\s*$', re.I)
CONTACT = re.compile(r'TEL|FAX|電話|\d{2,4}[-ー]\d{2,4}[-ー]\d{3,4}', re.I)
TERMS = {
 '野菜':('トマト','とまと','キャベツ','玉ねぎ','じゃがいも','きゅうり','白菜','大根','人参','にんじん','レタス','小松菜','ほうれん草','ブロッコリー','チンゲン菜','ピーマン','ねぎ'),
 '果物':('りんご','リンゴ','林檎','ふじ','みかん','バナナ','ぶどう','梨','柿','いちご','キウイ','オレンジ'),
 '精肉':('牛肉','豚肉','鶏肉','ロース','ひき肉','ミンチ','もも肉','むね肉'),
 '鮮魚':('まぐろ','マグロ','サーモン','鮭','さば','ぶり','しらす','えび','いか'),
 '乳製品・卵':('牛乳','ヨーグルト','チーズ','卵','たまご','バター'),
 '米・麺・パン':('お米','精米','食パン','うどん','そば','パスタ','ラーメン'),
 '飲料':('お茶','コーヒー','ジュース','天然水','炭酸水'),
 '加工食品':('醤油','しょうゆ','味噌','砂糖','マヨネーズ','ケチャップ','豆腐','ウインナー','ハム')}

def category(text):
    for cat, names in TERMS.items():
        if any(name.lower() in text.lower() for name in names):
            return cat
    return None

def valid_box(line):
    b=line.get('box')
    return bool(isinstance(b,dict) and all(isinstance(b.get(k),int) for k in ('left','top','width','height')))

def nearby(price, candidate):
    pb,nb=price['box'],candidate['box']
    px=pb['left']+pb['width']/2
    py=pb['top']+pb['height']/2
    nx=nb['left']+nb['width']/2
    ny=nb['top']+nb['height']/2
    dx,dy=nx-px,ny-py
    if abs(dx)>380 or abs(dy)>260:
        return None
    # Prefers text immediately above or to the left, but allows other directions.
    alignment=max(0,abs(dx)-(pb['width']+nb['width'])/2)
    distance=(dx*dx+(dy*1.25)**2)**.5
    penalty=30 if dy>50 else 0
    return round(distance+penalty+alignment*.3,1)

def is_name(text):
    t=text.strip()
    if len(t)<2 or CUE.search(t) or DATE.search(t) or CONTACT.search(t) or UNIT_ONLY.fullmatch(t):
        return False
    if not any('\u3040'<=c<='\u30ff' or '\u3400'<=c<='\u9fff' for c in t):
        return False
    if sum(c.isdigit() for c in t)>len(t)/2:
        return False
    return True

def evaluate(flyer):
    lines=[x for x in flyer.get('lines',[]) if valid_box(x) and x.get('text')]
    prices=[]
    names=[x for x in lines if is_name(x['text'])]
    for p in lines:
        txt=p['text']
        if not MONEY.search(txt) or not CUE.search(txt) or DATE.search(txt) or CONTACT.search(txt) or UNIT_ONLY.fullmatch(txt.strip()):
            continue
        ns=[]
        for n in names:
            if n is p:
                continue
            dist=nearby(p,n)
            if dist is None:
                continue
            cat=category(n['text'])
            score=max(0,round(100-dist/5+(18 if cat else 0)+min(10,max(0,(n.get('average_ocr_confidence') or 0)/10))))
            ns.append({'text_unverified':n['text'][:140], 'category_suggested':cat,'distance':dist,'score':min(100,score),'box':n['box']})
        ns.sort(key=lambda x:(-x['score'],x['distance']))
        prices.append({'price_text_unverified':txt[:160], 'numeric_tokens':MONEY.findall(txt)[:8],
                       'price_box':p['box'],'nearby_name_candidates':ns[:3],
                       'has_name_suggestion':bool(ns),'has_category_suggestion':any(x['category_suggested'] for x in ns[:3]),
                       'verified':False,'publish_allowed':False})
    return prices

def main():
    source=json.loads(INPUT.read_text(encoding='utf-8'))
    report={'generated_at_jst':datetime.now(JST).isoformat(timespec='seconds'),
            'stage':'FINAL_PRICE_ANCHOR_AB_TEST_UNVERIFIED', 'verified_products':0,'published_offers':0,
            'comparison_note':'Compare with older candidate reports. Counts are NOT accuracy measurements; manually review against original flyers.',
            'flyers':[]}
    for flyer in source.get('items',[]):
        pairs=evaluate(flyer) if flyer.get('status')=='ocr_generated_unverified' else []
        report['flyers'].append({'shop':flyer.get('shop','不明'),'source_url':flyer.get('source_url'),
                'ocr_status':flyer.get('status'),'anchored_price_candidates':len(pairs),
                'with_nearby_name':sum(p['has_name_suggestion'] for p in pairs),
                'with_category_hint':sum(p['has_category_suggestion'] for p in pairs),
                'suggestions':pairs})
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cards=[]
    for f in report['flyers']:
        items=[]
        for p in f['suggestions']:
            near=' / '.join(escape(n['text_unverified'])+(f'［{escape(n["category_suggested"])}］' if n['category_suggested'] else '') for n in p['nearby_name_candidates']) or 'なし'
            items.append(f'<li><b>{escape(p["price_text_unverified"])}</b><small> → {near}</small></li>')
        url=f.get('source_url') or ''
        link=f'<a href="{escape(url,quote=True)}" target="_blank" rel="noopener noreferrer">元画像</a>' if url.startswith('https://') else ''
        cards.append(f'<section><h2>{escape(f["shop"])}</h2><p>通貨付き数字 {f["anchored_price_candidates"]} / 周辺文字あり {f["with_nearby_name"]} / 分類候補あり {f["with_category_hint"]} （全件未確認）</p>{link}<ol>{"".join(items)}</ol></section>')
    PAGE.write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>最終OCR比較テスト</title><style>body{font-family:system-ui,sans-serif;max-width:900px;margin:auto;background:#f4f6fa;color:#222;padding:18px}section{background:white;padding:18px;margin:18px 0;border-radius:12px}li{margin:12px 0}small{display:block;color:#536071}</style><h1>価格起点の最終比較テスト</h1><p>価格らしい文字と近くの商品名候補。すべて未確認。正答率は元画像との照合が必要で、販売価格として自動公開しません。</p>'+''.join(cards)+'</html>',encoding='utf-8')
    print('Final price anchors:',sum(f['anchored_price_candidates'] for f in report['flyers']), 'with nearby text:',sum(f['with_nearby_name'] for f in report['flyers']))

if __name__=='__main__':
    main()
