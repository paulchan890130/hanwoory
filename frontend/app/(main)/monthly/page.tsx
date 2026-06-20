"use client";
import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { dailyApi, type YearlyOverview, type YearlyMonthCell, type FixedExpense, type TaxSummary, type DailyPoint } from "@/lib/api";
import { formatManwon, formatNumber } from "@/lib/utils";
import { getUser } from "@/lib/auth";

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

// ── 월별 일간 추이 (작년 동월 겹쳐보기) ─────────────────────────────────────
// 올해 선택월 vs 전년 동월을 같은 일자축(1~말일)에 겹쳐 그린다. 일별/누계 토글, 기준일 라인.
function DailyOverlayChart({
  data, metric, mode, refDay, curYear,
}: {
  data: DailyPoint[]; metric: "sales" | "net"; mode: "cum" | "daily"; refDay: number; curYear: number;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; label: string; val: number } | null>(null);
  const W = 860, H = 260, pad = { top: 16, right: 24, bottom: 30, left: 64 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;

  if (!data.length) {
    return <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>데이터 없음</div>;
  }

  const curField = (mode === "cum"
    ? (metric === "sales" ? "cur_cum_sales" : "cur_cum_net")
    : (metric === "sales" ? "cur_sales" : "cur_net")) as keyof DailyPoint;
  const prevField = (mode === "cum"
    ? (metric === "sales" ? "prev_cum_sales" : "prev_cum_net")
    : (metric === "sales" ? "prev_sales" : "prev_net")) as keyof DailyPoint;

  const n = data.length;
  const curVals = data.map((d) => d[curField] as number | null);
  const prevVals = data.map((d) => d[prevField] as number);
  const nums = [...(curVals.filter((v) => v != null) as number[]), ...prevVals, 0];
  const maxV = Math.max(...nums, 1), minV = Math.min(...nums, 0);
  const range = maxV - minV || 1;
  const toX = (i: number) => pad.left + (i / Math.max(n - 1, 1)) * innerW;
  const toY = (v: number) => pad.top + innerH - ((v - minV) / range) * innerH;
  const yTicks = [minV, (minV + maxV) / 2, maxV];

  const curPts = data
    .map((d, i) => ({ i, v: d[curField] as number | null }))
    .filter((o) => o.v != null)
    .map((o) => `${toX(o.i)},${toY(o.v as number)}`)
    .join(" ");
  const prevPts = data.map((d, i) => `${toX(i)},${toY(d[prevField] as number)}`).join(" ");
  const refX = toX(Math.max(refDay - 1, 0));

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
        {/* 기준일 라인 */}
        <line x1={refX} x2={refX} y1={pad.top} y2={H - pad.bottom} stroke="#F6AD55" strokeWidth={1.2} strokeDasharray="3,3" />
        <text x={refX} y={pad.top - 4} textAnchor="middle" fontSize={9} fill="#DD6B20">기준일 {refDay}일</text>
        {/* x축 일자 라벨(5일 간격 + 말일) */}
        {data.map((d, i) => (
          (d.day % 5 === 0 || d.day === 1 || d.day === n) && (
            <text key={d.day} x={toX(i)} y={H - pad.bottom + 16} textAnchor="middle" fontSize={9} fill="#718096">{d.day}</text>
          )
        ))}
        {/* 전년 라인 */}
        <polyline points={prevPts} fill="none" stroke="#A0AEC0" strokeWidth={2} strokeLinejoin="round" strokeDasharray="5,4" opacity={0.85} />
        {/* 올해 라인 */}
        <polyline points={curPts} fill="none" stroke={GOLD} strokeWidth={2.4} strokeLinejoin="round" />
        {/* 호버 포인트 */}
        {data.map((d, i) => {
          const cv = d[curField] as number | null;
          return (
            <g key={i}>
              {cv != null && (
                <circle cx={toX(i)} cy={toY(cv)} r={9} fill="transparent"
                  onMouseMove={(e) => {
                    const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: `${curYear}년 ${d.day}일`, val: cv });
                  }}
                  onMouseLeave={() => setTip(null)} />
              )}
            </g>
          );
        })}
      </svg>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", justifyContent: "center", marginTop: 6 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#4A5568" }}>
          <span style={{ width: 16, height: 3, background: GOLD, display: "inline-block", borderRadius: 2 }} />올해({curYear}년)
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#4A5568" }}>
          <span style={{ width: 16, height: 3, background: "#A0AEC0", display: "inline-block", borderRadius: 2 }} />전년({curYear - 1}년)
        </span>
      </div>
      {tip && (
        <div style={{
          position: "absolute", left: tip.x + 8, top: tip.y - 28,
          background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 6,
          padding: "6px 10px", fontSize: 12, pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", zIndex: 10,
        }}>
          <b>{tip.label}</b>: <span style={{ color: tip.val >= 0 ? "#276749" : "#C53030" }}>{fmt(tip.val)}원</span>
        </div>
      )}
    </div>
  );
}

