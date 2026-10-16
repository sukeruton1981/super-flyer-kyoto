"""Build an audit/review queue from discovered flyer image links.

No OCR or product prices are inferred. Approved flyer-level date ranges
are used ONLY for review prioritization, never to publish product offers.
Run from repo root: python scripts/build_flyer_review.py
"""
import json
from datetime import datetime, timezone, timedelta, date
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
DISCOVERED=ROOT/'data/discovered_flyers.json'
PERIODS=ROOT/'data/verified_flyer_periods.json'
QUEUE=ROOT/'data/flyer_review_queue.json'
PAGE=ROOT/'flyer_review.html'
JST=timezone(timedelta(hours=9))

def iso_date(x):
    return date.fromisoformat(x)

def main():
    data=json.loads(DISCOVERED.read_text(encoding='utf-8'))
    annotations=json.loads(PERIODS.read_text(encoding='utf-8'))
    by_url={entry['url']:entry for entry in annotations['flyers']}
    today=datetime.now(JST).date()
    reviewed=[]
    for item in data.get('flyers',[]):
        url=item.get('url','')
        if urlsplit(url).scheme!='https':
            continue
        meta=by_url.get(url)
        entry={'shop':item.get('shop',''), 'url':url,
               'first_seen_at_jst':item.get('first_seen_at_jst'),
               'flyer_date_status':'unverified', 'offer_import_allowed':False}
        if meta:
            start,end=iso_date(meta['flyer_valid_from']),iso_date(meta['flyer_valid_to'])
            if start>end: raise ValueError('Invalid flyer date range')
            entry.update(flyer_date_status='confirmed_flyer_level',flyer_valid_from=start.isoformat(),
                         flyer_valid_to=end.isoformat(),evidence=meta.get('evidence',''),
                         product_level_dates_confirmed=False)
            entry['review_priority']='current_flyer' if start<=today<=end else 'expired_flyer'
        else:
            entry['review_priority']='needs_date_review'
        reviewed.append(entry)
    reviewed.sort(key=lambda x:({'current_flyer':0,'needs_date_review':1,'expired_flyer':2}[x['review_priority']],x['url']))
    report={'generated_at_jst':datetime.now(JST).isoformat(timespec='seconds'),
            'image_links':len(reviewed),'confirmed_flyer_dates':sum(x['flyer_date_status']=='confirmed_flyer_level' for x in reviewed),
            'ready_for_automatic_product_price_import':0,
            'note':'Flyer-level dates do not prove individual product validity; no OCR or prices imported.',
            'items':reviewed}
    QUEUE.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    blocks=[]
    for x in reviewed:
        url=escape(x['url'],quote=True)
        label={'current_flyer':'掲載期間内・要商品確認','expired_flyer':'期間終了・履歴候補','needs_date_review':'期間未確認'}[x['review_priority']]
        dates=(x.get('flyer_valid_from','?')+' 〜 '+x.get('flyer_valid_to','?'))
        blocks.append(f'<article><a href="{url}" target="_blank" rel="noopener noreferrer"><img src="{url}" loading="lazy" alt="チラシ画像"></a><h2>{escape(x["shop"])}</h2><p>{label}<br>チラシ期間: {escape(dates)}</p><a href="{url}" target="_blank" rel="noopener noreferrer">元画像を確認 ↗</a></article>')
    html='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>チラシ画像確認一覧</title><style>body{font-family:system-ui,sans-serif;background:#f4f6f9;color:#19232e;margin:0;padding:20px}header{max-width:1100px;margin:auto}main{max-width:1100px;margin:20px auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:18px}article{background:white;border:1px solid #ddd;border-radius:12px;padding:12px}img{width:100%;height:330px;object-fit:contain;background:#eee}a{color:#12549d}p{line-height:1.5}small{color:#555}</style><header><h1>チラシ画像確認一覧</h1><p>自動検出した画像の確認用。チラシ期間は商品ごとの特売期間と異なる場合があります。</p><small>画像の表示は掲載元サイトの設定・利用条件に依存します。商品価格は未取得です。</small></header><main>'''+''.join(blocks)+'</main></html>'
    PAGE.write_text(html,encoding='utf-8')
    print(f'Review queue: {len(reviewed)} images, flyer-level dates confirmed: {report["confirmed_flyer_dates"]}; imported offers: 0')

if __name__=='__main__':main()
