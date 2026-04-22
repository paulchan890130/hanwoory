"use client";
/**
 * 마크다운 → 시맨틱 HTML 렌더러
 * react-markdown 없이 자체 구현 — 외부 ESM 패키지 의존 없음.
 * 지원 문법: ## H2, ### H3, **bold**, *italic*, - list, 1. list,
 *           > blockquote, [link](url), ![alt](src), `code`, ---, 줄바꿈(\n→<br>)
 * AI·크롤러 친화: 모든 블록이 실제 시맨틱 HTML 태그로 출력됨.
 */
import React from "react";

const GOLD = "#8B6914";
const GOLD_BORDER = "#C8A84B";

// ── 인라인 파서 ──────────────────────────────────────────────────────────────
function parseInline(text: string, prefix: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  // 순서 중요: 이미지 → 링크 → 굵게 → 기울임 → 코드 → 줄바꿈
  const re =
    /!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`|\n/g;
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const k = `${prefix}-${m.index}`;

    if (m[1] !== undefined) {
      // 인라인 이미지 ![alt](src)
      // eslint-disable-next-line @next/next/no-img-element
      parts.push(
        <img
          key={k}
          src={m[2]}
          alt={m[1] || ""}
          style={{ maxWidth: "100%", verticalAlign: "middle", borderRadius: 6 }}
          loading="lazy"
        />
      );
    } else if (m[3] !== undefined) {
      // 링크 [text](href)
      const href = m[4];
      const isExt = /^https?:\/\//.test(href);
      parts.push(
        <a
          key={k}
          href={href}
          style={{ color: GOLD, textDecoration: "underline" }}
          target={isExt ? "_blank" : undefined}
          rel={isExt ? "noopener noreferrer" : undefined}
        >
          {m[3]}
        </a>
      );
    } else if (m[5] !== undefined) {
      parts.push(
        <strong key={k} style={{ fontWeight: 700, color: "#1A1A1A" }}>
          {m[5]}
        </strong>
      );
    } else if (m[6] !== undefined) {
      parts.push(
        <em key={k} style={{ fontStyle: "italic" }}>
          {m[6]}
        </em>
      );
    } else if (m[7] !== undefined) {
      parts.push(
        <code
          key={k}
          style={{
            background: "#F3F4F6",
            padding: "2px 6px",
            borderRadius: 3,
            fontSize: "0.88em",
            fontFamily: "monospace",
            color: "#D73A49",
          }}
        >
          {m[7]}
        </code>
      );
    } else {
      // \n 단일 줄바꿈 → <br> (기존 plain-text 콘텐츠 하위호환)
      parts.push(<br key={k} />);
    }
    last = re.lastIndex;
  }

  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// ── 블록 파서 ────────────────────────────────────────────────────────────────
export function MarkdownContent({ content }: { content: string }) {
  if (!content?.trim()) {
    return <p style={{ color: "#999" }}>내용이 없습니다.</p>;
  }

  const normalized = content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const lines = normalized.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const raw = lines[i];
    const trimmed = raw.trim();

    // 빈 줄 건너뜀
    if (!trimmed) {
      i++;
      continue;
    }

    // ── 수평선 ---
    if (/^-{3,}$/.test(trimmed)) {
      elements.push(
        <hr
          key={key++}
          style={{ border: "none", borderTop: "1px solid #EAE4D8", margin: "28px 0" }}
        />
      );
      i++;
      continue;
    }

    // ── H2 ##
    if (trimmed.startsWith("## ")) {
      elements.push(
        <h2
          key={key++}
          style={{
            fontSize: 20,
            fontWeight: 700,
            color: "#1A1A1A",
            margin: "32px 0 14px",
            paddingBottom: 8,
            borderBottom: "2px solid #E8E0D4",
            lineHeight: 1.4,
          }}
        >
          {parseInline(trimmed.slice(3), `h2-${key}`)}
        </h2>
      );
      i++;
      continue;
    }

    // ── H3 ###
    if (trimmed.startsWith("### ")) {
      elements.push(
        <h3
          key={key++}
          style={{
            fontSize: 17,
            fontWeight: 700,
            color: "#2D2D2D",
            margin: "24px 0 10px",
            lineHeight: 1.4,
          }}
        >
          {parseInline(trimmed.slice(4), `h3-${key}`)}
        </h3>
      );
      i++;
      continue;
    }

    // ── 인용/강조 블록 >
    if (trimmed.startsWith("> ")) {
      const qLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("> ")) {
        qLines.push(lines[i].trim().slice(2));
        i++;
      }
      elements.push(
        <blockquote
          key={key++}
          style={{
            borderLeft: `3px solid ${GOLD_BORDER}`,
            background: "#FBF6EC",
            padding: "14px 20px",
            margin: "20px 0",
            borderRadius: "0 6px 6px 0",
          }}
        >
          {qLines.map((ql, qi) => (
            <p
              key={qi}
              style={{ margin: qi < qLines.length - 1 ? "0 0 6px" : 0, lineHeight: 1.8, color: "#5A4B1E" }}
            >
              {parseInline(ql, `bq-${key}-${qi}`)}
            </p>
          ))}
        </blockquote>
      );
      continue;
    }

    // ── 비순서 목록 -
    if (/^[-*]\s/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s/.test(lines[i])) {
        items.push(lines[i].trim().replace(/^[-*]\s/, ""));
        i++;
      }
      elements.push(
        <ul key={key++} style={{ paddingLeft: 22, margin: "0 0 18px", lineHeight: 1.85 }}>
          {items.map((item, ii) => (
            <li key={ii} style={{ marginBottom: 6, color: "#333" }}>
              {parseInline(item, `ul-${key}-${ii}`)}
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // ── 순서 목록 1.
    if (/^\d+\.\s/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+\.\s/.test(lines[i])) {
        items.push(lines[i].trim().replace(/^\d+\.\s/, ""));
        i++;
      }
      elements.push(
        <ol key={key++} style={{ paddingLeft: 22, margin: "0 0 18px", lineHeight: 1.85 }}>
          {items.map((item, ii) => (
            <li key={ii} style={{ marginBottom: 6, color: "#333" }}>
              {parseInline(item, `ol-${key}-${ii}`)}
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // ── 독립 이미지 줄 ![alt](src)
    const imgMatch = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(trimmed);
    if (imgMatch) {
      elements.push(
        <figure key={key++} style={{ margin: "24px 0", textAlign: "center" }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imgMatch[2]}
            alt={imgMatch[1] || ""}
            style={{ maxWidth: "100%", borderRadius: 8, display: "inline-block" }}
            loading="lazy"
          />
          {imgMatch[1] && (
            <figcaption
              style={{ fontSize: 13, color: "#888", marginTop: 8, fontStyle: "italic" }}
            >
              {imgMatch[1]}
            </figcaption>
          )}
        </figure>
      );
      i++;
      continue;
    }

    // ── 일반 단락 — 연속된 비블록 줄을 하나의 <p>로 묶음
    const pLines: string[] = [];
    while (i < lines.length) {
      const lt = lines[i].trim();
      if (!lt) break;
      if (
        /^(##|###)\s/.test(lt) ||
        /^[-*]\s/.test(lt) ||
        /^\d+\.\s/.test(lt) ||
        lt.startsWith("> ") ||
        /^-{3,}$/.test(lt) ||
        /^!\[([^\]]*)\]\(([^)]+)\)$/.test(lt)
      )
        break;
      pLines.push(lines[i]);
      i++;
    }
    if (pLines.length) {
      elements.push(
        <p key={key++} style={{ margin: "0 0 18px", lineHeight: 1.9, color: "#333" }}>
          {parseInline(pLines.join("\n"), `p-${key}`)}
        </p>
      );
    }
  }

  return <>{elements}</>;
}
