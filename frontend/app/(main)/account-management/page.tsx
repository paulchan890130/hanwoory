"use client";
// 우리 사무소 계정 — 사무소 주계정(office_admin)이 자기 tenant 서브계정(직원)을 관리.
// tenant_id 는 서버(JWT)에서만 취득. office_staff 접근 시 서버 403 → 접근거부 표시.
// 주계정 자기 정지/교체·다른 tenant·세 번째 계정 생성은 서버에서 차단(여기선 노출도 안 함).
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { myOfficeApi, type TenantSummary, type OfficeAccount } from "@/lib/api";

const ST_KO: Record<string, string> = { active: "활성", disabled: "정지", suspended: "정지", invited: "초대(미활성)", replaced: "교체됨" };

export default function AccountManagementPage() {
  const [state, setState] = useState<"loading" | "ready" | "denied" | "disabled">("loading");
  const [data, setData] = useState<TenantSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [reissued, setReissued] = useState<{ login: string; token: string } | null>(null);

  const load = useCallback(() => {
    myOfficeApi.accounts()
      .then((r) => { setData(r.data); setState("ready"); })
      .catch((e) => {
        const s = e?.response?.status;
        setState(s === 403 ? "denied" : s === 404 ? "disabled" : "ready");
      });
  }, []);
  useEffect(() => { load(); }, [load]);

  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const err = (e: unknown) => toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "실패");

  const doReissue = async (a: OfficeAccount) => {
    if (!confirm(`${a.name}(${a.login_id}) 서브계정의 활성화 링크를 재발급하시겠습니까? 기존 링크는 즉시 무효화됩니다.`)) return;
    setBusy(true);
    try { const r = await myOfficeApi.reissue(a.login_id); setReissued({ login: a.login_id, token: (r.data as { activation_token: string }).activation_token }); toast.success("활성화 링크 재발급됨"); }
    catch (e) { err(e); } finally { setBusy(false); load(); }
  };
  const doSuspend = async (a: OfficeAccount) => {
    if (!confirm(`${a.name} 서브계정을 정지하시겠습니까? 즉시 로그인이 차단됩니다.`)) return;
    setBusy(true); try { await myOfficeApi.suspend(a.login_id); toast.success("정지됨"); } catch (e) { err(e); } finally { setBusy(false); load(); }
  };
  const doRestore = async (a: OfficeAccount) => {
    setBusy(true); try { await myOfficeApi.restore(a.login_id); toast.success("복구됨"); } catch (e) { err(e); } finally { setBusy(false); load(); }
  };
  const doReplace = async (a: OfficeAccount) => {
    const name = prompt("새 직원 이름:"); if (!name) return;
    const email = prompt("새 직원 이메일(로그인 ID):"); if (!email) return;
    if (!confirm(`${a.name}(${a.login_id})을 새 직원 ${name}(${email})으로 교체하시겠습니까? 기존 계정은 로그인 차단되고 복구할 수 없습니다.`)) return;
    setBusy(true);
    try { const r = await myOfficeApi.replace(a.login_id, { new_name: name, new_email: email }); setReissued({ login: email, token: (r.data as { activation_token: string }).activation_token }); toast.success("교체됨 — 새 계정 활성화 링크가 발급되었습니다."); }
    catch (e) { err(e); } finally { setBusy(false); load(); }
  };

  if (state === "loading") return <div className="hw-card" style={{ color: "var(--hw-text-sub)" }}>불러오는 중...</div>;
  if (state === "denied") return (
    <div className="hw-card" style={{ color: "#C53030", lineHeight: 1.7 }}>
      이 화면은 사무소 주계정(관리자) 전용입니다. 접근 권한이 없습니다.
    </div>
  );
  if (state === "disabled") return (
    <div className="hw-card" style={{ color: "var(--hw-text-sub)", lineHeight: 1.7 }}>
      사무소 계정 관리 기능이 아직 활성화되지 않았습니다. (관리자 준비중)
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <h1 className="hw-page-title">우리 사무소 계정</h1>
      {data && (
        <div className="hw-card">
          <div style={{ fontSize: 13, color: "var(--hw-text-sub)", marginBottom: 10 }}>
            {data.office_name} · 상태 {ST_KO[data.service_status] || data.service_status} · 좌석 {data.active_count}/{data.seat_limit}
          </div>
          <table className="hw-table">
            <thead><tr><th>구분</th><th>이름</th><th>로그인 ID</th><th>상태</th><th>활성화</th><th style={{ width: 260 }}>관리</th></tr></thead>
            <tbody>
              {data.accounts.map((a) => (
                <tr key={a.login_id}>
                  <td style={{ fontWeight: 700 }}>{a.is_admin ? "주계정" : "직원"}</td>
                  <td>{a.name}</td>
                  <td style={{ fontFamily: "monospace", fontSize: 12 }}>{a.login_id}</td>
                  <td><span style={{ color: a.is_active ? "#276749" : "#C53030", fontWeight: 600 }}>{ST_KO[a.account_status] || a.account_status}</span></td>
                  <td style={{ fontSize: 11, color: "#718096" }}>{a.activated_at ? "완료" : a.invited_at ? "미활성" : "—"}</td>
                  <td>
                    {a.is_admin ? (
                      <span style={{ fontSize: 11, color: "#A0AEC0" }}>주계정은 시스템 관리자에게 문의</span>
                    ) : (
                      // 상태 전이에 맞춘 버튼만 노출(서버도 동일 규칙으로 강제):
                      //  invited → 활성화 링크 재발급 / active → 정지·교체 / suspended → 복구
                      //  replaced → 조작 불가 / disabled(레거시) → 안내 문구
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {a.account_status === "invited" && (
                          <button className="hw-filter-btn" disabled={busy} onClick={() => doReissue(a)}>활성화 링크 재발급</button>
                        )}
                        {a.account_status === "active" && (
                          <>
                            <button className="hw-filter-btn" disabled={busy} onClick={() => doSuspend(a)}>정지</button>
                            <button className="hw-filter-btn" disabled={busy} onClick={() => doReplace(a)}>교체</button>
                          </>
                        )}
                        {a.account_status === "suspended" && (
                          <button className="hw-filter-btn" disabled={busy} onClick={() => doRestore(a)}>복구</button>
                        )}
                        {a.account_status === "replaced" && (
                          <span style={{ fontSize: 11, color: "#A0AEC0" }}>교체됨 — 조작 불가</span>
                        )}
                        {a.account_status === "disabled" && (
                          <span style={{ fontSize: 11, color: "#A0AEC0" }}>레거시 비활성 — 시스템 관리자 문의</span>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: "#A0AEC0", marginTop: 10, lineHeight: 1.6 }}>
            좌석 한도({data.seat_limit})를 초과하는 계정 생성·주계정 정지/교체는 이 화면에서 할 수 없습니다. 자동 이메일 발송은 없으며, 발급된 활성화 링크는 직접 대상자에게 전달해 주세요.
          </p>
        </div>
      )}
      {reissued && (
        <div className="hw-card" style={{ background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>✅ 활성화 링크 (1회 표시 — 대상자에게 전달)</div>
          <div style={{ fontSize: 12, marginBottom: 4 }}>{reissued.login}</div>
          <code style={{ fontSize: 11, wordBreak: "break-all" }}>{`${origin}/activate/${reissued.token}`}</code>
          <div style={{ marginTop: 8 }}>
            <button className="btn-secondary" style={{ fontSize: 12 }}
              onClick={() => { navigator.clipboard?.writeText(`${origin}/activate/${reissued.token}`); toast.success("링크 복사됨"); }}>
              링크 복사
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
