#!/usr/bin/env python3
"""One-off A/B test: relax tax-word requirements and down-rank package-like text.

Run at repository root: python scripts/price_cue_relaxed_test.py
Input: data/flyer_fulltext_layout_review.json
Output: data/price_cue_relaxed_review.json, price_cue_relaxed_review.html
NEVER modifies verified_offers.json, price_history.json or index.html.

IMPORTANT: Package text cannot reliably be detected from OCR coordinates alone.
This script down-ranks, but does not exclude, low-confidence / brand-like text.
"""
import json
import re
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/flyer_fulltext_layout_review.json'
OUTPUT = ROOT / 'data/price_cue_relaxed_review.json'
PAGE = ROOT / 'price_cue_relaxed_review.html'
JST = timezone(timedelta(hours=9))
MONEY = re.compile(r'(?<![\d,.])(?:[1-9]\d{0,3}|[1-9]\d{0,2}(?:,\d{3})+)(?![\d,.])')
CURRENCY = re.compile(r'[円￥¥]|税込|税抜|税別|本体価格')
DATE = re.compile(r'\d{1,2}\s*[/／月]\s*\d{1,2}|\d{4}年|\d{1,2}:\d{2}|\d+日限り')
QUANTITY = re.compile(r'^\s*\d+(?:[.,]\d+)?\s*(?:g|kg|ml|mL|L|個|枚|本|袋|パック|%|％)\s*$', re.I)
PHONE = re.compile(r'TEL|FAX|電話|\d{2,4}[-ー]\d{2,4}[-ー]\d{3,4}', re.I)
ROMAN_ONLY = re.compile(r'^[\s\w\W]*$')
TERMS = {
 '野菜': ('トマト','とまと','キャベツ','玉ねぎ','じゃがいも','きゅうり','白菜','大根','人参','にんじん','レタス','小松菜','ほうれん草','ブロッコリー','チンゲン菜','ピーマン','ねぎ'),
 '果物': ('りんご','リンゴ','林檎','ふじ','みかん','バナナ','ぶどう','梨','柿','いちご','キウイ','オレンジ'),
 '精肉': ('牛肉','豚肉','鶏肉','ロース','ひき肉','ミンチ','もも肉','むね肉'),
 '鮮魚': ('まぐろ','マグロ','サーモン','鮭','さば','ぶり','しらす','えび','いか'),
 '乳製品・卵': ('牛乳','ヨーグルト','チーズ','卵','たまご','バター'),
 '米・麺・パン': ('お米','精米','食パン','うどん','そば','パスタ','ラーメン'),
 '飲料': ('お茶','コーヒー','ジュース','天然水','炭酸水'),
 '加工食品': ('醤油','しょうゆ','味噌','砂糖','マヨネーズ','ケチャップ','豆腐','ウインナー','ハム'),
}

def category(s):
    for k, words in TERMS.items():
        if any(w.lower() in s.lower() for w in words):
            return k
    return None

def valid(x):
    b=x.get('box')
    return bool(isinstance(b,dict) and all(isinstance(b.get(k),int) for k in ('left','top','width','height')) and x.get('text'))

def distance(p,n):
    a,b=p['box'],n['box']
    x1,y1=a['left']+a['width']/2,a['top']+a['height']/2
    x2,y2=b['left']+b['width']/2,b['top']+b['height']/2
    if abs(x2-x1)>300 or abs(y2-y1)>210:
        return None
    return ((x2-x1)**2+((y2-y1)*1.25)**2)**.5 + (30 if y2>y1+40 else 0)

def name_like(s):
    if DATE.search(s) or PHONE.search(s) or QUANTITY.fullmatch(s.strip()):return False
    if CURRENCY.search(s):return False
    if sum(c.isdigit() for c in s)>len(s)/2:return False
    return sum('\u3040'<=c<='\u30ff' or '\u3400'<=c<='\u9fff' for c in s)>=2

