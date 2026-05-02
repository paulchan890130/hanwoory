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


@router.delete("/accounts/{login_id}")
def delete_account(
    login_id: str,
    user: dict = Depends(require_admin),
):
    """계정 비활성화 (소프트 삭제). is_active=FALSE → 로그인 즉시 차단."""
    from core.google_sheets import read_data_from_sheet, upsert_rows_by_id
    from config import ACCOUNTS_SHEET_NAME
    from backend.services.accounts_service import ACCOUNTS_SCHEMA

    if login_id.strip() == str(user.get("login_id", "")).strip():
        raise HTTPException(status_code=400, detail="자신의 계정은 삭제할 수 없습니다.")

    records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[])
    target = None
    for r in records:
        if str(r.get("login_id", "")).strip() == login_id.strip():
            target = r
            break

    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    # 이미 비활성이면 idempotent 성공 반환
    if str(target.get("is_active", "")).upper() == "FALSE":
        return {"ok": True, "login_id": login_id, "already_inactive": True}

    target["is_active"] = "FALSE"

    header_list = ACCOUNTS_SCHEMA[:]
    for k in target:
        if k not in header_list:
            header_list.append(k)

    try:
        ok = upsert_rows_by_id(
            ACCOUNTS_SHEET_NAME,
            header_list=header_list,
            records=[target],
            id_field="login_id",
        )
    except Exception as e:
        import logging
        logging.getLogger("admin.delete").error("upsert_rows_by_id 실패: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"계정 비활성화 실패: {e}")

    if not ok:
        raise HTTPException(status_code=500, detail="계정 비활성화 실패 (upsert 반환 False)")

    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {"ok": True, "login_id": login_id}


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

    # folder_id / customer_sheet_key / work_sheet_key가 이미 제공된 경우에만 즉시 활성화.
    # 미제공 시 is_active=FALSE → 워크스페이스 생성 후 자동으로 TRUE가 됨.
    provided_folder = bool((body.folder_id or "").strip())
    provided_customer = bool((body.customer_sheet_key or "").strip())
    provided_work = bool((body.work_sheet_key or "").strip())
    immediate_active = provided_folder and provided_customer and provided_work

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
        is_active=immediate_active,  # 워크스페이스 키가 모두 있을 때만 즉시 활성화
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
    테넌트 워크스페이스 생성/재생성 (멱등성 보장).

    단계별 독립 실행:
      A. Drive 폴더 — 이미 folder_id가 Accounts에 있으면 재사용
      B. 고객 데이터 시트 복사 — 이미 customer_sheet_key가 있으면 건너뜀
      C. 업무정리 시트 복사 — 이미 work_sheet_key가 있으면 건너뜀
      D. Accounts 행 업데이트 — 성공한 ID만 기입, 기존 값 파괴 안 함
      E. is_active=TRUE — 세 키가 모두 채워졌을 때만 설정

    부분 성공 시 성공한 ID는 저장되며 실패 단계만 재시도 가능.
    """
    import logging
    log = logging.getLogger("admin.workspace")

    import config as _cfg
    from config import (
        ACCOUNTS_SHEET_NAME,
        PARENT_DRIVE_FOLDER_ID,
        CUSTOMER_DATA_TEMPLATE_ID,
        WORK_REFERENCE_TEMPLATE_ID,
    )
    # ── DIAGNOSTIC: prove which config.py the live process is using ──────────
    import os as _os
    log.warning(
        "[workspace:DIAG] pid=%s | config.__file__=%s | "
        "WORK_REFERENCE_TEMPLATE_ID=%s | CUSTOMER_DATA_TEMPLATE_ID=%s | "
        "PARENT_DRIVE_FOLDER_ID=%s",
        _os.getpid(),
        getattr(_cfg, "__file__", "(unknown)"),
        WORK_REFERENCE_TEMPLATE_ID,
        CUSTOMER_DATA_TEMPLATE_ID,
        PARENT_DRIVE_FOLDER_ID,
    )
    # ── END DIAGNOSTIC ────────────────────────────────────────────────────────
    from core.google_sheets import read_data_from_sheet, upsert_rows_by_id
    from backend.services.accounts_service import ACCOUNTS_SCHEMA

    login_id = body.login_id.strip()
    office_name = body.office_name.strip() or login_id

    # ── 현재 계정 상태 로드 ──────────────────────────────────────────────────
    current_folder_id = ""
    current_customer_key = ""
    current_work_key = ""
    target_record = None
    try:
        existing = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
        for r in existing:
            if str(r.get("login_id", "")).strip() == login_id:
                target_record = r
                current_folder_id = str(r.get("folder_id", "")).strip()
                current_customer_key = str(r.get("customer_sheet_key", "")).strip()
                current_work_key = str(r.get("work_sheet_key", "")).strip()
                break
        log.info(
            "[workspace] %s 현재 상태: folder=%s, customer=%s, work=%s",
            login_id, bool(current_folder_id), bool(current_customer_key), bool(current_work_key),
        )
    except Exception as e:
        log.warning("[workspace] Accounts 상태 조회 실패: %s (계속 진행)", e)

    if target_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"login_id='{login_id}' 계정을 찾을 수 없습니다. 먼저 계정을 생성하세요.",
        )

    # ── Drive 서비스 초기화 (admin user OAuth — templates live in admin My Drive) ─
    # Service account cannot copy files it does not own in the admin's My Drive.
    # Use the pre-existing admin user OAuth token (token.json) instead.
    try:
        from googleapiclient.discovery import build as _build
        from core.google_sheets import get_user_credentials

        _SCOPES = ["https://www.googleapis.com/auth/drive"]
        _oauth_creds = get_user_credentials(_SCOPES)
        drive = _build("drive", "v3", credentials=_oauth_creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Drive 초기화 실패 (OAuth): {e}")

    # ── Drive 스토리지 쿼터 진단 (로그만, 에러 아님) ─────────────────────────
    try:
        about = drive.about().get(fields="user,storageQuota").execute()
        sa_email = about.get("user", {}).get("emailAddress", "(unknown)")
        quota = about.get("storageQuota", {})
        used = int(quota.get("usage", 0))
        limit = int(quota.get("limit", -1))
        log.info(
            "[workspace] Drive 사용자: %s | 사용: %d MB / 한도: %s MB",
            sa_email,
            used // (1024 * 1024),
            str(limit // (1024 * 1024)) if limit > 0 else "unlimited",
        )
    except Exception as e:
        log.warning("[workspace] Drive 쿼터 조회 실패: %s", e)
        sa_email = "(unknown)"
        quota = {}

    # ── 단계별 결과 추적 ─────────────────────────────────────────────────────
    stages: dict = {
        "folder_create":   {"status": "skipped", "id": current_folder_id, "error": None},
        "customer_copy":   {"status": "skipped", "id": current_customer_key, "error": None},
        "work_copy":       {"status": "skipped", "id": current_work_key, "error": None},
        "accounts_update": {"status": "pending", "error": None},
    }

    folder_id = current_folder_id
    customer_sheet_key = current_customer_key
    work_sheet_key = current_work_key

    # ── A. 폴더 생성/재사용 ──────────────────────────────────────────────────
    if folder_id:
        log.info("[workspace] 폴더 재사용: %s", folder_id)
        stages["folder_create"]["status"] = "reused"
    else:
        log.info("[workspace] 폴더 생성 시작 (parent=%s)", PARENT_DRIVE_FOLDER_ID)
        try:
            folder_meta = {
                "name": login_id,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [PARENT_DRIVE_FOLDER_ID],
            }
            folder = drive.files().create(
                body=folder_meta,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            folder_id = folder["id"]
            stages["folder_create"] = {"status": "created", "id": folder_id, "error": None}
            log.info("[workspace] 폴더 생성 완료: %s", folder_id)
        except Exception as e:
            import traceback
            err_msg = str(e)
            stages["folder_create"] = {"status": "failed", "id": "", "error": err_msg}
            log.error(
                "[workspace] 폴더 생성 실패 | parent=%s | sa=%s | error=%s\n%s",
                PARENT_DRIVE_FOLDER_ID, sa_email, err_msg, traceback.format_exc(),
            )
            # 폴더 없으면 이후 단계 의미 없음 → 즉시 부분 결과 반환
            stages["customer_copy"]["status"] = "blocked"
            stages["work_copy"]["status"] = "blocked"
            stages["accounts_update"]["status"] = "blocked"
            return {
                "ok": False,
                "stages": stages,
                "folder_id": folder_id,
                "customer_sheet_key": customer_sheet_key,
                "work_sheet_key": work_sheet_key,
                "is_active": False,
                "drive_user": sa_email,
                "drive_quota": quota,
                "error": f"폴더 생성 실패: {err_msg}",
            }

    # ── shared probe helper (inline) ─────────────────────────────────────────
    import traceback as _tb
    import json as _json

    def _probe_template(file_id: str, label: str) -> dict:
        """
        files.get() the template before attempting a copy.
        Returns a dict with probe results; never raises.
        Distinguishes:
          - not_accessible : files.get() itself failed (404 / 403 at read level)
          - readable       : files.get() succeeded → check capabilities.canCopy
          - domain_policy  : error reason contains 'domainPolicy' / 'sharingNotSupported'
        """
        result = {"accessible": False, "can_copy": None, "metadata": None, "error": None, "reason": None}
        try:
            meta = drive.files().get(
                fileId=file_id,
                fields="id,name,mimeType,owners,sharingUser,capabilities,driveId,teamDriveId,parents",
                supportsAllDrives=True,
            ).execute()
            result["accessible"] = True
            result["metadata"] = {
                "id":       meta.get("id"),
                "name":     meta.get("name"),
                "mimeType": meta.get("mimeType"),
                "owners":   meta.get("owners"),
                "driveId":  meta.get("driveId") or meta.get("teamDriveId"),
                "parents":  meta.get("parents"),
            }
            caps = meta.get("capabilities", {})
            result["can_copy"] = caps.get("canCopy")
            result["capabilities"] = caps
            log.warning(
                "[workspace:PROBE] %s | file_id=%s | accessible=True | can_copy=%s | "
                "name=%r | mimeType=%s | driveId=%s | sa=%s | dest_folder=%s | caps=%s",
                label, file_id, caps.get("canCopy"), meta.get("name"), meta.get("mimeType"),
                meta.get("driveId") or meta.get("teamDriveId") or "(MyDrive)",
                sa_email, folder_id, _json.dumps(caps),
            )
        except Exception as probe_err:
            raw = str(probe_err)
            # Extract structured reason from googleapiclient HttpError if present
            reason = raw
            try:
                import googleapiclient.errors as _ge
                if isinstance(probe_err, _ge.HttpError):
                    body = _json.loads(probe_err.content.decode())
                    reason = (
                        body.get("error", {}).get("errors", [{}])[0].get("reason", raw)
                        + " | message: "
                        + body.get("error", {}).get("message", raw)
                    )
            except Exception:
                pass
            result["error"] = raw
            result["reason"] = reason
            log.warning(
                "[workspace:PROBE] %s | file_id=%s | accessible=False | "
                "raw_error=%s | reason=%s | sa=%s | dest_folder=%s",
                label, file_id, raw, reason, sa_email, folder_id,
            )
        return result

    # ── B. 고객 데이터 시트 복사/재사용 ─────────────────────────────────────
    if customer_sheet_key:
        log.info("[workspace] 고객 데이터 시트 재사용: %s", customer_sheet_key)
        stages["customer_copy"]["status"] = "reused"
    else:
        probe_c = _probe_template(CUSTOMER_DATA_TEMPLATE_ID, "customer_template")
        stages["customer_copy"]["probe"] = {
            "accessible": probe_c["accessible"],
            "can_copy":   probe_c["can_copy"],
            "reason":     probe_c["reason"],
            "metadata":   probe_c.get("metadata"),
        }
        log.info(
            "[workspace] 고객 데이터 시트 복사 시작 | template=%s | dest_parent=%s | sa=%s",
            CUSTOMER_DATA_TEMPLATE_ID, folder_id, sa_email,
        )
        try:
            customer_copy = drive.files().copy(
                fileId=CUSTOMER_DATA_TEMPLATE_ID,
                body={
                    "name": f"고객 데이터 - {office_name}",
                    "parents": [folder_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
            customer_sheet_key = customer_copy["id"]
            stages["customer_copy"]["status"] = "created"
            stages["customer_copy"]["id"] = customer_sheet_key
            stages["customer_copy"]["error"] = None
            log.info("[workspace] 고객 데이터 시트 복사 완료: %s", customer_sheet_key)
        except Exception as e:
            err_msg = str(e)
            # Extract raw API reason
            try:
                import googleapiclient.errors as _ge
                if isinstance(e, _ge.HttpError):
                    body = _json.loads(e.content.decode())
                    api_reason = (
                        body.get("error", {}).get("errors", [{}])[0].get("reason", "")
                        + " | " + body.get("error", {}).get("message", "")
                    )
                else:
                    api_reason = err_msg
            except Exception:
                api_reason = err_msg
            stages["customer_copy"]["status"] = "failed"
            stages["customer_copy"]["id"] = ""
            stages["customer_copy"]["error"] = err_msg
            stages["customer_copy"]["api_reason"] = api_reason
            log.error(
                "[workspace] 고객 데이터 시트 복사 실패 | template=%s | dest_parent=%s | "
                "sa=%s | api_reason=%s | raw=%s\n%s",
                CUSTOMER_DATA_TEMPLATE_ID, folder_id, sa_email,
                api_reason, err_msg, _tb.format_exc(),
            )

    # ── C. 업무정리 시트 복사/재사용 ─────────────────────────────────────────
    if work_sheet_key:
        log.info("[workspace] 업무정리 시트 재사용: %s", work_sheet_key)
        stages["work_copy"]["status"] = "reused"
    else:
        probe_w = _probe_template(WORK_REFERENCE_TEMPLATE_ID, "work_template")
        stages["work_copy"]["probe"] = {
            "accessible": probe_w["accessible"],
            "can_copy":   probe_w["can_copy"],
            "reason":     probe_w["reason"],
            "metadata":   probe_w.get("metadata"),
        }
        log.info(
            "[workspace] 업무정리 시트 복사 시작 | template=%s | dest_parent=%s | sa=%s",
            WORK_REFERENCE_TEMPLATE_ID, folder_id, sa_email,
        )
        try:
            tasks_copy = drive.files().copy(
                fileId=WORK_REFERENCE_TEMPLATE_ID,
                body={
                    "name": f"업무정리 - {office_name}",
                    "parents": [folder_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
            work_sheet_key = tasks_copy["id"]
            stages["work_copy"]["status"] = "created"
            stages["work_copy"]["id"] = work_sheet_key
            stages["work_copy"]["error"] = None
            log.info("[workspace] 업무정리 시트 복사 완료: %s", work_sheet_key)
        except Exception as e:
            err_msg = str(e)
            try:
                import googleapiclient.errors as _ge
                if isinstance(e, _ge.HttpError):
                    body = _json.loads(e.content.decode())
                    api_reason = (
                        body.get("error", {}).get("errors", [{}])[0].get("reason", "")
                        + " | " + body.get("error", {}).get("message", "")
                    )
                else:
                    api_reason = err_msg
            except Exception:
                api_reason = err_msg
            stages["work_copy"]["status"] = "failed"
            stages["work_copy"]["id"] = ""
            stages["work_copy"]["error"] = err_msg
            stages["work_copy"]["api_reason"] = api_reason
            log.error(
                "[workspace] 업무정리 시트 복사 실패 | template=%s | dest_parent=%s | "
                "sa=%s | api_reason=%s | raw=%s\n%s",
                WORK_REFERENCE_TEMPLATE_ID, folder_id, sa_email,
                api_reason, err_msg, _tb.format_exc(),
            )

    # ── D. Accounts 시트 업데이트 ────────────────────────────────────────────
    # 세 키가 모두 있을 때만 is_active=TRUE 설정
    all_ready = bool(folder_id and customer_sheet_key and work_sheet_key)

    try:
        if folder_id:
            target_record["folder_id"] = folder_id
        if customer_sheet_key:
            target_record["customer_sheet_key"] = customer_sheet_key
        if work_sheet_key:
            target_record["work_sheet_key"] = work_sheet_key
        if all_ready:
            target_record["is_active"] = "TRUE"
            log.info("[workspace] %s → is_active=TRUE (모든 키 확보)", login_id)

        # ACCOUNTS_SCHEMA 순서로 header 정렬 (컬럼 위치 오염 방지)
        header_list = ACCOUNTS_SCHEMA[:]
        for k in target_record:
            if k not in header_list:
                header_list.append(k)

        upsert_rows_by_id(
            ACCOUNTS_SHEET_NAME,
            header_list=header_list,
            records=[target_record],
            id_field="login_id",
        )
        stages["accounts_update"] = {"status": "saved", "error": None}
        log.info("[workspace] Accounts 업데이트 완료 (is_active=%s)", target_record.get("is_active"))

        # 캐시 초기화
        try:
            import backend.services.tenant_service as _ts
            _ts._TENANT_MAP_CACHE = {}
            _ts._TENANT_MAP_TIME = 0
        except Exception:
            pass

    except Exception as e:
        err_msg = str(e)
        stages["accounts_update"] = {"status": "failed", "error": err_msg}
        log.error("[workspace] Accounts 업데이트 실패: %s", err_msg)

    # ── 최종 응답 ────────────────────────────────────────────────────────────
    any_failed = any(
        s.get("status") == "failed"
        for s in stages.values()
    )
    return {
        "ok": not any_failed,
        "stages": stages,
        "folder_id": folder_id,
        "customer_sheet_key": customer_sheet_key,
        "work_sheet_key": work_sheet_key,
        "is_active": all_ready,
        "drive_user": sa_email,
    }
