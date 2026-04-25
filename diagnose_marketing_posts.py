"""
Diagnostic script — reads 홈페이지게시물 tab RAW (no filtering, no modification).
Run from the K.ID soft project root:
    python diagnose_marketing_posts.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gspread
from google.oauth2.service_account import Credentials
import config

KEY_PATH   = config.KEY_PATH
SHEET_KEY  = config.SHEET_KEY
TAB_NAME   = config.MARKETING_POSTS_SHEET_NAME   # "홈페이지게시물"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

print("=" * 60)
print("DIAGNOSE: 홈페이지게시물 tab")
print("=" * 60)
print(f"Sheet key : {SHEET_KEY}")
print(f"Tab name  : {TAB_NAME}")
print(f"Key path  : {KEY_PATH}")
print()

try:
    creds  = Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
    client = gspread.authorize(creds)
    sh     = client.open_by_key(SHEET_KEY)
    print(f"All tabs in workbook: {[ws.title for ws in sh.worksheets()]}")
    print()

    try:
        ws = sh.worksheet(TAB_NAME)
    except gspread.WorksheetNotFound:
        print(f"ERROR: Tab '{TAB_NAME}' does NOT exist in this spreadsheet!")
        print("  → The tab was never created, or it was deleted.")
        print("  → Check Google Sheets version history for the spreadsheet.")
        sys.exit(1)

    raw = ws.get_all_values()
    print(f"Raw row count (including header): {len(raw)}")
    print()

    if not raw:
        print("RESULT: Tab exists but is COMPLETELY EMPTY (no header, no data).")
        print("  → Posts were likely never written here, or the sheet was cleared.")
        sys.exit(0)

    header = raw[0]
    print(f"Current header row ({len(header)} columns):")
    for i, h in enumerate(header):
        print(f"  [{i}] '{h}'")
    print()

    data_rows = raw[1:]
    print(f"Data rows (posts): {len(data_rows)}")
    print()

    if not data_rows:
        print("RESULT: Header exists but NO data rows — all posts are gone.")
        print("  → Check Google Sheets version history to recover deleted rows.")
        sys.exit(0)

    # ── Try get_all_records() to see what the API-level read returns ──────────
    try:
        records = ws.get_all_records()
        print(f"get_all_records() returned {len(records)} records")
    except Exception as e:
        print(f"get_all_records() FAILED: {e}")
        records = []

    print()
    print("Post summary (raw values, no filter applied):")
    print("-" * 60)
    id_idx    = header.index("id")    if "id"           in header else None
    title_idx = header.index("title") if "title"        in header else None
    slug_idx  = header.index("slug")  if "slug"         in header else None
    pub_idx   = header.index("is_published") if "is_published" in header else None

    for i, row in enumerate(data_rows, start=1):
        rid   = row[id_idx][:8]    if id_idx    is not None and id_idx    < len(row) else "?"
        title = row[title_idx][:40] if title_idx is not None and title_idx < len(row) else "?"
        slug  = row[slug_idx][:30]  if slug_idx  is not None and slug_idx  < len(row) else "?"
        pub   = row[pub_idx]        if pub_idx   is not None and pub_idx   < len(row) else "?"
        print(f"  Row {i:2d} | id={rid}.. | pub={pub:6s} | slug={slug} | title={title}")

    print()
    published_count = 0
    if pub_idx is not None:
        published_count = sum(
            1 for row in data_rows
            if pub_idx < len(row) and str(row[pub_idx]).upper() in ("TRUE", "Y", "1")
        )
    print(f"Published posts (is_published=TRUE): {published_count}/{len(data_rows)}")

    # ── Check what the marketing router _read_posts() actually returns ────────
    print()
    print("Simulating _read_posts() (uses get_all_records):")
    if records:
        published_via_api = [
            p for p in records
            if str(p.get("is_published", "")).upper() in ("TRUE", "Y", "1")
        ]
        print(f"  Total records: {len(records)}")
        print(f"  Published: {len(published_via_api)}")
        for p in published_via_api:
            print(f"    slug={p.get('slug','?')[:30]}  title={str(p.get('title','?'))[:40]}")
    else:
        print("  get_all_records() returned 0 or failed — this is why posts aren't showing!")

except Exception as e:
    print(f"FATAL ERROR: {e}")
    import traceback; traceback.print_exc()
