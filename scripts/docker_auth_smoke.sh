#!/usr/bin/env bash
# Docker 인증 smoke — 배포되는 combined 이미지가 실제로 로그인 가능한지 검증.
# SEV-1(관리자 로그인 장애) 재발방지. 공개 홈 200/health 리다이렉트를 증거로 쓰지 않는다.
#
# 검증: 컨테이너 내부 /health 200 · 관리자 login 200 · wrong 401 · /me 200 · 프론트(:3000) 프록시 200.
# (선택) DRIFT=1 이면 deferred 컬럼(role/source_application_id/onboarding_*)을 DROP 해
#         운영 스키마 gap 상태에서도 로그인이 되는지 확인한다.
#
# 사용법(호스트에 docker 필요):
#   IMAGE=kid-combined:latest bash scripts/docker_auth_smoke.sh
#   DRIFT=1 IMAGE=kid-combined:latest bash scripts/docker_auth_smoke.sh
#
# 격리 throwaway 리소스만 사용하며 운영 DB/키/배포를 건드리지 않는다.
set -euo pipefail

IMAGE="${IMAGE:?set IMAGE=<combined image tag>}"
PW="Secret123!"
PGNAME="kid-authsmoke-pg"
APPNAME="kid-authsmoke-app"
PGPORT="${PGPORT:-5470}"
APPPORT="${APPPORT:-3020}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-python}"

cleanup() { docker rm -f "$APPNAME" "$PGNAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

cleanup
docker run -d --name "$PGNAME" -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=kidverify -p "${PGPORT}:5432" postgres:17-alpine >/dev/null
for i in $(seq 1 30); do docker exec "$PGNAME" pg_isready -U postgres >/dev/null 2>&1 && break; sleep 1; done

# 전체 스키마 생성 + 관리자 seed (+ optional drift). 운영 DB 아님.
DRIFT="${DRIFT:-0}" DATABASE_URL="postgresql+psycopg://postgres:verify@localhost:${PGPORT}/kidverify" \
  PYTHONPATH="$REPO_ROOT" "$PY" - <<'PYEOF'
import os, importlib, pkgutil
os.environ.setdefault("HANWOORY_ENV", "server")
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from backend.db.base import Base
import backend.db.models as models_pkg
for m in pkgutil.iter_modules(models_pkg.__path__):
    importlib.import_module(f"backend.db.models.{m.name}")
from backend.db.models.tenant import Tenant
from backend.db.models.user import AccountUser
from backend.services.accounts_service import hash_password
eng = create_engine(os.environ["DATABASE_URL"], future=True)
Base.metadata.drop_all(eng); Base.metadata.create_all(eng)
SL = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False, class_=Session)
with SL() as s:
    s.add(Tenant(tenant_id="of-1", office_name="office-smoke", is_active=True))
    s.add(AccountUser(login_id="admin@of1.kr", tenant_id="of-1",
                      password_hash=hash_password("Secret123!"), is_admin=True, is_active=True))
    s.commit()
if os.environ.get("DRIFT") == "1":
    with eng.begin() as c:
        for t, col in [("users","role"),("users","onboarding_completed_version"),
                       ("users","onboarding_completed_at"),("tenants","source_application_id")]:
            c.execute(text(f'ALTER TABLE {t} DROP COLUMN {col}'))
    print("seeded + drifted")
else:
    print("seeded")
eng.dispose()
PYEOF

docker run -d --name "$APPNAME" \
  -e DATABASE_URL="postgresql+psycopg://postgres:verify@host.docker.internal:${PGPORT}/kidverify" \
  -e JWT_SECRET_KEY="authsmoke-secret" -e HANWOORY_ENV=server \
  -p "${APPPORT}:3000" "$IMAGE" >/dev/null

for i in $(seq 1 60); do
  code=$(docker exec "$APPNAME" sh -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health' 2>/dev/null || true)
  [ "$code" = "200" ] && break; sleep 2
done
[ "$code" = "200" ] || { echo "FAIL: backend /health != 200 ($code)"; docker logs "$APPNAME" | tail -40; exit 1; }

login() { docker exec "$APPNAME" sh -c "curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' -d '$1'"; }
ADMIN=$(login '{"login_id":"admin@of1.kr","password":"Secret123!"}')
WRONG=$(login '{"login_id":"admin@of1.kr","password":"nope"}')
PROXY=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://localhost:${APPPORT}/api/auth/login" -H 'Content-Type: application/json' -d '{"login_id":"admin@of1.kr","password":"Secret123!"}')
ME=$(docker exec "$APPNAME" sh -c '
  T=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login -H "Content-Type: application/json" -d "{\"login_id\":\"admin@of1.kr\",\"password\":\"Secret123!\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"access_token\"])")
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/auth/me -H "Authorization: Bearer $T"')
HEALTH2=$(docker exec "$APPNAME" sh -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health')

echo "health=200 admin=$ADMIN wrong=$WRONG proxy=$PROXY me=$ME health_after=$HEALTH2 drift=${DRIFT:-0}"
[ "$ADMIN" = "200" ] && [ "$WRONG" = "401" ] && [ "$PROXY" = "200" ] && [ "$ME" = "200" ] && [ "$HEALTH2" = "200" ] \
  && echo "AUTH SMOKE: PASS" || { echo "AUTH SMOKE: FAIL"; exit 1; }