def package_risk(x):
    """Only a rough proxy. No actual image-based package detection performed."""
    t=x['text'].strip(); confidence=float(x.get('average_ocr_confidence') or 0)
    latin=sum(c.isascii() and c.isalpha() for c in t)
    letters=sum(c.isalpha() for c in t) or 1
    return (30 if confidence<40 else 12 if confidence<60 else 0) + (18 if latin/letters>.65 else 0)

def evaluate(flyer):
    lines=[x for x in flyer.get('lines',[]) if valid(x)]
    names=[x for x in lines if name_like(x['text'])]
    out=[]
    for p in lines:
        text=p['text']; nums=MONEY.findall(text)
        if not nums or DATE.search(text) or PHONE.search(text) or QUANTITY.fullmatch(text.strip()):continue
        # Standalone 1-2 digit tokens without currency are too ambiguous.
        if not CURRENCY.search(text) and not any(len(v.replace(',',''))>=2 for v in nums):continue
        suggestions=[]
        for n in names:
            if n is p:continue
            dist=distance(p,n)
            if dist is None:continue
            cat=category(n['text']); risk=package_risk(n)
            score=round(max(0,min(100, 90-dist/5+(14 if cat else 0)-risk)))
            suggestions.append({'text_unverified':n['text'][:160], 'category_hint':cat,
                                'distance':round(dist,1), 'package_text_risk_heuristic':risk,
                                'score':score})
        suggestions.sort(key=lambda v:(-v['score'],v['distance']))
        top=suggestions[:3]
        out.append({'number_line':text[:160],'number_tokens':nums[:8],
                    'has_currency_marker':bool(CURRENCY.search(text)),
                    'name_candidates':top,'has_name_candidate':bool(top),
                    'has_category_hint':any(v['category_hint'] for v in top),
                    'price_verified':False,'publish_allowed':False})
    return out

def main():
    data=json.loads(SOURCE.read_text(encoding='utf-8'))
    report={'generated_at_jst':datetime.now(JST).isoformat(timespec='seconds'),
      'stage':'ONE_OFF_RELAXED_PRICE_CUES_REVIEW_ONLY','verified_products':0,'published_offers':0,
      'limitation':'Package print is NOT visually segmented; only low-confidence/Latin-heavy OCR text is down-ranked. All results unverified.',
      'flyers':[]}
    for flyer in data.get('items',[]):
        suggestions=evaluate(flyer) if flyer.get('status')=='ocr_generated_unverified' else []
        report['flyers'].append({'shop':flyer.get('shop','不明'),'source_url':flyer.get('source_url'),
          'status':flyer.get('status'),'candidate_count':len(suggestions),
          'with_name_count':sum(x['has_name_candidate'] for x in suggestions),
          'with_category_count':sum(x['has_category_hint'] for x in suggestions),
          'suggestions':suggestions})
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    sections=[]
    for f in report['flyers']:
        lst=[]
        for x in f['suggestions']:
            candidate=' / '.join(escape(n['text_unverified'])+(' ['+escape(n['category_hint'])+']' if n['category_hint'] else '') for n in x['name_candidates']) or 'なし'
            lst.append('<li><b>'+escape(x['number_line'])+'</b> → '+candidate+'</li>')
        sections.append('<section><h2>'+escape(f['shop'])+'</h2><p>価格候補 '+str(f['candidate_count'])+' ／ 周辺文字あり '+str(f['with_name_count'])+' ／ 分類候補あり '+str(f['with_category_count'])+'</p><ol>'+''.join(lst)+'</ol></section>')
    PAGE.write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>条件緩和OCR比較</title><style>body{font-family:system-ui;max-width:950px;margin:auto;padding:20px;background:#f5f6fa}section{padding:16px;border-radius:12px;background:white;margin:18px 0}li{margin:10px 0}</style><h1>価格記号の条件緩和テスト</h1><p>候補はすべて未確認。包装の印字を画像から判別したものではなく、OCR文字の特徴で低優先化した試作。商品名・価格の一致は保証しません。</p>'+''.join(sections)+'</html>',encoding='utf-8')
    print('Relaxed OCR:',sum(f['candidate_count'] for f in report['flyers']),'candidates,',sum(f['with_category_count'] for f in report['flyers']),'category hints; published 0')

if __name__=='__main__':main()
