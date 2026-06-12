"""게시판 라우터 - 기존 Streamlit page_board.py 구조 복원
헤더: id, tenant_id, author_login, office_name, is_notice, category, title, content, created_at, updated_at
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.models import BoardPost, BoardComment

router = APIRouter()

# 기존 Streamlit page_board.py BOARD_HEADERS와 동일
POST_HEADER = [
    "id", "tenant_id", "author_login", "office_name",
    "is_notice", "category", "title", "content",
    "created_at", "updated_at",
    "popup_yn", "link_url", "comment_count",
]

HIKOREA_MANUAL_URL = (
    "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt"
    "?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1"
)
_MANUAL_CHECK_CATEGORY = "__manual_check__"
_MANUAL_NOTICE_CATEGORY = "__manual_notice__"
COMMENT_HEADER = [
    "id", "post_id", "tenant_id", "author_login", "office_name",
    "content", "created_at", "updated_at",
]


# PG-only(Phase H): 게시판은 board_pg_service 만 사용. Google Sheets(core.google_sheets) helper 제거.


@router.get("/popup")
def get_popup_notices(user: dict = Depends(get_current_user)):
    """팝업 표시 공지 목록 (popup_yn=Y) — PG-only(Phase H).

    시스템 자동공지(__manual_check__ / __manual_notice__)는 관리자 검토용이므로
    popup_yn 값과 무관하게 사용자 팝업 후보에서 항상 제외한다(방어적 차단)."""
    from backend.services.board_pg_service import list_posts
    posts = list_posts(exclude_categories=(_MANUAL_CHECK_CATEGORY, _MANUAL_NOTICE_CATEGORY))
    result = [p for p in posts if str(p.get("popup_yn", "")).strip().upper() == "Y"]
    result.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return result


@router.get("/check-manual")
def check_manual_update(user: dict = Depends(get_current_user)):
    """하이코리아 메뉴얼 첨부파일 날짜 변경 감지 (관리자 전용)"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="관리자만 사용 가능합니다.")

    import re
    import requests as req

    try:
        resp = req.get(
            HIKOREA_MANUAL_URL,
            timeout=12,
            verify=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"하이코리아 접근 실패: {exc}") from exc

    # 첨부파일 날짜: YYYY.MM.DD 또는 YYYY-MM-DD 형식 추출 후 최신값 사용
    dates = re.findall(r"\d{4}[.\-]\d{2}[.\-]\d{2}", html)
    if not dates:
        raise HTTPException(status_code=502, detail="날짜 정보를 찾을 수 없습니다.")
    latest_date = max(d.replace(".", "-") for d in dates)

    # PG-only(Phase H): 게시판 읽기/쓰기는 board_pg_service.
    from backend.services.board_pg_service import list_posts, upsert_post
    posts = list_posts()  # __system__ 포함 전체

    check_post = next((p for p in posts if p.get("category") == _MANUAL_CHECK_CATEGORY), None)
    stored_date = check_post.get("content", "") if check_post else ""

    if latest_date == stored_date:
        return {"updated": False, "date": latest_date}

    now = datetime.datetime.now().isoformat()

    # 감지 기록 갱신
    check_id = check_post.get("id") if check_post else str(uuid.uuid4())
    upsert_post({
        "id": check_id, "tenant_id": "__system__", "author_login": "__system__",
        "author": "__system__", "office_name": "", "is_notice": "",
        "category": _MANUAL_CHECK_CATEGORY, "title": "",
        "content": latest_date,
        "created_at": check_post.get("created_at", now) if check_post else now,
        "updated_at": now, "popup_yn": "", "link_url": "",
    })

    # 공지 등록/갱신
    notice_post = next((p for p in posts if p.get("category") == _MANUAL_NOTICE_CATEGORY), None)
    notice_id = notice_post.get("id") if notice_post else str(uuid.uuid4())
    upsert_post({
        "id": notice_id, "tenant_id": "__system__", "author_login": "__system__",
        "author": "__system__", "office_name": "시스템", "is_notice": "Y",
        "category": _MANUAL_NOTICE_CATEGORY,
        "title": f"메뉴얼 업데이트({latest_date})",
        "content": f"하이코리아 메뉴얼이 {latest_date}에 업데이트되었습니다.\n첨부파일을 확인하세요.",
        "created_at": notice_post.get("created_at", now) if notice_post else now,
        "updated_at": now, "popup_yn": "Y", "link_url": HIKOREA_MANUAL_URL,
    })

    return {"updated": True, "date": latest_date, "previous_date": stored_date}


@router.get("")
def get_posts(user: dict = Depends(get_current_user)):
    """게시판 목록 - 공지 상단, 나머지 최신순 — PG-only(Phase H)."""
    from backend.services.board_pg_service import list_posts
    posts = list_posts(exclude_categories=(_MANUAL_CHECK_CATEGORY,))
    notices = [p for p in posts if str(p.get("is_notice", "")).strip().upper() == "Y"]
    normal  = [p for p in posts if str(p.get("is_notice", "")).strip().upper() != "Y"]
    notices.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    normal.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return notices + normal


