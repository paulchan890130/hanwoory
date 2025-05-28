# app.py 최상단 – 기존 oauth2client 관련 임포트 전부 삭제
import os
import platform
import streamlit as st
import gspread
from pathlib import Path
import requests
import pandas as pd
import datetime
import json
import uuid # Ensure uuid is imported
import calendar
import streamlit.components.v1 as components
import matplotlib.pyplot as plt

# platform was already imported

def safe_int(val):
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return 0

try:
    import streamlit as st
except ModuleNotFoundError:
    print("Streamlit is not installed. Please run 'pip install streamlit' in your terminal.")
    st = None # Fallback if streamlit is not available

# -----------------------------
# ✅ Google Sheets Configuration & Helper Functions
# -----------------------------

SHEET_KEY = "14pEPo-Q3aFgbS1Gqcamb2lkadq-eFlOrQ-wST3EU1pk" # Provided Google Sheet Key

# Service account key file path
if platform.system() == "Windows":
    KEY_PATH = r"C:\Users\윤찬\내 드라이브\한우리 현행업무\프로그램\출입국업무관리\hanwoory-9eaa1a4c54d7.json"
else:
    KEY_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "/etc/secrets/hanwoory-9eaa1a4c54d7.json")

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Sheet Names
CUSTOMER_SHEET_NAME = "고객 데이터"
EVENTS_SHEET_NAME = "일정"
DAILY_SUMMARY_SHEET_NAME = "일일결산"
DAILY_BALANCE_SHEET_NAME = "잔액"
MEMO_LONG_SHEET_NAME = "장기메모"
MEMO_MID_SHEET_NAME = "중기메모"
MEMO_SHORT_SHEET_NAME = "단기메모"
PLANNED_TASKS_SHEET_NAME = "예정업무"
ACTIVE_TASKS_SHEET_NAME = "진행업무"
COMPLETED_TASKS_SHEET_NAME = "완료업무"

from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession

@st.cache_resource(ttl=600)
def get_gspread_client():
    # Ensure the key file exists
    if not os.path.exists(KEY_PATH):
        st.error(f"Google Cloud 서비스 계정 키 파일을 찾을 수 없습니다: {KEY_PATH}")
        st.stop()
    try:
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=SCOPE)
        client = gspread.Client(auth=creds)
        client.session = AuthorizedSession(creds)
        return client
    except Exception as e:
        st.error(f"Google Sheets 클라이언트 초기화 중 오류 발생: {e}")
        st.stop()


def get_worksheet(_client, sheet_name):
    if _client is None:
        return None
    try:
        return _client.open_by_key(SHEET_KEY).worksheet(sheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"스프레드시트를 찾을 수 없습니다. SHEET_KEY를 확인하세요: {SHEET_KEY}")
        return None
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"시트 '{sheet_name}'을 찾을 수 없습니다. 시트 이름을 확인하세요.")
        return None
    except Exception as e:
        st.error(f"시트 '{sheet_name}'을 여는 중 오류 발생: {e}")
        return None


def read_data_from_sheet(sheet_name: str, default_if_empty=None):
    if default_if_empty is None:
        default_if_empty = []
    client = get_gspread_client()
    if client is None:
        return default_if_empty

    worksheet = get_worksheet(client, sheet_name)
    if worksheet:
        try:
            return worksheet.get_all_records(empty2zero=False, head=1, default_blank="") # Match old behavior more closely
        except Exception as e:
            st.warning(f"시트 '{sheet_name}' 읽기 중 오류 (get_all_records): {e}. 빈 데이터로 간주합니다.")
            return default_if_empty
    return default_if_empty

def write_data_to_sheet(sheet_name: str, data_list_of_dicts, header_list: list):
    client = get_gspread_client()
    if client is None:
        return False

    worksheet = get_worksheet(client, sheet_name)
    if worksheet:
        try:
            worksheet.clear()
            if data_list_of_dicts: # Check if there's data to write
                # Convert all data to string to avoid gspread type issues, especially with numbers/None
                rows_to_write = [[str(row.get(col_header, "")) for col_header in header_list] for row in data_list_of_dicts]
                worksheet.update([header_list] + rows_to_write, value_input_option="USER_ENTERED")
            else: # If data_list_of_dicts is empty, just write the header
                if header_list:
                    worksheet.update([header_list], value_input_option="USER_ENTERED")
            st.cache_data.clear()
            return True
        except Exception as e:
            st.error(f"❌ 시트 쓰기 오류 [{sheet_name}]: {e}")
            return False
    return False

def read_memo_from_sheet(sheet_name):
    client = get_gspread_client()
    if client is None: return ""

    worksheet = get_worksheet(client, sheet_name)
    if worksheet:
        try:
            val = worksheet.acell('A1').value
            return val if val is not None else ""
        except Exception as e:
            st.error(f"'{sheet_name}' 시트 (메모) 읽기 중 오류 발생: {e}")
            return ""
    return ""

def save_memo_to_sheet(sheet_name, content):
    client = get_gspread_client()
    if client is None: return False
    
    worksheet = get_worksheet(client, sheet_name)
    if worksheet:
        try:
            worksheet.update_acell('A1', content)
            st.cache_data.clear() 
            return True
        except Exception as e:
            st.error(f"'{sheet_name}' 시트 (메모) 저장 중 오류 발생: {e}")
            return False
    return False

# -----------------------------
# ✅ Application Specific Data Load/Save Functions
# -----------------------------

# --- Customer Data Functions ---
# Adapted from the old get_google_sheet_df and new load_customer_df
def load_customer_df():
    client = get_gspread_client()
    if client is None: return pd.DataFrame(columns=['날짜', '한글', '성', '명', '연', '락', '처', '등록증', '만기일', '만기', '여권', '기타']) # Default columns

    worksheet = get_worksheet(client, CUSTOMER_SHEET_NAME)
    if worksheet:
        try:
            data = worksheet.get_all_records(empty2zero=False, head=1, default_blank="")
            df = pd.DataFrame(data)
            if df.empty and worksheet.row_count > 0 : # If get_all_records returns empty but sheet has headers
                headers = worksheet.row_values(1)
                if headers:
                    df = pd.DataFrame(columns=headers)
                else: # No headers, provide default structure
                     df = pd.DataFrame(columns=['날짜', '한글', '성', '명', '연', '락', '처', '등록증', '만기일', '만기', '여권', '기타'])


            # Original formatting logic from the old get_google_sheet_df
            cols_to_format = {
                '연': 3,  # Phone part 1
                '락': 4,  # Phone part 2
                '처': 4,  # Phone part 3
            }
            for col_name, zfill_len in cols_to_format.items():
                if col_name in df.columns:
                    df[col_name] = df[col_name].astype(str).apply(
                        lambda x: x.split('.')[0].zfill(zfill_len) if pd.notna(x) and x.strip() != "" and x.strip().lower() != 'nan' else ""
                    )
            # 등록증 번호 앞자리 0 보존 처리
            if '등록증' in df.columns:
                df['등록증'] = df['등록증'].astype(str).apply(
                    lambda x: x.split('.')[0].zfill(6) if pd.notna(x) and x.strip() and x.strip().lower() != 'nan' else ""
                )
            return df
        except Exception as e:
            st.error(f"'{CUSTOMER_SHEET_NAME}' 시트에서 고객 데이터 로드 중 오류 발생: {e}")
            return pd.DataFrame(columns=['날짜', '한글', '성', '명', '연', '락', '처', '등록증', '만기일', '만기', '여권', '기타'])
    return pd.DataFrame(columns=['날짜', '한글', '성', '명', '연', '락', '처', '등록증', '만기일', '만기', '여권', '기타'])


def save_customer_df(df):
    client = get_gspread_client()
    if client is None: return False
    
    worksheet = get_worksheet(client, CUSTOMER_SHEET_NAME)
    if worksheet:
        try:
            worksheet.clear()
            df_to_save = df.fillna("").astype(str)
            update_data = [df_to_save.columns.values.tolist()] + df_to_save.values.tolist()
            worksheet.update(update_data, value_input_option='USER_ENTERED') 
            st.cache_data.clear()
            if 'df_customer' in st.session_state: 
                del st.session_state['df_customer']
            if 'df' in st.session_state: 
                del st.session_state['df']
            return True
        except Exception as e:
            st.error(f"'{CUSTOMER_SHEET_NAME}' 시트에 고객 데이터 저장 중 오류 발생: {e}")
            return False
    return False

# --- Event (Calendar) Data Functions ---
@st.cache_data(ttl=300) 
def load_events(): 
    records = read_data_from_sheet(EVENTS_SHEET_NAME, default_if_empty=[])
    events = {}
    if not records:
        return {}
    for record in records:
        date_str = record.get('date_str')
        event_text = record.get('event_text', '') 
        if date_str: 
            if date_str not in events:
                events[date_str] = []
            events[date_str].append(str(event_text)) 
    return events

