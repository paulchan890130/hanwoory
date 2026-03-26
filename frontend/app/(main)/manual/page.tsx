"use client";
import { useState } from "react";
import { manualApi } from "@/lib/api";

export default function ManualPage() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = async () => {
    const q = question.trim();
    if (!q) return;
    setLoading(true);
    setAnswer(null);
    setError(null);
    try {
      const res = await manualApi.search(q);
      setAnswer(res.data.answer);
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "검색 중 오류가 발생했습니다.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  };

  return (
    <div style={{ maxWidth: 720, margin: "0 auto" }}>
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>
        🧭 메뉴얼 검색 (GPT 기반)
      </h2>
      <p style={{ fontSize: 13, color: "#718096", marginBottom: 20 }}>
        출입국 법령·절차에 관한 궁금한 내용을 입력하세요. GPT가 요약 답변을 제공합니다.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="예: F-4에서 F-5 변경 조건은?"
          rows={3}
          style={{
            width: "100%",
            padding: "10px 14px",
            borderRadius: 8,
            border: "1px solid var(--hw-border, #E2E8F0)",
            fontSize: 14,
            resize: "vertical",
            outline: "none",
            background: "var(--hw-card-bg, #fff)",
            color: "inherit",
          }}
        />
        <button
          onClick={handleSearch}
          disabled={loading || !question.trim()}
          style={{
            alignSelf: "flex-start",
            padding: "8px 20px",
            borderRadius: 8,
            border: "none",
            background: "var(--hw-gold, #D4A017)",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: loading || !question.trim() ? "not-allowed" : "pointer",
            opacity: loading || !question.trim() ? 0.6 : 1,
          }}
        >
          {loading ? "답변 생성 중..." : "🔍 GPT로 검색하기"}
        </button>
      </div>

      {error && (
        <div
          style={{
            marginTop: 20,
            padding: "12px 16px",
            borderRadius: 8,
            background: "#FFF5F5",
            border: "1px solid #FED7D7",
            color: "#C53030",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {answer !== null && !error && (
        <div
          style={{
            marginTop: 24,
            padding: "16px 20px",
            borderRadius: 10,
            background: "var(--hw-card-bg, #fff)",
            border: "1px solid var(--hw-border, #E2E8F0)",
            boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
          }}
        >
          <div
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: "var(--hw-gold, #D4A017)",
              marginBottom: 10,
            }}
          >
            🧠 GPT 요약 답변
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.75, whiteSpace: "pre-wrap" }}>
            {answer}
          </div>
        </div>
      )}
    </div>
  );
}
