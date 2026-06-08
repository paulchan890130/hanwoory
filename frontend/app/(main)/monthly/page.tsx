"use client";
import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { dailyApi, type YearlyOverview, type YearlyMonthCell, type FixedExpense, type TaxSummary } from "@/lib/api";
import { formatManwon, formatNumber } from "@/lib/utils";

// ── 색상 ─────────────────────────────────────────────────────────────────
const GOLD       = "#D4A843";
const GOLD_LIGHT = "rgba(212,168,67,0.12)";
const BLUE       = "#4299E1";
const GREEN      = "#48BB78";
const BORDER     = "#E2E8F0";
const GRAY_BG    = "#F9FAFB";

function fmt(n: number) { return n.toLocaleString("ko-KR"); }       // 원 단위 (tooltip/상세용)
function man(n: number) { return formatManwon(n); }                 // 만원 단위 (요약/표/카드)
// 차트 축 라벨용 짧은 만원 표기 ("125만")
function manAxis(n: number) {
  const v = Math.round((n / 10000) * 10) / 10;
  return `${(Number.isInteger(v) ? v : v.toFixed(1)).toLocaleString("ko-KR")}만`;
}

// ── 타입 ─────────────────────────────────────────────────────────────────
interface SummaryRow {
  month: string;
  income_cash: number; income_etc: number;
  exp_cash: number;    exp_etc: number;
  net: number;
}
interface TrendPoint  { month: string; net: number }
interface DowPoint    { name: string;  net: number;  [key: string]: string | number }
interface CatPoint    { name: string;  net: number;  [key: string]: string | number }
interface HourPoint   { hour: string;  net: number;  [key: string]: string | number }
interface AnalysisData {
  summary_table: SummaryRow[];
  trend:         TrendPoint[];
  selected_month: string;
  dow:           DowPoint[];
  category:      CatPoint[];
  hour:          HourPoint[];
}

// ── 카드 ─────────────────────────────────────────────────────────────────
function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: "#fff", border: `1px solid ${BORDER}`,
      borderRadius: 12, padding: "20px 24px",
      boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
    }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: "#2D3748", marginBottom: 16 }}>{title}</div>
      {children}
    </div>
  );
}

// ── SVG 세로 막대 차트 ───────────────────────────────────────────────────
function BarChartV({
  data, xKey, yKey, color, height = 200,
}: {
  data: { [key: string]: string | number }[];
  xKey: string; yKey: string; color: string; height?: number;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; label: string; val: number } | null>(null);

  const W = 540, H = height;
  const pad = { top: 16, right: 20, bottom: 32, left: 56 };
  const innerW = W - pad.left - pad.right;
  const innerH = H - pad.top - pad.bottom;

  const maxAbs = Math.max(...data.map((d) => Math.abs(Number(d[yKey]))), 1);
  const barW = Math.max(8, (innerW / data.length) * 0.55);
  const gap  = innerW / data.length;

  const toY = (val: number) => {
    const midY = pad.top + innerH / 2;
    return midY - (val / maxAbs) * (innerH / 2);
  };
  const midY = pad.top + innerH / 2;

  return (
    <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 300 }}>
        {/* 그리드 라인 */}
        {[-1, -0.5, 0, 0.5, 1].map((f) => {
          const y = pad.top + innerH / 2 - f * innerH / 2;
          return (
            <g key={f}>
              <line x1={pad.left} x2={W - pad.right} y1={y} y2={y}
                stroke={f === 0 ? "#CBD5E0" : "#EDF2F7"} strokeWidth={f === 0 ? 1.5 : 1} />
              <text x={pad.left - 6} y={y + 4} textAnchor="end" fontSize={10} fill="#A0AEC0">
                {manAxis(maxAbs * f)}
              </text>
            </g>
          );
        })}

        {/* 막대 */}
        {data.map((d, i) => {
          const val  = Number(d[yKey]);
          const cx   = pad.left + gap * i + gap / 2;
          const bx   = cx - barW / 2;
          const topY = toY(val);
          const barH = Math.abs(topY - midY);
          const barTop = val >= 0 ? topY : midY;
          return (
            <g key={i}
              onMouseMove={(e) => {
                const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: String(d[xKey]), val });
              }}
              onMouseLeave={() => setTip(null)}
            >
              <rect x={bx} y={barTop} width={barW} height={Math.max(barH, 2)}
                fill={val >= 0 ? color : "#FC8181"} rx={3} opacity={0.85} />
              <text x={cx} y={H - pad.bottom + 14} textAnchor="middle" fontSize={11} fill="#718096">
                {String(d[xKey])}
              </text>
            </g>
          );
        })}
      </svg>

      {tip && (
        <div style={{
          position: "absolute", left: tip.x + 8, top: tip.y - 28,
          background: "#fff", border: `1px solid ${BORDER}`,
          borderRadius: 6, padding: "6px 10px", fontSize: 12, pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", zIndex: 10,
        }}>
          <b>{tip.label}</b>: <span style={{ color: tip.val >= 0 ? "#276749" : "#C53030" }}>{fmt(tip.val)}원</span>
        </div>
      )}
    </div>
  );
}

