"""
backend/services/cache_service.py
----------------------------------
Lightweight in-memory TTL cache for Google Sheets API response caching.

Tenant-safe: all cache keys include tenant_id — no cross-tenant leakage.
Thread-safe: single threading.Lock around all _store mutations.

Usage:
    from backend.services.cache_service import cache_get, cache_set, cache_invalidate

    val = cache_get(tenant_id, "tasks:active")
    if val is None:
        val = expensive_read()
        cache_set(tenant_id, "tasks:active", val, ttl=30.0)

    # On mutation:
    cache_invalidate(tenant_id, "tasks:active")
"""
import threading
import time
from typing import Any, Optional

_lock = threading.Lock()
_store: dict[str, tuple[Any, float]] = {}   # key → (value, expire_monotonic)


def _key(tenant_id: str, name: str) -> str:
    return f"{tenant_id}::{name}"


def cache_get(tenant_id: str, name: str) -> Optional[Any]:
    """Return cached value or None if missing/expired."""
    k = _key(tenant_id, name)
    with _lock:
        entry = _store.get(k)
        if entry is None:
            return None
        val, expires = entry
        if time.monotonic() > expires:
            del _store[k]
            return None
        return val


def cache_set(tenant_id: str, name: str, value: Any, ttl: float) -> None:
    """Store value with TTL (seconds)."""
    k = _key(tenant_id, name)
    with _lock:
        _store[k] = (value, time.monotonic() + ttl)


def cache_invalidate(tenant_id: str, name: str) -> None:
    """Remove a specific cache entry immediately."""
    k = _key(tenant_id, name)
    with _lock:
        _store.pop(k, None)
