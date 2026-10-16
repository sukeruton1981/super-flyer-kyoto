"""Import verified public CSV feeds; never invent prices or availability."""
import csv, io, json, re, urllib.request
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
RUN_AT = datetime.now(JST).isoformat(timespec='minutes')
TODAY = datetime.now(JST).date().isoformat()
HISTORY = ROOT/'data/price_history.json'
CONFIG = ROOT/'data/sources.json'
BASE = ROOT/'base.html'
OUT = ROOT/'index.html'
FIELDS = {'product','category','spec','shop','price','unit','valid_from','valid_to','source_url'}

def valid(row):
    if not FIELDS.issubset(row): return None
    d={k:str(row.get(k,'')).strip() for k in FIELDS}
    if not all(d.values()): return None
    try:
        price=float(d['price']); begin=date.fromisoformat(d['valid_from']);end=date.fromisoformat(d['valid_to'])
        if not 0 < price < 10000000 or begin>end: return None
        if not d['source_url'].startswith('https://'): return None
    except (ValueError, OverflowError): return None
    d['price']=price
    return d

previous_status=json.loads((ROOT/'data/update_status.json').read_text(encoding='utf-8')) if (ROOT/'data/update_status.json').exists() else {}
cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
records=json.loads(HISTORY.read_text(encoding='utf-8'))
existing={(x['product'],x['spec'],x['shop'],x['price'],x['unit'],x['valid_from'],x['valid_to']) for x in records}
results=[]
for url in cfg.get('csv_urls',[]):
    if not isinstance(url,str) or not url.startswith('https://'):
        results.append({'source':str(url),'status':'invalid_url'});continue
    try:
        req=urllib.request.Request(url,headers={'User-Agent':'SuperFlyer/1.0 (public CSV ingest)'})
        with urllib.request.urlopen(req,timeout=18) as f:
            data=f.read(3_000_001)
        if len(data)>3_000_000: raise ValueError('CSV too large')
        reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
        count=0
        for row in reader:
            d=valid(row)
            if not d: continue
            key=(d['product'],d['spec'],d['shop'],d['price'],d['unit'],d['valid_from'],d['valid_to'])
            if key not in existing:
                records.append(d);existing.add(key);count+=1
        results.append({'source':url,'status':'ok','new_rows':count})
    except Exception as e:
        results.append({'source':url,'status':'error','detail':str(e)[:120]})

HISTORY.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
soup=BeautifulSoup(BASE.read_text(encoding='utf-8'),'html.parser')
container=soup.select_one('#cards')
# Only treat dated, verifiable records as currently active.
active=[r for r in records if r['valid_from']<=TODAY<=r['valid_to']]
groups={}
for r in active:
    key=(r['product'],r['spec'],r['unit'])
    groups.setdefault(key,[]).append(r)
# Keep old static archive but remove product rows where an up-to-date equivalent exists.
for c in list(container.select('article.card')):
    name_el=c.select_one('.product-name')
    spec_el=c.select_one('.spec')
    if not name_el or not spec_el:continue
    # Historical records are explicitly labeled, so they remain visible when exact comparison impossible.
    for product,spec,unit in groups:
        if name_el.get_text(' ',strip=True)==product and spec in spec_el.get_text(' ',strip=True):
            c.decompose();break
for idx,(key,offers) in enumerate(groups.items()):
    product,spec,unit=key
    ordered=sorted(offers,key=lambda x:x['price'])
    best=ordered[0]
    c=soup.new_tag('article',attrs={'class':'card','data-cat':best['category'],'data-date':TODAY,'data-i':'fresh-'+str(idx),'data-name':product+spec+' '+best['shop'],'data-price':str(best['price']),'data-shop':best['shop']})
    top=soup.new_tag('div',attrs={'class':'cardtop'})
    info=soup.new_tag('div');name=soup.new_tag('b',attrs={'class':'product-name'});name.string=product;info.append(name)
    marker=soup.new_tag('span',attrs={'class':'sale-tag'});marker.string='特売中';info.append(marker)
    sp=soup.new_tag('div',attrs={'class':'spec'});sp.string=spec+' · '+unit;info.append(sp);top.append(info)
    price=soup.new_tag('div',attrs={'class':'amount'});price.string='¥'+format(best['price'],',g');top.append(price);c.append(top)
    meta=soup.new_tag('div',attrs={'class':'meta'});meta.string='🏬 '+best['shop']+'　有効期間 '+best['valid_from']+'〜'+best['valid_to'];c.append(meta)
    category=soup.new_tag('div',attrs={'class':'catline'});tag=soup.new_tag('span');tag.string=best['category'];category.append(tag);c.append(category)
    detail=soup.new_tag('details');summary=soup.new_tag('summary');summary.string='特売店舗・価格を見る（'+str(len(offers))+'件）';detail.append(summary)
    for offer in ordered:
        line=soup.new_tag('div',attrs={'class':'offer'});line.string=f"{offer['shop']}：¥{offer['price']:g}　{offer['valid_from']}〜{offer['valid_to']}　"
        a=soup.new_tag('a',href=offer['source_url'],target='_blank',rel='noopener noreferrer');a.string='掲載元 ↗';line.append(a);detail.append(line)
    c.append(detail);container.insert(0,c)
# Use a note that reflects whether feeds exist, and never claim a successful daily refresh if missing.
warning=soup.select_one('.warning')
if warning:
    updated=sum(x.get('new_rows',0) for x in results)
    failed=sum(x['status']!='ok' for x in results)
    warning.string=(f'照合日：{TODAY}。当日有効な確認済み特売 {len(active)}件／新規取込 {updated}件／取得失敗 {failed}件。'
        + ('外部CSVの取得元が未設定です。毎朝9時の実価格自動取得はまだ動いていません。' if not cfg.get('csv_urls') else '対象外の商品は2026/10/16以前の保存記録です。最新の店頭価格ではありません。'))
# Display separately: execution time, confirmed data acquisition, and archive snapshot date.
status_bar=soup.select_one('.status')
last_success_at = RUN_AT if any(x.get('status')=='ok' for x in results) else previous_status.get('last_successful_source_check_at')
if status_bar:
    stamp=soup.new_tag('div',attrs={'id':'update-times','class':'update-times'})
    first=soup.new_tag('div');first.string='最終更新処理：'+RUN_AT.replace('T',' ')+'（日本時間）';stamp.append(first)
    second=soup.new_tag('div')
    second.string=('チラシ取得元の最終確認：'+last_success_at.replace('T',' ')+'（日本時間）') if last_success_at else 'チラシ取得元の最終確認：未取得'
    stamp.append(second)
    third=soup.new_tag('div');third.string='保存済み価格データ基準日：2026年10月16日';stamp.append(third)
    status_bar.insert_after(stamp)
    sty=soup.new_tag('style');sty.string='.update-times{font-size:12px;background:#e9f4ee;border:1px solid #c1decf;color:#244b39;border-radius:10px;padding:10px 13px;margin:0 0 12px;line-height:1.85}'
    soup.head.append(sty)
OUT.write_text(str(soup),encoding='utf-8')
(ROOT/'data/update_status.json').write_text(json.dumps({'checked_on':TODAY,'last_run_at':RUN_AT,'last_successful_source_check_at':last_success_at,'active_offers':len(active),'sources':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Checked',TODAY,'active',len(active),'sources',len(results))
