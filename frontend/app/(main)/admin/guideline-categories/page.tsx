"use client";
import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import { guidelineCategoriesApi, type GuidelineCategory } from "@/lib/api";

const LEVEL_LABEL: Record<string, string> = { major: "대분류", middle: "주분류", minor: "소분류" };
const BORDER = "#E2E8F0";

export default function GuidelineCategoriesAdminPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const user = getUser();
  const isAdmin = !!user?.is_admin;

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["guideline-categories", "admin"],
    queryFn: () => guidelineCategoriesApi.list(true).then((r) => r.data),
    enabled: isAdmin,
    retry: false,
  });

  const cats = data?.categories ?? [];
  const byParent = useMemo(() => {
    const m = new Map<number | null, GuidelineCategory[]>();
    cats.forEach((c) => {
      const k = c.parent_id ?? null;
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(c);
    });
    Array.from(m.values()).forEach((arr: GuidelineCategory[]) =>
      arr.sort((a, b) => a.sort_order - b.sort_order || a.id - b.id));
    return m;
  }, [cats]);
  const majors = useMemo(() => cats.filter((c) => c.level === "major").sort((a, b) => a.sort_order - b.sort_order || a.id - b.id), [cats]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["guideline-categories"] });
  };
  const mUpdate = useMutation({
    mutationFn: (v: { id: number; data: Record<string, unknown> }) => guidelineCategoriesApi.update(v.id, v.data),
    onSuccess: () => { toast.success("저장됨"); invalidate(); },
    onError: () => toast.error("저장 실패"),
  });
  const mDeactivate = useMutation({
    mutationFn: (id: number) => guidelineCategoriesApi.deactivate(id),
    onSuccess: () => { toast.success("비활성화됨"); invalidate(); },
    onError: () => toast.error("실패"),
  });
  const mCreate = useMutation({
    mutationFn: (v: { level: string; parent_id: number | null; display_name: string }) => guidelineCategoriesApi.create(v),
    onSuccess: () => { toast.success("추가됨"); invalidate(); },
    onError: () => toast.error("추가 실패"),
  });
  const mSeed = useMutation({
    mutationFn: () => guidelineCategoriesApi.seedFromJson(),
    onSuccess: (r) => { toast.success(`기본 분류 생성 ${r.data.created}건`); invalidate(); },
    onError: () => toast.error("시드 실패"),
  });

  if (!isAdmin) {
    return <div style={{ padding: 40, color: "#C53030" }}>관리자만 접근할 수 있습니다. <button onClick={() => router.replace("/dashboard")} style={{ marginLeft: 8 }}>홈으로</button></div>;
  }

  const childLevel = (lv: string) => (lv === "major" ? "middle" : lv === "middle" ? "minor" : null);

  function CatRow({ c, depth }: { c: GuidelineCategory; depth: number }) {
    const [name, setName] = useState(c.display_name);
    const [order, setOrder] = useState(String(c.sort_order));
    const [addName, setAddName] = useState("");
    const cl = childLevel(c.level);
    const children = byParent.get(c.id) ?? [];
    return (
      <div style={{ marginLeft: depth * 18 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
          borderBottom: `1px solid ${BORDER}`, opacity: c.is_active ? 1 : 0.5,
          background: c.is_active ? "#fff" : "#FFF5F5",
        }}>
          <span style={{ fontSize: 10, color: "#A0AEC0", width: 40 }}>{LEVEL_LABEL[c.level] ?? c.level}</span>
          <input value={name} onChange={(e) => setName(e.target.value)}
            style={{ fontSize: 13, padding: "4px 8px", border: `1px solid ${BORDER}`, borderRadius: 6, minWidth: 200 }} />
          <input value={order} onChange={(e) => setOrder(e.target.value)} title="순서" inputMode="numeric"
            style={{ width: 56, fontSize: 12, padding: "4px 6px", border: `1px solid ${BORDER}`, borderRadius: 6, textAlign: "right" }} />
          {!c.is_active && <span style={{ fontSize: 10, color: "#C53030", fontWeight: 700 }}>비활성</span>}
          {c.is_custom && <span style={{ fontSize: 10, color: "#3182CE" }}>커스텀</span>}
          <button onClick={() => mUpdate.mutate({ id: c.id, data: { display_name: name.trim(), sort_order: Number(order) || 0 } })}
            className="btn-primary" style={{ fontSize: 11, padding: "4px 10px" }}>저장</button>
          <button onClick={() => mUpdate.mutate({ id: c.id, data: { is_active: !c.is_active } })}
            style={{ fontSize: 11, padding: "4px 10px", border: `1px solid ${BORDER}`, borderRadius: 6, background: "#fff", cursor: "pointer" }}>
            {c.is_active ? "비활성화" : "활성화"}
          </button>
          {c.is_active && (
            <button onClick={() => { if (confirm("이 분류를 비활성화합니다. (물리삭제 아님, 연결 항목 보존)")) mDeactivate.mutate(c.id); }}
              style={{ fontSize: 11, padding: "4px 10px", border: "1px solid #FEB2B2", borderRadius: 6, background: "#fff", color: "#C53030", cursor: "pointer" }}>삭제(비활성)</button>
          )}
        </div>
        {/* 자식 추가 */}
        {cl && (
          <div style={{ marginLeft: 58, marginTop: 4, marginBottom: 6, display: "flex", gap: 6, alignItems: "center" }}>
            <input value={addName} onChange={(e) => setAddName(e.target.value)} placeholder={`+ ${LEVEL_LABEL[cl]} 추가`}
              style={{ fontSize: 12, padding: "4px 8px", border: `1px dashed ${BORDER}`, borderRadius: 6, minWidth: 180 }} />
            <button onClick={() => { if (addName.trim()) { mCreate.mutate({ level: cl, parent_id: c.id, display_name: addName.trim() }); setAddName(""); } }}
              style={{ fontSize: 11, padding: "4px 10px", border: `1px solid ${BORDER}`, borderRadius: 6, background: "#fff", cursor: "pointer" }}>추가</button>
          </div>
        )}
        {children.map((ch) => <CatRow key={ch.id} c={ch} depth={depth + 1} />)}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1000, margin: "0 auto", padding: "8px 0" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: "#1A202C", margin: 0 }}>🗂 실무지침 분류 관리</h1>
          <p style={{ fontSize: 12, color: "#718096", marginTop: 4 }}>대분류 → 주분류 → 소분류. 이름·순서·활성/비활성·추가. 원본 데이터는 변경되지 않습니다.</p>
        </div>
        <button onClick={() => mSeed.mutate()} disabled={mSeed.isPending} className="btn-secondary" style={{ fontSize: 12, padding: "6px 14px" }}>
          {mSeed.isPending ? "생성 중..." : "기본 분류 생성(JSON 기준)"}
        </button>
      </div>

      {isError && (
        <div style={{ padding: 16, background: "#FFF5F5", border: "1px solid #FEB2B2", borderRadius: 8, color: "#C53030", fontSize: 13 }}>
          분류 데이터를 불러오지 못했습니다. PG 모드(FEATURE_PG_GUIDELINES)가 켜져 있는지 확인하세요. ({String((error as { response?: { status?: number } })?.response?.status ?? "")})
        </div>
      )}
      {isLoading && <div style={{ padding: 40, color: "#718096" }}>불러오는 중...</div>}

      {data && (
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 10, overflow: "hidden" }}>
          {majors.length === 0 ? (
            <div style={{ padding: 24, color: "#A0AEC0", fontSize: 13 }}>
              분류가 없습니다. 우측 상단 “기본 분류 생성(JSON 기준)”을 눌러 현재 실무지침 데이터에서 기본 분류를 만드세요.
            </div>
          ) : majors.map((c) => <CatRow key={c.id} c={c} depth={0} />)}
        </div>
      )}
    </div>
  );
}
