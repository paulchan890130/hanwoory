"""
fee_rule 전수 수정
- EXTEND "수수료 없음 (체류기간 연장허가)" → "기본 6만원"
- CHANGE "수수료 없음 (체류자격 변경허가)" → "기본 10만원"
  단 특수 프로그램(K-STAR, 최우수인재, 지역특화형, 난민, H-2) 제외
"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")

db_path = r"C:\Users\윤찬\K.ID soft\backend\data\immigration_guidelines_db_v2.json"
with open(db_path, encoding="utf-8") as f:
    db = json.load(f)
rows = db["master_rows"]

# ── 특수 프로그램 면제 row_id 목록 (CHANGE "수수료 없음" 유지 대상) ──────────
# 최우수인재, K-STAR, 지역특화형, 난민, 방문취업(H-2) 2027 면제 정책
KEEP_FREE_ROW_IDS = {
    # 최우수인재 계열
    "M1-0097",  # D-10-T 최우수인재 구직
    "M1-0099",  # E-7-T 최우수인재 특정활동
    "M1-0094",  # F-2-T 최우수인재 거주
    "M1-0096",  # F-5-T 최우수인재 영주
    "M1-0105",  # F-2 최우수인재 거주의 동반가족
    "M1-0103",  # F-3 최우수인재 구직·특정활동의 동반가족
    # K-STAR 계열
    "M1-0093",  # F-5-S1 K-STAR 영주
    "M1-0102",  # F-5-S2 K-STAR 영주의 동반가족
    "M1-0090",  # F-2-71 K-STAR 거주의 동반가족
    "M1-0285",  # F-2-7S K-STAR 거주
    # 지역특화형 계열
    "M1-0307",  # E-7-4R 지역특화형 숙련기능인력
    "M1-0281",  # F-2-R 지역특화형 우수인재
    "M1-0283",  # F-3-1R 지역특화형 우수인재가족
    "M1-0087",  # F-3-2R 지역동포가족
    "M1-0284",  # F-3-3R 지역특화형 숙련기능인력가족
    "M1-0086",  # F-4-R 지역특화형 재외동포
    # 특수 프로그램
    "M1-0320",  # E-7-S 네거티브방식 전문인력
    "M1-0325",  # E-7-Y 국내성장인력
    # 인도적 / 난민
    "M1-0203",  # F-1-16 난민인정자 가족 방문동거
    "M1-0238",  # F-2-4 난민인정자 거주
    "M1-0287",  # G-1 기타(인도적 체류자)
    # 방문취업 (H-2→F-4 2027.12.31.까지 면제 정책)
    "M1-0276",  # H-2 방문취업 CHANGE
}

fix_extend = 0
fix_change = 0
keep_extend = 0
keep_change = 0

for r in rows:
    at = r.get("action_type", "")
    fee = r.get("fee_rule", "")

    if at == "EXTEND" and fee == "수수료 없음 (체류기간 연장허가)":
        r["fee_rule"] = "기본 6만원"
        fix_extend += 1
        print(f"  EXTEND 수정: {r['row_id']} {r['detailed_code']:12} {r['business_name'][:25]}")

    elif at == "CHANGE" and fee == "수수료 없음 (체류자격 변경허가)":
        if r["row_id"] in KEEP_FREE_ROW_IDS:
            keep_change += 1
        else:
            r["fee_rule"] = "기본 10만원"
            fix_change += 1
            print(f"  CHANGE 수정: {r['row_id']} {r['detailed_code']:12} {r['business_name'][:25]}")

print(f"\n[완료] EXTEND 수정: {fix_extend}건 | CHANGE 수정: {fix_change}건")
print(f"       CHANGE 면제 유지: {keep_change}건")

# 통계 갱신
db["갱신일"] = "2026-04-19 (fee_rule fix)"
db["master_rows"] = rows
with open(db_path, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
print(f"저장 완료: {db_path}")
