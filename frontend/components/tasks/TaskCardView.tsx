"use client";
import { useState, useEffect } from "react";
import type { ActiveTask } from "@/lib/api";
import { safeInt, formatNumber } from "@/lib/utils";

// ── helpers ───────────────────────────────────────────────────────────────────
function fmtDate(iso: string): string { return iso ? iso.slice(5, 10).replace("-", "/") : ""; }
function dPlusFromTs(ts: string): number {
  if (!ts) return 0;
  const start = new Date(ts.slice(0, 10));
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86_400_000));
}
function dpBorderColor(dp: number, hasReception: boolean): string {
  if (!hasReception) return "#2563EB";
  if (dp >= 20) return "#DC2626";
  if (dp >= 10) return "#F59E0B";
  return "#16A34A";
}
function dpTextColor(dp: number, hasReception: boolean): string {
  if (!hasReception) return "#2563EB";
  if (dp >= 20) return "#DC2626";
  if (dp >= 10) return "#D97706";
  return "#16A34A";
}

// ── props ─────────────────────────────────────────────────────────────────────
export interface TaskCardViewProps {
  tasks: ActiveTask[];
  progressPending: Map<string, { reception: string; processing: string; storage: string }>;
  onProgressToggle: (id: string, field: "reception" | "processing" | "storage") => void;
  completedIds: Set<string>;
  deleteIds: Set<string>;
  onSave: (id: string, data: Partial<ActiveTask>) => void;
  onToggleComplete: (id: string) => void;
  onToggleDelete: (id: string) => void;
  readonly?: boolean;
}

