"""manual_worker_run — Render Cron Job / Worker 진입점 (매뉴얼 업데이트 서버 자동화).

매뉴얼 업데이트의 **최종 방향은 서버 자동화**다. 이 스크립트는 Render Cron Job(또는
Worker)에서 1회 실행되어:

    감지 → 다운로드 → rhwp extract → diff → candidates → PG 저장
        → (chromium) 변경 페이지 PDF artifact 생성 → PG blob 저장 → /tmp 삭제 → 종료

를 수행한다. 로컬 수동 실행은 개발/검증용일 뿐 최종안이 아니며, 사용자 업로드 방식이나
Windows 한컴 COM 방식으로 되돌리지 않는다.

핵심 동작은 ``backend.services.manual_auto_update.run_worker_cycle`` 한 곳에 있고, 여기서는
인자 파싱 + 결과 JSON 출력 + 종료코드만 담당한다(중복 로직 없음).

종료코드:
    0 — staging 이 staged/no_change (PDF 단계 실패해도 staging 성공이면 0; PDF 실패는
        staging 에 전이되지 않는다)
    1 — staging 이 error/skipped 등(자동화 실패로 간주)

실행 예 (Render Cron Job command):
    python -m backend.scripts.manual_worker_run --pg --with-pdf

필요 env: DATABASE_URL, FEATURE_PG_MANUAL_UPDATE=1, FEATURE_MANUAL_AUTO_UPDATE=1,
          CHROME_PATH(예: /usr/bin/chromium), HANWOORY_ENV=server
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# repo root 을 sys.path 에 (python -m / 직접 실행 모두 지원)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="매뉴얼 업데이트 서버 자동화 1사이클 (Render Cron Job/Worker)."
    )
    ap.add_argument("--pg", action="store_true",
                    help="PG 단일 출처 경로(기본·유일 지원). 명시용 플래그.")
    ap.add_argument("--with-pdf", action="store_true",
                    help="staging 후 변경 페이지 PDF artifact 까지 생성(chromium 필요).")
    ap.add_argument("--force", action="store_true",
                    help="오늘 already-ran guard 무시(seen 비교는 유지).")
    ap.add_argument("--no-notify", action="store_true",
                    help="게시판 '검토 필요' 공지 생략.")
    ap.add_argument("--limit", type=int, default=None,
                    help="--with-pdf 시 PDF 생성 후보 수 제한(디버깅용 수동 제한). "
                         "미지정이면 컨테이너 메모리 기준 adaptive batch 로 누락 후보 전체 처리.")
    args = ap.parse_args(argv)

    from backend.services.manual_auto_update import run_worker_cycle

    res = run_worker_cycle(
        force=args.force,
        with_pdf=args.with_pdf,
        notify=not args.no_notify,
        limit=args.limit,
        trigger="cron",
    )
    print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)

    staging = res.get("staging") or {}
    staging_status = staging.get("status") if isinstance(staging, dict) else None
    return 0 if staging_status in ("staged", "no_change") else 1


if __name__ == "__main__":
    raise SystemExit(main())
