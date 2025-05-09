from pathlib import Path
import requests
import pandas as pd
import datetime
import json
import os
import uuid
import calendar

try:
    import streamlit as st
except ModuleNotFoundError:
    print("Streamlit is not installed. Please run 'pip install streamlit' in your terminal.")
    st = None

# 🔍 질문을 중간 서버에 보내고 응답 받는 함수
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
            return f"서버 오류: {res.status_code}"
    except Exception as e:
        return f"요청 실패: {str(e)}"

# 🔽 그 다음에 기존에 있는 함수들
def load_events():
    ...

# -----------------------------
# ✅ 설정
# -----------------------------
import gspread
from oauth2client.service_account import ServiceAccountCredentials
EVENT_FILE = "schedule_data.json"

SHEET_KEY = "14pEPo-Q3aFgbS1Gqcamb2lkadq-eFlOrQ-wST3EU1pk"
SHEET_NAME = "고객 데이터"

def get_google_sheet_df():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "/etc/secrets/hanwoory-9eaa1a4c54d7.json",
        scope
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_KEY).worksheet(SHEET_NAME)
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    for col in [4, 5, 6, 8]:
        if col < df.shape[1]:
            df.iloc[:, col] = df.iloc[:, col].apply(lambda x: str(x).split('.')[0].zfill(4 if col != 4 else 3))
    return df

def load_customer_df():
    return get_google_sheet_df()

def save_customer_df(df):
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "/etc/secrets/hanwoory-9eaa1a4c54d7.json",
        scope
    )
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_KEY).worksheet(SHEET_NAME)
    sheet.clear()
    sheet.update([df.columns.values.tolist()] + df.values.tolist())