// ── compact card ─────────────────────────────────────────────────────────────
function CompactCard({
  task, pendingReception, pendingProcessing, pendingStorage,
  markedComplete, markedDelete, onClick,
}: {
  task: ActiveTask;
  pendingReception: string; pendingProcessing: string; pendingStorage: string;
  markedComplete: boolean; markedDelete: boolean;
  onClick: () => void;
}) {
  const latestTs = [pendingStorage, pendingProcessing, pendingReception].filter(Boolean).sort().reverse()[0] ?? "";
  const dp = dPlusFromTs(latestTs);
  const bColor = dpBorderColor(dp, !!pendingReception);
  const tColor = dpTextColor(dp, !!pendingReception);

  const amounts = [
    { k: "이체", v: safeInt(task.transfer) },
    { k: "현금", v: safeInt(task.cash) },
    { k: "카드", v: safeInt(task.card) },
    { k: "인지", v: safeInt(task.stamp) },
    { k: "미수", v: safeInt(task.receivable) },
  ].filter(a => a.v > 0);

  const cardBg = markedDelete
    ? "rgba(229,62,62,0.04)"
    : markedComplete
    ? "rgba(72,187,120,0.06)"
    : "#fff";

  return (
    <div
      onClick={onClick}
      style={{
        background: cardBg,
        border: "1px solid #E2E8F0",
        borderLeft: `4px solid ${bColor}`,
        borderRadius: 8,
        padding: "10px 14px",
        cursor: "pointer",
        marginBottom: 6,
        transition: "box-shadow 0.15s",
        userSelect: "none",
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = "0 2px 8px rgba(0,0,0,0.08)"; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = "none"; }}
    >
      {/* 상단: 분류 + D+ */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {task.category && (
            <span style={{
              fontSize: 10, fontWeight: 700, color: tColor,
              background: `${bColor}18`,
              padding: "2px 7px", borderRadius: 10,
            }}>
              {task.category}
            </span>
          )}
          {(markedComplete || markedDelete) && (
            <span style={{ fontSize: 10 }}>
              {markedComplete ? "✅" : "❌"}
            </span>
          )}
        </div>
        {latestTs && (
          <span style={{ fontSize: 12, fontWeight: 700, color: tColor }}>
            D+{dp}
          </span>
        )}
      </div>

      {/* 중단: 이름 + 업무 */}
      <div style={{ fontSize: 14, fontWeight: 700, color: "#1A202C", marginBottom: 2, lineHeight: 1.3 }}>
        {task.name || <span style={{ color: "#CBD5E0" }}>이름 없음</span>}
      </div>
      {task.work && (
        <div style={{ fontSize: 13, color: "#4A5568", marginBottom: 4 }}>{task.work}</div>
      )}
      {task.details && (
        <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {task.details}
        </div>
      )}

      {/* 하단: 금액 + 날짜 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", gap: 8, fontSize: 12, color: "#2D3748" }}>
          {amounts.map(a => (
            <span key={a.k}>{a.k} {formatNumber(a.v)}</span>
          ))}
        </div>
        {task.date && (
          <span style={{ fontSize: 12, color: "#A0AEC0" }}>{task.date}</span>
        )}
      </div>
    </div>
  );
}

// ── expanded card (full edit) ─────────────────────────────────────────────────
function ExpandedCard({
  task, pendingReception, pendingProcessing, pendingStorage,
  onProgressToggle, onSave, markedComplete, markedDelete,
  onToggleComplete, onToggleDelete, onCollapse, readonly,
}: {
  task: ActiveTask;
  pendingReception: string; pendingProcessing: string; pendingStorage: string;
  onProgressToggle: (id: string, field: "reception" | "processing" | "storage") => void;
  onSave: (id: string, data: Partial<ActiveTask>) => void;
  markedComplete: boolean; markedDelete: boolean;
  onToggleComplete: (id: string) => void;
  onToggleDelete: (id: string) => void;
  onCollapse: () => void;
  readonly?: boolean;
}) {
  const [category, setCategory] = useState(task.category ?? "");
  const [date, setDate] = useState(task.date ?? "");
  const [name, setName] = useState(task.name ?? "");
  const [work, setWork] = useState(task.work ?? "");
  const [details, setDetails] = useState(task.details ?? "");
  const [transfer, setTransfer] = useState(String(safeInt(task.transfer) || ""));
  const [cash, setCash] = useState(String(safeInt(task.cash) || ""));
  const [card, setCard] = useState(String(safeInt(task.card) || ""));
  const [stamp, setStamp] = useState(String(safeInt(task.stamp) || ""));
  const [receivable, setReceivable] = useState(String(safeInt(task.receivable) || ""));
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setCategory(task.category ?? ""); setDate(task.date ?? ""); setName(task.name ?? "");
    setWork(task.work ?? ""); setDetails(task.details ?? "");
    setTransfer(String(safeInt(task.transfer) || "")); setCash(String(safeInt(task.cash) || ""));
    setCard(String(safeInt(task.card) || "")); setStamp(String(safeInt(task.stamp) || ""));
    setReceivable(String(safeInt(task.receivable) || "")); setDirty(false);
  }, [task.id]);

  const mark = () => setDirty(true);
  const handleSave = () => {
    onSave(task.id, { category, date, name, work, details,
      transfer: String(safeInt(transfer) || 0), cash: String(safeInt(cash) || 0),
      card: String(safeInt(card) || 0), stamp: String(safeInt(stamp) || 0),
      receivable: String(safeInt(receivable) || 0),
    });
    setDirty(false);
  };

  const latestTs = [pendingStorage, pendingProcessing, pendingReception].filter(Boolean).sort().reverse()[0] ?? "";
  const dp = dPlusFromTs(latestTs);
  const bColor = dpBorderColor(dp, !!pendingReception);

  const inp: React.CSSProperties = {
    width: "100%", padding: "4px 8px", fontSize: 13,
    border: "1px solid #E2E8F0", borderRadius: 5, background: "#FAFAFA",
    outline: "none", boxSizing: "border-box",
  };

  return (
    <div style={{
      background: "#fff",
      border: "1px solid #E2E8F0",
      borderLeft: `4px solid ${bColor}`,
      borderRadius: 8,
      padding: "12px 14px",
      marginBottom: 6,
      boxShadow: "0 2px 12px rgba(0,0,0,0.08)",
    }}>
      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#718096" }}>편집 중 {latestTs && `· D+${dp}`}</span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {dirty && !readonly && (
            <button onClick={handleSave} style={{
              padding: "3px 10px", fontSize: 11, fontWeight: 700,
              background: "#D4A843", color: "#fff",
              border: "none", borderRadius: 5, cursor: "pointer",
            }}>저장</button>
          )}
          <button onClick={onCollapse} style={{
            padding: "3px 8px", fontSize: 11, background: "#F7FAFC",
            border: "1px solid #E2E8F0", borderRadius: 5, cursor: "pointer", color: "#718096",
          }}>접기 ▲</button>
        </div>
      </div>

      {/* 필드 그리드 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 3 }}>분류</div>
          {readonly
            ? <div style={{ fontSize: 13 }}>{task.category}</div>
            : <input style={inp} value={category} onChange={e => { setCategory(e.target.value); mark(); }} />}
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 3 }}>날짜</div>
          {readonly
            ? <div style={{ fontSize: 13 }}>{task.date}</div>
            : <input style={inp} value={date} onChange={e => { setDate(e.target.value); mark(); }} />}
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 3 }}>이름</div>
          {readonly
            ? <div style={{ fontSize: 13, fontWeight: 600 }}>{task.name}</div>
            : <input style={inp} value={name} onChange={e => { setName(e.target.value); mark(); }} />}
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 3 }}>업무</div>
          {readonly
            ? <div style={{ fontSize: 13 }}>{task.work}</div>
            : <input style={inp} value={work} onChange={e => { setWork(e.target.value); mark(); }} />}
        </div>
      </div>
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 3 }}>세부내용</div>
        {readonly
          ? <div style={{ fontSize: 13, color: "#718096" }}>{task.details}</div>
          : <input style={inp} value={details} onChange={e => { setDetails(e.target.value); mark(); }} />}
      </div>

      {/* 금액 */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {([
          { label: "이체", val: transfer, set: setTransfer },
          { label: "현금", val: cash, set: setCash },
          { label: "카드", val: card, set: setCard },
          { label: "인지", val: stamp, set: setStamp },
          { label: "미수", val: receivable, set: setReceivable },
        ] as const).map(({ label, val, set }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ fontSize: 11, color: "#A0AEC0" }}>{label}</span>
            {readonly
              ? <span style={{ fontSize: 13 }}>{safeInt(val) > 0 ? formatNumber(safeInt(val)) : "—"}</span>
              : <input type="text" inputMode="numeric"
                  style={{ ...inp, width: 80, textAlign: "right", padding: "3px 6px" }}
                  value={val} placeholder="0"
                  onChange={e => { (set as (v: string) => void)(e.target.value); mark(); }} />}
          </div>
        ))}
      </div>

      {/* 접수/처리/보관 + 완료/삭제 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderTop: "1px solid #F7FAFC", paddingTop: 8 }}>
        <div style={{ display: "flex", gap: 10 }}>
          {([
            { field: "reception" as const, label: "접수", color: "#3182CE", ts: pendingReception },
            { field: "processing" as const, label: "처리", color: "#D4A843", ts: pendingProcessing },
            { field: "storage" as const, label: "보관중", color: "#9F7AEA", ts: pendingStorage },
          ]).map(({ field, label, color, ts }) => (
            <label key={field} style={{ display: "flex", alignItems: "center", gap: 3, cursor: readonly ? "default" : "pointer" }}>
              <input type="checkbox" checked={!!ts} disabled={readonly}
                onChange={() => !readonly && onProgressToggle(task.id, field)}
                style={{ accentColor: color, width: 12, height: 12 }} />
              <span style={{ fontSize: 11, color: ts ? color : "#A0AEC0", fontWeight: ts ? 700 : 400 }}>{label}</span>
              {ts && <span style={{ fontSize: 10, color: "#A0AEC0" }}>{fmtDate(ts)}</span>}
            </label>
          ))}
        </div>
        {!readonly && (
          <div style={{ display: "flex", gap: 10 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 3, cursor: "pointer", fontSize: 11, color: "#38A169" }}>
              <input type="checkbox" checked={markedComplete} onChange={() => onToggleComplete(task.id)}
                style={{ accentColor: "#38A169", width: 12, height: 12 }} /> 완료✅
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 3, cursor: "pointer", fontSize: 11, color: "#E53E3E" }}>
              <input type="checkbox" checked={markedDelete} onChange={() => onToggleDelete(task.id)}
                style={{ accentColor: "#E53E3E", width: 12, height: 12 }} /> 삭제❌
            </label>
          </div>
        )}
      </div>
    </div>
  );
}

// ── column ────────────────────────────────────────────────────────────────────
function KanbanColumn({
  title, headerColor, tasks, expandedId, onExpand,
  progressPending, onProgressToggle, completedIds, deleteIds,
  onSave, onToggleComplete, onToggleDelete, readonly,
}: {
  title: string; headerColor: string; tasks: ActiveTask[];
  expandedId: string | null; onExpand: (id: string | null) => void;
  progressPending: Map<string, { reception: string; processing: string; storage: string }>;
  onProgressToggle: (id: string, field: "reception" | "processing" | "storage") => void;
  completedIds: Set<string>; deleteIds: Set<string>;
  onSave: (id: string, data: Partial<ActiveTask>) => void;
  onToggleComplete: (id: string) => void; onToggleDelete: (id: string) => void;
  readonly?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      {/* 컬럼 헤더 */}
      <div style={{
        padding: "8px 12px 8px",
        borderTop: `3px solid ${headerColor}`,
        background: `${headerColor}10`,
        borderRadius: "0 0 4px 4px",
        marginBottom: 10,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>{title}</span>
        <span style={{
          fontSize: 11, fontWeight: 700,
          background: headerColor, color: "#fff",
          padding: "1px 8px", borderRadius: 10,
        }}>{tasks.length}</span>
      </div>

      {/* 카드 목록 */}
      {tasks.length === 0 ? (
        <div style={{ padding: "16px 0", textAlign: "center", fontSize: 12, color: "#CBD5E0",
          border: "1px dashed #E2E8F0", borderRadius: 8 }}>업무 없음</div>
      ) : (
        tasks.map((task) => {
          const p = progressPending.get(task.id);
          const pR = p?.reception ?? (task.reception as string) ?? "";
          const pP = p?.processing ?? (task.processing as string) ?? "";
          const pS = p?.storage ?? (task.storage as string) ?? "";
          const isExpanded = expandedId === task.id;

          if (isExpanded) {
            return (
              <ExpandedCard
                key={task.id} task={task}
                pendingReception={pR} pendingProcessing={pP} pendingStorage={pS}
                onProgressToggle={onProgressToggle} onSave={onSave}
                markedComplete={completedIds.has(task.id)} markedDelete={deleteIds.has(task.id)}
                onToggleComplete={onToggleComplete} onToggleDelete={onToggleDelete}
                onCollapse={() => onExpand(null)}
                readonly={readonly}
              />
            );
          }
          return (
            <CompactCard
              key={task.id} task={task}
              pendingReception={pR} pendingProcessing={pP} pendingStorage={pS}
              markedComplete={completedIds.has(task.id)} markedDelete={deleteIds.has(task.id)}
              onClick={() => onExpand(task.id)}
            />
          );
        })
      )}
    </div>
  );
}

// ── main ──────────────────────────────────────────────────────────────────────
export default function TaskCardView({
  tasks, progressPending, onProgressToggle,
  completedIds, deleteIds, onSave, onToggleComplete, onToggleDelete, readonly,
}: TaskCardViewProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const col1: ActiveTask[] = [], col2: ActiveTask[] = [], col3: ActiveTask[] = [];
  for (const t of tasks) {
    const p = progressPending.get(t.id);
    const storage    = p?.storage    || (t.storage    as string) || "";
    const processing = p?.processing || (t.processing as string) || "";
    if (storage) col3.push(t);
    else if (processing) col2.push(t);
    else col1.push(t);
  }

  const colProps = { expandedId, onExpand: setExpandedId, progressPending, onProgressToggle,
    completedIds, deleteIds, onSave, onToggleComplete, onToggleDelete, readonly };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, padding: "12px 0", alignItems: "start" }}>
      <KanbanColumn title="접수 중"  headerColor="#2563EB" tasks={col1} {...colProps} />
      <KanbanColumn title="처리 중"  headerColor="#D4A843" tasks={col2} {...colProps} />
      <KanbanColumn title="보관 중"  headerColor="#9F7AEA" tasks={col3} {...colProps} />
    </div>
  );
}
