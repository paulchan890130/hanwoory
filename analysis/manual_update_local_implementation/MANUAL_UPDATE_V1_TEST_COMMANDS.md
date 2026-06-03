# Manual Update v1 — 로컬 테스트 명령 모음

모든 명령은 repo 루트(`C:\Users\윤찬\K.ID soft`)에서 `.venv` 활성화 후 실행.
모두 **로컬 dry-run** — 운영 DB/PDF/Sheets 를 건드리지 않는다.

---

## 0. 사전 준비

```bash
# 새 매뉴얼 HWP/HWPX 를 incoming 에 둔다 (파일명에 체류민원/사증민원/수정이력 포함)
#   backend/data/manuals/incoming/
# 현재 incoming 에는 260414 원본 3종이 들어 있음 (same-baseline 테스트용).
```

---

## 1. same-baseline 테스트 (변경 0 확인 · 기본 light 모드)

```bash
# 빠른 단일 라벨 (5페이지, 수 초)
python backend/scripts/manual_update_local.py --version 260414_test_v1 \
    --baseline-version 260414 --label-only revision_history --dry-run

# 전체 3종 (≈1,449페이지 추출, 수 분)
python backend/scripts/manual_update_local.py --version 260414_test_v1 \
    --baseline-version 260414 --dry-run --force
```

기대:
- `changed_page_count = 0`, `manual_ref_candidate_count = 0`
- `pdf_mode = none` (PDF 미생성)
- `backend/data/manuals/staging/260414_test_v1/manifest.json` 존재
- 운영 PDF/DB 무변경

---

## 2. synthetic 한 페이지 변경 테스트 (영향 후보만 · 변경 페이지 PDF만)

```bash
python backend/scripts/manual_update_synthetic_test.py
# (이웃 범위 조정) python backend/scripts/manual_update_synthetic_test.py --neighbor 2
# (PDF 생략) python backend/scripts/manual_update_synthetic_test.py --no-pdf
```

기대:
- residence p.741 1건만 `modified`
- 영향 후보 **2건** (M1-0088, M1-0093) — 365건 전수검토 아님
- `review_pdf_pages/residence/` 에 p0740/p0741/p0742 3장만 생성 (변경 ± 1)
- `rhwp_pdf/` 디렉터리 미생성 (full 아님)

---

## 3. 실제 새 버전 처리 (변경 페이지 검토 PDF 기본 생성)

```bash
# 기본: 텍스트/해시/diff/후보 + (변경 있으면) 변경 페이지 ± 1 검토 PDF
python backend/scripts/manual_update_local.py --version 260620 --baseline-version 260414

# 변경 페이지 PDF 명시 강제
python backend/scripts/manual_update_local.py --version 260620 --changed-pages-pdf

# 변경 페이지 PDF 억제 (diff/후보만)
python backend/scripts/manual_update_local.py --version 260620 --no-changed-pages-pdf

# 이웃 ± 2
python backend/scripts/manual_update_local.py --version 260620 --neighbor 2

# 전체 staging PDF (무거움 — 명시할 때만)
python backend/scripts/manual_update_local.py --version 260620 --full-pdf
```

---

## 4. 엔드포인트 스모크 (admin 토큰 필요)

```bash
# manifest / changed-pages / candidates (JSON)
curl -H "Authorization: Bearer <ADMIN_JWT>" \
  http://localhost:8000/api/guidelines/manual-staging/versions
curl -H "Authorization: Bearer <ADMIN_JWT>" \
  http://localhost:8000/api/guidelines/manual-staging/synthetic_test/manifest
curl -H "Authorization: Bearer <ADMIN_JWT>" \
  http://localhost:8000/api/guidelines/manual-staging/synthetic_test/changed-pages
curl -H "Authorization: Bearer <ADMIN_JWT>" \
  http://localhost:8000/api/guidelines/manual-staging/synthetic_test/candidates

# 변경 페이지 검토 PDF (admin 토큰 query 허용 — iframe 임베드용)
curl -H "Authorization: Bearer <ADMIN_JWT>" \
  "http://localhost:8000/api/guidelines/manual-staging/synthetic_test/residence/review-page/741/pdf" -o p741.pdf

# 음성 케이스
#   invalid label -> 400 / non-existing page -> 404 / invalid version -> 400 /
#   missing version -> 404 / non-admin -> 403 / no auth -> 401
```

---

## 5. 기존 운영 뷰어 회귀 확인 (무변경)

```bash
curl "http://localhost:8000/api/guidelines/manual-pdf/체류민원?token=<JWT>" -o stay.pdf
curl "http://localhost:8000/api/guidelines/manual-pdf/사증민원?token=<JWT>" -o visa.pdf
# 200, 기존 PDF 그대로. sha256 = baseline manifest 값과 동일해야 함.
```

---

## 6. 컴파일/타입 체크

```bash
python -m py_compile backend/scripts/manual_update_local.py \
    backend/scripts/manual_update_synthetic_test.py backend/routers/guidelines.py
cd frontend && npx tsc --noEmit
```
