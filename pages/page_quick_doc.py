# pages/page_quick_doc.py
import io
import zipfile
import datetime
import streamlit as st
import fitz  # PyMuPDF

from config import SESS_TENANT_ID, DEFAULT_TENANT_ID

# ✅ 기존 문서엔진 재사용
from pages.page_document import (
    get_account_for_tenant,
    build_field_values,
    make_seal_bytes,
    fill_and_append_pdf,
    calc_is_minor,
    DOC_TEMPLATES,
)

def _pdf_bytes_to_jpg_or_zip(pdf_bytes: bytes, dpi: int = 200):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        n = doc.page_count
        if n <= 0:
            return ("jpg", b"")

        if n == 1:
            pix = doc.load_page(0).get_pixmap(dpi=dpi, alpha=False)
            return ("jpg", pix.tobytes("jpeg"))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i in range(n):
                pix = doc.load_page(i).get_pixmap(dpi=dpi, alpha=False)
                zf.writestr(f"page_{i+1:03d}.jpg", pix.tobytes("jpeg"))
        return ("zip", buf.getvalue())
    finally:
        doc.close()

def render():
    st.subheader("⚡ 위임장 빠른작성 (임시입력 → 도장 포함 → JPG 다운로드)")

    tenant_id = st.session_state.get(SESS_TENANT_ID, DEFAULT_TENANT_ID)
    account = get_account_for_tenant(tenant_id)

    template_path = DOC_TEMPLATES.get("위임장")
    if not template_path:
        st.error("DOC_TEMPLATES에 '위임장' 경로가 없습니다.")
        return

    st.markdown("### 1) 신청인 입력(위임장 맵핑)")
    c1, c2 = st.columns(2, gap="small")

    with c1:
        kor_name = st.text_input("신청인 한글명(도장명)", key="qd_kor_name")
        surname  = st.text_input("영문 성(Surname)", key="qd_surname")
        given    = st.text_input("영문 이름(Given names)", key="qd_given")
        stay_status = st.text_input("체류자격 (예: F-6)", key="qd_stay_status")  # ✅ 템플릿 필드명은 'V'

        reg6     = st.text_input("등록증 앞 6자리(YYMMDD)", key="qd_reg6")
        no7      = st.text_input("등록증 뒤 7자리", key="qd_no7")
        addr     = st.text_input("한국 내 주소", key="qd_addr")

    with c2:
        p1 = st.text_input("전화(연)", key="qd_p1", value="010")
        p2 = st.text_input("전화(락)", key="qd_p2")
        p3 = st.text_input("전화(처)", key="qd_p3")
        passport = st.text_input("여권번호", key="qd_passport")

        d1, d2 = st.columns(2, gap="small")
        with d1:
            apply_applicant_seal = st.checkbox("신청인 도장(yin)", value=True, key="qd_apply_applicant_seal")
        with d2:
            apply_agent_seal = st.checkbox("행정사 도장(ayin)", value=True, key="qd_apply_agent_seal")

        dpi = st.selectbox("JPG 해상도(DPI)", [150, 200, 250, 300], index=1, key="qd_dpi")

    st.markdown("### 2) 위임업무 체크(필요한 것만 선택)")
    # ✅ 템플릿 체크 필드명 확정: extension/registration/card/adrc/change/granting/ant
    t1, t2, t3, t4 = st.columns(4, gap="small")
    with t1:
        ck_extension = st.checkbox("체류기간연장", key="qd_ck_extension")
        ck_registration = st.checkbox("외국인등록(등록증발급)", key="qd_ck_registration")
    with t2:
        ck_card = st.checkbox("등록증재발급", key="qd_ck_card")
        ck_adrc = st.checkbox("체류지변경", key="qd_ck_adrc")
    with t3:
        ck_change = st.checkbox("체류자격 변경허가", key="qd_ck_change")
        ck_granting = st.checkbox("자격부여", key="qd_ck_granting")
    with t4:
        ck_ant = st.checkbox("등록사항변경", key="qd_ck_ant")

    st.markdown("---")

    if st.button("🖨 위임장 생성", type="primary", use_container_width=True):
        if not kor_name.strip():
            st.error("신청인 한글명은 필수.")
            return

        # ✅ build_field_values가 읽는 키에 맞춰 row 구성
        row = {
            "한글": kor_name.strip(),
            "성": surname.strip(),
            "명": given.strip(),
            "V": stay_status.strip(),     # ✅ 체류자격 칸이 'V'
            "등록증": reg6.strip(),
            "번호": no7.strip(),
            "주소": addr.strip(),         # build_field_values -> adress로 들어감
            "연": p1.strip(),
            "락": p2.strip(),
            "처": p3.strip(),
            "여권": passport.strip(),
        }

        is_minor = calc_is_minor(row.get("등록증", ""))

        # ✅ 기본 맵핑 생성(행정사 정보 포함)
        field_values = build_field_values(
            row=row,
            prov=None,
            guardian=None,
            guarantor=None,
            aggregator=None,
            is_minor=is_minor,
            account=account,
            category="체류",
            minwon="기타",  # 자동 체크 로직 안 쓰려고 대충 둠(우리가 아래서 덮어씀)
        )

        # ✅ 날짜(작성년/월/일) 추가
        today = datetime.date.today()
        field_values.update({
            "작성년": str(today.year),
            "월": str(today.month),
            "일": str(today.day),
        })

        # ✅ 위임업무 체크는 “직접” 세팅(이 위임장 템플릿 규칙)
        field_values.update({
            "extension": "V" if ck_extension else "",
            "registration": "V" if ck_registration else "",
            "adrc": "V" if ck_adrc else "",
            "change": "V" if ck_change else "",
            "granting": "V" if ck_granting else "",
            "ant": "V" if ck_ant else "",
        })
        # card는 체크박스 타입이라 on_state 값(실무상 '0')로 체크됨
        # fill_and_append_pdf는 텍스트 필드처럼 값을 넣기 때문에 "0" 넣으면 체크됨
        field_values["card"] = "0" if ck_card else ""

        # ✅ 도장 bytes
        agent_name = (account.get("contact_name", "") if account else "").strip()
        seal_bytes_by_role = {
            "applicant": make_seal_bytes(row["한글"]) if apply_applicant_seal else None,
            "agent": make_seal_bytes(agent_name) if (apply_agent_seal and agent_name) else None,
            "accommodation": None,
            "guarantor": None,
            "guardian": None,
            "aggregator": None,
        }

        merged_doc = fitz.open()
        fill_and_append_pdf(template_path, field_values, seal_bytes_by_role, merged_doc)

        out = io.BytesIO()
        merged_doc.save(out)
        merged_doc.close()
        pdf_bytes = out.getvalue()

        kind, data_bytes = _pdf_bytes_to_jpg_or_zip(pdf_bytes, dpi=int(dpi))
        ymd = today.strftime("%Y%m%d")
        base = f"{ymd}_{row['한글']}_위임장"

        if kind == "jpg":
            st.download_button(
                "📥 JPG 다운로드",
                data=data_bytes,
                file_name=f"{base}.jpg",
                mime="image/jpeg",
                use_container_width=True,
            )
        else:
            st.download_button(
                "📥 JPG ZIP 다운로드",
                data=data_bytes,
                file_name=f"{base}.zip",
                mime="application/zip",
                use_container_width=True,
            )
