"use client";
import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { dailyApi, customersApi, type DailyEntry, type BalanceData } from "@/lib/api";
import { today, safeInt, formatNumber } from "@/lib/utils";
import { Plus, Trash2, ChevronLeft, ChevronRight, BarChart2, Save, Pencil, X, UserPlus, ScanLine } from "lucide-react";

// ── 기존 Streamlit 구분 옵션 (그대로 복원) ──
const 구분_옵션 = ["출입국", "전자민원", "공증", "여권", "초청", "영주권", "기타"];
const CAT_OPTIONS = ["현금출금", ...구분_옵션]; // 현금출금 선두
const INCOME_METHODS = ["", "이체", "현금", "카드", "미수"];
const EXPENSE_METHODS = ["", "이체", "현금", "카드", "인지"];

// 메모 태그 파싱 (기존 Streamlit _unpack_memo 동일)
// e1a / e2a = per-slot expense amounts (added to preserve individual amounts)
function unpackMemo(memo: string): { inc: string; e1: string; e1a: string; e2: string; e2a: string; user: string } {
  const result: Record<string, string> = { inc: "", e1: "", e1a: "", e2: "", e2a: "", user: memo || "" };
  if (!memo) return result as ReturnType<typeof unpackMemo>;
  const start = memo.indexOf("[KID]");
  const end = memo.indexOf("[/KID]");
  if (start !== -1 && end !== -1 && end > start) {
    const inner = memo.slice(start + 5, end);
    inner.split(";").forEach((part) => {
      const [k, v] = part.split("=");
      if (k && v !== undefined) result[k.trim()] = v.trim();
    });
    result.user = memo.slice(end + 6).trim();
  }
  return result as ReturnType<typeof unpackMemo>;
}

