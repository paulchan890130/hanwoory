"""
K.ID 출입국업무관리 - FastAPI 백엔드
기존 core/*.py 로직을 REST API로 노출합니다.
"""
import sys
import os

# ── Windows 한글 인코딩 보정 ─────────────────────────────────────────────────
# uvicorn 로그/터미널 출력에서 한글이 ??? 로 깨지는 현상 방지.
# Python str 내부는 유니코드이므로 Sheets API 저장 자체에는 영향 없음.
# 그러나 uvicorn 로그 스트림 인코딩이 cp949 이면 에러 메시지도 깨지므로
# 백엔드 기동 시점에 강제로 utf-8 로 교체한다.
if sys.platform == "win32":
    import io as _io
    try:
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except AttributeError:
        pass  # IDLE / 이미 래핑된 환경에서는 무시
# ─────────────────────────────────────────────────────────────────────────────

# 부모 디렉토리를 sys.path에 추가 → config, core.* import 가능
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── .env 로딩 (로컬 개발용) ────────────────────────────────────────────────────
# 프로젝트 루트의 .env 파일에서 JWT_SECRET_KEY, ALLOWED_ORIGINS, HANWOORY_ENV 등을 읽는다.
# python-dotenv가 없으면 조용히 건너뜀 (Docker 환경에서는 compose env:가 대신 주입).
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.isfile(_env_path):
        _load_dotenv(_env_path, override=False)  # override=False: 시스템 환경변수 우선
except ImportError:
    pass
# ─────────────────────────────────────────────────────────────────────────────

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler


def _run_watcher():
    try:
        from backend.services.manual_watcher import check_and_update
        result = check_and_update(notify_board=True)
        print(f"[watcher] 자동 실행 완료: changed={len(result.get('changed', []))} errors={len(result.get('errors', []))}")
    except Exception as e:
        print(f"[watcher] 오류: {e}")


_scheduler = BackgroundScheduler()
_scheduler.add_job(_run_watcher, "interval", hours=12, id="manual_watcher")

# ── 신규 rhwp 매뉴얼 자동 staging 스케줄러 (레거시 watcher 와 완전 분리) ──────────
# FEATURE_MANUAL_AUTO_UPDATE=true 일 때만 등록/기동된다. 기본 OFF.
# server 환경이라도 env 로 명시적으로 켠 경우에만 동작한다(레거시 watcher 의 server 차단과 무관).
_rhwp_scheduler = BackgroundScheduler()


