"""Pydantic 모델 정의"""
from typing import Optional, List
from pydantic import BaseModel


# ── 인증 ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    login_id: str
    password: str

class SignupRequest(BaseModel):
    login_id: str
    password: str
    confirm_password: str
    office_name: str
    office_adr: Optional[str] = ""
    biz_reg_no: Optional[str] = ""
    agent_rrn: Optional[str] = ""
    contact_name: Optional[str] = ""
    contact_tel: Optional[str] = ""

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    login_id: str
    tenant_id: str
    is_admin: bool
    office_name: str
    contact_name: str = ""


# ── 업무 ─────────────────────────────────────────────────────────────────────
class ActiveTask(BaseModel):
    id: Optional[str] = None
    category: Optional[str] = ""
    date: Optional[str] = ""
    name: Optional[str] = ""
    work: Optional[str] = ""
    details: Optional[str] = ""
    transfer: Optional[str] = "0"
    cash: Optional[str] = "0"
    card: Optional[str] = "0"
    stamp: Optional[str] = "0"
    receivable: Optional[str] = "0"
    planned_expense: Optional[str] = "0"
    processed: Optional[bool] = False
    processed_timestamp: Optional[str] = ""
    # 업무 단계 타임스탬프 (접수 → 처리 → 보관중)
    reception: Optional[str] = ""
    processing: Optional[str] = ""
    storage: Optional[str] = ""

class PlannedTask(BaseModel):
    id: Optional[str] = None
    date: Optional[str] = ""
    period: Optional[str] = ""
    content: Optional[str] = ""
    note: Optional[str] = ""

class CompletedTask(BaseModel):
    id: Optional[str] = None
    category: Optional[str] = ""
    date: Optional[str] = ""
    name: Optional[str] = ""
    work: Optional[str] = ""
    details: Optional[str] = ""
    complete_date: Optional[str] = ""
    reception: Optional[str] = ""
    processing: Optional[str] = ""
    storage: Optional[str] = ""

class CompleteTasksRequest(BaseModel):
    """진행업무 → 완료업무 이동 요청"""
    task_ids: List[str]

class DeleteTasksRequest(BaseModel):
    task_ids: List[str]

class ProgressUpdate(BaseModel):
    id: str
    reception: str = ""
    processing: str = ""
    storage: str = ""

class BatchProgressRequest(BaseModel):
    updates: List[ProgressUpdate]


# ── 결산 ─────────────────────────────────────────────────────────────────────
class DailyEntry(BaseModel):
    id: Optional[str] = None
    date: Optional[str] = ""
    time: Optional[str] = ""
    category: Optional[str] = ""
    name: Optional[str] = ""
    task: Optional[str] = ""
    income_cash: Optional[int] = 0
    income_etc: Optional[int] = 0
    exp_cash: Optional[int] = 0
    exp_etc: Optional[int] = 0
    cash_out: Optional[int] = 0
    memo: Optional[str] = ""

class BalanceData(BaseModel):
    cash: int = 0
    profit: int = 0


# ── 메모 ─────────────────────────────────────────────────────────────────────
class MemoSaveRequest(BaseModel):
    content: str


# ── 일정 ─────────────────────────────────────────────────────────────────────
class EventItem(BaseModel):
    date_str: str
    event_text: str

class EventsSaveRequest(BaseModel):
    events: List[EventItem]


# ── 게시판 ───────────────────────────────────────────────────────────────────
class BoardPost(BaseModel):
    id: Optional[str] = None
    tenant_id: Optional[str] = ""
    author_login: Optional[str] = ""    # login_id (기존 Streamlit author_login)
    author: Optional[str] = ""          # 하위호환용
    office_name: Optional[str] = ""
    is_notice: Optional[str] = ""       # "Y" or ""
    category: Optional[str] = ""
    title: Optional[str] = ""
    content: Optional[str] = ""
    created_at: Optional[str] = ""
    updated_at: Optional[str] = ""
    popup_yn: Optional[str] = ""        # "Y" or "" — 일일 팝업에 표시
    link_url: Optional[str] = ""        # 클릭 시 이동할 외부 URL

class BoardComment(BaseModel):
    id: Optional[str] = None
    post_id: Optional[str] = ""
    tenant_id: Optional[str] = ""
    author_login: Optional[str] = ""
    author: Optional[str] = ""          # 하위호환
    office_name: Optional[str] = ""
    content: Optional[str] = ""
    created_at: Optional[str] = ""
    updated_at: Optional[str] = ""


# ── 관리자 ───────────────────────────────────────────────────────────────────
class AccountUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
    tenant_id: Optional[str] = None
    work_sheet_key: Optional[str] = None
    customer_sheet_key: Optional[str] = None
    folder_id: Optional[str] = None
    office_name: Optional[str] = None
    office_adr: Optional[str] = None
    contact_name: Optional[str] = None
    contact_tel: Optional[str] = None
    biz_reg_no: Optional[str] = None
    agent_rrn: Optional[str] = None
    sheet_key: Optional[str] = None


class AccountCreate(BaseModel):
    login_id: str
    password: str
    office_name: str
    tenant_id: Optional[str] = ""        # 미입력 시 login_id로 자동 설정
    office_adr: Optional[str] = ""
    contact_name: Optional[str] = ""
    contact_tel: Optional[str] = ""
    biz_reg_no: Optional[str] = ""
    agent_rrn: Optional[str] = ""
    folder_id: Optional[str] = ""
    work_sheet_key: Optional[str] = ""
    customer_sheet_key: Optional[str] = ""
    sheet_key: Optional[str] = ""
    is_admin: Optional[bool] = False