def save_events(events_dict): 
    data_to_save = []
    for date_str, event_texts_list in events_dict.items():
        for text in event_texts_list:
            data_to_save.append({'date_str': str(date_str), 'event_text': str(text)})
    header = ['date_str', 'event_text']
    if write_data_to_sheet(EVENTS_SHEET_NAME, data_to_save, header_list=header):
        load_events.clear() 
        return True
    return False


# --- Daily Summary & Balance Functions ---
@st.cache_data(ttl=300) 
def load_daily(): 
    records = read_data_from_sheet(DAILY_SUMMARY_SHEET_NAME, default_if_empty=[])
    processed_records = []
    for r in records:
        entry = {
            'id'          : r.get('id', str(uuid.uuid4())),
            'date'        : r.get('date', ''),
            'time'        : r.get('time', ''),
            'name'        : r.get('name', ''),
            'task'        : r.get('task', ''),
            'income_cash': safe_int(r.get('income_cash')),
            'income_etc' : safe_int(r.get('income_etc')),
            'exp_cash'   : safe_int(r.get('exp_cash')),
            'exp_etc'    : safe_int(r.get('exp_etc')),
            'cash_out'   : safe_int(r.get('cash_out')), 
            'memo'        : r.get('memo', '')
        }
        processed_records.append(entry)
    return processed_records

def save_daily(data_list_of_dicts): 
    header = ["id", "date", "time", "name", "task", "income_cash", "income_etc", "exp_cash", "cash_out", "exp_etc", "memo"]
    if write_data_to_sheet(DAILY_SUMMARY_SHEET_NAME, data_list_of_dicts, header_list=header):
        load_daily.clear() 
        load_balance.clear() 
        return True
    return False

@st.cache_data(ttl=300) 
def load_balance(): 
    records = read_data_from_sheet(DAILY_BALANCE_SHEET_NAME, default_if_empty=[])
    balance = {"cash": 0, "profit": 0} 
    if not records:
        return balance
    for record in records:
        key = record.get('key')
        value_str = str(record.get('value', '0')) 
        if key in balance:
            try:
                balance[key] = int(value_str) if value_str and value_str.strip() else 0
            except ValueError:
                st.warning(f"누적요약 데이터 '{key}'의 값 '{value_str}'을 숫자로 변환할 수 없습니다. 기본값 0으로 설정됩니다.")
                balance[key] = 0  
    return balance

def save_balance(balance_dict): 
    data_to_save = []
    for key, value in balance_dict.items():
        data_to_save.append({'key': str(key), 'value': str(value)}) 
    header = ['key', 'value']
    if write_data_to_sheet(DAILY_BALANCE_SHEET_NAME, data_to_save, header_list=header):
        load_balance.clear() 
        return True
    return False

# --- Memo Functions ---
@st.cache_data(ttl=600)
def load_long_memo(): return read_memo_from_sheet(MEMO_LONG_SHEET_NAME)
def save_long_memo(content): 
    if save_memo_to_sheet(MEMO_LONG_SHEET_NAME, content):
        load_long_memo.clear()

@st.cache_data(ttl=600)
def load_mid_memo(): return read_memo_from_sheet(MEMO_MID_SHEET_NAME)
def save_mid_memo(content): 
    if save_memo_to_sheet(MEMO_MID_SHEET_NAME, content):
        load_mid_memo.clear()

@st.cache_data(ttl=600)
def load_short_memo(): return read_memo_from_sheet(MEMO_SHORT_SHEET_NAME)
def save_short_memo(content): 
    if save_memo_to_sheet(MEMO_SHORT_SHEET_NAME, content):
        load_short_memo.clear()


# --- Planned Task Functions ---
@st.cache_data(ttl=300)
def load_planned_tasks(): 
    records = read_data_from_sheet(PLANNED_TASKS_SHEET_NAME, default_if_empty=[])
    return [{
        'id': r.get('id', str(uuid.uuid4())), 
        'date': str(r.get('date','')),
        'period': str(r.get('period','')),
        'content': str(r.get('content','')),
        'note': str(r.get('note',''))
    } for r in records]

def save_planned_tasks(data_list_of_dicts): 
    header = ["id", "date", "period", "content", "note"]
    if write_data_to_sheet(PLANNED_TASKS_SHEET_NAME, data_list_of_dicts, header_list=header):
        load_planned_tasks.clear()
        return True
    return False

# --- Active Task Functions ---
@st.cache_data(ttl=300)
def load_active_tasks(): 
    records = read_data_from_sheet(ACTIVE_TASKS_SHEET_NAME, default_if_empty=[])
    return [{
        'id': r.get('id', str(uuid.uuid4())), 
        'category': str(r.get('category','')),
        'date': str(r.get('date','')),
        'name': str(r.get('name','')),
        'work': str(r.get('work','')),
        'details': str(r.get('details',''))
    } for r in records]

def save_active_tasks(data_list_of_dicts): 
    header = ["id", "category", "date", "name", "work", "details"]
    if write_data_to_sheet(ACTIVE_TASKS_SHEET_NAME, data_list_of_dicts, header_list=header):
        load_active_tasks.clear()
        return True
    return False

# --- Completed Task Functions ---

def load_completed_tasks():
    return read_data_from_sheet(COMPLETED_TASKS_SHEET_NAME, default_if_empty=[])

def save_completed_tasks(records):
    header = ["id", "category", "date", "name", "work", "details", "complete_date"]
    return write_data_to_sheet(COMPLETED_TASKS_SHEET_NAME, records, header_list=header)

# -----------------------------
# ✅ Streamlit App Logic
# -----------------------------

def search_via_server(question):
    try:
        res = requests.post(
            "https://hanwoory.onrender.com/search", 
            json={"question": question},
            timeout=30
        )
        if res.status_code == 200:
            return res.json().get("answer", "답변을 받을 수 없습니다.")
        else:
            error_detail = res.text
            try: 
                error_json = res.json()
                error_detail = error_json.get("detail", res.text)
            except ValueError:
                pass
            return f"서버 오류: {res.status_code} - {error_detail}"
    except requests.exceptions.Timeout:
        return "요청 시간 초과: 서버가 응답하지 않습니다."
    except requests.exceptions.RequestException as e: 
        return f"요청 실패 (네트워크 또는 서버 문제): {str(e)}"
    except Exception as e:
        return f"요청 중 알 수 없는 오류: {str(e)}"


