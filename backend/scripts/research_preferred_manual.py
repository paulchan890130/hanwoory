"""
Research Groups A and B — preferred_manual_missing rows.
Group A: 10 VISA_CONFIRM rows needing 사증민원 pages.
Group B: 9 residence rows needing 체류민원 pages.
READ-ONLY. No DB write. No LLM call.
"""
import json, re, sys
from pathlib import Path
import fitz

ROOT = Path(__file__).parent.parent.parent
MANUALS = ROOT / "backend" / "data" / "manuals"
PDF_RES = MANUALS / "unlocked_체류민원.pdf"
PDF_VIS = MANUALS / "unlocked_사증민원.pdf"
OUT_A = MANUALS / "group_a_research.json"
OUT_B = MANUALS / "group_b_research.json"

NORM = [
    (re.compile(r"체류자격\s*부\s*여"), "체류자격부여"),
    (re.compile(r"사증\s*발급\s*인정서"), "사증발급인정서"),
    (re.compile(r"외국인\s*등록"), "외국인등록"),
    (re.compile(r"재입국\s*허가"), "재입국허가"),
    (re.compile(r"체류기간\s*연장"), "체류기간연장"),
    (re.compile(r"체류자격\s*변경"), "체류자격변경"),
    (re.compile(r"근무처\s*변경"), "근무처변경"),
]
def norm(t):
    for p, r in NORM:
        t = p.sub(r, t)
    return re.sub(r"[ \t　]+", " ", t)

def heading(txt, n=4):
    lines = [l.strip() for l in txt.splitlines()
             if l.strip() and not re.match(r"^- \d+ -$", l.strip()) and l.strip() != "목차"]
    return " / ".join(lines[:n])[:200]

def has_artifacts(txt):
    return {
        "req": bool(re.search(r"신청요건|허가요건|허용대상|가\. 대상|나\. 요건|제출서류|필수서류|첨부서류", txt)),
        "doc": bool(re.search(r"제출서류|필수서류|첨부서류|①신청서|①사증발급", txt)),
        "heading_kw": bool(re.search(r"사증발급인정서|사증발급확인서|발급대상|발급 대상|체류기간연장|외국인등록|재입국허가|근무처변경|체류자격변경|체류자격부여", txt[:600])),
    }

def score_page(txt, terms, action_kw_fn):
    arts = has_artifacts(txt)
    s = 0
    if arts["req"]: s += 20
    if arts["doc"]: s += 30
    if arts["heading_kw"]: s += 20
    for t in terms:
        if t in txt[:500]: s += 50; break
        if t in txt: s += 15; break
    if action_kw_fn(txt[:600]): s += 15
    return s

def search_doc(doc, terms, scope_s, scope_e, action_fn, max_hits=8):
    scope_e = min(scope_e, doc.page_count)
    hits = []
    for p in range(scope_s-1, scope_e):
        txt = doc.load_page(p).get_text() or ""
        ntxt = norm(txt)
        matched = any(t in ntxt or t in txt for t in terms)
        if not matched:
            continue
        s = score_page(ntxt, terms, action_fn)
        h = heading(ntxt)
        arts = has_artifacts(ntxt)
        hits.append({"page": p+1, "score": s, "heading": h, **arts})
        if len(hits) >= max_hits:
            break
    hits.sort(key=lambda x: -x["score"])
    return hits[:5]

def conf(s):
    if s >= 70: return "HIGH"
    if s >= 35: return "MEDIUM"
    return "LOW"