@router.post("", response_model=dict)
def create_post(post: BoardPost, user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_board_enabled
    import traceback as _tb
    now = datetime.datetime.now().isoformat()
    post.id          = str(uuid.uuid4())
    post.tenant_id   = user.get("tenant_id", "")
    post.author_login= user.get("login_id", "")
    post.author      = user.get("login_id", "")  # 하위호환
    post.office_name = user.get("office_name", "")
    post.created_at  = now
    post.updated_at  = now
    # 관리자가 아닌 경우 is_notice / popup_yn 강제 해제
    if not user.get("is_admin", False):
        post.is_notice = ""
        post.popup_yn = ""
    rec = {k: ("" if v is None else str(v)) for k, v in post.model_dump().items()}
    rec["comment_count"] = "0"
    # PG-only(Phase H).
    from backend.services.board_pg_service import upsert_post
    return upsert_post(rec)


@router.put("/{post_id}", response_model=dict)
def update_post(post_id: str, post: BoardPost, user: dict = Depends(get_current_user)):
    # PG-only(Phase H): 기존 글 조회(작성자 확인 + 서버 필드 보존) 후 부분 수정 upsert.
    from backend.services.board_pg_service import list_posts, upsert_post
    existing = next((p for p in list_posts() if p.get("id") == post_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    is_own = existing.get("author_login") == user.get("login_id")
    if not (is_own or user.get("is_admin", False)):
        raise HTTPException(status_code=403, detail="수정 권한 없음")
    # 클라이언트가 실제로 보낸 필드만 덮어쓴다(exclude_unset) — 기존 popup_yn/is_notice 등 보존.
    # (BoardPost 기본값이 ""이라 'is not None' 가드는 미전송 필드를 ""로 덮어쓰는 버그가 있었다.)
    sent = post.model_dump(exclude_unset=True)
    rec = {k: str(existing.get(k, "")) for k in POST_HEADER}
    for f in ("title", "content", "category"):
        if f in sent and sent[f] is not None:
            rec[f] = str(sent[f])
    rec["id"]         = post_id
    rec["updated_at"] = datetime.datetime.now().isoformat()
    if not user.get("is_admin", False):
        rec["is_notice"] = ""
        rec["popup_yn"] = ""
    else:
        if "is_notice" in sent and sent["is_notice"] is not None:
            rec["is_notice"] = str(sent["is_notice"])
        if "popup_yn" in sent and sent["popup_yn"] is not None:
            rec["popup_yn"] = str(sent["popup_yn"])
    return upsert_post(rec)


@router.delete("/{post_id}")
def delete_post(post_id: str, user: dict = Depends(get_current_user)):
    # PG-only(Phase H): 권한 확인 후 삭제(댓글 cascade 는 board_pg_service.delete_post 가 처리).
    from backend.services.board_pg_service import list_posts, delete_post as _pg
    existing = next((p for p in list_posts() if p.get("id") == post_id), None)
    if existing:
        is_own = existing.get("author_login") == user.get("login_id")
        if not (is_own or user.get("is_admin", False)):
            raise HTTPException(status_code=403, detail="삭제 권한 없음")
    _pg(post_id)
    return {"ok": True}


@router.get("/{post_id}/comments")
def get_comments(post_id: str, user: dict = Depends(get_current_user)):
    # PG-only(Phase H).
    from backend.services.board_pg_service import list_comments
    return list_comments(post_id)


@router.post("/{post_id}/comments", response_model=dict)
def add_comment(post_id: str, comment: BoardComment, user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_board_enabled
    now = datetime.datetime.now().isoformat()
    comment.id          = str(uuid.uuid4())
    comment.post_id     = post_id
    comment.author_login= user.get("login_id", "")
    comment.author      = user.get("login_id", "")
    comment.office_name = user.get("office_name", "")
    comment.tenant_id   = user.get("tenant_id", "")
    comment.created_at  = now
    comment.updated_at  = now
    rec = {k: ("" if v is None else str(v)) for k, v in comment.model_dump().items()}
    # PG-only(Phase H): comment_count 증가는 board_pg_service.add_comment 가 처리.
    from backend.services.board_pg_service import add_comment as _pg
    return _pg(rec)


@router.delete("/{post_id}/comments/{comment_id}")
def delete_comment(post_id: str, comment_id: str, user: dict = Depends(get_current_user)):
    """댓글 삭제 — PG-only(Phase H). 권한(Phase H-1):
    관리자=전체 / 일반=본인 작성분만 / 작성자 정보 없는 레거시=관리자만. 무인증=401(Depends), 없음=404.
    comment_count 감소·게시글 삭제 cascade 는 board_pg_service 가 처리."""
    from backend.services.board_pg_service import list_comments, delete_comment as _pg
    existing = next((c for c in list_comments(post_id) if c.get("id") == comment_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
    is_admin = bool(user.get("is_admin", False))
    author = str(existing.get("author_login", "")).strip()
    is_own = bool(author) and author == str(user.get("login_id", "")).strip()
    if not (is_admin or is_own):
        # 본인도 관리자도 아니거나, 작성자 정보 없는 레거시 댓글을 일반 사용자가 삭제 시도
        raise HTTPException(status_code=403, detail="삭제 권한 없음")
    _pg(post_id, comment_id)
    return {"ok": True}