def _feature_auto_update_enabled() -> bool:
    return os.environ.get("FEATURE_MANUAL_AUTO_UPDATE", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _register_rhwp_auto_update() -> None:
    """매일 15:00 KST(기본)에 rhwp 자동 staging 잡 등록. KST는 DST가 없어 고정 오프셋
    (UTC+9)으로 환산한다. 트리거 timezone 을 명시 UTC 로 두어 컨테이너 TZ 에 의존하지 않는다."""
    from datetime import timezone as _tz
    from apscheduler.triggers.cron import CronTrigger
    from backend.services.manual_auto_update import scheduled_job

    hour_kst = 15
    try:
        hour_kst = int(os.environ.get("MANUAL_AUTO_UPDATE_HOUR_KST", "15"))
    except ValueError:
        hour_kst = 15
    utc_hour = (hour_kst - 9) % 24  # 15 KST → 06 UTC
    _rhwp_scheduler.add_job(
        scheduled_job,
        CronTrigger(hour=utc_hour, minute=0, timezone=_tz.utc),
        id="rhwp_manual_auto_update",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _rhwp_scheduler.start()
    print(f"[manual-auto] rhwp auto-staging scheduler started — daily {hour_kst:02d}:00 KST "
          f"({utc_hour:02d}:00 UTC). FEATURE_MANUAL_AUTO_UPDATE=true")


# ── 매뉴얼 업데이트 알림: 첨부 제목 변동 1일 1회 감시 (auto-update 플래그와 독립) ──────
_alert_scheduler = BackgroundScheduler()


def _alert_title_watch_job() -> None:
    """1일 1회 첨부 제목 변동 감지 → alert event 기록. 예외/네트워크 실패는 무시(non-fatal)."""
    try:
        from backend.services.manual_alert_service import run_title_detection
        res = run_title_detection()
        print(f"[manual-alert] title watch: status={res.get('status')} created={res.get('created')}")
    except Exception as e:
        print(f"[manual-alert] title watch error (non-fatal): {e}")


def _register_manual_alert_watch() -> None:
    """PG 구성 시 매일 1회(기본 15:30 KST) 제목 변동 감시 잡 등록. 로그인 흐름과 분리."""
    from datetime import timezone as _tz
    from apscheduler.triggers.cron import CronTrigger
    try:
        hour_kst = int(os.environ.get("MANUAL_ALERT_WATCH_HOUR_KST", "15"))
    except ValueError:
        hour_kst = 15
    utc_hour = (hour_kst - 9) % 24
    _alert_scheduler.add_job(
        _alert_title_watch_job,
        CronTrigger(hour=utc_hour, minute=30, timezone=_tz.utc),
        id="manual_alert_title_watch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _alert_scheduler.start()
    print(f"[manual-alert] title-watch scheduler started — daily {hour_kst:02d}:30 KST "
          f"({utc_hour:02d}:30 UTC)")


def _is_server_env() -> bool:
    """운영(server) 환경 여부. HANWOORY_ENV 또는 RUN_ENV 가 'server' 이면 True.

    config.RUN_ENV 는 HANWOORY_ENV(기본 'local')에서 파생된다. 두 환경변수를 모두
    확인해, 레거시 Hancom/OpenHwpExe 자동 워처가 운영에서 기동되지 않도록 한다."""
    try:
        from config import RUN_ENV as _cfg_env
    except Exception:
        _cfg_env = os.environ.get("HANWOORY_ENV", "local")
    candidates = (
        str(_cfg_env or "").strip().lower(),
        os.environ.get("HANWOORY_ENV", "").strip().lower(),
        os.environ.get("RUN_ENV", "").strip().lower(),
    )
    return "server" in candidates


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Persistent Disk 최초 시드: MANUALS_DATA_DIR 가 baked 기본과 다르면 운영 PDF/baseline 을
    # '없을 때만' 복사한다(덮어쓰기 없음, 운영 DB 미이동). 실패해도 기동을 막지 않는다.
    try:
        from backend.services.manuals_disk_bootstrap import bootstrap_manuals_dir
        _seed = bootstrap_manuals_dir()
        if _seed.get("copied_files") or _seed.get("copied_dirs"):
            print(f"[manuals-disk] seeded {_seed}")
    except Exception as e:
        print(f"[manuals-disk] bootstrap skipped (non-fatal): {e}")

    # 레거시 Hancom/OpenHwpExe 자동 워처는 Windows·로컬 전용이다. 운영(server)에서는
    # win32com / OpenHwpExe.exe 가 없어 동작 불가하며, 설령 동작하더라도 운영 PDF를
    # 직접 덮어써 "staging 검토 + explicit apply" 원칙과 충돌한다. 따라서 server 에서는
    # 자동 실행 배선만 끊는다. (워처 코드 자체·rhwp v1·PDF 뷰어·apply 흐름은 무변경)
    if _is_server_env():
        print(
            "[watcher] legacy Hancom/OpenHwpExe manual watcher disabled on server; "
            "rhwp Manual Update v1 should be used"
        )
    else:
        _scheduler.start()
        print("[watcher] 스케줄러 시작 (12시간마다 자동 실행) — local 전용")

    # 신규 rhwp 자동 staging 스케줄러 — env 로 명시적으로 켠 경우에만(기본 OFF).
    if _feature_auto_update_enabled():
        try:
            _register_rhwp_auto_update()
        except Exception as e:
            print(f"[manual-auto] scheduler 등록 실패 (non-fatal): {e}")
    else:
        print("[manual-auto] rhwp auto-staging disabled (set FEATURE_MANUAL_AUTO_UPDATE=true to enable)")

    # 매뉴얼 업데이트 알림 제목 감시 — PG 구성 시에만(네트워크/감지 실패는 non-fatal).
    try:
        from backend.db.session import is_configured as _pg_configured
        if _pg_configured():
            _register_manual_alert_watch()
        else:
            print("[manual-alert] title-watch disabled (PostgreSQL not configured)")
    except Exception as e:
        print(f"[manual-alert] title-watch 등록 실패 (non-fatal): {e}")

    yield
    # server 에서는 start 하지 않았으므로, 실행 중일 때만 정리한다.
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    if _rhwp_scheduler.running:
        _rhwp_scheduler.shutdown(wait=False)
    if _alert_scheduler.running:
        _alert_scheduler.shutdown(wait=False)

from backend.routers import (
    auth,
    tasks,
    customers,
    daily,
    memos,
    events,
    board,
    scan,
    scan_workspace,
    scan_roi_preset,
    admin,
    search,
    reference,
    quick_doc,
    manual,
    guidelines,
    guideline_categories,
    marketing,
    signature,
    certification,
    business_card,
    health as health_router,
)

app = FastAPI(
    title="K.ID 출입국업무관리 API",
    version="2.0.0",
    description="출입국 업무관리 시스템 REST API",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,https://kid-saas.vercel.app"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 라우터 등록 ───────────────────────────────────────────────────────────────
app.include_router(auth.router,      prefix="/api/auth",      tags=["인증"])
app.include_router(tasks.router,     prefix="/api/tasks",     tags=["업무"])
app.include_router(customers.router, prefix="/api/customers", tags=["고객관리"])
app.include_router(daily.router,     prefix="/api/daily",     tags=["결산"])
app.include_router(memos.router,     prefix="/api/memos",     tags=["메모"])
app.include_router(events.router,    prefix="/api/events",    tags=["일정"])
app.include_router(board.router,     prefix="/api/board",     tags=["게시판"])
app.include_router(scan.router,      prefix="/api/scan",      tags=["OCR 스캔"])
app.include_router(scan_workspace.router,   prefix="/api/scan-workspace", tags=["OCR 작업판"])
app.include_router(scan_roi_preset.router, prefix="/api/scan",            tags=["ROI 프리셋"])
app.include_router(admin.router,     prefix="/api/admin",     tags=["관리자"])
app.include_router(search.router,    prefix="/api/search",    tags=["통합검색"])
app.include_router(reference.router, prefix="/api/reference", tags=["업무참고"])
app.include_router(quick_doc.router, prefix="/api/quick-doc", tags=["문서자동작성"])
app.include_router(manual.router,    prefix="/api/manual",     tags=["메뉴얼검색"])
app.include_router(guidelines.router, prefix="/api/guidelines", tags=["실무지침"])
app.include_router(guideline_categories.router, prefix="/api/guideline-categories", tags=["실무지침 분류"])
app.include_router(marketing.router,  prefix="/api/marketing",  tags=["마케팅"])
app.include_router(signature.router,      prefix="/api/signature",               tags=["서명"])
app.include_router(certification.router,  prefix="/api/certification-services",  tags=["각종공인증"])
app.include_router(business_card.router,   prefix="/api",                          tags=["전자명함"])
app.include_router(health_router.router,  prefix="/health",                       tags=["헬스체크"])

# ── Local-beta only: PostgreSQL dev endpoints ─────────────────────────────────
# These endpoints exist behind feature flags and are only mounted when
# HANWOORY_ENV=local. On the production server (HANWOORY_ENV=server) the
# router is never imported, so no surface area is exposed.
try:
    from config import RUN_ENV as _RUN_ENV
except Exception:
    _RUN_ENV = "server"
if _RUN_ENV == "local":
    from backend.routers import dev_pg as _dev_pg
    app.include_router(_dev_pg.router, prefix="/api/dev/pg", tags=["로컬베타-PG"])


@app.get("/health")
def health():
    return {"status": "ok"}
