"""manual update cron — 운영(server) PDF 자동생성 차단 가드 테스트.

최신 설계: PDF 는 수동 업로드, cron 은 감지+알림 전용. HANWOORY_ENV=server 에서는
pdf_batch_plan 이 절대 발생하지 않아야 한다.
실행: pytest backend/tests/test_manual_cron_pdf_guard.py
"""
import pytest

from backend.services import manual_auto_update as mu
from backend.services import manual_update_pg_service as svc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("HANWOORY_ENV", raising=False)
    monkeypatch.delenv("RUN_ENV", raising=False)
    monkeypatch.delenv("ALLOW_SERVER_PDF_BACKFILL", raising=False)


# ── 가드 헬퍼 ─────────────────────────────────────────────────────────────────
def test_server_pdf_disabled_helper(monkeypatch):
    # 비-server: 허용
    assert mu._server_pdf_disabled()[0] is False
    # server: 차단
    monkeypatch.setenv("HANWOORY_ENV", "server")
    assert mu._server_pdf_disabled()[0] is True
    # server + 명시 허용 flag: 허용
    monkeypatch.setenv("ALLOW_SERVER_PDF_BACKFILL", "1")
    assert mu._server_pdf_disabled()[0] is False


# ── generate_pdf_artifacts_for_version: server 에서 pdf_batch_plan 미발생 ──────
def test_generate_blocked_on_server_no_batch_plan(monkeypatch):
    monkeypatch.setenv("HANWOORY_ENV", "server")
    monkeypatch.setattr(svc, "pg_enabled", lambda: True)  # PG 켜진 것처럼

    events: list[str] = []
    monkeypatch.setattr(mu, "_log", lambda event, **kw: events.append(event))

    res = mu.generate_pdf_artifacts_for_version("v1")
    assert res["status"] == "skipped"
    assert "server_pdf_generation_disabled" in res["reason"]
    assert "pdf_batch_plan" not in events            # 핵심: batch plan 미발생
    assert "pdf_generation_skipped_server" in events


def test_generate_allowed_with_override(monkeypatch):
    # 명시 허용 flag 가 있으면 가드를 통과(이후 단계는 PG/네트워크라 별도) — 가드만 검증.
    monkeypatch.setenv("HANWOORY_ENV", "server")
    monkeypatch.setenv("ALLOW_SERVER_PDF_BACKFILL", "1")
    blocked, _ = mu._server_pdf_disabled()
    assert blocked is False


# ── run_worker_cycle: server + with_pdf=True 라도 PDF batch 미실행 ────────────
def test_run_worker_cycle_skips_pdf_on_server(monkeypatch):
    monkeypatch.setenv("HANWOORY_ENV", "server")
    monkeypatch.setattr(mu, "_emit_worker_preflight", lambda *a, **k: None)
    monkeypatch.setattr(mu, "run_auto_update_pg", lambda **k: {"status": "staged", "version": "v1"})

    called = {"gen": False}
    def _sentinel(*a, **k):
        called["gen"] = True
        return {"status": "generated"}
    monkeypatch.setattr(mu, "generate_pdf_artifacts_for_version", _sentinel)

    out = mu.run_worker_cycle(with_pdf=True, trigger="cron")
    assert out["pdf"]["status"] == "skipped"
    assert "server_pdf_generation_disabled" in out["pdf"]["reason"]
    assert called["gen"] is False  # PDF 생성 함수 자체가 호출되지 않음


def test_run_worker_cycle_with_pdf_false_skips(monkeypatch):
    # 기본값 with_pdf=False — 비-server 라도 PDF 단계 생략(감지+알림 전용).
    monkeypatch.setattr(mu, "_emit_worker_preflight", lambda *a, **k: None)
    monkeypatch.setattr(mu, "run_auto_update_pg", lambda **k: {"status": "staged", "version": "v1"})
    monkeypatch.setattr(mu, "generate_pdf_artifacts_for_version",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    out = mu.run_worker_cycle(trigger="cron")  # with_pdf 기본 False
    assert out["pdf"]["status"] == "skipped"
    assert out["pdf"]["reason"] == "with_pdf=False"
