"""관리자 라우터 - 계정 관리 + 워크스페이스 자동 생성"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user, require_admin
from backend.models import AccountUpdate, AccountCreate

router = APIRouter()

@router.post("/bootstrap")
def bootstrap_admin(body: AccountCreate):
    """
    최초 관리자 계정 생성 — 인증 불필요.
    Accounts 시트에 데이터 행이 하나도 없을 때만 동작합니다.
    계정이 1개라도 있으면 403 반환 (중복 부트스트랩 방지).

    모든 Accounts 읽기·쓰기는 accounts_service 경유 (서비스 계정 사용).
    """
    from config import KEY_PATH
    from backend.services.accounts_service import (
        ACCOUNTS_SCHEMA,
        hash_password,
        build_account_dict,
        dict_to_row,
        ensure_header,
        _get_ws,
    )

    import os as _os
    if not _os.path.isfile(KEY_PATH):
        raise HTTPException(status_code=500, detail=f"서비스 계정 키 파일 없음: {KEY_PATH}")

    # ── Accounts 워크시트 열기 ─────────────────────────────────────────────
    try:
        ws = _get_ws()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Accounts 시트 열기 실패: {e}")

    # ── 기존 데이터 행 확인 → 있으면 차단 ─────────────────────────────────
    try:
        existing_values = ws.get_all_values()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Accounts 시트 읽기 실패: {e}")

    # 1행은 헤더이므로 2행 이상에 값이 있으면 계정 존재로 판단
    data_rows = [r for r in existing_values[1:] if any(c.strip() for c in r)] if len(existing_values) > 1 else []
    if data_rows:
        raise HTTPException(
            status_code=403,
            detail="이미 계정이 존재합니다. bootstrap은 최초 1회만 사용 가능합니다. "
                   "계정 추가는 관리자 로그인 후 POST /api/admin/accounts 를 사용하세요.",
        )

    # ── 16컬럼 account dict 생성 ───────────────────────────────────────────
    account = build_account_dict(
        login_id=body.login_id,
        password_hash=hash_password(body.password),
        tenant_id=body.tenant_id or "",   # 미입력 시 build_account_dict가 login_id로 설정
        office_name=body.office_name,
        office_adr=body.office_adr or "",
        contact_name=body.contact_name or "",
        contact_tel=body.contact_tel or "",
        biz_reg_no=body.biz_reg_no or "",
        agent_rrn=body.agent_rrn or "",
        folder_id=body.folder_id or "",
        work_sheet_key=body.work_sheet_key or "",
        customer_sheet_key=body.customer_sheet_key or "",
        sheet_key=body.sheet_key or "",
        is_admin=True,   # bootstrap = 항상 관리자
        is_active=True,
    )
    data_row = dict_to_row(account)

    try:
        if not existing_values:
            # 완전히 빈 시트: 헤더 + 데이터 한 번에 기록
            ws.update("A1", [ACCOUNTS_SCHEMA, data_row], value_input_option="USER_ENTERED")
        else:
            # 헤더만 있고(또는 헤더가 다르고) 데이터 없음 → 헤더 보정 후 append
            ensure_header(ws)
            ws.append_row(data_row, value_input_option="USER_ENTERED")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"계정 생성 실패 — Sheets 쓰기 오류: {e}")

    # ── 테넌트 캐시 초기화 ─────────────────────────────────────────────────
    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {
        "ok": True,
        "login_id": body.login_id.strip(),
        "message": "최초 관리자 계정이 생성되었습니다. 이 엔드포인트는 더 이상 사용할 수 없습니다.",
    }

def _get_service_account_path() -> str:
    """기존 config.py KEY_PATH 구조와 동일한 방식으로 서비스 계정 경로 반환."""
    try:
        from config import KEY_PATH
        return KEY_PATH
    except ImportError:
        # config.py 없을 경우 환경변수 → 기본 경로 순서로 fallback
        return os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/etc/secrets/hanwoory-9eaa1a4c54d7.json",
        )


class WorkspaceCreateRequest(BaseModel):
    login_id: str
    office_name: str


@router.get("/accounts")
def list_accounts(user: dict = Depends(require_admin)):
    from core.google_sheets import read_data_from_sheet
    from config import ACCOUNTS_SHEET_NAME
    records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[])
    # 비밀번호 해시 제거 후 반환
    safe = []
    for r in records:
        r2 = {k: v for k, v in r.items() if k != "password_hash"}
        safe.append(r2)
    return safe


@router.put("/accounts/{login_id}")
def update_account(
    login_id: str,
    update: AccountUpdate,
    user: dict = Depends(require_admin),
):
    from core.google_sheets import read_data_from_sheet, upsert_rows_by_id
    from config import ACCOUNTS_SHEET_NAME

    records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[])
    target = None
    for r in records:
        if str(r.get("login_id", "")).strip() == login_id.strip():
            target = r
            break

    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    # Boolean 필드
    if update.is_active is not None:
        target["is_active"] = "TRUE" if update.is_active else "FALSE"
    if update.is_admin is not None:
        target["is_admin"] = "TRUE" if update.is_admin else "FALSE"
    # 문자열 필드 — None 이 아닐 때만 업데이트 (빈 문자열도 덮어씀)
    for field in (
        "tenant_id", "work_sheet_key", "customer_sheet_key",
        "folder_id", "office_name", "office_adr",
        "contact_name", "contact_tel", "biz_reg_no",
        "agent_rrn", "sheet_key",
    ):
        val = getattr(update, field, None)
        if val is not None:
            target[field] = val

    # 표준 스키마 순서로 헤더 정렬 (없는 컬럼은 끝에 추가)
    from backend.services.accounts_service import ACCOUNTS_SCHEMA
    header_list = ACCOUNTS_SCHEMA[:]
    for k in target:
        if k not in header_list:
            header_list.append(k)

    ok = upsert_rows_by_id(
        ACCOUNTS_SHEET_NAME,
        header_list=header_list,
        records=[target],
        id_field="login_id",
    )
    if not ok:
        raise HTTPException(status_code=500, detail="계정 수정 실패")

    # 테넌트 캐시 초기화
    try:
        from core.google_sheets import _load_tenant_sheet_keys
        _load_tenant_sheet_keys.clear()
    except Exception:
        pass
    # tenant_service 캐시도 초기화
    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {"ok": True}


@router.post("/accounts")
def create_account(
    body: AccountCreate,
    user: dict = Depends(require_admin),
):
    """신규 테넌트 계정 생성 (관리자 전용)"""
    from backend.services.accounts_service import (
        hash_password,
        find_account,
        build_account_dict,
        append_account,
    )

    # 중복 체크 (accounts_service → 서비스 계정 사용)
    if find_account(body.login_id.strip()):
        raise HTTPException(status_code=409, detail="이미 존재하는 login_id입니다.")

    account = build_account_dict(
        login_id=body.login_id,
        password_hash=hash_password(body.password),
        tenant_id=body.tenant_id or "",
        office_name=body.office_name,
        office_adr=body.office_adr or "",
        contact_name=body.contact_name or "",
        contact_tel=body.contact_tel or "",
        biz_reg_no=body.biz_reg_no or "",
        agent_rrn=body.agent_rrn or "",
        folder_id=body.folder_id or "",
        work_sheet_key=body.work_sheet_key or "",
        customer_sheet_key=body.customer_sheet_key or "",
        sheet_key=body.sheet_key or "",
        is_admin=bool(body.is_admin),
        is_active=True,
    )

    try:
        append_account(account)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"계정 생성 실패: {e}")

    # 캐시 초기화
    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {"ok": True, "login_id": account["login_id"]}


@router.post("/workspace")
def create_workspace(
    body: WorkspaceCreateRequest,
    user: dict = Depends(require_admin),
):
    """
    신규 테넌트를 위한 Google Drive 워크스페이스 자동 생성:
    1. Drive 폴더 생성
    2. 고객 데이터 스프레드시트 복사
    3. 업무정리 스프레드시트 복사
    4. Accounts 시트의 해당 계정에 customer_sheet_key / work_sheet_key / folder_id 업데이트
    """
    from config import (
        ACCOUNTS_SHEET_NAME,
        PARENT_DRIVE_FOLDER_ID,
        CUSTOMER_DATA_TEMPLATE_ID,
        WORK_REFERENCE_TEMPLATE_ID,
    )

    # ── 기존 워크스페이스 존재 여부 체크 ──
    try:
        from core.google_sheets import read_data_from_sheet
        existing = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
        for r in existing:
            if str(r.get("login_id", "")).strip() == body.login_id.strip():
                if str(r.get("folder_id", "")).strip():
                    raise HTTPException(
                        status_code=409,
                        detail=f"이미 워크스페이스가 존재합니다. folder_id={r['folder_id']}",
                    )
                break
    except HTTPException:
        raise
    except Exception:
        pass  # 체크 실패 시 생성 진행

    # ── Drive 서비스 초기화 ──
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build as _build

        _SCOPES = ["https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(
            _get_service_account_path(),
            scopes=_SCOPES,
        )
        drive = _build("drive", "v3", credentials=creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Drive 초기화 실패: {e}")

    try:
        # 0) 사전 확인: 부모 폴더 / 템플릿 접근 가능 여부
        parent_meta = drive.files().get(
            fileId=PARENT_DRIVE_FOLDER_ID,
            fields="id,name,mimeType,driveId",
            supportsAllDrives=True,
        ).execute()

        customer_template_meta = drive.files().get(
            fileId=CUSTOMER_DATA_TEMPLATE_ID,
            fields="id,name,mimeType,driveId",
            supportsAllDrives=True,
        ).execute()

        work_template_meta = drive.files().get(
            fileId=WORK_REFERENCE_TEMPLATE_ID,
            fields="id,name,mimeType,driveId",
            supportsAllDrives=True,
        ).execute()

        # 1) 폴더 생성
        folder_meta = {
            "name": body.login_id.strip(),
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [PARENT_DRIVE_FOLDER_ID],
        }
        folder = drive.files().create(
            body=folder_meta,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        folder_id: str = folder["id"]

        # 2) 고객 데이터 시트 복사
        customer_copy = drive.files().copy(
            fileId=CUSTOMER_DATA_TEMPLATE_ID,
            body={
                "name": f"고객 데이터 - {body.office_name.strip()}",
                "parents": [folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        customer_sheet_key: str = customer_copy["id"]

        # 3) 업무정리 시트 복사
        tasks_copy = drive.files().copy(
            fileId=WORK_REFERENCE_TEMPLATE_ID,
            body={
                "name": f"업무정리 - {body.office_name.strip()}",
                "parents": [folder_id],
            },
            fields="id",
            supportsAllDrives=True,
        ).execute()
        work_sheet_key: str = tasks_copy["id"]

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Drive 워크스페이스 생성 실패: "
                f"{e} | "
                f"parent={PARENT_DRIVE_FOLDER_ID}, "
                f"customer_template={CUSTOMER_DATA_TEMPLATE_ID}, "
                f"work_template={WORK_REFERENCE_TEMPLATE_ID}"
            ),
        )

    # 4) Accounts 시트 업데이트
    try:
        from core.google_sheets import read_data_from_sheet, upsert_rows_by_id

        records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
        target = None
        for r in records:
            if str(r.get("login_id", "")).strip() == body.login_id.strip():
                target = r
                break

        if not target:
            return {
                "ok": True,
                "warning": "계정을 찾지 못해 시트 키를 자동 기입하지 못했습니다. 직접 입력하세요.",
                "folder_id": folder_id,
                "customer_sheet_key": customer_sheet_key,
                "work_sheet_key": work_sheet_key,
            }

        target["customer_sheet_key"] = customer_sheet_key
        target["work_sheet_key"] = work_sheet_key
        target["folder_id"] = folder_id

        header_list = list(target.keys())
        upsert_rows_by_id(
            ACCOUNTS_SHEET_NAME,
            header_list=header_list,
            records=[target],
            id_field="login_id",
        )

        try:
            import backend.services.tenant_service as _ts
            _ts._TENANT_MAP_CACHE = {}
            _ts._TENANT_MAP_TIME = 0
        except Exception:
            pass

    except Exception as e:
        return {
            "ok": True,
            "warning": f"워크스페이스는 생성됐지만 Accounts 시트 업데이트 실패: {e}",
            "folder_id": folder_id,
            "customer_sheet_key": customer_sheet_key,
            "work_sheet_key": work_sheet_key,
        }

    return {
        "ok": True,
        "folder_id": folder_id,
        "customer_sheet_key": customer_sheet_key,
        "work_sheet_key": work_sheet_key,
        "message": f"워크스페이스 생성 완료 — 폴더 ID: {folder_id}",
    }
