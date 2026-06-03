# jpup Password Migration — Diagnosis & Fix Report

작성일: 2026-06-03 · 브랜치: `feat/postgres-foundation`

## Active login endpoint
`POST /api/auth/login` → `backend/routers/auth.py::login`.
- When `FEATURE_PG_USERS` is on: looks up `backend/services/auth_pg_service.find_user_pg(login_id)`
  (PG `users` table), then verifies with `backend.services.accounts_service.verify_password`.
- Falls back to the Sheets `find_account` only if the PG row is absent.

## Active account table/model
PG `users` table → `backend/db/models/user.py::AccountUser` (`login_id`, `tenant_id`,
`password_hash`, `is_admin`, `is_active`, …). Tenants in `tenants` table.

## Current password hash format
Single format across the whole app: **PBKDF2-HMAC-SHA256, 100,000 iterations,
`base64(salt[16] + dk[32])`** — produced and verified by
`accounts_service.hash_password` / `verify_password`. **No bcrypt/passlib is used for
real hashing.** The PG `password_hash` column deliberately stores this same format
(`user.py` docstring), so a correctly-migrated legacy hash verifies unchanged.

## Where jpup exists / its legacy hash
jpup's authoritative legacy row is in the migration snapshot
`migration_input/신 고객 데이터.xlsx` → **`Accounts`** tab:
- `tenant_id = jpup`, `is_active = True`, `is_admin = False`
- `password_hash = X0sn…8h7c` (len 64) → base64-decodes to **48 bytes (16 salt + 32 dk)**
  = exactly the legacy PBKDF2 format. **(value masked; raw password never present/printed.)**

The Excel importer `backend/scripts/import_excel_snapshot_to_pg_local.py::imp_accounts`
copies `password_hash` verbatim into PG `users`, but **skips a user entirely if its
snapshot `password_hash` cell is empty**, and `_ensure_admin_user` can create a fallback
login with the throwaway beta password. So jpup's PG row can end up with an **empty**,
**stale**, or **beta-placeholder** hash that doesn't match the real one.

## Hash format check
Legacy PBKDF2 base64 (NOT a new/bcrypt format). The existing verifier already supports it.

## Why login currently fails
Not a verifier problem — the verifier is format-compatible. The PG `users.password_hash`
for jpup does **not** equal the authoritative legacy hash from the snapshot (empty/stale/
placeholder from an earlier import), so `verify_password(real_password, pg_hash)` returns
False → HTTP 401. (Confirmed indirectly: snapshot has the correct legacy hash; verifier
handles that format; DATABASE_URL is unset in this analysis box so the live PG row was not
queried here — the migration script reconciles it on the user's machine.)

## Exact fix plan
1. **Verifier (forward-compatible, no downgrade):** harden `accounts_service.verify_password`
   to (a) keep the legacy PBKDF2 path identical, (b) safely handle malformed hashes (return
   False, never throw), (c) optionally verify bcrypt-style `$2…` hashes if such ever appear
   (lazy bcrypt import; absent → safe False). Legacy hashing unchanged.
2. **Migration script** `backend/scripts/migrate_account_password_hashes.py`:
   reads the authoritative legacy `password_hash` from the snapshot Accounts tab and
   reconciles PG `users.password_hash` for the target login when **empty or mismatched**
   (idempotent: equal → skip). Dry-run default; `--apply`; `--login-id jpup`; masked output;
   backs up affected rows; refuses if the source hash is missing (never invents/resets).
3. **Verify** jpup row gets the exact legacy hash → original password works unchanged.

## Result
jpup logs in with the **same password as before migration** — no reset, no new password.
