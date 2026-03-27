"use client";
import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  tasksApi, memosApi, eventsApi, customersApi,
  type ActiveTask, type PlannedTask, type ExpiryAlert,
} from "@/lib/api";
import { getUser } from "@/lib/auth";
import { safeInt, formatNumber } from "@/lib/utils";
import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import {
  Save, CheckCircle, UserPlus, ClipboardList,
  ScanLine, CalendarPlus, X,
} from "lucide-react";

// ── 공휴일 데이터 ────────────────────────────────────────────────────────────
const CN_HOLIDAYS = new Set([
  // 2025 중국 공휴일
  "2025-01-01","2025-01-28","2025-01-29","2025-01-30","2025-01-31",
  "2025-02-01","2025-02-02","2025-02-03","2025-02-04",
  "2025-04-04","2025-04-05","2025-04-06",
  "2025-05-01","2025-05-02","2025-05-03","2025-05-04","2025-05-05",
  "2025-05-31","2025-06-01","2025-06-02",
  "2025-10-01","2025-10-02","2025-10-03","2025-10-04","2025-10-05","2025-10-06","2025-10-07",
  "2025-10-06",
  // 2026 중국 공휴일
  "2026-01-01",
  "2026-02-17","2026-02-18","2026-02-19","2026-02-20","2026-02-21","2026-02-22","2026-02-23",
  "2026-04-05",
  "2026-05-01","2026-05-02","2026-05-03","2026-05-04","2026-05-05",
  "2026-06-19","2026-06-20","2026-06-21",
  "2026-09-25","2026-09-26","2026-09-27",
  "2026-10-01","2026-10-02","2026-10-03","2026-10-04","2026-10-05","2026-10-06","2026-10-07",
]);

const KR_HOLIDAYS = new Set([
  // 2025 한국 공휴일
  "2025-01-01",
  "2025-01-28","2025-01-29","2025-01-30",
  "2025-03-01","2025-05-05","2025-06-06",
  "2025-08-15",
  "2025-10-03","2025-10-05","2025-10-06","2025-10-07","2025-10-08","2025-10-09",
  "2025-12-25",
  // 2026 한국 공휴일
  "2026-01-01",
  "2026-02-16","2026-02-17","2026-02-18",
  "2026-03-01","2026-05-05","2026-06-06",
  "2026-08-15",
  "2026-09-23","2026-09-24","2026-09-25",
  "2026-10-03","2026-10-09",
  "2026-12-25",
]);

// ── 빠른 액션 바 ────────────────────────────────────────────────────────────────
function QuickActions() {
  const router = useRouter();
  const ACTIONS = [
    { label: "신규 고객",     icon: UserPlus,      href: "/customers?action=new" },
    { label: "진행업무 추가", icon: ClipboardList, href: "/tasks?tab=active&action=new" },
    { label: "OCR 스캔",     icon: ScanLine,      href: "/scan" },
    { label: "일정 추가",    icon: CalendarPlus,  href: "/dashboard?action=event" },
  ];
  return (
    <div className="hw-quick-actions">
      {ACTIONS.map(({ label, icon: Icon, href }) => (
        <button key={href} className="hw-quick-action-btn" onClick={() => router.push(href)}>
          <Icon size={16} />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}

// ── 만기 알림 테이블 (스크롤 제한) ─────────────────────────────────────────────
function ExpiryTable({ rows, dateField }: { rows: ExpiryAlert[]; dateField: string }) {
  if (!rows.length) return <p style={{ fontSize: 12, color: "#A0AEC0", padding: "6px 0" }}>(만기 예정 없음)</p>;
  return (
    <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: 290 }}>
      <table className="hw-table">
        <thead>
          <tr>
            <th>한글이름</th>
            <th>{dateField}</th>
            <th>여권번호</th>
            <th>생년월일</th>
            <th>전화번호</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontWeight: 500 }}>{r.한글이름}</td>
              <td style={{ color: "#DD6B20", fontWeight: 600 }}>
                {dateField === "등록증만기일" ? r.등록증만기일 : r.여권만기일}
              </td>
              <td>{r.여권번호}</td>
              <td>{r.생년월일}</td>
              <td>{r.전화번호}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── 진행업무 D+ 헬퍼 (가장 최근 체크 타임스탬프 기준) ─────────────────────────
function latestStageTs(task: ActiveTask): string {
  return [task.storage || "", task.processing || "", task.reception || ""]
    .filter(Boolean)
    .sort()
    .reverse()[0] ?? "";
}

function dPlusFromTs(ts: string): number {
  if (!ts) return 0;
  const start = new Date(ts.slice(0, 10));
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86_400_000));
}

