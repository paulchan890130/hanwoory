# PHASE 0 — 안전 점검 보고서 (PHASE0_SAFETY_CHECK_REPORT.md)

> **점검일시:** 2026-06-01
> **점검자:** Claude Code (Opus 4.7) — 사용자 위임
> **범위:** Phase 0 비파괴 안전 점검 전용. 코드/설정 무변경, 커밋 없음.
> **PostgreSQL 마이그레이션 계획서:** `POSTGRES_MIGRATION_PLAN.md` 참조

---

## 1. 실행한 명령

PowerShell이 기본 셸이지만, 다중 명령 파이프 / `grep -q` 등을 위해 Bash 도구(POSIX)를 통해 실행했습니다. 모든 명령은 비파괴입니다.

| # | 명령 | 셸 |
|---|---|---|
| 1 | `git status` | Bash |
| 2 | `du -sh .git` | Bash |
| 3 | `git ls-files --error-unmatch <folder>` (8개 폴더 각각) | Bash |
| 4 | `[ -d <folder> ]` 디스크 존재 확인 (8개 폴더 각각) | Bash |
| 5 | `.venv/Scripts/python.exe -m compileall backend -q` | Bash |
| 6 | `cd frontend && npx tsc --noEmit` | Bash |
| 7 | `.venv/Scripts/python.exe -m uvicorn backend.main:app --port 8000` (백그라운드) | Bash |
| 8 | `cd frontend && npm run dev` (백그라운드) | Bash |
| 9 | uvicorn / next 기동 로그 폴링 (until-grep) | Bash |
| 10 | `TaskStop` 으로 두 서버 정상 종료 | 도구 |

> `--reload` 플래그는 의도적으로 생략했습니다. 일회성 기동 확인에서 watcher가 불필요하고 종료가 더 깔끔해서입니다. 일반적인 개발 명령(`uvicorn ... --reload`)은 그대로 사용 가능합니다.

---

## 2. 각 명령의 결과

### 2.1 `git status`
```
On branch main
Your branch is ahead of 'origin/main' by 3 commits.
  (use "git push" to publish your local commits)

Untracked files:
  (use "git add <file>..." to include in what will be committed)
        POSTGRES_MIGRATION_PLAN.md

nothing added to commit but untracked files present
```
* **워킹 트리:** 깨끗함 (수정/스테이지 없음)
* **로컬 ahead:** `origin/main` 대비 3 커밋 앞섬 → push 미진행 상태
* **untracked:** `POSTGRES_MIGRATION_PLAN.md` 1개 (이전 단계에서 생성한 계획서)

### 2.2 `.git` 디렉터리 크기
```
991M    .git
```
* **고위험.** 작업트리 대비 매우 큼. 과거 히스토리에 거대 blob이 남아 있음을 의미. (계획서 §5.2 참조 — `frontend/node_modules` swc-binary 135MB, `샘플/_addr_db_inspect/*.txt` 40~100MB 다수, `analysis/*.pdf`, `.tmp.driveupload/*` 등)

### 2.3 보호 대상 폴더 — 추적 여부

| 폴더 | git 추적 | 디스크 존재 |
|---|---|---|
| `샘플/` | **untracked** ✅ | 존재 |
| `analysis/` | **untracked** ✅ | 존재 |
| `.tmp.driveupload/` | **untracked** ✅ | 존재 |
| `.tmp.drivedownload/` | **untracked** ✅ | 존재 |
| `.venv/` | **untracked** ✅ | 존재 |
| `frontend/node_modules/` | **untracked** ✅ | 존재 |
| `frontend/.next/` | **untracked** ✅ | 존재 |
| `secrets/` | **untracked** ✅ | 존재 |

* 8개 폴더 모두 `.gitignore` 규칙에 의해 **현재 HEAD에서는 추적되지 않음** — 정상.
* 단, **과거 히스토리에 일부 폴더의 거대 파일이 남아 있을 가능성 큼** (§2.2와 계획서 §5.2 참조).

