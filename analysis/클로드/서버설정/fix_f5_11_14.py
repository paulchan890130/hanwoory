"""
F-5-11, F-5-14 DB 수정
- M1-0368 (F-5-11): 점수제→특정분야 능력소유자 (과학·경영·교육·문화예술·체육)
- M1-0369 (F-5-14): 5년 합법체류→방문취업(H-2) 제조업 등 4년 이상 근무자
출처: 260310 체류민원 자격별 안내 매뉴얼.pdf (pp.424-426, pp.547-548)
"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")

db_path = r"C:\Users\윤찬\K.ID soft\backend\data\immigration_guidelines_db_v2.json"
with open(db_path, encoding="utf-8") as f:
    db = json.load(f)
rows = db["master_rows"]

FIXES = {
    "M1-0368": {
        "business_name": "특정분야 능력소유자",
        "detailed_code": "F-5-11",
        "overview_short": (
            "과학·경영·교육·문화예술·체육 등 특정 분야에서 탁월한 능력이 있는 사람으로서 "
            "법무부장관이 인정하는 외국인의 영주(F-5-11) 자격 변경 (별도 지침 적용)"
        ),
        "supporting_docs": (
            "여권 | 외국인등록증 | 탁월한 능력 입증서류(수상실적·업적증명·관련기관 추천서 등) | "
            "납세사실증명 | 국내외 범죄경력 증명서"
        ),
        "exceptions_summary": (
            "별도 지침 적용 | 법무부장관이 인정하는 탁월한 능력 소유 여부가 핵심 심사 기준 | "
            "분야별 세부 인정 요건은 출입국·외국인정책본부 지침 참조"
        ),
    },
    "M1-0369": {
        "business_name": "방문취업자(H-2) 제조업 등 4년 이상 근무자",
        "detailed_code": "F-5-14",
        "overview_short": (
            "방문취업(H-2) 자격으로 제조업·농·축산업·어업·간병인·기사보조인으로 "
            "동일업체에서 4년 이상 계속 근무한 외국인의 영주(F-5-14) 자격 변경 (별도 지침 적용)"
        ),
        "supporting_docs": (
            "여권 | 외국인등록증 | 재직증명서 또는 고용확인서(동일업체 4년 이상 근무 입증) | "
            "기술·기능 자격증(별첨 18 해당 자격, 해당자) | 소득금액증명원 또는 근로소득원천징수영수증 | "
            "납세사실증명 | 국내외 범죄경력 증명서 | 출입국사실증명"
        ),
        "exceptions_summary": (
            "동일업체 4년 이상 계속 근무 요건 | 재외동포(F-4) 변경자 포함 | "
            "4년 근무 후 완전출국 → 1년 내 재입국 → 동일업체/업종 2년 이상 종사 = 4년으로 인정 | "
            "충족 요건: 기술·기능 자격(별첨 18) 취득 OR 영주자격신청 시 GNI 70% 이상 소득 중 하나 | "
            "별도 지침 적용"
        ),
    },
}

fixed = 0
for r in rows:
    rid = r.get("row_id")
    if rid in FIXES:
        patch = FIXES[rid]
        old_name = r.get("business_name")
        for k, v in patch.items():
            r[k] = v
        fixed += 1
        print(f"  수정: {rid} {patch['detailed_code']} '{old_name}' → '{patch['business_name']}'")

print(f"\n[완료] {fixed}건 수정")

db["갱신일"] = "2026-04-19 (fix F-5-11 F-5-14)"
db["master_rows"] = rows
with open(db_path, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
print(f"저장 완료: {db_path}")
