# Render PostgreSQL 셋업 가이드 (RENDER_POSTGRES_SETUP_GUIDE.md)

> **작성일:** 2026-06-01
> **선행 상태:** Phase 1(연결 계층 + `/health/db`) 머지 완료, 운영에 배포된 상태.
> **목표:** Render Dashboard에서 PostgreSQL 인스턴스를 만들고 `DATABASE_URL`을 연결한 뒤 `/health/db`가 `ok`를 반환하는지 확인한다. **데이터 마이그레이션은 다음 단계.**
> **이 문서를 다 읽고 §11(절대 금지) 항목을 먼저 확인하세요.**

---

## 0. 사전 체크리스트

다음이 모두 충족되어야 본 가이드를 진행할 수 있습니다.

- [ ] `feat/postgres-foundation` 브랜치가 main에 머지되어 Render에 배포 완료
- [ ] 배포된 운영 도메인에서 `GET /health` 가 `{"status":"ok"}` 응답
- [ ] 배포된 운영 도메인에서 `GET /health/db` 가 `{"db":"unconfigured", ...}` 응답 (= DATABASE_URL이 아직 없음)
- [ ] Render Dashboard 접근 가능한 관리자 계정 보유
- [ ] 결제 수단 등록 완료 (Starter 플랜은 유료)

> `/health` 가 응답하지 않으면 본 가이드 진행 금지. 먼저 배포 자체를 안정화하세요.

---

## 1. 현재 Web Service의 리전(Region) 확인

PostgreSQL은 **반드시 Web Service와 동일 리전**에 만들어야 합니다. 리전이 다르면 매 쿼리마다 인터넷을 왕복해 10~수십 배 느려지고, Internal URL을 사용할 수도 없습니다.

### 1-1. Render Dashboard에서 확인
1. Render Dashboard 좌측 메뉴 → **Services**
2. K.ID 백엔드 Web Service(예: `kid-backend` 등) 클릭
3. 상단 또는 우측 **Settings** 탭으로 이동
4. **Region** 항목 확인. 일반적으로 다음 중 하나:
   - `Oregon (US West)` — 한국에서 자주 사용됨
   - `Singapore (Southeast Asia)`
   - `Frankfurt (EU Central)`
   - `Ohio (US East)`

### 1-2. 메모
다음 칸에 직접 적어두세요(다음 단계에서 동일하게 선택해야 함):

```
현재 Web Service 리전: ______________________
```

> 한국에서 운영한다면 `Singapore` 또는 `Oregon`이 일반적입니다. 어느 쪽이든 **PostgreSQL을 그 동일 리전에 만들어야** 합니다.

---

## 2. Render PostgreSQL 생성

### 2-1. 새 PostgreSQL 인스턴스 만들기
1. Render Dashboard 우측 상단 **New +** 클릭
2. 드롭다운에서 **PostgreSQL** 선택
3. 다음 폼이 나옵니다:

| 항목 | 입력값 |
|---|---|
| **Name** | `kid-postgres` (자유, 알아보기 쉽게) |
| **Database** | `kid_prod` (소문자/언더스코어 권장) |
| **User** | 빈 칸으로 두면 자동 생성됨 |
| **Region** | **§1에서 확인한 리전과 정확히 동일** ⚠️ |
| **PostgreSQL Version** | **16** (§4 참조) |
| **Datadog API Key** | 비워두기 |
| **Plan** | **Starter** (§3 참조) |

4. **Create Database** 클릭
5. Render가 5~10분 정도 프로비저닝을 진행합니다. 상태가 `Available`로 바뀌면 완료.

### 2-2. 진행 중 화면이 닫혔다면
- Dashboard 좌측 메뉴 → **Databases** → 방금 만든 인스턴스 클릭
- 상태가 `Available`인지 확인

---

## 3. 플랜 선택 기준

### 3-1. 이번 단계: **Starter ($7/월)**
이유:
- 본 단계는 **연결 검증**과 다음 단계의 **인증 테이블 추가**가 목적이며, 트래픽이 작음.
- Starter도 90일 보관·일 1회 자동 백업이 제공됨.
- 운영 데이터를 옮기기 전까지 비용을 최소화.

Starter 사양 요약:
- Storage: 1 GB
- RAM: 256 MB
- CPU: shared
- Connections: 약 97
- Backup: 일 1회, 7일 보관

### 3-2. 운영 전환 전: **Standard ($20~/월) 재검토**

다음 시점에 Starter → Standard 업그레이드 여부를 재평가합니다:
- 고객 데이터(Phase 4) 마이그레이션 직전
- 또는 동시 사무소 수가 10개 이상으로 증가하기 직전

