"use client";
import { useState, useEffect } from "react";
import type { ActiveTask } from "@/lib/api";
import { safeInt } from "@/lib/utils";

// ── helpers ───────────────────────────────────────────────────────────────────
function dPlusFromTs(ts: string): number {
  if (!ts) return 0;
  const start = new Date(ts.slice(0, 10));
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86_400_000));
}
function fmtDate(iso: string): string { return iso ? iso.slice(5, 10).replace("-", "/") : ""; }
function dpColor(dp: number, hasReception: boolean): string {
  if (!hasReception) return "#2563EB";
  if (dp >= 20) return "#DC2626";
  if (dp >= 10) return "#D97706";
  return "#16A34A";
}

// ── ActiveTaskRow (테이블 행) — D+ 색상 추가 ──────────────────────────────────
function ActiveTaskRow({
  task, onSave, onToggleComplete, onToggleDelete, markedComplete, markedDelete,
  onProgressToggle, pendingReception, pendingProcessing, pendingStorage,
}: {
  task: ActiveTask;
  onSave: (id: string, data: Partial<ActiveTask>) => void;
  onToggleComplete: (id: string) => void;
  onToggleDelete: (id: string) => void;
  markedComplete: boolean;
  markedDelete: boolean;
  onProgressToggle: (id: string, field: "reception" | "processing" | "storage") => void;
  pendingReception: string;
  pendingProcessing: string;
  pendingStorage: string;
}) {
  const [category,   setCategory]   = useState(task.category   ?? "");
  const [date,       setDate]       = useState(task.date        ?? "");
  const [name,       setName]       = useState(task.name        ?? "");
  const [work,       setWork]       = useState(task.work        ?? "");
  const [details,    setDetails]    = useState(task.details     ?? "");
  const [transfer,   setTransfer]   = useState(String(safeInt(task.transfer)   || ""));
  const [cash,       setCash]       = useState(String(safeInt(task.cash)       || ""));
  const [card,       setCard]       = useState(String(safeInt(task.card)       || ""));
  const [stamp,      setStamp]      = useState(String(safeInt(task.stamp)      || ""));
  const [receivable, setReceivable] = useState(String(safeInt(task.receivable) || ""));
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setCategory(task.category ?? ""); setDate(task.date ?? ""); setName(task.name ?? "");
    setWork(task.work ?? ""); setDetails(task.details ?? "");
    setTransfer(String(safeInt(task.transfer) || "")); setCash(String(safeInt(task.cash) || ""));
    setCard(String(safeInt(task.card) || "")); setStamp(String(safeInt(task.stamp) || ""));
    setReceivable(String(safeInt(task.receivable) || "")); setDirty(false);
  }, [task.id, task.category, task.date, task.name, task.work, task.details,
      task.transfer, task.cash, task.card, task.stamp, task.receivable]);

  const mark = () => setDirty(true);
  const handleSave = () => {
    onSave(task.id, {
      category, date, name, work, details,
      transfer: String(safeInt(transfer) || 0), cash: String(safeInt(cash) || 0),
      card: String(safeInt(card) || 0), stamp: String(safeInt(stamp) || 0),
      receivable: String(safeInt(receivable) || 0),
    });
    setDirty(false);
  };

  const latestTs = [pendingStorage, pendingProcessing, pendingReception].filter(Boolean).sort().reverse()[0] ?? "";
  const dp = dPlusFromTs(latestTs);
  const color = dpColor(dp, !!pendingReception);

  const rowBg = markedDelete
    ? "rgba(229,62,62,0.06)"
    : markedComplete
    ? "rgba(72,187,120,0.08)"
    : undefined;

  const inp: React.CSSProperties = {
    width: "100%", padding: "3px 5px", fontSize: 12,
    border: "1px solid transparent", borderRadius: 4,
    background: "transparent", outline: "none", boxSizing: "border-box",
  };

  return (
    <tr style={{ background: rowBg }}>
      {/* 분류 — D+ 색상 적용 */}
      <td style={{ borderLeft: `3px solid ${color}` }}>
        <input className="hw-table-input" style={inp}
          value={category} onChange={e => { setCategory(e.target.value); mark(); }} />
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <input className="hw-table-input" style={inp}
          value={date} onChange={e => { setDate(e.target.value); mark(); }} />
      </td>
      <td>
        <input className="hw-table-input" style={inp}
          value={name} onChange={e => { setName(e.target.value); mark(); }} />
      </td>
      <td style={{ minWidth: 110 }}>
        <input className="hw-table-input" style={inp}
          value={work} onChange={e => { setWork(e.target.value); mark(); }} />
      </td>
      <td style={{ minWidth: 130 }}>
        <input className="hw-table-input" style={inp}
          value={details} onChange={e => { setDetails(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={transfer} placeholder="이체" onChange={e => { setTransfer(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={cash} placeholder="현금" onChange={e => { setCash(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={card} placeholder="카드" onChange={e => { setCard(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={stamp} placeholder="인지" onChange={e => { setStamp(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={receivable} placeholder="미수" onChange={e => { setReceivable(e.target.value); mark(); }} />
      </td>
      {/* 저장 버튼 */}
      <td style={{ textAlign: "center", width: 36, verticalAlign: "middle" }}>
        {dirty && (
          <button onClick={handleSave} style={{
            padding: "2px 7px", fontSize: 9, fontWeight: 700,
            background: "#D4A843", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer",
          }}>저장</button>
        )}
      </td>
      {/* 접수 / 처리 / 보관중 */}
      <td style={{ minWidth: 160, verticalAlign: "middle" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {/* D+ 뱃지 */}
          {latestTs && (
            <span style={{ fontSize: 10, fontWeight: 700, color }}>D+{dp}</span>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "nowrap" }}>
            {([
              { field: "reception" as const,  label: "접수",  color: "#3182CE", onColor: "#2B6CB0", ts: pendingReception },
              { field: "processing" as const, label: "처리",  color: "#D4A843", onColor: "#96751E", ts: pendingProcessing },
              { field: "storage" as const,    label: "보관중", color: "#9F7AEA", onColor: "#553C9A", ts: pendingStorage },
            ]).map(({ field, label, color: fc, onColor, ts }) => (
              <label key={field} style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
                <input type="checkbox" checked={!!ts}
                  onChange={() => onProgressToggle(task.id, field)}
                  style={{ accentColor: fc, width: 11, height: 11 }} />
                <span style={{ fontSize: 10, color: ts ? onColor : "#A0AEC0", fontWeight: ts ? 700 : 400 }}>{label}</span>
                {ts && <span style={{ fontSize: 9, color: "#A0AEC0" }}>{fmtDate(ts)}</span>}
              </label>
            ))}
          </div>
        </div>
      </td>
      {/* 완료 */}
      <td style={{ textAlign: "center", width: 44 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={markedComplete} onChange={() => onToggleComplete(task.id)}
            style={{ accentColor: "#38A169" }} />
          <span style={{ fontSize: 9, color: "#38A169" }}>완료✅</span>
        </label>
      </td>
      {/* 삭제 */}
      <td style={{ textAlign: "center", width: 44 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={markedDelete} onChange={() => onToggleDelete(task.id)}
            style={{ accentColor: "#E53E3E" }} />
          <span style={{ fontSize: 9, color: "#E53E3E" }}>삭제❌</span>
        </label>
      </td>
    </tr>
  );
}

// ── TaskTableView ─────────────────────────────────────────────────────────────
export interface TaskTableViewProps {
  tasks: ActiveTask[];
  progressPending: Map<string, { reception: string; processing: string; storage: string }>;
  completedIds: Set<string>;
  deleteIds: Set<string>;
  onSave: (id: string, data: Partial<ActiveTask>) => void;
  onToggleComplete: (id: string) => void;
  onToggleDelete: (id: string) => void;
  onProgressToggle: (id: string, field: "reception" | "processing" | "storage") => void;
}

export default function TaskTableView({
  tasks, progressPending, completedIds, deleteIds,
  onSave, onToggleComplete, onToggleDelete, onProgressToggle,
}: TaskTableViewProps) {
  return (
    <div className="overflow-x-auto">
      <table className="hw-table min-w-[1080px]">
        <thead>
          <tr>
            <th className="text-left">분류</th>
            <th className="text-left">날짜</th>
            <th className="text-left">이름</th>
            <th className="text-left">업무</th>
            <th className="text-left">세부내용</th>
            <th className="text-right w-14">이체</th>
            <th className="text-right w-14">현금</th>
            <th className="text-right w-14">카드</th>
            <th className="text-right w-14">인지</th>
            <th className="text-right w-14">미수</th>
            <th style={{ width: 36 }}></th>
            <th style={{ width: 160 }}>접수/처리/보관중</th>
            <th style={{ textAlign: "center", width: 44 }}>완료✅</th>
            <th style={{ textAlign: "center", width: 44 }}>삭제❌</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <ActiveTaskRow
              key={task.id}
              task={task}
              onSave={onSave}
              onToggleComplete={onToggleComplete}
              onToggleDelete={onToggleDelete}
              markedComplete={completedIds.has(task.id)}
              markedDelete={deleteIds.has(task.id)}
              onProgressToggle={onProgressToggle}
              pendingReception={progressPending.get(task.id)?.reception ?? (task.reception as string) ?? ""}
              pendingProcessing={progressPending.get(task.id)?.processing ?? (task.processing as string) ?? ""}
              pendingStorage={progressPending.get(task.id)?.storage ?? (task.storage as string) ?? ""}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
