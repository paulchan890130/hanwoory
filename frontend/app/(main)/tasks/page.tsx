"use client";
import { useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { tasksApi, type ActiveTask, type PlannedTask, type CompletedTask } from "@/lib/api";
import { today, safeInt, formatNumber, normalizeDate } from "@/lib/utils";
import { Plus, Trash2, CheckCircle, AlertTriangle } from "lucide-react";

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
            style={{ padding: "2px 7px", fontSize: 9, fontWeight: 700, background: "#F5A623", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer", whiteSpace: "nowrap" }}>
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
              { field: "processing", label: "처리",  color: "#D69E2E", onColor: "#975A16", ts: pendingProcessing },
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
  const { data: completed = [] } = useQuery({
    queryKey: ["tasks", "completed"],
    queryFn: () => tasksApi.getCompleted().then((r) => r.data),
  });

  // ── Mutations ──
  const updateActive = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<ActiveTask> }) =>
      tasksApi.updateActive(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", "active"] }),
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
    onSuccess: () => {
      toast.success("삭제됨");
      qc.invalidateQueries({ queryKey: ["tasks", "planned"] });
    },
  });
  const deleteCompleted = useMutation({
    mutationFn: (ids: string[]) => tasksApi.deleteCompleted(ids),
    onSuccess: () => {
      toast.success("삭제됨");
      qc.invalidateQueries({ queryKey: ["tasks", "completed"] });
    },
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

  return (
    <div className="space-y-5">
      {/* 페이지 헤더 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="hw-page-title">업무관리</h1>
        <div className="flex items-center gap-2">
          {tab === "진행업무" && (
            <>
              <button
                onClick={() => addActive.mutate({
                  id: newId(), date: today(), category: "", name: "", work: "", details: "",
                })}
                disabled={addActive.isPending}
                className="btn-primary flex items-center gap-1.5 text-xs"
              >
                <Plus size={13} /> 업무 추가
              </button>
              {(completedIds.size > 0 || deleteIds.size > 0 || hasProgressChanges) && (
                <button
                  onClick={handleBatch}
                  disabled={completeMany.isPending || deleteActiveMut.isPending}
                  className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50"
                  style={{ background: "#38A169" }}
                >
                  <CheckCircle size={13} /> 선택 처리
                  {(completedIds.size + deleteIds.size) > 0 && ` (${completedIds.size + deleteIds.size}건)`}
                </button>
              )}
            </>
          )}
          {tab === "예정업무" && (
            <button
              onClick={() => addPlanned.mutate({
                id: newId(), date: today(), period: "단기🔴", content: "", note: "",
              })}
              disabled={addPlanned.isPending}
              className="btn-primary flex items-center gap-1.5 text-xs"
            >
              <Plus size={13} /> 추가
            </button>
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
      {tab === "진행업무" && (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          {(active as ActiveTask[]).length === 0 ? (
            <div className="p-6 text-center text-sm" style={{ color: "#A0AEC0" }}>
              진행 중인 업무가 없습니다. [업무 추가] 버튼을 눌러 등록하세요.
            </div>
          ) : (
            <>
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
                    {(active as ActiveTask[]).map((task) => (
                      <ActiveTaskRow
                        key={task.id}
                        task={task}
                        onSave={(id, data) => updateActive.mutate({ id, data })}
                        onToggleComplete={(id) =>
                          setCompletedIds((prev) => {
                            const n = new Set(prev);
                            n.has(id) ? n.delete(id) : n.add(id);
                            return n;
                          })
                        }
                        onToggleDelete={(id) =>
                          setDeleteIds((prev) => {
                            const n = new Set(prev);
                            n.has(id) ? n.delete(id) : n.add(id);
                            return n;
                          })
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

              {/* 미수금 합계 푸터 */}
              <div
                className="px-4 py-2.5 flex flex-wrap gap-4 text-xs border-t"
                style={{ borderColor: "#E2E8F0", color: "#718096" }}
              >
                {(["transfer", "cash", "card", "stamp", "receivable"] as const).map((f) => {
                  const total = (active as ActiveTask[]).reduce(
                    (s, t) => s + safeInt(t[f]),
                    0
                  );
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
      )}

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
                        onClick={() => deletePlanned.mutate([task.id])}
                        style={{ color: "#FC8181" }}
                        className="hover:opacity-70 transition-opacity"
                      >
                        <Trash2 size={13} />
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
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          {(completed as CompletedTask[]).length === 0 ? (
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
                  {(completed as CompletedTask[]).map((task) => (
                    <tr key={task.id}>
                      <td>{task.category}</td>
                      <td>{task.date}</td>
                      <td className="font-medium">{task.name}</td>
                      <td>{task.work}</td>
                      <td style={{ color: "#718096" }}>{task.details}</td>
                      <td style={{ color: "#38A169" }}>{task.complete_date}</td>
                      <td className="text-center">
                        <button
                          onClick={() => deleteCompleted.mutate([task.id])}
                          style={{ color: "#FC8181" }}
                          className="hover:opacity-70 transition-opacity"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
