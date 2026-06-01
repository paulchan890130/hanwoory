# 로컬 PostgreSQL 베타 매뉴얼 테스트 가이드 (사용자용)

> **목적:** 자동 검증은 끝났습니다. 이제 사용자가 직접 브라우저·터미널에서 1차 베타 동작을 확인합니다.
> **소요:** 약 15~20분.
> **선행:** `LOCAL_POSTGRES_BETA_REPORT.md` 의 §11 체크리스트와 동일한 절차의 한글 압축본입니다.

---

## 0. 시작 전 약속

* ❌ 본 가이드 도중 **커밋 / 푸시 / 머지 / Render 작업 일절 안 함**
* ❌ 운영 Google Sheets · Drive **수정 안 함**
* ✅ 모든 작업은 **로컬 Docker PostgreSQL + 로컬 백엔드 + 로컬 프론트엔드**로만 진행
* 모든 명령은 **PowerShell 기준**

### 포트 분담 (확정)

| 포트 | 용도 |
|---|---|
| **8000** | Claude(자동 검증) 전용 — 사용자는 이 포트 안 씀 |
| **8001** | 유학생 업무관리 — **건드리지 말 것** |
| **8002** | **본 가이드의 사용자 매뉴얼 베타 테스트 고정 포트** |

본 가이드의 모든 `--port`, `curl`, `$env:API_URL` 값은 **8002 고정**.

---

## 1. Docker PostgreSQL 실행 확인

```powershell
docker ps --filter "name=kid-postgres-local" --format "{{.Names}}`t{{.Status}}"
```

* 기대: `kid-postgres-local   Up X minutes` 한 줄 출력
* 만약 출력 없음 → 컨테이너 미실행. 다음 명령으로 시작:
  ```powershell
  docker run --name kid-postgres-local `
    -e POSTGRES_DB=kid_local `
    -e POSTGRES_USER=kid_user `
    -e POSTGRES_PASSWORD=kid_pass `
    -p 5433:5432 -d postgres:16
  ```

데이터 보유 확인 (선택):
```powershell
docker exec kid-postgres-local psql -U kid_user -d kid_local -c "SELECT login_id FROM users ORDER BY login_id;"
```
* 기대: `inactive_user / test_admin / test_user` 3행

---

## 2. 백엔드 기동 — **플래그 OFF (기존 동작 확인용)**

새 PowerShell 창에서:

```powershell
cd "C:\Users\윤찬\K.ID soft"
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
# 플래그는 일부러 설정 안 함 (= OFF 기본값)
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```

* 기대 로그: `Application startup complete.`, `Uvicorn running on http://127.0.0.1:8002`

빠른 헬스체크 (또 다른 PowerShell):
```powershell
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8002/health/db
curl http://127.0.0.1:8002/api/dev/pg/users/count
```

* `/health` → `{"status":"ok"}`
* `/health/db` → `{"db":"ok","latency_ms":<숫자>}`
* `/api/dev/pg/users/count` → **HTTP 503** (플래그 off 메시지) ← 이게 정상

---

## 3. 브라우저 테스트 — **기존 Google Sheets 동작 확인**

프론트엔드 별도 PowerShell:
```powershell
cd "C:\Users\윤찬\K.ID soft\frontend"
# ⚠️ 백엔드를 8002로 띄웠으므로 Next.js 프록시도 8002로 가도록 지정
$env:API_URL = "http://127.0.0.1:8002"
npm run dev
```

> `next.config.js`의 `rewrites()` 기본값은 `http://127.0.0.1:8000` 입니다. 환경변수를 안 주면 프론트엔드가 8000(Claude용 슬롯, 사용자 테스트와 무관)으로 프록시해서 본 백엔드(8002)와 통신 실패 → 로그인이 안 됩니다. **반드시** 위 `$env:API_URL` 설정 후 `npm run dev`.

`npm run dev` 출력의 `Local: http://localhost:XXXX` 줄에 표시된 **실제 포트**로 접속.
> 대부분 `3000`이지만 다른 프로세스(예: `kid-frontend` Docker 컨테이너)가 3000을 점유 중이면 Next.js가 자동으로 3001/3002/... 로 fallback합니다. **npm 콘솔의 실제 표시 포트**를 그대로 사용하세요.

그 주소에서 **평소 사용하던 운영 계정으로 로그인**.

확인할 페이지/동작:

| 페이지 | 확인할 것 |
|---|---|
| `/login` | 평소처럼 로그인됨 |
| `/dashboard` | 진행업무·예정업무·일일결산·달력 평소처럼 표시 |
| `/customers` | 고객 목록 검색·조회·열기 평소처럼 동작 |
| `/tasks` (진행/완료/예정) | 평소처럼 동작 |
| `/daily` | 일일결산·잔액 평소처럼 |
| `/quick-doc` | 원클릭 작성 / 문서자동작성 평소처럼 |

