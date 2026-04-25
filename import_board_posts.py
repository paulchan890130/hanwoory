"""
Safe upsert-by-slug import for TXT required-document guide posts.

RULES:
  - Never clears the sheet.
  - Never overwrites posts whose slug is NOT in the TXT files.
  - If slug already exists → updates that post only.
  - If slug does not exist → appends a new post.
  - is_published = TRUE for all files with 공개여부: 공개.

Run from the K.ID soft project root:
    python import_board_posts.py [--dry-run]

With --dry-run: prints what would happen without touching Google Sheets.
"""
import sys, os, re, uuid, datetime, pathlib, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TXT_DIR = pathlib.Path(__file__).parent / "hanwoori_required_documents_original_txt"
CREATED_BY = "hanwoory"

# ── 17-column header (matches current backend/routers/marketing.py) ────────────
MARKETING_HEADER = [
    "id", "title", "slug", "category", "summary", "content",
    "thumbnail_url", "is_published", "is_featured",
    "created_by", "created_at", "updated_at",
    "image_file_id", "image_url", "image_alt",
    "meta_description", "tags",
]


# ── TXT parser ────────────────────────────────────────────────────────────────

def _parse_txt(path: pathlib.Path) -> dict | None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    fields: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False

    for line in lines:
        if in_body:
            body_lines.append(line)
            continue

        if line.strip() == "본문:":
            in_body = True
            continue

        for key, field in [
            ("제목:",       "title"),
            ("슬러그 제안:", "slug"),
            ("카테고리:",   "category"),
            ("요약:",       "summary"),
            ("메타설명:",   "meta_description"),
            ("태그:",       "tags"),
            ("공개여부:",   "is_published_raw"),
        ]:
            if line.startswith(key):
                fields[field] = line[len(key):].strip()
                break

    if "title" not in fields:
        return None

    raw_pub = fields.get("is_published_raw", "")
    is_published = "TRUE" if raw_pub.strip() in ("공개", "TRUE", "Y", "1") else "FALSE"

    content = "\n".join(body_lines).strip()

    return {
        "title":            fields.get("title", ""),
        "slug":             fields.get("slug", ""),
        "category":         fields.get("category", ""),
        "summary":          fields.get("summary", ""),
        "content":          content,
        "thumbnail_url":    "",
        "is_published":     is_published,
        "is_featured":      "FALSE",
        "created_by":       CREATED_BY,
        "image_file_id":    "",
        "image_url":        "",
        "image_alt":        "",
        "meta_description": fields.get("meta_description", ""),
        "tags":             fields.get("tags", ""),
    }


# ── Google Sheets helpers ─────────────────────────────────────────────────────

def _get_worksheet():
    import gspread
    from google.oauth2.service_account import Credentials
    import config

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_file(config.KEY_PATH, scopes=scopes)
    client = gspread.authorize(creds)
    sh     = client.open_by_key(config.SHEET_KEY)

    tab_name = config.MARKETING_POSTS_SHEET_NAME  # "홈페이지게시물"
    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        ws = sh.add_worksheet(title=tab_name, rows=2000, cols=len(MARKETING_HEADER) + 2)

    return ws


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _read_existing(ws) -> tuple[list[str], dict[str, int], list[list[str]]]:
    """Returns (header, slug→row_no mapping, raw values)."""
    values = ws.get_all_values()
    if not values:
        return [], {}, []

    header = values[0]
    slug_col = header.index("slug") if "slug" in header else None
    slug_to_row: dict[str, int] = {}
    if slug_col is not None:
        for r_i, row in enumerate(values[1:], start=2):
            if slug_col < len(row):
                s = str(row[slug_col]).strip()
                if s:
                    slug_to_row[s] = r_i

    return header, slug_to_row, values


def _ensure_header(ws, current_header: list[str]) -> None:
    """If the sheet header is missing or outdated, update row 1 only."""
    last_col = _col_letter(len(MARKETING_HEADER))
    ws.update(
        f"A1:{last_col}1",
        [MARKETING_HEADER],
        value_input_option="USER_ENTERED",
    )


# ── Main import logic ─────────────────────────────────────────────────────────

