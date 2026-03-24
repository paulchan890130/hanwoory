"use client";
import { useState, useEffect } from "react";
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

// ── 진행업무 행 ─────────────────────────────────────────────────────────────────
function ActiveTaskRow({
  task, onUpdate, onToggleComplete, onToggleDelete, markedComplete, markedDelete,
}: {
  task: ActiveTask;
  onUpdate: (id: string, field: string, value: string | boolean) => void;
  onToggleComplete: (id: string) => void;
  onToggleDelete: (id: string) => void;
  markedComplete: boolean;
  markedDelete: boolean;
}) {
  const isProc = task.processed === true || String(task.processed).toLowerCase() === "true";
  const rowBg = markedDelete
    ? "rgba(229,62,62,0.06)"
    : markedComplete
    ? "rgba(72,187,120,0.08)"
    : undefined;

  return (
    <tr style={{ background: rowBg }}>
      <td>
        <input className="hw-table-input" defaultValue={task.category}
          onBlur={(e) => onUpdate(task.id, "category", e.target.value)} />
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <input className="hw-table-input" defaultValue={task.date}
          onBlur={(e) => onUpdate(task.id, "date", e.target.value)} />
      </td>
      <td>
        <input className="hw-table-input" defaultValue={task.name}
          onBlur={(e) => onUpdate(task.id, "name", e.target.value)} />
      </td>
      <td style={{ minWidth: 110 }}>
        {isProc
          ? <span style={{ color: "#3182CE", fontWeight: 500 }}>{task.work}</span>
          : <input className="hw-table-input" defaultValue={task.work}
              onBlur={(e) => onUpdate(task.id, "work", e.target.value)} />}
      </td>
      <td style={{ minWidth: 130 }}>
        {isProc
          ? <span style={{ color: "#3182CE" }}>{task.details}</span>
          : <input className="hw-table-input" defaultValue={task.details}
              onBlur={(e) => onUpdate(task.id, "details", e.target.value)} />}
      </td>
      {(["transfer","cash","card","stamp","receivable"] as const).map((f) => (
        <td key={f} style={{ textAlign: "right", width: 56 }}>
          <input type="text" inputMode="numeric"
            className="hw-table-input"
            style={{ textAlign: "right" }}
            defaultValue={safeInt(task[f]) || ""}
            placeholder={f === "transfer" ? "이체" : f === "cash" ? "현금" : f === "card" ? "카드" : f === "stamp" ? "인지" : "미수"}
            onBlur={(e) => onUpdate(task.id, f, e.target.value)} />
        </td>
      ))}
      {/* 처리중 체크박스 */}
      <td style={{ textAlign: "center", width: 48 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={isProc}
            onChange={() => onUpdate(task.id, "processed", !isProc)}
            style={{ accentColor: "#3182CE" }} />
          <span style={{ fontSize: 9, color: "#3182CE" }}>처리중</span>
        </label>
      </td>
      {/* 완료 체크박스 */}
      <td style={{ textAlign: "center", width: 48 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={markedComplete}
            onChange={() => onToggleComplete(task.id)}
            style={{ accentColor: "#38A169" }} />
          <span style={{ fontSize: 9, color: "#38A169" }}>완료✅</span>
        </label>
      </td>
      {/* 삭제 체크박스 */}
      <td style={{ textAlign: "center", width: 48 }}>
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

// ── 예정업무 행 (인라인 편집) ───────────────────────────────────────────────────
function PlannedTaskRow({
  task, onUpdate,
}: {
  task: PlannedTask;
  onUpdate: (id: string, data: Partial<PlannedTask>) => void;
}) {
  const periodColor =
    task.period === "단기🔴" ? "#C53030" :
    task.period === "중기🟡" ? "#975A16" :
    task.period === "장기🟢" ? "#276749" :
    task.period === "완료✅" ? "#A0AEC0" :
    "#4A5568";
  return (
    <tr style={{ opacity: task.period === "완료✅" ? 0.55 : 1 }}>
      <td style={{ whiteSpace: "nowrap" }}>
        <select
          style={{ background: "transparent", fontSize: 12, border: "none", outline: "none", cursor: "pointer", color: periodColor, fontWeight: 600 }}
          defaultValue={task.period}
          onBlur={(e) => onUpdate(task.id, { period: e.target.value })}
        >
          {["장기🟢","중기🟡","단기🔴","완료✅","보류⏹️"].map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </td>
      <td style={{ whiteSpace: "nowrap" }}>
        <input className="hw-table-input" defaultValue={task.date}
          onBlur={(e) => onUpdate(task.id, { date: e.target.value })} />
      </td>
      <td>
        <input className="hw-table-input" style={{ minWidth: 160 }} defaultValue={task.content}
          onBlur={(e) => onUpdate(task.id, { content: e.target.value })} />
      </td>
      <td>
        <input className="hw-table-input" style={{ minWidth: 100 }} defaultValue={task.note}
          onBlur={(e) => onUpdate(task.id, { note: e.target.value })} />
      </td>
    </tr>
  );
}

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
  const [calendarDate, setCalendarDate] = useState<string | null>(null);
  const [calendarMemo, setCalendarMemo] = useState("");
  const [showCalModal, setShowCalModal] = useState(false);
  const [calModalIsEdit, setCalModalIsEdit] = useState(false);

  useEffect(() => {
    if (shortMemo !== undefined) setMemoText(shortMemo as string);
  }, [shortMemo]);

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

  const handleFieldUpdate = (id: string, field: string, value: string | boolean) => {
    updateTaskMut.mutate({ id, data: { [field]: value } as Partial<ActiveTask> });
  };

  const handlePlannedUpdate = (id: string, data: Partial<PlannedTask>) => {
    updatePlannedMut.mutate({ id, data });
  };

  const handleBatchSave = () => {
    const completeArr = Array.from(completedIds);
    const deleteArr = Array.from(deleteIds).filter((id) => !completedIds.has(id));
    if (completeArr.length) completeTasksMut.mutate(completeArr);
    if (deleteArr.length) deleteTasksMut.mutate(deleteArr);
    if (!completeArr.length && !deleteArr.length) toast.info("선택된 항목이 없습니다.");
  };

  const calEvents = Object.entries(events as Record<string, string[]>).flatMap(([date, texts]) =>
    texts.map((text, i) => ({ id: `${date}-${i}`, title: text, date }))
  );

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
              plugins={[dayGridPlugin, interactionPlugin]}
              initialView="dayGridMonth"
              locale="ko"
              aspectRatio={1.4}
              expandRows={true}
              events={calEvents}
              // 한 날짜에 최소 두 줄 이상의 일정을 표시
              dayMaxEvents={2}
              // 일정 텍스트를 클릭해도 메모 창이 열리도록 추가
              eventClick={(info) => {
                const dateStr = info.event.startStr;
                const existing = (events as Record<string, string[]>)[dateStr] || [];
                setCalendarDate(dateStr);
                setCalendarMemo(existing.join("\n"));
                setCalModalIsEdit(existing.length > 0);
                setShowCalModal(true);
              }}
              // 클릭 가능한 부분에 마우스 커서를 손 모양으로 표시
              eventDidMount={(arg) => {
                arg.el.style.cursor = "pointer";
              }}
              headerToolbar={{ left: "prev", center: "title", right: "next" }}
              dateClick={(info) => {
                const existing = (events as Record<string, string[]>)[info.dateStr] || [];
                setCalendarDate(info.dateStr);
                setCalendarMemo(existing.join("\n"));
                setCalModalIsEdit(existing.length > 0);
                setShowCalModal(true);
              }}
              eventColor="var(--hw-gold)"
              dayHeaderContent={(info) => {
                const dow = info.dow; // 0=일, 6=토
                const color = dow === 0 ? "#DC2626" : dow === 6 ? "#2563EB" : "#4A5568";
                return <span style={{ color, fontWeight: 700, fontSize: 12 }}>{info.text}</span>;
              }}
              dayCellContent={(info) => {
                const d = info.date;
                const dateStr = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
                const dow = d.getDay();
                const isCN = CN_HOLIDAYS.has(dateStr);
                const isKR = KR_HOLIDAYS.has(dateStr);
                let color = "#2D3748";
                if (isKR) color = "#DC2626";
                else if (isCN) color = "#2563EB";
                else if (dow === 0) color = "#DC2626";
                else if (dow === 6) color = "#2563EB";
                const isBold = isCN || isKR || dow === 0 || dow === 6;
                return (
                  <span style={{ color, fontWeight: isBold ? 700 : 400 }}>
                    {info.dayNumberText}
                  </span>
                );
              }}
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

      {/* ── 예정업무 (인라인 편집) ── */}
      <div className="hw-card">
        <div className="hw-card-title">📌 예정업무</div>
        {sortedPlanned.length === 0 ? (
          <p style={{ fontSize: 12, color: "#A0AEC0" }}>예정된 업무가 없습니다.</p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="hw-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>기간</th>
                  <th style={{ textAlign: "left" }}>날짜</th>
                  <th style={{ textAlign: "left" }}>내용</th>
                  <th style={{ textAlign: "left" }}>비고</th>
                </tr>
              </thead>
              <tbody>
                {sortedPlanned.map((t) => (
                  <PlannedTaskRow key={t.id} task={t} onUpdate={handlePlannedUpdate} />
                ))}
              </tbody>
            </table>
          </div>
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
              <table className="hw-table" style={{ minWidth: 900 }}>
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
                    <th style={{ textAlign: "center", width: 48 }}>처리중</th>
                    <th style={{ textAlign: "center", width: 48 }}>완료✅</th>
                    <th style={{ textAlign: "center", width: 48 }}>삭제❌</th>
                  </tr>
                </thead>
                <tbody>
                  {(activeTasks as ActiveTask[]).map((task) => (
                    <ActiveTaskRow
                      key={task.id}
                      task={task}
                      onUpdate={handleFieldUpdate}
                      onToggleComplete={(id) =>
                        setCompletedIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; })
                      }
                      onToggleDelete={(id) =>
                        setDeleteIds((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; })
                      }
                      markedComplete={completedIds.has(task.id)}
                      markedDelete={deleteIds.has(task.id)}
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
