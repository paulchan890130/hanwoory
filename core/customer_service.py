# core/customer_service.py
import re
import datetime
import uuid
import pandas as pd
try:
    import streamlit as st
except ImportError:
    class _FakeST:
        session_state: dict = {}  # type: ignore
    st = _FakeST()  # type: ignore


# ===== 날짜 입력 정규화(yyyy.mm.dd / yyyy/mm/dd / yyyymmdd → YYYY-MM-DD) =====
_DATE_SEP_RE = re.compile(r"[./\s]+")
_DATE_DIGITS_RE = re.compile(r"^(\d{8})$")  # yyyymmdd
_DATE_HYPHEN_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")  # yyyy-m-d

def normalize_ymd(value: str) -> str:
    """입력 형식이 뭐든 저장은 YYYY-MM-DD로 정규화. 실패 시 원문(trim) 반환."""
    s = str(value or "").strip()
    if not s:
        return ""

    m = _DATE_HYPHEN_RE.match(s)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"

    m = _DATE_DIGITS_RE.match(s)
    if m:
        d8 = m.group(1)
        return f"{d8[:4]}-{d8[4:6]}-{d8[6:8]}"

    s2 = _DATE_SEP_RE.sub("-", s)
    m = _DATE_HYPHEN_RE.match(s2)
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        return f"{y}-{mo}-{d}"

    return s


from core.google_sheets import (
    get_gspread_client,
    get_drive_service,
    get_worksheet,
)
from googleapiclient.errors import HttpError

from config import (
    CUSTOMER_SHEET_NAME,
    PARENT_DRIVE_FOLDER_ID,
    CUSTOMER_PARENT_FOLDER_ID, 
    SESS_DF_CUSTOMER,
    ENABLE_CUSTOMER_FOLDERS,
    SESS_TENANT_ID,
    DEFAULT_TENANT_ID,
    SESS_IS_ADMIN,
)

def is_customer_folder_enabled() -> bool:
    """
    현재는 '관리자(한우리)'에게만 고객 폴더 기능을 열어둔다.
    - 전역 플래그 ENABLE_CUSTOMER_FOLDERS 가 True 여야 하고
    - 세션에서 관리자 플래그가 True 여야 한다.
    - (옵션) tenant_id 가 기본테넌트일 때만 허용
    """
    if not ENABLE_CUSTOMER_FOLDERS:
        return False

    import streamlit as st
    if not st.session_state.get(SESS_IS_ADMIN, False):
        # 일반 테넌트는 폴더 기능 사용 불가
        return False

    tenant_id = st.session_state.get(SESS_TENANT_ID, DEFAULT_TENANT_ID)
    if tenant_id != DEFAULT_TENANT_ID:
        # ✅ 한우리(기본 테넌트)가 아니면 고객폴더 기능 사용 불가
        return False

    return True


# ─────────────────────────────────
# 공통 헬퍼
# ─────────────────────────────────
def get_current_tenant_id():
    """현재 세션에서 사용하는 테넌트 ID"""
    return st.session_state.get(SESS_TENANT_ID, DEFAULT_TENANT_ID)

def get_customer_sheet_name():
    """
    나중에 테넌트별로 다른 고객 시트를 쓰고 싶으면
    이 함수만 수정하면 된다.
    지금은 모든 테넌트가 CUSTOMER_SHEET_NAME 하나를 공유.
    """
    tenant_id = get_current_tenant_id()
    # 예) return f"{tenant_id}_고객"  # (미래)
    return CUSTOMER_SHEET_NAME

def deduplicate_headers(headers):
    seen = {}
    result = []
    for col in headers:
        if col not in seen:
            seen[col] = 1
            result.append(col)
        else:
            seen[col] += 1
            result.append(f"{col}.{seen[col]-1}")
    return result

def col_index_to_letter(n: int) -> str:
    result = ''
    while n > 0:
        n, rem = divmod(n-1, 26)
        result = chr(65+rem) + result
    return result

def extract_folder_id(val: str) -> str:
    s = str(val or "").strip()
    if not s:
        return ""
    if "drive.google.com" in s:
        return s.rstrip("/").rsplit("/", 1)[-1]
    return s

