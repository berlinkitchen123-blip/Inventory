#!/usr/bin/env python3
"""
NRW Stock Filler — Apicbase Upload Skill
=========================================
Usage: python fill_apicbase_stock.py

Reads stock-patch.json (built from invoices) and fills
bella-bona-gmbh-nrw_inventory_ingredient_list.xlsx
with par, minimum amount, and storage location.
ONLY fills rows where product name EXACTLY matches an invoiced item.
ALL other rows are left completely untouched.

Workflow:
  1. Invoice arrives (email) → stock-patch.json is updated
  2. Run this script → docs/bella-bona-gmbh-nrw_inventory_ingredient_list.xlsx updated
  3. Git push → file live on GitHub
  4. Download from site → upload to Apicbase → stock created automatically

Price note: Both Metro and Chefs Culinar invoice NETTO prices (excl. VAT).
  Food items: Netto × 1.07 = Brutto
  Equipment:  Netto × 1.19 = Brutto
  Apicbase par column = quantity ordered (kg/l/pcs) — NOT price.
"""

import json, openpyxl, shutil, os
from pathlib import Path

BASE    = Path(__file__).parent.parent
STOCK   = BASE / 'data' / 'stock-patch.json'
TEMPLATE= BASE / 'docs'  / 'bella-bona-gmbh-nrw_inventory_ingredient_list.xlsx'
OUT     = BASE / 'docs'  / 'bella-bona-gmbh-nrw_inventory_ingredient_list.xlsx'

STORAGE_MAP = {
    # keyword → storage location
    'broccoli':'Freezer','spinach':'Freezer','edamame':'Freezer','peas':'Freezer',
    'frozen':'Freezer','gyoza':'Freezer','phanaeng':'Freezer','heat to eat':'Freezer',
    'smoked tofu':'Freezer','green beans':'Freezer',
    'chicken':'Fridge','bacon':'Fridge','cheese':'Fridge','cream':'Fridge',
    'milk':'Fridge','egg':'Fridge','feta':'Fridge','mozzarella':'Fridge',
    'tuna':'Fridge','salmon':'Fridge','yogurt':'Fridge','tofu':'Fridge',
    'arugula':'Fridge','baby spinach':'Fridge','basil':'Fridge','carrot':'Fridge',
    'champignon':'Fridge','cherry tomato':'Fridge','cucumber':'Fridge',
    'iceberg':'Fridge','mint':'Fridge','parsley':'Fridge','radicchio':'Fridge',
    'red bell pepper':'Fridge','regular tomato':'Fridge','small potato':'Fridge',
    'zucchini':'Fridge','celeriac':'Fridge','lime juice':'Fridge',
    'pesto':'Fridge','cooking cream':'Fridge',
}

def get_storage(name):
    nl = name.lower()
    for key, loc in STORAGE_MAP.items():
        if key in nl:
            return loc
    return 'Dry Store'

def build_stock_map():
    with open(STOCK) as f:
        d = json.load(f)
    m = {}
    for v in d['nrw_stock']['items'].values():
        m[v['name'].lower().strip()] = (v['qty'], v.get('unit','kg'))
    return m

def fill():
    stock_map = build_stock_map()
    wb = openpyxl.load_workbook(OUT)
    ws = wb['Inventory stock items list']
    rows = list(ws.iter_rows(values_only=True))

    updated = 0
    for excel_row_idx, row_data in enumerate(rows[2:], start=3):
        product = row_data[1]
        if not product:
            continue
        pl = str(product).lower().strip()
        if pl in stock_map:
            qty, unit = stock_map[pl]
            loc = get_storage(str(product))
            ws.cell(row=excel_row_idx, column=6, value=qty)
            ws.cell(row=excel_row_idx, column=7, value=round(qty * 0.2, 2))
            ws.cell(row=excel_row_idx, column=8, value=loc)
            updated += 1
        # else: leave completely untouched

    # Also handle Lentil Stew smart-quote variant
    for row in ws.iter_rows():
        v = row[1].value
        if v and 'Lentil Stew' in str(v) and 'Feijoada' in str(v):
            key = 'heat to eat: lentil stew \u201cfeijoada style\u201d'
            if key in stock_map:
                qty, unit = stock_map[key]
                row[5].value = qty
                row[6].value = round(qty * 0.2, 2)
                row[7].value = 'Freezer'
                updated += 1

    wb.save(OUT)
    print(f'✅ Done: {updated} rows filled, rest untouched')
    print(f'   File: {OUT}')

if __name__ == '__main__':
    fill()