if st: 
    st.set_page_config(page_title="출입국 업무관리", layout="wide")

    if "current_page" not in st.session_state:
        st.session_state["current_page"] = "home"

    st.markdown("""
    <style>
      [data-testid="stVerticalBlock"] > div { margin-bottom: 0px !important; }
      [data-testid="stColumns"] { margin-bottom: 0px !important; }
    </style>
    """, unsafe_allow_html=True)

    title_col, toolbar_col = st.columns([2, 3]) 
    with title_col:
        st.title("📋 출입국 업무관리")
        
    with toolbar_col:
        toolbar_options = {
            "🏠 홈으로": "home",
            "🗒️ 메모장": "memo",
            "📚 업무": "reference",
            "👥 고객관리": "customer",
            "📊 결산": "daily",
            "🧭 메뉴얼 검색": "manual"
        }
        num_buttons = len(toolbar_options)
        btn_cols = st.columns(num_buttons)  
        for idx, (label, page_key) in enumerate(toolbar_options.items()):
            if btn_cols[idx].button(label, key=f"nav-{page_key}-{idx}", use_container_width=True):
                st.session_state["current_page"] = page_key
                st.rerun()
                
    st.markdown("---") 

    current_page = st.session_state["current_page"]

    if current_page == "customer":
        st.subheader("👥 고객관리")
        if 'df' not in st.session_state: 
            st.session_state['df'] = load_customer_df()

        df_customer = st.session_state['df'] 

        col_add, col_search, col_select, col_delete, col_save, col_undo = st.columns([1, 1.5, 1, 1, 1, 1])

        with col_add: 
            if st.button("➕ 행 추가", use_container_width=True):
                today_str = datetime.date.today().strftime('%Y-%m-%d')
                if df_customer.empty:
                    temp_client = get_gspread_client()
                    temp_ws = get_worksheet(temp_client, CUSTOMER_SHEET_NAME)
                    headers = []
                    if temp_ws and temp_ws.row_count > 0:
                        headers = temp_ws.row_values(1)
                    if not headers: 
                        headers = ['날짜', '한글', '성', '명', '연', '락', '처', '등록증', '만기일', '만기', '여권', '기타']
                    new_row_data = {col: "" for col in headers}
                    if headers: new_row_data[headers[0]] = today_str
                    new_row = pd.Series(new_row_data)

                else: 
                    new_row_data = {col: "" for col in df_customer.columns}
                    if df_customer.columns.any(): new_row_data[df_customer.columns[0]] = today_str 
                    new_row = pd.Series(new_row_data)

                if not new_row.empty:
                    df_customer = pd.concat([pd.DataFrame([new_row], columns=new_row.index), df_customer], ignore_index=True)
                    st.session_state['df'] = df_customer.copy()
                    st.info("새 행이 추가되었습니다. 저장하려면 💾 버튼을 누르세요.")
                else:
                    st.error("새 행을 추가할 수 없습니다. 고객 데이터의 열 구조를 확인해주세요.")

        with col_search: 
            search_term = st.text_input("🔍 검색", value=st.session_state.get("customer_search_term", ""), key="customer_search_term")

        df_display_full = df_customer.copy()
        df_for_search = df_display_full.fillna("").astype(str) 

        if search_term:
            mask = df_for_search.apply(lambda row: search_term.lower() in row.str.lower().to_string(), axis=1)
            df_display_filtered = df_display_full[mask]
            st.session_state['customer_search_mask_indices'] = df_display_full[mask].index 
        else:
            df_display_filtered = df_display_full
            st.session_state['customer_search_mask_indices'] = df_display_full.index 

        df_display_for_editor = df_display_filtered.copy()
        df_display_for_editor = df_display_for_editor.fillna("").astype(str).reset_index(drop=True)


        with col_select: 
            max_val_delete = len(df_display_for_editor) - 1 if not df_display_for_editor.empty else 0
            selected_idx_display = st.number_input(
                "삭제할 행 번호",  
                min_value=0,  
                max_value=max_val_delete,  
                step=1,  
                key="selected_row", 
                disabled=df_display_for_editor.empty,
                help="삭제할 행 번호 (현재 표시된 테이블 기준)"
            )

        with col_delete: 
            if st.button("🗑️ 삭제 요청", use_container_width=True, disabled=df_display_for_editor.empty):
                if not df_display_for_editor.empty and 0 <= selected_idx_display <= max_val_delete:
                    st.session_state['pending_delete_idx_display'] = selected_idx_display
                    st.session_state['awaiting_delete_confirm'] = True
                    st.rerun()
                else:
                    st.warning("삭제할 행을 선택해주세요 또는 유효한 행이 없습니다.")
        
        with col_undo: 
            if st.button("↩️ 삭제 취소 (Undo)", use_container_width=True):
                if 'customer_deleted_rows_stack' in st.session_state and st.session_state['customer_deleted_rows_stack']:
                    original_idx, row_data_series = st.session_state['customer_deleted_rows_stack'].pop()
                    current_df = st.session_state['df'] 
                    
                    part1 = current_df.iloc[:original_idx]
                    part2 = current_df.iloc[original_idx:]
                    restored_df = pd.concat([part1, pd.DataFrame([row_data_series], columns=row_data_series.index), part2]).reset_index(drop=True)
                    
                    st.session_state['df'] = restored_df
                    st.success(f"{original_idx}번 행 (원본 기준)이 복구되었습니다. 저장하려면 💾 버튼을 누르세요.")
                    st.rerun()
                else:
                    st.warning("복구할 행이 없습니다.")

        if st.session_state.get('awaiting_delete_confirm', False):
            st.warning("🔔 정말 삭제하시겠습니까?")
            confirm_cols = st.columns(2)
            with confirm_cols[0]:
                if st.button("✅ 예, 삭제합니다", key="confirm_delete_customer"):
                    idx_to_delete_in_display = st.session_state.get('pending_delete_idx_display', -1)
                    
                    if idx_to_delete_in_display != -1 and 'customer_search_mask_indices' in st.session_state:
                        original_indices_of_filtered_df = st.session_state['customer_search_mask_indices']
                        if 0 <= idx_to_delete_in_display < len(original_indices_of_filtered_df):
                            actual_df_index_to_delete = original_indices_of_filtered_df[idx_to_delete_in_display]
                            
                            full_df_to_modify = st.session_state['df'] 
                            if actual_df_index_to_delete in full_df_to_modify.index:
                                deleted_row_data = full_df_to_modify.loc[actual_df_index_to_delete].copy()
                                st.session_state.setdefault('customer_deleted_rows_stack', []).append((actual_df_index_to_delete, deleted_row_data))
                                full_df_to_modify = full_df_to_modify.drop(index=actual_df_index_to_delete).reset_index(drop=True)
                                st.session_state['df'] = full_df_to_modify
                                st.success(f"행 (원본 인덱스 {actual_df_index_to_delete})이 삭제되었습니다. 저장하려면 💾 버튼을 누르세요.")
                            else:
                                st.warning("삭제할 행의 원본 인덱스를 찾을 수 없습니다.")
                        else:
                            st.warning("잘못된 삭제 인덱스입니다 (필터링 된 목록 기준).")
                    else:
                        st.warning("삭제할 행을 찾을 수 없습니다.")
                        
                    st.session_state['awaiting_delete_confirm'] = False
                    st.session_state.pop('pending_delete_idx_display', None)
                    st.rerun()
            with confirm_cols[1]:
                if st.button("❌ 아니오, 취소합니다", key="cancel_delete_customer"):
                    st.session_state['awaiting_delete_confirm'] = False
                    st.session_state.pop('pending_delete_idx_display', None)
                    st.info("삭제가 취소되었습니다.")
                    st.rerun()

        edited_df_display = st.data_editor(
            df_display_for_editor.fillna(""), 
            height=600,  
            use_container_width=True,  
            num_rows="dynamic", 
            key="edit_table", 
            hide_index=False 
        )

        with col_save:
            if st.button("💾 저장", use_container_width=True):
                components.html("""
                    <script>
                        document.activeElement.blur();
                    </script>
                """, height=0)
                full_df_to_save = st.session_state['df'].copy()
                edited_df_corrected = edited_df_display.copy() 

                if search_term and 'customer_search_mask_indices' in st.session_state:
                    original_indices_being_edited = st.session_state['customer_search_mask_indices']
                    
                    if len(edited_df_corrected) == len(original_indices_being_edited):
                        for i, original_idx in enumerate(original_indices_being_edited):
                            if original_idx in full_df_to_save.index: 
                                for col_editor in edited_df_corrected.columns:
                                    if col_editor in full_df_to_save.columns:
                                        full_df_to_save.loc[original_idx, col_editor] = edited_df_corrected.loc[i, col_editor]
                        # 날짜 필드 문자열로 들어오므로 datetime 형식으로 맞춰줌
                        if '만기일' in edited_df_corrected.columns:
                            edited_df_corrected['만기일'] = pd.to_datetime(edited_df_corrected['만기일'], errors='coerce').dt.strftime("%Y-%m-%d")
                        if '만기' in edited_df_corrected.columns:
                            edited_df_corrected['만기'] = pd.to_datetime(edited_df_corrected['만기'], errors='coerce').dt.strftime("%Y-%m-%d")

                    else: 
                        st.warning("검색 중 행 수가 변경되어 일부 변경사항만 적용될 수 있습니다. 전체 목록에서 확인 및 저장해주세요.")
                else: 
                    if list(full_df_to_save.columns) == list(edited_df_corrected.columns):
                         full_df_to_save = edited_df_corrected.copy()
                    else: 
                        if len(edited_df_corrected) >= len(full_df_to_save):
                            full_df_to_save = edited_df_corrected.reindex(columns=full_df_to_save.columns).fillna("")
                        else: 
                            full_df_to_save = edited_df_corrected.reindex(columns=full_df_to_save.columns).fillna("")


                st.session_state['df'] = full_df_to_save.reset_index(drop=True)
                if save_customer_df(st.session_state['df']):
                    st.success("수정된 내용이 Google Sheet에 저장되었습니다.")
                else:
                    st.error("Google Sheet에 저장 실패했습니다.")
                st.rerun()
            
    elif current_page == "daily":
        st.subheader("📊 일일결산") 

        col_left, col_right = st.columns([8,1])
        with col_right:
            if st.button("📅 월간결산", use_container_width=True):
                st.session_state["current_page"] = "monthly"
                st.rerun()

        data = load_daily() 
        balance = load_balance()
        
        # -------------------
        # 날짜 선택: Streamlit 기본 달력
        # -------------------
        if "daily_selected_date" not in st.session_state:
            st.session_state["daily_selected_date"] = datetime.date.today()

        # 달력 위젯
        선택날짜 = st.date_input(
            "날짜 선택",
            value=st.session_state["daily_selected_date"],
            key="daily_date_input"
        )

        # 날짜가 바뀌면 다시 렌더링
        if 선택날짜 != st.session_state["daily_selected_date"]:
            st.session_state["daily_selected_date"] = 선택날짜
            st.rerun()

        # 문자열 포맷
        선택날짜_문자열 = 선택날짜.strftime("%Y-%m-%d")
        선택날짜_표시     = 선택날짜.strftime("%Y년 %m월 %d일")

        st.subheader(f"📊 일일결산: {선택날짜_표시}")


        선택날짜_문자열 = 선택날짜.strftime("%Y-%m-%d")
        선택날짜_표시 = 선택날짜.strftime("%Y년 %m월 %d일")
        이번달_str = 선택날짜.strftime("%Y-%m") 

        오늘_데이터 = [row for row in data if row.get("date") == 선택날짜_문자열]
        오늘_데이터.sort(key=lambda x: x.get('time', '00:00:00')) 

        if not 오늘_데이터:
            st.info("선택한 날짜에 등록된 내역이 없습니다.")

        for idx, row_data in enumerate(오늘_데이터): 
            cols = st.columns([0.6, 1.5, 2.5, 1, 1, 1, 1, 1, 1.5, 0.8]) 
            cols[0].text_input("시간", value=row_data.get("time", ""), key=f"time_disp_{idx}", disabled=True, label_visibility="collapsed") 
            
            new_name = cols[1].text_input("이름", value=row_data.get("name", ""), key=f"name_{idx}", label_visibility="collapsed", placeholder="이름")
            new_task = cols[2].text_input("업무", value=row_data.get("task", ""), key=f"task_{idx}", label_visibility="collapsed", placeholder="업무")
            
            new_income_cash = cols[3].number_input("현금입금", value=row_data.get("income_cash", 0), key=f"inc_cash_{idx}", format="%d", label_visibility="collapsed", help="현금입금")
            new_exp_cash = cols[4].number_input("현금지출", value=row_data.get("exp_cash", 0), key=f"exp_cash_{idx}", format="%d", label_visibility="collapsed", help="현금지출")
            new_cash_out = cols[5].number_input("현금출금", value=row_data.get("cash_out", 0), key=f"cash_out_{idx}", format="%d", label_visibility="collapsed", help="현금출금(개인)")
            new_income_etc = cols[6].number_input("기타입금", value=row_data.get("income_etc", 0), key=f"inc_etc_{idx}", format="%d", label_visibility="collapsed", help="기타입금")
            new_exp_etc = cols[7].number_input("기타지출", value=row_data.get("exp_etc", 0), key=f"exp_etc_{idx}", format="%d", label_visibility="collapsed", help="기타지출")
            
            new_memo = cols[8].text_input("비고", value=row_data.get("memo", ""), key=f"memo_{idx}", label_visibility="collapsed", placeholder="비고")

            action_cols_daily = cols[9].columns(2)
            if action_cols_daily[0].button("✏️", key=f"edit_daily_{idx}", help="수정"):
                original_row_id = row_data.get("id")
                for item_idx_loop, item_loop in enumerate(data): 
                    if item_loop.get("id") == original_row_id:
                        data[item_idx_loop].update({
                            "name": new_name, "task": new_task,
                            "income_cash": new_income_cash, "income_etc": new_income_etc,
                            "exp_cash": new_exp_cash, "cash_out": new_cash_out, "exp_etc": new_exp_etc,
                            "memo": new_memo
                        })
                        break
                save_daily(data)
                st.success("수정되었습니다.")
                st.rerun()

            if action_cols_daily[1].button("🗑️", key=f"delete_daily_{idx}", help="삭제"):
                original_row_id = row_data.get("id")
                data = [d for d in data if d.get("id") != original_row_id]
                save_daily(data)
                st.success("삭제되었습니다.")
                st.rerun()
        st.markdown("---")
        
        st.markdown("#### 새 내역 추가")
        with st.form("add_daily_form_old_ui", clear_on_submit=True):
            form_cols = st.columns([1.5, 2.5, 1, 1, 1, 1, 1, 1.5, 0.8])
            add_name = form_cols[0].text_input("이름", key="add_daily_name_old")
            add_task = form_cols[1].text_input("업무", key="add_daily_task_old")
            add_income_cash = form_cols[2].number_input("현금입금", value=0, key="add_daily_inc_cash_old", format="%d")
            add_exp_cash = form_cols[3].number_input("현금지출", value=0, key="add_daily_exp_cash_old", format="%d")
            add_cash_out = form_cols[4].number_input("현금출금", value=0, key="add_daily_cash_out_old", format="%d") 
            add_income_etc = form_cols[5].number_input("기타입금", value=0, key="add_daily_inc_etc_old", format="%d")
            add_exp_etc = form_cols[6].number_input("기타지출", value=0, key="add_daily_exp_etc_old", format="%d")
            add_memo = form_cols[7].text_input("비고", key="add_daily_memo_old")
            
            submitted = form_cols[8].form_submit_button("➕ 추가")

            if submitted:
                if not add_name and not add_task:
                    st.warning("이름 또는 업무 내용을 입력해주세요.")
                else:
                    new_entry_row = { 
                        "id": str(uuid.uuid4()),
                        "date": 선택날짜_문자열,
                        "time": datetime.datetime.now().strftime("%H:%M:%S"),
                        "name": add_name, "task": add_task,
                        "income_cash": add_income_cash, "income_etc": add_income_etc,
                        "exp_cash": add_exp_cash, "cash_out": add_cash_out, "exp_etc": add_exp_etc,
                        "memo": add_memo
                    }
                    data.append(new_entry_row)
                    save_daily(data)
                    st.success(f"{선택날짜_표시}에 새 내역이 추가되었습니다.")
                    st.rerun()
        
        st.markdown("---")
        st.markdown("#### 요약 정보")

        일_총입금 = sum(r.get("income_cash", 0) + r.get("income_etc", 0) for r in 오늘_데이터)
        일_총사업지출 = sum(r.get("exp_cash", 0) + r.get("exp_etc", 0) for r in 오늘_데이터)
        일_총개인출금 = sum(r.get("cash_out", 0) for r in 오늘_데이터)
        일_총지출_합계 = 일_총사업지출 + 일_총개인출금
        일_순수익 = 일_총입금 - 일_총사업지출

        이번달_선택일까지_데이터 = [r for r in data if r.get("date","").startswith(이번달_str) and r.get("date","") <= 선택날짜_문자열]
        월_총입금 = sum(r.get("income_cash", 0) + r.get("income_etc", 0) for r in 이번달_선택일까지_데이터)
        월_총사업지출 = sum(r.get("exp_cash", 0) + r.get("exp_etc", 0) for r in 이번달_선택일까지_데이터)
        월_총개인출금 = sum(r.get("cash_out",0) for r in 이번달_선택일까지_데이터)
        월_총지출_합계 = 월_총사업지출 + 월_총개인출금
        월_순수익 = 월_총입금 - 월_총사업지출

        사무실현금_누적 = 0
        all_data_sorted_for_cash = sorted(data, key=lambda x: (x.get('date', ''), x.get('time', '00:00:00')))
        
        for r_calc in all_data_sorted_for_cash:
            if r_calc.get('date','') > 선택날짜_문자열: 
                break
            사무실현금_누적 += r_calc.get("income_cash", 0)
            사무실현금_누적 -= r_calc.get("exp_cash", 0)
            사무실현금_누적 -= r_calc.get("cash_out", 0) 

        all_entry_dates = sorted(list(set(r.get("date") for r in data if r.get("date"))))
        is_latest_entry_date_or_today = not all_entry_dates or 선택날짜_문자열 >= all_entry_dates[-1]
        
        if is_latest_entry_date_or_today : 
            balance["cash"] = 사무실현금_누적 
            current_month_all_entries = [d_item for d_item in data if d_item.get("date","").startswith(이번달_str)]
            current_month_total_profit = sum(
                d_item.get("income_cash",0) + d_item.get("income_etc",0) - d_item.get("exp_cash",0) - d_item.get("exp_etc",0)  
                for d_item in current_month_all_entries
            )
            balance["profit"] = current_month_total_profit 
            save_balance(balance) 

        sum_col1, sum_col2 = st.columns(2)
        with sum_col1:
            st.write(f"📅 {선택날짜.month}월 총 입금액 (선택일까지): {int(월_총입금):,} 원")
            st.write(f"📅 {선택날짜.month}월 총 지출액 (사업+개인, 선택일까지): {int(월_총지출_합계):,} 원")
            st.write(f"📅 {선택날짜.month}월 순수익 (선택일까지): {int(월_순수익):,} 원")
        with sum_col2:
            st.write(f"오늘({선택날짜.day}일) 총입금: {int(일_총입금):,} 원")
            st.write(f"오늘({선택날짜.day}일) 총지출 (사업+개인): {int(일_총지출_합계):,} 원")
            st.write(f"오늘({선택날짜.day}일) 순수익: {int(일_순수익):,} 원")
            st.write(f"💰 현재 사무실 현금 (선택일 마감 기준): {int(사무실현금_누적):,} 원")
        st.caption(f"* '{선택날짜.strftime('%Y년 %m월')}' 전체 순수익은 '{balance['profit']:,}' 원 입니다 (Google Sheet '잔액' 기준).")

    elif current_page == "monthly":
        st.subheader("📅 월간결산")

        all_daily_data = load_daily()
        if not all_daily_data:
            st.warning("결산 데이터가 없습니다.")
            st.stop()

        df_all = pd.DataFrame(all_daily_data)
        df_all['date'] = pd.to_datetime(df_all['date'], errors='coerce')
        df_all['순수익'] = df_all['income_cash'] + df_all['income_etc'] - df_all['exp_cash'] - df_all['exp_etc']
        df_all['총매출'] = df_all['income_cash'] + df_all['income_etc']

        # ⬛ 1. 월별 요약 테이블
        st.markdown("### 📊 월별 순수익 요약")
        df_all = df_all.dropna(subset=['date'])
        df_all['month'] = df_all['date'].dt.to_period('M').astype(str)

        monthly_summary = df_all.groupby('month').agg({
            'income_cash': 'sum',
            'income_etc': 'sum',
            'exp_cash': 'sum',
            'exp_etc': 'sum',
            '순수익': 'sum'
        }).rename(columns={
            'income_cash': '현금입금',
            'income_etc': '기타입금',
            'exp_cash': '현금지출',
            'exp_etc': '기타지출'
        })

        monthly_summary['총입금'] = monthly_summary['현금입금'] + monthly_summary['기타입금']
        monthly_summary['총지출'] = monthly_summary['현금지출'] + monthly_summary['기타지출']

        df_display = monthly_summary[['총입금', '총지출', '순수익']].astype(int)
        st.dataframe(df_display.style.format("{:,} 원"), use_container_width=True)

        st.markdown("---")

        # ✅ 한국 폰트 설정
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
        font_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
        if os.name == 'nt':
            font_path = "C:/Windows/Fonts/malgun.ttf"
        if os.path.exists(font_path):
            fontprop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = fontprop.get_name()
        else:
            st.warning("한국 폰트를 찾을 수 없어 기본 폰트로 표시됩니다. 글자가 깨질 수 있습니다.")

        # ⬛ 2. 📈 요일별 순수익 분석
        st.markdown("### 📈 요일별 순수익 분석")
        df_all['weekday'] = df_all['date'].dt.day_name()

        weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        weekday_kor = ['월', '화', '수', '목', '금', '토', '일']
        weekday_map = dict(zip(weekday_order, weekday_kor))

        weekday_summary = df_all.groupby('weekday')['순수익'].sum().reindex(weekday_order)

        if weekday_summary.isnull().all():
            st.warning("요일별 수익 데이터가 없습니다.")
        else:
            plt.figure(figsize=(8, 4))
            plt.bar([weekday_map.get(day, day) for day in weekday_summary.index], weekday_summary.values)
            plt.title('요일별 순수익')
            plt.ylabel('수익(원)')
            plt.xlabel('요일')
            st.pyplot(plt)

        st.markdown("---")

        # ⬛ 3. 🧼 업무별 순수익 분석
        st.markdown("### 🧼 업무별 순수익 분석")

        def classify_task(task_text):
            task_text = str(task_text)
            if any(keyword in task_text for keyword in ['등록', '연장', '변경']):
                return '출입국'
            elif '공증' in task_text:
                return '공증'
            elif '영주' in task_text:
                return '영주'
            else:
                return '기타'

        df_all['업무분류'] = df_all['task'].apply(classify_task)

        task_summary = df_all.groupby('업무분류')['순수익'].sum().reindex(['출입국', '공증', '영주', '기타'])

        plt.figure(figsize=(6, 4))
        task_summary.plot(kind='bar', color='orange')
        plt.title('업무별 순수익 분석')
        plt.ylabel('수익(원)')
        plt.xlabel('업무')
        st.pyplot(plt)

        st.markdown("---")

        # ⬛ 4. ⏰ 시간대별 매출 분석
        st.markdown("### ⏰ 시간대별 매출 분석")

        def classify_time_group(t_str):
            try:
                hour = int(str(t_str).split(':')[0])
                if hour < 11:
                    return '오전'
                elif hour < 16:
                    return '점심~오후'
                elif hour < 21:
                    return '저녁'
                else:
                    return '야간'
            except:
                return '기타'

        df_all['시간대'] = df_all['time'].apply(classify_time_group)
        time_summary = df_all.groupby('시간대')['총매출'].sum().reindex(['오전','점심~오후','저녁','야간','기타'])

        plt.figure(figsize=(6, 4))
        time_summary.plot(kind='bar', color='green')
        plt.title('시간대별 매출 분석')
        plt.ylabel('총매출(원)')
        plt.xlabel('시간대')
        st.pyplot(plt)

    elif current_page == "manual": 
        st.subheader("🧭 메뉴얼 검색 (GPT 기반)")
        question = st.text_input("궁금한 내용을 입력하세요", placeholder="예: F-4에서 F-5 변경 조건은?") 
        if st.button("🔍 GPT로 검색하기"): 
            if question:
                with st.spinner("답변 생성 중입니다..."): 
                    answer = search_via_server(question) 
                    st.markdown("#### 🧠 GPT 요약 답변")
                    st.write(answer) 
            else:
                st.info("검색할 내용을 입력해주세요.")

    elif current_page == "memo": 
        st.subheader("🗒️ 메모장")

        st.markdown("### 📌 장기보존 메모")
        memo_long_content = load_long_memo()
        edited_memo_long = st.text_area("🗂️ 장기보존 내용", value=memo_long_content, height=200, key="memo_long_old_ui")
        if st.button("💾 장기메모 저장", key="save_memo_long_old_ui", use_container_width=True): 
            save_long_memo(edited_memo_long)
            st.success("✅ 장기보존 메모가 저장되었습니다.")
            st.rerun() 

        st.markdown("---")
        col_mid, col_short = st.columns(2)

        with col_mid:
            st.markdown("### 🗓️ 중기 메모")
            memo_mid_content = load_mid_memo()
            edited_memo_mid = st.text_area("📘 중기메모", value=memo_mid_content, height=300, key="memo_mid_old_ui")
            if st.button("💾 중기메모 저장", key="save_memo_mid_old_ui", use_container_width=True):
                save_mid_memo(edited_memo_mid)
                st.success("✅ 중기메모가 저장되었습니다.")
                st.rerun()

        with col_short:
            st.markdown("### 📅 단기 메모")
            memo_short_content = load_short_memo()
            edited_memo_short = st.text_area("📗 단기메모", value=memo_short_content, height=300, key="memo_short_old_ui")
            if st.button("💾 단기메모 저장", key="save_memo_short_old_ui", use_container_width=True):
                save_short_memo(edited_memo_short)
                st.success("✅ 단기메모가 저장되었습니다.")
                st.rerun()

    # 📄 문서작성 자동화 페이지
    elif current_page == "document":
        st.subheader("📝 문서작성 자동화")
    
        # --- 1) 입력 영역 ---
        if "df_customer" not in st.session_state:
            st.session_state["df_customer"] = load_customer_df()
        df_cust = st.session_state["df_customer"]
        cust_list = df_cust["한글"].fillna("").tolist()
    
        cols = st.columns([2,2,2,2,2])
        with cols[0]:
            search_term = st.text_input("🔍 고객 검색 (이름 입력)", key="doc_search")
            customer = search_term
            # 미성년자 대리인 로직
            birth_val = df_cust.loc[df_cust["한글"]==customer, "등록증"].squeeze() if customer in cust_list else None
            if birth_val:
                try:
                    birth_year = int(str(birth_val).split("-")[0])
                except:
                    birth_year = 1900
                if birth_year > datetime.date.today().year - 19 and "대리인" in df_cust.columns:
                    reps = df_cust["대리인"].dropna().unique().tolist()
                    proxy = st.selectbox("대리인 선택", [""]+reps, key="doc_proxy")
        with cols[1]:
            업무 = st.selectbox("업무", ["H2","F4","F5","국적"], key="doc_task")
        with cols[2]:
            내용 = st.selectbox("내용", ["등록","연장","자격변경","자격부여","체류지 변경","등록사항 변경"], key="doc_action")
        with cols[3]:
            체류지 = st.text_input("체류지", placeholder="검색 또는 직접 입력", key="doc_location")
        with cols[4]:
            보증인 = st.text_input("신원보증인", placeholder="검색 또는 직접 입력", key="doc_guarantor")
    
        st.markdown("---")
    
        # --- 2) 필요 서류 안내 ---
        if st.button("➕ 필요서류 보기", key="show_docs"):
            서류맵 = { ("H2","등록"): ["비자신청서","초청장"],
                      ("F4","연장"): ["체류연장신청서","재직증명서"] }
            needed = 서류맵.get((업무,내용), ["서류 정의 필요"])        
            for d in needed: st.write(f"- {d}")
    
        st.markdown("---")
    
        # --- 3) PDF 업로드 ---
        uploaded = st.file_uploader("🗂️ 양식 PDF 업로드", type="pdf", key="doc_template_pdf")
        if uploaded:
            st.success("업로드 완료. 자동작성 로직 연결 예정입니다.")

    # 📚 업무참고 페이지
    elif current_page == "reference":
        st.subheader("📚 업무참고")
        col_blank, col_doc, col_done = st.columns([8,1,1])
        with col_doc:
            if st.button("📝 서류작성", key="nav-document"):
                st.session_state["current_page"] = "document"
                st.rerun()
        with col_done:
            if st.button("✅ 완료업무", key="nav-completed-ref"):
                st.session_state["current_page"] = "completed"
                st.rerun()
        # 업무참고로 돌아왔을 때도 iframe이 항상 실행되도록 분기 바로 안에 배치
        components.iframe(
            "https://docs.google.com/spreadsheets/d/1Jr-vGVMwRFlXu04J8Q1zEwmwv8b0CO0nqyRyRACowpY/edit?usp=drive_link",
            height=800,
            scrolling=True
        )

    elif current_page == "completed":
        st.subheader("✅ 완료업무")

        # 1) 검색 입력창
        search_term = st.text_input("🔍 검색", key="completed_search_term")

        # 2) 데이터 불러오기 및 DataFrame 변환
        completed = load_completed_tasks()
        df = pd.DataFrame(completed)
        if not df.empty and 'category' in df.columns:
            df['category'] = df['category'].fillna('')
            df = df.sort_values(by='category')

        # 3) id 컬럼 숨기기
        if "id" in df.columns:
            df = df.drop(columns=["id"])

        # 4) 검색어 필터링
        if search_term:
            mask = df.astype(str).apply(
                lambda row: search_term.lower() in row.str.lower().to_string(),
                axis=1
            )
            df = df[mask]

        # 5) 테이블 표시 (필요하다면 st.data_editor)
        edited = st.data_editor(
            df,
            use_container_width=True,
            num_rows="dynamic",
            hide_index=True
        )

        # 6) 편집 후 저장 (옵션)
        if st.button("💾 저장 완료업무"):
            save_completed_tasks(
                # 다시 id 없이 저장하려면, load_completed_tasks() 대신 edited 에 complete_date 등 포함
                edited.to_dict("records")
            )
            st.success("완료업무 시트에 저장되었습니다.")

    elif current_page == "home":
        # Use st.columns(2) for a 50/50 split as per the old UI's implied structure
        home_col_left, home_col_right = st.columns(2) 

        with home_col_left:
            st.subheader("1. 📅 일정 달력")
            
            # --- Calendar specific data (events_data_home) ---
            # This should use the Google Sheets based load_events()
            if "events_data_home" not in st.session_state:
                # 한 번만 불러와서 세션에 저장
                st.session_state["events_data_home"] = load_events()
            events_data_home = st.session_state["events_data_home"]

            # --- Year/Month Selection ---
            # Old UI: col_year, col_month = st.columns([1, 1])
            # Old UI: label_visibility="collapsed"
            cal_ym_cols = st.columns(2)
            today_cal = datetime.date.today() # Use a different variable name for today in this scope
            year_options_cal = list(range(today_cal.year - 5, today_cal.year + 6)) # More options like current code

            with cal_ym_cols[0]:
                selected_year_cal = st.selectbox(
                    "📅 연도 선택",  # Label from old code
                    options=year_options_cal,  
                    index=year_options_cal.index(st.session_state.get("home_selected_year", today_cal.year)), 
                    key="home_year_selector_old", # Unique key
                    label_visibility="collapsed" 
                )
            with cal_ym_cols[1]:
                selected_month_cal = st.selectbox(
                    "📆 달 선택", # Label from old code
                    options=range(1, 13),  
                    index=st.session_state.get("home_selected_month", today_cal.month) -1 , 
                    key="home_month_selector_old", # Unique key
                    format_func=lambda m_val: f"{m_val}월",
                    label_visibility="collapsed"
                )
            
            # Persist selection in session state
            st.session_state.home_selected_year = selected_year_cal
            st.session_state.home_selected_month = selected_month_cal

            # --- Calendar Display ---
            calendar_obj_home = calendar.Calendar(firstweekday=6) 
            month_days_home = calendar_obj_home.monthdayscalendar(selected_year_cal, selected_month_cal) 
            
            day_labels_cal = ["일", "월", "화", "수", "목", "금", "토"] 
            day_cols_cal = st.columns(7) 
            for i_cal, label_cal in enumerate(day_labels_cal): 
                day_cols_cal[i_cal].markdown(f"<h5 style='text-align:center;'>{label_cal}</h5>", unsafe_allow_html=True) # h5 from old

            for week_cal in month_days_home: 
                cols_cal_week = st.columns(7) 
                for i_day_cal, day_num_cal in enumerate(week_cal): 
                    if day_num_cal == 0:
                        cols_cal_week[i_day_cal].markdown(" ") 
                    else:
                        date_obj_cal = datetime.date(selected_year_cal, selected_month_cal, day_num_cal) 
                        date_str_event_cal = date_obj_cal.strftime("%Y-%m-%d") 
                        
                        button_label_cal = str(day_num_cal) 
                        is_today_cal = (date_obj_cal == today_cal) 
                        has_event_cal = date_str_event_cal in events_data_home and events_data_home[date_str_event_cal] 
                        
                        button_style_cal = "" 
                        if is_today_cal: button_style_cal = "🟢" 
                        elif has_event_cal: button_style_cal = "🔴" 

                        if cols_cal_week[i_day_cal].button(f"{button_style_cal} {button_label_cal}", key=f"day_btn_home_cal_{date_str_event_cal}", use_container_width=True):
                            st.session_state["home_calendar_selected_date"] = date_obj_cal 
                            st.rerun() 
            
            # --- Selected Date and Event Management ---
            if "home_calendar_selected_date" not in st.session_state:
                st.session_state["home_calendar_selected_date"] = today_cal
            
            selected_date_cal_display = st.session_state["home_calendar_selected_date"] 
            selected_date_str_cal_display = selected_date_cal_display.strftime("%Y-%m-%d") 

            st.markdown(f"**📅 선택한 날짜: {selected_date_cal_display.strftime('%Y-%m-%d')}**") # Old format from screenshot
            
            existing_events_cal = events_data_home.get(selected_date_str_cal_display, []) 
            if existing_events_cal:
                st.write("기존 일정:") 
                for idx_ev_cal, event_item_cal in enumerate(existing_events_cal): 
                    ev_cols_cal_disp = st.columns([8,2]) 
                    ev_cols_cal_disp[0].write(f"{idx_ev_cal + 1}. {event_item_cal}") 
                    if ev_cols_cal_disp[1].button("삭제", key=f"del_event_home_cal_{selected_date_str_cal_display}_{idx_ev_cal}", use_container_width=True):
                        # ① 세션에서 꺼내서
                        ev_dict = st.session_state["events_data_home"]
                        # ② 리스트에서 삭제
                        ev_dict[selected_date_str_cal_display].pop(idx_ev_cal)
                        # ③ 빈 리스트가 되면 키 자체를 지우고
                        if not ev_dict[selected_date_str_cal_display]:
                            del ev_dict[selected_date_str_cal_display]
                        # ④ 수정된 dict을 저장 함수로 넘기기
                        save_events(ev_dict)
                        st.success("일정이 삭제되었습니다.") 
                        st.rerun()
            
            with st.form("calendar_event_form"):
                event_text_cal_input = st.text_input(f"일정 입력 ({selected_date_str_cal_display})", key="event_text_cal_input_fixed")
                submitted = st.form_submit_button("일정 저장")

                if submitted:
                    if event_text_cal_input:
                        ev_dict = st.session_state["events_data_home"]
                        # 키가 없으면 빈 리스트 생성
                        ev_dict.setdefault(selected_date_str_cal_display, [])
                        # 텍스트 추가
                        ev_dict[selected_date_str_cal_display].append(event_text_cal_input)
                        # 저장
                        save_events(ev_dict)
                    st.success(f"'{event_text_cal_input}' 일정이 저장되었습니다.")
                    st.rerun()
            
            st.markdown("---")
            today_str_cal_summary = today_cal.strftime("%Y-%m-%d") 
            tomorrow_obj_cal_summary = today_cal + datetime.timedelta(days=1) 
            tomorrow_str_cal_summary = tomorrow_obj_cal_summary.strftime("%Y-%m-%d") 

            event_summary_cols_cal = st.columns(2)
            with event_summary_cols_cal[0]:
                st.subheader("📌 오늘 일정")
                today_events_list_cal = events_data_home.get(today_str_cal_summary, []) 
                if today_events_list_cal:
                    for e_cal_today in today_events_list_cal: st.write(f"- {e_cal_today}") 
                else: st.write("(일정 없음)")
            
            with event_summary_cols_cal[1]:
                st.subheader("🕒 내일 일정")
                tomorrow_events_list_cal = events_data_home.get(tomorrow_str_cal_summary, []) 
                if tomorrow_events_list_cal:
                    for e_cal_tmr in tomorrow_events_list_cal: st.write(f"- {e_cal_tmr}") 
                else: st.write("(일정 없음)")

        with home_col_right:
            # This is the equivalent of the old load_customer_data() function
            st.subheader("2. 🪪 등록증 만기 4개월 전") # Old subheader
            
            df_customers_for_alert = load_customer_df() # Use the main customer loader
            
            if df_customers_for_alert.empty:
                st.write("(표시할 고객 없음)") # Old message
            else:
                # Prepare display data specifically for alerts
                df_alert_display_prepared = pd.DataFrame()
                df_alert_display_prepared['한글이름'] = df_customers_for_alert.get('한글', pd.Series(dtype='str'))
                # 영문이름, 여권번호, 생년월일, 전화번호 formatting from old code
                df_alert_display_prepared['영문이름'] = df_customers_for_alert.get('성', pd.Series(dtype='str')).fillna('') + ' ' + df_customers_for_alert.get('명', pd.Series(dtype='str')).fillna('')
                df_alert_display_prepared['여권번호'] = df_customers_for_alert.get('여권', pd.Series(dtype='str')).astype(str).str.strip()
                
                # Phone number with spaces
                df_alert_display_prepared['전화번호'] = (
                    df_customers_for_alert.get('연', pd.Series(dtype='str')).astype(str).apply(lambda x: x.split('.')[0].zfill(3) if pd.notna(x) and x.strip() and x.lower()!='nan' else "") + ' ' +
                    df_customers_for_alert.get('락', pd.Series(dtype='str')).astype(str).apply(lambda x: x.split('.')[0].zfill(4) if pd.notna(x) and x.strip() and x.lower()!='nan' else "") + ' ' +
                    df_customers_for_alert.get('처', pd.Series(dtype='str')).astype(str).apply(lambda x: x.split('.')[0].zfill(4) if pd.notna(x) and x.strip() and x.lower()!='nan' else "")
                ).str.replace(r'^\s* \s*$', '(정보없음)', regex=True).str.replace(r'^--$', '(정보없음)', regex=True)


                # Birthdate formatting from old version
                def format_birthdate_alert(reg_num_str_series_val):
                    if pd.isna(reg_num_str_series_val) or not str(reg_num_str_series_val).strip(): return ''
                    reg_num_str = str(reg_num_str_series_val).split('.')[0]
                    if len(reg_num_str) >= 6 and reg_num_str[:6].isdigit():
                        yy = reg_num_str[:2]
                        # Old logic for century based on first digit of YYMMDD
                        year_prefix = '19' if yy[0] in '456789' else '20'
                        try: # Ensure full YYYYMMDD before formatting
                            return datetime.datetime.strptime(f"{year_prefix}{reg_num_str[:6]}", "%Y%m%d").strftime("%Y-%m-%d")
                        except ValueError: return ''
                    return ''
                df_alert_display_prepared['생년월일'] = df_customers_for_alert.get('등록증', pd.Series(dtype='str')).apply(format_birthdate_alert)

                # Passport expiry
                df_customers_for_alert['등록증만기일_dt_alert'] = pd.to_datetime(df_customers_for_alert.get('만기일'), errors='coerce') # '만기일' is reg card expiry
                card_alert_limit_hr = pd.to_datetime(datetime.date.today() + pd.DateOffset(months=4)) 
                card_alerts_hr = df_customers_for_alert[ 
                    df_customers_for_alert['등록증만기일_dt_alert'].notna() & 
                    (df_customers_for_alert['등록증만기일_dt_alert'] <= card_alert_limit_hr) &
                    (df_customers_for_alert['등록증만기일_dt_alert'] >= pd.to_datetime(datetime.date.today()))
                ].sort_values(by='등록증만기일_dt_alert')

                if not card_alerts_hr.empty:
                    display_df_card_alert = df_alert_display_prepared.loc[card_alerts_hr.index].copy()
                    display_df_card_alert['등록증만기일'] = card_alerts_hr['등록증만기일_dt_alert'].dt.strftime('%Y-%m-%d')
                    st.dataframe(display_df_card_alert[['한글이름', '등록증만기일', '여권번호', '생년월일', '전화번호']], use_container_width=True, hide_index=True) # height removed
                else:
                    st.write("(표시할 고객 없음)") 

                st.subheader("3. 🪪 여권 만기 6개월 전") # Old subheader
                df_customers_for_alert['여권만기일_dt_alert'] = pd.to_datetime(
                    df_customers_for_alert.get('만기').astype(str).str.strip(),
                    errors='coerce'
                )

                passport_alert_limit_hr = pd.to_datetime(datetime.date.today() + pd.DateOffset(months=6))
                passport_alerts_hr = df_customers_for_alert[ 
                    df_customers_for_alert['여권만기일_dt_alert'].notna() & 
                    (df_customers_for_alert['여권만기일_dt_alert'] <= passport_alert_limit_hr) &
                    (df_customers_for_alert['여권만기일_dt_alert'] >= pd.to_datetime(datetime.date.today()))
                ].sort_values(by='여권만기일_dt_alert')
                
                if not passport_alerts_hr.empty:
                    display_df_passport_alert = df_alert_display_prepared.loc[passport_alerts_hr.index].copy()
                    display_df_passport_alert['여권만기일'] = passport_alerts_hr['여권만기일_dt_alert'].dt.strftime('%Y-%m-%d')
                    st.dataframe(display_df_passport_alert[['한글이름', '여권만기일', '여권번호', '생년월일', '전화번호']], use_container_width=True, hide_index=True) # height removed for auto-sizing
                else:
                    st.write("(표시할 고객 없음)") 

        # Planned and Active tasks should be outside the columns, spanning full width
        st.markdown("---") 
        
        st.subheader("4. 📌 예정업무")
        planned_tasks_data_h = load_planned_tasks() 
        기간_옵션_plan_home = ["장기🟢", "중기🟡", "단기🔴", "완료✅", "보류⏹️"]  # Use consistent options
        기간_우선순위_plan_home = {option: i for i, option in enumerate(기간_옵션_plan_home)}
        
        planned_tasks_data_h.sort(key=lambda x: (기간_우선순위_plan_home.get(x.get("period",""), 99), pd.to_datetime(x.get("date", "9999-12-31"), errors='coerce')))

        # Headers for planned tasks (as in old code)
        h_cols_plan = st.columns([0.8, 1, 4, 2, 0.5, 0.5]) # Column ratios from old code for data row
        h_cols_plan[0].markdown("**기간**")
        h_cols_plan[1].markdown("**날짜**")
        h_cols_plan[2].markdown("**내용**")
        h_cols_plan[3].markdown("**비고**")
        h_cols_plan[4].markdown("**수정**") # Edit column header
        h_cols_plan[5].markdown("**삭제**") # Delete column header


        for idx_plan_h, task_plan_h in enumerate(planned_tasks_data_h): 
            unique_key_plan_h = f"plan_task_home_disp_{task_plan_h.get('id', idx_plan_h)}" # More specific key
            cols_plan_edit = st.columns([0.8, 1, 4, 2, 0.5, 0.5]) # Ratios from old code
            
            new_period_plan = cols_plan_edit[0].text_input(" ", value=task_plan_h.get("period",""), key=f"{unique_key_plan_h}_period_txt", label_visibility="collapsed")
            new_date_plan = cols_plan_edit[1].text_input(" ", value=task_plan_h.get("date",""), key=f"{unique_key_plan_h}_date_txt", label_visibility="collapsed")
            new_content_plan = cols_plan_edit[2].text_input(" ", value=task_plan_h.get("content",""), key=f"{unique_key_plan_h}_content", label_visibility="collapsed")
            new_note_plan = cols_plan_edit[3].text_input(" ", value=task_plan_h.get("note",""), key=f"{unique_key_plan_h}_note", label_visibility="collapsed")
            
            if cols_plan_edit[4].button("수정", key=f"{unique_key_plan_h}_save_btn", help="수정 저장", use_container_width=True): # Old button text
                try:
                    datetime.datetime.strptime(new_date_plan, "%Y-%m-%d")
                except ValueError:
                    st.error(f"날짜 형식이 잘못되었습니다 (YYYY-MM-DD): {new_date_plan}")
                    st.stop() 

                planned_tasks_data_h[idx_plan_h].update({
                    "date": new_date_plan, "period": new_period_plan, 
                    "content": new_content_plan, "note": new_note_plan
                })
                save_planned_tasks(planned_tasks_data_h)
                st.success("예정업무가 수정되었습니다.")
                st.rerun()
            if cols_plan_edit[5].button("❌", key=f"{unique_key_plan_h}_delete_btn", help="삭제", use_container_width=True): # Old button text
                planned_tasks_data_h.pop(idx_plan_h)
                save_planned_tasks(planned_tasks_data_h)
                st.success("예정업무가 삭제되었습니다.")
                st.rerun()

        with st.form("add_planned_form_home", clear_on_submit=True): # Key from old code
            # Column ratios from old code: p1(0.8), p2(1), p3(3), p4(2), p5(1)
            add_form_cols_plan_h = st.columns([0.8, 1, 3, 2, 1]) 
            add_period_plan_h = add_form_cols_plan_h[0].selectbox("기간", options=기간_옵션_plan_home, key="planned_period_form_home") # Selectbox as in old form
            add_date_val_plan_h = add_form_cols_plan_h[1].date_input("날짜", value=datetime.date.today(), key="planned_date_form_home") # Dateinput as in old form
            add_content_plan_h = add_form_cols_plan_h[2].text_input("내용", key="planned_content_form_home", placeholder="업무 내용")
            add_note_plan_h = add_form_cols_plan_h[3].text_input("비고", key="planned_note_form_home", placeholder="참고 사항")
            
            if add_form_cols_plan_h[4].form_submit_button("➕ 예정업무 추가", use_container_width=True): # Old button text
                if add_content_plan_h:
                    new_task_entry_plan_h = {
                        "id": str(uuid.uuid4()),  
                        "date": add_date_val_plan_h.strftime("%Y-%m-%d"),  
                        "period": add_period_plan_h,  
                        "content": add_content_plan_h,  
                        "note": add_note_plan_h
                    }
                    planned_tasks_data_h.append(new_task_entry_plan_h)
                    save_planned_tasks(planned_tasks_data_h)
                    st.success("추가 완료!") # Old success message
                    st.rerun()
                else:
                    st.warning("내용을 입력해주세요.")
        
        st.markdown("---")

        st.subheader("5. 🛠️ 진행업무")
        active_tasks_data_h = load_active_tasks()
        구분_옵션_active_home = ["출입국", "전자민원", "공증", "여권", "초청", "영주권", "기타"] 
        구분_우선순위_active_home = {option: i for i, option in enumerate(구분_옵션_active_home)}

        active_tasks_data_h.sort(key=lambda x: (구분_우선순위_active_home.get(x.get("category","").split(" - ")[0], 99), pd.to_datetime(x.get("date", "9999-12-31"), errors='coerce')))

        h_cols = st.columns([0.8, 1, 1, 1, 4, 0.8, 0.8, 0.8], gap="small")
        h_cols[0].markdown("**구분**")
        h_cols[1].markdown("**진행일**")
        h_cols[2].markdown("**성명**")
        h_cols[3].markdown("**업무**")
        h_cols[4].markdown("**세부내용**")
        h_cols[5].markdown("**수정**")
        h_cols[6].markdown("**완료**")
        h_cols[7].markdown("**삭제**")
        
        # --- 행별 입력 폼 ---
        for idx, task in enumerate(active_tasks_data_h):
            uid = f"{task['id']}_{idx}"
            cols = st.columns([0.8, 1, 1, 1, 4, 0.8, 0.8, 0.8], gap="small")
        
            new_category = cols[0].text_input(" ", value=task["category"], key=f"{uid}_cat",    label_visibility="collapsed")
            new_date     = cols[1].text_input(" ", value=task["date"],     key=f"{uid}_date",   label_visibility="collapsed")
            new_name     = cols[2].text_input(" ", value=task["name"],     key=f"{uid}_name",   label_visibility="collapsed")
            new_work     = cols[3].text_input(" ", value=task["work"],     key=f"{uid}_work",   label_visibility="collapsed")
            new_details  = cols[4].text_input(" ", value=task["details"],  key=f"{uid}_details",label_visibility="collapsed")
        
            # 수정
            if cols[5].button("수정", key=f"{uid}_save", use_container_width=True):
                try:
                    datetime.datetime.strptime(new_date, "%Y-%m-%d")
                except ValueError:
                    st.error("날짜 형식은 YYYY-MM-DD 이어야 합니다.")
                    st.stop()
                active_tasks_data_h[idx].update({
                    "category": new_category,
                    "date":     new_date,
                    "name":     new_name,
                    "work":     new_work,
                    "details":  new_details
                })
                save_active_tasks(active_tasks_data_h)
                st.success("진행업무가 수정되었습니다.")
                st.rerun()
        
            # 완료
            if cols[6].button("완료", key=f"{uid}_complete", use_container_width=True):
                today = datetime.date.today().strftime("%Y-%m-%d")
                comp = load_completed_tasks()
                comp.append({
                    "id":            task["id"],
                    "category":      task["category"],
                    "date":          task["date"],
                    "name":          task["name"],
                    "work":          task["work"],
                    "details":       task["details"],
                    "complete_date": today,
                })
                save_completed_tasks(comp)
                active_tasks_data_h.pop(idx)
                save_active_tasks(active_tasks_data_h)
                st.success("업무가 완료되어 완료업무 탭으로 이동했습니다.")
                st.rerun()
        
            # 삭제
            if cols[7].button("삭제", key=f"{uid}_delete", use_container_width=True):
                active_tasks_data_h.pop(idx)
                save_active_tasks(active_tasks_data_h)
                st.warning("해당 업무가 삭제되었습니다.")
                st.rerun()

        with st.form("add_active_form_home", clear_on_submit=True): # Key from old code
             # Column ratios from old code: a1(0.8), a2(1), a3(1), a4(1), a5(3), a6(1)
            add_form_cols_active_h = st.columns([0.8, 1, 1, 1, 3, 1])
            add_category_main_active_h = add_form_cols_active_h[0].selectbox("구분", options=구분_옵션_active_home, key="category_form_home") # Selectbox as in old form
            
            add_date_val_active_h = add_form_cols_active_h[1].date_input("진행일", value=datetime.date.today(), key="active_date_form_home") # Dateinput as in old form
            add_name_val_active_h = add_form_cols_active_h[2].text_input("성명", key="active_name_form_home", placeholder="성명")
            add_work_val_active_h = add_form_cols_active_h[3].text_input("업무", key="active_work_form_home", placeholder="업무 종류")
            add_details_val_active_h = add_form_cols_active_h[4].text_input("내용", key="active_detail_form_home", placeholder="세부 진행사항") # "내용" label from old

            final_add_category_active_h = add_category_main_active_h # Default
            if add_category_main_active_h == "기타": 
                # For "기타", the old code had an additional text_input *outside* the columns, then appended.
                # To keep it in the form and somewhat aligned, we might need a different approach or accept it's slightly different.
                # For now, let's assume the selectbox is enough or user types "기타 - 상세내용" in a details field.
                # Replicating the exact old "기타" input logic within this form structure is tricky.
                # The old code had:
                #   extra_input = st.text_input("기타 입력 내용", key="extra_category") # This was OUTSIDE the form's columns
                #   new_category += f" - {extra_input}"
                # This is hard to replicate cleanly inside the st.form's columns directly for the "기타" option of a selectbox.
                # A common workaround is a conditional st.text_input if "기타" is selected.
                # Let's try to add it conditionally within the same column for simplicity or a new one if needed.
                # For now, the category will just be "기타". User can add details in "세부내용".
                # Or, if a sub-category for "기타" is essential, it needs a dedicated input field.
                # The old code's "기타" input was separate. Here, we'll just use the selected "기타".
                pass


            if add_form_cols_active_h[5].form_submit_button("➕ 진행업무 추가", use_container_width=True): # Old button text
                if add_name_val_active_h and add_work_val_active_h :
                    new_active_task_entry_h = { 
                        "id": str(uuid.uuid4()), "category": final_add_category_active_h, 
                        "date": add_date_val_active_h.strftime("%Y-%m-%d"),
                        "name": add_name_val_active_h, "work": add_work_val_active_h, 
                        "details": add_details_val_active_h
                    }
                    active_tasks_data_h.append(new_active_task_entry_h)
                    save_active_tasks(active_tasks_data_h)
                    st.success("추가 완료!") # Old success message
                    st.rerun()
                else:
                    st.warning("성명과 업무 내용을 입력해주세요.")

else: 
    print("Streamlit is not available. Cannot run the application.")
    print(f"Key path configured: {KEY_PATH}")
    print("To run, ensure Streamlit is installed ('pip install streamlit') and run 'streamlit run your_script_name.py'")
