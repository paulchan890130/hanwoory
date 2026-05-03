"use client";
import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { memosApi } from "@/lib/api";
import { Save } from "lucide-react";

function MemoPanel({
  memoType,
  title,
  desc,
}: {
  memoType: "mid" | "long";
  title: string;
  desc: string;
}) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["memo", memoType],
    queryFn: () => memosApi.get(memoType).then((r) => r.data.content || ""),
  });
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data !== undefined) {
      setText(data as string);
      setDirty(false);
    }
  }, [data]);

  const saveMut = useMutation({
    mutationFn: (content: string) => memosApi.save(memoType, content),
    onSuccess: () => {
      toast.success("저장됨");
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["memo", memoType] });
    },
    onError: () => toast.error("저장 실패"),
  });

  const handleSave = () => saveMut.mutate(text);

  return (
    <div
      className="hw-card"
      style={{ display: "flex", flexDirection: "column", gap: "10px", height: "100%" }}
    >
      {/* 패널 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div>
          <span style={{ fontWeight: 600, fontSize: "14px", color: "#1A202C" }}>{title}</span>
          <span style={{ marginLeft: "8px", fontSize: "12px", color: "#A0AEC0" }}>{desc}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          {dirty && (
            <span style={{ fontSize: "11px", color: "#D4A843" }}>● 미저장</span>
          )}
          <button
            onClick={handleSave}
            disabled={saveMut.isPending || !dirty}
            className="btn-primary"
            style={{ display: "flex", alignItems: "center", gap: "4px", fontSize: "12px", opacity: (saveMut.isPending || !dirty) ? 0.4 : 1 }}
          >
            <Save size={12} />
            {saveMut.isPending ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>

      {/* 텍스트 에디터 */}
      <textarea
        className="hw-input"
        style={{
          flex: 1,
          width: "100%",
          resize: "none",
          fontSize: "13px",
          fontFamily: "monospace",
          lineHeight: 1.8,
          letterSpacing: "0.01em",
          minHeight: "420px",
        }}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setDirty(true);
        }}
        placeholder={`${title}를 입력하세요... (Ctrl+S로 저장)`}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "s") {
            e.preventDefault();
            if (dirty) handleSave();
          }
        }}
      />

      <p style={{ fontSize: "11px", color: "#A0AEC0" }}>
        Ctrl+S (또는 Cmd+S) 로 저장
      </p>
    </div>
  );
}

export default function MemosPage() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px", height: "100%" }}>
      {/* 페이지 헤더 */}
      <h1 className="hw-page-title">메모</h1>

      {/* 2컬럼 레이아웃 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "16px",
          alignItems: "start",
        }}
      >
        <MemoPanel
          memoType="long"
          title="📚 장기 메모"
          desc="참고사항, 업무 지침"
        />
        <MemoPanel
          memoType="mid"
          title="📝 중기 메모"
          desc="이번 주/이번 달 업무"
        />
      </div>
    </div>
  );
}
