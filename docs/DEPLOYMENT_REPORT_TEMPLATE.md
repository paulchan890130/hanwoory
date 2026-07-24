# 배포 보고서 템플릿 (필수 게이트)

SEV-1(관리자 로그인 장애, 2026-07-24) 재발방지. **아래 항목이 모두 채워지지 않은 배포는 "완료"로 보고하지 않는다.**
특히 공개 홈페이지 200 이나 `/health`→`/login` 리다이렉트를 **backend·login 정상 증거로 사용하지 않는다.**

## 좌표
- [ ] CI run ID / URL:
- [ ] 시작(직전) main SHA:
- [ ] 배포 head SHA:
- [ ] Render Live SHA (대시보드 직접 확인 — 미확인이면 "미확인"이라고 명시):
- [ ] alembic 단일 head:
- [ ] 운영 DB revision (읽기 전용 확인) + 신규 migration 적용 필요 여부:

## CI (green 필수)
- [ ] backend:
- [ ] frontend:
- [ ] e2e:
- [ ] PostgreSQL 통합 / migration dry-run:

## 아티팩트 검증 (배포되는 이미지 기준)
- [ ] Docker `Dockerfile.combined` build 성공:
- [ ] 컨테이너 내부 `curl -f http://127.0.0.1:8000/health` → 200 `{"status":"ok"}`:
- [ ] 컨테이너 정상 관리자 `POST /api/auth/login` → 200:
- [ ] 컨테이너 잘못된 비밀번호 → 401:
- [ ] 컨테이너 `GET /api/auth/me` (로그인 토큰) → 200:
- [ ] 프론트 프록시(:3000) 경유 `POST /api/auth/login` → 200:
- [ ] backend 프로세스 생존(로그인 배터리 후 /health 재확인 200):
- [ ] (권장) 운영 스키마 gap 재현(deferred 컬럼 DROP) 상태에서도 로그인 200:

> 위 Docker 검증은 `scripts/docker_auth_smoke.sh` 로 재현할 수 있다.

## 운영 복구 확인 (배포 후)
- [ ] 사용자 직접 관리자 로그인 200 (비밀번호 공유받지 않음):
- [ ] dashboard 진입 / `GET /api/auth/me` 200:
- [ ] 개인정보·비밀번호·hash·token 로그 노출 없음:

## 남은 위험 / 롤백 기준
- 남은 위험:
- known-good 롤백 SHA:
