"""
종합 DB 수정 스크립트 (2026-04-19)

수정 항목:
1. 가족관계증명서(상세) 오류 수정 (5건)
   - M1-0217, M1-0218, M1-0221: 가족관계증명서(상세) → 가족관계입증서류(출생증명서, 호구부 등)
   - M1-0219, M1-0220: 가족관계증명서(상세) 항목 제거 (이미 가족관계입증서류 포함)
   - 근거: 외국국적동포는 한국 행정기관 발급 가족관계증명서(상세) 발급 불가
     260310 체류민원 자격별 안내 매뉴얼.pdf F-1 방문동거 섹션 참조

2. fee_rule "수수료 면제" → "수수료 없음" 통일 (7건)
   - M1-0050, M1-0295~M1-0300
   - 근거: CLAUDE.md fee_rule 표준 형식 준수

3. OCR 오류 수정 - M1-0009 D-5 취재 CHANGE (form_docs 이중입력+OCR 오류)
   - 근거: 260310 매뉴얼.pdf pp.101-102 D-5 체류자격 변경허가 섹션

4. OCR 오류 수정 - M1-0086 F-4-R 지역특화형 재외동포 CHANGE (supporting_docs 앞부분 누락+끝 쓰레기)
   - 근거: 260310 매뉴얼.pdf pp.533-538 F-4 재외동포 섹션

5. OCR 오류 수정 - M1-0261 F-4 재외동포 CHANGE (M1-0086과 동일한 OCR 오류)
   - 근거: 동상
"""

import json, sys
sys.stdout.reconfigure(encoding="utf-8")

db_path = r"C:\Users\윤찬\K.ID soft\backend\data\immigration_guidelines_db_v2.json"
with open(db_path, encoding="utf-8") as f:
    db = json.load(f)
rows = db["master_rows"]

# ──────────────────────────────────────────────
# 수정 1: 가족관계증명서(상세) 오류 (5건)
# ──────────────────────────────────────────────
FK_REPLACE = "가족관계증명서(상세)"  # 잘못된 서류명
FK_CORRECT = "가족관계입증서류(출생증명서, 호구부 등)"  # 외국국적동포용 대체 서류

# M1-0217, M1-0218, M1-0221: 단순 교체
SIMPLE_FK_REPLACE = {"M1-0217", "M1-0218", "M1-0221"}

# M1-0219, M1-0220: 이미 '가족관계입증서류' 있으므로 가족관계증명서(상세) 만 제거
REMOVE_FK = {"M1-0219", "M1-0220"}

# ──────────────────────────────────────────────
# 수정 2: fee_rule 표기 통일
# ──────────────────────────────────────────────
FEE_REPLACE_ROWS = {"M1-0050", "M1-0295", "M1-0296", "M1-0297", "M1-0298", "M1-0299", "M1-0300"}

# ──────────────────────────────────────────────
# 수정 3: OCR 오류 - M1-0009 D-5 취재 CHANGE
# ──────────────────────────────────────────────
D5_FORM_DOCS_CORRECT = "통합신청서 | 위임장"

D5_SUPPORTING_DOCS_CORRECT = (
    "여권(사증면제로 입국한 독일인) | "
    "증명사진 1장(최근 6개월이내 배경흰색)(사증면제로 입국한 독일인) | "
    "파견명령서(사증면제로 입국한 독일인) | "
    "지사설치허가증(사증면제로 입국한 독일인) | "
    "사업자등록증(사증면제로 입국한 독일인) | "
    "체류지입증서류(임대차계약서/등기부등본/체류만료통지서 중 택1)(사증면제로 입국한 독일인) | "
    "소득금액증명원(해당자)(사증면제로 입국한 독일인) | "
    "숙소제공자 신분증(본인명의가 아닌 경우)(사증면제로 입국한 독일인) | "
    "결핵진단서(신청일기준 1년이내 연속으로 6개월이상 결핵고위험 국가에 장기체류한 경우)"
)

