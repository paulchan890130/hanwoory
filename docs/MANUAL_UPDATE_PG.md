# Manual Update v1 — PostgreSQL 단일 출처 운영 가이드

매뉴얼 자동 업데이트의 baseline / 변경결과 / 검토 decision / 상태를 **PostgreSQL** 에 저장한다.
HWP/HWPX 원본은 `/tmp` 에 임시 다운로드 후 분석이 끝나면 삭제한다. 운영 manual_ref
(`backend/data/immigration_guidelines_db_v2.json`)는 **자동 반영하지 않는다** — 관리자가
검토 후 explicit apply 로만 반영한다.

## 구성 요소

| 구분 | 위치 |
|---|---|
| 모델(10테이블) | `backend/db/models/manual_update.py` |
| 마이그레이션 | `alembic/versions/c0ffee004ab1_0004_manual_update_tables.py` |
| PG 서비스 | `backend/services/manual_update_pg_service.py` |
| baseline 적재 CLI | `backend/scripts/manual_baseline_load.py` |
| 자동 파이프라인 entry | `backend/services/manual_auto_update.py` (`run_auto_update_pg`, `--pg`) |
| admin 조회 API | `backend/routers/guidelines.py` (`/api/guidelines/manual-update/*`) |

## 환경변수

| 변수 | 기본 | 용도 |
|---|---|---|
| `DATABASE_URL` | (Render 주입) | PostgreSQL 연결 |
| `FEATURE_PG_MANUAL_UPDATE` | `false` | manual update 저장/조회를 PG 로(단일 출처). off 면 파일 fallback |
| `FEATURE_MANUAL_AUTO_UPDATE` | `false` | web 내부 스케줄러 활성(폴백용). 운영 기본 OFF |
| `MANUAL_AUTO_UPDATE_HOUR_KST` | `15` | web 스케줄러 실행 시각(KST) |

> `FEATURE_PG_MANUAL_UPDATE` = "어디에 저장/조회하나"(PG vs 파일),
> `FEATURE_MANUAL_AUTO_UPDATE` = "web 인스턴스가 스스로 돌리나"(cron 대안). 둘은 별개다.

## 1회 baseline 적재 (배포 후 최초 1회)

```bash
# 미리보기 (DB 미적재)
python -m backend.scripts.manual_baseline_load --baseline-version 260414

# 실제 적재 (PG 필요)
DATABASE_URL=... FEATURE_PG_MANUAL_UPDATE=true \
  python -m backend.scripts.manual_baseline_load --baseline-version 260414 --commit
```

- `manual_base_pages` ← 기존 baseline rhwp JSONL
- `manual_base_refs` ← `immigration_guidelines_db_v2.json` (읽기 전용 미러)

## 매일 15:00 KST 자동 실행 — Render Cron Job (1차, 권장)

PG 가 공유 저장소이므로 **별도 Cron 인스턴스**가 써도 web 이 즉시 읽는다.
(Persistent Disk 불필요. cron 의 ephemeral FS 는 `/tmp` 만 사용.)

Render Dashboard → **Cron Job** 생성:

- **Schedule**: `0 6 * * *`  (06:00 UTC = 15:00 KST, KST 는 DST 없음)
- **Image/Command**: 본 레포 이미지(`Dockerfile.combined`) 기준
  ```
  python -m backend.services.manual_auto_update --pg
  ```
- **Environment**: `DATABASE_URL`, `FEATURE_PG_MANUAL_UPDATE=true` (web 서비스와 동일 DB)
- 이미지에는 이미 Node + `tools/rhwp_manual_pipeline` 의존성(`npm ci`)이 포함되어 있어
  extract/diff 가 chromium 없이 동작한다. **검토 PDF/chromium 은 설치하지 않는다.**

흐름: 변경 확인 → (변경 시) `/tmp/manual_update/{version}/` 다운로드 → rhwp extract →
PG baseline diff → `manual_update_versions/changed_pages/candidates` 저장 →
decision 병합(직전 version 까지만, orphaned 1회/2세대 archive) → `/tmp` 삭제.

중복 실행 방지: `manual_update_state` 단일행 `SELECT … FOR UPDATE` 행 잠금 +
같은 KST 날짜 재실행 차단(today-guard).

## web 스케줄러 (fallback, 운영 기본 OFF)

Cron 을 못 쓰는 환경에서만:
```
FEATURE_MANUAL_AUTO_UPDATE=true
FEATURE_PG_MANUAL_UPDATE=true
```
→ web lifespan 의 스케줄러가 매일 15:00 KST 에 `scheduled_job()` 실행(PG 경로로 분기).
**운영 권장 구성: Cron Job ON + web scheduler OFF.**

## admin 조회 API (require_admin)

```
GET /api/guidelines/manual-update/state
GET /api/guidelines/manual-update/versions
GET /api/guidelines/manual-update/versions/{version}/changed-pages
GET /api/guidelines/manual-update/versions/{version}/candidates
GET /api/guidelines/manual-update/decisions/active
```

`FEATURE_PG_MANUAL_UPDATE=true` → PG, `false` → 기존 파일 staging fallback.
`decisions/active` 는 **현재 유효 + 이번 version 에서 막 orphaned 된 1회분**만 반환하며,
archive(2세대 orphaned)와 과거 orphaned 는 제외한다.

## decision 보존 규칙(요약)

- `manual_review_decisions` = row_id 당 1행(현재 유효본). **직전 version 까지만** 병합.
- 새 version 에 row_id 있으면 사람 결정 보존(+ `previous_decision_snapshot` 에 직전값 1개).
- 후보 page 변동 → `candidate_changed=True, needs_recheck=True`.
- 직전엔 있고 이번엔 없는 row_id → `orphaned=True, orphaned_at=version` (active 1회 표시).
- 이미 orphaned 였고 이번에도 없으면 → `manual_review_decisions_archive` 로 이동, active 제거.
- archive 는 자동 병합 대상으로 다시 끌어오지 않는다.

## 안전장치

- `DATABASE_URL` 미설정 또는 `FEATURE_PG_MANUAL_UPDATE=off` → 모든 PG 함수 no-op/skip.
- 운영 PDF 뷰어(`/api/guidelines/manual-pdf/{manual}`)는 무변경(파일 서빙 유지).
- `/apply`·운영 manual_ref 자동 반영 없음. immigration DB 자동 수정 없음.
- 마이그레이션은 additive create-only. 배포 시 수동 `alembic upgrade head`.
