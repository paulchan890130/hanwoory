"""
누락된 체류자격별 업무 행 추가 스크립트 (v3)
- D-2, D-3, D-4, D-5, D-6, D-7, D-9, D-10, F-2 누락 행 추가
- 출처: 260310 체류민원 자격별 안내 매뉴얼.pdf
"""

import sys, openpyxl, os
sys.stdout.reconfigure(encoding='utf-8')

현재폴더 = os.path.dirname(os.path.abspath(__file__))
엑셀경로 = os.path.join(현재폴더, '..', '정리.xlsx')

BASIS_FILE = "260310 체류민원 자격별 안내 매뉴얼.pdf"

# 추가할 행 목록 (row_id는 M1-0332부터)
NEW_ROWS = [
    # ── D-2 유학 ─────────────────────────────────────────────────────────────
    {
        "row_id": "M1-0332",
        "domain": "체류이민",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "유학",
        "detailed_code": "D-2",
        "overview_short": "유학(D-2) 체류자격으로 변경하는 절차",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서",
        "supporting_docs": "신청서(별지34호) | 여권 및 사본 1부 | 표준규격사진 1매 | 수수료 | 교육기관 사업자등록증(또는 고유번호증) 사본 | 표준입학허가서 | 학력요건 입증서류(재학증명서 또는 최종학력증명서) | 재정능력 입증서류(예금잔고증명 등) | 체류지 입증서류",
        "exceptions_summary": "기술연수(D-3)·계절근로(E-8)·비전문취업(E-9)·선원취업(E-10)·인도적체류허가(G-1-6)·장기기아동(G-1-8,13,14) 제외 기타(G-1)자격 소지자 자격변경 제한 / 단기체류(B·C 계열) 원칙적 변경 제한",
        "fee_rule": "체류자격변경 10만원",
        "basis_file": BASIS_FILE,
        "basis_section": "유학(D-2) > 체류자격 변경허가",
        "status": "active",
    },
    {
        "row_id": "M1-0333",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "유학",
        "detailed_code": "D-2",
        "overview_short": "유학(D-2) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 표준규격사진 1매 | 수수료(우수인증대학 재학생 면제 해당 여부 확인) | 재학(연구생)증명서 또는 등록금납입증명서 | 체류지 입증서류",
        "exceptions_summary": "정부초청장학생(GKS) 수수료 면제 / 우수인증대학 재학생 재정능력 입증서류 제출 불요 / 일반대학 하위과정 유학생 재정능력 입증서류 심사 강화",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 유학(D-2) 외국인등록",
        "status": "active",
    },
    {
        "row_id": "M1-0334",
        "domain": "체류이민",
        "major_action_std": "재입국허가",
        "action_type": "REENTRY",
        "business_name": "유학",
        "detailed_code": "D-2",
        "overview_short": "유학(D-2) 자격 재입국허가 및 면제 안내",
        "form_docs": "통합신청서 | 위임장",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료",
        "exceptions_summary": "외국인등록 유학생이 출국 후 1년 이내 재입국 시 재입국허가 면제 / 체류기간 1년보다 적게 남은 경우 체류기간 범위 내 면제 / 등록 유학생이 1년 이후 2년 이내 재입국 시 복수재입국허가 가능 / 사우디아라비아·이란·리비아 국민도 유학(D-2)은 복수재입국 가능",
        "fee_rule": "단수 3만원 | 복수 5만원",
        "basis_file": BASIS_FILE,
        "basis_section": "재입국허가|260310 체류민원 자격별 안내 매뉴얼 유학(D-2) 재입국허가",
        "status": "active",
    },
    {
        "row_id": "M1-0335",
        "domain": "체류이민",
        "major_action_std": "사증발급인정서",
        "action_type": "VISA_CONFIRM",
        "business_name": "유학",
        "detailed_code": "D-2",
        "overview_short": "유학(D-2) 사증발급인정서 발급 신청",
        "form_docs": "사증발급인정서 신청서 | 위임장",
        "supporting_docs": "표준입학허가서 | 최종학력 입증서류(졸업증명서 등) | 재정능력 입증서류(예금잔고증명, 장학금확인서 등) | 체류비 부담능력 입증서류 | 표준규격사진 1매 | 수수료",
        "exceptions_summary": "GKS 장학생은 유학생정보시스템(FIMS)에 정보확인 된 경우 국립국제교육원 총장이 발급한 '초청장'으로 대체 / 비자심사강화대학(흠·하위대학) 유학생은 한국어능력 요건 강화 적용",
        "fee_rule": "사증발급인정서 수수료 해당",
        "basis_file": BASIS_FILE,
        "basis_section": "사증발급인정서|260310 체류민원 자격별 안내 매뉴얼 유학(D-2) 사증발급인정서",
        "status": "active",
    },

    # ── D-3 기술연수 ─────────────────────────────────────────────────────────
    {
        "row_id": "M1-0336",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "기술연수",
        "detailed_code": "D-3",
        "overview_short": "기술연수(D-3) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 표준규격사진 1매 | 수수료 | 사업자등록증 및 공장등록증(해당자만) | 국내법인 납세증명서 | 산업재해보상보험 또는 보증보험 가입증명서 | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "체류자격 변경 불가 원칙 / 기술연수생은 취업활동 금지 / 연수시간은 원칙적으로 입국일부터 6개월 초과 불가(사무소장 추가 인정 시 2년 이내)",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 기술연수(D-3) 외국인등록",
        "status": "active",
    },
    {
        "row_id": "M1-0337",
        "domain": "체류이민",
        "major_action_std": "재입국허가",
        "action_type": "REENTRY",
        "business_name": "기술연수",
        "detailed_code": "D-3",
        "overview_short": "기술연수(D-3) 자격 재입국허가 및 면제 안내",
        "form_docs": "통합신청서 | 위임장",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료",
        "exceptions_summary": "출국 후 1년 이내 재입국 시 재입국허가 면제 / 체류기간이 1년보다 적게 남은 경우 체류기간 범위 내 면제 / 입국규제·사증발급규제자는 체류 관할 청(사무소·출장소) 방문하여 재입국허가를 받아야 함",
        "fee_rule": "단수 3만원 | 복수 5만원",
        "basis_file": BASIS_FILE,
        "basis_section": "재입국허가|260310 체류민원 자격별 안내 매뉴얼 기술연수(D-3) 재입국허가",
        "status": "active",
    },
    {
        "row_id": "M1-0338",
        "domain": "체류이민",
        "major_action_std": "사증발급인정서",
        "action_type": "VISA_CONFIRM",
        "business_name": "기술연수",
        "detailed_code": "D-3",
        "overview_short": "기술연수(D-3) 사증발급인정서 발급 신청 (해외투자기업 기술연수생 훈령)",
        "form_docs": "사증발급인정서 신청서 | 위임장",
        "supporting_docs": "피초청자가 기술연수생 요건 구비 입증서류 | 연수내용 확인 연수계획서(별첨3) | 초청자의 신원보증서 | 초청업체가 연수허용대상 업체임 입증서류(해외직투자신고서 등) | 연수허용인원 산정 필요 초청업체의 내국인 상시 근로자 수 입증서류",
        "exceptions_summary": "초청자(연수업체 장)가 주소지 관할 출입국·외국인관서에 신청 / 체류기간 6개월 이내의 사증발급인정서 발급 / 입국규제·사증발급규제자는 발급 제한",
        "fee_rule": "사증발급인정서 수수료 해당",
        "basis_file": BASIS_FILE,
        "basis_section": "사증발급인정서|260310 체류민원 자격별 안내 매뉴얼 기술연수(D-3) 사증발급인정서(해외투자기업 기술연수생 훈령)",
        "status": "active",
    },

    # ── D-4 일반연수 ─────────────────────────────────────────────────────────
    {
        "row_id": "M1-0339",
        "domain": "체류이민",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "일반연수",
        "detailed_code": "D-4",
        "overview_short": "일반연수(D-4) 체류자격으로 변경하는 절차",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증(소지자) | 표준규격사진 1매 | 수수료 | 교육기관 사업자등록증(또는 고유번호증) 사본 | 표준입학허가서 | 재정능력입증서류(예금잔고증명 등) | 재학증명서 또는 최종학력입증서류 | 수학계획서",
        "exceptions_summary": "D-4-1(어학연수) → D-4-2(졸업생 일반연수) 자격변경 허용 / 유학(D-2) 자격에 해당하는 교육기관 이외 교육기관이나 기업·단체에서 교육·연수 목적",
        "fee_rule": "체류자격변경 10만원",
        "basis_file": BASIS_FILE,
        "basis_section": "일반연수(D-4) > 체류자격 변경허가",
        "status": "active",
    },
    {
        "row_id": "M1-0340",
        "domain": "체류이민",
        "major_action_std": "체류기간 연장허가",
        "action_type": "EXTEND",
        "business_name": "일반연수",
        "detailed_code": "D-4",
        "overview_short": "일반연수(D-4) 체류기간 연장허가 신청",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서 | 외국인 직업 신고서 | 여권유효기간범위내체류확인서(해당자)",
        "supporting_docs": "여권원본 | 외국인등록증 | 수수료 | 재학증명서·출석확인서 | 성적증명서 | 재정입증서류(예금잔고증명 등) | 체류지 입증서류(임대차계약서, 숙소제공 확인서, 체류기간 만료예고 통지우편물, 공공요금 납부영수증 등)",
        "exceptions_summary": "1회 부여받을 수 있는 체류기간 상한: 2년 / 휴학자 연장 불가 원칙 / D-4-6 우수사설 교육기관 연수생 특례 적용 가능",
        "fee_rule": "기본 6만원",
        "basis_file": BASIS_FILE,
        "basis_section": "일반연수(D-4) > 체류기간 연장허가",
        "status": "active",
    },
    {
        "row_id": "M1-0341",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "일반연수",
        "detailed_code": "D-4",
        "overview_short": "일반연수(D-4) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "여권원본 | 표준규격사진 1매 | 수수료 | 재학증명서 | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "1회 부여받을 수 있는 체류기간 상한: 2년 / 어학연수(D-4-1) 자격 취득일부터 6개월 경과된 경우 회화지도(E-2) 자격의 활동 가능",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 일반연수(D-4) 외국인등록",
        "status": "active",
    },
    {
        "row_id": "M1-0342",
        "domain": "체류이민",
        "major_action_std": "재입국허가",
        "action_type": "REENTRY",
        "business_name": "일반연수",
        "detailed_code": "D-4",
        "overview_short": "일반연수(D-4) 자격 재입국허가 및 면제 안내",
        "form_docs": "통합신청서 | 위임장",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료",
        "exceptions_summary": "출국 후 1년 이내 재입국 시 재입국허가 면제 / 복수재입국허가 가능(사우디아라비아·이란·리비아 제외. 단, 동 국가 국민 중 일반연수(D-4)는 복수재입국 가능) / 체류기간 범위 내에서 면제 적용",
        "fee_rule": "단수 3만원 | 복수 5만원",
        "basis_file": BASIS_FILE,
        "basis_section": "재입국허가|260310 체류민원 자격별 안내 매뉴얼 일반연수(D-4) 재입국허가",
        "status": "active",
    },

    # ── D-5 취재 (REGISTRATION만 누락) ──────────────────────────────────────
    {
        "row_id": "M1-0343",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "취재",
        "detailed_code": "D-5",
        "overview_short": "취재(D-5) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "여권원본 | 표준규격사진 1매 | 수수료 | 지국·지사 설치허가증 또는 사업자등록증 | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "취재(D-5) 자격 체류기간 상한: 2년 / 외국 신문·방송·잡지 기타 보도기관 파견 취재·보도활동 목적",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 취재(D-5) 외국인등록",
        "status": "active",
    },

    # ── D-6 종교 ─────────────────────────────────────────────────────────────
    {
        "row_id": "M1-0344",
        "domain": "체류이민",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "종교",
        "detailed_code": "D-6",
        "overview_short": "종교(D-6) 체류자격으로 변경하는 절차",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료 | 종교단체 설립 관련 서류(설립인가서 또는 사업자등록증) | 파송명령서 또는 재직증명서(파송단체 발행) | 체류지 입증서류",
        "exceptions_summary": "외국의 종교단체 또는 사회복지단체로부터 파견되어 각 종교의 교리를 전파하거나 사회복지 활동 목적 / 영리목적 금지",
        "fee_rule": "체류자격변경 10만원",
        "basis_file": BASIS_FILE,
        "basis_section": "종교(D-6) > 체류자격 변경허가",
        "status": "active",
    },
    {
        "row_id": "M1-0345",
        "domain": "체류이민",
        "major_action_std": "체류기간 연장허가",
        "action_type": "EXTEND",
        "business_name": "종교",
        "detailed_code": "D-6",
        "overview_short": "종교(D-6) 체류기간 연장허가 신청",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서 | 외국인 직업 신고서",
        "supporting_docs": "여권원본 | 외국인등록증 | 수수료 | 재직증명서 또는 파송명령서(파송단체 발행) | 체류지 입증서류(임대차계약서, 숙소제공 확인서, 공공요금 납부영수증 등)",
        "exceptions_summary": "1회 부여받을 수 있는 체류기간 상한: 2년 / 종교단체 또는 사회복지단체 소속 확인 필요",
        "fee_rule": "기본 6만원",
        "basis_file": BASIS_FILE,
        "basis_section": "종교(D-6) > 체류기간 연장허가",
        "status": "active",
    },
    {
        "row_id": "M1-0346",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "종교",
        "detailed_code": "D-6",
        "overview_short": "종교(D-6) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "여권원본 | 표준규격사진 1매 | 수수료 | 종교단체 또는 사회복지단체 설립 관련 서류(설립인가서 등) | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "1회 부여받을 수 있는 체류기간 상한: 2년",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 종교(D-6) 외국인등록",
        "status": "active",
    },
    {
        "row_id": "M1-0347",
        "domain": "체류이민",
        "major_action_std": "재입국허가",
        "action_type": "REENTRY",
        "business_name": "종교",
        "detailed_code": "D-6",
        "overview_short": "종교(D-6) 자격 재입국허가 및 면제 안내",
        "form_docs": "통합신청서 | 위임장",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료",
        "exceptions_summary": "출국 후 1년 이내 재입국 시 재입국허가 면제 / 체류기간 범위 내에서 면제 / 복수재입국허가 가능(사우디아라비아·이란·리비아 제외)",
        "fee_rule": "단수 3만원 | 복수 5만원",
        "basis_file": BASIS_FILE,
        "basis_section": "재입국허가|260310 체류민원 자격별 안내 매뉴얼 종교(D-6) 재입국허가",
        "status": "active",
    },

    # ── D-7 주재 ─────────────────────────────────────────────────────────────
    {
        "row_id": "M1-0348",
        "domain": "체류이민",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "주재",
        "detailed_code": "D-7",
        "overview_short": "주재(D-7) 체류자격으로 변경하는 절차",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료 | 파견명령서(외국 본사 발행) | 재직증명서 | 사업자등록증(외국법자문법무사무소 등록증 해당자만) | 체류지 입증서류",
        "exceptions_summary": "외국의 공공기관·단체 또는 회사의 본사·지사 기타 사업체로부터 파견된 필수 전문인력 / 체류기간 상한: 3년",
        "fee_rule": "체류자격변경 10만원",
        "basis_file": BASIS_FILE,
        "basis_section": "주재(D-7) > 체류자격 변경허가",
        "status": "active",
    },
    {
        "row_id": "M1-0349",
        "domain": "체류이민",
        "major_action_std": "체류기간 연장허가",
        "action_type": "EXTEND",
        "business_name": "주재",
        "detailed_code": "D-7",
        "overview_short": "주재(D-7) 체류기간 연장허가 신청",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서 | 외국인 직업 신고서",
        "supporting_docs": "여권원본 | 외국인등록증 | 수수료 | 파견명령서(외국 본사 발행) | 재직증명서 | 체류지 입증서류(임대차계약서, 숙소제공 확인서, 공공요금 납부영수증 등)",
        "exceptions_summary": "1회 부여받을 수 있는 체류기간 상한: 3년 / 주재 목적의 파견 관계 확인 필요",
        "fee_rule": "기본 6만원",
        "basis_file": BASIS_FILE,
        "basis_section": "주재(D-7) > 체류기간 연장허가",
        "status": "active",
    },
    {
        "row_id": "M1-0350",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "주재",
        "detailed_code": "D-7",
        "overview_short": "주재(D-7) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "여권원본 | 표준규격사진 1매 | 수수료 | 사업자등록증(외국법자문법무사무소 등록증 해당자만) | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "1회 부여받을 수 있는 체류기간 상한: 3년",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 주재(D-7) 외국인등록",
        "status": "active",
    },
    {
        "row_id": "M1-0351",
        "domain": "체류이민",
        "major_action_std": "재입국허가",
        "action_type": "REENTRY",
        "business_name": "주재",
        "detailed_code": "D-7",
        "overview_short": "주재(D-7) 자격 재입국허가 및 면제 안내",
        "form_docs": "통합신청서 | 위임장",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료",
        "exceptions_summary": "출국 후 1년 이내 재입국 시 재입국허가 면제 / 체류기간 범위 내 면제 / 복수재입국허가 가능(사우디아라비아·이란·리비아 제외. 단, D-7은 면제국가 해당: 독일·프랑스·스웨덴·스위스·네덜란드·노르웨이·덴마크·핀란드·벨기에·룩셈부르크·리히텐슈타인·수리남·칠레)",
        "fee_rule": "단수 3만원 | 복수 5만원",
        "basis_file": BASIS_FILE,
        "basis_section": "재입국허가|260310 체류민원 자격별 안내 매뉴얼 주재(D-7) 재입국허가",
        "status": "active",
    },

    # ── D-9 무역경영 (CHANGE만 누락) ─────────────────────────────────────────
    {
        "row_id": "M1-0352",
        "domain": "체류이민",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "무역경영",
        "detailed_code": "D-9",
        "overview_short": "무역경영(D-9) 체류자격으로 변경하는 절차",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서 | 외국인 직업 신고서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료 | 파견명령서(외국본사 발행) 또는 외국본사 재직증명서 | 국내지사설치허가서 또는 국내지점 설치신고서(외화환은행 발행) | 영업실적(수출입실적 등) 증명서 | 개인 납세사실 증명서류 | 체류지 입증서류",
        "exceptions_summary": "외국에서 특정 회사 등에 투자 또는 무역 종사 목적 / 체류기간 상한: 2년 / 무역업 점수제 배점 기준 충족 필요",
        "fee_rule": "체류자격변경 10만원",
        "basis_file": BASIS_FILE,
        "basis_section": "무역경영(D-9) > 체류자격 변경허가",
        "status": "active",
    },

    # ── D-10 구직 (EXTEND, REGISTRATION 누락) ───────────────────────────────
    {
        "row_id": "M1-0353",
        "domain": "체류이민",
        "major_action_std": "체류기간 연장허가",
        "action_type": "EXTEND",
        "business_name": "구직",
        "detailed_code": "D-10",
        "overview_short": "구직(D-10) 체류기간 연장허가 신청",
        "form_docs": "통합신청서 | 위임장 | 업무수행확인서",
        "supporting_docs": "신청서(별지34호) | 여권사본 | 표준규격사진 1매 | 수수료 | 신분증 사본 | 구직활동계획서 | 학위증(졸업증명서, 학위취득증명서도 인정) | 체재비 입증서류(예금잔고증명 등) | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "체류기간 상한: 6개월(최대 2회 연장) / 취업활동 불가(구직활동만 허용) / D-10-1: 교수~전문인력(E-7) 자격에 해당하는 취업 예정자 / D-10-2: 기업투자(D-8) 자격 준비자",
        "fee_rule": "기본 6만원",
        "basis_file": BASIS_FILE,
        "basis_section": "구직(D-10) > 체류기간 연장허가",
        "status": "active",
    },
    {
        "row_id": "M1-0354",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "구직",
        "detailed_code": "D-10",
        "overview_short": "구직(D-10) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 표준규격사진 1매 | 수수료 | 사업자등록증(법인기업인 경우) | 체류지 입증서류(임대차계약서, 숙소제공 확인서 등)",
        "exceptions_summary": "체류기간 상한: 6개월 / 취업활동 불가 / D-10-1: 전문직 구직자 / D-10-2: 기업투자 준비자",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 구직(D-10) 외국인등록",
        "status": "active",
    },

    # ── F-2 거주 (REGISTRATION, REENTRY 누락) ───────────────────────────────
    {
        "row_id": "M1-0355",
        "domain": "체류이민",
        "major_action_std": "외국인등록",
        "action_type": "REGISTRATION",
        "business_name": "거주",
        "detailed_code": "F-2",
        "overview_short": "거주(F-2) 자격 외국인등록 신청",
        "form_docs": "통합신청서 | 위임장 | 외국인 직업 신고서",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 표준규격사진 1매 | 수수료 | 체류지 입증서류(임대차계약서, 부동산등기부등본, 전입신고 관련 서류 등) | (변경유형별 추가서류: 점수제 관련 서류 또는 가족관계 입증서류)",
        "exceptions_summary": "F-2는 영주자격 부여받기 위해 국내 장기체류 목적의 자격 / F-2-99(기타 장기거주) 자격변경 대상: 문화예술(D-1)·취재(D-5)·종교(D-6)·주재(D-7)·기업투자(D-8)·무역경영(D-9)·교수(E-1)·회화지도(E-2)·연구(E-3)·기술지도(E-4)·전문직업(E-5)·특정활동(E-7) 등 5년 이상 합법 체류자",
        "fee_rule": "외국인등록증 발급 3만 5천원",
        "basis_file": BASIS_FILE,
        "basis_section": "외국인등록|260310 체류민원 자격별 안내 매뉴얼 거주(F-2) 외국인등록",
        "status": "active",
    },
    {
        "row_id": "M1-0356",
        "domain": "체류이민",
        "major_action_std": "재입국허가",
        "action_type": "REENTRY",
        "business_name": "거주",
        "detailed_code": "F-2",
        "overview_short": "거주(F-2) 자격 재입국허가 및 면제 안내",
        "form_docs": "통합신청서 | 위임장",
        "supporting_docs": "신청서(별지34호) | 여권원본 | 외국인등록증 | 수수료",
        "exceptions_summary": "출국 후 1년 이내 재입국 시 재입국허가 면제 / 체류기간 범위 내 면제 / 복수재입국허가 가능(사우디아라비아·이란·리비아 제외) / 준법시민교육 대상자: 법령 위반 이력 확인 필요",
        "fee_rule": "단수 3만원 | 복수 5만원",
        "basis_file": BASIS_FILE,
        "basis_section": "재입국허가|260310 체류민원 자격별 안내 매뉴얼 거주(F-2) 재입국허가",
        "status": "active",
    },
]