# ─────────────────────────────────
# 드라이브 폴더 생성/연동
# ─────────────────────────────────
def create_customer_folders(df_customers: pd.DataFrame, worksheet=None):
    if not is_customer_folder_enabled():
        return

    drive_svc = get_drive_service()
    parent_id = CUSTOMER_PARENT_FOLDER_ID

    # 1) 부모 폴더의 하위 폴더 목록(name→id) 한 번만 가져오기
    resp = drive_svc.files().list(
        q=f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder'",
        fields="files(id,name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True
    ).execute()
    existing = {f["name"]: f["id"] for f in resp.get("files", [])}

    # 2) 시트에 기록된 고객ID→행 번호, '폴더' 컬럼 위치 찾기
    cust_row_map = {}
    folder_col = None
    if worksheet is not None:
        rows = worksheet.get_all_values()
        hdr = rows[0]
        id_i = hdr.index("고객ID")
        folder_col = hdr.index("폴더") + 1  # update_cell 1-based
        for r, row in enumerate(rows[1:], start=2):
            cid = row[id_i].strip()
            if cid:
                cust_row_map[cid] = r

    # 3) 재매핑이 필요한 행 판단 함수
    def needs_update(r):
        cid = str(r["고객ID"]).strip()
        if not cid:
            return False
        raw = str(r.get("폴더","")).strip()
        cur = raw.rsplit("/", 1)[-1] if raw else ""
        correct = existing.get(cid)
        return (cur == "") or (correct is not None and cur != correct)

    mask = df_customers.apply(needs_update, axis=1)

    for idx, row in df_customers[mask].iterrows():
        cid = str(row["고객ID"]).strip()
        if not cid:
            continue

        # 4) 이미 존재하면 재사용, 없으면 새로 생성
        if cid in existing:
            fid = existing[cid]
        else:
            fid = drive_svc.files().create(
                body={"name": cid,
                      "mimeType": "application/vnd.google-apps.folder",
                      "parents": [parent_id]},
                fields="id",
                supportsAllDrives=True
            ).execute()["id"]
            existing[cid] = fid

        # 5) DataFrame에 ID 저장
        df_customers.at[idx, "폴더"] = fid

        # 6) 시트도 업데이트
        if worksheet is not None and cid in cust_row_map:
            worksheet.update_cell(cust_row_map[cid], folder_col, fid)

# ─────────────────────────────────
# 데이터 로드
# ─────────────────────────────────
def load_original_customer_df(worksheet):
    data = worksheet.get_all_values()
    header = data[0]
    rows = data[1:]
    return pd.DataFrame(rows, columns=header)


@st.cache_data(ttl=300)
def load_customer_df_from_sheet(cache_tenant_id: str) -> pd.DataFrame:
    """
    현재 세션의 tenant에 맞는 '고객 데이터' 시트를 읽어서 DataFrame으로 반환.

    ⚠ cache_tenant_id는 실제 로직에는 안 쓰고,
       캐시 키를 테넌트별로 분리하는 용도로만 쓴다.
    """
    client = get_gspread_client()
    worksheet = get_worksheet(client, CUSTOMER_SHEET_NAME)

    all_values = worksheet.get_all_values() or []
    if not all_values:
        return pd.DataFrame()

    header = [str(h) for h in all_values[0]]
    data_rows = all_values[1:]

    if not data_rows:
        df = pd.DataFrame(columns=header)
    else:
        df = pd.DataFrame(data_rows, columns=header)

    if not df.empty:
        df = df.astype(str)

    return df


# ─────────────────────────────────
# 저장(배치 업데이트)
# ─────────────────────────────────
def save_customer_batch_update(edited_df: pd.DataFrame, worksheet) -> bool:
    """
    UI에 보이는 컬럼만 비교해서 수정/추가를 처리합니다.
    '고객ID' 컬럼은 변경 감지 대상에서 제외해야 합니다.
    """
    print("🚀 [진입] save_customer_batch_update 시작")

    # ✅ 날짜 컬럼 정규화(수기 입력 허용)
    for c in ["발급", "만기", "발급일", "만기일"]:
        if c in edited_df.columns:
            edited_df[c] = edited_df[c].apply(lambda x: normalize_ymd(x) or str(x or "").strip())

    existing_data = worksheet.get_all_values()
    raw_headers = existing_data[0]
    headers = deduplicate_headers(raw_headers)
    rows = existing_data[1:]
    existing_df = pd.DataFrame(rows, columns=headers)
    existing_df = existing_df.applymap(lambda x: str(x).strip() or " ")

    if "고객ID" not in existing_df.columns:
        st.error("❌ '고객ID' 컬럼이 시트에 없습니다.")
        return False
    existing_df.set_index("고객ID", inplace=True)

    batch_updates = []
    new_rows = []
    modified_count = 0
    added_count = 0

    compare_cols = [c for c in edited_df.columns if c not in ("고객ID", "폴더")]

    for _, row in edited_df.iterrows():
        cust_id = str(row["고객ID"]).strip()
        row_data = [str(row.get(h, "")).strip() or " " for h in headers]

        if "폴더" in headers:
            idx_folder = headers.index("폴더")
            raw = row_data[idx_folder]
            if raw.startswith("http"):
                row_data[idx_folder] = raw.rsplit("/", 1)[-1]

        if cust_id in existing_df.index:
            orig = existing_df.loc[cust_id]

            def norm(x): return str(x).strip()
            changed = any(norm(orig.get(h, "")) != norm(row[h])
                          for h in compare_cols)

            if changed:
                if modified_count >= 10:
                    st.error("❌ 수정 가능한 행은 최대 10개까지입니다.")
                    return False
                modified_count += 1

                base_row = existing_df.index.get_loc(cust_id) + 2
                for col_idx, val in enumerate(row_data):
                    if headers[col_idx] == "폴더":
                        continue
                    cell = f"{col_index_to_letter(col_idx+1)}{base_row}"
                    batch_updates.append({"range": cell, "values": [[val]]})
        else:
            if added_count >= 10:
                st.error("❌ 추가 가능한 행은 최대 10개까지입니다.")
                return False
            added_count += 1
            new_rows.append(row_data)

    if batch_updates:
        worksheet.batch_update(batch_updates)
    if new_rows:
        worksheet.append_rows(new_rows)
        create_customer_folders(edited_df, worksheet)

    st.success(f"🟢 저장 완료: 수정 {modified_count}건, 추가 {added_count}건")
    return True

