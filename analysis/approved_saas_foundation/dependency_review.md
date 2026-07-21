# Dependency Review — Approved-SaaS Foundation

`requirements.txt` 각 패키지의 런타임 사용 여부 조사. **이번 작업에서는 안전성이 완전히 입증된 것만 제거**하며, 불확실/표적검증 미완은 유지한다.

## 조사 방법
- 정적 import: `grep -rn "import X" backend`
- 동적 import / subprocess / feature-flag 경로 확인
- Docker build 사용 여부(Dockerfile.combined)

## 결과

| 패키지 | 런타임 사용 | 판정 |
|---|---|---|
| fastapi, uvicorn[standard], python-multipart, python-jose[cryptography] | 핵심 | **유지** |
| SQLAlchemy, psycopg[binary], alembic, pydantic-settings | 핵심 PG | **유지** |
| gspread, google-auth, google-api-python-client | Drive 보조/일부 경로 | **유지**(보수적) |
| pymupdf | PDF 생성/뷰어 | **유지** |
| Pillow, pytesseract | OCR/이미지 | **유지** |
| paddleocr, paddlepaddle | `ocr_service.py` **lazy import**(OmniMRZ) | **유지** — grep 0 아님, lazy 경로 존재. 표적 OCR 테스트 통과 전 제거 금지 |
| requests | 매뉴얼 감지 등 | **유지** |
| apscheduler | 스케줄러 | **유지** |
| holidays | 달력 공휴일 | **유지**(확인 필요시 별도) |
| matplotlib | 차트 — 런타임 라우터 사용 저빈도 | **유지(보류)** — 제거 후보이나 표적검증 필요 |
| PyPDF2 | pymupdf 와 중복 가능 | **유지(보류)** — 사용처 확인 후 별도 PR |
| pandas, openpyxl | 엑셀 일괄추가/추출 | **유지** |
| **streamlit** | 런타임 import **0건**(레거시 UI 제거됨) | **제거 후보** — 이번엔 보류(빌드 표적검증 후) |
| **streamlit-calendar** | 0건 | **제거 후보** — 보류 |
| **streamlit-aggrid** | 0건 | **제거 후보** — 보류 |

## 이번 작업 결정
- **패키지 제거 없음**. 이유: Docker 빌드 표적검증(빌드 성공 + 로그인/OCR/문서 smoke)을 이 세션에서 완주 보장 못 함. requirements 변경은 배포를 깨뜨릴 수 있어 별도 검증 사이클로 분리.
- 안전한 슬림화는 `.dockerignore`(런타임 무영향)로만 수행.

## 향후 안전 제거 절차 (별도 PR 권장)
1. `streamlit`, `streamlit-calendar`, `streamlit-aggrid` 제거 → `docker build` 성공 확인.
2. 컨테이너 기동 → `/health` 200, 로그인, OCR(`/api/scan`), 문서자동작성 smoke 통과 확인.
3. 통과 시에만 커밋. 실패 시 즉시 롤백.
4. (선택) 운영/개발/ocr 의존성 분리: `requirements.txt`(운영 핵심) / `requirements-dev.txt`(pytest 등) / `requirements-ocr.txt`(paddle*) — Dockerfile 이 세 파일을 순차 설치하도록 조정하되 **start 경로가 깨지지 않는 범위**에서만.