// e1a / e2a carry per-slot amounts so they survive the exp_etc aggregation
function packMemo(inc: string, e1: string, e1a: string, e2: string, e2a: string, userMemo: string): string {
  const tag = `[KID]inc=${inc};e1=${e1};e1a=${e1a};e2=${e2};e2a=${e2a}[/KID]`;
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
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
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

  // Day of month from selected date — used to clamp prior-month averages to same cutoff
  const viewDay = useMemo(() => parseInt(date.slice(8, 10), 10), [date]);

  // Cumulative net for current month up to (and including) selected date
  const cumulativeNet = useMemo(() => {
    const es = (monthlySummary as any)?.entries as any[] | undefined;
    if (!es) return null;
    const filtered = es.filter((e) => (e.date || "") <= date);
    const inc  = filtered.reduce((s, e) => s + safeInt(e.income_cash) + safeInt(e.income_etc), 0);
    const exp  = filtered.reduce((s, e) => s + safeInt(e.exp_cash)    + safeInt(e.exp_etc),    0);
    const cout = filtered.reduce((s, e) => s + safeInt(e.cash_out), 0);
    return { net: inc - exp, totalInc: inc, totalExp: exp + cout };
  }, [monthlySummary, date]);

  // Helper: sum a month's entries up to the same day-of-month cutoff
  const netUpToDay = (mData: any, day: number) => {
    const es = mData?.entries as any[] | undefined;
    if (!es) return { net: safeInt(mData?.net_income), incCash: 0, incEtc: 0, expCash: 0, expEtc: 0 };
    const cutoff = String(day).padStart(2, "0");
    const filtered = es.filter((e) => (String(e.date || "").slice(8, 10) || "99") <= cutoff);
    return {
      net:     filtered.reduce((s, e) => s + safeInt(e.income_cash) + safeInt(e.income_etc) - safeInt(e.exp_cash) - safeInt(e.exp_etc), 0),
      incCash: filtered.reduce((s, e) => s + safeInt(e.income_cash), 0),
      incEtc:  filtered.reduce((s, e) => s + safeInt(e.income_etc),  0),
      expCash: filtered.reduce((s, e) => s + safeInt(e.exp_cash),    0),
      expEtc:  filtered.reduce((s, e) => s + safeInt(e.exp_etc),     0),
    };
  };

  const avg3 = useMemo(() => {
    const months = [m1, m2, m3].filter(Boolean);
    if (!months.length) return null;
    const summed = months.map((m) => netUpToDay(m, viewDay));
    const avgIncome = Math.round(summed.reduce((s, m) => s + m.net,     0) / summed.length);
    const avgInCash = Math.round(summed.reduce((s, m) => s + m.incCash, 0) / summed.length);
    const avgInEtc  = Math.round(summed.reduce((s, m) => s + m.incEtc,  0) / summed.length);
    const avgExCash = Math.round(summed.reduce((s, m) => s + m.expCash, 0) / summed.length);
    const avgExEtc  = Math.round(summed.reduce((s, m) => s + m.expEtc,  0) / summed.length);
    return { avgIncome, avgInCash, avgInEtc, avgExCash, avgExEtc };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [m1, m2, m3, viewDay]);

  // ── 고객 자동완성 ──
  const [customerSuggestions, setCustomerSuggestions] = useState<Record<string, string>[]>([]);
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [showNewCustomerModal, setShowNewCustomerModal] = useState(false);
  const nameInputRef = useRef<HTMLInputElement>(null);
  // Dropdown uses position:fixed to escape parent overflow:auto clipping
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number } | null>(null);

  const updateDropdownPos = () => {
    if (nameInputRef.current) {
      const r = nameInputRef.current.getBoundingClientRect();
      setDropdownPos({ top: r.bottom + 2, left: r.left, width: Math.max(r.width, 240) });
    }
  };

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

  // 이름 입력 시 고객 자동완성 검색
  useEffect(() => {
    if (!newName.trim() || newName.length < 1) {
      setCustomerSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const res = await customersApi.list(newName.trim());
        const list = (res.data as Record<string, string>[]).slice(0, 8);
        setCustomerSuggestions(list);
        setShowSuggestions(list.length > 0 || newName.trim().length > 0);
      } catch {}
    }, 280);
    return () => clearTimeout(timer);
  }, [newName]);

  const addNewCustomerMut = useMutation({
    mutationFn: (data: Record<string, string>) => customersApi.add(data),
    onSuccess: (res) => {
      const newId = (res.data as { 고객ID: string }).고객ID;
      setSelectedCustomerId(newId);
      setShowNewCustomerModal(false);
      toast.success("신규 고객 등록됨");
    },
    onError: () => toast.error("고객 등록 실패"),
  });

  const addMut = useMutation({
    mutationFn: (entry: Partial<DailyEntry>) => dailyApi.addEntry(entry),
    onSuccess: () => {
      // 위임내역 append는 backend add_entry에서 처리 (daily.py _append_delegation_to_customer)
      toast.success("추가됨");
      // 입력 초기화
      setNewCategory(""); setNewName(""); setNewTask(""); setNewTime("");
      setNewIncType(""); setNewE1Type(""); setNewE2Type("");
      setNewIncAmt(""); setNewE1Amt(""); setNewE2Amt(""); setNewCashOut(""); setNewMemo("");
      setSelectedCustomerId(null); setCustomerSuggestions([]); setShowSuggestions(false);
    },
    onError: () => toast.error("추가 실패"),
    onSettled: () => {
      // 성공/실패 무관하게 항상 갱신 (기존 고객의 경우 위임내역 업데이트로 응답이 느릴 수 있음)
      qc.invalidateQueries({ queryKey: ["daily", "entries"] });
      qc.invalidateQueries({ queryKey: ["tasks", "active"] });
    },
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

    const memo = isCashOut ? newMemo : packMemo(newIncType, newE1Type, String(e1Amt), newE2Type, String(e2Amt), newMemo);

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

    // Compute display-oriented amounts (same logic as the view rendering).
    // Store these into the flat fields the edit inputs read/write so they load correctly.
    let incDisplay = 0, e1Display = 0, e2Display = 0;
    if (!isCashOut) {
      incDisplay = meta.inc === "현금" ? safeInt(entry.income_cash) : safeInt(entry.income_etc);
      if (meta.e1a || meta.e2a) {
        // New format: individual amounts stored in memo tag
        e1Display = safeInt(meta.e1a); e2Display = safeInt(meta.e2a);
      } else if (meta.e1 === "현금" && meta.e2 !== "현금") {
        e1Display = safeInt(entry.exp_cash); e2Display = safeInt(entry.exp_etc);
      } else if (meta.e1 !== "현금" && meta.e2 === "현금") {
        e1Display = safeInt(entry.exp_etc);  e2Display = safeInt(entry.exp_cash);
      } else {
        e1Display = safeInt(entry.exp_cash) + safeInt(entry.exp_etc); e2Display = 0;
      }
    }

    setEditId(entry.id);
    setEditValues({
      ...entry,
      inc_type: meta.inc,
      e1_type: meta.e1,
      e2_type: meta.e2,
      user_memo: meta.user,
      // income_cash holds the single display amount for income (type-resolved)
      income_cash: incDisplay,
      income_etc: 0,
      // exp_cash = e1 display amount, exp_etc = e2 display amount (position-mapped)
      exp_cash: e1Display,
      exp_etc: e2Display,
      cash_out: safeInt(entry.cash_out),
    });
  }, []);

  // 수정 저장
  const saveEdit = useCallback(() => {
    if (!editId) return;
    const isCashOut = editValues.category === "현금출금";
    // income_cash now holds the single display amount (set by startEdit + onChange)
    const incAmt = safeInt(editValues.income_cash);
    // exp_cash = e1 display amount, exp_etc = e2 display amount
    const e1Amt  = safeInt(editValues.exp_cash);
    const e2Amt  = safeInt(editValues.exp_etc);

    let income_cash = 0, income_etc = 0, exp_cash = 0, exp_etc = 0, cash_out = 0;
    if (isCashOut) {
      cash_out = safeInt(editValues.cash_out);
    } else {
      // Route income by type — same as handleAdd
      if (editValues.inc_type === "현금") income_cash = incAmt;
      else income_etc = incAmt;
      // Route each expense amount by its type — same as handleAdd
      if ((editValues.e1_type as string) === "현금") exp_cash += e1Amt; else exp_etc += e1Amt;
      if ((editValues.e2_type as string) === "현금") exp_cash += e2Amt;
      else if (editValues.e2_type) exp_etc += e2Amt;
    }

    const memo = isCashOut
      ? (editValues.user_memo || "")
      : packMemo(editValues.inc_type || "", editValues.e1_type || "", String(e1Amt), editValues.e2_type || "", String(e2Amt), editValues.user_memo || "");

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
      <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3,1fr)", gap: "12px" }}>
        {/* 이번달 누적 순수익 카드 (선택 날짜까지만) */}
        <div className="hw-card" style={{ padding: "16px" }}>
          <div style={{ fontSize: 11, color: "#718096", fontWeight: 500, marginBottom: 4 }}>
            {viewMonth}월 누적 순수익 (1일~{date.slice(8)}일)
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: (cumulativeNet?.net ?? 0) >= 0 ? "#276749" : "#C53030" }}>
            {formatNumber(cumulativeNet?.net ?? 0)}
          </div>
          <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 4 }}>
            {cumulativeNet ? (
              <>수입 {formatNumber(cumulativeNet.totalInc)} / 지출 {formatNumber(cumulativeNet.totalExp)}</>
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
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(3, 1fr)", gap: 10 }}>
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
          {/* 성명 (96px) — 고객 자동완성 */}
          <div style={{ width: 96, flexShrink: 0, position: "relative" }}>
            <div style={{ fontSize: 10, color: "#718096", marginBottom: 2, display: "flex", alignItems: "center", gap: 4 }}>
              성명
              {selectedCustomerId && (
                <span style={{ fontSize: 9, color: "#38A169", fontWeight: 700 }}>●연결됨</span>
              )}
            </div>
            <input
              ref={nameInputRef}
              style={{ ...inputSm, width: "100%" }}
              placeholder="성명 검색"
              value={newName}
              onChange={(e) => { setNewName(e.target.value); setSelectedCustomerId(null); updateDropdownPos(); }}
              onFocus={() => { updateDropdownPos(); if (customerSuggestions.length > 0) setShowSuggestions(true); }}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 180)}
              autoComplete="off"
            />
            {showSuggestions && dropdownPos && (
              <div style={{
                position: "fixed",
                top: dropdownPos.top,
                left: dropdownPos.left,
                width: dropdownPos.width,
                zIndex: 9999,
                background: "#fff", border: "1px solid #E2E8F0", borderRadius: 6,
                maxHeight: 220, overflowY: "auto",
                boxShadow: "0 4px 16px rgba(0,0,0,0.14)",
              }}>
                {customerSuggestions.map((c) => (
                  <div
                    key={c["고객ID"]}
                    onMouseDown={() => {
                      setNewName(c["한글"] || `${c["성"]} ${c["명"]}`.trim());
                      setSelectedCustomerId(c["고객ID"]);
                      setShowSuggestions(false);
                    }}
                    style={{ padding: "6px 10px", fontSize: 12, cursor: "pointer", borderBottom: "1px solid #F7FAFC" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "#F7FAFC")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                  >
                    <span style={{ fontWeight: 600 }}>{c["한글"] || `${c["성"]} ${c["명"]}`.trim()}</span>
                    <span style={{ marginLeft: 6, fontSize: 10, color: "#A0AEC0" }}>{c["국적"]} {c["V"]}</span>
                  </div>
                ))}
                <div
                  onMouseDown={() => { setShowSuggestions(false); setShowNewCustomerModal(true); }}
                  style={{ padding: "6px 10px", fontSize: 12, cursor: "pointer", color: "#F5A623", fontWeight: 600, display: "flex", alignItems: "center", gap: 4 }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "#FFFBF0")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                >
                  <UserPlus size={11} /> 신규 고객 등록
                </div>
              </div>
            )}
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
                  if (meta.e1a || meta.e2a) {
                    dispE1 = safeInt(meta.e1a); dispE2 = safeInt(meta.e2a);
                  } else if (meta.e1 === "현금" && meta.e2 !== "현금") {
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
                                  setEditValues((p) => ({ ...p, income_cash: v, income_etc: 0 }));
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

      {/* ── 신규 고객 등록 모달 ── */}
      {showNewCustomerModal && (
        <NewCustomerModal
          initialName={newName}
          onClose={() => setShowNewCustomerModal(false)}
          onSubmit={(data) => addNewCustomerMut.mutate(data)}
          isSaving={addNewCustomerMut.isPending}
        />
      )}
    </div>
  );
}

