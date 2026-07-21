# Slimming Baseline — Approved-SaaS Foundation

실측 기준 커밋 `ba7cdbcf` (feat/approved-saas-foundation).

## Docker build context 실측 (git-tracked + 미제외 파일)

| 경로 | 크기 | 이미지 포함(현재) | 조치 |
|---|---|---|---|
| `analysis/` | 1.8 GB | ❌ 이미 `.dockerignore` | 유지(제외) |
| `backend/data/manuals` | 504 MB | ✅ 포함 | **부분만 조치** — `unlocked_*.pdf`(런타임 뷰어) 유지, `staging/`은 admin staging 탭이 읽음 → 유지 |
| `backend/data/backups` | 29 MB | ✅ 포함(root `backups`만 제외돼 있었음) | **제외 추가** (런타임 미참조 확인) |
| `templates/` | 23 MB | ✅ 포함 | 유지(HWPX 런타임) |
| `tools/` | 18 MB | ✅ 포함 | 유지(rhwp 파이프라인, node-gated) |
| `backend/data/*.backup-*.json` | ~2 MB | ✅ 포함 | **제외 추가** |
| `docs/` | 536 KB | ✅ 포함 | **제외 추가**(런타임 미참조) |
| `frontend/dev-trace.log` | 2 KB | ✅ 포함 | **제외 + gitignore** |
| `frontend/tsconfig.tsbuildinfo` | ~110 KB | ✅ 포함 | **제외 + gitignore** |

## requirements
- `requirements.txt`: 27줄 / 약 24 패키지.
- 런타임 import 실측: `streamlit`/`streamlit-calendar`/`streamlit-aggrid` = backend 런타임 import **0건**(레거시 `pages/`·`app.py` 제거됨). → 제거 후보(단, 표적 빌드검증 전 제거 보류 — `dependency_review.md`).

## 이번 작업의 슬림화 범위 (안전·검증가능한 것만)
1. `.dockerignore` 확장 — 위 "제외 추가" 항목. **런타임 파일 미포함 → 앱 동작 불변**(빌드 컨텍스트만 축소).
2. `frontend/dev-trace.log`, `frontend/tsconfig.tsbuildinfo` gitignore(빌드 산출물/트레이스).
3. 의존성 실제 제거는 **보류**(Docker 빌드 표적검증을 이 세션에서 완주 못 하면 requirements 변경이 배포를 깨뜨릴 수 있어). `dependency_review.md` 에 근거·명령만 기록.

## 제외하면 안 되는 런타임 자산 (재확인)
- `backend/data/manuals/unlocked_*.pdf` — 운영 PDF 뷰어 최종 fallback.
- `backend/data/immigration_guidelines_db_v2.json`, `backend/data/guidelines_v3/*`, `backend/data/addr_index.json` — 모듈 import 시 로드.
- `templates/**` — HWPX/PDF 생성.
- `alembic/`, `start.sh`, OCR 모델/OmniMRZ 클론 산출물.

## 전후 수치 측정 방법(운영/로컬에서 실행 권장 — 이 세션 미실행 시)
```
# build context 크기(대략)
git ls-files | wc -l
docker build -f Dockerfile.combined -t kid:before .   # 슬림화 전 태그
# .dockerignore 적용 후
docker build -f Dockerfile.combined -t kid:after .
docker image ls | grep kid
```
> Docker 실빌드는 네트워크(OmniMRZ git clone·npm·pip) 의존이 커 이 세션에서 완주 보장 불가. `.dockerignore` 변경은 **런타임 무영향**이므로 빌드 미완주여도 안전. 최종보고에 실행여부 명시.
