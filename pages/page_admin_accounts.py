import streamlit as st
import pandas as pd
import hashlib, os, base64, hmac

from config import (
    ACCOUNTS_SHEET_NAME,
    SESS_IS_ADMIN,
)
from core.google_sheets import (
    read_data_from_sheet,
    write_data_to_sheet,
    create_office_files_for_tenant,  # 🔹 새로 추가한 헬퍼 사용
)

# 기본 컬럼 정의 (없으면 자동으로 만들어서 맞춰줌)
ACCOUNT_BASE_COLUMNS = [
    "login_id",
    "password_hash",
    "tenant_id",
    "office_name",
    "office_adr",       # ✅ 사무실 주소
    "contact_name",
    "contact_tel",
    "biz_reg_no",
    "agent_rrn",
    "is_admin",
    "is_active",
    "folder_id",
    "work_sheet_key",
    "customer_sheet_key",
    "created_at",
    "sheet_key",        # 테넌트 전체 스프레드시트 키(필요시)
]

# ---- 비밀번호 해시 유틸 ----
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + dk).decode("ascii")

def verify_password(password: str, hashed: str) -> bool:
    try:
        raw = base64.b64decode(hashed.encode("ascii"))
        salt, dk = raw[:16], raw[16:]
        new_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(dk, new_dk)
    except Exception:
        return False

# ---- Accounts 시트 로드/저장 ----
@st.cache_data(ttl=600)
def load_accounts_df() -> pd.DataFrame:
    records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []

    if not records:
        # 아무 계정도 없으면 빈 df 리턴
        return pd.DataFrame(columns=ACCOUNT_BASE_COLUMNS)

    df = pd.DataFrame(records)

    # 기본 컬럼이 없으면 빈 값으로 채워 넣기
    for col in ACCOUNT_BASE_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # base 컬럼 + 그 밖의 기타 컬럼 순서로 정렬
    extra_cols = [c for c in df.columns if c not in ACCOUNT_BASE_COLUMNS]
    df = df[ACCOUNT_BASE_COLUMNS + extra_cols]

    return df

def save_accounts_df(df: pd.DataFrame) -> bool:
    # base 컬럼 + 기타 컬럼 순서로 헤더 구성
    extra_cols = [c for c in df.columns if c not in ACCOUNT_BASE_COLUMNS]
    header = ACCOUNT_BASE_COLUMNS + extra_cols

    data = df[header].to_dict(orient="records")
    ok = write_data_to_sheet(ACCOUNTS_SHEET_NAME, data, header_list=header)
    if ok:
        load_accounts_df.clear()
    return ok