// ── 신규 고객 간편 등록 모달 ────────────────────────────────────────────────────
function NewCustomerModal({
  initialName, onClose, onSubmit, isSaving,
}: {
  initialName: string;
  onClose: () => void;
  onSubmit: (data: Record<string, string>) => void;
  isSaving: boolean;
}) {
  const router = useRouter();
  const [form, setForm] = useState<Record<string, string>>({
    한글: initialName,
    국적: "", 성: "", 명: "", V: "",
    연: "010", 락: "", 처: "",
    등록증: "", 번호: "", 발급일: "", 만기일: "",
    여권: "", 발급: "", 만기: "",
  });
  const set = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const inputSm: React.CSSProperties = {
    width: "100%", border: "1px solid #CBD5E0", borderRadius: 6,
    padding: "5px 8px", fontSize: 12, outline: "none", background: "#fff",
    boxSizing: "border-box",
  };
  const label: React.CSSProperties = { display: "block", fontSize: 10, color: "#718096", marginBottom: 2 };

  return (
    <div className="hw-modal-overlay" onClick={onClose}>
      <div className="hw-modal" style={{ maxWidth: 480, padding: 0 }} onClick={(e) => e.stopPropagation()}>
        <div className="hw-modal-header" style={{ padding: "14px 20px" }}>
          <span>신규 고객 등록</span>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              onClick={() => { onClose(); router.push("/scan"); }}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                fontSize: 11, fontWeight: 600, color: "#3182CE",
                background: "#EBF8FF", border: "1px solid #BEE3F8",
                borderRadius: 6, padding: "3px 8px", cursor: "pointer",
              }}
              title="OCR 스캔 페이지에서 여권/등록증을 스캔하세요. 완료 후 일일결산으로 돌아와서 입력하세요."
            >
              <ScanLine size={12} /> OCR 스캔
            </button>
            <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0" }}>
              <X size={15} />
            </button>
          </div>
        </div>
        <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 10, maxHeight: "60vh", overflowY: "auto" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div><label style={label}>한글이름 *</label><input style={inputSm} value={form["한글"]} onChange={(e) => set("한글", e.target.value)} placeholder="홍길동" /></div>
            <div><label style={label}>국적</label><input style={inputSm} value={form["국적"]} onChange={(e) => set("국적", e.target.value)} placeholder="CHN" /></div>
            <div><label style={label}>영문 성 (Last)</label><input style={inputSm} value={form["성"]} onChange={(e) => set("성", e.target.value)} placeholder="HONG" /></div>
            <div><label style={label}>영문 이름 (First)</label><input style={inputSm} value={form["명"]} onChange={(e) => set("명", e.target.value)} placeholder="GILDONG" /></div>
            <div><label style={label}>체류자격</label><input style={inputSm} value={form["V"]} onChange={(e) => set("V", e.target.value)} placeholder="F-6" /></div>
            <div><label style={label}>여권번호</label><input style={inputSm} value={form["여권"]} onChange={(e) => set("여권", e.target.value)} placeholder="AB1234567" /></div>
          </div>
          <div>
            <label style={label}>전화번호</label>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 4 }}>
              <input style={inputSm} value={form["연"]} onChange={(e) => set("연", e.target.value)} placeholder="010" />
              <input style={inputSm} value={form["락"]} onChange={(e) => set("락", e.target.value)} placeholder="0000" />
              <input style={inputSm} value={form["처"]} onChange={(e) => set("처", e.target.value)} placeholder="0000" />
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div><label style={label}>등록번호 앞 (생년월일)</label><input style={inputSm} value={form["등록증"]} onChange={(e) => set("등록증", e.target.value)} placeholder="YYMMDD" /></div>
            <div><label style={label}>등록번호 뒤 7자리</label><input style={inputSm} value={form["번호"]} onChange={(e) => set("번호", e.target.value)} placeholder="1234567" /></div>
            <div><label style={label}>등록증 만기일</label><input style={inputSm} value={form["만기일"]} onChange={(e) => set("만기일", e.target.value)} placeholder="YYYY-MM-DD" /></div>
            <div><label style={label}>여권 만기일</label><input style={inputSm} value={form["만기"]} onChange={(e) => set("만기", e.target.value)} placeholder="YYYY-MM-DD" /></div>
          </div>
        </div>
        <div className="hw-modal-footer">
          <button onClick={onClose} className="btn-secondary" style={{ fontSize: 12 }}>취소</button>
          <button
            onClick={() => { if (!form["한글"].trim()) { toast.error("한글이름은 필수입니다."); return; } onSubmit(form); }}
            disabled={isSaving}
            className="btn-primary"
            style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 5 }}
          >
            <UserPlus size={13} /> 등록
          </button>
        </div>
      </div>
    </div>
  );
}