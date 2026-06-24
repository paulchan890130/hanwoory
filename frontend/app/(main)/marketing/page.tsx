"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getUser, canManageContent } from "@/lib/auth";

// 마케팅 첫 화면: 공개 홈페이지 구조와 동일하게 두 영역으로 분리.
//   - 업무안내 관리  → /board (공지/업무안내/제도변경 등 게시판형 글)
//   - 업무별 준비서류 관리 → /documents (중분류 → 소분류 글, 폴더형)
export default function MarketingHomePage() {
  const router = useRouter();
  const user = getUser();

  useEffect(() => {
    if (!canManageContent(user)) router.replace("/dashboard");
  }, []);

  if (!canManageContent(user)) return null;

  const cardStyle: React.CSSProperties = {
    flex: 1,
    minWidth: 260,
    border: "1px solid #E2E8F0",
    borderRadius: 12,
    padding: "28px 26px",
    background: "#fff",
    cursor: "pointer",
    textAlign: "left",
    transition: "box-shadow .15s, border-color .15s",
  };

  return (
    <div style={{ padding: "32px 24px", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>마케팅 · 홈페이지 관리</h1>
        <p style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
          공개 홈페이지(hanwory.com)에 표시되는 콘텐츠를 두 영역으로 나누어 관리합니다.
        </p>
      </div>

      <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
        <button
          onClick={() => router.push("/marketing/board")}
          style={cardStyle}
          onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)"; e.currentTarget.style.borderColor = "#D4A843"; }}
          onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "none"; e.currentTarget.style.borderColor = "#E2E8F0"; }}
        >
          <div style={{ fontSize: 28, marginBottom: 12 }}>📢</div>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: "#1A202C", margin: "0 0 8px" }}>업무안내 관리</h2>
          <p style={{ fontSize: 13, color: "#718096", margin: 0, lineHeight: 1.6 }}>
            공지사항, 업무 안내, 제도 변경, 기타 게시글을 관리합니다.
            <br />공개 홈페이지의 <strong>/board</strong> 에 표시됩니다.
          </p>
        </button>

        <button
          onClick={() => router.push("/marketing/documents")}
          style={cardStyle}
          onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.08)"; e.currentTarget.style.borderColor = "#D4A843"; }}
          onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "none"; e.currentTarget.style.borderColor = "#E2E8F0"; }}
        >
          <div style={{ fontSize: 28, marginBottom: 12 }}>📂</div>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: "#1A202C", margin: "0 0 8px" }}>업무별 준비서류 관리</h2>
          <p style={{ fontSize: 13, color: "#718096", margin: 0, lineHeight: 1.6 }}>
            F-1 ~ F-6, H-2, 국적·귀화, 중국 공증 등 중분류별로 준비서류 글을 폴더형으로 관리합니다.
            <br />공개 홈페이지의 <strong>/documents</strong> 에 표시됩니다.
          </p>
        </button>
      </div>
    </div>
  );
}