# ─────────────────────────────────
# OCR 스캔 → 고객정보 업서트
# ─────────────────────────────────
def upsert_customer_from_scan(
    passport_info: dict,
    arc_info: dict,
    extra_info: dict | None = None
):
    """
    OCR 결과를 기반으로 고객 데이터를 추가/수정.

    passport_info: {"성","명","여권","발급","만기"}
    arc_info     : {"한글","등록증","번호","발급일","만기일","주소"}
    extra_info   : {"연","락","처","V"}  (없으면 무시)
    """
    extra_info = extra_info or {}

    client = get_gspread_client()
    sheet_name = get_customer_sheet_name()
    ws = get_worksheet(client, CUSTOMER_SHEET_NAME)

    rows = ws.get_all_values()
    if not rows:
        return False, "고객 시트가 비어 있습니다."

    headers = rows[0]
    df = pd.DataFrame(rows[1:], columns=headers)

    def norm(s): 
        return str(s or "").strip()

    # 🔑 기존 고객 찾기 (여권번호 or 등록증 앞/뒤 7자리)
    key_passport  = norm(passport_info.get("여권"))
    key_reg_front = norm(arc_info.get("등록증"))
    key_reg_back  = norm(arc_info.get("번호"))

    hit_idx = None
    if key_passport:
        m = df.index[
            df.get("여권", "").astype(str).str.strip() == key_passport
        ].tolist()
        if m:
            hit_idx = m[0]

    if hit_idx is None and key_reg_front and key_reg_back:
        m = df.index[
            (df.get("등록증", "").astype(str).str.strip() == key_reg_front) &
            (df.get("번호", "").astype(str).str.strip()   == key_reg_back)
        ].tolist()
        if m:
            hit_idx = m[0]

    # 🔄 업데이트할 값 모으기
    to_update: dict[str, str] = {}

    # 여권 정보
    for k in ["성", "명", "국적", "성별", "여권", "발급", "만기"]:
        v = norm(passport_info.get(k))
        if v:
            if k in ("발급", "만기"):
                v = normalize_ymd(v) or v
            to_update[k] = v

    # 등록증/주소 정보
    for k in ["한글", "등록증", "번호", "발급일", "만기일", "주소"]:
        v = norm(arc_info.get(k))
        if v:
            if k in ("발급일", "만기일"):
                v = normalize_ymd(v) or v
            to_update[k] = v

    # 📞 전화번호 + V (OCR 추가 항목)
    for k in ["연", "락", "처", "V"]:
        v = norm(extra_info.get(k))
        if v:
            to_update[k] = v

    # =========================
    # 1) 기존 고객이면 해당 행만 업데이트
    # =========================
    if hit_idx is not None:
        rownum = hit_idx + 2  # 1행은 헤더, 시트는 1부터 시작
        batch = []

        for col_name, val in to_update.items():
            if col_name in headers:
                col_idx = headers.index(col_name) + 1
                cell = f"{col_index_to_letter(col_idx)}{rownum}"
                batch.append({"range": cell, "values": [[val]]})

        if batch:
            ws.batch_update(batch)

        # 캐시 갱신
        tenant_id = st.session_state.get(SESS_TENANT_ID, DEFAULT_TENANT_ID)

        load_customer_df_from_sheet.clear()
        st.session_state[SESS_DF_CUSTOMER] = load_customer_df_from_sheet(tenant_id)

        return True, f"기존 고객({df.at[hit_idx, '고객ID']}) 정보가 업데이트되었습니다."

    # =========================
    # 2) 신규 고객이면 새 ID 발급 후 추가
    # =========================
    today_str = datetime.date.today().strftime('%Y%m%d')
    col_id = df.get("고객ID", pd.Series(dtype=str)).astype(str)
    next_seq = str(col_id[col_id.str.startswith(today_str)].shape[0] + 1).zfill(2)
    new_id = today_str + next_seq

    # 모든 컬럼 기본값 공백으로 초기화
    base = {h: " " for h in headers}
    base.update({"고객ID": new_id})

    # 새 값 덮어쓰기
    for k, v in to_update.items():
        if k in base:
            base[k] = v

    # 시트에 행 추가
    ws.append_row([base.get(h, "") for h in headers])

    # 👉 고객별 폴더 자동생성 끄고 싶으면 아래 한 줄을 주석 처리하면 됨
    create_customer_folders(pd.DataFrame([base]), ws)

    # 캐시 갱신
    tenant_id = st.session_state.get(SESS_TENANT_ID, DEFAULT_TENANT_ID)

    load_customer_df_from_sheet.clear()
    st.session_state[SESS_DF_CUSTOMER] = load_customer_df_from_sheet(tenant_id)

    return True, f"신규 고객이 추가되었습니다 (고객ID: {new_id})."
