"use client";
import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  tasksApi, memosApi, eventsApi, customersApi, boardApi, dailyApi, manualApi,
  type ActiveTask, type PlannedTask, type ExpiryAlert, type BoardPost,
} from "@/lib/api";
import { getUser } from "@/lib/auth";
import { safeInt, formatNumber } from "@/lib/utils";
import TaskSummaryCards from "@/components/tasks/TaskSummaryCards";
import TaskCategoryFilter from "@/components/tasks/TaskCategoryFilter";
import TaskCardView, { type MoneyDraft } from "@/components/tasks/TaskCardView";
import TaskTableView from "@/components/tasks/TaskTableView";
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

function dPlusFromTs(ts: string): number {
  if (!ts) return 0;
  const start = new Date(ts.slice(0, 10));
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86_400_000));
}

// 두 타임스탬프 사이의 일수. endTs 없으면 오늘까지.
function daysBetween(startTs: string, endTs: string | null): number {
  if (!startTs) return 0;
  const start = new Date(startTs.slice(0, 10));
  const end = endTs ? new Date(endTs.slice(0, 10)) : (() => { const d = new Date(); d.setHours(0,0,0,0); return d; })();
  return Math.max(0, Math.floor((end.getTime() - start.getTime()) / 86_400_000));
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
      transfer: String(safeInt(transfer) || 0),
      cash: String(safeInt(cash) || 0),
      card: String(safeInt(card) || 0),
      stamp: String(safeInt(stamp) || 0),
      receivable: String(safeInt(receivable) || 0),
    });
    setDirty(false);
  };

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
      <td style={{ minWidth: 72 }}>
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
          style={{ textAlign: "right" }} value={transfer}
          onChange={(e) => { setTransfer(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={cash}
          onChange={(e) => { setCash(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={card}
          onChange={(e) => { setCard(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={stamp}
          onChange={(e) => { setStamp(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input"
          style={{ textAlign: "right" }} value={receivable}
          onChange={(e) => { setReceivable(e.target.value); mark(); }} />
      </td>
      {/* 필드 저장 버튼 — progress 체크박스와 완전히 분리된 전용 열 */}
      <td style={{ textAlign: "center", width: 36, verticalAlign: "middle" }}>
        {dirty && (
          <button
            onClick={handleSave}
            style={{
              padding: "2px 7px", fontSize: 9, fontWeight: 700,
              background: "#D4A843", color: "#fff",
              border: "none", borderRadius: 4, cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            저장
          </button>
        )}
      </td>
      {/* 접수 / 처리 / 보관중 — 1줄 고정 */}
      <td style={{ minWidth: 120, verticalAlign: "middle", whiteSpace: "nowrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 5, flexWrap: "nowrap" }}>
          {/* 접수 */}
          <label style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
            <input type="checkbox" checked={!!pendingReception} onChange={() => toggleLocal("reception")}
              style={{ accentColor: "#3182CE", width: 11, height: 11, flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: pendingReception ? "#2B6CB0" : "#A0AEC0", fontWeight: pendingReception ? 700 : 400 }}>접</span>
            {pendingReception && (
              <span style={{ fontSize: 9, fontWeight: 700, color: pendingProcessing ? "#CBD5E0" : "#2B6CB0" }}>
                D+{daysBetween(pendingReception, pendingProcessing || null)}
              </span>
            )}
          </label>
          <span style={{ color: "#E2E8F0", fontSize: 10 }}>·</span>
          {/* 처 (처리) */}
          <label style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
            <input type="checkbox" checked={!!pendingProcessing} onChange={() => toggleLocal("processing")}
              style={{ accentColor: "#D4A843", width: 11, height: 11, flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: pendingProcessing ? "#96751E" : "#A0AEC0", fontWeight: pendingProcessing ? 700 : 400 }}>처</span>
            {pendingProcessing && (
              <span style={{ fontSize: 9, fontWeight: 700, color: pendingStorage ? "#CBD5E0" : "#96751E" }}>
                D+{daysBetween(pendingProcessing, pendingStorage || null)}
              </span>
            )}
          </label>
          <span style={{ color: "#E2E8F0", fontSize: 10 }}>·</span>
          {/* 보 (보관중) */}
          <label style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
            <input type="checkbox" checked={!!pendingStorage} onChange={() => toggleLocal("storage")}
              style={{ accentColor: "#9F7AEA", width: 11, height: 11, flexShrink: 0 }} />
            <span style={{ fontSize: 10, color: pendingStorage ? "#553C9A" : "#A0AEC0", fontWeight: pendingStorage ? 700 : 400 }}>보</span>
            {pendingStorage && (
              <span style={{ fontSize: 9, fontWeight: 700, color: "#553C9A" }}>
                D+{dPlusFromTs(pendingStorage)}
              </span>
            )}
          </label>
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
    period === "중기🟡" ? "#96751E" :
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
            background: dirty ? "#D4A843" : "#E2E8F0",
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
    staleTime: 2_000,
  });
  // 일일결산 카드지출 누계 (오늘/이번 달) — 진행업무 영역 표시용. 단일 API(중복계산 방지).
  const { data: cardExpense } = useQuery({
    queryKey: ["daily", "card-expense-summary"],
    queryFn: () => dailyApi.getCardExpenseSummary().then((r) => r.data),
    staleTime: 30_000,
  });
  // 일일결산 수입 합계 (오늘/이번 달) — 카드수입 포함(income_cash+income_etc 기준). active_task 무관.
  const { data: incomeSummary } = useQuery({
    queryKey: ["daily", "income-summary"],
    queryFn: () => dailyApi.getIncomeSummary().then((r) => r.data),
    staleTime: 30_000,
  });
  const { data: plannedTasks = [] } = useQuery({
    queryKey: ["tasks", "planned"],
    queryFn: () => tasksApi.getPlanned().then((r) => r.data),
    staleTime: 2_000,
  });
  const { data: shortMemo } = useQuery({
    queryKey: ["memo", "short"],
    queryFn: () => memosApi.get("short").then((r) => r.data.content || ""),
    staleTime: 30_000,
  });
  // 일정(events) 캐시는 tenant-scoped 키 사용 + staleTime 0.
  // 백엔드는 tenant 단위로 자동 격리되지만, 멀티-테넌트 SaaS 의 일반 원칙
  // (캐시 키에 tenant_id 포함) 을 따른다. 다른 테넌트로 로그인 전환 시 캐시
  // 충돌 방지.
  const tenantId = user?.tenant_id ?? "_anon_";
  const eventsKey = ["events", tenantId] as const;
  const { data: events = {} } = useQuery({
    queryKey: eventsKey,
    queryFn: () => eventsApi.get().then((r) => r.data),
    staleTime: 0,  // 캐시 없음 — 달력 내용은 항상 최신값 사용
  });
  const { data: expiryData } = useQuery({
    queryKey: ["expiry-alerts"],
    queryFn: () => customersApi.expiryAlerts().then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  // ── 공지 팝업 (신규 업데이트 시에만 표시) ──────────────────────────────────
  const [popupNotices, setPopupNotices] = useState<BoardPost[]>([]);
  const [showPopup, setShowPopup] = useState(false);
  const [popupDetail, setPopupDetail] = useState<BoardPost | null>(null);
  // 서버에서 받은 maxUpdated 값을 저장 — 닫기 시 이 값을 localStorage에 저장
  // (서버는 KST naive ISO, 클라이언트는 UTC+Z → 문자열 비교 시 항상 서버 > 클라이언트가 돼
  //  매번 팝업이 뜨는 버그 방지)
  const noticeMaxUpdatedRef = useRef("");
  // 계정별 localStorage 키 — 브라우저를 공유해도 계정마다 독립적으로 seen 상태 관리
  const noticeSeenKey = `notice_popup_seen_at_${user?.login_id ?? ""}`;

  useEffect(() => {
    boardApi.getPopup().then((res) => {
      const items = res.data as BoardPost[];
      if (items.length === 0) return;
      const seenAt = localStorage.getItem(noticeSeenKey) ?? "";
      const maxUpdated = items.reduce((mx, p) => {
        const u = (p.updated_at ?? p.created_at ?? "");
        return u > mx ? u : mx;
      }, "");
      noticeMaxUpdatedRef.current = maxUpdated;
      if (seenAt && maxUpdated <= seenAt) return;
      setPopupNotices(items);
      setShowPopup(true);
    }).catch(() => {/* 무시 */});
  }, []);

  const closePopup = () => {
    // 클라이언트 시간(UTC)이 아닌 서버 timestamp 문자열을 저장해야 다음 비교가 정확함
    localStorage.setItem(noticeSeenKey, noticeMaxUpdatedRef.current || new Date().toISOString());
    setShowPopup(false);
    setPopupDetail(null);
  };

  // ── 매뉴얼 업데이트 알림 (로그인 최초 1회, 새 버전마다 다시 1회) ───────────────
  // 조회 key 와 저장 key 를 동일하게(manual_update_seen_{login_id}) 사용하고,
  // marker 값은 version|detected_at → 같은 업데이트면 재표시 안 함, 새 run 이면 1회 표시.
  // 한계: localStorage 기반(기기/브라우저별) — DB read-marker 는 정식 개선안으로 유보.
  useEffect(() => {
    manualApi.latest().then((res) => {
      const v = res.data?.version;
      if (!v) return; // 탐지된 업데이트 없음 / PG 미구성 → 무알림
      const key = `manual_update_seen_${user?.login_id ?? ""}`;
      const marker = `${v}|${res.data?.detected_at ?? ""}`;
      if (localStorage.getItem(key) === marker) return; // 이미 확인한 업데이트
      toast(`실무지침 매뉴얼이 업데이트되었습니다 (버전 ${v}).`, { duration: 6000 });
      localStorage.setItem(key, marker);
    }).catch(() => {/* 무시 */});
  }, []);

  // ── 오늘 일정 팝업 (일 1회) ─────────────────────────────────────────────────
  const [showSchedulePopup, setShowSchedulePopup] = useState(false);
  const [todayScheduleLines, setTodayScheduleLines] = useState<string[]>([]);

  useEffect(() => {
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const seenDate = localStorage.getItem("today_schedule_seen") ?? "";
    if (seenDate === todayStr) return;
    const evMap = events as Record<string, string[]>;
    const lines = (evMap[todayStr] || []).filter(Boolean);
    if (lines.length === 0) return;
    setTodayScheduleLines(lines);
    setShowSchedulePopup(true);
  }, [events]);

  const closeSchedulePopup = () => {
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    localStorage.setItem("today_schedule_seen", todayStr);
    setShowSchedulePopup(false);
  };

  // ── 모바일 감지 ──────────────────────────────────────────────────────────────
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const [memoText, setMemoText] = useState("");
  const [dashViewMode, setDashViewMode] = useState<"table" | "card">("card");
  const [dashCategory, setDashCategory] = useState<string | "all">("all");
  const [completedIds, setCompletedIds] = useState<Set<string>>(new Set());
  const [deleteIds, setDeleteIds] = useState<Set<string>>(new Set());
  const [moneyDrafts, setMoneyDrafts]     = useState<Record<string, MoneyDraft>>({});
  const [moneyDirtyIds, setMoneyDirtyIds] = useState<Set<string>>(new Set());
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

  const batchMoneyMut = useMutation({
    mutationFn: (updates: Array<{ id: string; changes: Partial<Record<"transfer"|"cash"|"card"|"stamp"|"receivable"|"planned_expense", string>> }>) =>
      tasksApi.batchMoney(updates),
    onSuccess: (_, updates) => {
      const savedIds = new Set(updates.map(u => u.id));
      setMoneyDrafts(prev => {
        const next = { ...prev };
        savedIds.forEach(id => { delete next[id]; });
        return next;
      });
      setMoneyDirtyIds(prev => {
        const n = new Set(prev);
        savedIds.forEach(id => n.delete(id));
        return n;
      });
      toast.success(`${savedIds.size}건 금액 저장됨`);
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
    onError: () => toast.error("금액 저장 실패 — 수정 내용이 보존됩니다."),
  });

  const handleMoneyDraftChange = (id: string, field: keyof MoneyDraft, value: number) => {
    setMoneyDrafts(prev => ({ ...prev, [id]: { ...(prev[id] ?? {}), [field]: value } }));
    setMoneyDirtyIds(prev => { const n = new Set(prev); n.add(id); return n; });
  };

  const deleteTasksMut = useMutation({
    mutationFn: (ids: string[]) => tasksApi.deleteActive(ids),
    onSuccess: (_, ids) => {
      toast.success(`${ids.length}건 삭제됨`);
      setDeleteIds(new Set());
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
  });

  // saveEventMut — Add / Edit / Delete a date's events.
  //
  // * `onMutate` 가 캐시를 **즉시** 패치 (낙관적 업데이트) → 모달 닫히는 순간
  //   캘린더 + 오늘 일정 영역이 바로 새 내용으로 보인다. 네트워크 왕복을
  //   기다리지 않는다.
  // * `onError` 에서 이전 스냅샷으로 롤백.
  // * `onSettled` 가 ``["events", tenantId]`` 를 invalidate → 서버 응답으로
  //   배경 refetch → 최종 일관성 보장.
  // * 다른 날짜의 키는 절대 건드리지 않는다 — 객체 spread 후 해당 date 한
  //   개만 수정/삭제.
  const saveEventMut = useMutation({
    mutationFn: ({ date, text }: { date: string; text: string }) => {
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      // 빈칸 저장 = 해당 날짜 삭제 (다른 날짜 절대 건드리지 않음)
      if (lines.length === 0) {
        return eventsApi.delete(date);
      }
      return eventsApi.save(date, lines);
    },
    onMutate: async ({ date, text }: { date: string; text: string }) => {
      await qc.cancelQueries({ queryKey: eventsKey });
      const previous = qc.getQueryData<Record<string, string[]>>(eventsKey);
      const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
      qc.setQueryData<Record<string, string[]>>(eventsKey, (prev) => {
        const next: Record<string, string[]> = { ...(prev || {}) };
        if (lines.length === 0) delete next[date];
        else next[date] = lines;
        return next;
      });
      return { previous };
    },
    onError: (_err, { text }, context) => {
      // Roll back to the pre-mutation snapshot so the UI never shows a
      // mid-flight phantom state.
      if (context?.previous) {
        qc.setQueryData(eventsKey, context.previous);
      }
      const isEmpty = !text.split("\n").map((l) => l.trim()).filter(Boolean).length;
      toast.error(isEmpty ? "일정 삭제 실패 — 다시 시도해주세요" : "일정 저장 실패 — 다시 시도해주세요");
    },
    onSuccess: (_, { text }) => {
      const isEmpty = !text.split("\n").map((l) => l.trim()).filter(Boolean).length;
      toast.success(isEmpty ? "일정이 삭제되었습니다." : "일정이 저장되었습니다.");
      setShowCalModal(false);
      setCalendarMemo("");
    },
    onSettled: () => {
      // Force a server refetch as belt-and-suspenders — confirms optimistic
      // patch matches the server's truth (handles concurrent edits from
      // other tabs / sessions).
      qc.invalidateQueries({ queryKey: eventsKey });
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

    // Collect money drafts for dirty ids only
    const moneyUpdates: Array<{ id: string; changes: Partial<Record<"transfer"|"cash"|"card"|"stamp"|"receivable"|"planned_expense", string>> }> = [];
    Array.from(moneyDirtyIds).forEach(id => {
      const draft = moneyDrafts[id];
      if (!draft) return;
      const changes: Partial<Record<"transfer"|"cash"|"card"|"stamp"|"receivable"|"planned_expense", string>> = {};
      (Object.entries(draft) as Array<[keyof MoneyDraft, number | undefined]>).forEach(([field, val]) => {
        if (val !== undefined) changes[field] = String(val);
      });
      if (Object.keys(changes).length > 0) moneyUpdates.push({ id, changes });
    });

    if (!completeArr.length && !deleteArr.length && !progressArr.length && !moneyUpdates.length) {
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
    if (moneyUpdates.length) batchMoneyMut.mutate(moneyUpdates);
  };

  const calEvents = useMemo(
    () =>
      Object.entries(events as Record<string, string[]>).map(([date, texts]) => ({
        id: date,
        title: texts.filter(Boolean).join("\n"),
        date,
      })),
    [events]
  );

  // 기존 일정 로드는 항상 **최신 캐시**(qc.getQueryData)에서 읽는다 — FullCalendar 콜백이
  // 캡처한 events 클로저가 오래되어 '기존 내용 없음 → 신규처럼' 동작하는 문제 방지.
  const _openCalModalForDate = useCallback(
    (dateStr: string) => {
      const map =
        qc.getQueryData<Record<string, string[]>>(eventsKey) ||
        (events as Record<string, string[]>) ||
        {};
      const existing = map[dateStr] || [];
      setCalendarDate(dateStr);
      setCalendarMemo(existing.join("\n"));
      setCalModalIsEdit(existing.length > 0);
      setShowCalModal(true);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [qc, events]
  );

  // 이벤트 클릭: startStr(타임존/포맷 영향) 대신 calEvents 에서 부여한 id(=날짜 키)를 사용.
  const handleCalEventClick = useCallback(
    (info: { event: { id?: string; startStr: string } }) => {
      _openCalModalForDate(info.event.id || info.event.startStr);
    },
    [_openCalModalForDate]
  );

  const handleCalDateClick = useCallback(
    (info: { dateStr: string }) => {
      _openCalModalForDate(info.dateStr);
    },
    [_openCalModalForDate]
  );

  const handleEventDidMount = useCallback((arg: { el: HTMLElement }) => {
    arg.el.style.cursor = "pointer";
  }, []);

  // 모바일: 날짜 칸이 한눈에 보이도록 내용 전체 대신 골드 dot + 건수 배지만 표시.
  //         (날짜 클릭 → 캘린더 모달에서 해당 날짜의 일정 목록/수정 표시)
  // 데스크톱: 기존처럼 내용 전체 표시.
  const renderEventContent = useCallback((arg: { event: { title: string } }) => {
    if (isMobile) {
      const count = (arg.event.title || "").split("\n").filter(Boolean).length;
      return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 3, width: "100%", padding: "0 2px", overflow: "hidden" }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--hw-gold)", flexShrink: 0 }} />
          {count > 1 && <span style={{ fontSize: 10, fontWeight: 700, color: "#B7791F", lineHeight: 1 }}>{count}</span>}
        </div>
      );
    }
    return (
      <div style={{ fontSize: 11, padding: "1px 4px", whiteSpace: "pre-line", lineHeight: 1.4, overflow: "hidden", width: "100%" }}>
        {arg.event.title}
      </div>
    );
  }, [isMobile]);

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

      {/* ── 공지 팝업 모달 ── */}
      {showPopup && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 9000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "#fff", borderRadius: 10, width: 480, maxWidth: "92vw", maxHeight: "80vh", display: "flex", flexDirection: "column", boxShadow: "0 8px 40px rgba(0,0,0,0.18)" }}>
            {/* 팝업 헤더 */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid #E2E8F0" }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#1A202C" }}>📢 공지사항</span>
              <button onClick={closePopup} style={{ background: "none", border: "none", fontSize: 18, color: "#A0AEC0", cursor: "pointer", lineHeight: 1 }}>✕</button>
            </div>
            {/* 팝업 본문 */}
            <div style={{ flex: 1, overflowY: "auto", padding: "12px 18px" }}>
              {!popupDetail ? (
                // 목록
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  {popupNotices.map((n) => (
                    <button
                      key={n.id}
                      onClick={() => setPopupDetail(n)}
                      style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 8px", background: "none", border: "none", borderBottom: "1px solid #F7FAFC", cursor: "pointer", textAlign: "left", width: "100%", borderRadius: 6 }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#F7FAFC")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
                    >
                      <span style={{ fontSize: 13, fontWeight: 600, color: "#2D3748", flex: 1 }}>{n.title}</span>
                      <span style={{ fontSize: 11, color: "#A0AEC0", whiteSpace: "nowrap" }}>{n.updated_at?.slice(0, 10)}</span>
                    </button>
                  ))}
                </div>
              ) : (
                // 상세
                <div>
                  <button onClick={() => setPopupDetail(null)} style={{ background: "none", border: "none", fontSize: 12, color: "#3182CE", cursor: "pointer", marginBottom: 10, padding: 0 }}>← 목록으로</button>
                  <div style={{ fontSize: 15, fontWeight: 700, color: "#1A202C", marginBottom: 8 }}>{popupDetail.title}</div>
                  <div style={{ fontSize: 12, color: "#A0AEC0", marginBottom: 14 }}>{popupDetail.updated_at?.slice(0, 10)}</div>
                  <div style={{ fontSize: 13, color: "#4A5568", whiteSpace: "pre-wrap", lineHeight: 1.8 }}>{popupDetail.content}</div>
                  {popupDetail.link_url && (
                    <div style={{ marginTop: 16 }}>
                      <a href={popupDetail.link_url} target="_blank" rel="noopener noreferrer"
                        style={{ fontSize: 13, color: "#3182CE", fontWeight: 600, textDecoration: "none" }}>
                        🔗 바로 가기
                      </a>
                    </div>
                  )}
                </div>
              )}
            </div>
            {/* 팝업 푸터 */}
            <div style={{ padding: "12px 18px", borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "flex-end" }}>
              <button onClick={closePopup} style={{ fontSize: 13, padding: "6px 18px", background: "#EDF2F7", border: "none", borderRadius: 6, cursor: "pointer", color: "#4A5568", fontWeight: 600 }}>
                이후로 보지 않기
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 오늘 일정 팝업 모달 ── */}
      {showSchedulePopup && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 9001, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div style={{ background: "#fff", borderRadius: 10, width: 420, maxWidth: "92vw", maxHeight: "70vh", display: "flex", flexDirection: "column", boxShadow: "0 8px 40px rgba(0,0,0,0.18)" }}>
            {/* 헤더 */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid #E2E8F0" }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#1A202C" }}>📅 오늘 일정</span>
              <button onClick={closeSchedulePopup} style={{ background: "none", border: "none", fontSize: 18, color: "#A0AEC0", cursor: "pointer", lineHeight: 1 }}>✕</button>
            </div>
            {/* 본문 */}
            <div style={{ flex: 1, overflowY: "auto", padding: "14px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
              {todayScheduleLines.map((line, i) => (
                <div key={i} style={{ fontSize: 13, color: "#2D3748", padding: "8px 12px", background: "#FFF9E6", border: "1px solid #FDE68A", borderRadius: 7, lineHeight: 1.6 }}>
                  {line}
                </div>
              ))}
            </div>
            {/* 푸터 */}
            <div style={{ padding: "12px 18px", borderTop: "1px solid #E2E8F0", display: "flex", justifyContent: "flex-end" }}>
              <button onClick={closeSchedulePopup} style={{ fontSize: 13, padding: "6px 18px", background: "#EDF2F7", border: "none", borderRadius: 6, cursor: "pointer", color: "#4A5568", fontWeight: 600 }}>
                오늘 하루 보지 않기
              </button>
            </div>
          </div>
        </div>
      )}

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

      {/* ── 상단 레이아웃: 모바일=1컬럼(cal→memo→ARC→passport), 데스크톱=2컬럼 ── */}
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20, alignItems: "start" }}>

        {/* 왼쪽: 캘린더 + 단기메모 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 0 }}>
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
              dayMaxEvents={false}
              eventContent={renderEventContent}
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
        <div style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 0 }}>
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
      {(() => {
        const allActive = activeTasks as ActiveTask[];
        const dashCats = Array.from(new Set(allActive.map(t => t.category).filter(Boolean)));
        const dashCatCounts: Record<string, number> = {};
        for (const t of allActive) { if (t.category) dashCatCounts[t.category] = (dashCatCounts[t.category] || 0) + 1; }
        const dashFiltered = dashCategory === "all" ? allActive : allActive.filter(t => t.category === dashCategory);
        const dashUrgent = dashFiltered.filter(t => {
          const p = progressPending.get(t.id);
          const ts = [p?.storage ?? (t.storage as string) ?? "", p?.processing ?? (t.processing as string) ?? "", p?.reception ?? (t.reception as string) ?? ""].filter(Boolean).sort().reverse()[0] ?? "";
          if (!ts) return false;
          const d = Math.max(0, Math.floor((new Date().setHours(0,0,0,0), (Date.now() - new Date(ts.slice(0,10)).getTime()) / 86400000)));
          return d >= 20;
        }).length;
        const isBatchPending = completeTasksMut.isPending || deleteTasksMut.isPending || batchProgressMut.isPending || batchMoneyMut.isPending;
        const dashCommonProps = {
          progressPending, completedIds, deleteIds,
          onProgressToggle: handleProgressToggle,
          onSave: handleActiveTaskSave,
          onToggleComplete: (id: string) => setCompletedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; }),
          onToggleDelete: (id: string) => setDeleteIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; }),
          moneyDrafts,
          moneyDirtyIds,
          onMoneyDraftChange: handleMoneyDraftChange,
        };
        return (
          <>
            {/* 헤더 — 모바일에서 액션바가 화면 밖으로 나가지 않도록 wrap 허용 */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", minWidth: 0 }}>
                <div className="hw-card-title" style={{ marginBottom: 0 }}>⚡ 진행업무</div>
                {incomeSummary && (incomeSummary.today > 0 || incomeSummary.month > 0) && (
                  <span style={{
                    fontSize: 11, fontWeight: 600, color: "#276749",
                    background: "#F0FFF4", border: "1px solid #9AE6B4",
                    borderRadius: 999, padding: "2px 10px", whiteSpace: "nowrap",
                  }}>
                    💰 수입 합계 오늘 {formatNumber(incomeSummary.today)}원 / 이번 달 {formatNumber(incomeSummary.month)}원
                  </span>
                )}
                {cardExpense && (cardExpense.today > 0 || cardExpense.month > 0) && (
                  <span style={{
                    fontSize: 11, fontWeight: 600, color: "#9C4221",
                    background: "#FFFAF0", border: "1px solid #FBD38D",
                    borderRadius: 999, padding: "2px 10px", whiteSpace: "nowrap",
                  }}>
                    💳 카드지출 오늘 {formatNumber(cardExpense.today)}원 / 이번 달 {formatNumber(cardExpense.month)}원
                  </span>
                )}
              </div>
              <div style={{
                display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
                // 모바일: 액션바를 한 줄 전체로 내려 버튼이 오른쪽 정렬되며 화면 안에 들어오게 한다.
                ...(isMobile ? { width: "100%", justifyContent: "flex-end" } : {}),
              }}>
                <span style={{ fontSize: 11, color: "#A0AEC0" }}>완료/삭제 체크 후 →</span>
                <button onClick={handleBatchSave} disabled={isBatchPending}
                  className="btn-primary"
                  style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, opacity: isBatchPending ? 0.5 : 1, flexShrink: 0 }}>
                  <CheckCircle size={12} /> {isBatchPending ? "처리 중..." : "선택 처리"}
                </button>
              </div>
            </div>

            {allActive.length === 0 ? (
              <p style={{ fontSize: 12, color: "#A0AEC0" }}>진행 중인 업무가 없습니다. 업무관리 메뉴에서 추가하세요.</p>
            ) : (
              <>
                {/* 요약 카드 */}
                <TaskSummaryCards
                  totalCount={dashFiltered.length}
                  urgentCount={dashUrgent}
                  transferTotal={dashFiltered.reduce((s, t) => s + safeInt(t.transfer), 0)}
                  cashTotal={dashFiltered.reduce((s, t) => s + safeInt(t.cash), 0)}
                  stampTotal={dashFiltered.reduce((s, t) => s + safeInt(t.stamp), 0)}
                  hasUnpaid={dashFiltered.some(t => safeInt(t.receivable) > 0)}
                />

                {/* 분류 필터 + 뷰 토글 */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "2px solid #E2E8F0", marginBottom: 0 }}>
                  <TaskCategoryFilter
                    categories={dashCats}
                    activeCategory={dashCategory}
                    onChange={setDashCategory}
                    counts={dashCatCounts}
                    totalCount={allActive.length}
                  />
                  {/* 모바일은 가로로 넓은 표 대신 세로로 쌓이는 카드만 사용 → 토글 숨김 */}
                  {!isMobile && (
                    <div style={{ display: "flex", gap: 0, borderRadius: 6, overflow: "hidden", border: "1px solid #E2E8F0", flexShrink: 0, marginLeft: 12 }}>
                      {(["card", "table"] as const).map(mode => (
                        <button key={mode} onClick={() => setDashViewMode(mode)} style={{
                          height: 26, padding: "0 10px", fontSize: 11, fontWeight: 600,
                          cursor: "pointer", border: "none",
                          background: dashViewMode === mode ? "#4A5568" : "#F7FAFC",
                          color: dashViewMode === mode ? "#fff" : "#718096",
                        }}>
                          {mode === "table" ? "☰" : "⊞"}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {dashFiltered.length === 0 ? (
                  <p style={{ fontSize: 12, color: "#A0AEC0", padding: "12px 0" }}>해당 분류의 업무가 없습니다.</p>
                ) : (isMobile || dashViewMode === "card") ? (
                  <TaskCardView tasks={dashFiltered} {...dashCommonProps} />
                ) : (
                  <TaskTableView tasks={dashFiltered} {...dashCommonProps} />
                )}

                {/* 합계 푸터 */}
                <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 16, fontSize: 12, borderTop: "1px solid #E2E8F0", paddingTop: 8, color: "#718096" }}>
                  {(["transfer","cash","card","stamp","receivable"] as const).map((f) => {
                    const total = dashFiltered.reduce((s, t) => s + safeInt(t[f]), 0);
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
          </>
        );
      })()}
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
                  if (!calendarDate) return;
                  // 빈칸이면 삭제, 내용이 있으면 저장 — 모두 정상적인 의도
                  saveEventMut.mutate({ date: calendarDate, text: calendarMemo });
                }}
                disabled={saveEventMut.isPending}
                className="btn-primary"
                style={{ fontSize: 13, opacity: saveEventMut.isPending ? 0.5 : 1 }}
              >
                {saveEventMut.isPending
                  ? "처리 중..."
                  : calendarMemo.trim()
                  ? "저장"
                  : "삭제"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
