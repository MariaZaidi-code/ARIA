import json, sys, glob
sys.stdout.reconfigure(encoding='utf-8')
files = glob.glob(r'C:\Users\Go\Desktop\ARIA\data\schemas\user_437\*latest.json')
for f in files:
    with open(f) as fh:
        m = json.load(fh)
    cols = m.get('tables',{}).get('amazon',{}).get('columns',[])
    if not cols:
        continue
    di = m.get('data_intelligence',{})
    # Print just the top-level keys and tables summary
    print('Top keys:', list(di.keys()))
    tables = di.get('tables', [])
    print('Tables type:', type(tables).__name__)
    if isinstance(tables, list):
        for t in tables:
            if isinstance(t, dict):
                print('  Table:', t.get('table', t.get('name', '?')))
                print('    measures:', t.get('measures', []))
                print('    numerical:', t.get('numerical_columns', []))
                print('    dimensions:', t.get('dimensions', [])[:5])
    elif isinstance(tables, dict):
        for k, v in tables.items():
            print(f'  Table {k}:', type(v).__name__)
            if isinstance(v, dict):
                print('    measures:', v.get('measures', []))
    print('dataset_connected:', di.get('dataset_connected'))
    print('numeric_measures_available:', di.get('numeric_measures_available'))
    print('categorical_dimensions_available:', di.get('categorical_dimensions_available'))
    
    caps = m.get('capabilities')
    print('\nCapabilities:', json.dumps(caps, indent=2, default=str)[:500] if caps else 'None')
    break
