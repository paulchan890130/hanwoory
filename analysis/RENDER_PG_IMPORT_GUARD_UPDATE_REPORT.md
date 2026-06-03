# Render PG Import Guard Update — Report

작성일: 2026-06-03 · 브랜치: `feat/postgres-foundation`

## Problem
Render PostgreSQL is provisioned and `alembic upgrade head` succeeded, but the
Excel snapshot importer (`backend/scripts/import_excel_snapshot_to_pg_local.py`)
is blocked by the local-only guard:

```
[local-guard] DATABASE_URL host '...render.com' is NOT in ['127.0.0.1','::1','localhost'].
```

So no PG `users` row exists for jpup, and `migrate_account_password_hashes.py`
reports `jpup: SKIP (no PG users row — run the importer first)`.

## What changed
The local-only guard is **kept**. A narrow, explicit, confirmation-gated remote
path was added and centralized so the importer and the password-migration
script share one policy.

- **`backend/db/local_guard.py`** — added the single source of truth:
  `REMOTE_CONFIRM_STRING`, `resolve_execution_mode(url, *, allow_remote, confirm,
  reset_requested, command_hint, say)`, plus `mask_host` / `looks_render_host` /
  `database_host`. `assert_local_database_url` is unchanged and still used for the
  local/unset cases.
- **`backend/scripts/import_excel_snapshot_to_pg_local.py`** — new flags
  `--allow-remote-render-pg` and `--confirm`; the bare guard call on the
  `--execute` path now delegates to `resolve_execution_mode`. Runs **only on the
  `--execute` path** (after the dry-run short-circuit), so dry-run never opens a
  DB or touches the gate.
- **`backend/scripts/migrate_account_password_hashes.py`** — same two flags; the
  `--apply` path (which previously called `assert_local_database_url` and so was
  also blocked on Render) now delegates to `resolve_execution_mode`. **Dry-run is
  read-only and needs neither flag** (it connects to read/compare but never
  writes). Remote `--apply` requires `--allow-remote-render-pg` + exact `--confirm`.

### Decision matrix
| DATABASE_URL host | flags | result |
|---|---|---|
| loopback (`127.0.0.1`/`localhost`/`::1`) | any | **LOCAL** — allowed (unchanged) |
| unset | any | `assert_local_database_url` → exit 2 (unchanged) |
| non-local | (none) | **ABORT** (exit 3) + prints exact command |
| non-local | `--allow-remote-render-pg` only | **ABORT** — `--confirm` mismatch |
| non-local | allow + wrong `--confirm` | **ABORT** |
| non-local | `--execute` + allow + exact `--confirm` | **REMOTE_RENDER_CONFIRMED** — allowed |
| non-local | `--reset-local-pg` (+allow+confirm) | **ABORT** — reset never runs remote |

Notes:
- Remote allowed when host is Render-style (`render.com` / `dpg-…`) **or** any
  clearly non-local host that is explicitly confirmed (requirement 4).
- **Hard block (req 6):** `--reset-local-pg` against a non-local host aborts even
  with the allow flag present — checked before the confirm check.
- **Logging (req 8):** prints masked target host (credentials never included —
  `urlparse().hostname` excludes `user:pass`) and execution mode
  (`LOCAL` / `REMOTE_RENDER_CONFIRMED`). No passwords printed.
- Remote mode does not auto-reset/clear; importer uses row-level upserts.

## Verification (no DB connected, no import executed)
- `py_compile` for `local_guard.py` + both scripts ✅
- Shared `resolve_execution_mode` unit scenarios (8/8 PASS): local→LOCAL; remote
  no-confirm→abort; remote allow+wrong-confirm→abort; remote
  allow+confirm→REMOTE_RENDER_CONFIRMED; remote+reset hard-block→abort;
  non-local-non-render+confirm→allowed; local+reset→LOCAL; unset→SystemExit(2).
- Importer `--only all` (dry-run) with a remote URL set → "No DB connection opened" ✅
- Importer `--only all --execute` with remote URL, no confirm → abort (exit 3)
  printing the exact remote command, masked host ✅
- Migration-script integration test (`test_account_pw_migration.py`) still 8/8
  PASS through the refactored `--apply` gate (local target). ✅

## Commands to run (manual — NOT executed automatically)
```
# 1) Dry-run (no DB opened) — confirm roles/files
.venv\Scripts\python.exe -X utf8 backend\scripts\import_excel_snapshot_to_pg_local.py --only all

# 2) Import into Render PG (explicit, confirmed; do NOT add --reset-local-pg)
.venv\Scripts\python.exe -X utf8 backend\scripts\import_excel_snapshot_to_pg_local.py --only all --execute --allow-remote-render-pg --confirm "I-UNDERSTAND-IMPORT-TO-RENDER-PG"

# 3) After successful import — reconcile jpup's password hash
#    dry-run is read-only (no flags needed):
.venv\Scripts\python.exe -X utf8 backend\scripts\migrate_account_password_hashes.py --login-id jpup --dry-run
#    apply to Render needs the same explicit confirmation:
.venv\Scripts\python.exe -X utf8 backend\scripts\migrate_account_password_hashes.py --login-id jpup --apply --allow-remote-render-pg --confirm "I-UNDERSTAND-IMPORT-TO-RENDER-PG"
```
(`DATABASE_URL` must point at the Render PG when running steps 2–3.)

## Safety preserved
Guard not removed; remote not default; no destructive reset added; `--reset-local-pg`
hard-blocked remotely; no tables cleared automatically; nothing pushed/deployed.
