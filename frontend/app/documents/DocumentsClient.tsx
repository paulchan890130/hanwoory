"use client";

import { useState, useMemo } from "react";
import Link from "next/link";

interface DocItem {
  label: string;
  href: string;
}

interface DocGroup {
  group: string;
  items: DocItem[];
}

const GROUPS: DocGroup[] = [
  {
    group: "F-4",
    items: [
      { label: "F-4 등록 준비서류", href: "/board/f4-registration-documents" },
      { label: "F-4 연장 준비서류", href: "/board/f4-extension-documents" },
      { label: "H-2에서 F-4 변경 준비서류", href: "/board/h2-to-f4-change-documents" },
      { label: "기타 체류자격에서 F-4 변경 준비서류", href: "/board/other-status-to-f4-change-documents" },
      { label: "F-4 변경(만 60세 / 시험) 준비서류", href: "/board/f4-change-age-60-or-test-documents" },
      { label: "F-4 변경(초중고 재학) 준비서류", href: "/board/f4-change-school-student-documents" },
      { label: "F-4 변경(지방 제조업 2년) 준비서류", href: "/board/f4-change-local-manufacturing-documents" },
      { label: "F-4-R 변경 준비서류", href: "/board/f4r-change-documents" },
    ],
  },
  {
    group: "H-2",
    items: [
      { label: "H-2 등록 준비서류", href: "/board/h2-registration-documents" },
      { label: "H-2 연장 준비서류", href: "/board/h2-extension-documents" },
      { label: "C-3-8에서 H-2 변경 준비서류", href: "/board/c38-to-h2-change-documents" },
    ],
  },
  {
    group: "F-5 / 영주권",
    items: [
      { label: "F-4 2년 영주권 신청 준비서류(4대보험)", href: "/board/f4-two-year-pr-four-insurance-documents" },
      { label: "F-4 2년 영주권 신청 준비서류(일용직)", href: "/board/f4-two-year-pr-daily-worker-documents" },
      { label: "F-4 2년 영주권 신청 준비서류(재산세)", href: "/board/f4-two-year-pr-property-tax-documents" },
      { label: "F-4 2년 영주권 신청 준비서류(자산)", href: "/board/f4-two-year-pr-assets-documents" },
      { label: "F-4 2년 영주권 신청 준비서류(사업자)", href: "/board/f4-two-year-pr-business-owner-documents" },
      { label: "H-2 4년 영주권 신청 준비서류", href: "/board/h2-four-year-permanent-residence-documents" },
      { label: "C-3-8 영주권 신청 준비서류(부모님 국적)", href: "/board/c38-permanent-residence-parent-nationality-documents" },
      { label: "F-4 영주권 소득 70% 조건", href: "/board/f4-pr-income-70-percent-condition" },
    ],
  },
  {
    group: "F-6",
    items: [
      { label: "F-6 초청 준비서류", href: "/board/f6-invitation-documents" },
      { label: "F-6 변경 준비서류", href: "/board/f6-change-documents" },
      { label: "F-6 연장 준비서류", href: "/board/f6-extension-documents" },
    ],
  },
  {
    group: "F-3",
    items: [
      { label: "F-3 초청 준비서류", href: "/board/f3-invitation-documents" },
      { label: "F-3 변경(배우자) 준비서류", href: "/board/f3-change-spouse-documents" },
      { label: "F-3 변경(자녀) 준비서류", href: "/board/f3-change-child-documents" },
      { label: "F-3 등록 및 연장(배우자)", href: "/board/f3-registration-extension-spouse-documents" },
      { label: "F-3 등록 및 연장(미성년자)", href: "/board/f3-registration-extension-minor-documents" },
      { label: "F-3-R 변경 준비서류", href: "/board/f3r-change-documents" },
    ],
  },
  {
    group: "F-2",
    items: [
      { label: "F-2 초청·변경 준비서류", href: "/board/f2-invitation-change-documents" },
      { label: "F-2 변경(미성년) 준비서류", href: "/board/f2-change-minor-documents" },
      { label: "F-2 등록 및 연장(배우자)", href: "/board/f2-registration-extension-spouse-documents" },
      { label: "F-2 등록 및 연장(미성년자)", href: "/board/f2-registration-extension-minor-documents" },
    ],
  },
  {
    group: "F-1",
    items: [
      { label: "F-1 초청(양육지원) 준비서류", href: "/board/f1-childcare-support-invitation-documents" },
      { label: "F-1-5 초청 준비서류", href: "/board/f15-invitation-documents" },
    ],
  },
  {
    group: "국적 / 귀화",
    items: [
      { label: "일반귀화 준비서류", href: "/board/naturalization-general-documents" },
      { label: "간이귀화(결혼 2년) 준비서류", href: "/board/naturalization-simple-marriage-two-years-documents" },
      { label: "간이귀화(혼인단절) 준비서류", href: "/board/naturalization-simple-marriage-breakdown-documents" },
      { label: "혼인귀화(미성년 양육) 준비서류", href: "/board/naturalization-marriage-minor-child-documents" },
      { label: "특별귀화(부모국적) 준비서류", href: "/board/naturalization-special-parent-nationality-documents" },
      {
        label: "간이귀화(3년거주 + 사망한 부모국적) 준비서류",
        href: "/board/naturalization-simple-three-years-deceased-parent-documents",
      },
    ],
  },
  {
    group: "중국 공증·아포스티유",
    items: [
      { label: "친속공증 준비서류", href: "/board/family-notarization-documents" },
      { label: "결혼공증 준비서류", href: "/board/marriage-notarization-documents" },
      { label: "미혼·재혼공증 준비서류", href: "/board/single-remarriage-notarization-documents" },
      { label: "무범죄공증 준비서류", href: "/board/criminal-record-notarization-documents" },
    ],
  },
];