### 2.4 `python -m compileall backend -q`
```
EXIT=0
```
* **백엔드 모든 `.py` 컴파일 성공.** 출력 없음(=`-q` 옵션, 모든 파일 OK).

### 2.5 `npx tsc --noEmit`
```
npm notice New major version of npm available! 10.9.3 -> 11.16.0
EXIT=0
```
* **TypeScript 타입체크 통과.** 에러 0건.
* npm 자체 업데이트 안내(타입체크 결과와 무관)만 표시.

### 2.6 uvicorn 기동 확인
백그라운드로 기동 → 시작 로그 확인 후 `TaskStop`으로 정상 종료.
```
INFO:     Started server process [888]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```
* **기동 성공.** `Application startup complete.` 라인 확인 후 종료.
* `lifespan`의 manual_watcher 스케줄러도 정상 등록되어 있음(예외 메시지 없음).

### 2.7 `npm run dev` 기동 확인
백그라운드로 기동 → 시작 로그 확인 후 `TaskStop`으로 정상 종료.
```
> kid-frontend@2.0.0 dev
> next dev

  ▲ Next.js 14.2.5
  - Local:        http://localhost:3000

 ✓ Starting...
 ✓ Ready in 4s
```
* **기동 성공.** 4초 만에 Ready.

---

## 3. 실패한 항목

**없음.** 모든 점검 통과.

| 항목 | 결과 |
|---|---|
| Git working tree status | ✅ |
| 보호 대상 폴더 미추적 | ✅ (8/8) |
| `.git` 크기 측정 | ✅ (다만 크기 자체가 위험 — §4 참조) |
| `python -m compileall backend -q` | ✅ EXIT=0 |
| `npx tsc --noEmit` | ✅ EXIT=0 |
| uvicorn 기동 | ✅ Application startup complete |
| next dev 기동 | ✅ Ready in 4s |

---

## 4. 고위험 항목 (HIGH-RISK)

### 4.1 `.git` 디렉터리 991MB
* **현상:** 작업트리 대비 압도적으로 큼.
* **원인 추정:** 과거 커밋에 `frontend/node_modules`의 win32 swc 바이너리(약 135MB), `샘플/_addr_db_inspect/*.txt` 다수(40~100MB), `analysis/*.pdf`, `.tmp.driveupload/*`(약 58MB × 2)가 포함된 것으로 보임. 현재는 `.gitignore` 처리됨.
* **영향:**
  * GitHub push 시 거부될 수 있음 (개별 파일 100MB 초과 시).
  * `git clone` 시간/대역폭 폭증.
  * Render 빌드 시 git clone 단계가 느려질 수 있음.
* **본 단계에서의 조치:** **없음 (정책상 금지).** 정리 작업은 별도 PR로 명시적 승인 후 진행. 비파괴 명령으로는 해결 불가.

### 4.2 로컬 `main`이 `origin/main`보다 3 커밋 앞섬
* **현상:** `Your branch is ahead of 'origin/main' by 3 commits.`
* **영향:** Render가 git origin 기반으로 빌드한다면 로컬 변경이 아직 운영에 반영되지 않음. 또한 4.1과 함께라면 push 시 거부 가능성.
* **본 단계에서의 조치:** **없음.** 사용자 결정 사항.

### 4.3 (참고) 계획서 §4.3에 정리된 코드 레벨 위험
본 안전 점검 단계에서 코드 수정 금지이므로 **재확인만**:
* `backend/routers/daily.py:390` — `ws.clear()` + `ws.update()` (잔액 시트).
* `frontend/.env.local.example`과 `CLAUDE.md`의 `NEXT_PUBLIC_API_URL` 안내 불일치.
* 12개 백엔드 파일에서 `get_all_values()` 37회 호출.

---

