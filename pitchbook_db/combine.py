import pandas as pd
import os
import warnings
warnings.filterwarnings('ignore')

BASE = r'C:\Users\79818\Desktop\tests\pitchbook_db'
OUTPUT = os.path.join(BASE, 'all_leads.csv')

OUT_COLS = ['first_name', 'last_name', 'email', 'phone', 'title',
            'company_name', 'city', 'state', 'country', 'zip',
            'address', 'revenue', 'source', 'pitchbook_url']

all_records = []
processed = 0
skipped = 0


def clean(val):
    s = str(val).strip()
    return '' if s in ('nan', 'None', 'NaT', '-', 'N/A') else s


def from_obfuscated(df, source):
    rows = []
    for _, r in df.iterrows():
        email = clean(r.get('ellipsis 6', ''))
        if '@' not in email:
            email = ''
        rows.append({
            'first_name': clean(r.get('entity-hover', '')),
            'last_name': clean(r.get('entity-hover 2', '')),
            'email': email,
            'phone': clean(r.get('ellipsis 5', '')),
            'title': clean(r.get('ellipsis 14', r.get('ellipsis', ''))),
            'company_name': clean(r.get('entity-hover 3', '')),
            'city': clean(r.get('ellipsis 7', '')),
            'state': clean(r.get('ellipsis 11', '')),
            'country': clean(r.get('ellipsis 13', '')),
            'zip': clean(r.get('ellipsis 12', '')),
            'address': clean(r.get('ellipsis 9', '')),
            'revenue': '',
            'source': source,
            'pitchbook_url': clean(r.get('entity-hover href', '')),
        })
    return rows


def get_col(col_map, *keys):
    for k in keys:
        if k in col_map:
            return col_map[k]
    return None


def from_clean(df, source):
    col_map = {c.lower().strip(): c for c in df.columns}
    name_col = get_col(col_map, 'contact name', 'primary contact', 'name')
    company_col = get_col(col_map, 'company name', 'business name', 'dba')
    email_col = get_col(col_map, 'email')
    phone_col = get_col(col_map, 'phone number', 'number', 'company phone', 'main phone')
    title_col = get_col(col_map, 'title')
    city_col = get_col(col_map, 'city')
    state_col = get_col(col_map, 'state')
    zip_col = get_col(col_map, 'zip code', 'zip')
    addr_col = get_col(col_map, 'address line 1', 'address')
    rev_col = get_col(col_map, 'revenue')
    pb_col = get_col(col_map, 'pitchbook', 'entity-hover href', 'ellipsis href')

    rows = []
    for _, r in df.iterrows():
        name = clean(r[name_col]) if name_col else ''
        parts = name.split(' ', 1)
        first = parts[0] if parts else ''
        last = parts[1] if len(parts) > 1 else ''

        email = clean(r[email_col]) if email_col else ''
        if '@' not in email:
            email = ''

        rows.append({
            'first_name': first,
            'last_name': last,
            'email': email,
            'phone': clean(r[phone_col]) if phone_col else '',
            'title': clean(r[title_col]) if title_col else '',
            'company_name': clean(r[company_col]) if company_col else '',
            'city': clean(r[city_col]) if city_col else '',
            'state': clean(r[state_col]) if state_col else '',
            'country': '',
            'zip': clean(r[zip_col]) if zip_col else '',
            'address': clean(r[addr_col]) if addr_col else '',
            'revenue': clean(r[rev_col]) if rev_col else '',
            'source': source,
            'pitchbook_url': clean(r[pb_col]) if pb_col else '',
        })
    return rows


def process_file(filepath):
    global processed, skipped
    fname = os.path.basename(filepath)
    ext = fname.lower().split('.')[-1]
    source = fname.replace('.csv', '').replace('.xlsx', '')

    try:
        if ext == 'csv':
            df = pd.read_csv(filepath, low_memory=False, encoding='utf-8', encoding_errors='replace')
        elif ext == 'xlsx':
            df = pd.read_excel(filepath)
        else:
            return []

        if df.empty:
            return []

        cols = list(df.columns)
        if 'entity-hover' in cols or 'ellipsis' in cols:
            rows = from_obfuscated(df, source)
        else:
            rows = from_clean(df, source)

        processed += 1
        print(f'  OK  {len(rows):>6} rows  {fname[:60]}')
        return rows

    except Exception as e:
        skipped += 1
        print(f'  ERR {fname[:60]}: {e}')
        return []


print('Scanning files...')
for root, dirs, files in os.walk(BASE):
    for fname in files:
        ext = fname.lower().split('.')[-1]
        if ext not in ('csv', 'xlsx'):
            continue
        if fname == 'all_leads.csv':
            continue
        if fname == 'combine.py':
            continue
        fp = os.path.join(root, fname)
        rows = process_file(fp)
        all_records.extend(rows)

print(f'\nTotal raw records: {len(all_records):,}')
print('Building DataFrame...')

df_all = pd.DataFrame(all_records, columns=OUT_COLS)

print(f'Before dedup: {len(df_all):,}')
df_email = df_all[df_all['email'] != ''].drop_duplicates(subset=['email'])
df_no_email = df_all[df_all['email'] == ''].drop_duplicates(subset=['first_name', 'last_name', 'company_name'])
df_final = pd.concat([df_email, df_no_email], ignore_index=True)
print(f'After dedup:  {len(df_final):,}')

print(f'Saving to {OUTPUT}...')
df_final.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
print(f'Done. Files processed: {processed}, skipped: {skipped}')
print(f'Output: {OUTPUT}')
