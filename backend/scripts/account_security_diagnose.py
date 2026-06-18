"""계정공유 보안차단 진단/최소복구 (운영 DB, 읽기 우선).

사용 (운영 DB URL 은 **셸 환경변수로만** 주입 — 파일/소스에 절대 기록 금지):

    # 진단(읽기 전용, PII 미출력):
    $env:DATABASE_URL = "<Render External Database URL>"   # 본인 터미널에서만
    python backend/scripts/account_security_diagnose.py <login_id>

    # 최소 복구(차단 플래그만 해제, 증거 미삭제) — 명시 확인 필요:
    python backend/scripts/account_security_diagnose.py <login_id> --unblock --confirm <login_id>

설계:
- login_events 는 이미 마스킹(ip_prefix_masked)·요약(user_agent_summary)만 저장 → 원문 PII 미출력.
- --unblock 은 account_security 의 security_blocked/suspicion_count/blocked_* 만 갱신.
  login_events / security_notifications 는 **삭제·수정하지 않는다**(증거 보존).
- DATABASE_URL 미설정 시 즉시 종료(운영 보호).
"""
from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine, text


def _engine():
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        sys.exit("DATABASE_URL 이 설정되지 않았습니다. (셸 환경변수로만 주입하세요)")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if "sslmode=" not in url and (".render.com" in url or "oregon-postgres" in url):
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return create_engine(url, future=True)


def diagnose(eng, login_id: str) -> None:
    with eng.connect() as c:
        print(f"\n=== account_security ({login_id}) ===")
        for r in c.execute(text(
            "select login_id, suspicion_count, security_blocked, blocked_at, "
            "blocked_reason, last_suspicion_at, updated_at from account_security "
            "where login_id=:lid"), {"lid": login_id}):
            print(dict(r._mapping))

        print(f"\n=== login_events (최근 30, {login_id}) — 원문 PII 없음 ===")
        rows = c.execute(text(
            "select event_type, ip_prefix_masked, user_agent_summary, success, "
            "reason, risk_level, created_at from login_events where login_id=:lid "
            "order by created_at desc limit 30"), {"lid": login_id}).all()
        for r in rows:
            m = r._mapping
            print(f"{m['created_at']} | {m['event_type']:<28} | "
                  f"{(m['ip_prefix_masked'] or '-'):<16} | {(m['user_agent_summary'] or '-'):<16} | "
                  f"risk={m['risk_level']} | {m['reason'] or ''}")

        print(f"\n=== 요약 ===")
        n_suspicious = sum(1 for r in rows if r._mapping["event_type"] == "SUSPICIOUS_LOGIN_DETECTED")
        n_blocked = sum(1 for r in rows if r._mapping["event_type"] == "ACCOUNT_SECURITY_BLOCKED")
        n_revoke = sum(1 for r in rows if r._mapping["event_type"] == "SESSION_REVOKED_BY_NEW_LOGIN")
        distinct = {(r._mapping["ip_prefix_masked"], r._mapping["user_agent_summary"])
                    for r in rows if r._mapping["event_type"] == "LOGIN_SUCCESS"}
        print(f"SUSPICIOUS={n_suspicious}  BLOCKED={n_blocked}  "
              f"SESSION_REVOKED_BY_NEW_LOGIN={n_revoke}  "
              f"distinct(prefix+UA) in shown LOGIN_SUCCESS={len(distinct)} -> {sorted(distinct)}")

        print(f"\n=== security_notifications (최근 30 관련, {login_id}) ===")
        for r in c.execute(text(
            "select recipient_role, type, title, created_at, read_at from security_notifications "
            "where related_login_id=:lid order by created_at desc limit 30"), {"lid": login_id}):
            print(dict(r._mapping))


def unblock(eng, login_id: str) -> None:
    with eng.begin() as c:
        before = c.execute(text(
            "select security_blocked, suspicion_count from account_security where login_id=:lid"),
            {"lid": login_id}).first()
        print(f"복구 전: {dict(before._mapping) if before else None}")
        c.execute(text(
            "update account_security set security_blocked=false, suspicion_count=0, "
            "blocked_at=null, blocked_reason=null, updated_at=now() where login_id=:lid"),
            {"lid": login_id})
        after = c.execute(text(
            "select security_blocked, suspicion_count from account_security where login_id=:lid"),
            {"lid": login_id}).first()
        print(f"복구 후: {dict(after._mapping) if after else None}")
        print("login_events / security_notifications 는 보존되었습니다(증거 미삭제).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("login_id")
    ap.add_argument("--unblock", action="store_true", help="security_blocked 만 해제(증거 보존)")
    ap.add_argument("--confirm", help="--unblock 시 login_id 를 다시 입력해 확인")
    args = ap.parse_args()

    eng = _engine()
    diagnose(eng, args.login_id)

    if args.unblock:
        if args.confirm != args.login_id:
            sys.exit("\n[중단] --unblock 에는 --confirm <login_id> 가 정확히 일치해야 합니다.")
        print("\n--- 최소 복구 실행 ---")
        unblock(eng, args.login_id)


if __name__ == "__main__":
    main()
