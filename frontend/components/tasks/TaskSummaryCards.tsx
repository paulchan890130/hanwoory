"use client";
import { formatNumber } from "@/lib/utils";

interface Props {
  totalCount: number;
  urgentCount: number;      // D+20 이상
  transferTotal: number;
  cashTotal: number;
  stampTotal: number;
  hasUnpaid: boolean;
  receivableTotal?: number;
}

export default function TaskSummaryCards({
  totalCount, urgentCount, transferTotal, cashTotal, stampTotal, hasUnpaid, receivableTotal = 0,
}: Props) {
  const cards = [
    {
      label: "전체 진행",
      value: totalCount,
      unit: "건",
      valueColor: "#1A202C",
      sub: null as string | null,
    },
    {
      label: "긴급 (D+20↑)",
      value: urgentCount,
      unit: "건",
      valueColor: urgentCount > 0 ? "#DC2626" : "#A0AEC0",
      sub: urgentCount > 0 ? "확인 필요" : "없음",
    },
    {
      label: "이체 합계",
      value: transferTotal,
      unit: "원",
      valueColor: "#1A202C",
      sub: cashTotal > 0 ? `현금 ${formatNumber(cashTotal)}` : null,
      format: true,
    },
    {
      label: "인지 합계",
      value: stampTotal,
      unit: "원",
      valueColor: "#1A202C",
      sub: hasUnpaid ? `미수 포함` : null,
      subColor: hasUnpaid ? "#DC2626" : undefined,
      format: true,
    },
  ];

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: 12,
      marginBottom: 12,
    }}>
      {cards.map((c) => (
        <div key={c.label} style={{
          background: "#fff",
          border: "1px solid #E2E8F0",
          borderRadius: 8,
          padding: "14px 18px",
          boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", letterSpacing: "0.04em", marginBottom: 6, textTransform: "uppercase" }}>
            {c.label}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
            <span style={{ fontSize: 28, fontWeight: 700, color: c.valueColor, lineHeight: 1 }}>
              {"format" in c && c.format ? formatNumber(c.value) : c.value}
            </span>
            <span style={{ fontSize: 12, color: "#A0AEC0" }}>{c.unit}</span>
          </div>
          {c.sub && (
            <div style={{ fontSize: 12, color: ("subColor" in c && c.subColor) ? c.subColor : "#718096", marginTop: 4 }}>
              {c.sub}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