## 5. Phase 1 진행 가능 여부

### 결론: **기술적으로는 진행 가능하나, 사용자 명시적 승인 필요.**

* **기술 측면 ✅:** 백엔드/프론트엔드 모두 정상 기동, 컴파일·타입체크 통과, 보호 대상 폴더 미추적 확인.
* **블로커성 없음:** Phase 1(`backend/db/`, `/health/db` 추가)은 비즈니스 코드 무변경이며, `.git` 비대 문제와 독립적으로 진행 가능.
* **단, 다음 §6의 결정 항목을 먼저 확정해야 합니다.**

---

## 6. Phase 1 전에 반드시 사용자 결정이 필요한 사항

1. **`.git` 거대화 해결 시점 결정**
   * (a) Phase 1 전에 별도 작업으로 먼저 정리할지 (BFG / `git filter-repo`)
   * (b) 마이그레이션과 분리해서 별도 시점에 정리할지
   * → 권장: (b). Phase 1은 비파괴이며 본 문제와 독립적이므로 마이그레이션을 막을 이유 없음. 다만 GitHub push가 필요해질 때 (a)가 우선 작업이 됨.

2. **로컬 ahead 3 커밋의 push 여부**
   * 현재 origin과 어긋남. Phase 1 PR을 만들기 전에 origin 정렬 필요 여부 결정.

3. **Render PostgreSQL 인스턴스 생성 시점**
   * Phase 1의 `/health/db`는 DB 연결 없이도 작성 가능(404 또는 503 반환). 그러나 실제로 200 응답을 확인하려면 PG가 있어야 함.
   * 선택지:
     * (a) Phase 1 코드만 먼저 머지하고, PG는 Phase 2에서 생성.
     * (b) Phase 1 시점에 Render PG(Starter $7/월) 생성 후 즉시 연결 확인.

4. **Render PostgreSQL 플랜**
   * Starter ($7/월) vs Standard. 본 단계에서 결정 권장.

5. **Phase 1 PR 작성 방식**
   * (a) `requirements.txt` + `backend/db/` + `alembic` + `/health/db` 한 PR.
   * (b) 의존성 추가만 1차 PR, db/alembic을 2차 PR로 분리.
   * → 권장: (a). 양이 적고 응집도 높음.

6. **여권/외국인등록번호 암호화 정책 (Phase 4 사전 결정)**
   * 본 단계에서 결론낼 필요는 없으나, Phase 1 시작과 동시에 별도 결정 트랙으로 진행 권장.

---

## 7. 추천 다음 작업

1. **사용자 확인:** §6의 1~5번 결정 후 답변.
2. **Phase 1 시작 승인 시:**
   * 새 브랜치 생성 (예: `feat/postgres-foundation`)
   * `requirements.txt`에 4줄 추가
     ```
     SQLAlchemy>=2.0,<2.1
     psycopg[binary]>=3.1
     alembic>=1.13
     pydantic-settings>=2.0
     ```
   * `backend/db/{session,base,__init__}.py` 작성
   * `backend/routers/health.py` 작성 + `main.py`에 한 줄 등록
   * `alembic init alembic` 후 `env.py` 설정
   * 로컬에서 `GET /health/db` 200 확인 (PG 인스턴스 가용 시) 또는 503 graceful 확인
   * smoke test: 로그인 → 고객 조회 → 진행업무 조회 영향 없음 확인
3. **사용자 결정 §6-1을 (a)로 정한 경우:**
   * 별도 작업으로 `.git` 정리 PR을 먼저 진행. 본 마이그레이션 작업과 분리.

---

## 8. 사용자 승인 대기

본 시점에서 **모든 자동 작업을 중단**합니다. 다음 단계는 사용자의 명시적 승인 후에만 진행합니다.

* [ ] §6의 결정 항목에 대한 사용자 답변
* [ ] Phase 1 시작 승인

**END OF REPORT**