> 핵심: **PG 플래그가 꺼져 있으므로 모든 동작이 Google Sheets로 흐름**. 어떤 동작도 변하지 않아야 합니다.

---

## 4. 기존 Google Sheets 무변경 검증

브라우저에서 Google Sheets `Accounts` 시트와 `고객 데이터` 시트 직접 열어 확인:

* 행 수·열·값이 본 베타 작업 전과 동일해야 함
* 새로 생긴 행 / 사라진 행 / 변경된 셀 0건이어야 함

> 이 단계에서 본 도구가 운영 시트를 건드릴 가능성은 **0** (코드에서 쓰기 호출 없음)이지만, 사용자가 직접 눈으로 확인하는 것이 중요합니다.

---

## 5. 백엔드 재기동 — **플래그 ON (PG 경로 검증)**

§2의 PowerShell에서 `Ctrl+C` 로 uvicorn 종료. 같은 창에서:

```powershell
$env:FEATURE_PG_USERS = "true"
$env:FEATURE_PG_AUDIT = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```

기대 로그: `Application startup complete.` 다시 표시.

> `$env:DATABASE_URL` 은 같은 세션에 이미 설정되어 있으므로 다시 안 해도 됩니다.

---

## 6. `/api/dev/pg` 엔드포인트 테스트

별도 PowerShell에서 차례로:

### 6-1. 플래그 상태
```powershell
curl http://127.0.0.1:8002/api/dev/pg/flags
```
* 기대: `{"FEATURE_PG_USERS":true,"FEATURE_PG_AUDIT":true,"FEATURE_PG_CUSTOMERS":false}`

### 6-2. 사용자 수
```powershell
curl http://127.0.0.1:8002/api/dev/pg/users/count
```
* 기대: `{"count":3}`

### 6-3. 로그인 성공
```powershell
curl -Method Post -Uri http://127.0.0.1:8002/api/dev/pg/login-test `
  -ContentType "application/json" `
  -Body '{"login_id":"test_admin","password":"beta_test_password_123"}'
```
* 기대: `{"ok":true,"login_id":"test_admin","tenant_id":"test_admin","is_admin":true}`

### 6-4. 로그인 실패 (잘못된 비밀번호 / 비활성 / 미존재) — 3회 모두 시도
```powershell
# 잘못된 비밀번호
curl -Method Post -Uri http://127.0.0.1:8002/api/dev/pg/login-test `
  -ContentType "application/json" `
  -Body '{"login_id":"test_admin","password":"wrong"}'

# 비활성 사용자 — 비밀번호는 맞아도 로그인 거부되어야 함
curl -Method Post -Uri http://127.0.0.1:8002/api/dev/pg/login-test `
  -ContentType "application/json" `
  -Body '{"login_id":"inactive_user","password":"beta_test_password_123"}'

# 존재하지 않는 사용자
curl -Method Post -Uri http://127.0.0.1:8002/api/dev/pg/login-test `
  -ContentType "application/json" `
  -Body '{"login_id":"nope","password":"x"}'
```
* 세 경우 모두 동일하게 `{"ok":false,"reason":"invalid_credentials_or_inactive"}` — 정보 누출 없는 단일 메시지

### 6-5. 감사 로그 (audit)
```powershell
curl -Method Post -Uri http://127.0.0.1:8002/api/dev/pg/audit-test `
  -ContentType "application/json" `
  -Body '{"action":"user.manual.smoke"}'
```
* 기대: `{"ok":true,"rows_before":<n>,"rows_after":<n+1>,"delta":1}`
* 다시 호출하면 `delta`는 매번 1씩 증가

### 6-6. **운영 라우터가 여전히 Sheets로 동작하는지 재확인**

브라우저 `/login` 에서 **운영 계정으로 다시 로그인**:
* 평소처럼 로그인되고 평소처럼 동작해야 함
* 즉 PG 플래그가 켜져 있어도 기존 `/api/auth/login` 은 Sheets로만 흐름

---

## 7. 종료 및 정리

### 7-1. 백엔드 / 프론트엔드 종료
* 각 PowerShell 창에서 `Ctrl+C`

### 7-2. 환경변수 제거 (현재 세션 한정)
```powershell
$env:FEATURE_PG_USERS = $null
$env:FEATURE_PG_AUDIT = $null
$env:DATABASE_URL = $null
```
> 또는 그냥 해당 PowerShell 창을 닫으면 됩니다.

### 7-3. Docker 컨테이너 정리
```powershell
docker stop kid-postgres-local
docker rm kid-postgres-local
docker ps -a --filter "name=kid-postgres-local"
```
* 마지막 명령 출력이 헤더만 나와야 정상 (행 0건)

> 이미지(`postgres:16`)는 보관됨. 또 베타 테스트할 때 즉시 재실행 가능. 완전 제거를 원하면 `docker rmi postgres:16`.