# ⚠️ set_page_config는 가장 먼저 와야 함!
if st:
    st.set_page_config(page_title="출입국 업무관리", layout="wide")

    # -----------------------------
    # ✅ 현재 페이지 설정
    # -----------------------------
    current_page = st.session_state.get("current_page", "home")

    # -----------------------------
    # ✅ 제목 및 툴바
    # -----------------------------
    title_col, toolbar_col = st.columns([2, 3])
    with title_col:
        st.title("📋 출입국 업무관리")
        
    with toolbar_col:
        toolbar_options = {
            "🏠 홈으로": "home",
            "🗒️ 메모장": "memo",
            "📚 업무참고": "reference",
            "👥 고객관리": "customer",
            "📊 일일결산": "daily",
            "📅 월간결산": "monthly",
            "🧭 메뉴얼 검색": "manual"
        }
        btn_cols = st.columns(len(toolbar_options))
        for idx, (label, page) in enumerate(toolbar_options.items()):
            if btn_cols[idx].button(label, key=f"nav-{label}-{idx}"):
                st.session_state["current_page"] = page
                st.rerun()
        
    # -----------------------------
    # ✅ 각 페이지 처리

    if current_page == "customer":
        if 'df' not in st.session_state:
            st.session_state['df'] = load_customer_df()

        df = st.session_state['df']

        col_add, col_search, col_select, col_delete, col_save, col_undo = st.columns([1, 1.5, 1, 1, 1, 1])

        with col_add:
            if st.button("➕ 행 추가"):
                today_str = datetime.date.today().strftime('%Y-%m-%d')
                new_row = pd.Series(["" for _ in range(df.shape[1])], index=df.columns)
                new_row.iloc[0] = today_str
                df = pd.concat([pd.DataFrame([new_row]), df], ignore_index=True)
                st.session_state['df'] = df.copy()
                st.info("새 행이 추가되었습니다. 저장하려면 💾 버튼을 누르세요.")

        with col_search:
            search_term = st.text_input("🔍 검색", value="", key="search_term")

        with col_select:
            selected_idx = st.number_input("삭제할 행 번호", min_value=0, max_value=len(st.session_state['df']) - 1, step=1, key="selected_row")

        with col_delete:
            if st.button("🗑️ 삭제 요청"):
                st.session_state['pending_delete_idx'] = selected_idx
                st.session_state['awaiting_delete_confirm'] = True

        with col_undo:
            if st.button("↩️ 삭제 취소 (Undo)"):
                if 'deleted_rows_stack' in st.session_state and st.session_state['deleted_rows_stack']:
                    idx, row_data = st.session_state['deleted_rows_stack'].pop()
                    df = st.session_state['df']
                    restored_df = pd.concat([
                        df.iloc[:idx],
                        pd.DataFrame([row_data]),
                        df.iloc[idx:]
                    ]).reset_index(drop=True)
                    st.session_state['df'] = restored_df
                    st.success(f"{idx}번 행이 복구되었습니다. 저장하려면 💾 버튼을 누르세요.")
                else:
                    st.warning("복구할 행이 없습니다.")

        df_display = st.session_state['df'].copy().fillna("").replace(['None', 'nan', 'NaT'], '')
        if search_term:
            mask = st.session_state['df'].apply(lambda row: search_term.lower() in row.astype(str).str.lower().to_string(), axis=1)
            df_display = df_display[mask].reset_index(drop=True)
            st.session_state['search_mask'] = mask
        else:
            st.session_state['search_mask'] = pd.Series([True] * len(st.session_state['df']))

        if st.session_state.get('awaiting_delete_confirm', False):
            st.warning("🔔 정말 삭제하시겠습니까?")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("✅ 예, 삭제합니다"):
                    full_df = st.session_state['df']
                    mask = st.session_state['search_mask']
                    del_idx_in_search = st.session_state.get("pending_delete_idx", -1)
                    try:
                        target_indices = full_df[mask].index.tolist()
                        real_idx = target_indices[del_idx_in_search]
                        st.session_state.setdefault('deleted_rows_stack', []).append((real_idx, full_df.loc[real_idx].copy()))
                        full_df = full_df.drop(index=real_idx).reset_index(drop=True)
                        st.session_state['df'] = full_df
                        st.success(f"{real_idx}번 행이 삭제되었습니다. 저장하려면 💾 버튼을 누르세요.")
                    except:
                        st.warning("삭제할 수 없는 인덱스입니다.")
                    st.session_state['awaiting_delete_confirm'] = False
                    st.session_state.pop('pending_delete_idx', None)
                    st.rerun()
            with col_no:
                if st.button("❌ 아니오, 취소합니다"):
                    st.session_state['awaiting_delete_confirm'] = False
                    st.session_state.pop('pending_delete_idx', None)
                    st.info("삭제가 취소되었습니다.")
                    st.rerun()

        edited_df = st.data_editor(df_display, height=600, use_container_width=True, num_rows="dynamic", key="edit_table", hide_index=False)

        with col_save:
            if st.button("💾 저장"):
                full_df = st.session_state['df']
                if search_term:
                    mask = st.session_state['search_mask']
                    target_indices = full_df[mask].index.tolist()
                    for i, idx in enumerate(target_indices):
                        try:
                            for col in full_df.columns:
                                full_df.at[idx, col] = edited_df.at[i, col]
                        except Exception as e:
                            st.error(f"{idx}번 행 수정 중 오류 발생: {e}")
                else:
                    full_df = edited_df.copy()

                st.session_state['df'] = full_df.reset_index(drop=True)
                save_customer_df(st.session_state['df'])
                st.success("수정된 내용이 저장되었습니다.")
                st.rerun()

    elif current_page == "daily":
        일일결산_FILE = "daily_summary.json"
        누적요약_FILE = "daily_balance.json"

        def load_daily():
            if os.path.exists(일일결산_FILE):
                with open(일일결산_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []

        def save_daily(data):
            with open(일일결산_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

        def load_balance():
            if os.path.exists(누적요약_FILE):
                with open(누적요약_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            return {"cash": 0, "profit": 0}

        def save_balance(balance):
            with open(누적요약_FILE, "w", encoding="utf-8") as f:
                json.dump(balance, f, ensure_ascii=False)

        data = load_daily()
        balance = load_balance()

        날짜목록 = sorted(set(row["date"] for row in data))
        if 날짜목록:
            최근날짜 = max(날짜목록)
            최근년, 최근월, 최근일 = map(int, 최근날짜.split("-"))
        else:
            최근년, 최근월, 최근일 = datetime.date.today().year, datetime.date.today().month, datetime.date.today().day

        col_left, col_right = st.columns([1, 2])
        with col_left:
            col_y, col_m, col_d = st.columns([1, 1, 1])
            with col_y:
                선택_년 = st.selectbox("연도", list(range(2020, datetime.date.today().year + 1)), index=datetime.date.today().year - 2020)
            with col_m:
                선택_월 = st.selectbox("월", list(range(1, 13)), index=datetime.date.today().month - 1)
            with col_d:
                선택_일 = st.selectbox("일", list(range(1, 32)), index=min(datetime.date.today().day, 31) - 1)

        try:
            선택날짜 = datetime.date(선택_년, 선택_월, 선택_일)
        except:
            선택날짜 = datetime.date.today()

        선택날짜_문자열 = 선택날짜.strftime("%Y-%m-%d")
        선택날짜_표시 = 선택날짜.strftime("%Y년 %m월 %d일")
        이번달 = 선택날짜.strftime("%Y-%m")

        st.subheader(f"📊 일일결산 {선택날짜_표시}")

        오늘_데이터 = [row for row in data if row["date"] == 선택날짜_문자열]
        이번달_데이터 = [
            row for row in data
            if row["date"].startswith(이번달) and row["date"] <= 선택날짜_문자열
        ]

        for idx, row in enumerate(오늘_데이터):
            c0, c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns([0.5, 1, 2, 0.8, 0.8, 0.8, 0.8, 0.8, 1, 0.5])
            c0.write(row["time"])
            name = c1.text_input("이름", value=row.get("name", ""), key=f"name_{idx}")
            task = c2.text_input("업무", value=row.get("task", ""), key=f"task_{idx}")
            income_cash = c3.number_input("현금입금", value=row["income_cash"], key=f"inc_{idx}", format="%s")
            exp_cash = c4.number_input("현금지출", value=row["exp_cash"], key=f"expcash_{idx}", format="%s")
            cash_out = c5.number_input("현금출금", value=row.get("cash_out", 0), key=f"cashout_{idx}", format="%s")
            income_etc = c6.number_input("기타입금", value=row["income_etc"], key=f"etcinc_{idx}", format="%s")
            exp_etc = c7.number_input("기타출금", value=row["exp_etc"], key=f"etcexp_{idx}", format="%s")
            profit = income_cash + income_etc - exp_cash - exp_etc
            c7.markdown(f"**수익:** {profit:,} 원")
            memo = c8.text_input("비고", value=row["memo"], key=f"memo_{idx}")
            if c9.button("수정", key=f"edit_{idx}"):
                row.update({
                    "name": name,
                    "task": task,
                    "income_cash": income_cash,
                    "income_etc": income_etc,
                    "exp_cash": exp_cash,
                    "cash_out": cash_out,
                    "exp_etc": exp_etc,
                    "memo": memo
                })
                save_daily(data)
                st.rerun()
            if c9.button("❌", key=f"delete_{idx}"):
                data.remove(row)
                save_daily(data)
                st.rerun()

        st.markdown("---")

        with st.form("add_daily_form"):
            f0, f1, f2, f3, f4, f5, f6, f7, f8 = st.columns([1, 2, 0.8, 0.8, 0.8, 0.8, 0.8, 1, 0.5])
            name = f0.text_input("이름", key="add_name")
            task = f1.text_input("업무", key="add_task")
            income_cash = f2.number_input("현금입금", key="add_cash", format="%s")
            exp_cash = f3.number_input("현금지출", key="add_exp", format="%s")
            cash_out = f4.number_input("현금출금", key="add_cashout", format="%s")
            income_etc = f5.number_input("기타입금", key="add_etcinc", format="%s")
            exp_etc = f6.number_input("기타출금", key="add_etcexp", format="%s")
            memo = f7.text_input("비고", key="add_memo")
            submitted = f8.form_submit_button("➕ 저장")

            if submitted:
                new_row = {
                    "id": str(uuid.uuid4()),
                    "date": 선택날짜_문자열,
                    "time": datetime.datetime.now().strftime("%H:%M:%S"),
                    "name": name,
                    "task": task,
                    "income_cash": income_cash,
                    "income_etc": income_etc,
                    "exp_cash": exp_cash,
                    "cash_out": cash_out,
                    "exp_etc": exp_etc,
                    "memo": memo
                }
                data.append(new_row)
                save_daily(data)
                st.success("저장 완료")
                st.rerun()

        # 일일 합계
        일_입금 = sum(row["income_cash"] + row["income_etc"] for row in 오늘_데이터)
        일_출금 = sum(row["exp_cash"] + row["exp_etc"] + row.get("cash_out", 0) for row in 오늘_데이터)
        일_순수익 = sum(row["income_cash"] + row["income_etc"] - row["exp_cash"] - row["exp_etc"] for row in 오늘_데이터)

        # 월 누적 합계
        월_입금 = sum(row["income_cash"] + row["income_etc"] for row in 이번달_데이터)
        월_출금 = sum(row["exp_cash"] + row["exp_etc"] + row.get("cash_out", 0) for row in 이번달_데이터)
        월_순수익 = sum(row["income_cash"] + row["income_etc"] - row["exp_cash"] - row["exp_etc"] for row in 이번달_데이터)

        # 누적 현금 및 순수익 저장 및 사용
        이전일자_데이터 = [row for row in data if row["date"] < 선택날짜_문자열]
        이전일자_데이터.sort(key=lambda x: x["date"])

        사무실현금 = 0
        for row in 이전일자_데이터:
            사무실현금 += row["income_cash"]
            사무실현금 -= row["exp_cash"] + row.get("cash_out", 0)

        for row in 오늘_데이터:
            사무실현금 += row["income_cash"]
            사무실현금 -= row["exp_cash"] + row.get("cash_out", 0)

        balance["cash"] = 사무실현금
        balance["profit"] = 월_순수익

        if 선택날짜_문자열 == max(날짜목록):
            save_balance(balance)

        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"📅 {선택_월}월 총 입금액: {int(월_입금):,} 원")
            st.write(f"📅 {선택_월}월 총 출금액: {int(월_출금):,} 원")
            st.write(f"📅 {선택_월}월 순수익: {int(월_순수익):,} 원")
        with col2:
            st.write(f"📆 오늘 입금: {int(일_입금):,} 원")
            st.write(f"📆 오늘 출금: {int(일_출금):,} 원")
            st.write(f"📆 오늘 순수익: {int(일_순수익):,} 원")
            st.write(f"💰 사무실 현금: {int(사무실현금):,} 원")


    elif current_page == "monthly":
        st.subheader("📅 월간결산")
        st.info("이 페이지는 추후 작성할 월간 통계 및 보고서 기능을 위한 자리입니다.")

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

    if current_page == "memo":
        st.subheader("🗒️ 메모장")
        # 📁 메모 파일 경로
        MEMO_LONG = "memo_long.txt"
        MEMO_MID = "memo_mid.txt"
        MEMO_SHORT = "memo_short.txt"

        def load_memo(path):
                if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                                return f.read()
                return ""

        def save_memo(path, content):
                with open(path, "w", encoding="utf-8") as f:
                        f.write(content)

        # 1️⃣ 장기보존 메모 - 가로 전체
        st.markdown("### 📌 장기보존 메모")
        memo_long = st.text_area("🗂️ 장기보존 내용", value=load_memo(MEMO_LONG), height=200, key="memo_long")
        if st.button("💾 장기메모 저장"):
                save_memo(MEMO_LONG, memo_long)
                st.success("✅ 장기보존 메모가 저장되었습니다.")

        # 2️⃣ 중기/단기 메모 - 세로 양쪽 분할
        col_left, col_right = st.columns(2)

        with col_left:
                st.markdown("### 🗓️ 중기 메모")
                memo_mid = st.text_area("📘 중기메모", value=load_memo(MEMO_MID), height=300, key="memo_mid")
                if st.button("💾 중기메모 저장"):
                        save_memo(MEMO_MID, memo_mid)
                        st.success("✅ 중기메모가 저장되었습니다.")

        with col_right:
                st.markdown("### 📅 단기 메모")
                memo_short = st.text_area("📗 단기메모", value=load_memo(MEMO_SHORT), height=300, key="memo_short")
                if st.button("💾 단기메모 저장"):
                        save_memo(MEMO_SHORT, memo_short)
                        st.success("✅ 단기메모가 저장되었습니다.")


    elif current_page == "reference":
        st.subheader("📚 업무참고")
        st.info("이 페이지는 업무 참고 자료를 표시할 수 있는 영역입니다.")

    elif current_page == "home":

        def load_events():
            if os.path.exists(EVENT_FILE):
                with open(EVENT_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}

        def save_events(events):
            with open(EVENT_FILE, 'w', encoding='utf-8') as f:
                json.dump(events, f, ensure_ascii=False)

        events = load_events()

        col_left, col_right = st.columns([1, 1])
        
        with col_left:
            st.subheader("1. 📅 일정 달력")
        
            # 👇 왼쪽 반 화면의 한 줄을 다시 반으로 나눔
            col_year, col_month = st.columns([1, 1])
        
            today = datetime.date.today()
            year_options = list(range(today.year - 5, today.year + 5))
        
            with col_year:
                selected_year = st.selectbox(
                    "📅 연도 선택", 
                    options=year_options,
                    index=year_options.index(today.year),
                    format_func=lambda x: f"{x}년",
                    label_visibility="collapsed"  # 라벨 숨기기 옵션 (선택사항)
                )

            with col_month:
                selected_month = st.selectbox(
                    "📆 달 선택", 
                    options=range(1, 13), 
                    index=today.month - 1, 
                    format_func=lambda x: f"{x}월",
                    label_visibility="collapsed"  # 라벨 숨기기 옵션 (선택사항)
                )


            calendar_obj = calendar.Calendar(firstweekday=6)
            month_days = calendar_obj.monthdayscalendar(selected_year, selected_month)

            day_labels = ["일", "월", "화", "수", "목", "금", "토"]
            day_cols = st.columns(7)
            for i, label in enumerate(day_labels):
                day_cols[i].markdown(f"<h5 style='text-align:center;'>{label}</h5>", unsafe_allow_html=True)

            for week in month_days:
                cols = st.columns([1,1,1,1,1,1,1])
                for i, day in enumerate(week):
                    if day == 0:
                        cols[i].markdown(" ")
                    else:
                        date_obj = datetime.date(selected_year, selected_month, day)
                        is_today = (date_obj == today)
                        has_event = str(date_obj) in events
                        button_label = f"{day}"
                        button_style = ""
                        if is_today:
                            button_style += "🟢"
                        elif has_event:
                            button_style += "🔴"
                        if cols[i].button(f"{button_style} {button_label}", key=f"day-{day}-{i}", use_container_width=True):
                            st.session_state["selected_date"] = date_obj

            selected_date = st.session_state.get("selected_date") or st.session_state.get("__last_selected_date__") or today
            st.markdown(f"**📅 선택한 날짜: {selected_date}**")

            existing_events = events.get(str(selected_date), [])
            if existing_events:
                st.write("기존 일정:")
                for idx, e in enumerate(existing_events):
                    col_a, col_b = st.columns([8, 2])
                    with col_a:
                        st.write(f"{idx + 1}. {e}")
                    with col_b:
                        if st.button("삭제", key=f"delete-{idx}"):
                            events[str(selected_date)].pop(idx)
                            if not events[str(selected_date)]:
                                del events[str(selected_date)]
                            save_events(events)
                            st.session_state["__last_selected_date__"] = selected_date
                            st.rerun()
            
            event_text = st.text_input("일정 입력", "")
            if st.button("일정 저장"):
                date_str = str(selected_date)
                if date_str in events:
                    events[date_str].append(event_text)
                else:
                    events[date_str] = [event_text]
                save_events(events)
                st.session_state["__last_selected_date__"] = selected_date
                st.rerun()

            col1, col2 = st.columns(2)
            with col1:
                st.subheader("📌 오늘 일정")
                today_str = str(datetime.date.today())
                if today_str in events:
                    for e in events[today_str]:
                        st.write("-", e)
                else:
                    st.write("(일정 없음)")
            with col2:
                st.subheader("🕒 내일 일정")
                tomorrow_str = str(datetime.date.today() + datetime.timedelta(days=1))
                if tomorrow_str in events:
                    for e in events[tomorrow_str]:
                        st.write("-", e)
                else:
                    st.write("(일정 없음)")

        def format_phone_number(row):
            parts = []
            for i in [4, 5, 6]:
                val = row[i]
                if pd.isna(val):
                    val = ''
                else:
                    val = str(val).split('.')[0].zfill(4 if i != 4 else 3)
                parts.append(val)
            return f"{parts[0]} {parts[1]} {parts[2]}"

        def load_customer_data():
            df = get_google_sheet_df()
            df['여권만기일'] = pd.to_datetime(df['만기일'], errors='coerce').dt.date
            df['등록증만기일'] = pd.to_datetime(df['만기'], errors='coerce').dt.date
            df['한글이름'] = df['한글']
            df['영문이름'] = df['성'].fillna('') + ' ' + df['명'].fillna('')
            df['전화번호'] = df['연'].astype(str).str.zfill(3) + ' ' + df['락'].astype(str).str.zfill(4) + ' ' + df['처'].astype(str).str.zfill(4)
            df['생년월일'] = df['등록증'].astype(str).str.zfill(6).apply(lambda x: ('19' if x[0] in '456789' else '20') + x)
            df['여권번호'] = df['여권'].astype(str).str.strip()

            today_dt = pd.to_datetime(datetime.date.today())
            passport_alert = df[pd.to_datetime(df['여권만기일']) <= today_dt + pd.DateOffset(months=6)]
            card_alert = df[pd.to_datetime(df['등록증만기일']) <= today_dt + pd.DateOffset(months=4)]

            st.subheader("2. 🛂 여권 만기 6개월 이내 고객")
            if not passport_alert.empty:
                st.dataframe(passport_alert[['한글이름', '여권만기일', '여권번호', '생년월일', '전화번호']])
            else:
                st.write("(표시할 고객 없음)")

            st.subheader("3. 🪪 등록증 만기 4개월 이내 고객")
            if not card_alert.empty:
                st.dataframe(card_alert[['한글이름', '등록증만기일', '여권번호', '생년월일', '전화번호']])
            else:
                st.write("(표시할 고객 없음)")

        with col_right:
            load_customer_data()

        # 예정업무 / 진행업무 코드 이어서 작성 가능

        st.markdown("---")
        st.subheader("4. 📌 예정업무")
        예정업무_FILE = "planned_tasks.json"
        기간_옵션 = ["장기🟢", "중기🟡", "단기🔴"]
        기간_우선순위 = {k: i for i, k in enumerate(기간_옵션)}
        def load_planned():
            if os.path.exists(예정업무_FILE):
                with open(예정업무_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []

        def save_planned(data):
            with open(예정업무_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

        planned_data = load_planned()
        planned_data.sort(key=lambda x: 기간_우선순위.get(x["period"], len(기간_옵션)))

        for idx, row in enumerate(planned_data):
            c1, c2, c3, c4, c5, c6 = st.columns([0.8, 1, 4, 2, 0.5, 0.5])
            new_period = c1.text_input(label=" ", value=row["period"], key=f"plan_period_{idx}", label_visibility="collapsed")
            new_date = c2.text_input(label=" ", value=row["date"], key=f"plan_date_{idx}", label_visibility="collapsed")
            new_content = c3.text_input(label=" ", value=row["content"], key=f"plan_content_{idx}", label_visibility="collapsed")
            new_note = c4.text_input(label=" ", value=row["note"], key=f"plan_note_{idx}", label_visibility="collapsed")
            if c5.button("수정", key=f"edit_plan_{idx}"):
                planned_data[idx] = {
                    "id": row["id"],
                    "date": new_date,
                    "period": new_period,
                    "content": new_content,
                    "note": new_note
                }
                save_planned(planned_data)
                st.rerun()
            if c6.button("❌", key=f"delete_plan_{idx}"):
                planned_data.pop(idx)
                save_planned(planned_data)
                st.rerun()

        with st.form("add_planned_form"):
            p1, p2, p3, p4, p5 = st.columns([0.8, 1, 3, 2, 1])
            new_period = p1.selectbox("기간", options=기간_옵션, key="planned_period")
            new_date = p2.date_input("날짜", key="planned_date")
            new_content = p3.text_input("내용", key="planned_content")
            new_note = p4.text_input("비고", key="planned_note")

            with p5:
                submitted = st.form_submit_button("➕ 예정업무 추가")

            if submitted:
                planned_data.append({
                    "id": str(uuid.uuid4()),
                    "date": str(new_date),
                    "period": new_period,
                    "content": new_content,
                    "note": new_note
                })
                save_planned(planned_data)
                st.success("추가 완료!")
                st.rerun()

        st.markdown("---")
        st.subheader("5. 🛠️ 진행업무")
        진행업무_FILE = "active_tasks.json"
        구분_옵션 = ["출입국", "전자", "공증", "여권", "초청", "기타", "영주권"]
        구분_우선순위 = {k: i for i, k in enumerate(구분_옵션)}

        def load_active():
            if os.path.exists(진행업무_FILE):
                with open(진행업무_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            return []

        def save_active(data):
            with open(진행업무_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

        active_data = load_active()

        active_data.sort(key=lambda x: 구분_우선순위.get(x["category"].split(" - ")[0], len(구분_옵션)))

        for idx, row in enumerate(active_data):
            c1, c2, c3, c4, c5, c6, c7 = st.columns([0.8, 1, 1, 1, 4, 0.5, 0.5])
            new_category = c1.text_input(label=" ", value=row["category"], key=f"cat_{idx}", label_visibility="collapsed")
            new_date = c2.text_input(label=" ", value=row["date"], key=f"date_{idx}", label_visibility="collapsed")
            new_name = c3.text_input(label=" ", value=row["name"], key=f"name_{idx}", label_visibility="collapsed")
            new_work = c4.text_input(label=" ", value=row["work"], key=f"work_{idx}", label_visibility="collapsed")
            new_details = c5.text_input(label=" ", value=row["details"], key=f"details_{idx}", label_visibility="collapsed")
            if c6.button("수정", key=f"edit_active_{idx}"):
                active_data[idx] = {
                    "id": row["id"],
                    "category": new_category,
                    "date": new_date,
                    "name": new_name,
                    "work": new_work,
                    "details": new_details
                }
                save_active(active_data)
                st.rerun()
            if c7.button("❌", key=f"delete_active_{idx}"):
                active_data.pop(idx)
                save_active(active_data)
                st.rerun()

        with st.form("add_active_form"):
            a1, a2, a3, a4, a5, a6 = st.columns([0.8, 1, 1, 1, 3, 1])
            new_category = a1.selectbox("구분", options=구분_옵션, key="category")
            new_date = a2.date_input("진행일", key="active_date")
            new_name = a3.text_input("성명", key="active_name")
            new_work = a4.text_input("업무", key="active_work")
            new_details = a5.text_input("내용", key="active_detail")

            if new_category == "기타":
                extra_input = st.text_input("기타 입력 내용", key="extra_category")
                new_category += f" - {extra_input}"

            with a6:
                submitted = st.form_submit_button("➕ 진행업무 추가")

            if submitted:
                active_data.append({
                    "id": str(uuid.uuid4()),
                    "category": new_category,
                    "date": str(new_date),
                    "name": new_name,
                    "work": new_work,
                    "details": new_details
                })
                save_active(active_data)
                st.success("추가 완료!")
                st.rerun()
