#!/usr/bin/env python3
"""Filter price-first OCR candidates for manual review only.

Input: data/flyer_fulltext_layout_review.json
Output: data/filtered_price_candidates.json, filtered_price_candidates.html
Never modifies published offers or price history.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/flyer_fulltext_layout_review.json'
REPORT = ROOT / 'data/filtered_price_candidates.json'
PAGE = ROOT / 'filtered_price_candidates.html'
JST = timezone(timedelta(hours=9))
# Full numeric tokens only; 10,000+ cannot be an accepted price.
NUMBER = re.compile(r'(?<![\d,])(?:\d{1,3}(?:,\d{3})+|\d+)(?![\d,])')
DATE = re.compile(r'\d{1,2}\s*[/／月]\s*\d{1,2}(?:日)?|\d{4}\s*年|\d{1,2}\s*日|\d{1,2}:\d{2}')
QUANTITY = re.compile(r'\d+\s*(?:人|名|家族|世帯|点|個|本|枚|袋|パック|g|kg|ml|mL|L|%|％)', re.I)
DISCOUNT = re.compile(r'\d+(?:\.\d+)?\s*(?:円\s*引(?:き)?|割\s*引(?:き)?|%\s*OFF|％\s*OFF|%|％)|\d+\s*ポイント', re.I)
CONTEXT = re.compile(r'ご家族|お一人様|おひとり様|先着|限定|限り|まで|ポイント|引換|チャンス|抽選|プレゼント|チャージ|[FＴT]EL|電話|FAX', re.I)
PRICE_MARK = re.compile(r'[円￥¥]|税込|税抜|本体価格|特価')
NAME_STOP = re.compile(r'税込|税抜|価格|ご家族|お一人様|先着|限定|限り|まで|より|割引|円引|ポイント|日限り|抽選|本日')
CATEGORY = {
    '野菜': ('トマト','きゅうり','玉ねぎ','たまねぎ','白菜','キャベツ','レタス','大根','人参','にんじん','ねぎ','じゃがいも','ピーマン','小松菜','チンゲン菜'),
    '果物': ('りんご','リンゴ','ふじ','みかん','バナナ','ぶどう','柿','梨','いちご','キウイ'),
    '精肉': ('牛肉','豚肉','鶏肉','ロース','ミンチ','もも肉','むね肉'),
    '鮮魚': ('まぐろ','鮭','サーモン','さば','ぶり','えび','いか'),
    '乳製品・卵': ('牛乳','ヨーグルト','チーズ','卵','たまご'),
    '米・パン・麺': ('お米','精米','食パン','うどん','そば','ラーメン'),
    '加工食品': ('醤油','しょうゆ','味噌','豆腐','ハム','ウインナー')
}

def category_for(txt):
    return next((k for k, words in CATEGORY.items() if any(w in txt for w in words)), None)

def rect_gap(a, b):
    dx = max(0, a['left']-b['left']-b['width'], b['left']-a['left']-a['width'])
    dy = max(0, a['top']-b['top']-b['height'], b['top']-a['top']-a['height'])
    return (dx*dx+dy*dy)**.5

def extract_price_tokens(text):
    if DATE.search(text) or DISCOUNT.search(text) or CONTEXT.search(text):
        return []
    candidates=[]
    for match in NUMBER.finditer(text):
        val = int(match.group().replace(',', ''))
        if not 1 <= val <= 9999:
            continue
        # Exclude numeric units immediately attached to the candidate.
        after=text[match.end():]
        before=text[:match.start()]
        if re.match(r'\s*(?:月|日|人|名|世帯|家族|点|個|本|枚|袋|g|kg|ml|mL|L|%|％)', after, re.I):
            continue
        if re.search(r'(?:第|約|最大)\s*$', before):
            continue
        if QUANTITY.fullmatch(text.strip()):
            continue
        candidates.append(val)
    return candidates

def name_ok(text):
    t=text.strip()
    if not 2 <= len(t) <= 90 or NAME_STOP.search(t) or DATE.search(t) or DISCOUNT.search(t):
        return False
    if not any('\u3040' <= c <= '\u30ff' or '\u3400' <= c <= '\u9fff' for c in t):
        return False
    return not (sum(c.isdigit() for c in t) > len(t)//2)

def process(flyer):
    lines=[l for l in flyer.get('lines',[]) if isinstance(l.get('box'),dict) and l.get('text')]
    result=[]
    for line in lines:
        text=line['text']
        nums=extract_price_tokens(text)
        if not nums:
            continue
        neighbors=[]
        for other in lines:
            if other is line or not name_ok(other['text']):
                continue
            distance=rect_gap(line['box'],other['box'])
            if distance>220:
                continue
            cat=category_for(other['text'])
            confidence=float(other.get('average_ocr_confidence') or 0)
            score=round(max(0, min(100, 65-distance/6+(18 if cat else 0)+confidence/10)))
            neighbors.append({'text_unverified':other['text'][:120], 'category_hint':cat,
                              'distance_px':round(distance,1),'review_score':score})
        neighbors.sort(key=lambda n:(-n['review_score'],n['distance_px']))
        result.append({'raw_text':text[:160], 'number_candidates':nums[:6],
                       'currency_cue':bool(PRICE_MARK.search(text)), 'nearby_name_candidates':neighbors[:3],
                       'status':'unverified', 'publish_allowed':False})
    return result

def main():
    source=json.loads(SOURCE.read_text(encoding='utf-8'))
    flyers=[]
    for f in source.get('items',[]):
        c=process(f) if f.get('status') == 'ocr_generated_unverified' else []
        flyers.append({'shop':f.get('shop','不明'), 'source_url':f.get('source_url'),
                       'source_status':f.get('status'),'candidate_count':len(c),
                       'with_name_count':sum(bool(x['nearby_name_candidates']) for x in c),
                       'candidates':c})
    report={'generated_at_jst':datetime.now(JST).isoformat(timespec='seconds'),
            'stage':'RULE_FILTERED_PRICE_REVIEW_ONLY', 'verified_products':0,'published_offers':0,
            'note':'OCR and package/photo separation are not verified. Numbers and nearest words can still be wrong.',
            'flyers':flyers}
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    blocks=[]
    for f in flyers:
        lis=[]
        for c in f['candidates']:
            names=' / '.join(escape(n['text_unverified']) for n in c['nearby_name_candidates']) or 'なし'
            lis.append(f'<li>{escape(c["raw_text"])} → {names}（未確認）</li>')
        blocks.append(f'<section><h2>{escape(f["shop"])}</h2><p>候補 {f["candidate_count"]} 行、名前候補あり {f["with_name_count"]} 行</p><ol>{"".join(lis)}</ol></section>')
    PAGE.write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>除外ルール付き価格候補</title><style>body{font-family:system-ui,sans-serif;max-width:950px;margin:auto;padding:18px;background:#f6f7fa}section{padding:14px;background:white;border-radius:12px;margin:16px 0}li{margin:10px 0}</style><h1>価格候補（未確認）</h1><p>10000円以上、日付、数量、割引、購入制限などを除外する試作。画像内のパッケージ文字の厳密な除外は未実装。価格として公開しません。</p>'+''.join(blocks)+'</html>',encoding='utf-8')
    print('Filtered candidates:',sum(f['candidate_count'] for f in flyers),'published 0')

if __name__=='__main__':
    main()