---

## 8. PASS 판정 기준 (모두 충족 시 PASS)

* [ ] §1: 컨테이너 살아있고 `users` 행 3개 존재
* [ ] §2: 백엔드 기동 정상, 플래그 OFF에서 `/api/dev/pg/users/count` 가 **503** 반환
* [ ] §3: 브라우저 운영 계정 로그인 성공, 대시보드·고객·진행업무·일일결산 등 **평소와 완전히 동일하게 동작**
* [ ] §4: Google Sheets 시트 행 수·값 **변경 없음**
* [ ] §5: 플래그 ON 으로 재기동 성공
* [ ] §6-1: flags 응답이 `USERS:true, AUDIT:true, CUSTOMERS:false`
* [ ] §6-2: `count: 3`
* [ ] §6-3: `ok:true`
* [ ] §6-4: 3가지 실패 케이스 전부 `ok:false`
* [ ] §6-5: audit `delta:1`
* [ ] §6-6: 플래그 ON 상태에서도 운영 `/api/auth/login` 으로 Sheets 로그인 평소처럼 성공

---

## 9. FAIL 판정 기준 (하나라도 해당 시 FAIL)

* `/health` 가 200이 아님
* `/health/db` 가 `db:"ok"` 가 아님 (특히 `unavailable` 503 이 나오면 PG 컨테이너 죽었거나 포트 충돌)
* **플래그 OFF인데** `/api/dev/pg/users/count` 가 200을 반환 (→ 가드 실패)
* **플래그 OFF에서** 운영 페이지 동작이 평소와 다름 (→ 코드가 기존 흐름에 영향을 줌)
* Google Sheets 행 수가 변함 (→ 절대 발생하면 안 됨 — 즉시 중단)
* 플래그 ON 인데 `count` 가 3이 아님 (→ 임포트 누락)
* `login-test` 정답 케이스에서 `ok:false`, 또는 오답 케이스에서 `ok:true` (→ 인증 로직 결함)
* `audit-test` 가 200을 반환했는데 `delta:0` (→ 쓰기 실패가 silent로 묻혀 있음)
* uvicorn 부팅 중 `Traceback` / `ImportError` / `OperationalError` 등 빨간 로그 발생

FAIL 발생 시:
1. uvicorn 콘솔 로그 + 실패한 응답을 캡처
2. `docker logs kid-postgres-local` 확인
3. 컨테이너 / 환경변수 §7로 정리 후 상황 공유

---

## 10. PASS 시 커밋 대상 파일

PASS 확정 후에만 커밋. 본 베타 작업과 무관한 변경(Opus 4.8 마이그레이션)은 **별도 커밋** 권장.

### 10-1. 베타 구현 커밋 대상
```powershell
git add `
  backend/db/__init__.py `
  backend/main.py `
  backend/db/models/ `
  backend/db/feature_flags.py `
  backend/db/local_guard.py `
  backend/services/audit_service.py `
  backend/services/auth_pg_service.py `
  backend/routers/dev_pg.py `
  backend/scripts/migrate_accounts_to_pg.py `
  alembic/versions/ `
  LOCAL_POSTGRES_BETA_PLAN.md `
  LOCAL_POSTGRES_BETA_REPORT.md `
  LOCAL_POSTGRES_BETA_USER_TEST_STEPS.md
```

커밋 메시지 예시:
```
feat(db): local PostgreSQL beta — models, flags, audit, dev endpoints

- Add Tenant / AccountUser / AuditLog ORM models + Alembic 0001
- Add FEATURE_PG_USERS / FEATURE_PG_AUDIT / FEATURE_PG_CUSTOMERS (default off)
- Add /api/dev/pg/* dev endpoints (HANWOORY_ENV=local only)
- Add audit_service (best-effort, silent on failure)
- Add auth_pg_service (PG-side login lookup behind feature flag)
- Add Accounts → local PG import script (local-only guard, dry-run default)
- Existing Sheets-backed flow unchanged; flags default off preserves it.
```

### 10-2. 별도 커밋 (Opus 4.8 마이그레이션 — PASS 무관)
```powershell
git add `
  backend/scripts/llm_judge_run_v1.py `
  backend/scripts/llm_verifier_run_v1.py `
  backend/scripts/llm_remap_all.py `
  backend/scripts/analyze_manual_structure.py
```

커밋 메시지 예시:
```
chore(scripts): migrate LLM helper scripts to claude-opus-4-8
```

### 10-3. **하지 말 것**
* `git push` — 별도 결정
* `git merge` 또는 force-push — 본 도구 절대 자동 안 함
* Render Dashboard 작업 — `RENDER_POSTGRES_SETUP_GUIDE.md` 참조, 사용자가 직접
* 운영 PG에 `alembic upgrade head` — 절대 금지

---

**END OF GUIDE**