# ──────────────────────────────────────────────
# 수정 4+5: OCR 오류 - M1-0086, M1-0261 F-4 CHANGE supporting_docs
# ──────────────────────────────────────────────
F4_SUPPORTING_DOCS_CORRECT = (
    "여권 | "
    "거소신고증 또는 외국인등록증(해당자) | "
    "재외동포임을 증명하는 서류(가족관계기록사항 증명서, 제적등본, 호구부, 거민증, 출생증명서 등) | "
    "소득금액증명원 또는 종합소득자과세표준확정신고및납부계산서 또는 거주자사업소득원천징수영수증(해당자) | "
    "결핵진단서(신청일기준 1년이내 연속으로 6개월이상 결핵고위험 국가에 장기체류한 경우, 단기체류자와 타체류자격자 필요) | "
    "체류지입증서류(임대차계약서/등기부등본/체류만료통지서 중 택1) | "
    "숙소제공자 신분증(본인명의가 아닌 경우) | "
    "한국어능력 입증서류(해당자) | "
    "조기적응프로그램 이수증(해당자) 또는 면제자 이수증 "
    "(면제자: 국내 초중고교 재학·졸업자, 만 6세 이하, 만 65세 이상, "
    "장기체류자격 국내 3년이상 체류자, 이전 이수자, 사회통합프로그램 1단계 이상 이수자)"
)

# ──────────────────────────────────────────────
# 적용
# ──────────────────────────────────────────────
fixed = 0

for r in rows:
    rid = r.get("row_id", "")

    # 수정 1a: 단순 교체
    if rid in SIMPLE_FK_REPLACE:
        sd = r.get("supporting_docs", "")
        if FK_REPLACE in sd:
            r["supporting_docs"] = sd.replace(FK_REPLACE, FK_CORRECT)
            print(f"  [FK교체] {rid}: 가족관계증명서(상세) → 가족관계입증서류(출생증명서, 호구부 등)")
            fixed += 1

    # 수정 1b: 가족관계증명서(상세) 항목 제거 (pipe로 구분된 항목 제거)
    elif rid in REMOVE_FK:
        sd = r.get("supporting_docs", "")
        if FK_REPLACE in sd:
            # " | 가족관계증명서(상세)" 또는 "가족관계증명서(상세) | " 패턴 제거
            new_sd = sd.replace(" | " + FK_REPLACE, "").replace(FK_REPLACE + " | ", "")
            if new_sd == sd:  # 패턴 미매칭 시 단순 제거
                new_sd = sd.replace(FK_REPLACE, "").strip(" |")
            r["supporting_docs"] = new_sd
            print(f"  [FK제거] {rid}: 가족관계증명서(상세) 항목 제거")
            fixed += 1

    # 수정 2: fee_rule 표기 통일
    if rid in FEE_REPLACE_ROWS:
        if r.get("fee_rule") == "수수료 면제":
            r["fee_rule"] = "수수료 없음"
            print(f"  [FEE] {rid} {r.get('detailed_code')} {r.get('business_name')}: 수수료 면제 → 수수료 없음")
            fixed += 1

    # 수정 3: M1-0009 D-5 OCR 오류
    if rid == "M1-0009":
        old_fd = r.get("form_docs", "")
        old_sd = r.get("supporting_docs", "")
        r["form_docs"] = D5_FORM_DOCS_CORRECT
        r["supporting_docs"] = D5_SUPPORTING_DOCS_CORRECT
        print(f"  [OCR] M1-0009 D-5: form_docs 이중입력 수정 + supporting_docs OCR 오류 수정")
        fixed += 1

    # 수정 4+5: M1-0086, M1-0261 F-4 supporting_docs OCR 오류
    if rid in ("M1-0086", "M1-0261"):
        r["supporting_docs"] = F4_SUPPORTING_DOCS_CORRECT
        print(f"  [OCR] {rid} {r.get('detailed_code')}: supporting_docs 앞부분 누락+끝 쓰레기 수정")
        fixed += 1

print(f"\n[완료] {fixed}건 수정")

db["갱신일"] = "2026-04-19 (fix comprehensive v1)"
db["master_rows"] = rows
with open(db_path, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
print(f"저장 완료: {db_path}")
