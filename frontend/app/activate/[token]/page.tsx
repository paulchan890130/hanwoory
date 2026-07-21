"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { officeApplicationApi } from "@/lib/api";

// 활성화(최초 비밀번호 설정) — 승인된 계정이 발급받은 1회성 링크로 접근한다.
// 토큰 원문은 저장/재노출하지 않으며, 완료 시 계정이 활성화되고 링크는 폐기된다.

export default function ActivatePage() {
  const params = useParams();
  const router = useRouter();
  const token = decodeURIComponent(String(params?.token || ""));

  const [state, setState] = useState<"checking" | "ready" | "invalid" | "done">("checking");
  const [loginId, setLoginId] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    officeApplicationApi.checkActivation(token)
      .then((r) => { if (!cancelled) { setLoginId((r.data as { login_id: string }).login_id); setState("ready"); } })
      .catch(() => { if (!cancelled) setState("invalid"); });
    return () => { cancelled = true; };
  }, [token]);

  const submit = async () => {
    setError("");
    if (pw.length < 6) { setError("비밀번호는 6자 이상이어야 합니다."); return; }
    if (pw !== pw2) { setError("비밀번호 확인이 일치하지 않습니다."); return; }
    setBusy(true);
    try {
      await officeApplicationApi.completeActivation(token, pw);
      setState("done");
      setTimeout(() => router.push("/login"), 2500);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "활성화에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ maxWidth: 440, margin: "64px auto", padding: "0 16px" }}>
      <div className="hw-card">
        <h1 className="hw-page-title" style={{ marginBottom: 12 }}>계정 활성화</h1>

        {state === "checking" && <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>확인 중...</p>}

        {state === "invalid" && (
          <>
            <p style={{ fontSize: 13, color: "#C53030", lineHeight: 1.7 }}>
              유효하지 않거나 만료된 활성화 링크입니다. 관리자에게 재발급을 요청해 주세요.
            </p>
            <Link href="/login" className="btn-secondary" style={{ marginTop: 16, textDecoration: "none" }}>
              로그인 화면으로
            </Link>
          </>
        )}

        {state === "ready" && (
          <>
            <p style={{ fontSize: 13, color: "var(--hw-text-sub)", marginBottom: 16, lineHeight: 1.7 }}>
              <strong style={{ color: "var(--hw-text)" }}>{loginId}</strong> 계정의 최초 비밀번호를 설정합니다.
            </p>
            <div className="hw-field">
              <label className="hw-label">새 비밀번호</label>
              <input className="hw-input" type="password" value={pw} onChange={(e) => setPw(e.target.value)} />
            </div>
            <div className="hw-field">
              <label className="hw-label">새 비밀번호 확인</label>
              <input className="hw-input" type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} />
            </div>
            {error && (
              <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030",
                borderRadius: 8, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>{error}</div>
            )}
            <button className="btn-primary" onClick={submit} disabled={busy}>
              {busy ? "설정 중..." : "비밀번호 설정 후 활성화"}
            </button>
          </>
        )}

        {state === "done" && (
          <p style={{ fontSize: 14, color: "#276749", lineHeight: 1.7 }}>
            ✅ 계정이 활성화되었습니다. 로그인 화면으로 이동합니다...
          </p>
        )}
      </div>
    </div>
  );
}
