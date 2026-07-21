# Codebase Audit — Approved-SaaS Foundation

작성: feat/approved-saas-foundation. 실측 기준 커밋 `ba7cdbcf`.

## 1. 재사용할 기존 구조 (신규 생성 금지 — 반드시 재사용)

### 인증 / 권한 (`backend/auth.py`)
- `get_current_user`: **매 요청** PG `account_auth_status(login_id)` 재확인 → `is_active=false`/`missing` 이면 **401 `{code:"ACCOUNT_DISABLED"}`**. → **계정 정지 즉시차단은 신규 구현 불필요**, `users.is_active=false` + 세션 revoke 만으로 달성됨.
- `require_admin` = full admin(`is_admin`) 또는 마스터(`wkdwhfl`). **승인/정지/복구/교체 API 의 게이트로 재사용**.
- `require_admin_or_sub_admin` = +sub_admin. 승인 흐름에는 쓰지 않음(승인은 full admin 전용).
- 역할 체계: `is_admin`(bool, source of truth) + `role`(`user`/`sub_admin`/`admin`, migration 0024). **신규 역할 체계 만들지 않음** — 계정1=`is_admin=true`(office_admin 상당), 계정2=`is_admin=false`,`role=user`(office_staff 상당)로 매핑.
- 마스터 `wkdwhfl` 은 강등/삭제 불가(서버 강제).

### 세션 즉시 무효화 (`backend/services/session_pg_service.py`, `FEATURE_SINGLE_SESSION`)
- `revoke_active_sessions(login_id, reason, only_non_kiosk=False)` → 기존 세션 즉시 revoke. **정지/교체에서 재사용**.
- `session_status(sid)` 로 `get_current_user` 가 revoked 세션 차단.
- 주의: 단일세션 sid 검사는 `FEATURE_SINGLE_SESSION` on 일 때만. **`is_active=false` 차단은 플래그와 무관하게 항상 동작**(availability). → 정지의 1차 방어선은 `is_active`, 2차는 세션 revoke.

### 계정 lifecycle (`backend/routers/admin.py`)
- 기존: `PUT /accounts/{id}`(활성토글+세션revoke), `DELETE /accounts/{id}`(비활성+revoke), `POST /accounts/{id}/restore`, `DELETE /accounts/{id}/hard`(물리삭제, 가드), `PUT /accounts/{id}/role`, `POST /accounts`(생성), `_other_admin_count`(마지막 admin 보호), `_connected_data_summary`, `_audit_account`.
- 신규 승인 SaaS 는 **별도 경로**(`/users/...`, `/tenants/...`, `/office-applications/...`)로 추가 → 기존 `/accounts/...` 미접촉.

### 계정 저장소 = PostgreSQL-only (`backend/services/accounts_service.py`)
- `find_account`/`append_account`/`build_account_dict`/`hash_password`/`verify_password` 전부 **PG(users+tenants)**. Sheets 아님(이관 완료).
- 로그인(`routers/auth.py`)·`admin.create_account` 모두 PG. **user 생성 시 append_account 또는 직접 ORM 재사용**.

### 기존 가입신청 프로토 (`backend/routers/auth.py` `/signup`)
- 이미 존재: `/signup` → PG `tenants`+`users` 생성, `is_active=false`(관리자 승인 대기). 로그인 화면에 "사무실 가입신청" 탭 있음(`login/page.tsx`).
- **차이**: 기존 signup 은 신청 즉시 tenant+user 를 만든다(신규 원칙 위반). 신규 `office_applications` 흐름은 **승인 전까지 tenant/user 미생성**. → 기존 signup 은 **건드리지 않고 보존**, 신규 공개 신청은 별도 `/apply` 로 추가(병존).

### 감사로그 (`backend/services/audit_service.py`, `FEATURE_PG_AUDIT`)
- `log_event(action, actor_login_id, tenant_id, target_type, target_id, payload, ...)` best-effort, 절대 raise 안 함. **신규 이벤트도 이 함수 재사용**. (`audit_logs` 는 FK 없음 → 계정 삭제돼도 로그 잔존.)

### PII (`backend/services/pii_crypto.py`)
- `encrypt_agent_rrn`/`rrn_last4`/`validate_rrn_format`, HMAC 검색 패턴 존재 → 중복경고 민감정보 비교에 재사용 가능(사업자번호 등은 저위험이라 평문 비교로도 충분 — 아래 결정 참조).

### tenant 프로비저닝 (`backend/services/tenant_provisioning_service.py`)
- `ensure_tenant_provisioned(tenant_id, office_name)` 멱등. 승인 트랜잭션에서 직접 ORM 으로 tenant 생성(트랜잭션 원자성 위해 helper 대신 같은 세션 내 insert).

