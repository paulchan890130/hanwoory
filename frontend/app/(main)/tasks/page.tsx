"use client";
import { useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { tasksApi, type ActiveTask, type PlannedTask, type CompletedTask } from "@/lib/api";
import { today, safeInt, formatNumber } from "@/lib/utils";
import { Plus, Trash2, CheckCircle, AlertTriangle } from "lucide-react";

const newId = () => crypto.randomUUID();

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

  const handleBatch = () => {
    const comArr = Array.from(completedIds);
    const delArr = Array.from(deleteIds).filter((id) => !completedIds.has(id));
    if (comArr.length) {
      setShowCompleteModal(true);
      return;
    }
    if (delArr.length) deleteActiveMut.mutate(delArr);
    if (!comArr.length && !delArr.length) toast.info("선택된 항목이 없습니다.");
  };

  const confirmComplete = () => {
    const comArr = Array.from(completedIds);
    const delArr = Array.from(deleteIds).filter((id) => !completedIds.has(id));
    if (comArr.length) completeMany.mutate(comArr);
    if (delArr.length) deleteActiveMut.mutate(delArr);
  };

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
              {(completedIds.size > 0 || deleteIds.size > 0) && (
                <button
                  onClick={handleBatch}
                  disabled={completeMany.isPending || deleteActiveMut.isPending}
                  className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50"
                  style={{ background: "#38A169" }}
                >
                  <CheckCircle size={13} /> 선택 처리 ({completedIds.size + deleteIds.size}건)
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
                <table className="hw-table min-w-[900px]">
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
                      <th className="text-center w-10">처리</th>
                      <th className="text-center w-10">완료✅</th>
                      <th className="text-center w-10">삭제❌</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(active as ActiveTask[]).map((task) => {
                      const isProc =
                        task.processed === true ||
                        String(task.processed).toLowerCase() === "true";
                      const rowBg = deleteIds.has(task.id)
                        ? "rgba(229,62,62,0.06)"
                        : completedIds.has(task.id)
                        ? "rgba(72,187,120,0.08)"
                        : undefined;
                      return (
                        <tr key={task.id} style={{ background: rowBg }}>
                          {(["category", "date", "name"] as const).map((f) => (
                            <td key={f}>
                              <input
                                className="hw-table-input"
                                defaultValue={task[f]}
                                onBlur={(e) =>
                                  updateActive.mutate({ id: task.id, data: { [f]: e.target.value } })
                                }
                              />
                            </td>
                          ))}
                          <td className="min-w-[120px]">
                            {isProc ? (
                              <span style={{ color: "#3182CE", fontWeight: 500 }}>{task.work}</span>
                            ) : (
                              <input
                                className="hw-table-input"
                                defaultValue={task.work}
                                onBlur={(e) =>
                                  updateActive.mutate({ id: task.id, data: { work: e.target.value } })
                                }
                              />
                            )}
                          </td>
                          <td className="min-w-[140px]">
                            {isProc ? (
                              <span style={{ color: "#3182CE" }}>{task.details}</span>
                            ) : (
                              <input
                                className="hw-table-input"
                                defaultValue={task.details}
                                onBlur={(e) =>
                                  updateActive.mutate({ id: task.id, data: { details: e.target.value } })
                                }
                              />
                            )}
                          </td>
                          {(["transfer", "cash", "card", "stamp", "receivable"] as const).map((f) => (
                            <td key={f} className="text-right w-14">
                              <input
                                type="text"
                                inputMode="numeric"
                                className="hw-table-input text-right"
                                defaultValue={safeInt(task[f]) || ""}
                                onBlur={(e) =>
                                  updateActive.mutate({ id: task.id, data: { [f]: e.target.value } })
                                }
                              />
                            </td>
                          ))}
                          <td className="text-center w-10">
                            <input
                              type="checkbox"
                              checked={isProc}
                              onChange={() =>
                                updateActive.mutate({ id: task.id, data: { processed: !isProc } })
                              }
                              style={{ accentColor: "#3182CE" }}
                            />
                          </td>
                          <td className="text-center w-10">
                            <input
                              type="checkbox"
                              checked={completedIds.has(task.id)}
                              onChange={() =>
                                setCompletedIds((prev) => {
                                  const n = new Set(prev);
                                  n.has(task.id) ? n.delete(task.id) : n.add(task.id);
                                  return n;
                                })
                              }
                              style={{ accentColor: "#38A169" }}
                            />
                          </td>
                          <td className="text-center w-10">
                            <input
                              type="checkbox"
                              checked={deleteIds.has(task.id)}
                              onChange={() =>
                                setDeleteIds((prev) => {
                                  const n = new Set(prev);
                                  n.has(task.id) ? n.delete(task.id) : n.add(task.id);
                                  return n;
                                })
                              }
                              style={{ accentColor: "#E53E3E" }}
                            />
                          </td>
                        </tr>
                      );
                    })}
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
                          updatePlanned.mutate({ id: task.id, data: { date: e.target.value } })
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
