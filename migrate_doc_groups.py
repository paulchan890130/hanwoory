"""
One-time migration: adds doc_group:<id> tag to existing 준비서류 posts in Google Sheets.

Safe to run multiple times — already-tagged posts are skipped.

Run from the K.ID soft project root:
    python migrate_doc_groups.py [--dry-run]

After running, new posts added via the admin UI (/marketing) will immediately appear
on /documents if their Tags field includes e.g.  doc_group:f4

Valid group IDs:
    f1  f2  f3  f4  f5  f6  h2  nationality  china-notarization
"""
import sys, os, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Authoritative slug → group mapping (mirrors GROUP_DEFS in DocumentsClient.tsx)
SLUG_TO_GROUP: dict[str, str] = {
    # F-1
    "f1-childcare-support-invitation-documents": "f1",
    "f15-invitation-documents": "f1",
    # F-2
    "f2-invitation-change-documents": "f2",
    "f2-change-minor-documents": "f2",
    "f2-registration-extension-spouse-documents": "f2",
    "f2-registration-extension-minor-documents": "f2",
    # F-3
    "f3-invitation-documents": "f3",
    "f3-change-spouse-documents": "f3",
    "f3-change-child-documents": "f3",
    "f3-registration-extension-spouse-documents": "f3",
    "f3-registration-extension-minor-documents": "f3",
    "f3r-change-documents": "f3",
    # F-4
    "f4-registration-documents": "f4",
    "f4-extension-documents": "f4",
    "h2-to-f4-change-documents": "f4",
    "other-status-to-f4-change-documents": "f4",
    "f4-change-age-60-or-test-documents": "f4",
    "f4-change-school-student-documents": "f4",
    "f4-change-local-manufacturing-documents": "f4",
    "f4r-change-documents": "f4",
    # F-5 / 영주권
    "f4-two-year-pr-four-insurance-documents": "f5",
    "f4-two-year-pr-daily-worker-documents": "f5",
    "f4-two-year-pr-property-tax-documents": "f5",
    "f4-two-year-pr-assets-documents": "f5",
    "f4-two-year-pr-business-owner-documents": "f5",
    "h2-four-year-permanent-residence-documents": "f5",
    "c38-permanent-residence-parent-nationality-documents": "f5",
    "f4-pr-income-70-percent-condition": "f5",
    # F-6
    "f6-invitation-documents": "f6",
    "f6-change-documents": "f6",
    "f6-extension-documents": "f6",
    # H-2
    "h2-registration-documents": "h2",
    "h2-extension-documents": "h2",
    "c38-to-h2-change-documents": "h2",
    # 국적 / 귀화
    "naturalization-general-documents": "nationality",
    "naturalization-simple-marriage-two-years-documents": "nationality",
    "naturalization-simple-marriage-breakdown-documents": "nationality",
    "naturalization-marriage-minor-child-documents": "nationality",
    "naturalization-special-parent-nationality-documents": "nationality",
    "naturalization-simple-three-years-deceased-parent-documents": "nationality",
    # 중국 공증·아포스티유
    "family-notarization-documents": "china-notarization",
    "marriage-notarization-documents": "china-notarization",
    "single-remarriage-notarization-documents": "china-notarization",
    "criminal-record-notarization-documents": "china-notarization",
}

MARKETING_HEADER = [
    "id", "title", "slug", "category", "summary", "content",
    "thumbnail_url", "is_published", "is_featured",
    "created_by", "created_at", "updated_at",
    "image_file_id", "image_url", "image_alt",
    "meta_description", "tags",
]


def _get_worksheet():
    import gspread
    from google.oauth2.service_account import Credentials
    import config

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(config.KEY_PATH, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(config.SHEET_KEY)
    return sh.worksheet(config.MARKETING_POSTS_SHEET_NAME)


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _add_doc_group_tag(existing_tags: str, group_id: str) -> str:
    """Append doc_group:<id> to tags if not already present. Returns new tags string."""
    marker = f"doc_group:{group_id}"
    parts = [t.strip() for t in existing_tags.split(",") if t.strip()]
    if any(p == marker or p.startswith("doc_group:") for p in parts):
        return existing_tags  # already tagged
    parts.append(marker)
    return ", ".join(parts)


def run(dry_run: bool = False) -> None:
    print("=" * 60)
    print(f"MIGRATE doc_group tags — {'DRY RUN' if dry_run else 'LIVE'}")
    print("=" * 60)

    if dry_run:
        print("\n[DRY RUN] Would connect to Google Sheets.")
        print(f"[DRY RUN] Would tag {len(SLUG_TO_GROUP)} known slugs with doc_group:<id>.")
        for slug, gid in sorted(SLUG_TO_GROUP.items()):
            print(f"  {slug} → doc_group:{gid}")
        print("\n[DRY RUN] No changes made.")
        return

    print("\nConnecting to Google Sheets …")
    ws = _get_worksheet()
    values = ws.get_all_values()
    if not values:
        print("Sheet is empty — nothing to migrate.")
        return

    header = values[0]
    slug_idx = header.index("slug") if "slug" in header else None
    tags_idx = header.index("tags") if "tags" in header else None
    tags_col_letter = _col_letter(tags_idx + 1) if tags_idx is not None else None

    if slug_idx is None or tags_idx is None:
        print("ERROR: 'slug' or 'tags' column not found in sheet header.")
        return

    print(f"Sheet has {len(values) - 1} data rows.")

    updates: list[tuple[int, str]] = []  # (row_number_1indexed, new_tags_value)
    skipped_already_tagged = 0
    skipped_no_match = 0

    for row_i, row in enumerate(values[1:], start=2):
        slug = row[slug_idx].strip() if slug_idx < len(row) else ""
        if not slug:
            continue

        group_id = SLUG_TO_GROUP.get(slug)
        if group_id is None:
            skipped_no_match += 1
            continue

        current_tags = row[tags_idx].strip() if tags_idx < len(row) else ""
        new_tags = _add_doc_group_tag(current_tags, group_id)

        if new_tags == current_tags:
            skipped_already_tagged += 1
            continue

        updates.append((row_i, new_tags))
        print(f"  Row {row_i}: {slug} → tags: {new_tags[:80]}")

    print(f"\nAlready tagged (skip): {skipped_already_tagged}")
    print(f"No slug match (skip):  {skipped_no_match}")
    print(f"To update:             {len(updates)}")

    if not updates:
        print("\nNothing to update.")
        return

    print("\nApplying updates …")
    batch = [
        {
            "range": f"{tags_col_letter}{row_no}",
            "values": [[new_tags]],
        }
        for row_no, new_tags in updates
    ]
    ws.batch_update(batch, value_input_option="USER_ENTERED")

    print(f"\nDone. Tagged {len(updates)} post(s) with doc_group:<id>.")
    print("=" * 60)
    print("\nNext steps:")
    print("  • Restart the backend (uvicorn) so the updated tags are served.")
    print("  • Visit /documents — all 44 existing items should appear as before.")
    print("  • To add a NEW 준비서류 post: create it in the admin /marketing page,")
    print("    set category to the appropriate value, and add  doc_group:<id>  to Tags.")
    print("    Valid group IDs:  f1 f2 f3 f4 f5 f6 h2 nationality china-notarization")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
