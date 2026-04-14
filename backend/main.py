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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    admin,
    search,
    reference,
    quick_doc,
    manual,
    guidelines,
)

app = FastAPI(
    title="K.ID 출입국업무관리 API",
    version="2.0.0",
    description="출입국 업무관리 시스템 REST API",
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
app.include_router(scan_workspace.router, prefix="/api/scan-workspace",  tags=["OCR 작업판"])
app.include_router(admin.router,     prefix="/api/admin",     tags=["관리자"])
app.include_router(search.router,    prefix="/api/search",    tags=["통합검색"])
app.include_router(reference.router, prefix="/api/reference", tags=["업무참고"])
app.include_router(quick_doc.router, prefix="/api/quick-doc", tags=["문서자동작성"])
app.include_router(manual.router,    prefix="/api/manual",     tags=["메뉴얼검색"])
app.include_router(guidelines.router, prefix="/api/guidelines", tags=["실무지침"])


@app.get("/health")
def health():
    return {"status": "ok"}
