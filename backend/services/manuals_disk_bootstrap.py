"""manuals_disk_bootstrap — Persistent Disk 최초 시드(seed) 헬퍼.

MANUALS_DATA_DIR 를 이미지 baked 기본 경로(backend/data/manuals)와 다른 경로
(예: Render Persistent Disk `/data/manuals`)로 지정한 경우, 운영에 꼭 필요한 읽기 전용
자산만 **없을 때 한 번** 복사한다.

엄격한 원칙
-----------
* 기존 파일을 절대 덮어쓰지 않는다 (dst 가 이미 있으면 건너뜀).
* immigration_guidelines_db_v2.json(운영 DB)은 복사 대상이 아니다 — 이미지 baked 유지.
* staging/incoming/decisions/review JSON 같은 "생성물"은 시드하지 않는다(런타임이 만든다).
* 어떤 예외도 서버 기동을 막지 않는다 — 호출부에서 try/except 로 감싼다.

시드 대상(있을 때만):
  - unlocked_체류민원.pdf / unlocked_사증민원.pdf  (운영 PDF 뷰어가 읽는 파일)
  - baseline/  (rhwp diff 기준 — 디렉토리째, 대상에 없을 때만 통째 복사)
"""
from __future__ import annotations
import os
import shutil
from pathlib import Path

# 시드할 운영 PDF 파일명 (뷰어가 읽는 unlocked_*.pdf 만)
_SEED_FILES = ("unlocked_체류민원.pdf", "unlocked_사증민원.pdf")
# 시드할 디렉토리 (대상에 없을 때만 통째 복사)
_SEED_DIRS = ("baseline",)


def bootstrap_manuals_dir() -> dict:
    """MANUALS_DATA_DIR 가 baked 기본과 다르면 운영 자산을 '없을 때만' 복사.

    반환: 수행 요약 dict (로깅용). baked==target 이거나 source 부재 시 no-op."""
    try:
        from config import MANUALS_DATA_DIR, BASE_DIR
    except Exception as e:
        return {"skipped": f"config import failed: {e}"}

    source = Path(BASE_DIR) / "backend" / "data" / "manuals"  # 이미지 baked 기본 경로
    target = Path(MANUALS_DATA_DIR)

    # 디스크 분리를 안 했으면(기본 경로 그대로) 할 일 없음
    try:
        if target.resolve() == source.resolve():
            return {"skipped": "MANUALS_DATA_DIR == baked default (no disk override)"}
    except Exception:
        # resolve 실패해도 문자열 비교로 한 번 더 방어
        if str(target) == str(source):
            return {"skipped": "MANUALS_DATA_DIR == baked default (no disk override)"}

    summary: dict = {"target": str(target), "copied_files": [], "copied_dirs": [], "notes": []}

    if not source.exists():
        summary["notes"].append(f"baked source absent ({source}) — nothing to seed")
        return summary

    target.mkdir(parents=True, exist_ok=True)

    # 파일: dst 가 없을 때만 복사 (덮어쓰기 절대 없음)
    for name in _SEED_FILES:
        s = source / name
        d = target / name
        if s.exists() and not d.exists():
            shutil.copy2(s, d)
            summary["copied_files"].append(name)

    # 디렉토리: dst 가 없을 때만 통째 복사
    for name in _SEED_DIRS:
        s = source / name
        d = target / name
        if s.is_dir() and not d.exists():
            shutil.copytree(s, d)
            summary["copied_dirs"].append(name)

    return summary
