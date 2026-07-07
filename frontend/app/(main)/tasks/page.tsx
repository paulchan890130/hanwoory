"use client";
import { useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { toast } from "sonner";
import { tasksApi, dailyApi, type ActiveTask, type PlannedTask, type CompletedTask } from "@/lib/api";
import TaskCardView from "@/components/tasks/TaskCardView";
import TaskTableView from "@/components/tasks/TaskTableView";
import TaskSummaryCards from "@/components/tasks/TaskSummaryCards";
import TaskCategoryFilter from "@/components/tasks/TaskCategoryFilter";
import { today, safeInt, formatNumber, normalizeDate } from "@/lib/utils";

// D+ 계산 (요약 카드용)
function _dPlusFromTs(ts: string): number {
  if (!ts) return 0;
  const start = new Date(ts.slice(0, 10));
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86_400_000));
}
import { Plus, Trash2, CheckCircle, AlertTriangle, Loader2 } from "lucide-react";
import { SubmitButton } from "@/components/SubmitButton";

const newId = () => crypto.randomUUID();

// ── 진행업무 행 (Dashboard와 동일한 controlled state + dirty/save 패턴) ──────────
function fmtDate(iso: string): string { return iso ? iso.slice(5, 10).replace("-", "/") : ""; }
function dPlusFromTs(ts: string): number {
  if (!ts) return 0;
  const start = new Date(ts.slice(0, 10));
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.max(0, Math.floor((now.getTime() - start.getTime()) / 86_400_000));
}

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
    setCategory(task.category   ?? "");
    setDate(task.date           ?? "");
    setName(task.name           ?? "");
    setWork(task.work           ?? "");
    setDetails(task.details     ?? "");
    setTransfer(String(safeInt(task.transfer)   || ""));
    setCash(String(safeInt(task.cash)           || ""));
    setCard(String(safeInt(task.card)           || ""));
    setStamp(String(safeInt(task.stamp)         || ""));
    setReceivable(String(safeInt(task.receivable) || ""));
    setDirty(false);
  }, [task.id, task.category, task.date, task.name, task.work, task.details,
      task.transfer, task.cash, task.card, task.stamp, task.receivable]);

  const mark = () => setDirty(true);

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

  const latestTs = [pendingStorage, pendingProcessing, pendingReception]
    .filter(Boolean).sort().reverse()[0] ?? "";
  const dp = dPlusFromTs(latestTs);
  const rowBg = markedDelete
    ? "rgba(229,62,62,0.06)"
    : markedComplete
    ? "rgba(72,187,120,0.08)"
    : undefined;

  const inp: React.CSSProperties = { width: "100%", padding: "3px 5px", fontSize: 12, border: "1px solid transparent", borderRadius: 4, background: "transparent", outline: "none", boxSizing: "border-box" };
  const inpFocus = "hover:border-gray-200 focus:border-blue-300 focus:bg-white";

  return (
    <tr style={{ background: rowBg }}>
      <td><input className={`hw-table-input ${inpFocus}`} style={inp} value={category}   onChange={(e) => { setCategory(e.target.value);   mark(); }} /></td>
      <td style={{ whiteSpace: "nowrap" }}><input className="hw-table-input" style={inp} value={date}      onChange={(e) => { setDate(e.target.value);       mark(); }} /></td>
      <td><input className="hw-table-input" style={inp} value={name}      onChange={(e) => { setName(e.target.value);       mark(); }} /></td>
      <td style={{ minWidth: 110 }}><input className="hw-table-input" style={inp} value={work}      onChange={(e) => { setWork(e.target.value);       mark(); }} /></td>
      <td style={{ minWidth: 130 }}><input className="hw-table-input" style={inp} value={details}   onChange={(e) => { setDetails(e.target.value);    mark(); }} /></td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={transfer} placeholder="이체" onChange={(e) => { setTransfer(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={cash} placeholder="현금" onChange={(e) => { setCash(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={card} placeholder="카드" onChange={(e) => { setCard(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={stamp} placeholder="인지" onChange={(e) => { setStamp(e.target.value); mark(); }} />
      </td>
      <td style={{ textAlign: "right", width: 56 }}>
        <input type="text" inputMode="numeric" className="hw-table-input" style={{ ...inp, textAlign: "right" }}
          value={receivable} placeholder="미수" onChange={(e) => { setReceivable(e.target.value); mark(); }} />
      </td>
      {/* 필드 저장 버튼 — progress와 분리된 전용 열 */}
      <td style={{ textAlign: "center", width: 36, verticalAlign: "middle" }}>
        {dirty && (
          <button onClick={handleSave}
            style={{ padding: "2px 7px", fontSize: 9, fontWeight: 700, background: "#D4A843", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer", whiteSpace: "nowrap" }}>
            저장
          </button>
        )}
      </td>
      {/* 접수 / 처리 / 보관중 — 선택 처리로만 저장 */}
      <td style={{ minWidth: 160, verticalAlign: "middle" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          {latestTs && <span style={{ fontSize: 10, fontWeight: 700, color: "#718096" }}>D+{dp}</span>}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "nowrap" }}>
            {([
              { field: "reception",  label: "접수",  color: "#3182CE", onColor: "#2B6CB0", ts: pendingReception },
              { field: "processing", label: "처리",  color: "#D4A843", onColor: "#96751E", ts: pendingProcessing },
              { field: "storage",    label: "보관중", color: "#9F7AEA", onColor: "#553C9A", ts: pendingStorage },
            ] as const).map(({ field, label, color, onColor, ts }) => (
              <label key={field} style={{ display: "flex", alignItems: "center", gap: 2, cursor: "pointer", userSelect: "none" }}>
                <input type="checkbox" checked={!!ts}
                  onChange={() => onProgressToggle(task.id, field)}
                  style={{ accentColor: color, width: 11, height: 11 }} />
                <span style={{ fontSize: 10, color: ts ? onColor : "#A0AEC0", fontWeight: ts ? 700 : 400 }}>{label}</span>
                {ts && <span style={{ fontSize: 9, color: "#A0AEC0" }}>{fmtDate(ts)}</span>}
              </label>
            ))}
          </div>
        </div>
      </td>
      <td style={{ textAlign: "center", width: 44 }}>
        <label style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 1, cursor: "pointer" }}>
          <input type="checkbox" checked={markedComplete} onChange={() => onToggleComplete(task.id)}
            style={{ accentColor: "#38A169" }} />
          <span style={{ fontSize: 9, color: "#38A169" }}>완료✅</span>
        </label>
      </td>
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

const TABS = ["진행업무", "예정업무", "완료업무"] as const;
type Tab = (typeof TABS)[number];

const PERIOD_OPTIONS = ["단기🔴", "중기🟡", "장기🟢", "완료✅", "보류⏹️"];

// ── 완료이동 확인 모달 ──────────────────────────────────────────────────────────
function CompleteConfirmModal({
  count,
  onConfirm,
  onCancel,
}: {
  count: number;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="hw-modal-overlay" onClick={onCancel}>
      <div className="hw-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 380 }}>
        <div className="flex items-start gap-3 mb-4">
          <div
            className="flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center"
            style={{ background: "#F0FFF4" }}
          >
            <AlertTriangle size={18} style={{ color: "#38A169" }} />
          </div>
          <div>
            <div className="font-semibold text-sm" style={{ color: "#2D3748" }}>
              완료 처리 확인
            </div>
            <div className="mt-1 text-xs" style={{ color: "#718096" }}>
              선택된 <strong style={{ color: "#2D3748" }}>{count}건</strong>의 업무를
              완료업무 탭으로 이동합니다.
              <br />이 작업은 되돌릴 수 없습니다.
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="btn-secondary text-xs">취소</button>
          <button
            onClick={onConfirm}
            className="btn-primary text-xs flex items-center gap-1.5"
          >
            <CheckCircle size={12} /> 완료 처리
          </button>
        </div>
      </div>
    </div>
  );
}

export default function TasksPage() {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [tab, setTab] = useState<Tab>("진행업무");
  const [completedIds, setCompletedIds] = useState<Set<string>>(new Set());
  const [deleteIds, setDeleteIds] = useState<Set<string>>(new Set());
  const [showCompleteModal, setShowCompleteModal] = useState(false);
  const [deletingPlannedId, setDeletingPlannedId] = useState<string | null>(null);
  const [deletingCompletedId, setDeletingCompletedId] = useState<string | null>(null);
  // 뷰 모드 토글 (카드형 / 테이블형)
  const [viewMode, setViewMode] = useState<"table" | "card">("table");
  // 분류 필터
  const [activeCategory, setActiveCategory] = useState<string | "all">("all");
  // 완료업무 필터/정렬
  const [completedSort, setCompletedSort] = useState<"newest" | "oldest">("newest");
  const [completedFilterName, setCompletedFilterName] = useState("");
  const [completedFilterCategory, setCompletedFilterCategory] = useState("");
  const [completedFilterWork, setCompletedFilterWork] = useState("");
  const [completedDateFrom, setCompletedDateFrom] = useState("");
  const [completedDateTo, setCompletedDateTo] = useState("");
  // 완료업무 서버 페이지네이션
  const COMPLETED_PAGE_SIZE = 20;
  const [completedPage, setCompletedPage] = useState(1);
  // 이름/업무 검색어는 타이핑마다 요청을 쏘지 않도록 350ms 디바운스
  const [debouncedName, setDebouncedName] = useState("");
  const [debouncedWork, setDebouncedWork] = useState("");
  useEffect(() => {
    const h = setTimeout(() => setDebouncedName(completedFilterName.trim()), 350);
    return () => clearTimeout(h);
  }, [completedFilterName]);
  useEffect(() => {
    const h = setTimeout(() => setDebouncedWork(completedFilterWork.trim()), 350);
    return () => clearTimeout(h);
  }, [completedFilterWork]);
  // 검색/필터/정렬이 바뀌면 항상 1페이지로 초기화
  useEffect(() => {
    setCompletedPage(1);
  }, [debouncedName, debouncedWork, completedFilterCategory, completedDateFrom, completedDateTo, completedSort]);

  type ProgressEntry = { reception: string; processing: string; storage: string };
  const [progressPending, setProgressPending] = useState<Map<string, ProgressEntry>>(new Map());

  // URL param: tab=active&action=new
  useEffect(() => {
    const t = searchParams.get("tab");
    if (t === "active") setTab("진행업무");
    else if (t === "planned") setTab("예정업무");
    else if (t === "completed") setTab("완료업무");

    if (searchParams.get("action") === "new" && (t === "active" || !t)) {
      // 새 업무 추가 후 URL 초기화
      setTimeout(() => {
        addActive.mutate({
          id: newId(), date: today(), category: "", name: "", work: "", details: "",
        });
        router.replace("/tasks");
      }, 100);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 데이터 ──
  const { data: active = [] } = useQuery({
    queryKey: ["tasks", "active"],
    queryFn: () => tasksApi.getActive().then((r) => r.data),
  });
  // 일일결산 카드지출 누계(오늘/이번 달) — 진행업무 상단 표시용. 단일 API(중복계산 방지).
  const { data: cardExpense } = useQuery({
    queryKey: ["daily", "card-expense-summary"],
    queryFn: () => dailyApi.getCardExpenseSummary().then((r) => r.data),
    staleTime: 30_000,
  });
  // 일일결산 수입 합계(오늘/이번 달) — 카드수입 포함(income 기준). active_task 무관.
  const { data: incomeSummary } = useQuery({
    queryKey: ["daily", "income-summary"],
    queryFn: () => dailyApi.getIncomeSummary().then((r) => r.data),
    staleTime: 30_000,
  });

  // Seed progressPending from server on every refetch
  useEffect(() => {
    setProgressPending(new Map(
      (active as ActiveTask[]).map((t) => [
        t.id,
        {
          reception: (t.reception as string) || "",
          processing: (t.processing as string) || "",
          storage: (t.storage as string) || "",
        },
      ])
    ));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const { data: planned = [] } = useQuery({
    queryKey: ["tasks", "planned"],
    queryFn: () => tasksApi.getPlanned().then((r) => r.data),
  });
  const { data: completedResp, isFetching: completedFetching } = useQuery({
    queryKey: [
      "tasks", "completed",
      completedPage, debouncedName, debouncedWork,
      completedFilterCategory, completedDateFrom, completedDateTo, completedSort,
    ],
    queryFn: () =>
      tasksApi.getCompleted({
        page: completedPage,
        page_size: COMPLETED_PAGE_SIZE,
        name: debouncedName,
        work: debouncedWork,
        category: completedFilterCategory,
        date_from: completedDateFrom,
        date_to: completedDateTo,
        sort: completedSort,
      }).then((r) => r.data),
    placeholderData: keepPreviousData, // 페이지 이동 시 이전 목록 유지(깜빡임 방지)
  });

  // ── Mutations ──
  const updateActive = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<ActiveTask> }) =>
      tasksApi.updateActive(id, data),
    onSuccess: () => { toast.success("저장됨"); qc.invalidateQueries({ queryKey: ["tasks", "active"] }); },
    onError: () => toast.error("저장 실패"),
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
  const addActive = useMutation({
    mutationFn: (task: Partial<ActiveTask>) => tasksApi.addActive(task),
    onSuccess: () => {
      toast.success("업무 추가됨");
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
  });
  const completeMany = useMutation({
    mutationFn: (ids: string[]) => tasksApi.completeTasks(ids),
    onSuccess: (_, ids) => {
      toast.success(`${ids.length}건 완료 처리됨`);
      setCompletedIds(new Set());
      setDeleteIds(new Set());
      qc.invalidateQueries({ queryKey: ["tasks"] });
      setShowCompleteModal(false);
    },
  });
  const deleteActiveMut = useMutation({
    mutationFn: (ids: string[]) => tasksApi.deleteActive(ids),
    onSuccess: (_, ids) => {
      toast.success(`${ids.length}건 삭제됨`);
      setDeleteIds(new Set());
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
  });
  const addPlanned = useMutation({
    mutationFn: (t: Partial<PlannedTask>) => tasksApi.addPlanned(t),
    onSuccess: () => {
      toast.success("예정 업무 추가됨");
      qc.invalidateQueries({ queryKey: ["tasks", "planned"] });
    },
  });
  const updatePlanned = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<PlannedTask> }) =>
      tasksApi.updatePlanned(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", "planned"] }),
  });
  const deletePlanned = useMutation({
    mutationFn: (ids: string[]) => tasksApi.deletePlanned(ids),
    onMutate: (ids: string[]) => setDeletingPlannedId(ids[0] ?? null),
    onSuccess: () => { toast.success("삭제됨"); qc.invalidateQueries({ queryKey: ["tasks", "planned"] }); },
    onError: () => toast.error("삭제 실패"),
    onSettled: () => setDeletingPlannedId(null),
  });
  const deleteCompleted = useMutation({
    mutationFn: (ids: string[]) => tasksApi.deleteCompleted(ids),
    onMutate: (ids: string[]) => setDeletingCompletedId(ids[0] ?? null),
    onSuccess: () => { toast.success("삭제됨"); qc.invalidateQueries({ queryKey: ["tasks", "completed"] }); },
    onError: () => toast.error("삭제 실패"),
    onSettled: () => setDeletingCompletedId(null),
  });

  const handleProgressToggle = (id: string, field: "reception" | "processing" | "storage") => {
    const now = new Date().toISOString();
    setProgressPending((prev) => {
      const next = new Map(prev);
      const cur = next.get(id) ?? { reception: "", processing: "", storage: "" };
      next.set(id, { ...cur, [field]: cur[field] ? "" : now });
      return next;
    });
  };

  const handleBatch = () => {
    const comArr = Array.from(completedIds);
    const delArr = Array.from(deleteIds).filter((id) => !completedIds.has(id));

    // Collect pending progress changes
    const progressArr: Array<{ id: string; data: { reception: string; processing: string; storage: string } }> = [];
    for (const t of active as ActiveTask[]) {
      const pending = progressPending.get(t.id);
      if (!pending) continue;
      const changed =
        pending.reception !== ((t.reception as string) || "") ||
        pending.processing !== ((t.processing as string) || "") ||
        pending.storage !== ((t.storage as string) || "");
      if (changed) progressArr.push({ id: t.id, data: pending });
    }

    if (!comArr.length && !delArr.length && !progressArr.length) {
      toast.info("선택된 항목이 없습니다.");
      return;
    }

    // Single batch call — 1 read + 1 write regardless of how many rows changed
    if (progressArr.length) {
      batchProgressMut.mutate(progressArr.map(({ id, data }) => ({ id, ...data })));
    }

    if (comArr.length) {
      setShowCompleteModal(true);
      return;
    }
    if (delArr.length) deleteActiveMut.mutate(delArr);
  };

  const confirmComplete = () => {
    const comArr = Array.from(completedIds);
    const delArr = Array.from(deleteIds).filter((id) => !completedIds.has(id));
    if (comArr.length) completeMany.mutate(comArr);
    if (delArr.length) deleteActiveMut.mutate(delArr);
  };

  const hasProgressChanges = (active as ActiveTask[]).some((t) => {
    const pending = progressPending.get(t.id);
    return pending && (
      pending.reception !== ((t.reception as string) || "") ||
      pending.processing !== ((t.processing as string) || "") ||
      pending.storage !== ((t.storage as string) || "")
    );
  });

  // 완료업무 — 필터/정렬/페이지네이션은 모두 서버(DB LIMIT/OFFSET)에서 처리한다.
  // 여기서는 서버 응답을 그대로 렌더링만 한다 (client-side slice/필터 금지).
  const completedItems = completedResp?.items ?? [];
  const completedTotal = completedResp?.total ?? 0;
  const completedHasNext = completedResp?.has_next ?? false;
  const completedCategories = completedResp?.categories ?? [];
  const completedPageCount = Math.max(1, Math.ceil(completedTotal / COMPLETED_PAGE_SIZE));

  return (
    <div className="space-y-5">
      {/* 페이지 헤더 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="hw-page-title">업무관리</h1>
        <div className="flex items-center gap-2">
          {tab === "진행업무" && (
            <>
              <SubmitButton
                isSubmitting={addActive.isPending}
                onClick={() => addActive.mutate({
                  id: newId(), date: today(), category: "", name: "", work: "", details: "",
                })}
                loadingText="추가 중..."
                className="text-xs"
                style={{ padding: "6px 12px", fontSize: 12 }}
              >
                <><Plus size={13} /> 업무 추가</>
              </SubmitButton>
              {(completedIds.size > 0 || deleteIds.size > 0 || hasProgressChanges) && (
                <SubmitButton
                  isSubmitting={completeMany.isPending || deleteActiveMut.isPending}
                  onClick={handleBatch}
                  loadingText="처리 중..."
                  className="text-xs"
                  style={{ padding: "6px 12px", fontSize: 12, background: "#38A169" }}
                >
                  <><CheckCircle size={13} /> 선택 처리
                  {(completedIds.size + deleteIds.size) > 0 && ` (${completedIds.size + deleteIds.size}건)`}</>
                </SubmitButton>
              )}
            </>
          )}
          {tab === "예정업무" && (
            <SubmitButton
              isSubmitting={addPlanned.isPending}
              onClick={() => addPlanned.mutate({
                id: newId(), date: today(), period: "단기🔴", content: "", note: "",
              })}
              loadingText="추가 중..."
              className="text-xs"
              style={{ padding: "6px 12px", fontSize: 12 }}
            >
              <><Plus size={13} /> 추가</>
            </SubmitButton>
          )}
        </div>
      </div>

      {/* 탭 */}
      <div className="hw-tabs">
        {TABS.map((t) => (
          <button
            key={t}
            className={`hw-tab ${tab === t ? "active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
            {t === "진행업무" && (active as ActiveTask[]).length > 0 && (
              <span
                className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full font-bold"
                style={{
                  background: tab === t ? "var(--hw-gold)" : "#E2E8F0",
                  color: tab === t ? "#fff" : "#718096",
                }}
              >
                {(active as ActiveTask[]).length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── 진행업무 탭 ── */}
      {tab === "진행업무" && (() => {
        const allActive = active as ActiveTask[];
        // 분류 목록 (중복 제거)
        const categories = Array.from(new Set(allActive.map(t => t.category).filter(Boolean)));
        // 분류 필터 적용
        const filteredActive = activeCategory === "all"
          ? allActive
          : allActive.filter(t => t.category === activeCategory);
        // 카테고리별 건수
        const catCounts: Record<string, number> = {};
        for (const t of allActive) { if (t.category) catCounts[t.category] = (catCounts[t.category] || 0) + 1; }
        // 요약 카드 값 (필터된 데이터 기준)
        const urgentCount = filteredActive.filter(t => {
          const p = progressPending.get(t.id);
          const latestTs = [
            p?.storage ?? (t.storage as string) ?? "",
            p?.processing ?? (t.processing as string) ?? "",
            p?.reception ?? (t.reception as string) ?? "",
          ].filter(Boolean).sort().reverse()[0] ?? "";
          return _dPlusFromTs(latestTs) >= 20;
        }).length;
        const commonProps = {
          progressPending, completedIds, deleteIds,
          onProgressToggle: handleProgressToggle,
          onSave: (id: string, data: Partial<ActiveTask>) => updateActive.mutate({ id, data }),
          onToggleComplete: (id: string) => setCompletedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; }),
          onToggleDelete: (id: string) => setDeleteIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; }),
        };

        return (
          <>
            {/* 수입 합계 (일일결산 기준, 카드수입 포함) */}
            {incomeSummary && (incomeSummary.today > 0 || incomeSummary.month > 0) && (
              <div style={{
                marginBottom: 8, display: "flex", alignItems: "center", gap: 8,
                fontSize: 12, fontWeight: 600, color: "#276749",
                background: "#F0FFF4", border: "1px solid #9AE6B4",
                borderRadius: 8, padding: "6px 12px",
              }}>
                💰 수입 합계
                <span>오늘 {formatNumber(incomeSummary.today)}원</span>
                <span style={{ color: "#CBD5E0" }}>·</span>
                <span>이번 달 {formatNumber(incomeSummary.month)}원</span>
              </div>
            )}

            {/* 카드지출 누계 (일일결산 기준) */}
            {cardExpense && (cardExpense.today > 0 || cardExpense.month > 0) && (
              <div style={{
                marginBottom: 8, display: "flex", alignItems: "center", gap: 8,
                fontSize: 12, fontWeight: 600, color: "#9C4221",
                background: "#FFFAF0", border: "1px solid #FBD38D",
                borderRadius: 8, padding: "6px 12px",
              }}>
                💳 카드지출 누계
                <span>오늘 {formatNumber(cardExpense.today)}원</span>
                <span style={{ color: "#CBD5E0" }}>·</span>
                <span>이번 달 {formatNumber(cardExpense.month)}원</span>
              </div>
            )}

            {/* 요약 카드 */}
            <TaskSummaryCards
              totalCount={filteredActive.length}
              urgentCount={urgentCount}
              transferTotal={filteredActive.reduce((s, t) => s + safeInt(t.transfer), 0)}
              cashTotal={filteredActive.reduce((s, t) => s + safeInt(t.cash), 0)}
              stampTotal={filteredActive.reduce((s, t) => s + safeInt(t.stamp), 0)}
              hasUnpaid={filteredActive.some(t => safeInt(t.receivable) > 0)}
              receivableTotal={filteredActive.reduce((s, t) => s + safeInt(t.receivable), 0)}
            />

            {/* 분류 필터 + 뷰 토글 */}
            <div className="hw-card" style={{ padding: "0 0 0 0", overflow: "hidden" }}>
              <div style={{ padding: "0 16px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <TaskCategoryFilter
                  categories={categories}
                  activeCategory={activeCategory}
                  onChange={setActiveCategory}
                  counts={catCounts}
                  totalCount={allActive.length}
                />
                {/* 뷰 토글 */}
                <div style={{ display: "flex", gap: 0, borderRadius: 6, overflow: "hidden", border: "1px solid #E2E8F0", flexShrink: 0, marginLeft: 12 }}>
                  {(["table", "card"] as const).map(mode => (
                    <button key={mode} onClick={() => setViewMode(mode)} style={{
                      height: 28, padding: "0 12px", fontSize: 11, fontWeight: 600,
                      cursor: "pointer", border: "none",
                      background: viewMode === mode ? "#4A5568" : "#F7FAFC",
                      color: viewMode === mode ? "#fff" : "#718096",
                    }}>
                      {mode === "table" ? "☰ 테이블" : "⊞ 카드"}
                    </button>
                  ))}
                </div>
              </div>

              {filteredActive.length === 0 ? (
                <div className="p-6 text-center text-sm" style={{ color: "#A0AEC0" }}>
                  {allActive.length === 0 ? "진행 중인 업무가 없습니다." : "해당 분류의 업무가 없습니다."}
                </div>
              ) : (
                <>
                  {viewMode === "card" && (
                    <div style={{ padding: "0 16px 16px" }}>
                      <TaskCardView tasks={filteredActive} {...commonProps} />
                    </div>
                  )}
                  {viewMode === "table" && (
                    <TaskTableView tasks={filteredActive} {...commonProps} />
                  )}

                  {/* 합계 푸터 */}
                  <div className="px-4 py-2.5 flex flex-wrap gap-4 text-xs border-t"
                    style={{ borderColor: "#E2E8F0", color: "#718096" }}>
                    {(["transfer", "cash", "card", "stamp", "receivable"] as const).map((f) => {
                      const total = filteredActive.reduce((s, t) => s + safeInt(t[f]), 0);
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
          </>
        );
      })()}

      {/* ── 예정업무 탭 ── */}
      {tab === "예정업무" && (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          {(planned as PlannedTask[]).length === 0 ? (
            <div className="p-6 text-center text-sm" style={{ color: "#A0AEC0" }}>
              예정된 업무가 없습니다.
            </div>
          ) : (
            <table className="hw-table">
              <thead>
                <tr>
                  <th className="text-left">날짜</th>
                  <th className="text-left">기간</th>
                  <th className="text-left">내용</th>
                  <th className="text-left">비고</th>
                  <th className="text-center w-10">삭제</th>
                </tr>
              </thead>
              <tbody>
                {(planned as PlannedTask[]).map((task) => (
                  <tr key={task.id}>
                    <td className="w-28">
                      <input
                        className="hw-table-input"
                        defaultValue={task.date}
                        onBlur={(e) =>
                          updatePlanned.mutate({ id: task.id, data: { date: normalizeDate(e.target.value) } })
                        }
                      />
                    </td>
                    <td className="w-32">
                      <select
                        className="hw-table-input bg-transparent"
                        value={task.period}
                        onChange={(e) =>
                          updatePlanned.mutate({ id: task.id, data: { period: e.target.value } })
                        }
                      >
                        {PERIOD_OPTIONS.map((o) => (
                          <option key={o} value={o}>{o}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        className="hw-table-input"
                        defaultValue={task.content}
                        onBlur={(e) =>
                          updatePlanned.mutate({ id: task.id, data: { content: e.target.value } })
                        }
                      />
                    </td>
                    <td>
                      <input
                        className="hw-table-input"
                        defaultValue={task.note}
                        onBlur={(e) =>
                          updatePlanned.mutate({ id: task.id, data: { note: e.target.value } })
                        }
                      />
                    </td>
                    <td className="text-center">
                      <button
                        onClick={() => { if (!deletingPlannedId) deletePlanned.mutate([task.id]); }}
                        disabled={deletingPlannedId === task.id}
                        style={{ color: "#FC8181", opacity: deletingPlannedId === task.id ? 0.4 : 1 }}
                        className="hover:opacity-70 transition-opacity"
                      >
                        {deletingPlannedId === task.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── 완료업무 탭 ── */}
      {tab === "완료업무" && (
        <div>
          {/* 검색/필터 바 */}
          <div className="hw-card" style={{ padding: "10px 14px", marginBottom: 8 }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <input
                placeholder="이름 검색"
                value={completedFilterName}
                onChange={(e) => setCompletedFilterName(e.target.value)}
                style={{ height: 28, padding: "0 8px", fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 5, outline: "none", width: 110 }}
              />
              <select
                value={completedFilterCategory}
                onChange={(e) => setCompletedFilterCategory(e.target.value)}
                style={{ height: 28, padding: "0 6px", fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 5, outline: "none" }}
              >
                <option value="">분류 전체</option>
                {completedCategories.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <input
                placeholder="업무 검색"
                value={completedFilterWork}
                onChange={(e) => setCompletedFilterWork(e.target.value)}
                style={{ height: 28, padding: "0 8px", fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 5, outline: "none", width: 110 }}
              />
              <input type="date" value={completedDateFrom} onChange={(e) => setCompletedDateFrom(e.target.value)}
                style={{ height: 28, padding: "0 6px", fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 5, outline: "none" }} />
              <span style={{ fontSize: 11, color: "#A0AEC0" }}>~</span>
              <input type="date" value={completedDateTo} onChange={(e) => setCompletedDateTo(e.target.value)}
                style={{ height: 28, padding: "0 6px", fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 5, outline: "none" }} />
              <button
                onClick={() => setCompletedSort(completedSort === "newest" ? "oldest" : "newest")}
                style={{ height: 28, padding: "0 10px", fontSize: 11, fontWeight: 600, border: "1px solid #CBD5E0", borderRadius: 5, background: "#F7FAFC", color: "#4A5568", cursor: "pointer" }}
              >
                {completedSort === "newest" ? "최신순 ↓" : "오래된순 ↑"}
              </button>
              {(completedFilterName || completedFilterCategory || completedFilterWork || completedDateFrom || completedDateTo) && (
                <button
                  onClick={() => { setCompletedFilterName(""); setCompletedFilterCategory(""); setCompletedFilterWork(""); setCompletedDateFrom(""); setCompletedDateTo(""); }}
                  style={{ height: 28, padding: "0 10px", fontSize: 11, border: "1px solid #FEB2B2", borderRadius: 5, background: "#FFF5F5", color: "#E53E3E", cursor: "pointer" }}
                >
                  필터 초기화
                </button>
              )}
              <span style={{ fontSize: 11, color: "#A0AEC0", marginLeft: "auto" }}>
                총 {completedTotal}건{completedFetching ? " · 불러오는 중…" : ""}
              </span>
            </div>
          </div>

        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          {completedItems.length === 0 ? (
            <div className="p-6 text-center text-sm" style={{ color: "#A0AEC0" }}>
              완료된 업무가 없습니다.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="hw-table min-w-[600px]">
                <thead>
                  <tr>
                    <th className="text-left">분류</th>
                    <th className="text-left">접수일</th>
                    <th className="text-left">이름</th>
                    <th className="text-left">업무</th>
                    <th className="text-left">세부내용</th>
                    <th className="text-left">완료일</th>
                    <th className="text-center w-10">삭제</th>
                  </tr>
                </thead>
                <tbody>
                  {completedItems.map((task) => (
                    <tr key={task.id}>
                      <td>{task.category}</td>
                      <td>{task.date}</td>
                      <td className="font-medium">{task.name}</td>
                      <td>{task.work}</td>
                      <td style={{ color: "#718096" }}>{task.details}</td>
                      <td style={{ color: "#38A169" }}>{task.complete_date}</td>
                      <td className="text-center">
                        <button
                          onClick={() => { if (!deletingCompletedId) deleteCompleted.mutate([task.id]); }}
                          disabled={deletingCompletedId === task.id}
                          style={{ color: "#FC8181", opacity: deletingCompletedId === task.id ? 0.4 : 1 }}
                          className="hover:opacity-70 transition-opacity"
                        >
                          {deletingCompletedId === task.id ? <Loader2 size={13} className="animate-spin" /> : <Trash2 size={13} />}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* 페이지네이션 — 서버가 20건 단위로 내려주므로 이전/다음으로 조회 */}
        {completedTotal > 0 && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10, marginTop: 10 }}>
            <button
              onClick={() => setCompletedPage((p) => Math.max(1, p - 1))}
              disabled={completedPage <= 1 || completedFetching}
              style={{ height: 30, padding: "0 12px", fontSize: 12, fontWeight: 600, border: "1px solid #CBD5E0", borderRadius: 6, background: completedPage <= 1 ? "#EDF2F7" : "#fff", color: completedPage <= 1 ? "#A0AEC0" : "#4A5568", cursor: completedPage <= 1 ? "default" : "pointer" }}
            >
              ← 이전
            </button>
            <span style={{ fontSize: 12, color: "#4A5568", fontWeight: 600, minWidth: 90, textAlign: "center" }}>
              {completedPage} / {completedPageCount} 페이지
            </span>
            <button
              onClick={() => setCompletedPage((p) => (completedHasNext ? p + 1 : p))}
              disabled={!completedHasNext || completedFetching}
              style={{ height: 30, padding: "0 12px", fontSize: 12, fontWeight: 600, border: "1px solid #CBD5E0", borderRadius: 6, background: !completedHasNext ? "#EDF2F7" : "#fff", color: !completedHasNext ? "#A0AEC0" : "#4A5568", cursor: !completedHasNext ? "default" : "pointer" }}
            >
              다음 →
            </button>
          </div>
        )}
        </div>
      )}

      {/* 완료이동 확인 모달 */}
      {showCompleteModal && (
        <CompleteConfirmModal
          count={completedIds.size}
          onConfirm={confirmComplete}
          onCancel={() => setShowCompleteModal(false)}
        />
      )}
    </div>
  );
}
