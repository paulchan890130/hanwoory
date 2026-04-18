"""
종합 DB 수정 스크립트
1. status '정상' → 'active' (7개 행)
2. F-4 EXTEND fee_rule 수정 ('수수료 없음' → '인지세 6만원')
3. F-5 누락 항목 추가 (F-5-1, F-5-6, F-5-10, F-5-11, F-5-14)
"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")

db_path = r"C:\Users\윤찬\K.ID soft\backend\data\immigration_guidelines_db_v2.json"

with open(db_path, encoding="utf-8") as f:
    db = json.load(f)

rows = db["master_rows"]
print(f"[시작] 총 {len(rows)}개 행")

# ── Fix 1: status '정상' → 'active' ──────────────────────────────────────
fixed_status = 0
for r in rows:
    if r.get("status") == "정상":
        r["status"] = "active"
        fixed_status += 1
        print(f"  status 수정: {r['row_id']} {r.get('detailed_code')} {r.get('action_type')}")
print(f"[Fix 1] status 정상 → active: {fixed_status}개 수정")

# ── Fix 2: F-4 EXTEND fee_rule 수정 ──────────────────────────────────────
fixed_fee = 0
for r in rows:
    if str(r.get("detailed_code", "")).startswith("F-4") and r.get("action_type") == "EXTEND":
        old = r.get("fee_rule", "")
        if "수수료 없음" in old:
            r["fee_rule"] = "인지세 6만원"
            fixed_fee += 1
            print(f"  fee 수정: {r['row_id']} {r.get('detailed_code')} | '{old}' → '인지세 6만원'")
print(f"[Fix 2] F-4 EXTEND fee 수정: {fixed_fee}개")

# ── Fix 3: F-5 누락 항목 추가 ────────────────────────────────────────────
BASIS_FILE = "260310 체류민원 자격별 안내 매뉴얼.pdf"

NEW_F5_ROWS = [
    # ── F-5-1: 국민의 배우자·자녀 (5년 이상 합법체류) ──────────────────
    {
        "row_id": "M1-0364",
        "domain": "체류민원",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "국민의 배우자·자녀",
        "detailed_code": "F-5-1",
        "overview_short": "국민의 배우자 또는 그 자녀로서 5년 이상 합법 체류한 외국인의 영주(F-5-1) 자격 변경",
        "form_docs": "통합신청서 | 위임장 | 대행업무수행확인서",
        "supporting_docs": "여권 | 외국인등록증 | 기본증명서(국민 배우자·부모) | 가족관계증명서 | 혼인관계증명서(배우자의 경우) | 건강보험료 납부확인서 | 납세사실증명(소득세·종합소득세) | 출입국사실증명 | 국내외 범죄경력 증명서 | 신원보증서",
        "exceptions_summary": "체류 5년 중 단기사증으로 체류한 기간은 합산 불가 | 위법 체류 이력 있으면 심사 가중 | 보증인 요건은 담당 직원 재량",
        "fee_rule": "인지세 20만원",
        "basis_file": BASIS_FILE,
        "basis_section": "영주(F-5) > F-5-1 국민의 배우자·자녀",
        "status": "active",
        "search_keys": [],
        "quickdoc_category": None,
        "quickdoc_minwon": None,
        "quickdoc_kind": None,
        "quickdoc_detail": None,
    },
    # ── F-5-2: 미성년 자녀 ────────────────────────────────────────────────
    {
        "row_id": "M1-0365",
        "domain": "체류민원",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "미성년 자녀",
        "detailed_code": "F-5-2",
        "overview_short": "국민인 부 또는 모의 미성년 자녀로서 영주(F-5-2) 자격 변경",
        "form_docs": "통합신청서 | 위임장 | 대행업무수행확인서",
        "supporting_docs": "여권 | 기본증명서(국민 부·모) | 가족관계증명서 | 출생증명서(외국 출생 시) | 출입국사실증명",
        "exceptions_summary": "미성년 자녀 본인 신청 가능(국내 출생자 포함) | 부 또는 모 중 1인이 국민이면 가능",
        "fee_rule": "인지세 20만원",
        "basis_file": BASIS_FILE,
        "basis_section": "영주(F-5) > F-5-2 미성년 자녀",
        "status": "active",
        "search_keys": [],
        "quickdoc_category": None,
        "quickdoc_minwon": None,
        "quickdoc_kind": None,
        "quickdoc_detail": None,
    },
    # ── F-5-6: 결혼이민자 (F-6 기반) ────────────────────────────────────
    {
        "row_id": "M1-0366",
        "domain": "체류민원",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "결혼이민자",
        "detailed_code": "F-5-6",
        "overview_short": "결혼이민(F-6) 자격으로 2년 이상 국내 체류한 외국인의 영주(F-5-6) 자격 변경",
        "form_docs": "통합신청서 | 위임장 | 대행업무수행확인서",
        "supporting_docs": "여권 | 외국인등록증 | 기본증명서(국민 배우자) | 가족관계증명서 | 혼인관계증명서 | 건강보험료 납부확인서 | 납세사실증명 | 국내외 범죄경력 증명서 | 사회통합프로그램 이수증(해당자)",
        "exceptions_summary": "배우자 사망·이혼 후에도 자녀 양육 또는 귀책사유 없는 경우 신청 가능 | 사회통합프로그램 이수 시 가점",
        "fee_rule": "인지세 20만원",
        "basis_file": BASIS_FILE,
        "basis_section": "영주(F-5) > F-5-6 결혼이민자",
        "status": "active",
        "search_keys": [],
        "quickdoc_category": None,
        "quickdoc_minwon": None,
        "quickdoc_kind": None,
        "quickdoc_detail": None,
    },
    # ── F-5-10: 재외동포 동포영주 ────────────────────────────────────────
    {
        "row_id": "M1-0367",
        "domain": "체류민원",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "재외동포(동포영주)",
        "detailed_code": "F-5-10",
        "overview_short": "재외동포(F-4) 자격으로 5년 이상 합법 체류한 외국인의 영주(F-5-10 동포영주) 자격 변경",
        "form_docs": "통합신청서 | 위임장 | 대행업무수행확인서",
        "supporting_docs": "여권 | 외국인등록증 | 잔액증명서(1인당 GNI 이상, 금융기관 발행) | 납세사실증명(최근 1년) | 건강보험료 납부확인서(최근 1년) | 출입국사실증명 | 국내외 범죄경력 증명서",
        "exceptions_summary": "F-4 자격으로 5년 중 단기체류·불법체류 기간 제외 | 소득 GNI(1인당 국민총소득) 이상 잔액 증명 필요 | 결격사유(벌금 등) 있으면 심사 가중",
        "fee_rule": "인지세 20만원",
        "basis_file": BASIS_FILE,
        "basis_section": "영주(F-5) > F-5-10 재외동포(동포영주)",
        "status": "active",
        "search_keys": [],
        "quickdoc_category": None,
        "quickdoc_minwon": None,
        "quickdoc_kind": None,
        "quickdoc_detail": None,
    },
    # ── F-5-11: 점수제 우수인재 ───────────────────────────────────────────
    {
        "row_id": "M1-0368",
        "domain": "체류민원",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "점수제 우수인재",
        "detailed_code": "F-5-11",
        "overview_short": "점수제 우수인재 기준(60점 이상)을 충족하는 외국인의 영주(F-5-11) 자격 변경",
        "form_docs": "통합신청서 | 위임장 | 대행업무수행확인서",
        "supporting_docs": "여권 | 외국인등록증 | 점수표(자기평가서) | 학력증명서(해외 학위 시 번역·공증) | 연간소득증명서(근로소득원천징수영수증 또는 소득금액증명원) | 재직증명서 또는 사업자등록증 | 납세사실증명 | 국내외 범죄경력 증명서 | 사회통합프로그램 이수증(가점 적용 시)",
        "exceptions_summary": "점수제 기준표 항목(학력·연봉·나이·국어능력·공헌도 등) 자기 평가 후 합산 60점 이상 요건 | 사회통합프로그램 이수 시 3점 가점",
        "fee_rule": "인지세 20만원",
        "basis_file": BASIS_FILE,
        "basis_section": "영주(F-5) > F-5-11 점수제 우수인재",
        "status": "active",
        "search_keys": [],
        "quickdoc_category": None,
        "quickdoc_minwon": None,
        "quickdoc_kind": None,
        "quickdoc_detail": None,
    },
    # ── F-5-14: 5년 이상 합법체류 일반 ───────────────────────────────────
    {
        "row_id": "M1-0369",
        "domain": "체류민원",
        "major_action_std": "체류자격 변경허가",
        "action_type": "CHANGE",
        "business_name": "5년 이상 합법체류",
        "detailed_code": "F-5-14",
        "overview_short": "5년 이상 합법 체류 후 소득·자산 요건을 충족한 일반 외국인의 영주(F-5-14) 자격 변경",
        "form_docs": "통합신청서 | 위임장 | 대행업무수행확인서",
        "supporting_docs": "여권 | 외국인등록증 | 출입국사실증명 | 납세사실증명(최근 1년) | 소득금액증명원 또는 근로소득원천징수영수증 | 잔액증명서(3억원 이상, 본인 소유 부동산 시 등기부등본 대체) | 건강보험료 납부확인서 | 국내외 범죄경력 증명서",
        "exceptions_summary": "소득 조건: 전년도 1인당 GNI 이상 | 자산 조건: 3억원 이상(부동산·예금 합산) | 5년 중 불법 체류 기간 제외 | 심사 재량으로 추가 서류 요청 가능",
        "fee_rule": "인지세 20만원",
        "basis_file": BASIS_FILE,
        "basis_section": "영주(F-5) > F-5-14 5년 이상 합법체류",
        "status": "active",
        "search_keys": [],
        "quickdoc_category": None,
        "quickdoc_minwon": None,
        "quickdoc_kind": None,
        "quickdoc_detail": None,
    },
]

# 기존 row_id 중복 체크
existing_ids = {r["row_id"] for r in rows}
added = 0
for new_row in NEW_F5_ROWS:
    if new_row["row_id"] in existing_ids:
        print(f"  [SKIP] {new_row['row_id']} 이미 존재")
    else:
        rows.append(new_row)
        added += 1
        print(f"  [ADD] {new_row['row_id']} {new_row['detailed_code']} {new_row['business_name']}")

print(f"[Fix 3] F-5 행 추가: {added}개")

# ── 저장 ──────────────────────────────────────────────────────────────────
# 통계 업데이트
db["통계"]["업무항목"] = len(rows)
db["갱신일"] = "2026-04-19 (comprehensive fix)"

db["master_rows"] = rows
with open(db_path, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=None, separators=(",", ":"))

print(f"\n[완료] 총 {len(rows)}개 행으로 저장: {db_path}")