// ── 그룹 막대 (시간대별 올해 vs 전년) ───────────────────────────────────────
function GroupedBarChart({
  data, curYear, height = 220,
}: {
  data: { label: string; cur: number; prev: number }[]; curYear: number; height?: number;
}) {
  const [tip, setTip] = useState<{ x: number; y: number; label: string; val: number } | null>(null);
  const W = 540, H = height, pad = { top: 16, right: 16, bottom: 34, left: 56 };
  const innerW = W - pad.left - pad.right, innerH = H - pad.top - pad.bottom;
  const maxV = Math.max(...data.flatMap((d) => [d.cur, d.prev]), 1);
  const gap = innerW / data.length;
  const barW = Math.max(6, (gap * 0.7) / 2);
  const toY = (v: number) => pad.top + innerH - (v / maxV) * innerH;

  return (
    <div style={{ position: "relative", width: "100%", overflowX: "auto" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", minWidth: 320 }}>
        {[0, 0.5, 1].map((f) => {
          const y = pad.top + innerH - f * innerH;
          return (
            <g key={f}>
              <line x1={pad.left} x2={W - pad.right} y1={y} y2={y} stroke="#EDF2F7" strokeWidth={1} />
              <text x={pad.left - 6} y={y + 4} textAnchor="end" fontSize={10} fill="#A0AEC0">{manAxis(maxV * f)}</text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const cx = pad.left + gap * i + gap / 2;
          const series = [
            { v: d.prev, x: cx - barW - 1, color: "#CBD5E0", who: `전년(${curYear - 1})` },
            { v: d.cur, x: cx + 1, color: BLUE, who: `올해(${curYear})` },
          ];
          return (
            <g key={i}>
              {series.map((s, si) => (
                <rect key={si} x={s.x} y={toY(s.v)} width={barW} height={Math.max(innerH - (toY(s.v) - pad.top), 2)}
                  fill={s.color} rx={2} opacity={0.9}
                  onMouseMove={(e) => {
                    const rect = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect();
                    setTip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label: `${d.label} ${s.who}`, val: s.v });
                  }}
                  onMouseLeave={() => setTip(null)} />
              ))}
              <text x={cx} y={H - pad.bottom + 14} textAnchor="middle" fontSize={10} fill="#718096">{d.label}</text>
            </g>
          );
        })}
      </svg>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", justifyContent: "center", marginTop: 4 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#4A5568" }}>
          <span style={{ width: 12, height: 12, background: BLUE, display: "inline-block", borderRadius: 2 }} />올해({curYear})
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#4A5568" }}>
          <span style={{ width: 12, height: 12, background: "#CBD5E0", display: "inline-block", borderRadius: 2 }} />전년({curYear - 1})
        </span>
      </div>
      {tip && (
        <div style={{
          position: "absolute", left: tip.x + 8, top: tip.y - 28,
          background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 6,
          padding: "6px 10px", fontSize: 12, pointerEvents: "none",
          boxShadow: "0 2px 8px rgba(0,0,0,0.12)", zIndex: 10,
        }}>
          <b>{tip.label}</b>: <span style={{ color: "#276749" }}>{fmt(tip.val)}원</span>
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

function TaxReportPanel({ year, month, pgOn, autoCardSales = 0, autoCardCount = 0 }: { year: number; month: number; pgOn: boolean; autoCardSales?: number; autoCardCount?: number }) {
  const qc = useQueryClient();
  const ym = `${year}-${String(month).padStart(2, "0")}`;
  const { data } = useQuery({
    queryKey: ["tax-summary", ym],
    queryFn: () => dailyApi.getTaxSummary(ym).then((r) => r.data),
    enabled: pgOn,
  });
  const [f, setF] = useState<Partial<TaxSummary>>({});
  useEffect(() => {
    const d = data as TaxSummary | undefined;
    setF(d && d.year_month ? d : {});
  }, [data, ym]);
  const saveMut = useMutation({
    mutationFn: () => dailyApi.saveTaxSummary({ ...f, year_month: ym }),
    onSuccess: () => { toast.success("저장됨"); qc.invalidateQueries({ queryKey: ["tax-summary"] }); qc.invalidateQueries({ queryKey: ["yearly-overview"] }); },
    onError: () => toast.error("저장 실패"),
  });

  if (!pgOn) return <Card title="🧾 신고 기준 / 부가세"><PgNeeded /></Card>;

  const d = data as TaxSummary | undefined;
  // 자동 카드매출/건수: tax-summary 응답이 우선(선택월 일일결산 기준), 없으면 overview prop fallback.
  const autoCard = Math.max(0, num(d?.auto_card_revenue ?? d?.auto_card_sales ?? autoCardSales));
  const autoCount = Math.max(0, num(d?.auto_card_count ?? autoCardCount));

  // 모든 입력은 공급대가(부가세 포함), 원 단위 정수, 음수 불허. 부가세 = 금액 − round(금액/1.1).
  const invoice = Math.max(0, num(f.manual_tax_invoice_revenue));
  const other = Math.max(0, num(f.manual_other_revenue));
  const cardExpense = Math.max(0, num(f.business_card_expense));
  const nonDeduct = Math.max(0, num(f.non_deductible_expense));

  const totalSales = autoCard + invoice + other;
  const deductible = Math.max(cardExpense - nonDeduct, 0);
  const vatOf = (amt: number) => (amt <= 0 ? 0 : amt - Math.round(amt / 1.1));
  const outVat = vatOf(totalSales);
  const inVat = vatOf(deductible);
  const expected = outVat - inVat;

  const cell: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 4 };
  const lbl: React.CSSProperties = { fontSize: 11, color: "#718096" };
  const roBox: React.CSSProperties = { ...fieldStyle, textAlign: "right", background: "#F7FAFC", color: "#2D3748", fontWeight: 600 };
  const hint: React.CSSProperties = { fontSize: 10.5, color: "#A0AEC0" };
  const secHead: React.CSSProperties = { fontSize: 12, fontWeight: 800, color: "#2D3748", marginBottom: 2 };
  const secBox: React.CSSProperties = { border: `1px solid ${BORDER}`, borderRadius: 8, padding: "12px 14px", display: "flex", flexDirection: "column", gap: 10 };
  const dRow: React.CSSProperties = { display: "flex", justifyContent: "space-between", fontSize: 13 };
  const clampSet = (key: keyof TaxSummary) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [key]: Math.max(0, num(e.target.value)) }));
  const won = (n: number) => `${fmt(n)}원`;

  return (
    <Card title="🧾 신고 기준 / 부가세 (대략 자동계산)">
      <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 12 }}>
        ※ 일반과세 10% 기준 <b>관리용 예상 계산판</b>입니다(실제 신고 확정값과 다를 수 있음). 모든 금액은 <b>공급대가(부가세 포함)</b> · 원 단위.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* A. 자동 매출 */}
        <div style={secBox}>
          <div style={secHead}>A. 자동 매출 <span style={{ fontWeight: 500, color: "#A0AEC0", fontSize: 10.5 }}>(수정 불가 · 일일결산 자동 합산)</span></div>
          <div style={{ fontSize: 14 }}>
            일일결산 카드매출 자동합계: <b style={{ color: "#2B6CB0" }} title={won(autoCard)}>{won(autoCard)}</b>
            <span style={{ color: "#718096" }}> / {autoCount}건</span>
          </div>
          {autoCount === 0 && (
            <div style={{ fontSize: 11.5, color: "#DD6B20", background: "#FFFAF0", border: "1px solid #FBD38D", borderRadius: 6, padding: "6px 10px" }}>
              선택한 월의 일일결산 중 결제수단이 카드인 수입 건이 없습니다. (현금·이체·인지 수입은 자동 카드매출에 포함되지 않습니다.)
            </div>
          )}
        </div>

        {/* B. 수동 매출 */}
        <div style={secBox}>
          <div style={secHead}>B. 수동 매출</div>
          <div style={cell}>
            <span style={lbl}>수동 세금계산서 매출액 (원)</span>
            <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" value={f.manual_tax_invoice_revenue ?? ""} onChange={clampSet("manual_tax_invoice_revenue")} />
            {invoice === 0 && <span style={hint}>필요 시 직접 입력 (외부 발행 세금계산서 분)</span>}
          </div>
          <div style={cell}>
            <span style={lbl}>기타 수동 조정 매출액 (원)</span>
            <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" value={f.manual_other_revenue ?? ""} onChange={clampSet("manual_other_revenue")} />
          </div>
          <span style={hint}>세금계산서 매출은 외부 발행분이 있을 수 있어 직접 입력합니다.</span>
        </div>

        {/* C. 매입 공제 */}
        <div style={secBox}>
          <div style={secHead}>C. 매입 공제</div>
          <div style={cell}>
            <span style={lbl}>사업용 카드 사용액 (원)</span>
            <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" value={f.business_card_expense ?? ""} onChange={clampSet("business_card_expense")} />
            {cardExpense === 0 && <span style={{ ...hint, color: "#DD6B20" }}>수동 입력 필요</span>}
          </div>
          <div style={cell}>
            <span style={lbl}>불공제/개인사용 제외액 (원)</span>
            <input style={{ ...fieldStyle, textAlign: "right" }} inputMode="numeric" value={f.non_deductible_expense ?? ""} onChange={clampSet("non_deductible_expense")} />
          </div>
          <div style={cell}>
            <span style={lbl}>공제 대상 매입액 (원, 자동)</span>
            <input style={roBox} value={won(deductible)} readOnly tabIndex={-1} />
          </div>
          <span style={hint}>자격사 업종은 매입이 많지 않으므로 월별 사업용 카드 사용액을 기준으로 대략 계산합니다.</span>
        </div>

        {/* D. 예상 부가세 */}
        <div style={{ ...secBox, background: "#EBF8FF", borderColor: "#BEE3F8" }}>
          <div style={secHead}>D. 예상 부가세</div>
          <div style={dRow}><span>신고 매출 합계</span><b title={won(totalSales)}>{won(totalSales)}</b></div>
          <div style={dRow}><span>매출세액</span><b title={won(outVat)}>{won(outVat)}</b></div>
          <div style={dRow}><span>매입세액</span><b title={won(inVat)}>{won(inVat)}</b></div>
          <div style={{ ...dRow, borderTop: "1px dashed #BEE3F8", paddingTop: 8 }}>
            <span>예상 납부 부가세</span>
            {expected >= 0
              ? <b style={{ color: "#C53030" }} title={won(expected)}>{won(expected)}</b>
              : <b style={{ color: "#276749" }} title={won(expected)}>환급/이월 가능성 ({won(expected)})</b>}
          </div>
        </div>
      </div>

      {/* 신고 메모 + 저장 */}
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginTop: 12 }}>
        <div style={{ ...cell, flex: 1 }}>
          <span style={lbl}>신고 메모</span>
          <input style={fieldStyle} value={f.memo ?? ""} onChange={(e) => setF((p) => ({ ...p, memo: e.target.value }))} />
        </div>
        <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending} className="btn-primary" style={{ fontSize: 12, padding: "8px 18px", whiteSpace: "nowrap" }}>저장</button>
      </div>

      {/* 자동계산식 */}
      <div style={{ marginTop: 12, fontSize: 10.5, color: "#A0AEC0", lineHeight: 1.7, background: GRAY_BG, borderRadius: 6, padding: "8px 12px" }}>
        <b>자동계산식</b><br />
        · 신고 매출 합계 = 일일결산 카드매출 자동합계 + 수동 세금계산서 매출 + 기타 조정 매출<br />
        · 매출세액 = 신고 매출 합계 × 10 / 110<br />
        · 공제 대상 매입액 = 사업용 카드 사용액 − 불공제/개인사용 제외액<br />
        · 매입세액 = 공제 대상 매입액 × 10 / 110<br />
        · 예상 납부 부가세 = 매출세액 − 매입세액 (음수면 환급/이월 가능성)
      </div>
    </Card>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────
