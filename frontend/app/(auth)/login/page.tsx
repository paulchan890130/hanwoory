"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { authApi } from "@/lib/api";
import { setUser } from "@/lib/auth";

type LoginForm = { login_id: string; password: string };
type SignupForm = {
  office_name: string;
  office_adr: string;
  biz_reg_no: string;
  agent_rrn: string;
  contact_name: string;
  contact_tel: string;
  login_id: string;
  password: string;
  confirm_password: string;
};

const GOLD = "#F5A623";
const GOLD_DARK = "#D4891A";
const BORDER = "#E2E8F0";

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "12px 14px",
  fontSize: 15,
  border: `1.5px solid ${BORDER}`,
  borderRadius: 8,
  background: "#F9FAFB",
  color: "#1A202C",
  outline: "none",
  boxSizing: "border-box",
  transition: "border-color 0.15s, background 0.15s",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 13,
  fontWeight: 600,
  color: "#2D3748",
  marginBottom: 6,
};

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "signup">("login");
  const [loading, setLoading] = useState(false);

  const loginForm = useForm<LoginForm>();
  const signupForm = useForm<SignupForm>();

  const onLogin = async (data: LoginForm) => {
    setLoading(true);
    try {
      const res = await authApi.login(data.login_id, data.password);
      setUser(res.data);
      toast.success(`${res.data.office_name || data.login_id}님, 환영합니다!`);
      router.replace("/dashboard");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "로그인 실패";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const onSignup = async (data: SignupForm) => {
    if (data.password !== data.confirm_password) {
      toast.error("비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setLoading(true);
    try {
      await authApi.signup(data as unknown as Record<string, string>);
      toast.success(
        "가입신청이 완료되었습니다. 사업자등록증, 행정사업무신고확인증, 사업장 사진(3장 이상)을 chan@hanwoory.world 로 보내주시면 승인해 드리겠습니다.",
        { duration: 8000 }
      );
      setTab("login");
      signupForm.reset();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "가입 실패";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-outer" style={{ minHeight: "100vh", display: "flex", background: "#fff" }}>

      {/* ── 좌측 브랜딩 패널 (흰 배경, 골드 포인트) ── */}
      <div
        className="login-left"
        style={{
          flex: "0 0 420px",
          background: "#fff",
          borderRight: `3px solid ${GOLD}`,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "52px 44px",
        }}
      >
        {/* 로고 */}
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 48 }}>
            <img
              src="/hanwoori-logo-new.jpeg"
              alt="한우리 로고"
              style={{
                width: 60, height: 60, borderRadius: 0,
                objectFit: "contain",
                flexShrink: 0,
              }}
            />
            <div>
              <div style={{ fontSize: 26, fontWeight: 900, color: "#1A202C", letterSpacing: "-1px" }}>K.ID</div>
              <div style={{ fontSize: 12, color: "#718096", marginTop: 2, fontWeight: 500 }}>출입국 업무관리 시스템</div>
            </div>
          </div>

          <div style={{ marginBottom: 36 }}>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: "#1A202C", lineHeight: 1.45, marginBottom: 12 }}>
              행정사사무소<br />
              <span style={{ color: GOLD }}>업무관리</span> 시스템
            </h2>
            <p style={{ fontSize: 13, color: "#718096", lineHeight: 1.9 }}>
              고객 등록증·여권 만기 알림, 업무 일정관리,<br />
              문서 자동작성, 일일결산까지<br />
              행정사 실무 전과정을 한 화면에서.
            </p>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { icon: "👤", text: "고객 통합관리" },
              { icon: "⏰", text: "등록증·여권 만기 자동 알림" },
              { icon: "📄", text: "문서 자동 작성 (신청서 등)" },
              { icon: "💴", text: "일일 월간 결산 관리" },
              { icon: "📋", text: "업무 일정 및 메모 관리" },
            ].map((item, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "9px 14px", borderRadius: 8,
                background: "#FAFAFA",
                border: "1px solid #F0F0F0",
              }}>
                <span style={{ fontSize: 15 }}>{item.icon}</span>
                <span style={{ fontSize: 13, color: "#4A5568", fontWeight: 500 }}>{item.text}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          borderTop: `1px solid ${BORDER}`,
          paddingTop: 20,
          fontSize: 11,
          color: "#A0AEC0",
        }}>
          © 한우리행정사사무소 · K.ID 출입국 업무관리<br />
          Powered by Google Sheets + FastAPI + Next.js
        </div>
      </div>

      {/* ── 우측 로그인 폼 (흰 배경) ── */}
      <div
        className="login-right"
        style={{
          flex: 1,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px 32px",
          background: "#fff",
        }}
      >
        <div className="login-inner" style={{ width: "100%", maxWidth: 440 }}>

          {/* 폼 헤더 */}
          <div style={{ marginBottom: 32 }}>
            <h3 style={{ fontSize: 24, fontWeight: 800, color: "#1A202C", marginBottom: 6 }}>
              {tab === "login" ? "시스템 로그인" : "사무실 가입신청"}
            </h3>
            <p style={{ fontSize: 13, color: "#718096" }}>
              {tab === "login"
                ? "승인된 행정사 사무소 계정으로 로그인하세요."
                : "정식 영업 중인 행정사 사무소 전용입니다."}
            </p>
          </div>

          {/* 탭 */}
          <div
            style={{
              display: "flex",
              background: "#F7F8FA",
              borderRadius: 10,
              padding: 4,
              marginBottom: 32,
              border: `1px solid ${BORDER}`,
              gap: 4,
            }}
          >
            {(["login", "signup"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  flex: 1, padding: "10px 0", borderRadius: 8,
                  fontSize: 14, fontWeight: tab === t ? 700 : 500,
                  color: tab === t ? "#1A1F2E" : "#718096",
                  background: tab === t ? GOLD : "transparent",
                  border: "none", cursor: "pointer",
                  transition: "all 0.15s",
                  boxShadow: tab === t ? "0 1px 4px rgba(245,166,35,0.4)" : "none",
                }}
              >
                {t === "login" ? "로그인" : "가입신청"}
              </button>
            ))}
          </div>

          {/* ── 로그인 폼 ── */}
          {tab === "login" && (
            <form onSubmit={loginForm.handleSubmit(onLogin)} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
              <div>
                <label style={labelStyle}>로그인 ID</label>
                <input
                  {...loginForm.register("login_id", { required: true })}
                  style={inputStyle}
                  placeholder="ID 입력"
                  autoComplete="username"
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = GOLD;
                    e.currentTarget.style.background = "#fff";
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = BORDER;
                    e.currentTarget.style.background = "#F9FAFB";
                  }}
                />
              </div>
              <div>
                <label style={labelStyle}>비밀번호</label>
                <input
                  {...loginForm.register("password", { required: true })}
                  type="password"
                  style={inputStyle}
                  placeholder="비밀번호 입력"
                  autoComplete="current-password"
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = GOLD;
                    e.currentTarget.style.background = "#fff";
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = BORDER;
                    e.currentTarget.style.background = "#F9FAFB";
                  }}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                style={{
                  width: "100%",
                  padding: "14px 0",
                  borderRadius: 8,
                  fontWeight: 800,
                  fontSize: 16,
                  background: loading ? "#ccc" : GOLD,
                  color: "#1A1F2E",
                  border: "none",
                  cursor: loading ? "not-allowed" : "pointer",
                  marginTop: 4,
                  boxShadow: loading ? "none" : "0 2px 8px rgba(245,166,35,0.4)",
                  transition: "background 0.15s",
                }}
                onMouseEnter={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.background = GOLD_DARK; }}
                onMouseLeave={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.background = GOLD; }}
              >
                {loading ? "로그인 중..." : "로그인"}
              </button>
            </form>
          )}

          {/* ── 가입신청 폼 ── */}
          {tab === "signup" && (
            <form
              onSubmit={signupForm.handleSubmit(onSignup)}
              style={{ display: "flex", flexDirection: "column", gap: 14, maxHeight: "62vh", overflowY: "auto", paddingRight: 4 }}
            >
              <div
                style={{
                  fontSize: 12, padding: "12px 14px", borderRadius: 8,
                  background: "rgba(245,166,35,0.06)",
                  color: "#4A5568",
                  border: `1px solid rgba(245,166,35,0.25)`,
                  lineHeight: 1.7,
                }}
              >
                가입 후 관리자 승인이 필요합니다.<br />
                사업자등록증, 행정사업무신고확인증, 사업장 사진(3장 이상)을<br />
                <span style={{ color: GOLD, fontWeight: 700 }}>chan@hanwoory.world</span>로 보내주세요.
              </div>
              {[
                { name: "office_name", label: "대행기관명 *", placeholder: "사무실명" },
                { name: "office_adr", label: "사무실 주소", placeholder: "" },
                { name: "biz_reg_no", label: "사업자등록번호", placeholder: "000-00-00000" },
                { name: "agent_rrn", label: "행정사 주민등록번호", placeholder: "000000-0000000" },
                { name: "contact_name", label: "행정사 성명", placeholder: "" },
                { name: "contact_tel", label: "연락처", placeholder: "010-0000-0000" },
                { name: "login_id", label: "로그인 ID *", placeholder: "영문/숫자 권장" },
              ].map((f) => (
                <div key={f.name}>
                  <label style={labelStyle}>{f.label}</label>
                  <input
                    {...signupForm.register(f.name as keyof SignupForm)}
                    style={inputStyle}
                    placeholder={f.placeholder}
                    onFocus={(e) => {
                      e.currentTarget.style.borderColor = GOLD;
                      e.currentTarget.style.background = "#fff";
                    }}
                    onBlur={(e) => {
                      e.currentTarget.style.borderColor = BORDER;
                      e.currentTarget.style.background = "#F9FAFB";
                    }}
                  />
                </div>
              ))}
              <div>
                <label style={labelStyle}>비밀번호 *</label>
                <input
                  {...signupForm.register("password")}
                  type="password"
                  style={inputStyle}
                  autoComplete="new-password"
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = GOLD;
                    e.currentTarget.style.background = "#fff";
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = BORDER;
                    e.currentTarget.style.background = "#F9FAFB";
                  }}
                />
              </div>
              <div>
                <label style={labelStyle}>비밀번호 확인 *</label>
                <input
                  {...signupForm.register("confirm_password")}
                  type="password"
                  style={inputStyle}
                  autoComplete="new-password"
                  onFocus={(e) => {
                    e.currentTarget.style.borderColor = GOLD;
                    e.currentTarget.style.background = "#fff";
                  }}
                  onBlur={(e) => {
                    e.currentTarget.style.borderColor = BORDER;
                    e.currentTarget.style.background = "#F9FAFB";
                  }}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                style={{
                  width: "100%", padding: "14px 0", borderRadius: 8,
                  fontWeight: 800, fontSize: 16,
                  background: loading ? "#ccc" : GOLD,
                  color: "#1A1F2E", border: "none",
                  cursor: loading ? "not-allowed" : "pointer",
                  marginTop: 4,
                  boxShadow: "0 2px 8px rgba(245,166,35,0.4)",
                }}
                onMouseEnter={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.background = GOLD_DARK; }}
                onMouseLeave={(e) => { if (!loading) (e.currentTarget as HTMLButtonElement).style.background = GOLD; }}
              >
                {loading ? "신청 중..." : "가입신청"}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