HEADERS = ['row_id', 'domain', 'major_action_std', 'action_type', 'business_name',
           'detailed_code', 'overview_short', 'form_docs', 'supporting_docs',
           'exceptions_summary', 'fee_rule', 'basis_file', 'basis_section', 'status']


def main():
    print('=' * 60)
    print('  누락 행 추가 스크립트 v3')
    print('=' * 60)

    if not os.path.exists(엑셀경로):
        print(f'[오류] {엑셀경로} 파일 없음')
        return

    print('[1/3] 엑셀 파일 열기...')
    wb = openpyxl.load_workbook(엑셀경로)
    ws = wb['MASTER_ROWS']

    # 기존 row_id 수집 (중복 방지)
    existing_ids = set()
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if v:
            existing_ids.add(str(v))

    print(f'  기존 행 수: {len(existing_ids)}')

    print('[2/3] 새 행 추가...')
    added = 0
    skipped = 0
    for row_data in NEW_ROWS:
        rid = row_data['row_id']
        if rid in existing_ids:
            print(f'  SKIP (중복): {rid}')
            skipped += 1
            continue

        new_row = [row_data.get(h, '') or '' for h in HEADERS]
        ws.append(new_row)
        print(f'  ADD: {rid} | {row_data["detailed_code"]} {row_data["action_type"]}')
        added += 1

    print(f'[3/3] 저장...')
    wb.save(엑셀경로)

    print()
    print(f'  추가: {added}건, 건너뜀(중복): {skipped}건')
    print(f'  저장 완료: {엑셀경로}')
    print()
    print('다음 단계:')
    print('  1. python 엑셀_json_변환.py')
    print('  2. python backend/scripts/migrate_guidelines_v2.py')


if __name__ == '__main__':
    main()