export default function MonthlyPage() {
  const now = new Date();
  const [isMobile, setIsMobile] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    setIsAdmin(!!getUser()?.is_admin);   // 클라이언트에서만 읽어 hydration 불일치 방지
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);
  const [year, setYear]   = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);

  const [overlayMetric, setOverlayMetric] = useState<OverlayMetric>("net");
  // 월별 일간 추이(작년 동월 겹쳐보기) — 기본 누계/순수익이 실무적으로 유용
  const [dailyMetric, setDailyMetric] = useState<"sales" | "net">("net");
  const [dailyMode, setDailyMode] = useState<"cum" | "daily">("cum");
  // 연도별 월간 추이 표시 연도 필터(기본 최근 5년) — 데이터가 쌓여도 화면 단순 유지
  const [overlayYears, setOverlayYears] = useState<Set<number>>(new Set());
  const [overlayInit, setOverlayInit] = useState(false);
  // 연간 월별 요약 연도(기본 현재 연도)
  const [summaryYear, setSummaryYear] = useState(now.getFullYear());
  // 추가 비교(동월/동분기/YTD·업무군·요일) 접기/펼치기
  const [showExtra, setShowExtra] = useState(false);

  const { data, isLoading, isError } = useQuery<AnalysisData>({
    queryKey: ["monthly-analysis", year, month],
    queryFn:  () => dailyApi.getMonthlyAnalysis(year, month).then((r) => r.data),
    staleTime: 60_000,
  });

  // 고도화: 기준일 누계 비교 + 연도 overlay + 동월/동분기/YTD + 시간대 + 자동분석 (단일 API)
  const { data: overview } = useQuery<YearlyOverview>({
    queryKey: ["yearly-overview", year, month],
    queryFn:  () => dailyApi.getYearlyOverview(year, month).then((r) => r.data),
    staleTime: 60_000,
  });

  // overlay 표시 연도 초기화(최근 5년)
  useEffect(() => {
    if (overview && !overlayInit && overview.years.length) {
      const recent = [...overview.years].sort((a, b) => b - a).slice(0, 5);
      setOverlayYears(new Set(recent));
      setOverlayInit(true);
    }
  }, [overview, overlayInit]);

  const yearOptions = useMemo(() => {
    const years = new Set<number>([now.getFullYear()]);
    (overview?.years ?? []).forEach((y) => years.add(y));
    return Array.from(years).sort((a, b) => b - a);
  }, [overview, now]);

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
        const P = overview.period;
        const A = overview.analysis;
        const pad2 = (n: number) => String(n).padStart(2, "0");
        const rangeLabel = P
          ? `올해 ${year}-${pad2(month)}-01 ~ ${pad2(P.ref_day)}일 vs 전년 ${year - 1}-${pad2(month)}-01 ~ ${pad2(P.prev_ref_day)}일`
          : "";

        // ── 핵심 지표(기준일까지 누계 비교) ──
        type Kpi = { label: string; val: number; prev: number; kind: "money" | "count"; note?: string };
        const prevFull = overview.monthly_by_year[String(year - 1)]?.find((c) => c.month === month);
        const kpis: Kpi[] = P ? [
          { label: "누계 매출",      val: P.cur.sales,   prev: P.prev.sales,   kind: "money" },
          { label: "누계 순수익",    val: P.cur.net,     prev: P.prev.net,     kind: "money" },
          { label: "누계 지출",      val: P.cur.expense, prev: P.prev.expense, kind: "money" },
          { label: "건수",          val: P.cur.count,   prev: P.prev.count,   kind: "count" },
          { label: "일평균 매출",    val: P.avg_daily_sales, prev: P.prev_ref_day ? Math.round(P.prev.sales / P.prev_ref_day) : 0, kind: "money" },
          { label: "일평균 순수익",  val: P.avg_daily_net,   prev: P.prev_ref_day ? Math.round(P.prev.net / P.prev_ref_day) : 0,   kind: "money" },
        ] : [];

        // ── 연간 월별 요약(선택연도 1~12월) ──
        const curYearCells = overview.monthly_by_year[String(summaryYear)] ?? [];
        const prevYearCells = overview.monthly_by_year[String(summaryYear - 1)] ?? [];
        const cellOf = (cells: YearlyMonthCell[], m: number) => cells.find((c) => c.month === m);
        const rate = (c: number, p: number) => (!p ? null : Math.round(((c - p) / Math.abs(p)) * 1000) / 10);

        // ── overlay(연도별 월간 추이) 표시 연도 필터링 ──
        const overlaySeries: Record<string, YearlyMonthCell[]> = {};
        Object.keys(overview.monthly_by_year)
          .filter((y) => overlayYears.has(Number(y)))
          .forEach((y) => { overlaySeries[y] = overview.monthly_by_year[y]; });

        const hc = overview.hour_compare ?? [];

        return (
          <div style={{ display: "flex", flexDirection: "column", gap: 20, marginBottom: 20 }}>

            {/* ② 핵심 지표 (기준일까지 누계, 전년 동월 동일기간 대비) */}
            <Card title={`🎯 ${selectedLabel} 핵심 지표 (전년 동월 동일기간 누계 대비)`}>
              <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 12 }}>
                ※ {rangeLabel}
                {P?.is_current_month && " · 진행 중인 월은 오늘까지 누계"}
                {P && !P.is_current_month && !P.is_future && " · 완료된 월은 말일까지 누계"}
              </div>
              {!P ? (
                <div style={{ fontSize: 13, color: "#A0AEC0" }}>데이터를 불러오는 중...</div>
              ) : (
                <>
                  <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(6, 1fr)", gap: 12 }}>
                    {kpis.map((k) => (
                      <div key={k.label} style={{ background: GRAY_BG, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "12px 14px" }}>
                        <div style={{ fontSize: 11, color: "#718096", marginBottom: 6 }}>{k.label}</div>
                        <div title={k.kind === "money" ? `${fmt(k.val)}원` : undefined} style={{ fontSize: 17, fontWeight: 800, color: "#1A202C" }}>
                          {k.kind === "money" ? man(k.val) : `${fmt(k.val)}건`}
                        </div>
                        <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 6 }}>
                          <DeltaBadge cur={k.val} prev={k.prev} />
                          <span style={{ fontSize: 10, color: "#A0AEC0" }} title={k.kind === "money" ? `${fmt(k.prev)}원` : undefined}>
                            전년 {k.kind === "money" ? man(k.prev) : `${fmt(k.prev)}건`}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                  {/* 월말 예상(진행 중인 월) */}
                  {P.is_current_month && (
                    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr 1fr" : "repeat(2, 1fr)", gap: 12, marginTop: 12 }}>
                      {[
                        { label: "월말 예상 매출", val: P.projected_sales, prevFull: prevFull?.sales ?? 0 },
                        { label: "월말 예상 순수익", val: P.projected_net, prevFull: prevFull?.net ?? 0 },
                      ].map((k) => (
                        <div key={k.label} style={{ background: "#FFFBEB", border: `1px solid #FCE9B6`, borderRadius: 10, padding: "12px 14px" }}>
                          <div style={{ fontSize: 11, color: "#B7791F", marginBottom: 6 }}>{k.label} (일평균 기준 추정)</div>
                          <div title={`${fmt(k.val)}원`} style={{ fontSize: 17, fontWeight: 800, color: "#1A202C" }}>{man(k.val)}</div>
                          <div style={{ marginTop: 4, fontSize: 10, color: "#A0AEC0" }} title={`${fmt(k.prevFull)}원`}>전년 동월 전체 {man(k.prevFull)}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </Card>

            {/* ③ 월별 일간 추이 (작년 동월 겹쳐보기) */}
            <Card title={`📈 월별 일간 추이 (${selectedLabel} · 작년 동월 겹쳐보기)`}>
              <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
                {(["net", "sales"] as const).map((mk) => (
                  <button key={mk} onClick={() => setDailyMetric(mk)} style={{
                    padding: "5px 14px", borderRadius: 999, fontSize: 12, cursor: "pointer", fontWeight: 600,
                    border: `1.5px solid ${dailyMetric === mk ? GOLD : BORDER}`,
                    background: dailyMetric === mk ? GOLD : "#fff", color: dailyMetric === mk ? "#fff" : "#4A5568",
                  }}>{mk === "net" ? "순수익" : "매출"}</button>
                ))}
                <span style={{ width: 1, height: 18, background: BORDER, margin: "0 4px" }} />
                {(["cum", "daily"] as const).map((mk) => (
                  <button key={mk} onClick={() => setDailyMode(mk)} style={{
                    padding: "5px 14px", borderRadius: 999, fontSize: 12, cursor: "pointer", fontWeight: 600,
                    border: `1.5px solid ${dailyMode === mk ? BLUE : BORDER}`,
                    background: dailyMode === mk ? BLUE : "#fff", color: dailyMode === mk ? "#fff" : "#4A5568",
                  }}>{mk === "cum" ? "누계" : "일별"}</button>
                ))}
              </div>
              {(overview.daily_series ?? []).length === 0 ? (
                <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>데이터 없음</div>
              ) : (
                <DailyOverlayChart
                  data={overview.daily_series as DailyPoint[]}
                  metric={dailyMetric}
                  mode={dailyMode}
                  refDay={P?.ref_day ?? (overview.daily_series?.length ?? 0)}
                  curYear={year}
                />
              )}
            </Card>

            {/* ④ 연도별 월간 추이 (1~12월 겹쳐보기) */}
            <Card title="📊 연도별 월간 추이 (1~12월 겹쳐보기)">
              <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
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
              {/* 표시 연도 필터 */}
              <div style={{ display: "flex", gap: 10, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
                <span style={{ fontSize: 11, color: "#A0AEC0" }}>표시 연도:</span>
                {[...overview.years].sort((a, b) => b - a).map((y) => (
                  <label key={y} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#4A5568", cursor: "pointer" }}>
                    <input type="checkbox" checked={overlayYears.has(y)} onChange={(e) => {
                      setOverlayYears((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(y); else next.delete(y);
                        return next;
                      });
                    }} />{y}
                  </label>
                ))}
              </div>
              <OverlayLineChart seriesByYear={overlaySeries} metric={overlayMetric} />
            </Card>

            {/* ⑤ 연간 월별 요약 (선택연도 1~12월) */}
            <Card title="📋 연간 월별 요약">
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <span style={{ fontSize: 12, color: "#4A5568", fontWeight: 600 }}>연도:</span>
                <select value={summaryYear} onChange={(e) => setSummaryYear(Number(e.target.value))}
                  style={{ padding: "6px 10px", border: `1px solid ${BORDER}`, borderRadius: 8, fontSize: 13, background: "#fff", cursor: "pointer" }}>
                  {yearOptions.map((y) => <option key={y} value={y}>{y}년</option>)}
                </select>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, minWidth: 720 }}>
                  <thead>
                    <tr style={{ background: GRAY_BG }}>
                      {["월", "매출", "지출", "순수익", "건수", "전년 매출", "전년 순수익", "매출 증감률", "순수익 증감률"].map((h) => (
                        <th key={h} style={{ padding: "9px 10px", textAlign: h === "월" ? "left" : "right", fontWeight: 700, color: "#4A5568", borderBottom: `2px solid ${BORDER}`, whiteSpace: "nowrap" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                      const c = cellOf(curYearCells, m);
                      const p = cellOf(prevYearCells, m);
                      const sales = c?.sales ?? 0, expense = c?.expense ?? 0, net = c?.net ?? 0, count = c?.count ?? 0;
                      const pSales = p?.sales ?? 0, pNet = p?.net ?? 0;
                      const sr = rate(sales, pSales), nr = rate(net, pNet);
                      const isSel = summaryYear === year && m === month;
                      const empty = sales === 0 && expense === 0 && count === 0;
                      return (
                        <tr key={m} style={{ background: isSel ? GOLD_LIGHT : "transparent", cursor: "pointer" }}
                          onClick={() => { setYear(summaryYear); setMonth(m); }}>
                          <td style={{ padding: "8px 10px", borderBottom: `1px solid ${BORDER}`, fontWeight: isSel ? 700 : 400, color: isSel ? GOLD : "#2D3748" }}>{m}월</td>
                          <td title={`${fmt(sales)}원`} style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: empty ? "#CBD5E0" : "#4A5568" }}>{empty ? "-" : man(sales)}</td>
                          <td title={`${fmt(expense)}원`} style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: empty ? "#CBD5E0" : "#4A5568" }}>{empty ? "-" : man(expense)}</td>
                          <td title={`${fmt(net)}원`} style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: empty ? "#CBD5E0" : net >= 0 ? "#276749" : "#C53030" }}>{empty ? "-" : man(net)}</td>
                          <td style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: empty ? "#CBD5E0" : "#4A5568" }}>{empty ? "-" : `${fmt(count)}`}</td>
                          <td title={`${fmt(pSales)}원`} style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#A0AEC0" }}>{pSales ? man(pSales) : "-"}</td>
                          <td title={`${fmt(pNet)}원`} style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#A0AEC0" }}>{pNet ? man(pNet) : "-"}</td>
                          <td style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: sr == null ? "#CBD5E0" : sr >= 0 ? "#276749" : "#C53030" }}>{sr == null ? "-" : `${sr >= 0 ? "+" : ""}${sr}%`}</td>
                          <td style={{ padding: "8px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: nr == null ? "#CBD5E0" : nr >= 0 ? "#276749" : "#C53030" }}>{nr == null ? "-" : `${nr >= 0 ? "+" : ""}${nr}%`}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>

            {/* ⑥ 업무별/요일별 + 동월·동분기·YTD (접기/펼치기) */}
            <Card title="🗂 추가 비교 (업무군 · 요일 · 동월/동분기/YTD)">
              <button onClick={() => setShowExtra((v) => !v)} style={{
                fontSize: 12, padding: "6px 14px", borderRadius: 8, cursor: "pointer",
                border: `1px solid ${BORDER}`, background: "#fff", color: "#4A5568", fontWeight: 600,
              }}>{showExtra ? "▲ 접기" : "▼ 펼치기"}</button>
              {showExtra && (
                <div style={{ display: "flex", flexDirection: "column", gap: 20, marginTop: 16 }}>
                  {/* 업무군 증감 */}
                  {overview.category_compare.length > 0 && (
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 8 }}>업무군별 증감 ({month}월 · 전년 동월 대비)</div>
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
                    </div>
                  )}

                  {/* 요일별 + 카테고리별 (선택월) */}
                  {data && (
                    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr", gap: 20 }}>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 8 }}>{selectedLabel} 요일별 순수익</div>
                        {data.dow.every((d) => d.net === 0) ? (
                          <div style={{ textAlign: "center", padding: 30, color: "#A0AEC0", fontSize: 13 }}>해당 월 데이터 없음</div>
                        ) : <BarChartV data={data.dow} xKey="name" yKey="net" color={BLUE} height={200} />}
                      </div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 8 }}>{selectedLabel} 카테고리별 순수익</div>
                        {data.category.length === 0 ? (
                          <div style={{ textAlign: "center", padding: 30, color: "#A0AEC0", fontSize: 13 }}>해당 월 데이터 없음</div>
                        ) : <BarChartH data={data.category} height={Math.max(200, data.category.slice(0, 10).length * 28 + 40)} />}
                      </div>
                    </div>
                  )}

                  {/* 동월 / 동분기 / YTD */}
                  <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr 1fr", gap: 16 }}>
                    {([
                      { title: `동월 (${month}월)`, rows: overview.same_month },
                      { title: `동분기 (Q${overview.selected.quarter})`, rows: overview.same_quarter },
                      { title: `YTD (1~${month}월)`, rows: overview.ytd },
                    ] as const).map((blk) => (
                      <div key={blk.title}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 8 }}>{blk.title}</div>
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
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>

            {/* ⑦ 시간대별 비교 분석 (선택월 현재기간 vs 전년 동월 동일기간) */}
            <Card title="⏰ 시간대별 비교 분석 (전년 동월 동일기간 대비)">
              {hc.length === 0 || hc.every((h) => h.cur_sales === 0 && h.prev_sales === 0) ? (
                <div style={{ textAlign: "center", padding: 40, color: "#A0AEC0", fontSize: 13 }}>해당 기간 데이터 없음</div>
              ) : (
                <>
                  <GroupedBarChart data={hc.map((h) => ({ label: h.bucket, cur: h.cur_sales, prev: h.prev_sales }))} curYear={year} height={220} />
                  <div style={{ overflowX: "auto", marginTop: 12 }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12.5, minWidth: 560 }}>
                      <thead>
                        <tr style={{ background: GRAY_BG }}>
                          {["시간대", "매출", "순수익", "건수", "전년 매출", "매출 증감률"].map((h) => (
                            <th key={h} style={{ padding: "8px 10px", textAlign: h === "시간대" ? "left" : "right", fontWeight: 700, color: "#4A5568", borderBottom: `2px solid ${BORDER}`, whiteSpace: "nowrap" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {hc.map((h) => {
                          const sr = rate(h.cur_sales, h.prev_sales);
                          return (
                            <tr key={h.bucket}>
                              <td style={{ padding: "7px 10px", borderBottom: `1px solid ${BORDER}`, color: "#2D3748" }}>{h.bucket}</td>
                              <td title={`${fmt(h.cur_sales)}원`} style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{man(h.cur_sales)}</td>
                              <td title={`${fmt(h.cur_net)}원`} style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: h.cur_net >= 0 ? "#276749" : "#C53030" }}>{man(h.cur_net)}</td>
                              <td style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{fmt(h.cur_count)}</td>
                              <td title={`${fmt(h.prev_sales)}원`} style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#A0AEC0" }}>{h.prev_sales ? man(h.prev_sales) : "-"}</td>
                              <td style={{ padding: "7px 10px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: sr == null ? "#CBD5E0" : sr >= 0 ? "#276749" : "#C53030" }}>{sr == null ? "-" : `${sr >= 0 ? "+" : ""}${sr}%`}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </Card>

            {/* ⑧ 자동 분석 (장점 / 부족한 점 / 대응 포인트) */}
            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 1fr 1fr", gap: 20 }}>
              <Card title="✅ 장점">
                {!A || A.good.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#A0AEC0" }}>데이터 부족</div>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {A.good.map((g, i) => <li key={i} style={{ fontSize: 13, color: "#276749" }}>{g}</li>)}
                  </ul>
                )}
              </Card>
              <Card title="⚠️ 부족한 점">
                {!A || A.bad.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#A0AEC0" }}>특이 하락 항목이 없습니다.</div>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {A.bad.map((b, i) => <li key={i} style={{ fontSize: 13, color: "#C53030" }}>{b}</li>)}
                  </ul>
                )}
              </Card>
              <Card title="🎯 남은 기간 대응 포인트">
                {!A || A.actions.length === 0 ? (
                  <div style={{ fontSize: 13, color: "#A0AEC0" }}>대응 포인트가 없습니다.</div>
                ) : (
                  <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                    {A.actions.map((a, i) => <li key={i} style={{ fontSize: 13, color: "#2B6CB0" }}>{a}</li>)}
                  </ul>
                )}
              </Card>
            </div>

            {/* ⑧-2 업무군별 경영 진단 보고서 */}
            {(() => {
              const bi = overview.business_insights;
              if (!bi) return null;
              const mTxt = (v: number | null) => (v == null ? "-" : `${v}%`);
              const pctTxt = (v: number | null) => (v == null ? "-" : `${v >= 0 ? "+" : ""}${v}%`);
              const deltaColor = (v: number | null) => (v == null ? "#CBD5E0" : v >= 0 ? "#276749" : "#C53030");
              const sumCards = [
                { label: "💎 가장 수익성 높은 업무군", cat: bi.summary.best_margin_category, sub: bi.summary.best_margin_value != null ? `순이익률 ${bi.summary.best_margin_value}%` : "데이터 부족", bg: "#F0FFF4", bd: "#C6F6D5", fg: "#276749" },
                { label: "📉 전년 대비 가장 감소한 업무군", cat: bi.summary.worst_decline_category, sub: bi.summary.worst_decline_net != null ? `순이익 ${man(bi.summary.worst_decline_net)}` : "전년 데이터 없음", bg: "#FFF5F5", bd: "#FED7D7", fg: "#C53030" },
                { label: "🎯 집중 개선 대상 업무군", cat: bi.summary.focus_category, sub: bi.summary.focus_margin != null ? `순이익률 ${bi.summary.focus_margin}%` : "데이터 부족", bg: "#FFFBEB", bd: "#FCE9B6", fg: "#B7791F" },
              ];
              return (
                <Card title="📑 업무군별 경영 진단 보고서 (전년 동월 동일기간 기준)">
                  {/* 총평 */}
                  <div style={{ fontSize: 13.5, color: "#2D3748", lineHeight: 1.6, padding: "10px 14px", background: GRAY_BG, borderRadius: 8, marginBottom: 16 }}>
                    {bi.total_comment}
                  </div>

                  {/* 요약 카드 3개 */}
                  <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(3, 1fr)", gap: 12, marginBottom: 18 }}>
                    {sumCards.map((s) => (
                      <div key={s.label} style={{ background: s.bg, border: `1px solid ${s.bd}`, borderRadius: 10, padding: "12px 14px" }}>
                        <div style={{ fontSize: 11, color: "#718096", marginBottom: 6 }}>{s.label}</div>
                        <div style={{ fontSize: 17, fontWeight: 800, color: s.cat ? s.fg : "#A0AEC0" }}>{s.cat ?? "데이터 부족"}</div>
                        <div style={{ fontSize: 11, color: "#718096", marginTop: 3 }}>{s.sub}</div>
                      </div>
                    ))}
                  </div>

                  {/* 손익 테이블 */}
                  {bi.categories.length === 0 ? (
                    <div style={{ fontSize: 13, color: "#A0AEC0", padding: "16px 0" }}>데이터 부족: 이번 기간 업무군 데이터가 없습니다.</div>
                  ) : (
                    <div style={{ overflowX: "auto", marginBottom: 18 }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12, minWidth: 820 }}>
                        <thead>
                          <tr style={{ background: GRAY_BG }}>
                            {["업무군", "건수", "매출", "지출", "순이익", "순이익률", "객단가", "건당순익", "전년 순이익", "건수 증감", "매출 증감률", "순익 증감률", "순이익률 차이"].map((h) => (
                              <th key={h} style={{ padding: "8px 9px", textAlign: h === "업무군" ? "left" : "right", fontWeight: 700, color: "#4A5568", borderBottom: `2px solid ${BORDER}`, whiteSpace: "nowrap" }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {bi.categories.map((c) => (
                            <tr key={c.category}>
                              <td style={{ padding: "7px 9px", borderBottom: `1px solid ${BORDER}`, fontWeight: 700, color: "#2D3748", whiteSpace: "nowrap" }}>{c.category}</td>
                              <td style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{fmt(c.cur_count)}</td>
                              <td title={`${fmt(c.cur_sales)}원`} style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{man(c.cur_sales)}</td>
                              <td title={`${fmt(c.cur_expense)}원`} style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{man(c.cur_expense)}</td>
                              <td title={`${fmt(c.cur_net)}원`} style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: c.cur_net >= 0 ? "#276749" : "#C53030" }}>{man(c.cur_net)}</td>
                              <td style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: c.cur_margin == null ? "#CBD5E0" : "#2D3748" }}>{mTxt(c.cur_margin)}</td>
                              <td title={`${fmt(c.cur_avg_ticket)}원`} style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#718096" }}>{man(c.cur_avg_ticket)}</td>
                              <td title={`${fmt(c.cur_net_per_case)}원`} style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#718096" }}>{man(c.cur_net_per_case)}</td>
                              <td title={c.has_prev ? `${fmt(c.prev_net)}원` : undefined} style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#A0AEC0" }}>{c.has_prev ? man(c.prev_net) : "-"}</td>
                              <td style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: c.has_prev ? deltaColor(c.count_delta) : "#CBD5E0" }}>{c.has_prev ? `${c.count_delta >= 0 ? "+" : ""}${c.count_delta}` : "-"}</td>
                              <td style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: deltaColor(c.sales_delta_pct) }}>{c.has_prev ? pctTxt(c.sales_delta_pct) : "-"}</td>
                              <td style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: deltaColor(c.net_delta_pct) }}>{c.has_prev ? pctTxt(c.net_delta_pct) : "-"}</td>
                              <td style={{ padding: "7px 9px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 600, color: deltaColor(c.margin_delta) }}>{c.margin_delta == null ? "-" : `${c.margin_delta >= 0 ? "+" : ""}${c.margin_delta}%p`}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {/* 업무군별 진단 + 개선 제안 */}
                  {bi.categories.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12, marginBottom: 18 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>업무군별 손익 진단 · 개선 제안</div>
                      {bi.categories.map((c) => (
                        <div key={c.category} style={{ border: `1px solid ${BORDER}`, borderRadius: 8, padding: "12px 14px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                            <span style={{ fontSize: 13, fontWeight: 700, color: "#1A202C" }}>{c.category}</span>
                            <span style={{ fontSize: 10, color: "#718096", background: GRAY_BG, borderRadius: 6, padding: "2px 8px" }}>통제가능성 {c.controllability}</span>
                          </div>
                          <div style={{ fontSize: 13, color: "#2D3748", lineHeight: 1.6 }}>{c.diagnosis}</div>
                          <div style={{ fontSize: 13, color: "#2B6CB0", lineHeight: 1.6, marginTop: 4 }}>👉 {c.recommendation}</div>
                          {c.risk_factors.length > 0 && (
                            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
                              {c.risk_factors.map((rf) => (
                                <span key={rf} style={{ fontSize: 10.5, color: "#975A16", background: "#FFFBEB", border: "1px solid #FCE9B6", borderRadius: 999, padding: "2px 8px" }}>{rf}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 외부요인 / 매뉴얼 이슈 — 상태별(linked/not_linked/error) */}
                  {(() => {
                    const st = bi.manual_issue.status;
                    const theme = st === "linked"
                      ? { bd: "#BEE3F8", bg: "#EBF8FF" }      // 변경 감지
                      : st === "error"
                        ? { bd: "#FED7D7", bg: "#FFF5F5" }    // 조회 실패/미구성
                        : { bd: "#E2E8F0", bg: GRAY_BG };     // 변경 없음(중립)
                    return (
                      <div style={{ border: `1px solid ${theme.bd}`, background: theme.bg, borderRadius: 8, padding: "12px 14px", marginBottom: 16 }}>
                        <div style={{ fontSize: 12, fontWeight: 700, color: "#4A5568", marginBottom: 4 }}>🌐 외부요인 / 매뉴얼 이슈 (출입국)</div>
                        <div style={{ fontSize: 13, color: "#2D3748", lineHeight: 1.6 }}>{bi.manual_issue.comment}</div>
                        {bi.manual_issue.related_changes.length > 0 && (
                          <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                            {bi.manual_issue.related_changes.map((rc, i) => (
                              <li key={i} style={{ fontSize: 12, color: "#2B6CB0" }}>{rc.detected_at} · {rc.version} (변경 페이지 {rc.changed_page_count}개)</li>
                            ))}
                          </ul>
                        )}
                        {/* 관리자: PG 화면 안내 / 일반 사용자: 미반영 안내만 */}
                        <div style={{ marginTop: 10 }}>
                          {isAdmin ? (
                            <a href="/admin" style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 600, color: "#2B6CB0", textDecoration: "none", border: `1px solid ${BORDER}`, background: "#fff", borderRadius: 6, padding: "5px 12px" }}>
                              🔧 매뉴얼 업데이트 PG 확인 →
                            </a>
                          ) : (
                            <span style={{ fontSize: 11, color: "#A0AEC0" }}>※ 매뉴얼 변경 데이터는 월간결산에 자동 반영되지 않습니다.</span>
                          )}
                        </div>
                      </div>
                    );
                  })()}

                  {/* 다음 달 액션 */}
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 8 }}>📌 다음 달 액션</div>
                    {bi.actions.length === 0 ? (
                      <div style={{ fontSize: 13, color: "#A0AEC0" }}>특이 액션 항목이 없습니다.</div>
                    ) : (
                      <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6 }}>
                        {bi.actions.map((a, i) => <li key={i} style={{ fontSize: 13, color: "#2B6CB0", lineHeight: 1.5 }}>{a}</li>)}
                      </ul>
                    )}
                  </div>
                </Card>
              );
            })()}

            {/* 고정지출 관리 + 신고/부가세 (PG 전용) */}
            <FixedExpensePanel year={year} month={month} pgOn={!!overview.pg_daily} />
            <TaxReportPanel year={year} month={month} pgOn={!!overview.pg_daily} autoCardSales={overview.tax?.auto_card_sales ?? 0} autoCardCount={overview.tax?.auto_card_count ?? 0} />
          </div>
        );
      })()}
    </div>
  );
}
