"use client";
import { useState, useMemo, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { dailyApi, type DailyEntry, type BalanceData } from "@/lib/api";
import { today, safeInt, formatNumber } from "@/lib/utils";
import { Plus, Trash2, ChevronLeft, ChevronRight, BarChart2, Save, Pencil, X } from "lucide-react";

// ── 기존 Streamlit 구분 옵션 (그대로 복원) ──
const 구분_옵션 = ["출입국", "전자민원", "공증", "여권", "초청", "영주권", "기타"];
const CAT_OPTIONS = ["현금출금", ...구분_옵션]; // 현금출금 선두
const INCOME_METHODS = ["", "이체", "현금", "카드", "미수"];
const EXPENSE_METHODS = ["", "이체", "현금", "카드", "인지"];

// 메모 태그 파싱 (기존 Streamlit _unpack_memo 동일)
function unpackMemo(memo: string): { inc: string; e1: string; e2: string; user: string } {
  const result = { inc: "", e1: "", e2: "", user: memo || "" };
  if (!memo) return result;
  const start = memo.indexOf("[KID]");
  const end = memo.indexOf("[/KID]");
  if (start !== -1 && end !== -1 && end > start) {
    const inner = memo.slice(start + 5, end);
    inner.split(";").forEach((part) => {
      const [k, v] = part.split("=");
      if (k && v !== undefined) result[k.trim() as "inc" | "e1" | "e2"] = v.trim();
    });
    result.user = memo.slice(end + 6).trim();
  }
  return result;
}

function packMemo(inc: string, e1: string, e2: string, userMemo: string): string {
  const tag = `[KID]inc=${inc};e1=${e1};e2=${e2}[/KID]`;
  return userMemo ? `${tag} ${userMemo}` : tag;
}

const cellStyle: React.CSSProperties = {
  border: "none",
  background: "transparent",
  fontSize: 12,
  outline: "none",
  width: "100%",
};

const selectCellStyle: React.CSSProperties = {
  ...cellStyle,
  cursor: "pointer",
};

export default function DailyPage() {
  const qc = useQueryClient();
  const [date, setDate] = useState(today());
  const [showMonthly, setShowMonthly] = useState(false);
  const [editId, setEditId] = useState<string | null>(null); // 수정 중인 행 id
  const [editValues, setEditValues] = useState<Partial<DailyEntry & { inc_type: string; e1_type: string; e2_type: string; user_memo: string }>>({});

  // 현재 날짜에서 연/월 추출
  const [viewYear, viewMonth] = useMemo(() => {
    const d = new Date(date);
    return [d.getFullYear(), d.getMonth() + 1];
  }, [date]);

  const { data: entries = [] } = useQuery({
    queryKey: ["daily", "entries", date],
    queryFn: () => dailyApi.getEntries(date).then((r) => r.data),
  });

  const { data: balance = { cash: 0, profit: 0 } } = useQuery({
    queryKey: ["daily", "balance"],
    queryFn: () => dailyApi.getBalance().then((r) => r.data),
  });

  // 월별 합계 – 항상 현재 연/월의 요약을 불러와서 카드에 표시하고, 패널에도 사용한다.
  const { data: monthlySummary } = useQuery({
    queryKey: ["daily", "summary", viewYear, viewMonth],
    queryFn: () => dailyApi.getMonthlySummary(viewYear, viewMonth).then((r) => r.data),
  });

  // 직전 3개월 평균
  const prev3Months = useMemo(() => {
    const months = [] as { year: number; month: number }[];
    for (let i = 1; i <= 3; i++) {
      const d = new Date(viewYear, viewMonth - 1 - i, 1);
      months.push({ year: d.getFullYear(), month: d.getMonth() + 1 });
    }
    return months;
  }, [viewYear, viewMonth]);

  const { data: m1 } = useQuery({
    queryKey: ["daily", "summary", prev3Months[0].year, prev3Months[0].month],
    queryFn: () => dailyApi.getMonthlySummary(prev3Months[0].year, prev3Months[0].month).then((r) => r.data),
  });
  const { data: m2 } = useQuery({
    queryKey: ["daily", "summary", prev3Months[1].year, prev3Months[1].month],
    queryFn: () => dailyApi.getMonthlySummary(prev3Months[1].year, prev3Months[1].month).then((r) => r.data),
  });
  const { data: m3 } = useQuery({
    queryKey: ["daily", "summary", prev3Months[2].year, prev3Months[2].month],
    queryFn: () => dailyApi.getMonthlySummary(prev3Months[2].year, prev3Months[2].month).then((r) => r.data),
  });

  const avg3 = useMemo(() => {
    const months = [m1, m2, m3].filter(Boolean);
    if (!months.length) return null;
    const avgIncome = Math.round(months.reduce((s, m: any) => s + safeInt(m?.net_income), 0) / months.length);
    const avgInCash = Math.round(months.reduce((s, m: any) => s + safeInt(m?.income_cash), 0) / months.length);
    const avgInEtc  = Math.round(months.reduce((s, m: any) => s + safeInt(m?.income_etc), 0) / months.length);
    const avgExCash = Math.round(months.reduce((s, m: any) => s + safeInt(m?.exp_cash), 0) / months.length);
    const avgExEtc  = Math.round(months.reduce((s, m: any) => s + safeInt(m?.exp_etc), 0) / months.length);
    return { avgIncome, avgInCash, avgInEtc, avgExCash, avgExEtc };
  }, [m1, m2, m3]);

  // ── 새 항목 상태 ──
  const [newCategory, setNewCategory] = useState("");
  const [newName, setNewName] = useState("");
  const [newTask, setNewTask] = useState("");
  const [newTime, setNewTime] = useState(""); // 비워두면 추가 시 현재 시간 자동
  const [newIncType, setNewIncType] = useState("");
  const [newE1Type, setNewE1Type] = useState("");
  const [newE2Type, setNewE2Type] = useState("");
  const [newIncAmt, setNewIncAmt] = useState("");
  const [newE1Amt, setNewE1Amt] = useState("");
  const [newE2Amt, setNewE2Amt] = useState("");
  const [newCashOut, setNewCashOut] = useState("");
  const [newMemo, setNewMemo] = useState("");

  const addMut = useMutation({
    mutationFn: (entry: Partial<DailyEntry>) => dailyApi.addEntry(entry),
    onSuccess: () => {
      toast.success("추가됨");
      qc.invalidateQueries({ queryKey: ["daily", "entries"] });
      // 입력 초기화
      setNewCategory(""); setNewName(""); setNewTask(""); setNewTime("");
      setNewIncType(""); setNewE1Type(""); setNewE2Type("");
      setNewIncAmt(""); setNewE1Amt(""); setNewE2Amt(""); setNewCashOut(""); setNewMemo("");
    },
    onError: () => toast.error("추가 실패"),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<DailyEntry> }) =>
      dailyApi.updateEntry(id, data),
    onSuccess: () => {
      toast.success("수정됨");
      qc.invalidateQueries({ queryKey: ["daily", "entries"] });
      setEditId(null);
    },
    onError: () => toast.error("수정 실패"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => dailyApi.deleteEntry(id),
    onSuccess: () => { toast.success("삭제됨"); qc.invalidateQueries({ queryKey: ["daily", "entries"] }); },
  });

  const saveBalMut = useMutation({
    mutationFn: (data: BalanceData) => dailyApi.saveBalance(data),
    onSuccess: () => { toast.success("잔액 저장됨"); qc.invalidateQueries({ queryKey: ["daily", "balance"] }); },
  });

  // 오늘 데이터 시간순 정렬
  const sortedEntries = useMemo(() =>
    [...(entries as DailyEntry[])].sort((a, b) => (a.time || "").localeCompare(b.time || "")),
    [entries]
  );

  // 합계 계산
  const sumInCash = (entries as DailyEntry[]).reduce((s, e) => s + safeInt(e.income_cash), 0);
  const sumInEtc  = (entries as DailyEntry[]).reduce((s, e) => s + safeInt(e.income_etc), 0);
  const sumExCash = (entries as DailyEntry[]).reduce((s, e) => s + safeInt(e.exp_cash), 0);
  const sumExEtc  = (entries as DailyEntry[]).reduce((s, e) => s + safeInt(e.exp_etc), 0);
  const sumCashOut= (entries as DailyEntry[]).reduce((s, e) => s + safeInt(e.cash_out), 0);
  const netTotal  = sumInCash + sumInEtc - sumExCash - sumExEtc - sumCashOut;

  const moveDate = (delta: number) => {
    const d = new Date(date);
    d.setDate(d.getDate() + delta);
    setDate(d.toISOString().slice(0, 10));
  };

  // 새 항목 추가 핸들러
  const handleAdd = useCallback(() => {
    if (!newCategory) { toast.error("구분을 선택하세요."); return; }
    const isCashOut = newCategory === "현금출금";

    // 시간 비어있으면 현재 시각 자동입력
    const now = new Date();
    const autoTime = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    const timeVal = newTime.trim() || autoTime;

    let income_cash = 0, income_etc = 0, exp_cash = 0, exp_etc = 0, cash_out = 0;
    const incAmt = safeInt(newIncAmt);
    const e1Amt  = safeInt(newE1Amt);
    const e2Amt  = safeInt(newE2Amt);
    const coAmt  = safeInt(newCashOut);

    if (isCashOut) {
      cash_out = coAmt;
    } else {
      if (newIncType === "현금") income_cash = incAmt;
      else income_etc = incAmt;
      if (newE1Type === "현금") exp_cash += e1Amt;
      else exp_etc += e1Amt;
      if (newE2Type === "현금") exp_cash += e2Amt;
      else if (newE2Type) exp_etc += e2Amt;
    }

    const memo = isCashOut ? newMemo : packMemo(newIncType, newE1Type, newE2Type, newMemo);

    addMut.mutate({
      date,
      time: timeVal,
      category: newCategory,
      name: newName,
      task: newTask,
      income_cash,
      income_etc,
      exp_cash,
      exp_etc,
      cash_out,
      memo,
    });
  }, [newCategory, newName, newTask, newTime, newIncType, newE1Type, newE2Type, newIncAmt, newE1Amt, newE2Amt, newCashOut, newMemo, date, addMut]);

  // 수정 시작
  const startEdit = useCallback((entry: DailyEntry) => {
    const meta = unpackMemo(entry.memo || "");
    const isCashOut = entry.category === "현금출금" || safeInt(entry.cash_out) > 0;
    let incAmt = "", e1Amt = "", e2Amt = "";
    if (!isCashOut) {
      incAmt = String(meta.inc === "현금" ? safeInt(entry.income_cash) : safeInt(entry.income_etc)) || "";
      const expTotal = safeInt(entry.exp_cash) + safeInt(entry.exp_etc);
      if (meta.e1 === "현금" && meta.e2 !== "현금") {
        e1Amt = String(safeInt(entry.exp_cash));
        e2Amt = String(safeInt(entry.exp_etc));
      } else if (meta.e1 !== "현금" && meta.e2 === "현금") {
        e1Amt = String(safeInt(entry.exp_etc));
        e2Amt = String(safeInt(entry.exp_cash));
      } else {
        e1Amt = String(expTotal);
        e2Amt = "";
      }
    }
    setEditId(entry.id);
    setEditValues({
      ...entry,
      inc_type: meta.inc,
      e1_type: meta.e1,
      e2_type: meta.e2,
      user_memo: meta.user,
      income_cash: safeInt(entry.income_cash),
      income_etc: safeInt(entry.income_etc),
      exp_cash: safeInt(entry.exp_cash),
      exp_etc: safeInt(entry.exp_etc),
      cash_out: safeInt(entry.cash_out),
    });
  }, []);

  // 수정 저장
  const saveEdit = useCallback(() => {
    if (!editId) return;
    const isCashOut = editValues.category === "현금출금";
    const incAmt = safeInt(editValues.income_cash);
    const e1Amt  = safeInt(editValues.exp_cash);
    const e2Amt  = safeInt(editValues.exp_etc);

    let income_cash = 0, income_etc = 0, exp_cash = 0, exp_etc = 0, cash_out = 0;
    if (isCashOut) {
      cash_out = safeInt(editValues.cash_out);
    } else {
      if (editValues.inc_type === "현금") income_cash = incAmt;
      else income_etc = incAmt;
      exp_cash = e1Amt; // 이미 분리 저장된 값 그대로
      exp_etc  = e2Amt;
    }

    const memo = isCashOut
      ? (editValues.user_memo || "")
      : packMemo(editValues.inc_type || "", editValues.e1_type || "", editValues.e2_type || "", editValues.user_memo || "");

    updateMut.mutate({
      id: editId,
      data: {
        date: (editValues.date as string) || date,
        time: editValues.time || "",
        category: editValues.category || "",
        name: editValues.name || "",
        task: editValues.task || "",
        income_cash,
        income_etc,
        exp_cash,
        exp_etc,
        cash_out,
        memo,
      },
    });
  }, [editId, editValues, updateMut]);

  const inputSm: React.CSSProperties = {
    border: "1px solid #CBD5E0",
    borderRadius: 6,
    padding: "4px 6px",
    fontSize: 12,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>

      {/* ── 헤더 ── */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
        <h1 className="hw-page-title">📊 일일결산</h1>
        <div style={{ display: "flex", alignItems: "center", gap: "4px", background: "#fff", border: "1px solid #E2E8F0", borderRadius: 8, padding: "4px 8px" }}>
          <button onClick={() => moveDate(-1)} style={{ padding: "2px", cursor: "pointer", color: "#718096", background: "none", border: "none" }}>
            <ChevronLeft size={14} />
          </button>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
            style={{ fontSize: 13, border: "none", outline: "none", background: "transparent", cursor: "pointer" }} />
          <button onClick={() => moveDate(1)} style={{ padding: "2px", cursor: "pointer", color: "#718096", background: "none", border: "none" }}>
            <ChevronRight size={14} />
          </button>
        </div>
        <button onClick={() => setDate(today())}
          style={{ fontSize: 12, color: "#3182CE", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>
          오늘
        </button>
        <button onClick={() => setShowMonthly((p) => !p)} className="btn-secondary"
          style={{ marginLeft: "auto", fontSize: 12, padding: "5px 12px", display: "flex", alignItems: "center", gap: 4 }}>
          <BarChart2 size={12} /> {showMonthly ? "월별 합계 닫기" : `${viewYear}년 ${viewMonth}월 합계`}
        </button>
      </div>

      {/* ── 요약 카드 ── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "12px" }}>
        {/* 이번달 누적 순수익 카드 */}
        <div className="hw-card" style={{ padding: "16px" }}>
          <div style={{ fontSize: 11, color: "#718096", fontWeight: 500, marginBottom: 4 }}>이번달 누적 순수익</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: safeInt((monthlySummary as any)?.net_income) >= 0 ? "#276749" : "#C53030" }}>
            {formatNumber(safeInt((monthlySummary as any)?.net_income))}
          </div>
          <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 4 }}>
            {monthlySummary ? (
              <>
                수입 {formatNumber(safeInt((monthlySummary as any)?.income_cash) + safeInt((monthlySummary as any)?.income_etc))} / 지출 {formatNumber(safeInt((monthlySummary as any)?.exp_cash) + safeInt((monthlySummary as any)?.exp_etc) + safeInt((monthlySummary as any)?.cash_out))}
              </>
            ) : null}
          </div>
        </div>
        {/* 오늘 수익 합계 카드 */}
        <div className="hw-card" style={{ padding: "16px" }}>
          <div style={{ fontSize: 11, color: "#718096", fontWeight: 500, marginBottom: 4 }}>오늘 수익 합계</div>
          <div style={{ fontSize: 22, fontWeight: 700, color: "#276749" }}>
            {formatNumber(sumInCash + sumInEtc - sumExCash - sumExEtc)}
          </div>
          <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 4 }}>
            수입 {formatNumber(sumInCash + sumInEtc)} / 지출 {formatNumber(sumExCash + sumExEtc)}
          </div>
        </div>
        {/* 직전 3개월 평균 카드 */}
        {avg3 ? (
          <div className="hw-card" style={{ padding: "10px 16px" }}>
            <div style={{ fontSize: 11, color: "#718096", fontWeight: 500, marginBottom: 6, display: "flex", alignItems: "center", gap: 4 }}>
              <BarChart2 size={12} /> 직전 3개월 평균
            </div>
            <div style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12 }}>
              <span>순수익: <strong style={{ color: avg3.avgIncome >= 0 ? "#276749" : "#C53030" }}>{formatNumber(avg3.avgIncome)}</strong></span>
              <span style={{ color: "#718096" }}>수입(현){formatNumber(avg3.avgInCash)} / 수입(기타){formatNumber(avg3.avgInEtc)}</span>
              <span style={{ color: "#718096" }}>지출(현){formatNumber(avg3.avgExCash)} / 지출(기타){formatNumber(avg3.avgExEtc)}</span>
            </div>
          </div>
        ) : (<div />)}
      </div>

      {/* 월별 합계 패널 */}
      {showMonthly && monthlySummary && (
        <div className="hw-card" style={{ padding: "12px 16px" }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#2D3748", marginBottom: 10 }}>
            {viewYear}년 {viewMonth}월 결산 합계
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
            {[
              { label: "수입(현금)", val: (monthlySummary as any).income_cash, color: "#2B6CB0" },
              { label: "수입(기타)", val: (monthlySummary as any).income_etc, color: "#2B6CB0" },
              { label: "지출(현금)", val: (monthlySummary as any).exp_cash, color: "#C53030" },
              { label: "지출(기타)", val: (monthlySummary as any).exp_etc, color: "#C53030" },
              { label: "현금출납", val: (monthlySummary as any).cash_out, color: "#718096" },
              { label: "순수익", val: (monthlySummary as any).net_income, color: safeInt((monthlySummary as any).net_income) >= 0 ? "#276749" : "#C53030" },
            ].map(({ label, val, color }) => (
              <div key={label} style={{ background: "#F7FAFC", borderRadius: 6, padding: "8px 10px" }}>
                <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color }}>{formatNumber(safeInt(val))}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── 새 항목 추가 폼 ── 테이블 컬럼(시간/구분/성명/세부내용/수입/지출1/지출2)과 단일 행 정렬 */}
      <div className="hw-card" style={{ padding: "8px 12px", overflowX: "auto" }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>+ 새 내역</div>
        <div style={{ display: "flex", gap: 6, alignItems: "flex-end", minWidth: 900 }}>
          {/* 시간 (80px) */}
          <div style={{ width: 80, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>시간</div>
            <input type="time" title="시간 (비워두면 자동)" style={{ ...inputSm, width: "100%" }}
              value={newTime} onChange={(e) => setNewTime(e.target.value)} />
          </div>
          {/* 구분 (60px) */}
          <div style={{ width: 60, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>구분</div>
            <select style={{ ...inputSm, width: "100%" }} value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
              <option value="">선택</option>
              {CAT_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          {/* 성명 (72px) */}
          <div style={{ width: 72, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>성명</div>
            <input style={{ ...inputSm, width: "100%" }} placeholder="성명" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </div>
          {/* 세부내용 및 비고 (flex) */}
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>세부내용</div>
            <div style={{ display: "flex", gap: 4 }}>
              <input style={{ ...inputSm, flex: 1 }} placeholder="세부내용" value={newTask} onChange={(e) => setNewTask(e.target.value)} />
              <input style={{ ...inputSm, width: 72, flexShrink: 0 }} placeholder="비고" value={newMemo} onChange={(e) => setNewMemo(e.target.value)} />
            </div>
          </div>
          {/* 수입 (90px) */}
          <div style={{ width: 90, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>수입</div>
            {newCategory === "현금출금" ? (
              <div style={{ height: 52 }} />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <select style={{ ...inputSm, width: "100%", fontSize: 11 }} value={newIncType} onChange={(e) => setNewIncType(e.target.value)}>
                  {INCOME_METHODS.map((m) => <option key={m} value={m}>{m || "유형"}</option>)}
                </select>
                <input type="text" inputMode="numeric" style={{ ...inputSm, width: "100%", textAlign: "right" }}
                  placeholder="0" value={newIncAmt} onChange={(e) => setNewIncAmt(e.target.value)} />
              </div>
            )}
          </div>
          {/* 지출1 (90px) */}
          <div style={{ width: 90, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>지출1</div>
            {newCategory === "현금출금" ? (
              <input type="text" inputMode="numeric" style={{ ...inputSm, width: "100%", textAlign: "right" }}
                placeholder="출금액" value={newCashOut} onChange={(e) => setNewCashOut(e.target.value)} />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <select style={{ ...inputSm, width: "100%", fontSize: 11 }} value={newE1Type} onChange={(e) => setNewE1Type(e.target.value)}>
                  {EXPENSE_METHODS.map((m) => <option key={m} value={m}>{m || "유형"}</option>)}
                </select>
                <input type="text" inputMode="numeric" style={{ ...inputSm, width: "100%", textAlign: "right" }}
                  placeholder="0" value={newE1Amt} onChange={(e) => setNewE1Amt(e.target.value)} />
              </div>
            )}
          </div>
          {/* 지출2 (90px) */}
          <div style={{ width: 90, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2 }}>지출2</div>
            {newCategory === "현금출금" ? (
              <div style={{ height: 52 }} />
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                <select style={{ ...inputSm, width: "100%", fontSize: 11 }} value={newE2Type} onChange={(e) => setNewE2Type(e.target.value)}>
                  {EXPENSE_METHODS.map((m) => <option key={m} value={m}>{m || "유형"}</option>)}
                </select>
                <input type="text" inputMode="numeric" style={{ ...inputSm, width: "100%", textAlign: "right" }}
                  placeholder="0" value={newE2Amt} onChange={(e) => setNewE2Amt(e.target.value)} />
              </div>
            )}
          </div>
          {/* 추가 버튼 (64px) */}
          <div style={{ width: 64, flexShrink: 0, display: "flex", alignItems: "flex-end" }}>
            <button onClick={handleAdd} disabled={addMut.isPending} className="btn-primary"
              style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, padding: "6px 10px", justifyContent: "center", width: "100%" }}>
              <Plus size={12} /> 추가
            </button>
          </div>
        </div>
      </div>

      {/* ── 결산 테이블 ── */}
      <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="hw-table" style={{ minWidth: 820 }}>
            <thead>
              <tr>
                <th style={{ width: 60, textAlign: "left" }}>구분</th>
                <th style={{ width: 72, textAlign: "left" }}>성명</th>
                <th style={{ textAlign: "left" }}>세부내용</th>
                <th style={{ width: 90, textAlign: "right" }}>수입</th>
                <th style={{ width: 90, textAlign: "right" }}>지출1</th>
                <th style={{ width: 90, textAlign: "right" }}>지출2</th>
                <th style={{ width: 90, textAlign: "right" }}>순수익</th>
                <th style={{ width: 32, textAlign: "center" }}>수정</th>
                <th style={{ width: 32, textAlign: "center" }}>삭제</th>
              </tr>
            </thead>
            <tbody>
              {sortedEntries.map((entry) => {
                const meta = unpackMemo(entry.memo || "");
                const isCashOut = entry.category === "현금출금" || safeInt(entry.cash_out) > 0;
                const isEditing = editId === entry.id;

                // 표시용 금액 계산
                let dispInc = 0, dispE1 = 0, dispE2 = 0;
                let incLabel = meta.inc || "", e1Label = meta.e1 || "", e2Label = meta.e2 || "";
                if (isCashOut) {
                  dispE1 = safeInt(entry.cash_out);
                  e1Label = "현금출금";
                } else {
                  dispInc = meta.inc === "현금" ? safeInt(entry.income_cash) : safeInt(entry.income_etc);
                  if (meta.e1 === "현금" && meta.e2 !== "현금") {
                    dispE1 = safeInt(entry.exp_cash); dispE2 = safeInt(entry.exp_etc);
                  } else if (meta.e1 !== "현금" && meta.e2 === "현금") {
                    dispE1 = safeInt(entry.exp_etc); dispE2 = safeInt(entry.exp_cash);
                  } else {
                    dispE1 = safeInt(entry.exp_cash) + safeInt(entry.exp_etc); dispE2 = 0;
                  }
                }
                const profitVal = dispInc - dispE1 - dispE2;

                if (isEditing) {
                  const ev = editValues;
                  const editIsCashOut = ev.category === "현금출금";
                  return (
                    <tr key={entry.id} style={{ background: "#FFFBEA" }}>
                      <td>
                        <select style={{ ...cellStyle, fontSize: 11, width: 72 }}
                          value={ev.category || ""} onChange={(e) => setEditValues((p) => ({ ...p, category: e.target.value }))}>
                          <option value="">선택</option>
                          {CAT_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </td>
                      <td><input style={{ ...cellStyle, minWidth: 60 }} value={ev.name || ""} onChange={(e) => setEditValues((p) => ({ ...p, name: e.target.value }))} /></td>
                      <td>
                        <div style={{ display: "flex", gap: 4 }}>
                          <input type="time" style={{ ...cellStyle, width: 80 }} value={ev.time || ""} onChange={(e) => setEditValues((p) => ({ ...p, time: e.target.value }))} />
                          <input style={{ ...cellStyle, flex: 1 }} value={ev.task || ""} onChange={(e) => setEditValues((p) => ({ ...p, task: e.target.value }))} />
                        </div>
                      </td>
                      {editIsCashOut ? (
                        <>
                          <td colSpan={2} style={{ textAlign: "right" }}>
                            <input type="text" inputMode="numeric" style={{ ...cellStyle, textAlign: "right", width: 80 }}
                              value={safeInt(ev.cash_out) || ""} onChange={(e) => setEditValues((p) => ({ ...p, cash_out: safeInt(e.target.value) }))} />
                          </td>
                          <td />
                        </>
                      ) : (
                        <>
                          <td style={{ textAlign: "right" }}>
                            <div style={{ display: "flex", gap: 2, justifyContent: "flex-end" }}>
                              <select style={{ ...cellStyle, fontSize: 10, width: 44 }}
                                value={ev.inc_type || ""} onChange={(e) => setEditValues((p) => ({ ...p, inc_type: e.target.value }))}>
                                {INCOME_METHODS.map((m) => <option key={m} value={m}>{m || "-"}</option>)}
                              </select>
                              <input type="text" inputMode="numeric" style={{ ...cellStyle, textAlign: "right", width: 60 }}
                                value={safeInt(ev.income_cash) + safeInt(ev.income_etc) || ""}
                                onChange={(e) => {
                                  const v = safeInt(e.target.value);
                                  if (ev.inc_type === "현금") setEditValues((p) => ({ ...p, income_cash: v, income_etc: 0 }));
                                  else setEditValues((p) => ({ ...p, income_etc: v, income_cash: 0 }));
                                }} />
                            </div>
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <div style={{ display: "flex", gap: 2, justifyContent: "flex-end" }}>
                              <select style={{ ...cellStyle, fontSize: 10, width: 44 }}
                                value={ev.e1_type || ""} onChange={(e) => setEditValues((p) => ({ ...p, e1_type: e.target.value }))}>
                                {EXPENSE_METHODS.map((m) => <option key={m} value={m}>{m || "-"}</option>)}
                              </select>
                              <input type="text" inputMode="numeric" style={{ ...cellStyle, textAlign: "right", width: 60 }}
                                value={safeInt(ev.exp_cash) || ""}
                                onChange={(e) => setEditValues((p) => ({ ...p, exp_cash: safeInt(e.target.value) }))} />
                            </div>
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <div style={{ display: "flex", gap: 2, justifyContent: "flex-end" }}>
                              <select style={{ ...cellStyle, fontSize: 10, width: 44 }}
                                value={ev.e2_type || ""} onChange={(e) => setEditValues((p) => ({ ...p, e2_type: e.target.value }))}>
                                {EXPENSE_METHODS.map((m) => <option key={m} value={m}>{m || "-"}</option>)}
                              </select>
                              <input type="text" inputMode="numeric" style={{ ...cellStyle, textAlign: "right", width: 60 }}
                                value={safeInt(ev.exp_etc) || ""}
                                onChange={(e) => setEditValues((p) => ({ ...p, exp_etc: safeInt(e.target.value) }))} />
                            </div>
                          </td>
                        </>
                      )}
                      {/* 순수익 칸: 편집 모드에서는 비워둔다 */}
                      <td />
                      <td style={{ textAlign: "center" }}>
                        <button onClick={saveEdit} disabled={updateMut.isPending}
                          style={{ color: "#48BB78", background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                          <Save size={13} />
                        </button>
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <button onClick={() => setEditId(null)}
                          style={{ color: "#A0AEC0", background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                          <X size={13} />
                        </button>
                      </td>
                    </tr>
                  );
                }

                return (
                  <tr key={entry.id}>
                    <td style={{ fontSize: 12 }}>
                      <span style={{ fontSize: 11, color: "#718096", display: "block" }}>{entry.time?.slice(0, 5)}</span>
                      {entry.category}
                    </td>
                    <td style={{ fontSize: 12 }}>{entry.name}</td>
                    <td style={{ fontSize: 12 }}>
                      {entry.task}
                      {meta.user && <span style={{ fontSize: 10, color: "#A0AEC0", marginLeft: 4 }}>({meta.user})</span>}
                    </td>
                    <td style={{ textAlign: "right", fontSize: 12 }}>
                      {dispInc > 0 && (
                        <span>{incLabel && <span style={{ fontSize: 10, color: "#718096", marginRight: 2 }}>{incLabel}</span>}{formatNumber(dispInc)}</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right", fontSize: 12, color: isCashOut ? "#718096" : "#C53030" }}>
                      {dispE1 > 0 && (
                        <span>{e1Label && <span style={{ fontSize: 10, color: "#718096", marginRight: 2 }}>{e1Label}</span>}{formatNumber(dispE1)}</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right", fontSize: 12, color: "#C53030" }}>
                      {dispE2 > 0 && (
                        <span>{e2Label && <span style={{ fontSize: 10, color: "#718096", marginRight: 2 }}>{e2Label}</span>}{formatNumber(dispE2)}</span>
                      )}
                    </td>
                    {/* 순수익 표시 */}
                    <td style={{ textAlign: "right", fontSize: 12, color: profitVal >= 0 ? "#276749" : "#C53030" }}>
                      {profitVal !== 0 && formatNumber(profitVal)}
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <button onClick={() => startEdit(entry)}
                        style={{ color: "#3182CE", background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                        <Pencil size={11} />
                      </button>
                    </td>
                    <td style={{ textAlign: "center" }}>
                      <button onClick={() => deleteMut.mutate(entry.id)}
                        style={{ color: "#FC8181", background: "none", border: "none", cursor: "pointer", padding: 2 }}>
                        <Trash2 size={11} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr style={{ background: "#F7FAFC", fontWeight: 600, fontSize: 12, color: "#2D3748", borderTop: "2px solid #E2E8F0" }}>
                <td colSpan={3} style={{ padding: "6px 8px", textAlign: "right" }}>합계</td>
                <td style={{ padding: "6px 8px", textAlign: "right", color: "#2B6CB0" }}>{formatNumber(sumInCash + sumInEtc)}</td>
                <td style={{ padding: "6px 8px", textAlign: "right", color: "#C53030" }}>{formatNumber(sumExCash + sumCashOut)}</td>
                <td style={{ padding: "6px 8px", textAlign: "right", color: "#C53030" }}>{formatNumber(sumExEtc)}</td>
                <td style={{ padding: "6px 8px", textAlign: "right", color: netTotal >= 0 ? "#276749" : "#C53030" }}>{formatNumber(netTotal)}</td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  );
}