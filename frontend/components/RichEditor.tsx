"use client";
/**
 * 마크다운 툴바 에디터 (관리자 전용)
 * - 외부 에디터 라이브러리 의존 없음
 * - Toolbar: H2 H3 | B I | •목록 1.목록 | 인용 링크 이미지 | 구분선 | 미리보기
 * - 이미지: URL 입력 또는 파일 업로드 (onImageUpload prop 필요)
 * - 미리보기: MarkdownContent 컴포넌트로 실시간 렌더링
 */
import { useRef, useState, useCallback } from "react";
import { MarkdownContent } from "@/components/MarkdownContent";

interface RichEditorProps {
  value: string;
  onChange: (v: string) => void;
  onImageUpload?: (file: File) => Promise<string>;
  placeholder?: string;
  minHeight?: number;
}

interface ImgDlg {
  open: boolean;
  url: string;
  alt: string;
  uploading: boolean;
}

const BTN_BASE: React.CSSProperties = {
  padding: "4px 9px",
  fontSize: 12,
  fontWeight: 600,
  border: "1px solid #D1D5DB",
  borderRadius: 4,
  background: "#fff",
  color: "#374151",
  cursor: "pointer",
  lineHeight: 1.5,
  fontFamily: "inherit",
  whiteSpace: "nowrap",
};