// ── SVG 가로 막대 차트 (카테고리) ─────────────────────────────────────────
function BarChartH({
  data, height = 220,
}: {
  data: CatPoint[]; height?: number;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; label: string; val: number } | null>(null);
  const sliced = data.slice(0, 10);

  const W = 480, H = Math.max(height, sliced.length * 26 + 40);
  const pad = { top: 10, right: 60, bottom: 20, left: 90 };
  const innerW = W - pad.left - pad.right;
  const innerH = H - pad.top - pad.bottom;

  const maxAbs = Math.max(...sliced.map((d) => Math.abs(d.net)), 1);
  const rowH   = innerH / sliced.length;
  const barH   = Math.max(8, rowH * 0.55);

  const toX = (val: number) => pad.left + (Math.max(val, 0) / maxAbs) * innerW;

  return (
    <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 280 }}>
        {/* 세로 기준선 */}
        <line x1={pad.left} x2={pad.left} y1={pad.top} y2={H - pad.bottom}
          stroke="#CBD5E0" strokeWidth={1.5} />

        {sliced.map((d, i) => {
          const cy  = pad.top + rowH * i + rowH / 2;
          const by  = cy - barH / 2;
          const bw  = Math.max((Math.abs(d.net) / maxAbs) * innerW, 2);
          const bx  = d.net >= 0 ? pad.left : pad.left - bw;
          return (
            <g key={i}
              onMouseMove={(e) => {
                const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: d.name, val: d.net });
              }}
              onMouseLeave={() => setTip(null)}
            >
              <rect x={bx} y={by} width={bw} height={barH}
                fill={d.net >= 0 ? GREEN : "#FC8181"} rx={2} opacity={0.85} />
              <text x={pad.left - 6} y={cy + 4} textAnchor="end" fontSize={11} fill="#4A5568">
                {d.name.length > 8 ? d.name.slice(0, 8) + "…" : d.name}
              </text>
              <text x={pad.left + bw + 6} y={cy + 4} textAnchor="start" fontSize={10} fill="#718096">
                {manAxis(d.net)}
              </text>
            </g>
          );
        })}
      </svg>

      {tip && (
        <div style={{
          position: "absolute", left: tip.x + 8, top: tip.y - 28,
          background: "#fff", border: `1px solid ${BORDER}`,
          borderRadius: 6, padding: "6px 10px", fontSize: 12, pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", zIndex: 10,
        }}>
          <b>{tip.label}</b>: <span style={{ color: tip.val >= 0 ? "#276749" : "#C53030" }}>{fmt(tip.val)}원</span>
        </div>
      )}
    </div>
  );
}

// ── SVG 라인 차트 ─────────────────────────────────────────────────────────
function LineChartSVG({ data }: { data: TrendPoint[] }) {
  const [tip, setTip] = useState<{ x: number; y: number; label: string; val: number } | null>(null);

  const W = 860, H = 200;
  const pad = { top: 16, right: 24, bottom: 36, left: 60 };
  const innerW = W - pad.left - pad.right;
  const innerH = H - pad.top - pad.bottom;

  if (data.length === 0) {
    return <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>데이터 없음</div>;
  }

  const minVal = Math.min(...data.map((d) => d.net));
  const maxVal = Math.max(...data.map((d) => d.net));
  const range  = maxVal - minVal || 1;

  const toX = (i: number) => pad.left + (i / Math.max(data.length - 1, 1)) * innerW;
  const toY = (v: number) => pad.top + innerH - ((v - minVal) / range) * innerH;

  const points = data.map((d, i) => `${toX(i)},${toY(d.net)}`).join(" ");

  // y 눈금 (3개)
  const yTicks = [minVal, (minVal + maxVal) / 2, maxVal];

  return (
    <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 400 }}>
        {/* 그리드 */}
        {yTicks.map((v, i) => {
          const y = toY(v);
          return (
            <g key={i}>
              <line x1={pad.left} x2={W - pad.right} y1={y} y2={y}
                stroke="#EDF2F7" strokeWidth={1} strokeDasharray="4,4" />
              <text x={pad.left - 6} y={y + 4} textAnchor="end" fontSize={10} fill="#A0AEC0">
                {manAxis(v)}
              </text>
            </g>
          );
        })}

        {/* 0 선 */}
        {minVal < 0 && maxVal > 0 && (
          <line x1={pad.left} x2={W - pad.right} y1={toY(0)} y2={toY(0)}
            stroke="#CBD5E0" strokeWidth={1.5} />
        )}

        {/* 라인 */}
        <polyline points={points} fill="none" stroke={GOLD} strokeWidth={2.5} strokeLinejoin="round" />

        {/* 점 */}
        {data.map((d, i) => (
          <g key={i}>
            <circle cx={toX(i)} cy={toY(d.net)} r={4} fill={GOLD} />
            <circle cx={toX(i)} cy={toY(d.net)} r={10} fill="transparent"
              onMouseMove={(e) => {
                const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: d.month, val: d.net });
              }}
              onMouseLeave={() => setTip(null)}
            />
            {/* x 라벨 — 간격이 좁으면 짝수만 */}
            {(data.length <= 12 || i % 2 === 0) && (
              <text x={toX(i)} y={H - pad.bottom + 14} textAnchor="middle" fontSize={10} fill="#718096">
                {d.month.slice(5)}
              </text>
            )}
          </g>
        ))}

        {/* x축 연도 라벨 (좌측 끝에만) */}
        {data.length > 0 && (
          <text x={pad.left} y={H - 2} textAnchor="middle" fontSize={10} fill="#A0AEC0">
            {data[0].month.slice(0, 4)}
          </text>
        )}
      </svg>

      {tip && (
        <div style={{
          position: "absolute", left: tip.x + 8, top: tip.y - 28,
          background: "#fff", border: `1px solid ${BORDER}`,
          borderRadius: 6, padding: "6px 10px", fontSize: 12, pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", zIndex: 10,
        }}>
          <b>{tip.label}</b>: <span style={{ color: tip.val >= 0 ? "#276749" : "#C53030" }}>{fmt(tip.val)}원</span>
        </div>
      )}
    </div>
  );
}

