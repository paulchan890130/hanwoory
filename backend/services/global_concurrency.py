"""[로컬 PoC — A안 보강] OCR/DOC 전역 동시수 제한.

combined + uvicorn workers>=2 에서는 process-local asyncio.Semaphore 가 프로세스
경계를 넘지 못해 전역 제한이 되지 않는다(=workers 수만큼 동시 허용). 그래서 여기서는
PostgreSQL **advisory lock** 으로 프로세스 경계를 넘는 전역 1 제한을 건다.

advisory lock 채택 이유(限limiter table 대비):
- migration 불필요(스키마 변경 0) — 새 테이블/컬럼 없음.
- 크래시/연결 종료 시 락이 **자동 해제** — limiter table 의 "프로세스가 죽으면 카운터가
  멈춤" 위험(stale counter / reaper 필요)이 없다.

PG 미구성(DATABASE_URL 없음) 환경에서는 process-local Semaphore(1) 로 graceful
degrade 한다(전역 보장은 안 되며 경고 로그를 남긴다).

비블로킹(non_blocking=True)이면 이미 점유 중일 때 즉시 ConcurrencyBusy 를 던진다
(기존 backend/routers/scan.py 의 sem.locked() -> busy 응답과 동일한 의미).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import contextmanager

from sqlalchemy import text

from backend.db import session as _db

log = logging.getLogger("global_concurrency")

# advisory lock 키 — 임의 고정 정수(다른 advisory lock 사용처와 충돌 방지용 네임스페이스).
OCR_LOCK_KEY = 815001
DOC_LOCK_KEY = 815002

# 대기 정책(초). 스캔/문서생성이 겹치면 즉시 거절하지 않고 이 시간만큼 순서를 기다린다.
# 동시 스캔은 드물고 대부분 한 명이 한 번씩 처리하므로, '기다렸다 이어서 처리'가 자연스럽다.
# - OCR: 실제 사무실 단독 처리는 약 2초 → 30초면 겹쳐도 충분한 여유.
# - DOC: 문서생성은 OCR보다 길어질 수 있어 60초.
# 모두 env(OCR_WAIT_SECONDS / DOC_WAIT_SECONDS)로 운영 중 조정 가능.
OCR_WAIT_SECONDS = float(os.environ.get("OCR_WAIT_SECONDS", "30") or "30")
DOC_WAIT_SECONDS = float(os.environ.get("DOC_WAIT_SECONDS", "60") or "60")

_LOCAL_SEMS: dict[int, asyncio.Semaphore] = {}
_LOCAL_SYNC_SEMS: dict[int, threading.Semaphore] = {}
_local_sync_lock = threading.Lock()
_warned_local = False
_warned_local_sync = False


class ConcurrencyBusy(Exception):
    """전역 슬롯이 이미 점유 중이라 즉시 거절(503 busy)."""


def _local_sem(key: int) -> asyncio.Semaphore:
    sem = _LOCAL_SEMS.get(key)
    if sem is None:
        sem = asyncio.Semaphore(1)
        _LOCAL_SEMS[key] = sem
    return sem


def _pg_try_lock(key: int):
    """동기. 성공 시 (conn, True), 점유 중이면 (None, False). 예외는 호출측에서 처리."""
    engine = _db.get_engine()
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        if got:
            return conn, True
        conn.close()
        return None, False
    except Exception:
        conn.close()
        raise


def _pg_unlock(conn, key: int) -> None:
    """동기. unlock 후 연결 반환. 어떤 경우에도 connection 을 닫는다."""
    try:
        conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
    finally:
        conn.close()


class global_limit:
    """async context manager — 전역 동시수 1 게이트(대기 가능).

    사용:
        async with global_limit(OCR_LOCK_KEY, wait_timeout=OCR_WAIT_SECONDS):
            result = await asyncio.to_thread(...)

    동작:
    - 슬롯이 비어 있으면 즉시 획득.
    - 점유 중이면 wait_timeout 초까지 0.5초 간격으로 풀리길 기다렸다가 획득(이벤트루프 비블로킹).
    - wait_timeout 까지도 못 잡으면 ConcurrencyBusy(호출측이 친절한 안내 반환).
    - wait_timeout=0 이면 즉시 거절(기존 동작).

    PG 구성 시 advisory lock(프로세스 경계 넘는 전역 1), 미구성 시 process-local Semaphore.
    """

    def __init__(self, key: int, *, wait_timeout: float = 0.0, poll: float = 0.5):
        self.key = key
        self.wait_timeout = max(0.0, float(wait_timeout))
        self.poll = poll
        self._conn = None
        self._local: asyncio.Semaphore | None = None

    async def __aenter__(self):
        if _db.is_configured():
            waited = 0.0
            while True:
                conn, got = await asyncio.to_thread(_pg_try_lock, self.key)
                if got:
                    self._conn = conn
                    return self
                if waited >= self.wait_timeout:
                    raise ConcurrencyBusy()
                await asyncio.sleep(self.poll)
                waited += self.poll

        # ── PG 미구성: process-local fallback (전역 보장 X) ──
        global _warned_local
        if not _warned_local:
            log.warning(
                "PG 미구성 — 전역 동시수 제한이 process-local Semaphore 로 degrade됩니다 "
                "(workers>=2 에서 전역 1 보장 안 됨)."
            )
            _warned_local = True
        sem = _local_sem(self.key)
        if self.wait_timeout <= 0:
            if sem.locked():
                raise ConcurrencyBusy()
            await sem.acquire()
        else:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=self.wait_timeout)
            except asyncio.TimeoutError:
                raise ConcurrencyBusy()
        self._local = sem
        return self

    async def __aexit__(self, *exc):
        if self._conn is not None:
            try:
                await asyncio.to_thread(_pg_unlock, self._conn, self.key)
            finally:
                self._conn = None
        if self._local is not None:
            self._local.release()
            self._local = None
        return False


def _local_sync_sem(key: int) -> threading.Semaphore:
    with _local_sync_lock:
        sem = _LOCAL_SYNC_SEMS.get(key)
        if sem is None:
            sem = threading.Semaphore(1)
            _LOCAL_SYNC_SEMS[key] = sem
        return sem


@contextmanager
def global_limit_sync(key: int, *, wait_timeout: float = DOC_WAIT_SECONDS, poll: float = 0.25):
    """동기 핸들러용 전역 동시수 1 게이트(DOC 문서생성 등).

    FastAPI 의 동기(`def`) 핸들러는 anyio 외부 스레드풀에서 실행되므로 여기서 blocking
    대기를 해도 이벤트루프를 막지 않는다. DOC 는 사용자가 의도한 산출물 생성이므로
    '거절'보다 '직렬화(짧게 대기)'가 자연스럽다 → pg_try_advisory_lock 을 poll 하며
    최대 wait_timeout 초 대기 후에도 못 잡으면 ConcurrencyBusy(503).

    PG 미구성 시 process-local threading.Semaphore(1) blocking 대기(전역 보장 X).
    """
    if _db.is_configured():
        engine = _db.get_engine()
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        acquired = False
        try:
            waited = 0.0
            while True:
                got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
                if got:
                    acquired = True
                    break
                if waited >= wait_timeout:
                    raise ConcurrencyBusy()
                time.sleep(poll)
                waited += poll
            yield
        finally:
            if acquired:
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                finally:
                    conn.close()
            else:
                conn.close()
        return

    # ── PG 미구성: process-local fallback (전역 보장 X) ──
    global _warned_local_sync
    if not _warned_local_sync:
        log.warning(
            "PG 미구성 — DOC 전역 동시수 제한이 process-local Semaphore 로 degrade됩니다 "
            "(workers>=2 에서 전역 1 보장 안 됨)."
        )
        _warned_local_sync = True
    sem = _local_sync_sem(key)
    if not sem.acquire(timeout=wait_timeout):
        raise ConcurrencyBusy()
    try:
        yield
    finally:
        sem.release()