Standard로 올리는 기준:
- 동시 커넥션이 50개를 넘기 시작
- Sheets 캐시 미스 + PG 쿼리가 동시에 잦아져 latency가 100ms를 넘기 시작
- 단일 사무소 고객 수 5,000명 이상

> Starter ↔ Standard는 Render Dashboard에서 클릭 한 번으로 업그레이드 가능. 단, **다운그레이드는 데이터 손실 위험**이 있으므로 신중히.

---

## 4. PostgreSQL 버전 선택

### 권장: **PostgreSQL 16**

이유:
- 2024-2026 시점 기준 가장 안정적인 LTS급 버전
- SQLAlchemy 2.x, psycopg 3.x 모두 완전 지원
- JSONB·파티셔닝·인덱스 성능 등에서 14/15 대비 개선
- Render가 안정 지원하는 최신 버전

> Render UI에서 16이 기본 선택되어 있다면 그대로 두면 됩니다. 17이 옵션으로 보이더라도 본 마이그레이션에서는 **16을 명시적으로 선택**하세요(라이브러리 호환성 검증 완료한 버전).

> 한 번 버전을 정하면 마이너 업그레이드는 자동이지만 **메이저 버전 다운그레이드는 불가**합니다. 신중히 선택.

---

## 5. Internal Database URL 확인

PostgreSQL이 `Available` 상태가 된 후:

1. Render Dashboard → **Databases** → 방금 만든 인스턴스 클릭
2. 상단의 **Info** 또는 좌측 **Connect** 탭에 다음 두 URL이 표시됨:

   - **Internal Database URL** — Render 내부망 전용. 예:
     ```
     postgresql://kid_user:xxxxxxxx@dpg-abc123-a/kid_prod
     ```
     호스트에 `.render.com`이 **없고** 짧은 형태(`dpg-...-a`). **이 URL을 사용합니다.**

   - **External Database URL** — 외부에서 접속용. 예:
     ```
     postgresql://kid_user:xxxxxxxx@dpg-abc123-a.oregon-postgres.render.com/kid_prod
     ```
     로컬 PC에서 `psql`로 점검할 때만 사용. **운영 환경변수에 넣지 말 것.**

3. **Internal Database URL** 옆의 복사 버튼(📋)을 눌러 클립보드에 복사

### 5-1. 왜 Internal URL을 써야 하는가
| 항목 | Internal | External |
|---|---|---|
| 속도 | 빠름 (내부망, 1-3ms) | 느림 (인터넷, 30-100ms) |
| 보안 | 내부망, 노출 위험 낮음 | 공개 인터넷, 비밀번호 노출 시 위험 |
| 비용 | 트래픽 무료 | 외부 egress 과금 가능 |
| 안정성 | Render 내부 라우팅 | 외부 네트워크 의존 |

운영 환경변수에는 **반드시 Internal**을 사용합니다.

---

## 6. Web Service 환경변수에 DATABASE_URL 등록

### 6-1. 변수 추가 절차
1. Render Dashboard → **Services** → K.ID 백엔드 Web Service 클릭
2. 좌측 메뉴 **Environment** 탭 클릭
3. **Add Environment Variable** 클릭
4. 다음과 같이 입력:

   | 필드 | 값 |
   |---|---|
   | **Key** | `DATABASE_URL` |
   | **Value** | §5에서 복사한 **Internal Database URL** 그대로 |

5. **Save Changes** 클릭

### 6-2. (선택) 함께 설정 가능한 보조 변수
필요 시 같은 화면에서 추가. 미설정 시 코드 기본값 사용:

| Key | 기본값 | 의미 |
|---|---|---|
| `DATABASE_POOL_SIZE` | `5` | SQLAlchemy 풀 기본 크기 |
| `DATABASE_MAX_OVERFLOW` | `10` | 풀 초과 시 허용할 추가 커넥션 |
| `DATABASE_CONNECT_TIMEOUT` | `5` | 단일 연결 시도 타임아웃(초) |

> 이번 단계에서는 기본값만 사용 권장. 부하 측정 후에 조정.

### 6-3. 절대 하지 말 것
- `.env` 파일에 `DATABASE_URL`을 적어 Git에 커밋하지 말 것. Render Dashboard에만 등록.
- External URL을 `DATABASE_URL`에 넣지 말 것.
- 비밀번호 부분을 다른 곳(채팅·문서)에 복사해두지 말 것.

---

## 7. 저장 후 재배포 확인

### 7-1. 자동 재배포 트리거
환경변수 변경 시 Render는 **자동으로 새 빌드를 시작**합니다.