## 2. 기존 테이블 / 필드
- `tenants`(0001): `tenant_id`(natural key, unique), `office_name`, `office_adr`, `biz_reg_no`, `is_active`, agent_rrn_*, card_* … → **여기에 service_tier/seat_limit/service_status/approved_* additive**.
- `users`(0001) = `AccountUser`(테이블 `users`): `login_id`(unique), `tenant_id`(FK→tenants.tenant_id ON UPDATE CASCADE), `password_hash`, `is_admin`, `role`(0024, deferred), `is_active`, `contact_name`/`contact_tel` … → **account_status/approved_*/replace_*/invited_at/activated_at additive**.
- `audit_logs`(0001): FK 없음, JSONB payload.
- `user_sessions`(0007): 세션 원장.
- alembic **단일 head = `f8a9b0c10030`(0030)**. 신규 migration 0031 은 여기서 체인.

## 3. Migration 필요사항 (모두 additive)
- 신규 테이블 2개: `office_applications`, `activation_tokens`.
- `tenants` +6 컬럼, `users` +7 컬럼.
- backfill: 기존 tenant `service_status='active'`(is_active 기준)/`service_tier='managed_basic'`/`seat_limit = max(2, tenant 별 active user 수)`; 기존 user `account_status = active|disabled(is_active 기준)`.
- **신규 컬럼은 SQLAlchemy 모델에서 `deferred=True`** — 0031 미적용 DB(운영=0016)에서도 기존 `select(Tenant)`/`select(AccountUser)` full-row 조회가 깨지지 않게(0024 `role` 선례와 동일).

## 4. 기존 tenant/user 데이터 영향
- **무해**. 전부 additive + backfill. 기존 active 사용자 비활성화 없음. seat_limit 은 기존 tenant 에 대해 `max(2, 현재 active 수)` → 이미 3명이어도 정지/삭제 없음. 신규 승인 tenant 만 seat_limit=2 강제.

## 5. 파일 업로드(증빙) 지속성 — **차단 요인**
- 지속 가능한 범용 파일 스토리지 **없음**(운영 데이터는 PG, 일부 Drive 보조). Render 로컬 FS 는 ephemeral.
- **결정**: 증빙 업로드는 **feature flag(`FEATURE_OFFICE_APPLICATION_UPLOADS`, 기본 OFF)로 비활성화**. 신청·심사 데이터모델/UI 는 구현하되, 증빙은 "관리자에게 이메일 송부"(기존 signup 안내와 동일) 방식으로 우회. 저장계층 인터페이스(`evidence_storage`)만 분리해 두고 실제 저장은 미구현. 최종보고에 명시.

## 6. 보안 위험 / 대응
- 공개 신청 API 무인증 → **rate-limit + 입력검증 + 중복제출 차단** 필요(신규). PII 를 URL query 에 노출 금지(POST body).
- activation token: **원문 미저장, sha256 hash 만 저장 + 만료 + 1회성**. 승인 응답에서 raw 토큰 1회 반환(관리자가 대상자에게 전달, 이메일 자동발송 없음).
- 승인은 `require_admin` 서버검사(프론트 숨김 의존 금지). tenant_id 클라이언트 입력 불신.

## 7. 슬림화 가능 항목 / 유지해야 할 런타임 의존성
→ `slimming_baseline.md`, `dependency_review.md` 참조. 요약:
- 안전 제외(이미지 컨텍스트): `analysis/`(이미 제외), `backend/data/backups`, `**/*.backup-*`, `docs/`, `*.log`, `dev-trace.log`, `__pycache__`, `.pytest_cache`, `tsconfig.tsbuildinfo`, `page - 2.txt`류.
- **절대 제외 금지(런타임)**: `backend/data/manuals/unlocked_*.pdf`(PDF 뷰어 fallback), `backend/data/*.json`(guidelines 런타임 로드), `templates/`(HWPX), `alembic/`, `start.sh`, OCR 모델 경로.
- 의존성: `streamlit`/`streamlit-calendar`/`streamlit-aggrid` 런타임 import 0건(제거 후보) — 단, 표적 빌드 검증 전 제거하지 않고 문서화만. `paddleocr`/`paddlepaddle`/OmniMRZ 는 `ocr_service` lazy import → **유지**.

## 8. 결론
구조적 차단 사유 없음(증빙 저장만 flag-OFF 로 우회). 승인형 SaaS 는 기존 PG/auth/session/audit 를 재사용해 **additive** 로 구현 가능. 구현 계속 진행.