// ── 연도별 월간추이 겹쳐보기 (1~12월 overlay) ─────────────────────────────
const YEAR_COLORS = ["#A0AEC0", "#4299E1", "#D4A843", "#48BB78", "#9F7AEA", "#ED64A6", "#F6AD55"];
type OverlayMetric = "sales" | "net" | "card" | "fixed" | "net_after_fixed";
const METRIC_LABEL: Record<OverlayMetric, string> = {
  sales: "매출", net: "순이익", card: "카드지출", fixed: "고정지출", net_after_fixed: "고정차감후 순이익",
};

function OverlayLineChart({
  seriesByYear, metric,
}: {
  seriesByYear: Record<string, YearlyMonthCell[]>; metric: OverlayMetric;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; label: string; val: number } | null>(null);
  const years = Object.keys(seriesByYear).sort();
  const W = 860, H = 260, pad = { top: 16, right: 24, bottom: 30, left: 64 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  if (years.length === 0) {
    return <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>데이터 없음</div>;
  }

  const allVals = years.flatMap((y) => seriesByYear[y].map((c) => Number(c[metric] ?? 0)));
  const maxV = Math.max(...allVals, 1);
  const minV = Math.min(...allVals, 0);
  const range = maxV - minV || 1;
  const toX = (m: number) => pad.left + ((m - 1) / 11) * innerW;
  const toY = (v: number) => pad.top + innerH - ((v - minV) / range) * innerH;
  const yTicks = [minV, (minV + maxV) / 2, maxV];

  return (
    <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 400 }}>
        {yTicks.map((v, i) => {
          const y = toY(v);
          return (
            <g key={i}>
              <line x1={pad.left} x2={W - pad.right} y1={y} y2={y} stroke="#EDF2F7" strokeWidth={1} strokeDasharray="4,4" />
              <text x={pad.left - 6} y={y + 4} textAnchor="end" fontSize={10} fill="#A0AEC0">{manAxis(v)}</text>
            </g>
          );
        })}
        {minV < 0 && maxV > 0 && (
          <line x1={pad.left} x2={W - pad.right} y1={toY(0)} y2={toY(0)} stroke="#CBD5E0" strokeWidth={1.5} />
        )}
        {/* x축 월 라벨 */}
        {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
          <text key={m} x={toX(m)} y={H - pad.bottom + 16} textAnchor="middle" fontSize={10} fill="#718096">{m}월</text>
        ))}
        {/* 연도별 라인 */}
        {years.map((y, yi) => {
          const color = YEAR_COLORS[yi % YEAR_COLORS.length];
          const cells = seriesByYear[y];
          const pts = cells.map((c) => `${toX(c.month)},${toY(Number(c[metric] ?? 0))}`).join(" ");
          return (
            <g key={y}>
              <polyline points={pts} fill="none" stroke={color} strokeWidth={2.2} strokeLinejoin="round" opacity={0.9} />
              {cells.map((c) => (
                <circle key={c.month} cx={toX(c.month)} cy={toY(Number(c[metric] ?? 0))} r={8} fill="transparent"
                  onMouseMove={(e) => {
                    const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: `${y}년 ${c.month}월`, val: Number(c[metric] ?? 0) });
                  }}
                  onMouseLeave={() => setTip(null)} />
              ))}
            </g>
          );
        })}
      </svg>
      {/* 범례 */}
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", justifyContent: "center", marginTop: 6 }}>
        {years.map((y, yi) => (
          <span key={y} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#4A5568" }}>
            <span style={{ width: 16, height: 3, background: YEAR_COLORS[yi % YEAR_COLORS.length], display: "inline-block", borderRadius: 2 }} />
            {y}년 {METRIC_LABEL[metric]}
          </span>
        ))}
      </div>
      {tip && (
        <div style={{
          position: "absolute", left: tip.x + 8, top: tip.y - 28,
          background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 6,
          padding: "6px 10px", fontSize: 12, pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", zIndex: 10,
        }}>
          <b>{tip.label}</b>: <span style={{ color: tip.val >= 0 ? "#276749" : "#C53030" }}>{man(tip.val)}</span>
        </div>
      )}
    </div>
  );
}

// ── 전년 대비 증감 배지 ────────────────────────────────────────────────────
function DeltaBadge({ cur, prev }: { cur: number; prev: number }) {
  if (!prev) return <span style={{ fontSize: 11, color: "#A0AEC0" }}>—</span>;
  const p = Math.round(((cur - prev) / Math.abs(prev)) * 1000) / 10;
  const up = p >= 0;
  return (
    <span style={{ fontSize: 11, fontWeight: 700, color: up ? "#276749" : "#C53030" }}>
      {up ? "▲" : "▼"} {Math.abs(p)}%
    </span>
  );
}

