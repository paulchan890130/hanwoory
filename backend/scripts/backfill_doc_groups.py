"""업무별 준비서류 중분류 backfill (로컬 전용).

목적:
  1) document_groups 테이블에 9개 중분류를 seed(멱등).
  2) 기존 marketing_posts 에 doc_group:<group_key> 태그를 부여
     (기존 태그 우선 → slugOrder 매핑 → 제목 prefix 추정 → 미분류 보고).

원칙:
  - 기존 글 slug/URL/제목 변경 금지. tags 에 doc_group 토큰만 추가.
  - 이미 doc_group 태그가 있으면 절대 변경하지 않는다(기존 태그 우선).
  - 추정이 애매하면 자동 배치하지 않고 "미분류"로 보고만 한다.
  - 멱등: 재실행해도 동일 결과. dry-run 이 기본.

사용:
  python -m backend.scripts.backfill_doc_groups            # dry-run (기본, 쓰기 없음)
  python -m backend.scripts.backfill_doc_groups --apply    # 로컬 DB 에 실제 반영

운영 DB 에는 실행 금지.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_DOC_GROUP_TAG_RE = re.compile(r"doc_group:([a-z0-9][a-z0-9-]*)")

# DocumentsClient.tsx GROUP_DEFS 와 동일(키/표시명/순서/대표 slug). 단일 출처로 seed.
GROUP_DEFS = [
    {"key": "f1", "title": "F-1", "slugs": [
        "f1-childcare-support-invitation-documents",
        "f15-invitation-documents",
    ]},
    {"key": "f2", "title": "F-2", "slugs": [
        "f2-invitation-change-documents",
        "f2-change-minor-documents",
        "f2-registration-extension-spouse-documents",
        "f2-registration-extension-minor-documents",
    ]},
    {"key": "f3", "title": "F-3", "slugs": [
        "f3-invitation-documents",
        "f3-change-spouse-documents",
        "f3-change-child-documents",
        "f3-registration-extension-spouse-documents",
        "f3-registration-extension-minor-documents",
        "f3r-change-documents",
    ]},
    {"key": "f4", "title": "F-4", "slugs": [
        "f4-registration-documents",
        "f4-extension-documents",
        "h2-to-f4-change-documents",
        "other-status-to-f4-change-documents",
        "f4-change-age-60-or-test-documents",
        "f4-change-school-student-documents",
        "f4-change-local-manufacturing-documents",
        "f4r-change-documents",
    ]},
    {"key": "f5", "title": "F-5 / 영주권", "slugs": [
        "f4-two-year-pr-four-insurance-documents",
        "f4-two-year-pr-daily-worker-documents",
        "f4-two-year-pr-property-tax-documents",
        "f4-two-year-pr-assets-documents",
        "f4-two-year-pr-business-owner-documents",
        "h2-four-year-permanent-residence-documents",
        "c38-permanent-residence-parent-nationality-documents",
        "f4-pr-income-70-percent-condition",
    ]},
    {"key": "f6", "title": "F-6", "slugs": [
        "f6-invitation-documents",
        "f6-change-documents",
        "f6-extension-documents",
    ]},
    {"key": "h2", "title": "H-2", "slugs": [
        "h2-registration-documents",
        "h2-extension-documents",
        "c38-to-h2-change-documents",
    ]},
    {"key": "nationality", "title": "국적 / 귀화", "slugs": [
        "naturalization-general-documents",
        "naturalization-simple-marriage-two-years-documents",
        "naturalization-simple-marriage-breakdown-documents",
        "naturalization-marriage-minor-child-documents",
        "naturalization-special-parent-nationality-documents",
        "naturalization-simple-three-years-deceased-parent-documents",
    ]},
    {"key": "china-notarization", "title": "중국 공증·아포스티유", "slugs": [
        "family-notarization-documents",
        "marriage-notarization-documents",
        "single-remarriage-notarization-documents",
        "criminal-record-notarization-documents",
    ]},
]

# slug → group_key (authoritative; GROUP_DEFS 에서 파생)
SLUG_TO_KEY = {s: g["key"] for g in GROUP_DEFS for s in g["slugs"]}
VALID_KEYS = {g["key"] for g in GROUP_DEFS}


def _existing_tag_key(tags: str) -> str:
    m = _DOC_GROUP_TAG_RE.search(tags or "")
    return m.group(1).strip().lower() if m else ""


def _infer_by_title(title: str) -> str:
    """제목 prefix 추정. 강한 영주권 신호를 먼저 확인(예: 'H-2 4년 영주권' → f5)."""
    t = (title or "").strip()
    tl = t.lower().replace(" ", "")
    # 영주권 우선(특정 비자 prefix 보다 강함)
    if ("영주권" in t) or ("영주" in t) or ("permanentresidence" in tl) or ("f-5" in tl) or ("f5" in tl):
        return "f5"
    if ("귀화" in t) or ("국적" in t) or ("naturalization" in tl):
        return "nationality"
    if ("공증" in t) or ("아포스티유" in t) or ("notariz" in tl) or ("apostille" in tl):
        return "china-notarization"
    if tl.startswith("f-1") or tl.startswith("f1"):
        return "f1"
    if tl.startswith("f-2") or tl.startswith("f2"):
        return "f2"
    if tl.startswith("f-3") or tl.startswith("f3"):
        return "f3"
    if tl.startswith("f-4") or tl.startswith("f4"):
        return "f4"
    if tl.startswith("f-6") or tl.startswith("f6"):
        return "f6"
    if tl.startswith("h-2") or tl.startswith("h2"):
        return "h2"
    return ""


def _append_doc_group(tags: str, key: str) -> str:
    tags = (tags or "").strip()
    token = f"doc_group:{key}"
    if not tags:
        return token
    return f"{tags}, {token}"


def seed_groups(apply: bool) -> list[str]:
    from backend.services import document_group_pg_service as svc
    logs = []
    try:
        existing = {g["group_key"]: g for g in svc.list_groups(published_only=False)}
    except Exception as e:
        # migration 0024 미적용(테이블 없음) — dry-run 을 migration 전에 돌릴 수 있게 graceful.
        logs.append(f"  [warn] document_groups 조회 실패(테이블 미생성?) — seed 생략: {e}")
        for i, g in enumerate(GROUP_DEFS):
            logs.append(f"  [seed*] {g['key']:<18} 생성 예정 ('{g['title']}', order={i}) — migration 후 가능")
        return logs
    for i, g in enumerate(GROUP_DEFS):
        if g["key"] in existing:
            logs.append(f"  [skip] {g['key']:<18} 이미 존재 ('{existing[g['key']]['title']}')")
            continue
        if apply:
            svc.create_group(
                group_key=g["key"], title=g["title"],
                sort_order=i, is_published=True,
            )
            logs.append(f"  [seed] {g['key']:<18} 생성 ('{g['title']}', order={i})")
        else:
            logs.append(f"  [seed*] {g['key']:<18} 생성 예정 ('{g['title']}', order={i})")
    return logs


def backfill_tags(apply: bool):
    from backend.services import marketing_pg_service as mkt
    posts = mkt.list_admin()

    kept, by_slug, by_title, unclassified = [], [], [], []
    for p in posts:
        title = p.get("title", "")
        slug = p.get("slug", "")
        tags = p.get("tags", "")
        existing_key = _existing_tag_key(tags)
        if existing_key:
            kept.append((title, slug, existing_key,
                         "VALID" if existing_key in VALID_KEYS else "UNKNOWN-KEY"))
            continue
        key = SLUG_TO_KEY.get(slug, "")
        if key:
            by_slug.append((p, key))
            continue
        key = _infer_by_title(title)
        if key:
            by_title.append((p, key))
            continue
        unclassified.append((title, slug))

    print("\n=== 1) 기존 doc_group 태그 보유 (변경 안 함) ===")
    if not kept:
        print("  (없음)")
    for title, slug, key, status in kept:
        print(f"  - [{key}] {status:<11} {title}  (slug={slug})")

    print("\n=== 2) slugOrder 매핑으로 태그 부여 대상 ===")
    if not by_slug:
        print("  (없음)")
    for p, key in by_slug:
        new_tags = _append_doc_group(p.get("tags", ""), key)
        print(f"  - [{key}] {p.get('title','')}  (slug={p.get('slug','')})")
        print(f"        tags: '{p.get('tags','')}'  ->  '{new_tags}'")

    print("\n=== 3) 제목 prefix 추정으로 태그 부여 대상 ===")
    if not by_title:
        print("  (없음)")
    for p, key in by_title:
        new_tags = _append_doc_group(p.get("tags", ""), key)
        print(f"  - [{key}] {p.get('title','')}  (slug={p.get('slug','')})")
        print(f"        tags: '{p.get('tags','')}'  ->  '{new_tags}'")

    print("\n=== 4) 미분류 (자동 배치 안 함 — 수동 검토 필요) ===")
    if not unclassified:
        print("  (없음)")
    for title, slug in unclassified:
        print(f"  - {title}  (slug={slug})")

    to_write = by_slug + by_title
    print("\n--- 요약 ---")
    print(f"  전체 글: {len(posts)}")
    print(f"  기존 태그 유지: {len(kept)}")
    print(f"  slug 매핑 부여: {len(by_slug)}")
    print(f"  제목 추정 부여: {len(by_title)}")
    print(f"  미분류: {len(unclassified)}")
    print(f"  => 태그 변경 건수: {len(to_write)}")

    if apply and to_write:
        for p, key in to_write:
            p["tags"] = _append_doc_group(p.get("tags", ""), key)
            mkt.upsert_post(p)
        print(f"\n[APPLIED] {len(to_write)}건 태그 반영 완료.")
    elif not apply:
        print("\n[DRY-RUN] 쓰기 없음. 실제 반영하려면 --apply 옵션을 사용하세요.")


def main():
    parser = argparse.ArgumentParser(description="document_groups seed + doc_group 태그 backfill (로컬 전용)")
    parser.add_argument("--apply", action="store_true", help="실제 DB 반영 (기본: dry-run)")
    args = parser.parse_args()

    from backend.db import session as db_session
    if not db_session.is_configured():
        print("[ERROR] PostgreSQL 미구성 (DATABASE_URL 없음). 로컬 DB 설정 후 실행하세요.")
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== document_groups backfill ({mode}) ===")

    print("\n[A] document_groups seed")
    for line in seed_groups(args.apply):
        print(line)

    print("\n[B] marketing_posts doc_group 태그 backfill")
    backfill_tags(args.apply)


if __name__ == "__main__":
    main()