def run(dry_run: bool = False) -> None:
    print("=" * 60)
    print(f"IMPORT board posts - {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 60)

    # 1. Scan TXT files (skip files starting with "00_")
    txt_files = sorted(
        p for p in TXT_DIR.glob("*.txt")
        if not p.name.startswith("00_")
    )
    print(f"\nTXT files found: {len(txt_files)}")

    # 2. Parse all TXT files
    parsed: list[tuple[pathlib.Path, dict]] = []
    skipped: list[tuple[str, str]] = []

    for p in txt_files:
        data = _parse_txt(p)
        if data is None:
            skipped.append((p.name, "제목: 필드 없음 — 파싱 실패"))
            continue
        if not data["title"]:
            skipped.append((p.name, "제목 비어 있음"))
            continue
        if not data["slug"]:
            skipped.append((p.name, "슬러그 제안: 비어 있음"))
            continue
        parsed.append((p, data))

    print(f"Parsed successfully: {len(parsed)}")
    print(f"Skipped: {len(skipped)}")
    for fname, reason in skipped:
        print(f"  SKIP {fname}: {reason}")

    if not parsed:
        print("\nNothing to import.")
        return

    # 3. Connect to sheet (unless dry-run)
    ws = None
    slug_to_row: dict[str, int] = {}
    raw_values: list[list[str]] = []
    sheet_header: list[str] = []

    if not dry_run:
        print("\nConnecting to Google Sheets …")
        ws = _get_worksheet()
        sheet_header, slug_to_row, raw_values = _read_existing(ws)

        existing_post_count = len(raw_values) - 1 if raw_values else 0
        print(f"Existing posts in sheet: {existing_post_count}")
        print(f"Current sheet header columns: {len(sheet_header)}")

        # Update header to 17 columns if needed (safe — does not touch data rows)
        if sheet_header != MARKETING_HEADER:
            print(f"Updating header from {len(sheet_header)} → {len(MARKETING_HEADER)} columns …")
            _ensure_header(ws, sheet_header)
            # Re-read so slug_to_row remains valid (header update doesn't move rows)
            sheet_header, slug_to_row, raw_values = _read_existing(ws)
    else:
        print("\n[DRY RUN] Would connect to Google Sheets.")
        print(f"[DRY RUN] Would check existing slugs for conflicts.")

    # 4. Classify: update vs create
    to_update: list[tuple[pathlib.Path, dict, int]] = []   # (path, data, row_no)
    to_create: list[tuple[pathlib.Path, dict]] = []         # (path, data)

    for p, data in parsed:
        slug = data["slug"]
        if slug in slug_to_row:
            to_update.append((p, data, slug_to_row[slug]))
        else:
            to_create.append((p, data))

    print(f"\nPosts to UPDATE (slug match): {len(to_update)}")
    for p, data, row_no in to_update:
        print(f"  UPDATE row {row_no}: slug={data['slug'][:50]}")

    print(f"Posts to CREATE (new slug):  {len(to_create)}")
    for p, data in to_create:
        print(f"  CREATE: slug={data['slug'][:50]}")

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return

    # 5. Apply updates
    now = datetime.datetime.now().isoformat()
    last_col = _col_letter(len(MARKETING_HEADER))

    if to_update:
        print("\nApplying updates …")
        # Re-read existing rows to merge (preserve id, created_at, created_by)
        id_idx = MARKETING_HEADER.index("id")
        ca_idx = MARKETING_HEADER.index("created_at")
        cb_idx = MARKETING_HEADER.index("created_by")

        batch_updates = []
        for p, data, row_no in to_update:
            # Fetch the existing row to preserve id, created_at, created_by
            existing_row = raw_values[row_no - 1]  # raw_values[0] = header, [1]=row2, etc.
            existing_id = existing_row[id_idx] if id_idx < len(existing_row) else ""
            existing_ca = existing_row[ca_idx] if ca_idx < len(existing_row) else ""
            existing_cb = existing_row[cb_idx] if cb_idx < len(existing_row) else CREATED_BY

            merged = {
                **data,
                "id":         existing_id or str(uuid.uuid4()),
                "created_at": existing_ca or now,
                "created_by": existing_cb,
                "updated_at": now,
            }
            row_vals = [str(merged.get(c, "")) for c in MARKETING_HEADER]
            batch_updates.append({
                "range":  f"A{row_no}:{last_col}{row_no}",
                "values": [row_vals],
            })

        ws.batch_update(batch_updates, value_input_option="USER_ENTERED")
        print(f"  Updated {len(to_update)} post(s).")

    # 6. Apply creates
    if to_create:
        print("\nAppending new posts …")
        new_rows = []
        for p, data in to_create:
            row = {
                **data,
                "id":         str(uuid.uuid4()),
                "created_at": now,
                "updated_at": now,
            }
            new_rows.append([str(row.get(c, "")) for c in MARKETING_HEADER])

        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"  Created {len(to_create)} new post(s).")

    # 7. Summary
    print("\n" + "=" * 60)
    print("IMPORT COMPLETE")
    print(f"  Created : {len(to_create)}")
    print(f"  Updated : {len(to_update)}")
    print(f"  Skipped : {len(skipped)}")
    print()
    print("Slugs created:")
    for p, data in to_create:
        print(f"  /board/{data['slug']}")
    if to_update:
        print("Slugs updated:")
        for p, data, _ in to_update:
            print(f"  /board/{data['slug']}")
    if skipped:
        print("Skipped files:")
        for fname, reason in skipped:
            print(f"  {fname}: {reason}")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Start backend: uvicorn backend.main:app --reload --port 8000")
    print("  2. Check /board (public) and /marketing (admin)")
    print("  3. Verify imported posts appear with correct content")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