def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

    doc_v = fitz.open(str(PDF_VIS))
    doc_r = fitz.open(str(PDF_RES))

    # ── Group A — 사증민원 ─────────────────────────────────────────
    GROUP_A = [
        ("M1-0114","D-8-1","VISA_CONFIRM","법인투자",["D-8-1","법인투자","기업투자(D-8)","사증발급인정서"],95,130),
        ("M1-0115","D-8-2","VISA_CONFIRM","벤처투자",["D-8-2","벤처투자","사증발급인정서"],95,130),
        ("M1-0116","D-8-3","VISA_CONFIRM","개인기업투자",["D-8-3","개인기업투자","사증발급인정서"],95,130),
        ("M1-0132","D-10-3","VISA_CONFIRM","첨단기술인턴",["D-10-3","첨단기술인턴","사증발급인정서"],140,200),
        ("M1-0141","E-1","VISA_CONFIRM","교수",["교수(E-1)","E-1","사증발급인정서"],155,230),
        ("M1-0146","E-2","VISA_CONFIRM","회화지도",["회화지도(E-2)","E-2","사증발급인정서"],155,230),
        ("M1-0151","E-3","VISA_CONFIRM","연구",["연구(E-3)","E-3","사증발급인정서"],160,230),
        ("M1-0161","E-5","VISA_CONFIRM","전문직업",["전문직업(E-5)","E-5","사증발급인정서"],160,235),
        ("M1-0199","E-10","VISA_CONFIRM","선원취업",["선원취업(E-10)","E-10","사증발급인정서"],155,235),
        ("M1-0205","F-1-5","VISA_CONFIRM","결혼이민자의 부모 등 가족 방문동거",["F-1-5","결혼이민자","방문동거","사증발급인정서"],290,330),
    ]
    visa_fn = lambda t: bool(re.search(r"사증발급인정서|발급대상|첨부서류", t))

    results_a = []
    print("=== Group A — 사증민원 ===")
    for rid, code, action, title, terms, s0, s1 in GROUP_A:
        hits = search_doc(doc_v, terms, s0, s1, visa_fn)
        best = hits[0] if hits else None
        c = conf(best["score"]) if best else "NONE"
        print(f"  {rid}  {code:<8}  {action:<14}  page={best['page'] if best else 'N/A':<5}  conf={c:<6}  {(best['heading'][:100] if best else '')}")
        results_a.append({
            "row_id": rid, "detailed_code": code, "action_type": action, "title": title,
            "preferred_manual": "사증민원",
            "found_page": best["page"] if best else None,
            "heading_snippet": best["heading"] if best else "",
            "confidence": c,
            "score": best["score"] if best else 0,
            "top_candidates": hits,
        })

    OUT_A.write_text(json.dumps({"rows": results_a}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OUT] {OUT_A.relative_to(ROOT)}")

    # ── Group B — 체류민원 ─────────────────────────────────────────
    # action-specific heading fns
    def ext_fn(t): return bool(re.search(r"체류기간연장|연장허가|연장 허가", t))
    def chg_fn(t): return bool(re.search(r"체류자격변경|변경허가|변경 허가", t))
    def reg_fn(t): return bool(re.search(r"외국인등록|등록 신청", t))
    def ree_fn(t): return bool(re.search(r"재입국허가|재입국 허가", t))
    def wkp_fn(t): return bool(re.search(r"근무처변경|근무처추가|근무처 변경", t))
    def grt_fn(t): return bool(re.search(r"체류자격부여|자격부여", t))

    GROUP_B = [
        ("M1-0015","E-10-2","WORKPLACE","선원취업",["E-10-2","선원취업","근무처변경","근무처 변경"],328,345,wkp_fn),
        ("M1-0098","D-10-T","EXTEND","최우수인재 구직",["D-10-T","최우수인재","체류기간연장"],150,165,ext_fn),
        ("M1-0134","D-10-2","EXTEND","기술창업준비",["D-10-2","기술창업준비","체류기간연장"],149,165,ext_fn),
        ("M1-0290","H-1","CHANGE","관광취업",["관광취업(H-1)","H-1","체류자격변경"],1,55,chg_fn),
        ("M1-0291","H-1","EXTEND","관광취업",["관광취업(H-1)","H-1","체류기간연장"],1,55,ext_fn),
        ("M1-0292","H-1","REGISTRATION","관광취업",["관광취업(H-1)","H-1","외국인등록"],1,55,reg_fn),
        ("M1-0293","H-1","REENTRY","관광취업",["관광취업(H-1)","H-1","재입국허가"],1,55,ree_fn),
        ("M1-0321","E-7-S","EXTEND","네거티브방식 전문인력",["E-7-S","네거티브","체류기간연장"],285,320,ext_fn),
        ("M1-0324","E-7-S","GRANT","네거티브방식 전문인력",["E-7-S","네거티브","체류자격부여"],285,320,grt_fn),
    ]

    results_b = []
    print("\n=== Group B — 체류민원 ===")
    for rid, code, action, title, terms, s0, s1, action_fn in GROUP_B:
        hits = search_doc(doc_r, terms, s0, s1, action_fn)
        best = hits[0] if hits else None
        c = conf(best["score"]) if best else "NONE"
        print(f"  {rid}  {code:<8}  {action:<14}  page={best['page'] if best else 'N/A':<5}  conf={c:<6}  {(best['heading'][:100] if best else '')}")
        results_b.append({
            "row_id": rid, "detailed_code": code, "action_type": action, "title": title,
            "preferred_manual": "체류민원",
            "found_page": best["page"] if best else None,
            "heading_snippet": best["heading"] if best else "",
            "confidence": c,
            "score": best["score"] if best else 0,
            "top_candidates": hits,
        })

    OUT_B.write_text(json.dumps({"rows": results_b}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OUT] {OUT_B.relative_to(ROOT)}")

    doc_v.close(); doc_r.close()

    # Summary
    all_rows = results_a + results_b
    from collections import Counter
    cc = Counter(r["confidence"] for r in all_rows)
    print(f"\nSummary: HIGH={cc.get('HIGH',0)}  MEDIUM={cc.get('MEDIUM',0)}  LOW={cc.get('LOW',0)}  NONE={cc.get('NONE',0)}")

if __name__ == "__main__":
    main()
