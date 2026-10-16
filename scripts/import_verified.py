"""Import manually verified dated offers into the existing price history.

Run from repository root: python scripts/import_verified.py
Source: data/verified_offers.json. Does not scrape web pages or infer sale dates.
"""
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'data' / 'verified_offers.json'
HISTORY = ROOT / 'data' / 'price_history.json'
REQUIRED = ('product', 'category', 'spec', 'shop', 'price', 'unit', 'valid_from', 'valid_to', 'source_url')

def verified(row):
    if not isinstance(row, dict) or any(not str(row.get(k, '')).strip() for k in REQUIRED):
        return None
    if row.get('verification_status') != 'verified':
        return None
    try:
        start = date.fromisoformat(str(row['valid_from']))
        end = date.fromisoformat(str(row['valid_to']))
        price = float(row['price'])
        u = urlsplit(str(row['source_url']))
    except (ValueError, TypeError, OverflowError):
        return None
    if start > end or not 0 < price < 10_000_000 or not (u.scheme == 'https' and u.hostname and not u.username and not u.password):
        return None
    return {k: price if k == 'price' else str(row[k]).strip() for k in REQUIRED}

def main():
    submitted = json.loads(INPUT.read_text(encoding='utf-8'))
    if not isinstance(submitted, list):
        raise ValueError('verified_offers.json must contain a list')
    saved = json.loads(HISTORY.read_text(encoding='utf-8'))
    if not isinstance(saved, list):
        raise ValueError('price_history.json must contain a list')
    keys = lambda item: tuple(str(item[k]) for k in REQUIRED)
    existing = {keys(item) for item in saved}
    accepted = skipped = 0
    for item in submitted:
        offer = verified(item)
        if offer is None:
            skipped += 1
            continue
        key = keys(offer)
        if key not in existing:
            saved.append(offer)
            existing.add(key)
            accepted += 1
    if accepted:
        HISTORY.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'New verified offers: {accepted}; skipped unverified/invalid: {skipped}; historical records: {len(saved)}')

if __name__ == '__main__':
    main()
