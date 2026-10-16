#!/usr/bin/env python3
"""Conservative flyer price/category ranking; human review ONLY.

Reads data/flyer_fulltext_layout_review.json produced by scan_flyer_layout_v2.py.
Creates data/ranked_offer_candidates.json and ranked_offer_candidates.html.
Does not alter verified_offers.json, price_history.json, or index.html.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/flyer_fulltext_layout_review.json'
DEST = ROOT / 'data/ranked_offer_candidates.json'
PAGE = ROOT / 'ranked_offer_candidates.html'
JST = timezone(timedelta(hours=9))

# Japanese OCR may split currency signs and numerals across neighboring lines.
PRICE = re.compile(r'(?<![\d,])(?:[1-9]\d{0,3}|[1-9]\d{0,2}(?:,\d{3}){1,2})(?![\d,])')
CURRENCY = re.compile(r'(?:円|￥|¥|税込|税抜|税別|本体価格|販売価格|各\s*\d+\s*円)')
TAX_INC = re.compile(r'税込|税込価格|税込み')
TAX_EXC = re.compile(r'税抜|税別|本体価格')
UNIT = re.compile(r'(?:\d+(?:\.\d+)?\s*(?:g|kg|ml|mL|L|個|本|枚|袋|パック|人前|cm|㎝)|\d+\s*[%％])', re.I)
DATE = re.compile(r'(?:\d{1,2}\s*[/／月]\s*\d{1,2}(?:日)?|\d{4}年|\d{1,2}日限り|\d{1,2}:\d{2})')
PHONE = re.compile(r'(?:0\d{1,4}[-ー]\d{1,4}[-ー]\d{3,4})')
CATEGORY_TERMS = {
    '野菜': ['トマト','とまと','玉ねぎ','たまねぎ','キャベツ','レタス','白菜','大根','にんじん','人参','きゅうり','胡瓜','じゃがいも','ピーマン','ほうれん草','小松菜','チンゲン菜','ブロッコリー','もやし','ねぎ','葱'],
    '果物': ['りんご','リンゴ','林檎','みかん','バナナ','ぶどう','葡萄','梨','なし','柿','いちご','苺','キウイ','オレンジ','レモン','桃'],
    '精肉': ['牛肉','豚肉','鶏肉','牛こま','豚こま','もも肉','むね肉','ひき肉','挽肉','ロース','バラ肉','ささみ','ミンチ'],
    '鮮魚': ['まぐろ','マグロ','鮪','鮭','さけ','サーモン','さば','鯖','ぶり','鰤','しらす','たら','鯛','えび','海老','いか','イカ'],
    '乳製品・卵': ['牛乳','たまご','卵','ヨーグルト','チーズ','バター','豆乳'],
    'パン・麺・米': ['食パン','パン','うどん','そば','蕎麦','ラーメン','パスタ','米','精米','そうめん'],
    '飲料': ['お茶','茶','コーヒー','ジュース','天然水','炭酸水','サイダー'],
    '調味料・加工食品': ['醤油','しょうゆ','味噌','みそ','砂糖','塩','ケチャップ','マヨネーズ','カレー','ウインナー','ハム','豆腐','納豆']
}


def box_gap(a, b):
    x1, y1, w1, h1 = (int(a.get(k,0)) for k in ('left','top','width','height'))
    x2, y2, w2, h2 = (int(b.get(k,0)) for k in ('left','top','width','height'))
    dx = max(0, x2-(x1+w1), x1-(x2+w2))
    dy = max(0, y2-(y1+h1), y1-(y2+h2))
    return (dx*dx+dy*dy)**0.5


def classified(text):
    found=[]
    low=text.lower()
    for category,terms in CATEGORY_TERMS.items():
        for term in terms:
            if term.lower() in low:
                found.append({'category':category,'matched_term':term})
                break
    return found


def rank(flyer):
    lines=[x for x in flyer.get('lines',[]) if isinstance(x.get('box'),dict)]
    out=[]
    for line in lines:
        raw=line.get('text','')
        # Dates and unit quantities alone must not turn into sale prices.
        nums=PRICE.findall(raw)
        if not nums:
            continue
        nearby=sorted((x for x in lines if x is not line),key=lambda x:box_gap(line['box'],x['box']))[:18]
        close=[x for x in nearby if box_gap(line['box'],x['box'])<=170]
        related=' '.join(x.get('text','') for x in close)
        context=(raw+' '+related)
        has_currency=bool(CURRENCY.search(raw))
        neighboring_currency=bool(CURRENCY.search(related))
        # Do not infer taxes solely from the existence of a nearby sign.
        tax_label=('税込' if TAX_INC.search(raw) else '税抜・本体' if TAX_EXC.search(raw) else '不明')
        date_or_unit=bool(DATE.search(raw) or PHONE.search(raw) or UNIT.fullmatch(raw.strip()))
        category_matches=classified(related)
        best_label=next((x for x in close if classified(x.get('text',''))),None)
        conf=float(line.get('average_ocr_confidence') or 0)
        score=(35 if has_currency else 16 if neighboring_currency else 0)
        score+=(25 if TAX_INC.search(raw) or TAX_EXC.search(raw) else 0)
        score+=(20 if category_matches else 0)
        score+=(10 if best_label and box_gap(line['box'],best_label['box'])<100 else 0)
        score+=(10 if conf>=70 else 5 if conf>=45 else 0)
        score-=(45 if date_or_unit else 0)
        score=max(0,min(100,score))
        # Without explicit on-line currency or near currency, keep numeric text only as low priority.
        out.append({'raw_number_line':raw[:180], 'number_tokens':nums[:8],
                    'currency_on_same_line':has_currency,'currency_nearby':neighboring_currency,
                    'tax_label_on_same_line':tax_label,'date_or_quantity_risk':date_or_unit,
                    'categories_suggested':category_matches[:5],
                    'nearest_category_text':best_label.get('text','')[:120] if best_label else None,
                    'distance_to_category_text':round(box_gap(line['box'],best_label['box']),1) if best_label else None,
                    'box':line['box'],'ocr_confidence':conf,'score':score,
                    'priority':'high_review' if score>=75 else 'review' if score>=40 else 'low_review',
                    'status':'unverified','publish_allowed':False})
    return sorted(out,key=lambda x:(-x['score'],x['box'].get('top',0)))


def main():
    data=json.loads(SOURCE.read_text(encoding='utf-8'))
    report={'generated_at_jst':datetime.now(JST).isoformat(timespec='seconds'),
            'stage':'PRICE_CUE_CATEGORY_REVIEW_ONLY',
            'explanation':'Heuristic candidates only; nearby text may be unrelated; tax label applies only to its own OCR line.',
            'verified_products':0,'published_offers':0,'flyers':[]}
    for flyer in data.get('items',[]):
        candidates=rank(flyer)
        report['flyers'].append({'shop':flyer.get('shop'),'source_url':flyer.get('source_url'),
                                 'ocr_status':flyer.get('status'),'candidate_count':len(candidates),
                                 'high_review_count':sum(x['priority']=='high_review' for x in candidates),
                                 'candidates':candidates})
    DEST.parent.mkdir(parents=True,exist_ok=True)
    DEST.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    cards=[]
    for flyer in report['flyers']:
        lis=[]
        for c in flyer['candidates'][:300]:
            category='、'.join(x['category'] for x in c['categories_suggested']) or '不明'
            lis.append('<li><strong>'+escape(c['raw_number_line'])+'</strong> '
                +f'〔{c["score"]}点・{escape(c["priority"])}〕 分類候補：{escape(category)} '
                +'／近い文字：'+escape(c.get('nearest_category_text') or 'なし')+'</li>')
        cards.append('<section><h2>'+escape(flyer['shop'] or '店舗不明')+'</h2>'
                     +f'<p>{flyer["candidate_count"]}件の数字候補（高優先{flyer["high_review_count"]}件）</p>'
                     +'<ol>'+''.join(lis)+'</ol></section>')
    html=('<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
          '<title>通貨・分類辞書による価格候補</title><style>body{font-family:system-ui,sans-serif;max-width:950px;margin:auto;padding:18px;background:#f6f7fa;color:#182536}'
          'section{background:white;padding:16px;border-radius:12px;margin:16px 0}li{margin:10px 0;overflow-wrap:anywhere}</style>'
          '<h1>価格記号・分類辞書による候補</h1><p>すべて未確認です。数字、商品名、税込・税抜表示の対応を保証せず、価格比較へ自動登録しません。</p>'
          +''.join(cards)+'</html>')
    PAGE.write_text(html,encoding='utf-8')
    print('Review candidates:',sum(x['candidate_count'] for x in report['flyers']),
          'high priority:',sum(x['high_review_count'] for x in report['flyers']))

if __name__=='__main__': main()
