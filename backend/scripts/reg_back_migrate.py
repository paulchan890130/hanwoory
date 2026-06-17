"""고객 외국인등록번호 뒷자리(reg_back) 암호화 마이그레이션 — dry-run / verify / apply.

운영 적용은 **별도 승인** 후에만. 기본은 dry-run(읽기 전용, 변환 없음).
**원문 등록번호는 절대 출력/로깅하지 않는다.**

사용:
  python -m backend.scripts.reg_back_migrate                 # dry-run 리포트(기본)
  python -m backend.scripts.reg_back_migrate --verify        # 변환 결과 검증(읽기 전용)
  python -m backend.scripts.reg_back_migrate --apply --yes   # 실제 변환(로컬/승인 환경에서만)

전제: DATABASE_URL 설정 + migration 0018 적용. 키(CUSTOMER_PII_ENCRYPTION_KEY)/PII_HASH_SECRET
설정 시에만 암호화/해시가 채워진다(미설정이면 dry-run 카운트만 의미).
"""
from __future__ import annotations

import argparse
import sys


def _session():
    from backend.db.session import get_sessionmaker, is_configured
    if not is_configured():
        print("[ERROR] DATABASE_URL 미설정 — 중단", file=sys.stderr)
        sys.exit(2)
    return get_sessionmaker()()


def _is_valid_back(digits: str) -> bool:
    return len(digits) == 7 and digits.isdigit()


def dry_run() -> dict:
    from sqlalchemy import select
    from backend.db.models.customer import Customer
    from backend.services import pii_crypto as p

    stats = dict(total=0, plaintext_present=0, to_encrypt=0, already_encrypted=0,
                 abnormal=0, tenant_missing=0, migratable=0)
    with _session() as s:
        rows = s.scalars(select(Customer).where(Customer.deleted_at.is_(None))).all()
        for r in rows:
            stats["total"] += 1
            raw = (r.reg_back or "")
            enc = (r.reg_back_encrypted or "")
            if enc:
                stats["already_encrypted"] += 1
            digits = p.normalize_reg_back(raw)
            has_plain = bool(raw) and "*" not in str(raw)
            if has_plain:
                stats["plaintext_present"] += 1
            if not str(r.tenant_id or "").strip():
                stats["tenant_missing"] += 1
            if has_plain and not enc:
                if _is_valid_back(digits):
                    stats["to_encrypt"] += 1
                    if str(r.tenant_id or "").strip():
                        stats["migratable"] += 1
                elif digits:
                    stats["abnormal"] += 1
    return stats


def apply_migration() -> dict:
    from datetime import datetime, timezone
    from sqlalchemy import select
    from backend.db.models.customer import Customer
    from backend.services import pii_crypto as p

    if not p.customer_pii_available():
        print("[ERROR] CUSTOMER_PII_ENCRYPTION_KEY 미설정 — 변환 중단", file=sys.stderr)
        sys.exit(3)

    done = skipped = failed = 0
    with _session() as s:
        rows = s.scalars(select(Customer).where(Customer.deleted_at.is_(None))).all()
        for r in rows:
            raw = (r.reg_back or "")
            if r.reg_back_encrypted or "*" in str(raw):
                skipped += 1
                continue
            digits = p.normalize_reg_back(raw)
            if not _is_valid_back(digits) or not str(r.tenant_id or "").strip():
                skipped += 1
                continue
            try:
                r.reg_back_encrypted = p.encrypt_pii(digits)
                r.reg_back_hash = p.hash_pii(r.tenant_id, digits)
                r.reg_back_last4 = p.last4_reg_back(digits)
                r.reg_back_enc_ver = p.REG_BACK_ENC_VERSION
                r.reg_back_migrated_at = datetime.now(timezone.utc)
                # 1차: 평문 reg_back 유지(fallback/rollback). 2차에서 마스크/널 처리.
                done += 1
            except Exception:
                failed += 1
        s.commit()
    return dict(converted=done, skipped=skipped, failed=failed)


def verify() -> dict:
    from sqlalchemy import select
    from backend.db.models.customer import Customer
    from backend.services import pii_crypto as p

    res = dict(checked=0, decrypt_ok=0, decrypt_fail=0, last4_ok=0, hash_ok=0,
               mask_first_digit_ok=0, plaintext_leak=0)
    with _session() as s:
        rows = s.scalars(
            select(Customer).where(Customer.deleted_at.is_(None), Customer.reg_back_encrypted.isnot(None))
        ).all()
        for r in rows:
            if not r.reg_back_encrypted:
                continue
            res["checked"] += 1
            try:
                plain = p.decrypt_pii(r.reg_back_encrypted)
                res["decrypt_ok"] += 1
            except Exception:
                res["decrypt_fail"] += 1
                continue
            if p.last4_reg_back(plain) == (r.reg_back_last4 or ""):
                res["last4_ok"] += 1
            if r.reg_back_hash and p.hash_pii(r.tenant_id, plain) == r.reg_back_hash:
                res["hash_ok"] += 1
            masked = p.mask_reg_back(r.reg_back or plain)
            if masked[:1] == plain[:1]:
                res["mask_first_digit_ok"] += 1
            # _row_to_dict(reveal=False) 가 원문을 노출하지 않는지 점검
            from backend.services.customer_pg_service import _row_to_dict
            d = _row_to_dict(r, reveal=False)
            if d.get("번호") and "*" not in d["번호"] and len(p.normalize_reg_back(d["번호"])) == 7:
                res["plaintext_leak"] += 1
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 변환(승인 환경에서만)")
    ap.add_argument("--verify", action="store_true", help="변환 결과 검증(읽기 전용)")
    ap.add_argument("--yes", action="store_true", help="--apply 확인 플래그")
    args = ap.parse_args()

    if args.verify:
        print("[VERIFY]", verify())
        return
    if args.apply:
        if not args.yes:
            print("[ABORT] --apply 는 --yes 확인 플래그가 필요합니다(운영 적용은 승인 후).", file=sys.stderr)
            sys.exit(1)
        print("[APPLY]", apply_migration())
        return
    print("[DRY-RUN]", dry_run())
    print("원문 등록번호는 출력하지 않습니다. 운영 적용은 --apply --yes + 사전 백업/승인 필요.")


if __name__ == "__main__":
    main()