# ---- 메인 렌더 ----
def render():
    # --- 접근 권한 체크 ---
    if not st.session_state.get(SESS_IS_ADMIN, False):
        st.error("이 페이지에 접근할 권한이 없습니다. (관리자 전용)")
        st.stop()

    st.subheader("🧩 사무소 계정 관리")

    tab_list = st.tabs(["계정 목록", "계정 승인/수정", "새 계정 생성"])

    # ========== 탭 1: 계정 목록 ==========
    with tab_list[0]:
        df = load_accounts_df()

        if df.empty:
            st.info("등록된 계정이 없습니다.")
        else:
            st.write("현재 등록된 계정 목록:")
            # 보기 좋게 일부 컬럼만 우선 표시
            view_cols = [
                "login_id",
                "tenant_id",
                "office_name",
                "contact_name",
                "contact_tel",
                "is_admin",
                "is_active",
                "folder_id",
                "customer_sheet_key",
                "work_sheet_key",
                "created_at",
            ]
            view_cols = [c for c in view_cols if c in df.columns]
            st.dataframe(df[view_cols], use_container_width=True)

    # ========== 탭 2: 계정 승인/수정 ==========
    with tab_list[1]:
        df = load_accounts_df()
        if df.empty:
            st.info("등록된 계정이 없습니다.")
        else:
            login_ids = df["login_id"].tolist()
            selected_id = st.selectbox("수정/승인할 계정을 선택하세요", login_ids)

            row = df[df["login_id"] == selected_id].iloc[0]
            idx = df.index[df["login_id"] == selected_id][0]

            st.markdown("#### 기본 정보")

            new_office_name = st.text_input(
                "대행기관명 (사무실명)",
                value=str(row.get("office_name", "")),
            )
            new_office_adr = st.text_input(
                "사무실 주소",
                value=str(row.get("office_adr", "")),
            )

            new_tenant_id = st.text_input(
                "테넌트 ID (빈칸이면 login_id와 동일)",
                value=str(row.get("tenant_id", "")),
            )

            new_biz_reg_no = st.text_input(
                "사업자등록번호",
                value=str(row.get("biz_reg_no", "")),
                placeholder="000-00-00000",
            )
            new_agent_rrn = st.text_input(
                "행정사 주민등록번호",
                value=str(row.get("agent_rrn", "")),
                placeholder="000000-0000000",
            )

            new_contact_name = st.text_input(
                "행정사 성명",
                value=str(row.get("contact_name", "")),
            )
            new_contact_tel = st.text_input(
                "연락처 (전화번호)",
                value=str(row.get("contact_tel", "")),
            )

            new_is_admin = st.checkbox(
                "관리자 계정 여부",
                value=str(row.get("is_admin", "")).strip().lower() in ("true", "1", "y"),
            )
            new_is_active = st.checkbox(
                "활성 상태 (로그인 허용)",
                value=str(row.get("is_active", "")).strip().lower() in ("true", "1", "y"),
            )

            st.markdown("#### 폴더 / 시트 상태")
            folder_id = str(row.get("folder_id", "")).strip()
            customer_sheet_key = str(row.get("customer_sheet_key", "")).strip()
            work_sheet_key = str(row.get("work_sheet_key", "")).strip()

            col_f1, col_f2 = st.columns(2)
            with col_f1:
                st.write(f"- 폴더 ID: `{folder_id or '(미생성)'}`")
                st.write(f"- 고객데이터 시트: `{customer_sheet_key or '(미생성)'}`")
                st.write(f"- 업무정리 시트: `{work_sheet_key or '(미생성)'}`")
            with col_f2:
                if st.button("📂 폴더+시트 자동 생성/재생성", use_container_width=True):
                    """
                    버튼 클릭 시 새 폴더와 시트를 생성/재생성한다.
                    create_office_files_for_tenant()에서 오류가 발생해도
                    부분적으로 생성된 결과를 이용해 df를 업데이트하고,
                    발생한 오류는 사용자에게 경고로 표시한다.
                    """
                    try:
                        res = create_office_files_for_tenant(
                            tenant_id=new_tenant_id or selected_id,
                            office_name=new_office_name or selected_id,
                        )
                        # 부분 성공 값도 데이터프레임에 기록
                        df.at[idx, "folder_id"] = res.get("folder_id", "")
                        df.at[idx, "customer_sheet_key"] = res.get("customer_sheet_key", "")
                        df.at[idx, "work_sheet_key"] = res.get("work_sheet_key", "")
                        # 오류 메시지가 있으면 사용자에게 표시
                        err_msg = res.get("errors")
                        if err_msg:
                            st.warning(f"일부 파일 생성에 실패했습니다: {err_msg}")
                        if save_accounts_df(df):
                            st.success("폴더 및 시트 정보가 저장되었습니다.")
                    except Exception as e:
                        st.error(f"폴더/시트 자동 생성 중 오류: {e}")

            st.markdown("#### 비밀번호 변경 (옵션)")
            new_pw = st.text_input(
                "새 비밀번호 (비워두면 변경 없음)",
                type="password",
            )

            if st.button("💾 변경 사항 저장", type="primary"):
                df.at[idx, "office_name"] = new_office_name or selected_id
                df.at[idx, "office_adr"]   = new_office_adr
                df.at[idx, "tenant_id"] = new_tenant_id or selected_id
                df.at[idx, "contact_name"] = new_contact_name
                df.at[idx, "contact_tel"] = new_contact_tel
                df.at[idx, "biz_reg_no"] = new_biz_reg_no
                df.at[idx, "agent_rrn"] = new_agent_rrn
                df.at[idx, "is_admin"] = "TRUE" if new_is_admin else "FALSE"
                df.at[idx, "is_active"] = "TRUE" if new_is_active else "FALSE"

                if new_pw:
                    df.at[idx, "password_hash"] = hash_password(new_pw)

                if save_accounts_df(df):
                    st.success("계정 정보가 저장되었습니다.")
                else:
                    st.error("계정 저장 중 오류가 발생했습니다.")

            # 선택적으로 계정 삭제 기능도 추가 (필요 없으면 주석 처리)
            st.markdown("---")

            # 1단계: 삭제 요청 (타겟만 기억)
            if st.button("🗑️ 이 계정 삭제", help="※ 되돌릴 수 없습니다.", type="secondary"):
                st.session_state["admin_account_delete_target"] = selected_id

            # 2단계: 실제 확인창
            target = st.session_state.get("admin_account_delete_target")
            if target == selected_id:
                st.warning(f"정말로 계정 '{selected_id}' 을(를) 삭제하시겠습니까? 되돌릴 수 없습니다.")
                col_yes, col_no = st.columns(2)

                with col_yes:
                    if st.button("✅ 예, 삭제합니다", key="btn_admin_delete_yes"):
                        df = df[df["login_id"] != selected_id].reset_index(drop=True)
                        if save_accounts_df(df):
                            st.success(f"계정 '{selected_id}' 이(가) 삭제되었습니다.")
                            st.session_state["admin_account_delete_target"] = None
                            st.rerun()

                with col_no:
                    if st.button("❌ 아니오, 취소합니다", key="btn_admin_delete_no"):
                        st.info("삭제가 취소되었습니다.")
                        st.session_state["admin_account_delete_target"] = None
                        st.rerun()

    # ========== 탭 3: 새 계정 생성 (관리자용) ==========
    with tab_list[2]:
        st.markdown("### ➕ 새 사무소 계정 생성 (관리자)")

        with st.form("create_account_form"):
            login_id = st.text_input("로그인 ID", placeholder="예: seoul_office")
            raw_pw = st.text_input("초기 비밀번호", type="password")

            office_name = st.text_input("대행기관명 (사무실명)", placeholder="예: 서울 출입국 행정사")
            biz_reg_no = st.text_input("사업자등록번호", placeholder="000-00-00000")
            agent_rrn = st.text_input("행정사 주민등록번호", placeholder="000000-0000000")

            contact_name = st.text_input("행정사 성명", placeholder="선택 입력")
            contact_tel = st.text_input("연락처 (전화번호)", placeholder="선택 입력")

            tenant_id = st.text_input(
                "테넌트 ID (빈칸이면 login_id와 동일)",
                value="",
                placeholder="예: seoul01",
            )

            is_admin = st.checkbox("관리자 계정으로 설정", value=False)
            is_active = st.checkbox("계정 생성 후 즉시 로그인 허용", value=True)
            auto_files = st.checkbox(
                "이 계정용 폴더 및 시트를 템플릿에서 자동 생성",
                value=True,
            )

            submitted = st.form_submit_button("계정 생성")

        if submitted:
            if not login_id or not raw_pw:
                st.error("로그인 ID와 비밀번호는 필수입니다.")
            else:
                df = load_accounts_df()
                if not df.empty and (df["login_id"] == login_id).any():
                    st.error("이미 존재하는 로그인 ID입니다.")
                else:
                    tid = tenant_id or login_id
                    pw_hash = hash_password(raw_pw)

                    folder_id = ""
                    customer_sheet_key = ""
                    work_sheet_key = ""

                    if auto_files:
                        try:
                            res = create_office_files_for_tenant(
                                tenant_id=tid,
                                office_name=office_name or tid,
                            )
                            folder_id = res.get("folder_id", "")
                            customer_sheet_key = res.get("customer_sheet_key", "")
                            work_sheet_key = res.get("work_sheet_key", "")
                            err_msg = res.get("errors")
                            if err_msg:
                                st.warning(f"새 계정용 폴더/시트 생성 중 일부 실패: {err_msg}")
                        except Exception as e:
                            st.error(f"폴더/시트 자동 생성 중 오류: {e}")
                            # 자동생성 실패해도 계정 자체는 만들 수 있게 두고, 나중에 수정 탭에서 다시 시 가능

                    new_row = {
                        "login_id": login_id,
                        "password_hash": pw_hash,
                        "tenant_id": tid,
                        "office_name": office_name or tid,
                        "contact_name": contact_name,
                        "contact_tel": contact_tel,
                        "biz_reg_no": biz_reg_no,
                        "agent_rrn": agent_rrn,
                        "is_admin": "TRUE" if is_admin else "FALSE",
                        "is_active": "TRUE" if is_active else "FALSE",
                        "folder_id": folder_id,
                        "work_sheet_key": work_sheet_key,
                        "customer_sheet_key": customer_sheet_key,
                        "created_at": pd.Timestamp.today().strftime("%Y-%m-%d"),
                    }


                    # 기존 df에 컬럼이 있다면 맞춰주기
                    for col in df.columns:
                        if col not in new_row:
                            new_row[col] = ""

                    # 혹시 신규 컬럼이 df에 없으면 추가
                    for col in new_row.keys():
                        if col not in df.columns:
                            df[col] = ""

                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

                    if save_accounts_df(df):
                        st.success(f"새 계정 '{login_id}' 이(가) 생성되었습니다.")
                    else:
                        st.error("계정 저장 중 오류가 발생했습니다.")