// ── 고정지출 / 신고·부가세 (PG 전용) ──────────────────────────────────────
const FIXED_CATS = ["임대료", "통신비", "구독료", "광고비", "세무기장", "렌탈", "보험", "기타"];
const PAY_METHODS = ["카드", "계좌", "현금"];
const fieldStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", padding: "6px 8px",
  border: `1px solid ${BORDER}`, borderRadius: 6, fontSize: 12,
};
function num(v: unknown): number {
  const n = parseInt(String(v ?? "").replace(/,/g, "").trim() || "0", 10);
  return Number.isFinite(n) ? n : 0;
}
function ymInt(s: string | undefined): number | null {
  const t = String(s || "").trim();
  if (t.length < 7) return null;
  const y = Number(t.slice(0, 4)), m = Number(t.slice(5, 7));
  return y && m ? y * 12 + m : null;
}
function isEffective(r: FixedExpense, y: number, m: number): boolean {
  const target = y * 12 + m;
  if (r.is_recurring) {
    const start = ymInt(r.start_month) || ymInt(r.year_month);
    const end = ymInt(r.end_month);
    return start != null && start <= target && (end == null || target <= end);
  }
  return ymInt(r.year_month) === target;
}
function PgNeeded() {
  return (
    <div style={{ fontSize: 13, color: "#A0AEC0", padding: "8px 0" }}>
      이 기능은 PG 모드(FEATURE_PG_DAILY)에서만 사용할 수 있습니다.
    </div>
  );
}