export function RichEditor({
  value,
  onChange,
  onImageUpload,
  placeholder,
  minHeight = 380,
}: RichEditorProps) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState(false);
  const [imgDlg, setImgDlg] = useState<ImgDlg>({ open: false, url: "", alt: "", uploading: false });

  // ── 헬퍼: 선택 영역을 markdown 문법으로 감쌈 ─────────────────────────────
  const wrap = useCallback(
    (before: string, after = "", ph = "텍스트") => {
      const ta = taRef.current;
      if (!ta) return;
      const s = ta.selectionStart;
      const e = ta.selectionEnd;
      const sel = value.slice(s, e) || ph;
      const next = value.slice(0, s) + before + sel + after + value.slice(e);
      onChange(next);
      requestAnimationFrame(() => {
        ta.setSelectionRange(s + before.length, s + before.length + sel.length);
        ta.focus();
      });
    },
    [value, onChange]
  );

  // ── 헬퍼: 현재 줄 앞에 prefix 삽입 ─────────────────────────────────────────
  const linePrefix = useCallback(
    (prefix: string) => {
      const ta = taRef.current;
      if (!ta) return;
      const s = ta.selectionStart;
      const lineStart = value.lastIndexOf("\n", s - 1) + 1;
      const next = value.slice(0, lineStart) + prefix + value.slice(lineStart);
      onChange(next);
      requestAnimationFrame(() => {
        ta.setSelectionRange(s + prefix.length, s + prefix.length);
        ta.focus();
      });
    },
    [value, onChange]
  );

  // ── 헬퍼: 커서 위치에 텍스트 삽입 ──────────────────────────────────────────
  const insert = useCallback(
    (text: string) => {
      const ta = taRef.current;
      if (!ta) return;
      const s = ta.selectionStart;
      const next = value.slice(0, s) + text + value.slice(s);
      onChange(next);
      requestAnimationFrame(() => {
        ta.setSelectionRange(s + text.length, s + text.length);
        ta.focus();
      });
    },
    [value, onChange]
  );

  // ── 링크 삽입 ────────────────────────────────────────────────────────────────
  const insertLink = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    const s = ta.selectionStart;
    const e = ta.selectionEnd;
    const sel = value.slice(s, e);
    if (sel) {
      const next = value.slice(0, s) + `[${sel}](URL)` + value.slice(e);
      onChange(next);
      requestAnimationFrame(() => {
        ta.setSelectionRange(s + sel.length + 3, s + sel.length + 6);
        ta.focus();
      });
    } else {
      const md = "[링크 텍스트](URL)";
      const next = value.slice(0, s) + md + value.slice(s);
      onChange(next);
      requestAnimationFrame(() => {
        ta.setSelectionRange(s + 1, s + 1 + "링크 텍스트".length);
        ta.focus();
      });
    }
  }, [value, onChange]);

  // ── 이미지 삽입 ──────────────────────────────────────────────────────────────
  const insertImage = useCallback(
    (url: string, alt: string) => {
      insert(`![${alt || "이미지"}](${url})\n`);
      setImgDlg({ open: false, url: "", alt: "", uploading: false });
    },
    [insert]
  );

  const handleFileUpload = useCallback(
    async (file: File) => {
      if (!onImageUpload) return;
      setImgDlg((d) => ({ ...d, uploading: true }));
      try {
        const url = await onImageUpload(file);
        insertImage(url, imgDlg.alt || file.name.replace(/\.[^.]+$/, ""));
      } catch {
        setImgDlg((d) => ({ ...d, uploading: false }));
      }
    },
    [onImageUpload, imgDlg.alt, insertImage]
  );

  // ── 툴바 버튼 렌더 ────────────────────────────────────────────────────────────
  const Btn = ({
    label,
    onClick,
    title,
    active,
  }: {
    label: string;
    onClick: () => void;
    title?: string;
    active?: boolean;
  }) => (
    <button
      type="button"
      title={title || label}
      onClick={onClick}
      style={{
        ...BTN_BASE,
        background: active ? "#D4A843" : "#fff",
        color: active ? "#fff" : "#374151",
        borderColor: active ? "#D4A843" : "#D1D5DB",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.background = "#F3F4F6";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.background = "#fff";
      }}
    >
      {label}
    </button>
  );

  const Divider = () => (
    <span
      style={{ display: "inline-block", width: 1, height: 18, background: "#D1D5DB", margin: "0 2px", verticalAlign: "middle" }}
    />
  );

  return (
    <div style={{ border: "1.5px solid #E2E8F0", borderRadius: 8, overflow: "hidden", background: "#fff" }}>
      {/* ── 툴바 ─────────────────────────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 4,
          padding: "8px 10px",
          background: "#F9FAFB",
          borderBottom: "1px solid #E2E8F0",
          alignItems: "center",
        }}
      >
        <Btn label="H2" onClick={() => linePrefix("## ")} title="소제목 (H2)" />
        <Btn label="H3" onClick={() => linePrefix("### ")} title="소소제목 (H3)" />
        <Divider />
        <Btn label="B" onClick={() => wrap("**", "**")} title="굵게 (Bold)" />
        <Btn label="I" onClick={() => wrap("*", "*")} title="기울임 (Italic)" />
        <Divider />
        <Btn label="• 목록" onClick={() => linePrefix("- ")} title="글머리표 목록" />
        <Btn label="1. 목록" onClick={() => linePrefix("1. ")} title="번호 목록" />
        <Divider />
        <Btn label="❝ 인용" onClick={() => linePrefix("> ")} title="인용/강조 블록" />
        <Btn label="🔗 링크" onClick={insertLink} title="링크 삽입" />
        <Btn
          label="🖼 이미지"
          onClick={() => setImgDlg((d) => ({ ...d, open: !d.open }))}
          title="이미지 삽입"
          active={imgDlg.open}
        />
        <Divider />
        <Btn label="구분선" onClick={() => insert("\n---\n")} title="수평 구분선" />
        {/* Spacer */}
        <span style={{ flex: 1 }} />
        <button
          type="button"
          onClick={() => setPreview((p) => !p)}
          style={{
            ...BTN_BASE,
            border: "1px solid #D4A843",
            background: preview ? "#D4A843" : "#fff",
            color: preview ? "#fff" : "#D4A843",
          }}
        >
          {preview ? "✏️ 편집" : "👁 미리보기"}
        </button>
      </div>

      {/* ── 이미지 삽입 패널 ──────────────────────────────────────────────────── */}
      {imgDlg.open && (
        <div
          style={{
            padding: "12px 14px",
            background: "#FAFAFA",
            borderBottom: "1px solid #E2E8F0",
          }}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              <label
                style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#4A5568", marginBottom: 4 }}
              >
                이미지 URL
              </label>
              <input
                value={imgDlg.url}
                onChange={(e) => setImgDlg((d) => ({ ...d, url: e.target.value }))}
                placeholder="https://..."
                style={{
                  width: "100%",
                  padding: "7px 10px",
                  fontSize: 13,
                  border: "1px solid #D1D5DB",
                  borderRadius: 6,
                  outline: "none",
                  boxSizing: "border-box",
                }}
              />
            </div>
            <div style={{ flex: "1 1 150px", minWidth: 0 }}>
              <label
                style={{ display: "block", fontSize: 11, fontWeight: 600, color: "#4A5568", marginBottom: 4 }}
              >
                대체 텍스트 (alt / 캡션)
              </label>
              <input
                value={imgDlg.alt}
                onChange={(e) => setImgDlg((d) => ({ ...d, alt: e.target.value }))}
                placeholder="이미지 설명"
                style={{
                  width: "100%",
                  padding: "7px 10px",
                  fontSize: 13,
                  border: "1px solid #D1D5DB",
                  borderRadius: 6,
                  outline: "none",
                  boxSizing: "border-box",
                }}
              />
            </div>
            <button
              type="button"
              onClick={() => imgDlg.url && insertImage(imgDlg.url, imgDlg.alt)}
              disabled={!imgDlg.url}
              style={{
                ...BTN_BASE,
                padding: "7px 14px",
                fontSize: 13,
                border: "none",
                background: imgDlg.url ? "#D4A843" : "#ccc",
                color: "#fff",
                cursor: imgDlg.url ? "pointer" : "not-allowed",
              }}
            >
              URL로 삽입
            </button>
            {onImageUpload && (
              <>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={imgDlg.uploading}
                  style={{
                    ...BTN_BASE,
                    padding: "7px 14px",
                    fontSize: 13,
                    border: "1px solid #D4A843",
                    background: "#fff",
                    color: "#D4A843",
                    cursor: imgDlg.uploading ? "not-allowed" : "pointer",
                  }}
                >
                  {imgDlg.uploading ? "업로드 중..." : "파일 업로드"}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/gif,image/webp"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleFileUpload(f);
                    e.target.value = "";
                  }}
                />
              </>
            )}
          </div>
          <p style={{ fontSize: 11, color: "#9CA3AF", margin: "8px 0 0" }}>
            업로드된 이미지는 Google Drive에 저장됩니다. 최대 5MB, jpg/png/gif/webp.
          </p>
        </div>
      )}

      {/* ── 편집 영역 / 미리보기 ─────────────────────────────────────────────── */}
      {preview ? (
        <div
          style={{
            padding: "20px 24px",
            minHeight,
            overflow: "auto",
            fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
            fontSize: 15,
          }}
        >
          {value.trim() ? (
            <MarkdownContent content={value} />
          ) : (
            <p style={{ color: "#9CA3AF", fontStyle: "italic" }}>본문 내용을 입력하면 여기에 미리보기가 표시됩니다.</p>
          )}
        </div>
      ) : (
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            placeholder ||
            "본문을 입력하세요.\n\n마크다운 문법:\n## 소제목  ### 소소제목\n**굵게**  *기울임*\n- 목록 항목\n1. 번호 목록\n> 강조/인용 블록\n[링크 텍스트](URL)\n![이미지 설명](URL)"
          }
          style={{
            display: "block",
            width: "100%",
            minHeight,
            padding: "16px 18px",
            fontSize: 14,
            lineHeight: 1.75,
            border: "none",
            outline: "none",
            resize: "vertical",
            fontFamily: "'Noto Sans KR', 'Pretendard', monospace",
            color: "#1A202C",
            background: "#fff",
            boxSizing: "border-box",
            tabSize: 2,
          }}
        />
      )}

      {/* ── 하단 힌트 ────────────────────────────────────────────────────────── */}
      <div
        style={{
          padding: "5px 12px",
          background: "#F9FAFB",
          borderTop: "1px solid #E2E8F0",
          fontSize: 11,
          color: "#9CA3AF",
          lineHeight: 1.5,
        }}
      >
        마크다운 지원: <code style={{ fontSize: 10 }}>**굵게**</code> &nbsp;
        <code style={{ fontSize: 10 }}>*기울임*</code> &nbsp;
        <code style={{ fontSize: 10 }}>## 소제목</code> &nbsp;
        <code style={{ fontSize: 10 }}>- 목록</code> &nbsp;
        <code style={{ fontSize: 10 }}>&gt; 인용</code> &nbsp;
        <code style={{ fontSize: 10 }}>![alt](URL)</code>
      </div>
    </div>
  );
}