export function DocumentsClient() {
  const [query, setQuery] = useState("");

  const filteredGroups = useMemo(() => {
    if (!query.trim()) return GROUPS;
    const q = query.trim().toLowerCase();
    return GROUPS.map((g) => ({
      ...g,
      items: g.items.filter((item) => item.label.toLowerCase().includes(q)),
    })).filter((g) => g.items.length > 0);
  }, [query]);

  return (
    <>
      {/* ── 검색 ───────────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="체류자격 또는 업무명으로 검색 (예: F-4, 연장, 귀화...)"
          style={{
            width: "100%",
            padding: "11px 18px",
            fontSize: 14,
            border: "1px solid #DDD",
            borderRadius: 8,
            outline: "none",
            fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
            boxSizing: "border-box",
            color: "#333",
            background: "#fff",
          }}
        />
      </div>

      {/* ── 그룹 그리드 ─────────────────────────────────────────────────── */}
      {filteredGroups.length === 0 ? (
        <p style={{ color: "#999", textAlign: "center", padding: "60px 0", fontSize: 15 }}>
          &apos;{query}&apos; 검색 결과가 없습니다.
        </p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 20,
          }}
        >
          {filteredGroups.map((group) => (
            <section
              key={group.group}
              style={{
                background: "#FAF8F4",
                border: "1px solid #EAE4D8",
                borderRadius: 10,
                padding: "18px 20px 16px",
              }}
            >
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 700,
                  color: "#7A5C10",
                  margin: "0 0 12px",
                  paddingBottom: 10,
                  borderBottom: "1px solid #E4DAC8",
                }}
              >
                {group.group}
              </h2>
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {group.items.map((item) => (
                  <li key={item.href} style={{ marginBottom: 7 }}>
                    <Link
                      href={item.href}
                      style={{
                        fontSize: 13,
                        color: "#333",
                        textDecoration: "none",
                        display: "flex",
                        alignItems: "baseline",
                        gap: 6,
                        lineHeight: 1.55,
                      }}
                    >
                      <span style={{ color: "#C8A84B", flexShrink: 0, fontSize: 11 }}>›</span>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
