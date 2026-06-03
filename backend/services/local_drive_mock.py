"""Local mock for Google Drive folder/file operations.

Activated by ``FEATURE_LOCAL_DRIVE_MOCK=true``. When on, ``admin.py``'s
workspace-creation flow doesn't reach the real Drive API; instead each
operation returns a sentinel ID so the rest of the flow (writing
``customer_sheet_key`` / ``work_sheet_key`` / ``folder_id`` to the
``Accounts`` row or local PG ``tenants`` row) keeps working.

The mock also writes a manifest file under ``.local_pg_beta_drive/`` so a
developer can see what would have been created, but never touches Google
Drive or the production parent folder.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_ROOT = Path(__file__).resolve().parent.parent.parent / ".local_pg_beta_drive"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ensure_root() -> Path:
    _ROOT.mkdir(parents=True, exist_ok=True)
    return _ROOT


def mock_folder_id(login_id: str) -> str:
    return f"local-folder-{login_id}-{uuid.uuid4().hex[:8]}"


def mock_sheet_id(kind: str, login_id: str) -> str:
    """``kind`` is one of ``customer`` / ``work`` / ``other``."""
    return f"local-sheet-{kind}-{login_id}-{uuid.uuid4().hex[:8]}"


def provision_workspace(login_id: str, office_name: Optional[str] = None) -> dict:
    """Simulate the workspace-creation flow without touching Drive.

    Returns the same shape ``admin.py:_create_workspace`` produces on
    success, so the caller doesn't need to branch beyond checking the
    feature flag.
    """
    root = _ensure_root()
    folder_id = mock_folder_id(login_id)
    customer_sheet_key = mock_sheet_id("customer", login_id)
    work_sheet_key = mock_sheet_id("work", login_id)

    manifest = {
        "login_id": login_id,
        "office_name": office_name or "",
        "folder_id": folder_id,
        "customer_sheet_key": customer_sheet_key,
        "work_sheet_key": work_sheet_key,
        "provisioned_at": _now_iso(),
        "note": "Local mock — no Google Drive call. Real production must use admin.py path with FEATURE_LOCAL_DRIVE_MOCK off.",
    }
    manifest_path = root / f"{login_id}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "ok": True,
        "stages": {
            "folder_create":    {"status": "mocked", "id": folder_id,         "error": None},
            "customer_copy":    {"status": "mocked", "id": customer_sheet_key, "error": None},
            "work_copy":        {"status": "mocked", "id": work_sheet_key,     "error": None},
            "accounts_update":  {"status": "deferred-to-caller", "error": None},
        },
        "folder_id": folder_id,
        "customer_sheet_key": customer_sheet_key,
        "work_sheet_key": work_sheet_key,
        "is_active": False,
        "drive_user": "LOCAL_MOCK",
        "drive_quota": None,
        "message": f"Local mock workspace created. Manifest: {manifest_path}",
    }
