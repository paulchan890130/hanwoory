"use client";
import { toast } from "sonner";

// 활성화 링크 발급/재발급 결과 — 계정관리·사업장관리·승인 상세에서 공통 사용.
// 보안·안내 문구를 한 곳에서 통일한다. token 원문은 이 화면에서만 노출되며 로그에 남기지 않는다.

export interface ActivationLinkInfo {
  name?: string;
  login_id: string;
  role?: string;       // office_admin | office_staff | admin | user
  token: string;
}

const roleKo = (r?: string) =>
  r === "office_admin" || r === "admin" ? "대표자 관리자" : r === "office_staff" || r === "user" ? "실무자 직원" : (r || "");

export default function ActivationLinkResult({ info, onClose }: {
  info: ActivationLinkInfo; onClose?: () => void;
}) {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const url = `${origin}/activate/${info.token}`;
  return (
    <div style={{ marginTop: 12, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)",
      borderRadius: 8, padding: "12px 14px" }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>활성화 링크가 발급되었습니다.</div>
      <div style={{ fontSize: 12, color: "var(--hw-text-sub)", lineHeight: 1.75, marginBottom: 8 }}>
        <div><strong>로그인 ID</strong>: {info.login_id} (가입신청 당시 이메일 주소)</div>
        {roleKo(info.role) && <div><strong>역할</strong>: {roleKo(info.role)}{info.name ? ` · ${info.name}` : ""}</div>}
        <div style={{ marginTop: 6 }}><strong>최초 로그인 방법</strong></div>
        <ol style={{ margin: "2px 0 0", paddingLeft: 18 }}>
          <li>아래 활성화 링크를 사용자에게 전달</li>
          <li>사용자가 링크에서 최초 비밀번호 설정</li>
          <li>이메일과 설정한 비밀번호로 로그인</li>
        </ol>
        <div style={{ marginTop: 6, color: "#9C4221" }}>
          자동 이메일은 발송되지 않습니다. 이 링크는 지금 이 화면에서만 확인할 수 있습니다.
        </div>
      </div>
      <code style={{ fontSize: 11, wordBreak: "break-all", display: "block" }}>{url}</code>
      <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn-secondary" style={{ fontSize: 12 }}
          onClick={() => { navigator.clipboard?.writeText(url); toast.success("활성화 링크를 복사했습니다."); }}>
          활성화 링크 복사
        </button>
        <button className="btn-secondary" style={{ fontSize: 12 }}
          onClick={() => { navigator.clipboard?.writeText(info.login_id); toast.success("로그인 ID를 복사했습니다."); }}>
          로그인 ID 복사
        </button>
        {onClose && (
          <button className="btn-secondary" style={{ fontSize: 12 }} onClick={onClose}>닫기</button>
        )}
      </div>
    </div>
  );
}