1. Web Service의 **Events** 또는 **Logs** 탭으로 이동
2. 다음과 같은 이벤트가 보이는지 확인:
   - `Deploy started for ... (env var updated)`
   - `Build successful`
   - `Deploy live`
3. 보통 3~10분 소요.

### 7-2. 새 빌드가 안 보일 때
- 환경변수 추가 후 Dashboard를 새로고침
- 그래도 빌드가 안 보이면 Web Service 상단의 **Manual Deploy** → **Deploy latest commit** 클릭

### 7-3. 빌드 실패 시
- **Logs** 탭에서 빨간 줄 확인
- `requirements.txt`의 `psycopg[binary]>=3.1` 설치가 실패했는지 확인 (Phase 1이 이미 통과한 라인이므로 대개 문제없음)
- 실패한 빌드가 있어도 **이전 운영 빌드는 그대로 살아 있음** — 외부에서는 변화를 못 느낌

---

## 8. 배포 후 `/health/db` 확인

배포가 `Live`로 바뀌면:

### 8-1. 브라우저 또는 curl로 호출
```
https://<your-service>.onrender.com/health/db
```

### 8-2. 기대 응답 (성공)
```json
{
  "db": "ok",
  "latency_ms": 12
}
```
- `latency_ms`는 1~50 사이가 정상(Internal URL 사용 시).
- 100ms 이상이면 §1 리전 불일치 가능성.

### 8-3. 기대 응답 (실패)
```json
{
  "db": "unavailable",
  "latency_ms": 5023,
  "error": "OperationalError",
  "detail": "..."
}
```
HTTP 503. 이 경우 §9 점검표로 이동.

### 8-4. 함께 확인할 것
- `GET /health` 가 여전히 `{"status":"ok"}` 200 반환 (앱 자체는 살아 있음)
- 운영 페이지(로그인, 고객조회, 진행업무)가 평소처럼 동작
- 사용자 입장에서 어떤 변화도 체감되지 않아야 정상

---

## 9. 실패 시 점검 항목

### 9-1. `DATABASE_URL` 오타 / 누락
| 증상 | `/health/db` 응답이 여전히 `unconfigured` |
|---|---|
| 점검 | Render Dashboard → Web Service → Environment 탭에서 키 이름이 **정확히 `DATABASE_URL`** 인지 확인. 대소문자, 공백 없음. |
| 처리 | 오타 수정 → Save → 자동 재배포 대기 |

### 9-2. 외부 URL / 내부 URL 혼동
| 증상 | `unavailable` + 매우 느린 latency 또는 인증 실패 |
|---|---|
| 점검 | URL 호스트에 `.render.com` 또는 `oregon-postgres.render.com` 같은 도메인이 들어가 있다 → **외부 URL**. 잘못된 값. |
| 처리 | §5로 돌아가 **Internal Database URL** 다시 복사 후 교체 |

### 9-3. 리전 불일치
| 증상 | `unavailable` (Internal URL인데 connection refused 또는 timeout) |
|---|---|
| 점검 | Render Dashboard에서 Web Service Region(§1)과 PostgreSQL Region(§2)이 동일한지 확인 |
| 처리 | 다르면 PostgreSQL 인스턴스를 **삭제하고 동일 리전으로 재생성**. (인스턴스 리전은 변경 불가) — 단, 이 단계엔 아직 데이터가 없으므로 안전하게 재생성 가능. |

### 9-4. `sslmode` 문제
| 증상 | `SSL connection has been closed unexpectedly` 또는 `no pg_hba.conf entry, no encryption` |
|---|---|
| 점검 | 코드(`backend/db/session.py`)는 Render 호스트 자동 감지 시 `?sslmode=require`를 부착하지만, Internal URL은 도메인 패턴이 다르므로 부착되지 않을 수 있음. |
| 처리 | Environment 탭에서 `DATABASE_URL` 끝에 `?sslmode=require`를 수동으로 붙임. 이미 `?`가 있으면 `&sslmode=require`. |

