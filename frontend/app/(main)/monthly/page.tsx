"use client";
import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { dailyApi } from "@/lib/api";

// ── 색상 ─────────────────────────────────────────────────────────────────
const GOLD       = "#F5A623";
const GOLD_LIGHT = "rgba(245,166,35,0.12)";
const BLUE       = "#4299E1";
const GREEN      = "#48BB78";
const BORDER     = "#E2E8F0";
const GRAY_BG    = "#F9FAFB";

function fmt(n: number) { return n.toLocaleString("ko-KR"); }

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
                {fmt(Math.round(maxAbs * f / 1000))}천
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
                {fmt(Math.round(d.net / 1000))}천
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
                {fmt(Math.round(v / 1000))}천
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

  const { data, isLoading, isError } = useQuery<AnalysisData>({
    queryKey: ["monthly-analysis", year, month],
    queryFn:  () => dailyApi.getMonthlyAnalysis(year, month).then((r) => r.data),
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
                          <td key={i} style={{ padding: "9px 12px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, color: "#4A5568" }}>{fmt(v)}</td>
                        ))}
                        <td style={{ padding: "9px 12px", textAlign: "right", borderBottom: `1px solid ${BORDER}`, fontWeight: 700, color: row.net >= 0 ? "#276749" : "#C53030" }}>
                          {fmt(row.net)}
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
