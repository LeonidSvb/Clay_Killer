import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'), override=True)

import pandas as pd
from core.db import import_csv_to_db, get_leads_master_count, is_connected

print('Connected:', is_connected())

path = r'C:\Users\79818\Desktop\Leads\EURope- recruit - withemails.csv'
df = pd.read_csv(path, dtype=str, keep_default_na=False)
print(f'Rows: {len(df)}, cols: {list(df.columns)}')

rows = df.head(5).to_dict(orient='records')
print('Sample email:', rows[0].get('Email'))

result = import_csv_to_db(rows, 'EU Recruit Test', 'EURope- recruit - withemails.csv')
print('Result:', result)
print('Total in leads_master:', get_leads_master_count())