### 9-5. Render 배포 자체 실패
| 증상 | 환경변수 저장 후 새 deploy가 빨간색(Failed) |
|---|---|
| 점검 | Logs 탭 → Build 단계의 마지막 에러 메시지. 일반적 원인: 디스크 부족(Render 측 일시 이슈), pip 인덱스 일시 장애, requirements 의존성 충돌. |
| 처리 | 5분 대기 후 **Manual Deploy → Deploy latest commit** 재시도. 반복 실패 시 Render Status 페이지(https://status.render.com) 확인. |

### 9-6. `/health/db` 자체가 404
| 증상 | `Not Found` |
|---|---|
| 점검 | 배포가 옛 빌드일 가능성. `main.py`에 `app.include_router(health_router.router, prefix="/health", ...)` 한 줄이 포함된 커밋이 배포되었는지 확인. |
| 처리 | Manual Deploy로 최신 커밋 재배포 |

### 9-7. 그 외 일반 점검
- **Logs 탭에서 가장 최근 ERROR 또는 Traceback** 한 화면 캡처해서 확인
- 비밀번호에 특수문자(`@`, `:`, `/`)가 포함된 경우 URL 인코딩 누락 여부 점검 (Render가 생성한 자동 비번은 안전 문자만 사용하지만, 수동 변경했다면 점검 필요)

---

## 10. 본 단계 완료 기준

다음이 모두 충족되면 본 단계 종료:

- [ ] Render PostgreSQL 인스턴스 상태가 `Available`
- [ ] PostgreSQL 리전 = Web Service 리전
- [ ] Web Service Environment에 `DATABASE_URL` 등록됨 (Internal URL)
- [ ] 자동 재배포 성공 (Logs에 `Deploy live`)
- [ ] `https://<service>/health/db` 가 `{"db":"ok", "latency_ms":<50}` 응답
- [ ] `https://<service>/health` 는 여전히 `{"status":"ok"}` 응답
- [ ] 운영 페이지(로그인/고객조회/진행업무 등)에 어떤 영향도 없음

이후 사용자 승인 시 Phase 2(테이블 생성)로 진행.

---

## 11. 이 단계에서 절대 하면 안 되는 것 (DO-NOT-LIST)

> 본 가이드는 **PostgreSQL 인스턴스 생성과 `/health/db` 검증**까지만 다룹니다. 그 이상은 다음 단계입니다.

- ❌ **`alembic upgrade head` 실행 금지.**
  Phase 1의 `alembic`은 `target_metadata`가 비어 있어 실행해도 의미 없는 빈 트랜잭션이지만, 실수로 다음 단계의 마이그레이션 파일이 생긴 상태에서 실행하면 의도치 않은 DDL이 적용됩니다.
- ❌ **`alembic revision --autogenerate` 실행 금지.**
  Phase 2에서 모델을 먼저 정의한 뒤 별도 PR로 진행합니다.
- ❌ **비즈니스 테이블(`tenants`, `users`, `customers`, `audit_logs` 등) 생성 금지.**
  PG Dashboard의 Query 콘솔에서도, psql에서도, ORM에서도 만들지 마세요.
- ❌ **Google Sheets 로직 수정 금지.**
  `backend/services/tenant_service.py`, `accounts_service.py` 등을 건드리지 않습니다.
- ❌ **Google Drive 로직 수정 금지.**
  `backend/routers/admin.py` 의 Drive 호출부, `marketing.py`의 이미지 업로드 등 무변경.
- ❌ **고객 데이터 이전 금지.**
  Phase 4에서만 이전합니다.
- ❌ **UI 변경 금지.**
- ❌ **`.env` / 비밀 파일 / `config.py` 비밀 정보 수정 금지.**
- ❌ **`psql`로 운영 DB에 직접 DDL 실행 금지.**
  로컬에서 External URL로 접속해 `SELECT version();` 정도 확인은 허용. `CREATE TABLE` 등은 금지.
- ❌ **다른 환경(개발/스테이징)에서 받은 dump를 운영 PG에 import 금지.**

---

## 12. 완료 후 다음 단계 미리보기 (참고용, 실행 금지)

본 단계가 끝나면 다음 단계(Phase 2)에서 진행할 작업:
1. `backend/db/models/tenant.py`, `user.py`, `audit.py` 작성 (모델만)
2. `alembic revision --autogenerate -m "0001 tenants users audit_logs"` 실행 (로컬에서 마이그레이션 파일 생성)
3. 마이그레이션 파일 검토 → PR
4. 머지 후 Render에서 `alembic upgrade head` (또는 release command로 자동) 1회 실행
5. Accounts 시트 → PG 임포트 스크립트 dry-run → 실행
6. 한 테스트 계정으로 PG 경로 로그인 검증

> 위 작업은 **본 가이드의 범위가 아닙니다.** 본 가이드는 §10까지로 종료.

---

## 13. 사용자 승인 대기 시점

본 가이드를 따라 §10의 모든 체크박스가 OK가 된 시점에 멈추고 다음 한 줄을 알려주세요:

> "Render PG 셋업 완료, `/health/db`가 `ok` 반환 확인. Phase 2 진행 요청."

그 후에만 Phase 2를 시작합니다.

**END OF GUIDE**
