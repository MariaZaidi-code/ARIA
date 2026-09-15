import sqlite3, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

# Get unique table names from all user databases
dbs = glob.glob(r'C:\Users\Go\Desktop\ARIA\data\uploads\user_*\*.db')
seen = {}
for db_path in sorted(dbs, key=os.path.getmtime, reverse=True):
    try:
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        for t in tables:
            if t not in seen:
                seen[t] = os.path.basename(db_path).replace('.db','')
    except:
        pass

print("TABLE NAMES IN DATABASES:")
for t, src in sorted(seen.items()):
    print(f"  {t}  (from {src})")