function fmtDate(iso: string): string {
  // "2026-03-25T..." → "03/25"
  return iso ? iso.slice(5, 10).replace("-", "/") : "";
}

// ── 진행업무 행 ─────────────────────────────────────────────────────────────────
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
  // All editable fields as local controlled state — nothing persists until the row save button is clicked
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

  // Sync all local state when server data changes (after save / refetch)
  useEffect(() => {
    setCategory(task.category ?? "");
    setDate(task.date ?? "");
    setName(task.name ?? "");
    setWork(task.work ?? "");
    setDetails(task.details ?? "");
    setTransfer(String(safeInt(task.transfer) || ""));
    setCash(String(safeInt(task.cash) || ""));
    setCard(String(safeInt(task.card) || ""));
    setStamp(String(safeInt(task.stamp) || ""));
    setReceivable(String(safeInt(task.receivable) || ""));
    setDirty(false);
  }, [task.id, task.category, task.date, task.name, task.work, task.details,
      task.transfer, task.cash, task.card, task.stamp, task.receivable]);

  const mark = () => setDirty(true);

  const toggleLocal = (field: "reception" | "processing" | "storage") => {
    onProgressToggle(task.id, field);
  };

  const handleSave = () => {
    onSave(task.id, {
      category, date, name, work, details,
      transfer: safeInt(transfer) || 0,
      cash: safeInt(cash) || 0,
      card: safeInt(card) || 0,
      stamp: safeInt(stamp) || 0,
      receivable: safeInt(receivable) || 0,
    });
    setDirty(false);
  };

  // Display uses parent-managed pending state so checkboxes feel responsive
  const latestTs = [pendingStorage, pendingProcessing, pendingReception]
    .filter(Boolean).sort().reverse()[0] ?? "";
  const dp = dPlusFromTs(latestTs);
  const rowBg = markedDelete
    ? "rgba(229,62,62,0.06)"
    : markedComplete
    ? "rgba(72,187,120,0.08)"
    : undefined;

  return (
    <tr style={{ background: rowBg }}>
      <td>
        <input className="hw-table-input" value={category}
          onChange={(e) => { setCategory(e.target.value); mark(); }} />
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <input className="hw-table-input" value={date}
          onChange={(e) => { setDate(e.target.value); mark(); }} />
      </td>
      <td>
        <input className="hw-table-input" value={name}
          onChange={(e) => { setName(e.target.value); mark(); }} />
      </td>
      <td style={{ minWidth: 110 }}>
        <input className="hw-table-input" value={work}
          onChange={(e) => { setWork(e.target.value); mark(); }} />
      </td>
      <td style={{ minWidth: 130 }}>
        <input className="hw-table-input" value={details}
          onChange={(e) => { setDetails(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={transfer} placeholder="이체"
          onChange={(e) => { setTransfer(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={cash} placeholder="현금"
          onChange={(e) => { setCash(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={card} placeholder="카드"
          onChange={(e) => { setCard(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={stamp} placeholder="인지"
          onChange={(e) => { setStamp(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={receivable} placeholder="미수"
          onChange={(e) => { setReceivable(e.target.value); mark(); }} />
      </td>
      {/* 필드 저장 버튼 — progress 체크박스와 완전히 분리된 전용 열 */}
      <td style={{ textAlign: "center", width: 36, verticalAlign: "middle" }}>
        {dirty && (
          <button
            onClick={handleSave}
            style={{
              padding: "2px 7px", fontSize: 9, fontWeight: 700,
              background: "#F5A623", color: "#fff",
              border: "none", borderRadius: 4, cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            저장
          </button>
        )}
      </td>
      {/* 접수 / 처리 / 보관중 — 가로 배치, 저장 버튼 없음 (선택 처리로만 저장) */}
      <td style={{ minWidth: 160, verticalAlign: "middle" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {latestTs ? (
            <span style={{ fontSize: 10, fontWeight: 700, color: "#718096" }}>D+{dp}</span>
          ) : null}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "nowrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
              <input type="checkbox" checked={!!pendingReception} onChange={() => toggleLocal("reception")}
                style={{ accentColor: "#3182CE", width: 11, height: 11 }} />
              <span style={{ fontSize: 10, color: pendingReception ? "#2B6CB0" : "#A0AEC0", fontWeight: pendingReception ? 700 : 400 }}>접수</span>
              {pendingReception && <span style={{ fontSize: 9, color: "#A0AEC0" }}>{fmtDate(pendingReception)}</span>}
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
              <input type="checkbox" checked={!!pendingProcessing} onChange={() => toggleLocal("processing")}
                style={{ accentColor: "#D69E2E", width: 11, height: 11 }} />
              <span style={{ fontSize: 10, color: pendingProcessing ? "#975A16" : "#A0AEC0", fontWeight: pendingProcessing ? 700 : 400 }}>처리</span>
              {pendingProcessing && <span style={{ fontSize: 9, color: "#A0AEC0" }}>{fmtDate(pendingProcessing)}</span>}
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
              <input type="checkbox" checked={!!pendingStorage} onChange={() => toggleLocal("storage")}
                style={{ accentColor: "#9F7AEA", width: 11, height: 11 }} />
              <span style={{ fontSize: 10, color: pendingStorage ? "#553C9A" : "#A0AEC0", fontWeight: pendingStorage ? 700 : 400 }}>보관중</span>
              {pendingStorage && <span style={{ fontSize: 9, color: "#A0AEC0" }}>{fmtDate(pendingStorage)}</span>}
            </label>
          </div>
        </div>
      </td>
      {/* 완료 체크박스 */}
      <td style={{ textAlign: "center", width: 44 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={markedComplete}
            onChange={() => onToggleComplete(task.id)}
            style={{ accentColor: "#38A169" }} />
          <span style={{ fontSize: 9, color: "#38A169" }}>완료✅</span>
        </label>
      </td>
      {/* 삭제 체크박스 */}
      <td style={{ textAlign: "center", width: 44 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={markedDelete}
            onChange={() => onToggleDelete(task.id)}
            style={{ accentColor: "#E53E3E" }} />
          <span style={{ fontSize: 9, color: "#E53E3E" }}>삭제❌</span>
        </label>
      </td>
    </tr>
  );
}

// ── 예정업무 행 (인라인 편집 + 명시적 저장 버튼) ─────────────────────────────
function PlannedTaskRow({
  task, onUpdate,
}: {
  task: PlannedTask;
  onUpdate: (id: string, data: Partial<PlannedTask>) => void;
}) {
  const [period, setPeriod] = useState(task.period ?? "");
  const [date, setDate] = useState(task.date ?? "");
  const [content, setContent] = useState(task.content ?? "");
  const [note, setNote] = useState(task.note ?? "");
  const [dirty, setDirty] = useState(false);

  // Sync if task data changes (e.g. after refetch)
  useEffect(() => {
    setPeriod(task.period ?? "");
    setDate(task.date ?? "");
    setContent(task.content ?? "");
    setNote(task.note ?? "");
    setDirty(false);
  }, [task.id, task.period, task.date, task.content, task.note]);

  const mark = () => setDirty(true);
  const handleSave = () => {
    onUpdate(task.id, { period, date, content, note });
    setDirty(false);
  };

  const periodColor =
    period === "단기🔴" ? "#C53030" :
    period === "중기🟡" ? "#975A16" :
    period === "장기🟢" ? "#276749" :
    period === "완료✅" ? "#A0AEC0" :
    "#4A5568";

  return (
    <tr style={{ opacity: period === "완료✅" ? 0.55 : 1 }}>
      <td style={{ whiteSpace: "nowrap" }}>
        <select
          style={{ background: "transparent", fontSize: 12, border: "none", outline: "none", cursor: "pointer", color: periodColor, fontWeight: 600 }}
          value={period}
          onChange={(e) => { setPeriod(e.target.value); mark(); }}
        >
          {["장기🟢","중기🟡","단기🔴","완료✅","보류⏹️"].map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <input className="hw-table-input" value={date}
          onChange={(e) => { setDate(e.target.value); mark(); }} />
      </td>
      <td>
        <input className="hw-table-input" style={{ minWidth: 160 }} value={content}
          onChange={(e) => { setContent(e.target.value); mark(); }} />
      </td>
      <td>
        <input className="hw-table-input" style={{ minWidth: 100 }} value={note}
          onChange={(e) => { setNote(e.target.value); mark(); }} />
      </td>
      <td style={{ width: 52 }}>
        <button
          onClick={handleSave}
          disabled={!dirty}
          style={{
            padding: "3px 8px", fontSize: 10, fontWeight: 700,
            background: dirty ? "#F5A623" : "#E2E8F0",
            color: dirty ? "#fff" : "#A0AEC0",
            border: "none", borderRadius: 4,
            cursor: dirty ? "pointer" : "default",
            whiteSpace: "nowrap",
          }}
        >
          저장
        </button>
      </td>
    </tr>
  );
}

// Stable constants — defined outside the component so their identity never changes
const CAL_PLUGINS = [dayGridPlugin, interactionPlugin];
const CAL_HEADER_TOOLBAR = { left: "prev", center: "title", right: "next" } as const;

// ── 메인 대시보드 ────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const qc = useQueryClient();
  const user = getUser();
  const router = useRouter();

  const { data: activeTasks = [] } = useQuery({
    queryKey: ["tasks", "active"],
    queryFn: () => tasksApi.getActive().then((r) => r.data),
  });
  const { data: plannedTasks = [] } = useQuery({
    queryKey: ["tasks", "planned"],
    queryFn: () => tasksApi.getPlanned().then((r) => r.data),
  });
  const { data: shortMemo } = useQuery({
    queryKey: ["memo", "short"],
    queryFn: () => memosApi.get("short").then((r) => r.data.content || ""),
  });
  const { data: events = {} } = useQuery({
    queryKey: ["events"],
    queryFn: () => eventsApi.get().then((r) => r.data),
  });
  const { data: expiryData } = useQuery({
    queryKey: ["expiry-alerts"],
    queryFn: () => customersApi.expiryAlerts().then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const [memoText, setMemoText] = useState("");
  const [completedIds, setCompletedIds] = useState<Set<string>>(new Set());
  const [deleteIds, setDeleteIds] = useState<Set<string>>(new Set());
  // Map of task.id → {reception, processing, storage} — mirrors server state, updated on toggle
  const [progressPending, setProgressPending] = useState<Map<string, { reception: string; processing: string; storage: string }>>(() => new Map());
  const [calendarDate, setCalendarDate] = useState<string | null>(null);
  const [calendarMemo, setCalendarMemo] = useState("");
  const [showCalModal, setShowCalModal] = useState(false);
  const [calModalIsEdit, setCalModalIsEdit] = useState(false);

  useEffect(() => {
    if (shortMemo !== undefined) setMemoText(shortMemo as string);
  }, [shortMemo]);

  // Reset progressPending from server data whenever activeTasks refetches
  useEffect(() => {
    const next = new Map<string, { reception: string; processing: string; storage: string }>();
    for (const t of activeTasks as ActiveTask[]) {
      next.set(t.id, {
        reception: (t.reception as string) || "",
        processing: (t.processing as string) || "",
        storage: (t.storage as string) || "",
      });
    }
    setProgressPending(next);
  }, [activeTasks]);

  const handleProgressToggle = (id: string, field: "reception" | "processing" | "storage") => {
    setProgressPending((prev) => {
      const next = new Map(prev);
      const cur = next.get(id) ?? { reception: "", processing: "", storage: "" };
      next.set(id, { ...cur, [field]: cur[field] ? "" : new Date().toISOString() });
      return next;
    });
  };

  const saveMemoMut = useMutation({
    mutationFn: (text: string) => memosApi.save("short", text),
    onSuccess: () => {
      toast.success("메모 저장됨");
      qc.invalidateQueries({ queryKey: ["memo", "short"] });
    },
    onError: () => toast.error("메모 저장 실패"),
  });

  const updateTaskMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<ActiveTask> }) =>
      tasksApi.updateActive(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", "active"] }),
  });

  const updatePlannedMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<PlannedTask> }) =>
      tasksApi.updatePlanned(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", "planned"] }),
  });

  const completeTasksMut = useMutation({
    mutationFn: (ids: string[]) => tasksApi.completeTasks(ids),
    onSuccess: (_, ids) => {
      toast.success(`${ids.length}건 완료 처리됨`);
      setCompletedIds(new Set());
      setDeleteIds(new Set());
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const batchProgressMut = useMutation({
    mutationFn: (updates: { id: string; reception: string; processing: string; storage: string }[]) =>
      tasksApi.batchProgress(updates),
    onSuccess: (_, updates) => {
      toast.success(`${updates.length}건 진행상태 저장됨`);
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
    onError: () => toast.error("진행상태 저장 실패"),
  });

  const deleteTasksMut = useMutation({
    mutationFn: (ids: string[]) => tasksApi.deleteActive(ids),
    onSuccess: (_, ids) => {
      toast.success(`${ids.length}건 삭제됨`);
      setDeleteIds(new Set());
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
  });

  const saveEventMut = useMutation({
    mutationFn: ({ date, text }: { date: string; text: string }) => {
      const eventsMap = events as Record<string, string[]>;
      const allEvents: { date_str: string; event_text: string }[] = [];
      // 다른 날짜 이벤트는 그대로 유지
      Object.entries(eventsMap).forEach(([d, txts]) => {
        if (d !== date) txts.forEach((t) => allEvents.push({ date_str: d, event_text: t }));
      });
      // 선택한 날짜는 새 내용으로 교체 (append 아님)
      const newLines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      newLines.forEach((t) => allEvents.push({ date_str: date, event_text: t }));
      return eventsApi.save(allEvents);
    },
    onSuccess: () => {
      toast.success("일정 저장됨");
      qc.invalidateQueries({ queryKey: ["events"] });
      setShowCalModal(false);
      setCalendarMemo("");
    },
  });

  const handleActiveTaskSave = (id: string, data: Partial<ActiveTask>) => {
    updateTaskMut.mutate({ id, data });
  };

  const handlePlannedUpdate = (id: string, data: Partial<PlannedTask>) => {
    updatePlannedMut.mutate({ id, data });
  };

  // ── 예정업무 추가 ──
  const [newPlannedPeriod, setNewPlannedPeriod] = useState("단기🔴");
  const [newPlannedDate, setNewPlannedDate] = useState("");
  const [newPlannedContent, setNewPlannedContent] = useState("");
  const [newPlannedNote, setNewPlannedNote] = useState("");

  const addPlannedMut = useMutation({
    mutationFn: (task: Partial<PlannedTask>) => tasksApi.addPlanned(task),
    onSuccess: () => {
      toast.success("예정업무 추가됨");
      setNewPlannedPeriod("단기🔴");
      setNewPlannedDate("");
      setNewPlannedContent("");
      setNewPlannedNote("");
      qc.invalidateQueries({ queryKey: ["tasks", "planned"] });
    },
    onError: () => toast.error("예정업무 추가 실패"),
  });

  const handleAddPlanned = () => {
    if (!newPlannedContent.trim()) { toast.error("내용을 입력하세요."); return; }
    addPlannedMut.mutate({ period: newPlannedPeriod, date: newPlannedDate, content: newPlannedContent, note: newPlannedNote });
  };

  const handleBatchSave = () => {
    const completeArr = Array.from(completedIds);
    const deleteArr = Array.from(deleteIds).filter((id) => !completedIds.has(id));

    // Collect rows whose progress fields differ from the original server data
    const progressArr: Array<{ id: string; data: { reception: string; processing: string; storage: string } }> = [];
    for (const t of activeTasks as ActiveTask[]) {
      const pending = progressPending.get(t.id);
      if (!pending) continue;
      const changed =
        pending.reception !== ((t.reception as string) || "") ||
        pending.processing !== ((t.processing as string) || "") ||
        pending.storage !== ((t.storage as string) || "");
      if (changed) progressArr.push({ id: t.id, data: pending });
    }

    if (!completeArr.length && !deleteArr.length && !progressArr.length) {
      toast.info("선택된 항목이 없습니다.");
      return;
    }
    if (completeArr.length && !confirm(`${completeArr.length}건을 완료 처리하시겠습니까?`)) return;
    if (deleteArr.length && !confirm(`${deleteArr.length}건을 삭제하시겠습니까?`)) return;

    if (completeArr.length) completeTasksMut.mutate(completeArr);
    if (deleteArr.length) deleteTasksMut.mutate(deleteArr);
    // Single batch call — 1 read + 1 write regardless of how many rows changed
    if (progressArr.length) {
      batchProgressMut.mutate(progressArr.map(({ id, data }) => ({ id, ...data })));
    }
  };

  const calEvents = useMemo(
    () =>
      Object.entries(events as Record<string, string[]>).flatMap(([date, texts]) =>
        texts.map((text, i) => ({ id: `${date}-${i}`, title: text, date }))
      ),
    [events]
  );

  const handleCalEventClick = useCallback(
    (info: { event: { startStr: string } }) => {
      const dateStr = info.event.startStr;
      const existing = (events as Record<string, string[]>)[dateStr] || [];
      setCalendarDate(dateStr);
      setCalendarMemo(existing.join("\n"));
      setCalModalIsEdit(existing.length > 0);
      setShowCalModal(true);
    },
    [events]
  );

  const handleCalDateClick = useCallback(
    (info: { dateStr: string }) => {
      const existing = (events as Record<string, string[]>)[info.dateStr] || [];
      setCalendarDate(info.dateStr);
      setCalendarMemo(existing.join("\n"));
      setCalModalIsEdit(existing.length > 0);
      setShowCalModal(true);
    },
    [events]
  );

  const handleEventDidMount = useCallback((arg: { el: HTMLElement }) => {
    arg.el.style.cursor = "pointer";
  }, []);

  // Returns class names only (no JSX) — avoids ContentInjector custom-rendering loop
  const handleDayCellClassNames = useCallback((info: { date: Date }) => {
    const d = info.date;
    const dateStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const dow = d.getDay();
    if (KR_HOLIDAYS.has(dateStr)) return ["cal-kr-holiday"];
    if (CN_HOLIDAYS.has(dateStr)) return ["cal-cn-holiday"];
    if (dow === 0) return ["cal-sun"];
    if (dow === 6) return ["cal-sat"];
    return [];
  }, []);

  const periodOrder: Record<string, number> = { "장기🟢": 0, "중기🟡": 1, "단기🔴": 2, "완료✅": 3, "보류⏹️": 4 };
  const sortedPlanned = [...(plannedTasks as PlannedTask[])].sort((a, b) => {
    const pa = periodOrder[a.period] ?? 99, pb = periodOrder[b.period] ?? 99;
    if (pa !== pb) return pa - pb;
    return (a.date || "").localeCompare(b.date || "");
  });

  const alertCount =
    (expiryData?.card_alerts?.length ?? 0) +
    (expiryData?.passport_alerts?.length ?? 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* 페이지 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 className="hw-page-title">홈 대시보드</h1>
        {alertCount > 0 && (
          <span
            style={{
              fontSize: 12, padding: "4px 10px", borderRadius: 99, fontWeight: 500, cursor: "pointer",
              background: "#FFF5F5", color: "#C53030", border: "1px solid #FEB2B2",
            }}
            onClick={() => router.push("/dashboard")}
          >
            ⚠️ 만기 알림 {alertCount}건
          </span>
        )}
      </div>

      {/* 빠른 액션 */}
      <QuickActions />

      {/* ── 상단 2단 레이아웃 (원본 Streamlit st.columns(2) = 1:1) ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>

        {/* 왼쪽: 캘린더 + 단기메모 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* 일정 달력 — 높이 증가 */}
          <div className="hw-card">
            {/* 제목 + 범례 */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <div className="hw-card-title" style={{ marginBottom: 0 }}>📅 일정 달력</div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", fontSize: 11, fontWeight: 600 }}>
                <span style={{ color: "#2563EB" }}>● 중국공휴일</span>
                <span style={{ color: "#DC2626" }}>● 한국공휴일</span>
              </div>
            </div>
            <FullCalendar
              plugins={CAL_PLUGINS}
              initialView="dayGridMonth"
              locale="ko"
              aspectRatio={1.4}
              expandRows={true}
              events={calEvents}
              dayMaxEvents={2}
              eventClick={handleCalEventClick}
              eventDidMount={handleEventDidMount}
              headerToolbar={CAL_HEADER_TOOLBAR}
              dateClick={handleCalDateClick}
              eventColor="var(--hw-gold)"
              dayCellClassNames={handleDayCellClassNames}
            />
          </div>

          {/* 단기메모 — 높이 증가 */}
          <div className="hw-card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="hw-card-title">📝 단기메모</div>
            <textarea
              className="hw-input"
              style={{ width: "100%", height: 120, resize: "vertical", fontSize: 13, lineHeight: 1.7, boxSizing: "border-box" }}
              value={memoText}
              onChange={(e) => setMemoText(e.target.value)}
              placeholder="단기 업무 메모 (대시보드 전용)..."
            />
            <button
              onClick={() => saveMemoMut.mutate(memoText)}
              disabled={saveMemoMut.isPending}
              className="btn-primary"
              style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, alignSelf: "flex-start" }}
            >
              <Save size={12} /> 저장
            </button>
          </div>
        </div>

        {/* 오른쪽: 만기 알림 (스크롤 제한) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          {/* 등록증 만기 4개월 */}
          <div className="hw-card">
            <div className="hw-card-title">🪪 등록증 만기 4개월 전</div>
            <ExpiryTable rows={expiryData?.card_alerts ?? []} dateField="등록증만기일" />
          </div>

          {/* 여권 만기 6개월 */}
          <div className="hw-card">
            <div className="hw-card-title">🛂 여권 만기 6개월 전</div>
            <ExpiryTable rows={expiryData?.passport_alerts ?? []} dateField="여권만기일" />
          </div>
        </div>
      </div>

      {/* ── 예정업무 (인라인 편집 + 추가) ── */}
      <div className="hw-card">
        <div className="hw-card-title">📌 예정업무</div>
        <div style={{ overflowX: "auto" }}>
          <table className="hw-table">
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>기간</th>
                <th style={{ textAlign: "left" }}>날짜</th>
                <th style={{ textAlign: "left" }}>내용</th>
                <th style={{ textAlign: "left" }}>비고</th>
                <th style={{ width: 48 }}></th>
              </tr>
            </thead>
            <tbody>
              {sortedPlanned.map((t) => (
                <PlannedTaskRow key={t.id} task={t} onUpdate={handlePlannedUpdate} />
              ))}
              {/* 새 예정업무 추가 행 */}
              <tr style={{ background: "#F7FAFC" }}>
                <td style={{ whiteSpace: "nowrap" }}>
                  <select
                    style={{ background: "transparent", fontSize: 12, border: "none", outline: "none", cursor: "pointer", fontWeight: 600 }}
                    value={newPlannedPeriod}
                    onChange={(e) => setNewPlannedPeriod(e.target.value)}
                  >
                    {["장기🟢","중기🟡","단기🔴","완료✅","보류⏹️"].map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <input className="hw-table-input" value={newPlannedDate} placeholder="날짜"
                    onChange={(e) => setNewPlannedDate(e.target.value)} />
                </td>
                <td>
                  <input className="hw-table-input" style={{ minWidth: 160 }} value={newPlannedContent} placeholder="내용 입력..."
                    onChange={(e) => setNewPlannedContent(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleAddPlanned(); }} />
                </td>
                <td>
                  <input className="hw-table-input" style={{ minWidth: 100 }} value={newPlannedNote} placeholder="비고"
                    onChange={(e) => setNewPlannedNote(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") handleAddPlanned(); }} />
                </td>
                <td style={{ width: 52 }}>
                  <button
                    onClick={handleAddPlanned}
                    disabled={addPlannedMut.isPending}
                    style={{
                      padding: "3px 8px", fontSize: 10, fontWeight: 700,
                      background: "#3182CE", color: "#fff",
                      border: "none", borderRadius: 4, cursor: "pointer",
                      opacity: addPlannedMut.isPending ? 0.5 : 1,
                    }}
                  >
                    추가
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        {sortedPlanned.length === 0 && (
          <p style={{ fontSize: 12, color: "#A0AEC0", marginTop: 4 }}>예정된 업무가 없습니다. 위에서 추가하세요.</p>
        )}
      </div>

      {/* ── 진행업무 ── */}
      <div className="hw-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <div className="hw-card-title" style={{ marginBottom: 0 }}>⚡ 진행업무</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 11, color: "#A0AEC0" }}>완료/삭제 체크 후 →</span>
            <button
              onClick={handleBatchSave}
              disabled={completeTasksMut.isPending || deleteTasksMut.isPending}
              className="btn-primary"
              style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, opacity: (completeTasksMut.isPending || deleteTasksMut.isPending) ? 0.5 : 1 }}
            >
              <CheckCircle size={12} /> 선택 처리
            </button>
          </div>
        </div>

        {activeTasks.length === 0 ? (
          <p style={{ fontSize: 12, color: "#A0AEC0" }}>
            진행 중인 업무가 없습니다. 업무관리 메뉴에서 추가하세요.
          </p>
        ) : (
          <>
            <div style={{ overflowX: "auto" }}>
              <table className="hw-table" style={{ minWidth: 960 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>분류</th>
                    <th style={{ textAlign: "left" }}>날짜</th>
                    <th style={{ textAlign: "left" }}>이름</th>
                    <th style={{ textAlign: "left" }}>업무</th>
                    <th style={{ textAlign: "left" }}>세부내용</th>
                    <th style={{ textAlign: "right", width: 56 }}>이체</th>
                    <th style={{ textAlign: "right", width: 56 }}>현금</th>
                    <th style={{ textAlign: "right", width: 56 }}>카드</th>
                    <th style={{ textAlign: "right", width: 56 }}>인지</th>
                    <th style={{ textAlign: "right", width: 56 }}>미수</th>
                    <th style={{ width: 36 }}></th>
                    <th style={{ width: 150 }}>접수/처리/보관중</th>
                    <th style={{ textAlign: "center", width: 44 }}>완료✅</th>
                    <th style={{ textAlign: "center", width: 44 }}>삭제❌</th>
                  </tr>
                </thead>
                <tbody>
                  {(activeTasks as ActiveTask[]).map((task) => (
                    <ActiveTaskRow
                      key={task.id}
                      task={task}
                      onSave={handleActiveTaskSave}
                      onToggleComplete={(id) =>
                        setCompletedIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; })
                      }
                      onToggleDelete={(id) =>
                        setDeleteIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; })
                      }
                      markedComplete={completedIds.has(task.id)}
                      markedDelete={deleteIds.has(task.id)}
                      onProgressToggle={handleProgressToggle}
                      pendingReception={progressPending.get(task.id)?.reception ?? (task.reception as string) ?? ""}
                      pendingProcessing={progressPending.get(task.id)?.processing ?? (task.processing as string) ?? ""}
                      pendingStorage={progressPending.get(task.id)?.storage ?? (task.storage as string) ?? ""}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            {/* 합계 푸터 */}
            <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, borderTop: "1px solid #E2E8F0", paddingTop: 8, color: "#718096" }}>
              {(["transfer","cash","card","stamp","receivable"] as const).map((f) => {
                const total = (activeTasks as ActiveTask[]).reduce((s, t) => s + safeInt(t[f]), 0);
                return total > 0 ? (
                  <span key={f}>
                    {f === "transfer" ? "이체" : f === "cash" ? "현금" : f === "card" ? "카드" : f === "stamp" ? "인지" : "미수"}:{" "}
                    <strong style={{ color: "#2D3748" }}>{formatNumber(total)}</strong>
                  </span>
                ) : null;
              })}
            </div>
          </>
        )}
      </div>

      {/* ── 캘린더 모달 ── */}
      {showCalModal && (
        <div className="hw-modal-overlay" onClick={() => setShowCalModal(false)}>
          <div className="hw-modal" onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <h3 style={{ fontWeight: 600, fontSize: 14, color: "#2D3748" }}>
                📅 {calendarDate} 일정 {calModalIsEdit ? "수정" : "추가"}
              </h3>
              <button onClick={() => setShowCalModal(false)} style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0" }}>
                <X size={16} />
              </button>
            </div>
            <textarea
              className="hw-input"
              style={{ width: "100%", resize: "none", height: 96, fontSize: 13, boxSizing: "border-box" }}
              placeholder="일정 내용 입력... (한 줄 = 한 일정, 빈칸으로 저장하면 삭제)"
              value={calendarMemo}
              onChange={(e) => setCalendarMemo(e.target.value)}
              autoFocus
            />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
              <button
                onClick={() => setShowCalModal(false)}
                className="btn-secondary"
                style={{ fontSize: 13 }}
              >
                닫기
              </button>
              <button
                onClick={() => {
                  if (!calendarDate || !calendarMemo.trim()) return;
                  saveEventMut.mutate({ date: calendarDate, text: calendarMemo.trim() });
                }}
                disabled={!calendarMemo.trim() || saveEventMut.isPending}
                className="btn-primary"
                style={{ fontSize: 13, opacity: (!calendarMemo.trim() || saveEventMut.isPending) ? 0.5 : 1 }}
              >
                저장
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