function FixedExpensePanel({ year, month, pgOn }: { year: number; month: number; pgOn: boolean }) {
  const qc = useQueryClient();
  const ym = `${year}-${String(month).padStart(2, "0")}`;
  // 선택월 유효 규칙(매월 자동 반영) — effective_month 기준
  const { data: monthRows = [] } = useQuery({
    queryKey: ["fixed-expenses", "effective", ym],
    queryFn: () => dailyApi.listFixedExpenses({ effective_month: ym }).then((r) => r.data),
    enabled: pgOn,
  });
  // 연 합계 계산용 전체 규칙
  const { data: allRules = [] } = useQuery({
    queryKey: ["fixed-expenses", "all"],
    queryFn: () => dailyApi.listFixedExpenses({}).then((r) => r.data),
    enabled: pgOn,
  });
  const [form, setForm] = useState<Partial<FixedExpense>>({ category: "임대료", payment_method: "계좌" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const reset = () => { setForm({ category: "임대료", payment_method: "계좌" }); setEditingId(null); };
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["fixed-expenses"] });
    qc.invalidateQueries({ queryKey: ["yearly-overview"] });
  };
  const saveMut = useMutation({
    mutationFn: () => {
      // year_month=선택월. 신규=반복 규칙으로 생성, 수정=선택월 기준(금액 변경 시 백엔드 term-out)
      const payload: Partial<FixedExpense> = { ...form, year_month: ym, amount: num(form.amount) };
      return editingId ? dailyApi.updateFixedExpense(editingId, payload) : dailyApi.createFixedExpense(payload);
    },
    onSuccess: () => { toast.success("저장됨"); reset(); invalidate(); },
    onError: () => toast.error("저장 실패"),
  });
  // 삭제 = 선택월부터 중단(과거 보존). effective_month 전달.
  const delMut = useMutation({
    mutationFn: (id: string) => dailyApi.deleteFixedExpense(id, ym),
    onSuccess: () => { toast.success("이 달부터 중단됨"); invalidate(); },
    onError: () => toast.error("중단 실패"),
  });

  if (!pgOn) return <Card title="💼 고정지출 관리"><PgNeeded /></Card>;

  const monthTotal = monthRows.reduce((s, r) => s + (r.amount || 0), 0);
  // 연 합계 = 1~12월 각 월 유효 규칙 금액의 합
  let yearTotal = 0;
  for (let m = 1; m <= 12; m++) {
    yearTotal += allRules.filter((r) => isEffective(r, year, m)).reduce((s, r) => s + (r.amount || 0), 0);
  }
  const byCat: Record<string, number> = {};
  monthRows.forEach((r) => { byCat[r.category || "기타"] = (byCat[r.category || "기타"] || 0) + (r.amount || 0); });

  return (
    <Card title={`💼 고정지출 관리 (${ym} · 매월 자동 반영)`}>
      <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 10 }}>
        ※ 한 번 입력하면 이후 모든 달에 자동 반영됩니다. 특정 월부터 금액을 바꾸면 그 달부터 새 금액이 적용되고 과거 월은 유지됩니다. ‘삭제’는 이 달부터 중단입니다.
      </div>
      {/* 입력 폼 */}
      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr 0.8fr 1.4fr auto", gap: 6, alignItems: "center", marginBottom: 12 }}>
        <input style={fieldStyle} placeholder="항목 (예: 사무실 월세)" value={form.name ?? ""} onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} />
        <select style={fieldStyle} value={form.category ?? "임대료"} onChange={(e) => setForm((p) => ({ ...p, category: e.target.value }))}>
          {FIXED_CATS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select style={fieldStyle} value={form.payment_method ?? "계좌"} onChange={(e) => setForm((p) => ({ ...p, payment_method: e.target.value }))}>
          {PAY_METHODS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" placeholder="금액(원)" value={form.amount ?? ""} onChange={(e) => setForm((p) => ({ ...p, amount: num(e.target.value) }))} />
        <label style={{ fontSize: 11, color: "#4A5568", display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={!!form.vat_included} onChange={(e) => setForm((p) => ({ ...p, vat_included: e.target.checked }))} /> VAT포함
        </label>
        <input style={fieldStyle} placeholder="메모" value={form.memo ?? ""} onChange={(e) => setForm((p) => ({ ...p, memo: e.target.value }))} />
        <div style={{ display: "flex", gap: 4 }}>
          <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending || !(form.name || "").trim()} className="btn-primary" style={{ fontSize: 12, padding: "6px 12px", whiteSpace: "nowrap" }}>
            {editingId ? "수정" : "추가"}
          </button>
          {editingId && <button onClick={reset} style={{ fontSize: 12, padding: "6px 10px", border: `1px solid ${BORDER}`, borderRadius: 6, background: "#fff", cursor: "pointer" }}>취소</button>}
        </div>
      </div>

      {/* 목록 */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: GRAY_BG }}>
              {["항목", "카테고리", "결제", "금액", "VAT", "메모", ""].map((h, i) => (
                <th key={h + i} style={{ padding: "7px 8px", textAlign: i === 3 ? "right" : "left", fontWeight: 700, color: "#4A5568", borderBottom: `2px solid ${BORDER}` }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {monthRows.length === 0 ? (
              <tr><td colSpan={7} style={{ textAlign: "center", padding: 16, color: "#A0AEC0" }}>이 달 유효한 고정지출이 없습니다.</td></tr>
            ) : monthRows.map((r) => (
              <tr key={r.id}>
                <td style={{ padding: "6px 8px", borderBottom: `1px solid ${BORDER}` }}>{r.name}</td>
                <td style={{ padding: "6px 8px", borderBottom: `1px solid ${BORDER}`, color: "#718096" }}>{r.category}</td>
                <td style={{ padding: "6px 8px", borderBottom: `1px solid ${BORDER}`, color: "#718096" }}>{r.payment_method}</td>
                <td title={`${fmt(r.amount)}원`} style={{ padding: "6px 8px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600 }}>{man(r.amount)}</td>
                <td style={{ padding: "6px 8px", borderBottom: `1px solid ${BORDER}`, color: "#A0AEC0" }}>{r.vat_included ? "포함" : "-"}</td>
                <td style={{ padding: "6px 8px", borderBottom: `1px solid ${BORDER}`, color: "#718096" }}>{r.memo}</td>
                <td style={{ padding: "6px 8px", borderBottom: `1px solid ${BORDER}`, whiteSpace: "nowrap" }}>
                  <button onClick={() => { setEditingId(r.id); setForm(r); }} style={{ fontSize: 11, marginRight: 6, border: "none", background: "none", color: "#3182CE", cursor: "pointer" }}>수정</button>
                  <button onClick={() => { if (confirm(`${ym}부터 이 고정지출을 중단합니다. (과거 월은 유지)`)) delMut.mutate(r.id); }} style={{ fontSize: 11, border: "none", background: "none", color: "#C53030", cursor: "pointer" }}>중단</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 합계 */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginTop: 12, fontSize: 13 }}>
        <span><b>선택월 합계</b> <span style={{ color: "#C53030", fontWeight: 700 }}>{man(monthTotal)}</span></span>
        <span><b>{year}년 합계</b> <span style={{ color: "#C53030", fontWeight: 700 }}>{man(yearTotal)}</span></span>
        <span style={{ display: "flex", gap: 8, flexWrap: "wrap", color: "#718096", fontSize: 12 }}>
          {Object.entries(byCat).map(([c, v]) => <span key={c}>{c} {man(v)}</span>)}
        </span>
      </div>
    </Card>
  );
}

function TaxReportPanel({ year, month, pgOn, autoReportedSales = 0 }: { year: number; month: number; pgOn: boolean; autoReportedSales?: number }) {
  const qc = useQueryClient();
  const ym = `${year}-${String(month).padStart(2, "0")}`;
  const { data } = useQuery({
    queryKey: ["tax-summary", ym],
    queryFn: () => dailyApi.getTaxSummary(ym).then((r) => r.data),
    enabled: pgOn,
  });
  const [f, setF] = useState<Partial<TaxSummary>>({ vat_basis: "tax_included" });
  useEffect(() => {
    const d = data as TaxSummary | undefined;
    setF(d && d.year_month ? d : { vat_basis: "tax_included" });
  }, [data, ym]);
  const saveMut = useMutation({
    mutationFn: () => dailyApi.saveTaxSummary({ ...f, year_month: ym }),
    onSuccess: () => { toast.success("저장됨"); qc.invalidateQueries({ queryKey: ["tax-summary"] }); qc.invalidateQueries({ queryKey: ["yearly-overview"] }); },
    onError: () => toast.error("저장 실패"),
  });

  if (!pgOn) return <Card title="🧾 신고 기준 / 부가세"><PgNeeded /></Card>;

  const basis = f.vat_basis || "tax_included";
  // 자동(카드수입+세금계산서) + 수동 조정 = 합계 신고매출. 부가세는 합계 기준.
  const manualSales = num(f.reported_revenue);
  const totalSales = autoReportedSales + manualSales;
  const vatOf = (amt: number) => basis === "supply_price" ? Math.round(amt * 0.1) : amt - Math.round(amt / 1.1);
  const supplyOf = (amt: number) => basis === "supply_price" ? amt : Math.round(amt / 1.1);
  const outVat = num(f.reported_output_vat) || vatOf(totalSales);
  const inVat = num(f.reported_input_vat) || vatOf(num(f.reported_expense));
  const supply = supplyOf(totalSales);
  const expected = outVat - inVat;
  const cell: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 4 };
  const lbl: React.CSSProperties = { fontSize: 11, color: "#718096" };

  return (
    <Card title="🧾 신고 기준 / 부가세">
      <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 12 }}>
        ※ 일반과세 10% 기준 <b>관리용 예상 계산</b>입니다. 실제 신고 확정값과 다를 수 있습니다.
        자동 신고매출 = 일일결산의 <b>카드수입 + 세금계산서 발행 체크 수입</b> (행당 1회).
      </div>

      {/* 신고매출 구성 요약 */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginBottom: 12, padding: "10px 14px", background: "#EBF8FF", border: "1px solid #BEE3F8", borderRadius: 8, fontSize: 13 }}>
        <span>① 자동 신고매출 <b title={`${fmt(autoReportedSales)}원`}>{man(autoReportedSales)}</b></span>
        <span style={{ color: "#CBD5E0" }}>+</span>
        <span>② 수동 추가/조정 <b title={`${fmt(manualSales)}원`}>{man(manualSales)}</b></span>
        <span style={{ color: "#CBD5E0" }}>=</span>
        <span>③ 합계 신고매출 <b style={{ color: "#2B6CB0" }} title={`${fmt(totalSales)}원`}>{man(totalSales)}</b></span>
        <span style={{ color: "#CBD5E0" }}>·</span>
        <span>예상 공급가액 <b title={`${fmt(supply)}원`}>{man(supply)}</b></span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        <div style={cell}>
          <span style={lbl}>부가세 기준</span>
          <select style={fieldStyle} value={basis} onChange={(e) => setF((p) => ({ ...p, vat_basis: e.target.value as TaxSummary["vat_basis"] }))}>
            <option value="tax_included">공급대가(부가세 포함) 입력</option>
            <option value="supply_price">공급가액 입력</option>
          </select>
        </div>
        <div style={cell}>
          <span style={lbl}>수동 추가/조정 신고매출 (원)</span>
          <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" value={f.reported_revenue ?? ""} onChange={(e) => setF((p) => ({ ...p, reported_revenue: num(e.target.value) }))} />
        </div>
        <div style={cell}>
          <span style={lbl}>신고 매입/지출액 (원)</span>
          <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" value={f.reported_expense ?? ""} onChange={(e) => setF((p) => ({ ...p, reported_expense: num(e.target.value) }))} />
        </div>
        <div style={cell}>
          <span style={lbl}>매출세액 (비우면 합계 기준 자동)</span>
          <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" placeholder={`자동 ${fmt(vatOf(totalSales))}`} value={f.reported_output_vat ?? ""} onChange={(e) => setF((p) => ({ ...p, reported_output_vat: num(e.target.value) }))} />
        </div>
        <div style={cell}>
          <span style={lbl}>매입세액 (비우면 자동)</span>
          <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" placeholder={`자동 ${fmt(vatOf(num(f.reported_expense)))}`} value={f.reported_input_vat ?? ""} onChange={(e) => setF((p) => ({ ...p, reported_input_vat: num(e.target.value) }))} />
        </div>
        <div style={cell}>
          <span style={lbl}>신고 메모</span>
          <input style={fieldStyle} value={f.memo ?? ""} onChange={(e) => setF((p) => ({ ...p, memo: e.target.value }))} />
        </div>
      </div>
      {/* 예상 계산 결과 */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 16, alignItems: "center", marginTop: 14, padding: "10px 14px", background: GRAY_BG, borderRadius: 8, fontSize: 13 }}>
        <span>매출세액 <b title={`${fmt(outVat)}원`}>{man(outVat)}</b></span>
        <span>매입세액 <b title={`${fmt(inVat)}원`}>{man(inVat)}</b></span>
        <span>예상 납부 부가세 <b style={{ color: expected >= 0 ? "#C53030" : "#276749" }} title={`${fmt(expected)}원`}>{man(expected)}</b></span>
        <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} className="btn-primary" style={{ fontSize: 12, padding: "6px 16px", marginLeft: "auto" }}>저장</button>
      </div>
    </Card>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────
export default function MonthlyPage() {
  const now = new Date();
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  const [year, setYear]   = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const [overlayMetric, setOverlayMetric] = useState<OverlayMetric>("sales");

  const { data, isLoading, isError } = useQuery<AnalysisData>({
    queryKey: ["monthly-analysis", year, month],
    queryFn:  () => dailyApi.getMonthlyAnalysis(year, month).then((r) => r.data),
    staleTime: 60_000,
  });

  // 고도화: 연도 overlay + 동월/동분기/YTD 비교 + 자동진단 (단일 API)
  const { data: overview } = useQuery<YearlyOverview>({
    queryKey: ["yearly-overview", year, month],
    queryFn:  () => dailyApi.getYearlyOverview(year, month).then((r) => r.data),
    staleTime: 60_000,
  });

  const yearOptions = useMemo(() => {
    const years = new Set([now.getFullYear()]);
    (data?.summary_table ?? []).forEach((r) => years.add(parseInt(r.month.slice(0, 4))));
    return Array.from(years).sort((a, b) => b - a);
  }, [data]);

  const selectedLabel = `${year}년 ${month}월`;

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto" }}>

      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "#1A202C", margin: 0 }}>📊 월간결산</h1>
          <p style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>월별 수입·지출 분석 및 추세</p>
        </div>

        {/* 월 선택기 */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ fontSize: 13, color: "#4A5568", fontWeight: 600 }}>🔎 분석할 월:</label>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))}
            style={{ padding: "8px 12px", border: `1px solid ${BORDER}`, borderRadius: 8, fontSize: 14, background: "#fff", cursor: "pointer" }}>
            {yearOptions.map((y) => <option key={y} value={y}>{y}년</option>)}
          </select>
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))}
            style={{ padding: "8px 12px", border: `1px solid ${BORDER}`, borderRadius: 8, fontSize: 14, background: "#fff", cursor: "pointer" }}>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
              <option key={m} value={m}>{m}월</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && (
        <div style={{ textAlign: "center", padding: 60, color: "#718096", fontSize: 14 }}>
          데이터를 불러오는 중...
        </div>
      )}

      {isError && (
        <div style={{ padding: 20, background: "#FFF5F5", border: "1px solid #FEB2B2", borderRadius: 8, color: "#C53030", fontSize: 14 }}>
          데이터 로드 실패. 서버 연결을 확인해주세요.
        </div>
      )}

      {overview && (() => {
        const cur  = overview.same_month.find((r) => r.year === year);
        const prev = overview.same_month.find((r) => r.year === year - 1);
        const pgOn = !!overview.pg_daily;
        const curRate = cur && cur.sales ? Math.round(((cur.net_after_fixed ?? cur.net) / cur.sales) * 1000) / 10 : 0;
        const prevRate = prev && prev.sales ? Math.round(((prev.net_after_fixed ?? prev.net) / prev.sales) * 1000) / 10 : 0;
        type Kpi = { label: string; val: number; prev: number; kind: "money" | "count" | "pct" };
        const kpis: Kpi[] = [
          { label: "매출",        val: cur?.sales ?? 0,   prev: prev?.sales ?? 0,   kind: "money" },
          { label: "순이익",      val: cur?.net ?? 0,     prev: prev?.net ?? 0,     kind: "money" },
          { label: "지출",        val: cur?.expense ?? 0, prev: prev?.expense ?? 0, kind: "money" },
          { label: "카드지출",    val: cur?.card ?? 0,    prev: prev?.card ?? 0,    kind: "money" },
          { label: "건수",        val: cur?.count ?? 0,   prev: prev?.count ?? 0,   kind: "count" },
          { label: "평균 객단가", val: cur?.avg ?? 0,     prev: prev?.avg ?? 0,     kind: "money" },
          ...(pgOn ? [
            { label: "고정지출",        val: cur?.fixed ?? 0,            prev: prev?.fixed ?? 0,            kind: "money" as const },
            { label: "고정차감후 순이익", val: cur?.net_after_fixed ?? 0,  prev: prev?.net_after_fixed ?? 0,  kind: "money" as const },
            { label: "순이익률",        val: curRate,                    prev: prevRate,                    kind: "pct" as const },
          ] : []),
        ];
        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 20, marginBottom: 20 }}>
            {/* 핵심 KPI */}
            <Card title={`🎯 ${selectedLabel} 핵심 지표 (전년 동월 대비)`}>
              <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(6, 1fr)", gap: 12 }}>
                {kpis.map((k) => (
                  <div key={k.label} style={{ background: GRAY_BG, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "12px 14px" }}>
                    <div style={{ fontSize: 11, color: "#718096", marginBottom: 6 }}>{k.label}</div>
                    <div title={k.kind === "money" ? `${fmt(k.val)}원` : undefined} style={{ fontSize: 17, fontWeight: 800, color: "#1A202C" }}>
                      {k.kind === "money" ? man(k.val) : k.kind === "pct" ? `${k.val}%` : `${fmt(k.val)}건`}
                    </div>
                    {k.kind !== "pct" && <div style={{ marginTop: 4 }}><DeltaBadge cur={k.val} prev={k.prev} /></div>}
                    {k.kind === "pct" && <div style={{ marginTop: 4, fontSize: 11, color: "#A0AEC0" }}>전년 {k.prev}%</div>}
                  </div>
                ))}
              </div>
            </Card>

            {/* 연도별 월간 추이 겹쳐보기 */}
            <Card title="📈 연도별 월간 추이 (1~12월 겹쳐보기)">
              <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
                {((overview.pg_daily
                  ? ["sales", "net", "card", "fixed", "net_after_fixed"]
                  : ["sales", "net", "card"]) as OverlayMetric[]).map((mk) => (
                  <button key={mk} onClick={() => setOverlayMetric(mk)} style={{
                    padding: "5px 14px", borderRadius: 999, fontSize: 12, cursor: "pointer", fontWeight: 600,
                    border: `1.5px solid ${overlayMetric === mk ? GOLD : BORDER}`,
                    background: overlayMetric === mk ? GOLD : "#fff",
                    color: overlayMetric === mk ? "#fff" : "#4A5568",
                  }}>{METRIC_LABEL[mk]}</button>
                ))}
              </div>
              <OverlayLineChart seriesByYear={overview.monthly_by_year} metric={overlayMetric} />
            </Card>

            {/* 동월 / 동분기 / YTD 비교 */}
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr 1fr", gap: 20 }}>
              {([
                { title: `📆 동월 비교 (${month}월)`, rows: overview.same_month },
                { title: `🗓 동분기 비교 (Q${overview.selected.quarter})`, rows: overview.same_quarter },
                { title: `📊 YTD 비교 (1~${month}월)`, rows: overview.ytd },
              ] as const).map((blk) => (
                <Card key={blk.title} title={blk.title}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: GRAY_BG }}>
                        {["연도", "매출", "순이익", "건수"].map((h) => (
                          <th key={h} style={{ padding: "7px 8px", textAlign: h === "연도" ? "left" : "right", fontWeight: 700, color: "#4A5568", borderBottom: `2px solid ${BORDER}` }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {blk.rows.map((r) => (
                        <tr key={r.year} style={{ background: r.year === year ? GOLD_LIGHT : "transparent" }}>
                          <td style={{ padding: "7px 8px", borderBottom: `1px solid ${BORDER}`, fontWeight: r.year === year ? 700 : 400, color: r.year === year ? GOLD : "#2D3748" }}>{r.year}</td>
                          <td title={`${fmt(r.sales)}원`} style={{ padding: "7px 8px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{man(r.sales)}</td>
                          <td title={`${fmt(r.net)}원`} style={{ padding: "7px 8px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: r.net >= 0 ? "#276749" : "#C53030" }}>{man(r.net)}</td>
                          <td style={{ padding: "7px 8px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{fmt(r.count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              ))}
            </div>

            {/* 업무군 증감 (선택월 vs 전년 동월) */}
            {overview.category_compare.length > 0 && (
              <Card title={`🗂 업무군별 증감 (${month}월 · 전년 동월 대비)`}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: GRAY_BG }}>
                      {["업무군", "올해", "전년", "증감"].map((h) => (
                        <th key={h} style={{ padding: "8px 10px", textAlign: h === "업무군" ? "left" : "right", fontWeight: 700, color: "#4A5568", borderBottom: `2px solid ${BORDER}` }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {overview.category_compare.map((c) => (
                      <tr key={c.name}>
                        <td style={{ padding: "7px 10px", borderBottom: `1px solid ${BORDER}`, color: "#2D3748" }}>{c.name}</td>
                        <td title={`${fmt(c.cur)}원`} style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{man(c.cur)}</td>
                        <td title={`${fmt(c.prev)}원`} style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#A0AEC0" }}>{man(c.prev)}</td>
                        <td style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 700, color: c.delta >= 0 ? "#276749" : "#C53030" }}>
                          {c.delta >= 0 ? "+" : ""}{man(c.delta)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}

            {/* 자동 진단 */}
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
              <Card title="✅ 잘한 부분">
                {overview.diagnosis.good.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#A0AEC0" }}>전년 동기 데이터가 부족합니다.</div>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {overview.diagnosis.good.map((g, i) => (
                      <li key={i} style={{ fontSize: 13, color: "#276749" }}>{g}</li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="⚠️ 부족한 부분">
                {overview.diagnosis.bad.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#A0AEC0" }}>특이 하락 항목이 없습니다.</div>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {overview.diagnosis.bad.map((b, i) => (
                      <li key={i} style={{ fontSize: 13, color: "#C53030" }}>{b}</li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>

            {/* 고정지출 관리 + 신고/부가세 (PG 전용) */}
            <FixedExpensePanel year={year} month={month} pgOn={!!overview.pg_daily} />
            <TaxReportPanel year={year} month={month} pgOn={!!overview.pg_daily} autoReportedSales={overview.tax?.auto_reported_sales ?? 0} />
          </div>
        );
      })()}

      {data && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

          {/* ① 월별 요약 테이블 */}
          <Card title="📋 전체 월별 요약">
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ background: GRAY_BG }}>
                    {["월", "현금입금", "기타입금", "현금지출", "기타지출", "순수익"].map((h) => (
                      <th key={h} style={{
                        padding: "10px 12px",
                        textAlign: h === "월" ? "left" : "right",
                        fontWeight: 700, color: "#4A5568",
                        borderBottom: `2px solid ${BORDER}`,
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.summary_table.length === 0 ? (
                    <tr><td colSpan={6} style={{ textAlign: "center", padding: 20, color: "#A0AEC0" }}>데이터 없음</td></tr>
                  ) : data.summary_table.map((row) => {
                    const isSelected = row.month === `${year}-${String(month).padStart(2, "0")}`;
                    return (
                      <tr key={row.month}
                        style={{ background: isSelected ? GOLD_LIGHT : "transparent", cursor: "pointer" }}
                        onClick={() => { const [y, m] = row.month.split("-"); setYear(Number(y)); setMonth(Number(m)); }}
                      >
                        <td style={{ padding: "9px 12px", borderBottom: `1px solid ${BORDER}`, fontWeight: isSelected ? 700 : 400, color: isSelected ? GOLD : "#2D3748" }}>
                          {row.month}
                        </td>
                        {[row.income_cash, row.income_etc, row.exp_cash, row.exp_etc].map((v, i) => (
                          <td key={i} title={`${fmt(v)}원`} style={{ padding: "9px 12px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{man(v)}</td>
                        ))}
                        <td title={`${fmt(row.net)}원`} style={{ padding: "9px 12px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 700, color: row.net >= 0 ? "#276749" : "#C53030" }}>
                          {man(row.net)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* ② 월별 순수익 추세 라인 차트 */}
          <Card title="📈 월별 순수익 추세">
            <LineChartSVG data={data.trend} />
          </Card>

          {/* ③④ 요일별 + 카테고리별 — 모바일 1컬럼 */}
          <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
            <Card title={`📅 ${selectedLabel} 요일별 순수익`}>
              {data.dow.every((d) => d.net === 0) ? (
                <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>해당 월 데이터 없음</div>
              ) : (
                <BarChartV data={data.dow} xKey="name" yKey="net" color={BLUE} height={200} />
              )}
            </Card>

            <Card title={`🗂 ${selectedLabel} 카테고리별 순수익`}>
              {data.category.length === 0 ? (
                <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>해당 월 데이터 없음</div>
              ) : (
                <BarChartH data={data.category} height={Math.max(200, data.category.slice(0, 10).length * 28 + 40)} />
              )}
            </Card>
          </div>

          {/* ⑤ 시간대별 순수익 */}
          <Card title={`⏰ ${selectedLabel} 시간대별 순수익`}>
            {data.hour.length === 0 ? (
              <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>해당 월 데이터 없음</div>
            ) : (
              <BarChartV data={data.hour} xKey="hour" yKey="net" color={GOLD} height={200} />
            )}
          </Card>

        </div>
      )}
    </div>
  );
}
