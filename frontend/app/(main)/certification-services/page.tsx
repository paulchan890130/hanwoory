"use client";
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  certApi,
  CertBootstrap, CertVendor, CertDirection, CertGroup, CertRegion, CertPrice,
} from "@/lib/api";
import { RefreshCw, Plus, Trash2, Edit2, Save, X, Copy, Search, AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, EyeOff } from "lucide-react";

type Tab = "comparison" | "db" | "vendors" | "classification";

const POSSIBLE_ORDER: Record<string, number> = { "가능": 0, "문의": 1, "불가": 2 };

function fmt(price: string): string {
  const n = parseInt(price || "0", 10);
  if (!n) return "-";
  return n.toLocaleString("ko-KR") + "원";
}

function possibleBadge(p: string) {
  const colors: Record<string, string> = { "가능": "#10B981", "문의": "#F59E0B", "불가": "#EF4444" };
  return (
    <span style={{
      display: "inline-block", padding: "1px 8px", borderRadius: 999,
      background: colors[p] ?? "#9CA3AF", color: "#fff", fontSize: 12, fontWeight: 600,
    }}>{p || "미정"}</span>
  );
}

function Input({ label, value, onChange, multiline, style }: {
  label?: string; value: string; onChange: (v: string) => void;
  multiline?: boolean; style?: React.CSSProperties;
}) {
  const base: React.CSSProperties = {
    width: "100%", minWidth: 0, boxSizing: "border-box",
    padding: "5px 8px", border: "1px solid #CBD5E0", borderRadius: 6,
    fontSize: 13, background: "#fff", ...style,
  };
  return (
    <div style={{ marginBottom: 6 }}>
      {label && <div style={{ fontSize: 11, color: "#718096", marginBottom: 2 }}>{label}</div>}
      {multiline
        ? <textarea value={value} onChange={e => onChange(e.target.value)} rows={2} style={{ ...base, resize: "vertical" }} />
        : <input value={value} onChange={e => onChange(e.target.value)} style={base} />
      }
    </div>
  );
}

function Select({ label, value, onChange, options }: {
  label?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[];
}) {
  return (
    <div style={{ marginBottom: 6 }}>
      {label && <div style={{ fontSize: 11, color: "#718096", marginBottom: 2 }}>{label}</div>}
      <select value={value} onChange={e => onChange(e.target.value)}
        style={{ width: "100%", minWidth: 0, boxSizing: "border-box", padding: "5px 8px", border: "1px solid #CBD5E0", borderRadius: 6, fontSize: 13, background: "#fff" }}>
        <option value="">선택 없음</option>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

function Toast({ msg, type, onClose }: { msg: string; type: "success" | "error"; onClose: () => void }) {
  useEffect(() => { const t = setTimeout(onClose, type === "error" ? 6000 : 3000); return () => clearTimeout(t); }, [onClose, type]);
  return (
    <div style={{
      position: "fixed", bottom: 24, right: 24, zIndex: 9999,
      padding: "10px 20px", borderRadius: 8,
      background: type === "success" ? "#10B981" : "#EF4444",
      color: "#fff", fontSize: 14, boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
    }}>{msg}</div>
  );
}

function Btn({ onClick, children, color, size, disabled }: {
  onClick: () => void; children: React.ReactNode;
  color?: string; size?: "sm" | "xs"; disabled?: boolean;
}) {
  const bg = color === "red" ? "#EF4444" : color === "green" ? "#10B981" : color === "blue" ? "#3B82F6" : "#E2E8F0";
  const fg = color ? "#fff" : "#374151";
  const pd = size === "xs" ? "2px 8px" : "4px 12px";
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ padding: pd, borderRadius: 6, background: bg, color: fg, fontSize: size === "xs" ? 11 : 13,
        border: "none", cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
        display: "inline-flex", alignItems: "center", gap: 4 }}>
      {children}
    </button>
  );
}

const EMPTY_PRICE: Partial<CertPrice> = {
  vendor_id: "", group_id: "", direction: "", region: "", condition: "",
  price: "0", possible: "가능", documents: "", lead_time: "", strength: "", risk: "", source: "", last_checked: "",
};

const EMPTY_VENDOR: Partial<CertVendor> = { name: "", contact: "", memo: "", active: "true" };
const EMPTY_DIR: Partial<CertDirection> = { name: "", sort_order: "0", active: "true" };
const EMPTY_GRP: Partial<CertGroup> = { group_name: "", aliases: "", default_direction: "", sort_order: "0", active: "true" };
const EMPTY_RGN: Partial<CertRegion> = { name: "", sort_order: "0", active: "true" };

export default function CertificationServicesPage() {
  const [tab, setTab] = useState<Tab>("comparison");
  const [data, setData] = useState<CertBootstrap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const loadInFlightRef = useRef(false);

  // 입력 중인 필터 (아직 적용 안 됨)
  const [filterDir, setFilterDir] = useState("");
  const [filterGrp, setFilterGrp] = useState("");
  const [filterRgn, setFilterRgn] = useState("");
  const [keyword, setKeyword] = useState("");

  // 검색 버튼 클릭 시 확정된 필터
  const [appliedDir, setAppliedDir] = useState("");
  const [appliedGrp, setAppliedGrp] = useState("");
  const [appliedRgn, setAppliedRgn] = useState("");
  const [appliedKeyword, setAppliedKeyword] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  // comparison
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // db edit
  const [editPriceId, setEditPriceId] = useState<string | null>(null);
  const [priceDraft, setPriceDraft] = useState<Partial<CertPrice>>({});
  const [addingPrice, setAddingPrice] = useState(false);
  const [newPrice, setNewPrice] = useState<Partial<CertPrice>>({ ...EMPTY_PRICE });

  // vendor edit
  const [editVendorId, setEditVendorId] = useState<string | null>(null);
  const [vendorDraft, setVendorDraft] = useState<Partial<CertVendor>>({});
  const [addingVendor, setAddingVendor] = useState(false);
  const [newVendor, setNewVendor] = useState<Partial<CertVendor>>({ ...EMPTY_VENDOR });

  // dir edit
  const [editDirId, setEditDirId] = useState<string | null>(null);
  const [dirDraft, setDirDraft] = useState<Partial<CertDirection>>({});
  const [addingDir, setAddingDir] = useState(false);
  const [newDir, setNewDir] = useState<Partial<CertDirection>>({ ...EMPTY_DIR });

  // group edit
  const [editGrpId, setEditGrpId] = useState<string | null>(null);
  const [grpDraft, setGrpDraft] = useState<Partial<CertGroup>>({});
  const [addingGrp, setAddingGrp] = useState(false);
  const [newGrp, setNewGrp] = useState<Partial<CertGroup>>({ ...EMPTY_GRP });

  // region edit
  const [editRgnId, setEditRgnId] = useState<string | null>(null);
  const [rgnDraft, setRgnDraft] = useState<Partial<CertRegion>>({});
  const [addingRgn, setAddingRgn] = useState(false);
  const [newRgn, setNewRgn] = useState<Partial<CertRegion>>({ ...EMPTY_RGN });

  const showToast = useCallback((msg: string, type: "success" | "error") => setToast({ msg, type }), []);

  const load = useCallback(async () => {
    // 동시 중복 호출 방지 (React StrictMode dev double-invoke 포함)
    if (loadInFlightRef.current) return;
    loadInFlightRef.current = true;
    setLoading(true); setError("");
    try {
      const r = await certApi.bootstrap();
      setData(r.data);
    } catch (e: any) {
      const status = (e as any).response?.status;
      if (status === 429) {
        setError("데이터 조회 한도를 초과했습니다. 잠시 후 다시 시도하거나 새로고침 횟수를 줄여주세요.");
      } else {
        setError((e as any).response?.data?.detail || "데이터 로드 실패");
      }
    } finally {
      setLoading(false);
      loadInFlightRef.current = false;
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const getFiltered = useCallback(() => {
    if (!data || !hasSearched) return [];
    const activeVendorIds = new Set(data.vendors.filter(v => v.active === "true").map(v => v.id));
    let list = data.prices.filter(p => activeVendorIds.has(p.vendor_id));

    if (appliedDir) list = list.filter(p => p.direction === appliedDir);
    if (appliedGrp) list = list.filter(p => p.group_id === appliedGrp);
    if (appliedRgn) list = list.filter(p => p.region === appliedRgn);

    if (appliedKeyword.trim()) {
      const kw = appliedKeyword.toLowerCase();
      const vm = Object.fromEntries(data.vendors.map(v => [v.id, v.name]));
      const gm = Object.fromEntries(data.groups.map(g => [g.id, `${g.group_name} ${g.aliases}`]));
      list = list.filter(p => [vm[p.vendor_id] ?? "", gm[p.group_id] ?? "", p.direction, p.region,
        p.condition, p.documents, p.strength, p.risk, p.lead_time, p.last_checked].join(" ").toLowerCase().includes(kw));
    }

    list.sort((a, b) => {
      const po = (POSSIBLE_ORDER[a.possible] ?? 1) - (POSSIBLE_ORDER[b.possible] ?? 1);
      if (po !== 0) return po;
      if (a.possible === "가능" && b.possible === "가능") {
        const pa = parseInt(a.price || "0", 10), pb = parseInt(b.price || "0", 10);
        if (!pa && pb) return 1; if (!pb && pa) return -1;
        return pa - pb;
      }
      return 0;
    });
    return list;
  }, [data, hasSearched, appliedDir, appliedGrp, appliedRgn, appliedKeyword]);

  // find lowest valid price among 가능 rows
  const getLowestPriceId = useCallback((prices: CertPrice[]) => {
    let min = Infinity, minId = "";
    for (const p of prices) {
      if (p.possible !== "가능") continue;
      const n = parseInt(p.price || "0", 10);
      if (n > 0 && n < min) { min = n; minId = p.id; }
    }
    return minId;
  }, []);

  const handleSearch = useCallback(() => {
    setAppliedDir(filterDir);
    setAppliedGrp(filterGrp);
    setAppliedRgn(filterRgn);
    setAppliedKeyword(keyword);
    setHasSearched(true);
    setSelectedId(null);
  }, [filterDir, filterGrp, filterRgn, keyword]);

  // ── 종속 필터 후보 계산 ─────────────────────────────────────────────────────
  const visibleGroups = useMemo(() => {
    const groups = data?.groups ?? [];
    if (!filterDir) return groups;
    return groups.filter(g => {
      const extra = (g.applicable_directions ?? "").split(",").map(s => s.trim()).filter(Boolean);
      return g.default_direction === filterDir || extra.includes(filterDir);
    });
  }, [data, filterDir]);

  const visibleRegions = useMemo(() => {
    const regions = data?.regions ?? [];
    return regions.filter(r => {
      const dirs = (r.applicable_directions ?? "").split(",").map(s => s.trim()).filter(Boolean);
      const grps = (r.applicable_group_ids ?? "").split(",").map(s => s.trim()).filter(Boolean);
      if (filterDir) {
        if (dirs.length > 0 && !dirs.includes(filterDir)) return false;
        // 중국→한국 또는 중국 현지 선택 시 "한국" 지역 숨김
        if ((filterDir === "중국 → 한국" || filterDir === "중국 현지 내부처리") && r.name === "한국") return false;
      }
      if (filterGrp) {
        if (grps.length > 0 && !grps.includes(filterGrp)) return false;
      }
      return true;
    });
  }, [data, filterDir, filterGrp]);

  // ── 분류 정합성 진단(6-3) — 드롭다운/검색과 같은 bootstrap 정본으로 클라이언트에서 계산 ──
  type ClassDiag = {
    total: number; active: number; inactive: number; usedCount: number;
    orphanUsed: string[]; inactiveButUsed: string[]; duplicateNames: string[];
  };
  function diagClass<T extends { id: string; active: string }>(
    items: T[], usedValues: (string | undefined)[], keyOf: (item: T) => string, nameOf: (item: T) => string,
  ): ClassDiag {
    const usedCounts = new Map<string, number>();
    usedValues.forEach(v => { if (v) usedCounts.set(v, (usedCounts.get(v) ?? 0) + 1); });
    const isActive = (i: T) => i.active === "true" || i.active === "TRUE";
    const keySet = new Set(items.map(keyOf));
    const orphanUsed = Array.from(usedCounts.keys()).filter(v => !keySet.has(v));
    const inactiveButUsed = items.filter(i => !isActive(i) && usedCounts.has(keyOf(i))).map(nameOf);
    const usedCount = items.filter(i => usedCounts.has(keyOf(i))).length;
    const nameCounts = new Map<string, number>();
    items.forEach(i => { const n = nameOf(i); if (n) nameCounts.set(n, (nameCounts.get(n) ?? 0) + 1); });
    const duplicateNames = Array.from(nameCounts.entries()).filter(([, c]) => c > 1).map(([n]) => n);
    return {
      total: items.length, active: items.filter(isActive).length,
      inactive: items.filter(i => !isActive(i)).length, usedCount, orphanUsed, inactiveButUsed, duplicateNames,
    };
  }
  const dirDiag = useMemo(() => data
    ? diagClass(data.directions, data.prices.map(p => p.direction), d => d.name, d => d.name) : null, [data]);
  const grpDiag = useMemo(() => data
    ? diagClass(data.groups, data.prices.map(p => p.group_id), g => g.id, g => g.group_name) : null, [data]);
  const rgnDiag = useMemo(() => data
    ? diagClass(data.regions, data.prices.map(p => p.region), r => r.name, r => r.name) : null, [data]);
  const [showDiag, setShowDiag] = useState(false);

  // 대분류 변경 → 현재 중분류/소분류가 후보 밖이면 자동 초기화 (API 호출 없음)
  useEffect(() => {
    if (filterGrp && !visibleGroups.some((g: { id: string }) => g.id === filterGrp)) setFilterGrp("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleGroups]);

  useEffect(() => {
    if (filterRgn && !visibleRegions.some((r: { name: string }) => r.name === filterRgn)) setFilterRgn("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleRegions]);

  // ── Filter Bar ─────────────────────────────────────────────────────────────
  const FilterBar = (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 16 }}>
      <select value={filterDir} onChange={e => setFilterDir(e.target.value)}
        style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13, minWidth: 140 }}>
        <option value="">대분류 전체</option>
        {data?.directions.map(d => <option key={d.id} value={d.name}>{d.name}</option>)}
      </select>
      <select value={filterGrp} onChange={e => setFilterGrp(e.target.value)}
        style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13, minWidth: 160 }}>
        <option value="">중분류 전체</option>
        {visibleGroups.map(g => <option key={g.id} value={g.id}>{g.group_name}</option>)}
      </select>
      <select value={filterRgn} onChange={e => setFilterRgn(e.target.value)}
        style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13, minWidth: 140 }}>
        <option value="">소분류/지역 전체</option>
        {visibleRegions.map(r => <option key={r.id} value={r.name}>{r.name}</option>)}
      </select>
      <button
        onClick={handleSearch}
        style={{ padding: "5px 16px", borderRadius: 6, border: "none", background: "#3B82F6", color: "#fff", cursor: "pointer", display: "flex", alignItems: "center", gap: 5, fontSize: 13, fontWeight: 600 }}>
        <Search size={13} /> 검색
      </button>
      <input
        value={keyword}
        onChange={e => setKeyword(e.target.value)}
        onKeyDown={e => e.key === "Enter" && handleSearch()}
        placeholder="검색어 / 키워드 (선택)"
        style={{ marginLeft: "auto", padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13, minWidth: 200 }}
      />
    </div>
  );

  // ── Comparison Tab ─────────────────────────────────────────────────────────
  const filtered = getFiltered();
  const lowestId = getLowestPriceId(filtered);
  const selected = data?.prices.find(p => p.id === selectedId) ?? null;
  const vendorMap = Object.fromEntries((data?.vendors ?? []).map(v => [v.id, v.name]));
  const groupMap = Object.fromEntries((data?.groups ?? []).map(g => [g.id, g.group_name]));

  const ComparisonTab = (
    <div style={{ display: "flex", gap: 16, height: "calc(100vh - 220px)" }}>
      <div style={{ flex: "0 0 55%", overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
        {!hasSearched && (
          <div style={{ color: "#718096", padding: 40, textAlign: "center", lineHeight: 1.8 }}>
            <Search size={28} style={{ display: "block", margin: "0 auto 10px", opacity: 0.35 }} />
            조건을 선택하고 <strong>검색</strong> 버튼을 누르세요.<br />
            <span style={{ fontSize: 12 }}>조건 없이 검색하면 전체 항목을 볼 수 있습니다.</span>
          </div>
        )}
        {hasSearched && filtered.length === 0 && <div style={{ color: "#718096", padding: 20, textAlign: "center" }}>결과 없음</div>}
        {filtered.map(p => {
          const isLowest = p.id === lowestId;
          const isSelected = p.id === selectedId;
          return (
            <div key={p.id} onClick={() => setSelectedId(p.id)}
              style={{
                padding: "10px 14px", borderRadius: 8, cursor: "pointer",
                border: isSelected ? "2px solid #3B82F6" : isLowest ? "2px solid #10B981" : "1px solid #E2E8F0",
                background: isSelected ? "#EFF6FF" : isLowest ? "#F0FDF4" : "#fff",
                display: "flex", alignItems: "center", gap: 10,
              }}>
              {isLowest && <span style={{ fontSize: 10, background: "#10B981", color: "#fff", padding: "1px 6px", borderRadius: 999, whiteSpace: "nowrap" }}>최저가</span>}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <span style={{ fontWeight: 700, fontSize: 14 }}>{vendorMap[p.vendor_id] ?? `[삭제된 업체]`}</span>
                  <span style={{ fontSize: 12, color: "#718096" }}>{groupMap[p.group_id] ?? `[삭제된 중분류]`}</span>
                  {possibleBadge(p.possible)}
                </div>
                <div style={{ fontSize: 12, color: "#4A5568", marginTop: 2 }}>{p.condition}</div>
                {p.region && <div style={{ fontSize: 11, color: "#718096" }}>{p.direction} / {p.region}</div>}
              </div>
              <div style={{ fontWeight: 700, fontSize: 15, color: isLowest ? "#059669" : "#1A202C", whiteSpace: "nowrap" }}>{fmt(p.price)}</div>
            </div>
          );
        })}
      </div>

      <div style={{ flex: 1, overflowY: "auto", border: "1px solid #E2E8F0", borderRadius: 10, padding: 16 }}>
        {!selected ? (
          <div style={{ color: "#718096", padding: 20, textAlign: "center" }}>왼쪽 항목을 클릭하면 상세 정보가 표시됩니다</div>
        ) : (
          <>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginBottom: 12 }}>
              <Btn onClick={() => {
                const text = [
                  `[${vendorMap[selected.vendor_id] ?? "[삭제된 업체]"}] ${groupMap[selected.group_id] ?? "[삭제된 중분류]"}`,
                  `조건: ${selected.condition}`,
                  `대분류/지역: ${selected.direction} / ${selected.region}`,
                  `원가: ${fmt(selected.price)} (${selected.possible})`,
                  selected.documents && `서류: ${selected.documents}`,
                  selected.lead_time && `처리기간: ${selected.lead_time}`,
                  selected.risk && `주의: ${selected.risk}`,
                  selected.last_checked && `최종확인: ${selected.last_checked}`,
                ].filter(Boolean).join("\n");
                navigator.clipboard.writeText(text).then(() => showToast("복사됨", "success"));
              }} color="blue" size="sm"><Copy size={13} /> 요약 복사</Btn>
              <Btn onClick={() => { setTab("db"); setEditPriceId(selected.id); setPriceDraft({ ...selected }); }} size="sm">
                <Edit2 size={13} /> 선택항목 수정
              </Btn>
            </div>
            {[
              ["업체", vendorMap[selected.vendor_id] ?? "[삭제된 업체]"],
              ["중분류", groupMap[selected.group_id] ?? "[삭제된 중분류]"],
              ["대분류", selected.direction],
              ["소분류/지역", selected.region],
              ["조건", selected.condition],
              ["원가", fmt(selected.price)],
              ["가능여부", selected.possible],
              ["구비서류", selected.documents],
              ["처리기간", selected.lead_time],
              ["업체강점", selected.strength],
              ["주의사항", selected.risk],
              ["출처", selected.source],
              ["최종확인일", selected.last_checked],
            ].map(([k, v]) => v ? (
              <div key={k} style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 11, color: "#718096" }}>{k}</div>
                <div style={{ fontSize: 13, color: "#1A202C", whiteSpace: "pre-wrap" }}>{v}</div>
              </div>
            ) : null)}
          </>
        )}
      </div>
    </div>
  );

  // ── DB관리 Tab ──────────────────────────────────────────────────────────────
  const dirOpts = (data?.directions ?? []).map(d => ({ value: d.name, label: d.name }));
  const vendorOpts = (data?.vendors ?? []).map(v => ({ value: v.id, label: v.name }));

  // PriceForm: 대분류 선택에 따라 중분류/소분류 후보를 동적으로 계산.
  // ⚠️ 컴포넌트 본문 안에 정의돼 있으므로 JSX(<PriceForm/>)로 렌더하면 매 입력마다
  // 부모 리렌더 → 새 컴포넌트 식별자 → input 리마운트로 포커스가 사라진다.
  // 반드시 함수 호출({PriceForm({draft, setDraft})})로 렌더해 부모 트리에 인라인한다.
  const PriceForm = ({ draft, setDraft }: { draft: Partial<CertPrice>; setDraft: (d: Partial<CertPrice>) => void }) => {
    const allGroups = data?.groups ?? [];
    const allRegions = data?.regions ?? [];

    // 대분류 기준 중분류 후보
    const formGrps = draft.direction
      ? allGroups.filter(g => {
          const extra = (g.applicable_directions ?? "").split(",").map(s => s.trim()).filter(Boolean);
          return g.default_direction === draft.direction || extra.includes(draft.direction!);
        })
      : allGroups;

    // 현재 group_id 가 후보에 없으면 "현재값" 항목을 앞에 추가 (값 보존)
    const grpInVisible = !draft.group_id || formGrps.some(g => g.id === draft.group_id);
    const formGrpOpts = [
      ...(!grpInVisible && draft.group_id
        ? [{ value: draft.group_id, label: `현재값: ${groupMap[draft.group_id] ?? draft.group_id}` }]
        : []),
      ...formGrps.map(g => ({ value: g.id, label: g.group_name })),
    ];

    // 소분류/지역 옵션 = 소분류/지역 관리에 등록된 active master 전체(절대 distinct/일부로 잘라내지 않음).
    // 대분류/중분류 매핑(applicable_*)이 있으면 그 지역을 '우선'(앞쪽 정렬)할 뿐 제외하지 않는다.
    const RGN_PRIORITY = ["지역상관없음", "전국", "중국", "한국"];
    const isMappedToDraft = (r: CertRegion) => {
      const dirs = (r.applicable_directions ?? "").split(",").map(s => s.trim()).filter(Boolean);
      const grps = (r.applicable_group_ids ?? "").split(",").map(s => s.trim()).filter(Boolean);
      const dirOk = !!draft.direction && dirs.length > 0 && dirs.includes(draft.direction);
      const grpOk = !!draft.group_id && grps.length > 0 && grps.includes(draft.group_id);
      return dirOk || grpOk;
    };
    const rgnRank = (r: CertRegion): [number, number, number] => {
      const pi = RGN_PRIORITY.indexOf(r.name);
      if (pi >= 0) return [0, pi, 0];                       // 고정 우선 지역(지역상관없음/전국/중국/한국)
      return [1, isMappedToDraft(r) ? 0 : 1, Number(r.sort_order) || 0];  // 매핑 지역 우선, 그 외 sort_order
    };
    const formRgns = allRegions
      .filter(r => (r.active ?? "true") !== "false")        // active master 전체
      .slice()
      .sort((a, b) => {
        const ra = rgnRank(a), rb = rgnRank(b);
        for (let i = 0; i < 3; i++) if (ra[i] !== rb[i]) return ra[i] - rb[i];
        return a.name.localeCompare(b.name);
      });

    // 현재값이 master 에 없을 때만 "현재값: xxx" 를 맨 위에 추가(값 보존). 그 외엔 master 전체 노출.
    const rgnInVisible = !draft.region || formRgns.some(r => r.name === draft.region);
    const formRgnOpts = [
      ...(!rgnInVisible && draft.region
        ? [{ value: draft.region, label: `현재값: ${draft.region} (목록에 없음)` }]
        : []),
      ...formRgns.map(r => ({ value: r.name, label: r.name })),
    ];

    return (
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
        <Select label="업체" value={draft.vendor_id ?? ""} onChange={v => setDraft({ ...draft, vendor_id: v })} options={vendorOpts} />
        <Select label="대분류" value={draft.direction ?? ""} onChange={v => setDraft({ ...draft, direction: v })} options={dirOpts} />
        <Select label="중분류" value={draft.group_id ?? ""} onChange={v => setDraft({ ...draft, group_id: v })} options={formGrpOpts} />
        <Select label="소분류/지역" value={draft.region ?? ""} onChange={v => setDraft({ ...draft, region: v })} options={formRgnOpts} />
        <div style={{ gridColumn: "1 / -1" }}>
          <Input label="조건" value={draft.condition ?? ""} onChange={v => setDraft({ ...draft, condition: v })} />
        </div>
        <Input label="원가 (숫자만)" value={draft.price ?? "0"} onChange={v => setDraft({ ...draft, price: v })} />
        <Select label="가능여부" value={draft.possible ?? "가능"} onChange={v => setDraft({ ...draft, possible: v })}
          options={[{ value: "가능", label: "가능" }, { value: "문의", label: "문의" }, { value: "불가", label: "불가" }]} />
        <div style={{ gridColumn: "1 / -1" }}>
          <Input label="구비서류" value={draft.documents ?? ""} onChange={v => setDraft({ ...draft, documents: v })} multiline />
        </div>
        <Input label="처리기간" value={draft.lead_time ?? ""} onChange={v => setDraft({ ...draft, lead_time: v })} />
        <Input label="최종확인일" value={draft.last_checked ?? ""} onChange={v => setDraft({ ...draft, last_checked: v })} />
        <div style={{ gridColumn: "1 / -1" }}>
          <Input label="업체강점" value={draft.strength ?? ""} onChange={v => setDraft({ ...draft, strength: v })} multiline />
          <Input label="주의사항" value={draft.risk ?? ""} onChange={v => setDraft({ ...draft, risk: v })} multiline />
          <Input label="출처" value={draft.source ?? ""} onChange={v => setDraft({ ...draft, source: v })} />
        </div>
      </div>
    );
  };

  const savePriceEdit = async () => {
    if (!priceDraft.id) return;
    try {
      const r = await certApi.updatePrice(priceDraft.id, priceDraft);
      setData(prev => prev ? { ...prev, prices: prev.prices.map(p => p.id === r.data.id ? r.data as CertPrice : p) } : prev);
      setEditPriceId(null); showToast("저장됨", "success");
    } catch { showToast("저장 실패", "error"); }
  };

  const saveNewPrice = async () => {
    try {
      const r = await certApi.createPrice(newPrice);
      setData(prev => prev ? { ...prev, prices: [...prev.prices, r.data as CertPrice] } : prev);
      setAddingPrice(false); setNewPrice({ ...EMPTY_PRICE }); showToast("추가됨", "success");
    } catch { showToast("추가 실패", "error"); }
  };

  const deletePrice = async (id: string) => {
    if (!confirm("이 항목을 삭제하시겠습니까?")) return;
    try {
      await certApi.deletePrice(id);
      setData(prev => prev ? { ...prev, prices: prev.prices.filter(p => p.id !== id) } : prev);
      showToast("삭제됨", "success");
    } catch (e: any) { showToast(e.response?.data?.detail || "삭제 실패", "error"); }
  };

  const dbFiltered = (() => {
    if (!data) return [];
    if (!hasSearched) return [];
    let list = [...data.prices];
    if (appliedDir) list = list.filter(p => p.direction === appliedDir);
    if (appliedGrp) list = list.filter(p => p.group_id === appliedGrp);
    if (appliedRgn) list = list.filter(p => p.region === appliedRgn);
    if (appliedKeyword.trim()) {
      const kw = appliedKeyword.toLowerCase();
      list = list.filter(p => [vendorMap[p.vendor_id] ?? "", groupMap[p.group_id] ?? "",
        p.direction, p.region, p.condition].join(" ").toLowerCase().includes(kw));
    }
    // 기본 정렬: 가능 항목 우선 → 가격 오름차순(숫자 기준) → 가격 없는 항목은 아래 → 동가는 업체명 안정 정렬.
    // (행 추가/수정/삭제는 data.prices 를 갱신하므로 매 렌더 재계산되어 즉시 재정렬된다.)
    list.sort((a, b) => {
      const po = (POSSIBLE_ORDER[a.possible] ?? 1) - (POSSIBLE_ORDER[b.possible] ?? 1);
      if (po !== 0) return po;
      const pa = parseInt(a.price || "0", 10), pb = parseInt(b.price || "0", 10);
      const za = pa > 0 ? 0 : 1, zb = pb > 0 ? 0 : 1;     // 가격 없음(0/빈값)은 아래로
      if (za !== zb) return za - zb;
      if (pa !== pb) return pa - pb;                       // 숫자 기준 오름차순
      return (vendorMap[a.vendor_id] ?? "").localeCompare(vendorMap[b.vendor_id] ?? "");
    });
    return list;
  })();

  const DBTab = (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 14, color: "#718096" }}>{hasSearched ? `${dbFiltered.length}건` : "—"}</span>
        <Btn onClick={() => { setAddingPrice(true); setNewPrice({ ...EMPTY_PRICE }); }} color="green">
          <Plus size={14} /> 행 추가
        </Btn>
      </div>

      {!hasSearched && (
        <div style={{ color: "#718096", padding: 40, textAlign: "center", lineHeight: 1.8 }}>
          <Search size={28} style={{ display: "block", margin: "0 auto 10px", opacity: 0.35 }} />
          조건을 선택하고 <strong>검색</strong> 버튼을 누르세요.<br />
          <span style={{ fontSize: 12 }}>조건 없이 검색하면 전체 가격조건을 볼 수 있습니다.</span>
        </div>
      )}

      {addingPrice && (
        <div style={{ border: "2px dashed #3B82F6", borderRadius: 10, padding: 16, marginBottom: 16, background: "#EFF6FF" }}>
          <div style={{ fontWeight: 700, marginBottom: 10, color: "#1D4ED8" }}>새 항목 추가</div>
          {PriceForm({ draft: newPrice, setDraft: setNewPrice })}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Btn onClick={saveNewPrice} color="green"><Save size={13} /> 저장</Btn>
            <Btn onClick={() => setAddingPrice(false)}><X size={13} /> 취소</Btn>
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {dbFiltered.map(p => (
          <div key={p.id} id={`price-${p.id}`}
            style={{ border: editPriceId === p.id ? "2px solid #3B82F6" : "1px solid #E2E8F0", borderRadius: 10, padding: 14, background: "#fff" }}>
            {editPriceId === p.id ? (
              <>
                <div style={{ fontWeight: 700, marginBottom: 10, color: "#1D4ED8" }}>수정 중</div>
                {PriceForm({ draft: priceDraft, setDraft: setPriceDraft })}
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <Btn onClick={savePriceEdit} color="green"><Save size={13} /> 저장</Btn>
                  <Btn onClick={() => setEditPriceId(null)}><X size={13} /> 취소</Btn>
                </div>
              </>
            ) : (
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                    <span style={{ fontWeight: 700 }}>{vendorMap[p.vendor_id] ?? `[삭제된 업체]`}</span>
                    <span style={{ color: "#718096", fontSize: 13 }}>{groupMap[p.group_id] ?? `[삭제된 중분류]`}</span>
                    {possibleBadge(p.possible)}
                    <span style={{ fontWeight: 700, color: "#059669" }}>{fmt(p.price)}</span>
                  </div>
                  <div style={{ fontSize: 13, color: "#4A5568" }}>{p.condition}</div>
                  <div style={{ fontSize: 12, color: "#718096" }}>{p.direction}{p.region ? " / " + p.region : ""}</div>
                  {p.documents && <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>서류: {p.documents}</div>}
                  {p.risk && <div style={{ fontSize: 12, color: "#E53E3E", marginTop: 2 }}>주의: {p.risk}</div>}
                  {p.last_checked && <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 2 }}>최종확인: {p.last_checked}</div>}
                </div>
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <Btn onClick={() => { setEditPriceId(p.id); setPriceDraft({ ...p }); }} size="xs"><Edit2 size={11} /> 수정</Btn>
                  <Btn onClick={() => deletePrice(p.id)} color="red" size="xs"><Trash2 size={11} /></Btn>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );

  // ── 업체관리 Tab ────────────────────────────────────────────────────────────
  const saveVendorEdit = async () => {
    if (!vendorDraft.id) return;
    try {
      const r = await certApi.updateVendor(vendorDraft.id, vendorDraft);
      setData(prev => prev ? { ...prev, vendors: prev.vendors.map(v => v.id === r.data.id ? r.data as CertVendor : v) } : prev);
      setEditVendorId(null); showToast("저장됨", "success");
    } catch { showToast("저장 실패", "error"); }
  };

  const saveNewVendor = async () => {
    try {
      const r = await certApi.createVendor(newVendor);
      setData(prev => prev ? { ...prev, vendors: [...prev.vendors, r.data as CertVendor] } : prev);
      setAddingVendor(false); setNewVendor({ ...EMPTY_VENDOR }); showToast("추가됨", "success");
    } catch { showToast("추가 실패", "error"); }
  };

  const deleteVendor = async (id: string) => {
    if (!confirm("이 업체를 삭제하시겠습니까?\n(가격조건이 연결된 경우 삭제 대신 비활성 처리됩니다)")) return;
    try {
      const r = await certApi.deleteVendor(id);
      const { action, ref_count } = r.data;
      if (action === "deactivated") {
        setData(prev => prev ? { ...prev, vendors: prev.vendors.map(v => v.id === id ? { ...v, active: "false" } : v) } : prev);
        showToast(`가격조건 ${ref_count}건이 연결되어 비활성 처리됨`, "success");
      } else {
        setData(prev => prev ? { ...prev, vendors: prev.vendors.filter(v => v.id !== id) } : prev);
        showToast("삭제됨", "success");
      }
    } catch (e: any) { showToast(e.response?.data?.detail || "삭제 실패", "error"); }
  };

  // ⚠️ PriceForm 과 동일 — 함수 호출({VendorForm({...})})로만 렌더(포커스 유지).
  const VendorForm = ({ draft, setDraft }: { draft: Partial<CertVendor>; setDraft: (d: Partial<CertVendor>) => void }) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
      <Input label="업체명" value={draft.name ?? ""} onChange={v => setDraft({ ...draft, name: v })} />
      <Input label="연락처" value={draft.contact ?? ""} onChange={v => setDraft({ ...draft, contact: v })} />
      <div style={{ gridColumn: "1 / -1" }}>
        <Input label="메모" value={draft.memo ?? ""} onChange={v => setDraft({ ...draft, memo: v })} multiline />
      </div>
      <Select label="사용여부" value={draft.active ?? "true"} onChange={v => setDraft({ ...draft, active: v })}
        options={[{ value: "true", label: "활성" }, { value: "false", label: "비활성" }]} />
    </div>
  );

  const VendorsTab = (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <Btn onClick={() => { setAddingVendor(true); setNewVendor({ ...EMPTY_VENDOR }); }} color="green">
          <Plus size={14} /> 업체 추가
        </Btn>
      </div>

      {addingVendor && (
        <div style={{ border: "2px dashed #3B82F6", borderRadius: 10, padding: 16, marginBottom: 16, background: "#EFF6FF" }}>
          <div style={{ fontWeight: 700, marginBottom: 10, color: "#1D4ED8" }}>새 업체 추가</div>
          {VendorForm({ draft: newVendor, setDraft: setNewVendor })}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Btn onClick={saveNewVendor} color="green"><Save size={13} /> 저장</Btn>
            <Btn onClick={() => setAddingVendor(false)}><X size={13} /> 취소</Btn>
          </div>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {(data?.vendors ?? []).map(v => (
          <div key={v.id} style={{ border: editVendorId === v.id ? "2px solid #3B82F6" : "1px solid #E2E8F0", borderRadius: 10, padding: 14, background: "#fff" }}>
            {editVendorId === v.id ? (
              <>
                <div style={{ fontWeight: 700, marginBottom: 10, color: "#1D4ED8" }}>수정 중</div>
                {VendorForm({ draft: vendorDraft, setDraft: setVendorDraft })}
                <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                  <Btn onClick={saveVendorEdit} color="green"><Save size={13} /> 저장</Btn>
                  <Btn onClick={() => setEditVendorId(null)}><X size={13} /> 취소</Btn>
                </div>
              </>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 700, fontSize: 15 }}>{v.name}</span>
                  {v.contact && <span style={{ marginLeft: 10, fontSize: 13, color: "#718096" }}>{v.contact}</span>}
                  <span style={{ marginLeft: 8, fontSize: 12, padding: "1px 8px", borderRadius: 999, background: v.active === "true" ? "#D1FAE5" : "#FEE2E2", color: v.active === "true" ? "#065F46" : "#991B1B" }}>
                    {v.active === "true" ? "활성" : "비활성"}
                  </span>
                  {v.memo && <div style={{ fontSize: 13, color: "#718096", marginTop: 2 }}>{v.memo}</div>}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <Btn onClick={() => { setEditVendorId(v.id); setVendorDraft({ ...v }); }} size="xs"><Edit2 size={11} /> 수정</Btn>
                  <Btn onClick={() => deleteVendor(v.id)} color="red" size="xs"><Trash2 size={11} /></Btn>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );

  // ── 분류관리 Tab ────────────────────────────────────────────────────────────
  const saveDirEdit = async () => {
    if (!dirDraft.id) return;
    try {
      const r = await certApi.updateDirection(dirDraft.id, dirDraft);
      setData(prev => prev ? { ...prev, directions: prev.directions.map(d => d.id === r.data.id ? r.data as CertDirection : d) } : prev);
      setEditDirId(null); showToast("저장됨", "success");
    } catch { showToast("저장 실패", "error"); }
  };
  const saveNewDir = async () => {
    try {
      const r = await certApi.createDirection(newDir);
      setData(prev => prev ? { ...prev, directions: [...prev.directions, r.data as CertDirection] } : prev);
      setAddingDir(false); setNewDir({ ...EMPTY_DIR }); showToast("추가됨", "success");
    } catch { showToast("추가 실패", "error"); }
  };
  const deleteDir = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    try {
      await certApi.deleteDirection(id);
      setData(prev => prev ? { ...prev, directions: prev.directions.filter(d => d.id !== id) } : prev);
      showToast("삭제됨", "success");
    } catch (e: any) { showToast(e.response?.data?.detail || "삭제 실패", "error"); }
  };

  const saveGrpEdit = async () => {
    if (!grpDraft.id) return;
    try {
      const r = await certApi.updateGroup(grpDraft.id, grpDraft);
      setData(prev => prev ? { ...prev, groups: prev.groups.map(g => g.id === r.data.id ? r.data as CertGroup : g) } : prev);
      setEditGrpId(null); showToast("저장됨", "success");
    } catch { showToast("저장 실패", "error"); }
  };
  const saveNewGrp = async () => {
    try {
      const r = await certApi.createGroup(newGrp);
      setData(prev => prev ? { ...prev, groups: [...prev.groups, r.data as CertGroup] } : prev);
      setAddingGrp(false); setNewGrp({ ...EMPTY_GRP }); showToast("추가됨", "success");
    } catch { showToast("추가 실패", "error"); }
  };
  const deleteGrp = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    try {
      await certApi.deleteGroup(id);
      setData(prev => prev ? { ...prev, groups: prev.groups.filter(g => g.id !== id) } : prev);
      showToast("삭제됨", "success");
    } catch (e: any) { showToast(e.response?.data?.detail || "삭제 실패", "error"); }
  };

  const saveRgnEdit = async () => {
    if (!rgnDraft.id) return;
    try {
      const r = await certApi.updateRegion(rgnDraft.id, rgnDraft);
      setData(prev => prev ? { ...prev, regions: prev.regions.map(r2 => r2.id === r.data.id ? r.data as CertRegion : r2) } : prev);
      setEditRgnId(null); showToast("저장됨", "success");
    } catch { showToast("저장 실패", "error"); }
  };
  const saveNewRgn = async () => {
    try {
      const r = await certApi.createRegion(newRgn);
      setData(prev => prev ? { ...prev, regions: [...prev.regions, r.data as CertRegion] } : prev);
      setAddingRgn(false); setNewRgn({ ...EMPTY_RGN }); showToast("추가됨", "success");
    } catch { showToast("추가 실패", "error"); }
  };
  const deleteRgn = async (id: string) => {
    if (!confirm("삭제하시겠습니까?")) return;
    try {
      await certApi.deleteRegion(id);
      setData(prev => prev ? { ...prev, regions: prev.regions.filter(r => r.id !== id) } : prev);
      showToast("삭제됨", "success");
    } catch (e: any) { showToast(e.response?.data?.detail || "삭제 실패", "error"); }
  };

  // ── 정합성 요약 + 경고(6-3) ──────────────────────────────────────────────
  const DiagSummaryCard = ({ label, d }: { label: string; d: ClassDiag | null }) => {
    const errCount = (d?.orphanUsed.length ?? 0) + (d?.duplicateNames.length ?? 0) + (d?.inactiveButUsed.length ?? 0);
    return (
      <div style={{ flex: 1, minWidth: 160, border: "1px solid #E2E8F0", borderRadius: 8, padding: "10px 12px" }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#4A5568", marginBottom: 6 }}>{label}</div>
        <div style={{ fontSize: 11.5, color: "#718096", lineHeight: 1.7 }}>
          전체 {d?.total ?? 0} · 활성 {d?.active ?? 0} · 비활성 {d?.inactive ?? 0}<br />
          사용중 {d?.usedCount ?? 0} · 미사용 {(d?.total ?? 0) - (d?.usedCount ?? 0)}<br />
          <span style={{ color: errCount > 0 ? "#C53030" : "#718096" }}>오류 {errCount}</span>
          {" · "}고아값 {d?.orphanUsed.length ?? 0} · 표기중복 {d?.duplicateNames.length ?? 0}
        </div>
      </div>
    );
  };
  const diagWarnings: { level: "error" | "warn"; text: string; jumpTo?: string }[] = [
    ...(dirDiag?.orphanUsed.map(v => ({ level: "error" as const, text: `대분류 "${v}" — 가격조건에서 사용되지만 대분류 목록에 없음(고아 값)`, jumpTo: v })) ?? []),
    ...(grpDiag?.orphanUsed.map(v => ({ level: "error" as const, text: `중분류 ID "${v}" — 가격조건에서 사용되지만 중분류 목록에 없음(고아 값)` })) ?? []),
    ...(rgnDiag?.orphanUsed.map(v => ({ level: "error" as const, text: `소분류/지역 "${v}" — 가격조건에서 사용되지만 목록에 없음(고아 값)`, jumpTo: v })) ?? []),
    ...(dirDiag?.inactiveButUsed.map(v => ({ level: "warn" as const, text: `대분류 "${v}" — 비활성 상태인데 사용 중인 가격조건이 있음`, jumpTo: v })) ?? []),
    ...(grpDiag?.inactiveButUsed.map(v => ({ level: "warn" as const, text: `중분류 "${v}" — 비활성 상태인데 사용 중인 가격조건이 있음`, jumpTo: v })) ?? []),
    ...(rgnDiag?.inactiveButUsed.map(v => ({ level: "warn" as const, text: `소분류/지역 "${v}" — 비활성 상태인데 사용 중인 가격조건이 있음`, jumpTo: v })) ?? []),
    ...(dirDiag?.duplicateNames.map(v => ({ level: "warn" as const, text: `대분류 "${v}" — 동일한 표시명이 중복 등록됨`, jumpTo: v })) ?? []),
    ...(grpDiag?.duplicateNames.map(v => ({ level: "warn" as const, text: `중분류 "${v}" — 동일한 표시명이 중복 등록됨`, jumpTo: v })) ?? []),
    ...(rgnDiag?.duplicateNames.map(v => ({ level: "warn" as const, text: `소분류/지역 "${v}" — 동일한 표시명이 중복 등록됨`, jumpTo: v })) ?? []),
  ];
  const DiagPanel = (
    <div style={{ marginBottom: 20, border: "1px solid #E2E8F0", borderRadius: 10, padding: 16, background: "#F9FAFB" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 10, flex: 1, flexWrap: "wrap" }}>
          <DiagSummaryCard label="대분류" d={dirDiag} />
          <DiagSummaryCard label="중분류" d={grpDiag} />
          <DiagSummaryCard label="소분류/지역" d={rgnDiag} />
        </div>
        <Btn onClick={() => setShowDiag(s => !s)} size="sm">
          {showDiag ? <ChevronUp size={13} /> : <ChevronDown size={13} />} 정합성 검사 {diagWarnings.length > 0 ? `(${diagWarnings.length})` : ""}
        </Btn>
      </div>
      {showDiag && (
        diagWarnings.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#276749" }}>
            <CheckCircle2 size={14} /> 정합성 경고 없음 — 고아 값·중복 표시명·비활성 사용 없음
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {diagWarnings.map((w, i) => (
              <div key={i}
                onClick={w.jumpTo ? () => {
                  setTreeSearch(w.jumpTo!); setTreeErrorsOnly(false); setTreeActive("all"); setTreeUsed("all");
                  setExpandedDirs(new Set((data?.directions ?? []).map(d => d.id)));
                } : undefined}
                style={{
                display: "flex", alignItems: "flex-start", gap: 6, fontSize: 12.5,
                color: w.level === "error" ? "#822727" : "#744210",
                background: w.level === "error" ? "#FFF5F5" : "#FFFBEB",
                border: `1px solid ${w.level === "error" ? "#FEB2B2" : "#F6E05E"}`,
                borderRadius: 6, padding: "6px 10px", cursor: w.jumpTo ? "pointer" : "default",
              }}>
                <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 1 }} /> {w.text}
                {w.jumpTo && <span style={{ marginLeft: "auto", fontSize: 11, textDecoration: "underline", flexShrink: 0 }}>해당 분류로 이동</span>}
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );

  // ── 계층형 분류관리 트리(6-3) ────────────────────────────────────────────────
  const dirUsage = useMemo(() => {
    const m = new Map<string, number>();
    (data?.prices ?? []).forEach(p => { if (p.direction) m.set(p.direction, (m.get(p.direction) ?? 0) + 1); });
    return m;
  }, [data]);
  const grpUsage = useMemo(() => {
    const m = new Map<string, number>();
    (data?.prices ?? []).forEach(p => { if (p.group_id) m.set(p.group_id, (m.get(p.group_id) ?? 0) + 1); });
    return m;
  }, [data]);
  const rgnUsage = useMemo(() => {
    const m = new Map<string, number>();
    (data?.prices ?? []).forEach(p => { if (p.region) m.set(p.region, (m.get(p.region) ?? 0) + 1); });
    return m;
  }, [data]);
  const isActiveVal = (a: string) => a === "true" || a === "TRUE";

  const [treeSearch, setTreeSearch] = useState("");
  const [treeActive, setTreeActive] = useState<"all" | "active" | "inactive">("all");
  const [treeUsed, setTreeUsed] = useState<"all" | "used" | "unused">("all");
  const [treeErrorsOnly, setTreeErrorsOnly] = useState(false);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [expandedGrps, setExpandedGrps] = useState<Set<string>>(new Set());
  const [connectedView, setConnectedView] = useState<{ label: string; rows: CertPrice[] } | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<{
    kind: "dir" | "grp" | "rgn"; id: string; name: string; usage: number;
  } | null>(null);

  const dirHasErr = useMemo(() => new Set(dirDiag?.duplicateNames.length ? (data?.directions ?? []).filter(d => (dirDiag.duplicateNames.includes(d.name))).map(d => d.id) : []), [dirDiag, data]);
  const grpHasErr = useMemo(() => new Set((data?.groups ?? []).filter(g => grpDiag?.duplicateNames.includes(g.group_name)).map(g => g.id)), [grpDiag, data]);
  const rgnHasErr = useMemo(() => new Set((data?.regions ?? []).filter(r => rgnDiag?.duplicateNames.includes(r.name) || rgnDiag?.inactiveButUsed.includes(r.name)).map(r => r.id)), [rgnDiag, data]);

  const matchesCommon = (name: string, active: string, usage: number, hasErr: boolean) => {
    if (treeSearch.trim() && !name.toLowerCase().includes(treeSearch.trim().toLowerCase())) return false;
    if (treeActive === "active" && !isActiveVal(active)) return false;
    if (treeActive === "inactive" && isActiveVal(active)) return false;
    if (treeUsed === "used" && usage === 0) return false;
    if (treeUsed === "unused" && usage > 0) return false;
    if (treeErrorsOnly && !hasErr) return false;
    return true;
  };

  const showConnected = (label: string, matchFn: (p: CertPrice) => boolean) => {
    setConnectedView({ label, rows: (data?.prices ?? []).filter(matchFn) });
  };

  const requestDeactivate = (kind: "dir" | "grp" | "rgn", id: string, name: string, usage: number) => {
    setDeactivateTarget({ kind, id, name, usage });
  };
  const runDeactivate = async () => {
    if (!deactivateTarget) return;
    const { kind, id } = deactivateTarget;
    try {
      if (kind === "dir") await certApi.updateDirection(id, { active: "false" });
      else if (kind === "grp") await certApi.updateGroup(id, { active: "false" });
      else await certApi.updateRegion(id, { active: "false" });
      setData(prev => {
        if (!prev) return prev;
        if (kind === "dir") return { ...prev, directions: prev.directions.map(d => d.id === id ? { ...d, active: "false" } : d) };
        if (kind === "grp") return { ...prev, groups: prev.groups.map(g => g.id === id ? { ...g, active: "false" } : g) };
        return { ...prev, regions: prev.regions.map(r => r.id === id ? { ...r, active: "false" } : r) };
      });
      showToast("비활성화됨", "success");
    } catch { showToast("비활성화 실패", "error"); }
    setDeactivateTarget(null);
  };
  const runDeleteWithGuard = async (
    kind: "dir" | "grp" | "rgn", id: string, name: string, usage: number, del: (id: string) => Promise<void>,
  ) => {
    if (usage > 0) { requestDeactivate(kind, id, name, usage); return; }
    if (!confirm(`"${name}"을(를) 삭제하시겠습니까?`)) return;
    await del(id);
  };

  // 대분류에 속한 중분류/지역 판정 — 검색 드롭다운(visibleGroups/visibleRegions)과 동일 로직 재사용.
  const groupsOfDir = (dirName: string) => (data?.groups ?? []).filter(g => {
    const extra = (g.applicable_directions ?? "").split(",").map(s => s.trim()).filter(Boolean);
    return g.default_direction === dirName || extra.includes(dirName);
  });
  const regionsOfGroup = (grpId: string) => (data?.regions ?? []).filter(r => {
    const grps = (r.applicable_group_ids ?? "").split(",").map(s => s.trim()).filter(Boolean);
    return grps.includes(grpId);
  });
  const regionsUnrestricted = () => (data?.regions ?? []).filter(r =>
    !(r.applicable_directions ?? "").trim() && !(r.applicable_group_ids ?? "").trim());

  const RowActions = ({ onEdit, onView, onDeactivate, onDelete, active }: {
    onEdit: () => void; onView: () => void; onDeactivate?: () => void; onDelete: () => void; active: boolean;
  }) => (
    <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
      <button onClick={onView} title="연결 업무 보기" style={{ background: "none", border: "none", cursor: "pointer", color: "#718096" }}><Search size={12} /></button>
      <button onClick={onEdit} title="수정" style={{ background: "none", border: "none", cursor: "pointer", color: "#3B82F6" }}><Edit2 size={12} /></button>
      {active && onDeactivate && (
        <button onClick={onDeactivate} title="비활성화" style={{ background: "none", border: "none", cursor: "pointer", color: "#D97706" }}><EyeOff size={12} /></button>
      )}
      <button onClick={onDelete} title="삭제" style={{ background: "none", border: "none", cursor: "pointer", color: "#EF4444" }}><Trash2 size={12} /></button>
    </div>
  );

  // 함수 호출 방식으로 렌더(ClassList 와 동일 이유 — JSX 컴포넌트로 쓰면 매 렌더 리마운트로 입력 포커스 손실).
  function RgnRow({ r, usage }: { r: CertRegion; usage: number }) {
    if (editRgnId === r.id) {
      return (
        <div style={{ border: "1px solid #3B82F6", borderRadius: 6, padding: 8 }}>
          <Input label="이름" value={rgnDraft.name ?? ""} onChange={v => setRgnDraft({ ...rgnDraft, name: v })} />
          <Input label="정렬순서" value={rgnDraft.sort_order ?? "0"} onChange={v => setRgnDraft({ ...rgnDraft, sort_order: v })} />
          <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
            <Btn onClick={saveRgnEdit} color="green" size="xs"><Save size={11} /> 저장</Btn>
            <Btn onClick={() => setEditRgnId(null)} size="xs"><X size={11} /> 취소</Btn>
          </div>
        </div>
      );
    }
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
        <span style={{ flex: 1 }}>📍 {r.name} <span style={{ fontSize: 10, color: "#A0AEC0" }}>({r.id})</span></span>
        <span style={{ fontSize: 10.5, color: isActiveVal(r.active) ? "#276749" : "#A0AEC0" }}>{isActiveVal(r.active) ? "활성" : "비활성"}</span>
        <span style={{ fontSize: 10.5, color: "#718096" }}>사용 {usage}건</span>
        <RowActions active={isActiveVal(r.active)}
          onEdit={() => { setEditRgnId(r.id); setRgnDraft({ ...r }); }}
          onView={() => showConnected(`소분류/지역: ${r.name}`, p => p.region === r.name)}
          onDeactivate={() => requestDeactivate("rgn", r.id, r.name, usage)}
          onDelete={() => runDeleteWithGuard("rgn", r.id, r.name, usage, deleteRgn)} />
      </div>
    );
  }

  const ClassificationTab = (
    <div>
      {DiagPanel}

      {/* 필터 */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
        <input value={treeSearch} onChange={e => setTreeSearch(e.target.value)} placeholder="분류명 검색"
          style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13, minWidth: 160 }} />
        <select value={treeActive} onChange={e => setTreeActive(e.target.value as any)}
          style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13 }}>
          <option value="all">활성/비활성 전체</option>
          <option value="active">활성만</option>
          <option value="inactive">비활성만</option>
        </select>
        <select value={treeUsed} onChange={e => setTreeUsed(e.target.value as any)}
          style={{ padding: "5px 10px", borderRadius: 6, border: "1px solid #CBD5E0", fontSize: 13 }}>
          <option value="all">사용여부 전체</option>
          <option value="used">사용 중만</option>
          <option value="unused">미사용만</option>
        </select>
        <label style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, color: "#4A5568", cursor: "pointer" }}>
          <input type="checkbox" checked={treeErrorsOnly} onChange={e => setTreeErrorsOnly(e.target.checked)} /> 오류만 보기
        </label>
        <button onClick={() => setExpandedDirs(new Set((data?.directions ?? []).map(d => d.id)))}
          style={{ marginLeft: "auto", fontSize: 12, padding: "4px 10px", borderRadius: 6, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer" }}>전체 펼치기</button>
        <button onClick={() => { setExpandedDirs(new Set()); setExpandedGrps(new Set()); }}
          style={{ fontSize: 12, padding: "4px 10px", borderRadius: 6, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer" }}>전체 접기</button>
      </div>

      {/* 대분류 추가 */}
      <div style={{ marginBottom: 12 }}>
        {addingDir ? (
          <div style={{ border: "2px dashed #3B82F6", borderRadius: 8, padding: 12, background: "#EFF6FF" }}>
            <Input label="이름" value={newDir.name ?? ""} onChange={v => setNewDir({ ...newDir, name: v })} />
            <Input label="정렬순서" value={newDir.sort_order ?? "0"} onChange={v => setNewDir({ ...newDir, sort_order: v })} />
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <Btn onClick={saveNewDir} color="green" size="xs"><Save size={11} /> 저장</Btn>
              <Btn onClick={() => setAddingDir(false)} size="xs"><X size={11} /> 취소</Btn>
            </div>
          </div>
        ) : (
          <Btn onClick={() => { setAddingDir(true); setNewDir({ ...EMPTY_DIR }); }} color="green" size="xs"><Plus size={12} /> 대분류 추가</Btn>
        )}
      </div>

      {/* 트리 */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {(data?.directions ?? [])
          .filter(d => matchesCommon(d.name, d.active, dirUsage.get(d.name) ?? 0, dirHasErr.has(d.id)))
          .map(d => {
            const dUsage = dirUsage.get(d.name) ?? 0;
            const isOpen = expandedDirs.has(d.id);
            const groups = groupsOfDir(d.name).filter(g => matchesCommon(g.group_name, g.active, grpUsage.get(g.id) ?? 0, grpHasErr.has(g.id)));
            const commonRegions = regionsUnrestricted().filter(r => matchesCommon(r.name, r.active, rgnUsage.get(r.name) ?? 0, rgnHasErr.has(r.id)));
            return (
              <div key={d.id} style={{ border: "1px solid #E2E8F0", borderRadius: 10, background: "#fff", overflow: "hidden" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", background: "#F9FAFB" }}>
                  <button onClick={() => setExpandedDirs(s => { const n = new Set(s); n.has(d.id) ? n.delete(d.id) : n.add(d.id); return n; })}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#4A5568" }}>
                    {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </button>
                  {editDirId === d.id ? (
                    <div style={{ flex: 1 }}>
                      <Input label="이름" value={dirDraft.name ?? ""} onChange={v => setDirDraft({ ...dirDraft, name: v })} />
                      <Input label="정렬순서" value={dirDraft.sort_order ?? "0"} onChange={v => setDirDraft({ ...dirDraft, sort_order: v })} />
                      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                        <Btn onClick={saveDirEdit} color="green" size="xs"><Save size={11} /> 저장</Btn>
                        <Btn onClick={() => setEditDirId(null)} size="xs"><X size={11} /> 취소</Btn>
                      </div>
                    </div>
                  ) : (
                    <>
                      <span style={{ fontSize: 14, fontWeight: 700, color: "#1A202C", flex: 1 }}>
                        📁 {d.name} <span style={{ fontSize: 11, fontWeight: 400, color: "#A0AEC0" }}>({d.id})</span>
                      </span>
                      <span style={{ fontSize: 11, color: isActiveVal(d.active) ? "#276749" : "#A0AEC0" }}>{isActiveVal(d.active) ? "활성" : "비활성"}</span>
                      <span style={{ fontSize: 11, color: "#718096" }}>사용 {dUsage}건</span>
                      <RowActions active={isActiveVal(d.active)}
                        onEdit={() => { setEditDirId(d.id); setDirDraft({ ...d }); }}
                        onView={() => showConnected(`대분류: ${d.name}`, p => p.direction === d.name)}
                        onDeactivate={() => requestDeactivate("dir", d.id, d.name, dUsage)}
                        onDelete={() => runDeleteWithGuard("dir", d.id, d.name, dUsage, deleteDir)} />
                    </>
                  )}
                </div>

                {isOpen && (
                  <div style={{ padding: "8px 12px 12px 28px", display: "flex", flexDirection: "column", gap: 6 }}>
                    {addingGrp ? (
                      <div style={{ border: "2px dashed #3B82F6", borderRadius: 8, padding: 10, background: "#EFF6FF" }}>
                        <Input label="그룹명" value={newGrp.group_name ?? ""} onChange={v => setNewGrp({ ...newGrp, group_name: v })} />
                        <Input label="별칭/키워드" value={newGrp.aliases ?? ""} onChange={v => setNewGrp({ ...newGrp, aliases: v })} multiline />
                        <Select label="기본 대분류" value={newGrp.default_direction ?? d.name} onChange={v => setNewGrp({ ...newGrp, default_direction: v })} options={dirOpts} />
                        <Input label="정렬순서" value={newGrp.sort_order ?? "0"} onChange={v => setNewGrp({ ...newGrp, sort_order: v })} />
                        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                          <Btn onClick={saveNewGrp} color="green" size="xs"><Save size={11} /> 저장</Btn>
                          <Btn onClick={() => setAddingGrp(false)} size="xs"><X size={11} /> 취소</Btn>
                        </div>
                      </div>
                    ) : (
                      <Btn onClick={() => { setAddingGrp(true); setNewGrp({ ...EMPTY_GRP, default_direction: d.name }); }} color="green" size="xs"><Plus size={11} /> 중분류 추가</Btn>
                    )}

                    {groups.map(g => {
                      const gUsage = grpUsage.get(g.id) ?? 0;
                      const gOpen = expandedGrps.has(g.id);
                      const rgns = regionsOfGroup(g.id).filter(r => matchesCommon(r.name, r.active, rgnUsage.get(r.name) ?? 0, rgnHasErr.has(r.id)));
                      return (
                        <div key={g.id} style={{ border: "1px solid #EDF2F7", borderRadius: 8 }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px" }}>
                            <button onClick={() => setExpandedGrps(s => { const n = new Set(s); n.has(g.id) ? n.delete(g.id) : n.add(g.id); return n; })}
                              style={{ background: "none", border: "none", cursor: "pointer", color: "#4A5568" }}>
                              {gOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                            </button>
                            {editGrpId === g.id ? (
                              <div style={{ flex: 1 }}>
                                <Input label="그룹명" value={grpDraft.group_name ?? ""} onChange={v => setGrpDraft({ ...grpDraft, group_name: v })} />
                                <Input label="별칭/키워드" value={grpDraft.aliases ?? ""} onChange={v => setGrpDraft({ ...grpDraft, aliases: v })} multiline />
                                <Select label="기본 대분류" value={grpDraft.default_direction ?? ""} onChange={v => setGrpDraft({ ...grpDraft, default_direction: v })} options={dirOpts} />
                                <Input label="정렬순서" value={grpDraft.sort_order ?? "0"} onChange={v => setGrpDraft({ ...grpDraft, sort_order: v })} />
                                <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                                  <Btn onClick={saveGrpEdit} color="green" size="xs"><Save size={11} /> 저장</Btn>
                                  <Btn onClick={() => setEditGrpId(null)} size="xs"><X size={11} /> 취소</Btn>
                                </div>
                              </div>
                            ) : (
                              <>
                                <span style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>
                                  📂 {g.group_name} <span style={{ fontSize: 10.5, fontWeight: 400, color: "#A0AEC0" }}>({g.id})</span>
                                </span>
                                <span style={{ fontSize: 10.5, color: isActiveVal(g.active) ? "#276749" : "#A0AEC0" }}>{isActiveVal(g.active) ? "활성" : "비활성"}</span>
                                <span style={{ fontSize: 10.5, color: "#718096" }}>사용 {gUsage}건</span>
                                <RowActions active={isActiveVal(g.active)}
                                  onEdit={() => { setEditGrpId(g.id); setGrpDraft({ ...g }); }}
                                  onView={() => showConnected(`중분류: ${g.group_name}`, p => p.group_id === g.id)}
                                  onDeactivate={() => requestDeactivate("grp", g.id, g.group_name, gUsage)}
                                  onDelete={() => runDeleteWithGuard("grp", g.id, g.group_name, gUsage, deleteGrp)} />
                              </>
                            )}
                          </div>
                          {gOpen && (
                            <div style={{ padding: "4px 10px 8px 24px", display: "flex", flexDirection: "column", gap: 4 }}>
                              {rgns.length === 0 && <div style={{ fontSize: 11, color: "#A0AEC0" }}>이 중분류에만 한정된 소분류/지역 없음(공통 지역은 대분류 하단 "공통" 참조)</div>}
                              {rgns.map(r => (
                                <div key={r.id}>{RgnRow({ r, usage: rgnUsage.get(r.name) ?? 0 })}</div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}

                    {/* 공통(전체 지역 무관) 소분류/지역 */}
                    {commonRegions.length > 0 && (
                      <div style={{ border: "1px solid #EDF2F7", borderRadius: 8, padding: "7px 10px" }}>
                        <div style={{ fontSize: 11.5, fontWeight: 600, color: "#718096", marginBottom: 4 }}>🌐 공통(대분류·중분류 무관 전체 적용)</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                          {commonRegions.map(r => <div key={r.id}>{RgnRow({ r, usage: rgnUsage.get(r.name) ?? 0 })}</div>)}
                        </div>
                      </div>
                    )}
                    {addingRgn ? (
                      <div style={{ border: "2px dashed #3B82F6", borderRadius: 8, padding: 10, background: "#EFF6FF" }}>
                        <Input label="이름" value={newRgn.name ?? ""} onChange={v => setNewRgn({ ...newRgn, name: v })} />
                        <Input label="정렬순서" value={newRgn.sort_order ?? "0"} onChange={v => setNewRgn({ ...newRgn, sort_order: v })} />
                        <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                          <Btn onClick={saveNewRgn} color="green" size="xs"><Save size={11} /> 저장</Btn>
                          <Btn onClick={() => setAddingRgn(false)} size="xs"><X size={11} /> 취소</Btn>
                        </div>
                      </div>
                    ) : (
                      <Btn onClick={() => { setAddingRgn(true); setNewRgn({ ...EMPTY_RGN }); }} color="green" size="xs"><Plus size={11} /> 소분류/지역 추가</Btn>
                    )}
                  </div>
                )}
              </div>
            );
          })}
      </div>

      {/* 연결 업무 보기 */}
      {connectedView && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 600, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
          onClick={() => setConnectedView(null)}>
          <div style={{ background: "#fff", borderRadius: 12, width: "min(700px, 100%)", maxHeight: "80vh", overflowY: "auto", padding: 18 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: 14 }}>{connectedView.label} — 연결된 가격조건 {connectedView.rows.length}건</div>
              <button onClick={() => setConnectedView(null)} style={{ background: "none", border: "none", cursor: "pointer" }}><X size={16} /></button>
            </div>
            {connectedView.rows.length === 0 ? (
              <div style={{ color: "#A0AEC0", fontSize: 13 }}>연결된 가격조건이 없습니다(미사용).</div>
            ) : (
              <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                <thead><tr style={{ borderBottom: "1px solid #E2E8F0" }}>
                  <th style={{ textAlign: "left", padding: 4 }}>방향</th><th style={{ textAlign: "left", padding: 4 }}>지역</th>
                  <th style={{ textAlign: "left", padding: 4 }}>조건</th><th style={{ textAlign: "left", padding: 4 }}>가격</th>
                </tr></thead>
                <tbody>
                  {connectedView.rows.map(p => (
                    <tr key={p.id} style={{ borderBottom: "1px solid #F0F0F0" }}>
                      <td style={{ padding: 4 }}>{p.direction}</td><td style={{ padding: 4 }}>{p.region}</td>
                      <td style={{ padding: 4 }}>{p.condition}</td><td style={{ padding: 4 }}>{fmt(p.price)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* 비활성화 확인(사용 중인 분류 삭제 시도 시) */}
      {deactivateTarget && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 600, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
          onClick={() => setDeactivateTarget(null)}>
          <div style={{ background: "#fff", borderRadius: 12, width: "min(420px, 100%)", padding: 18 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
              <AlertTriangle size={16} style={{ color: "#D97706" }} />
              <span style={{ fontWeight: 700, fontSize: 14 }}>사용 중인 분류입니다</span>
            </div>
            <div style={{ fontSize: 13, color: "#4A5568", marginBottom: 14, lineHeight: 1.6 }}>
              <strong>{deactivateTarget.name}</strong>을(를) 사용하는 가격조건이 <strong>{deactivateTarget.usage}건</strong> 있어
              즉시 삭제할 수 없습니다. 먼저 비활성화하시겠습니까? (기존 가격조건은 그대로 유지되고, 새 검색·등록에서만 숨겨집니다.)
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <Btn onClick={() => setDeactivateTarget(null)}>취소</Btn>
              <Btn onClick={runDeactivate} color="blue">비활성화</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // ── Render ─────────────────────────────────────────────────────────────────
  const TABS: { key: Tab; label: string }[] = [
    { key: "comparison", label: "비교화면" },
    { key: "db", label: "DB관리" },
    { key: "vendors", label: "업체관리" },
    { key: "classification", label: "분류관리" },
  ];

  if (loading) return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <RefreshCw size={20} style={{ animation: "spin 1s linear infinite", display: "inline-block" }} />
      &nbsp;로딩 중...
    </div>
  );

  if (error) return (
    <div style={{ padding: 40, textAlign: "center", color: "#EF4444" }}>
      오류: {error}
      <div style={{ marginTop: 10 }}><Btn onClick={load} size="sm"><RefreshCw size={13} /> 재시도</Btn></div>
    </div>
  );

  return (
    <div style={{ padding: "20px 24px", maxWidth: 1400, margin: "0 auto" }}>
      {toast && <Toast msg={toast.msg} type={toast.type} onClose={() => setToast(null)} />}

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 800, color: "#1A202C", margin: 0 }}>기타업무참고</h1>
        <button onClick={load} style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 12px", border: "1px solid #CBD5E0", borderRadius: 6, background: "#fff", cursor: "pointer", fontSize: 13, color: "#4A5568" }}>
          <RefreshCw size={13} /> 새로고침
        </button>
      </div>

      {/* 예시(샘플) 데이터 안내 — 샘플 항목이 있을 때만 표시 */}
      {(() => {
        const named = [
          ...(data?.vendors ?? []).map(v => v.name),
          ...(data?.directions ?? []).map(d => d.name),
          ...(data?.groups ?? []).map(g => g.group_name),
          ...(data?.regions ?? []).map(r => r.name),
        ];
        const hasSample = named.some(n => (n ?? "").includes("[예시]")) ||
          (data?.prices ?? []).some(p => p.source === "new_tenant_sample_v1");
        return hasSample ? (
          <div style={{
            background: "#EBF8FF", border: "1px solid #BEE3F8", borderRadius: 6,
            padding: "8px 16px", fontSize: 12, color: "#2B6CB0", marginBottom: 12,
          }}>
            현재 표시된 일부 항목은 예시 데이터입니다. 실제 업무 기준에 맞게 수정하거나 삭제하세요.
          </div>
        ) : null;
      })()}

      {/* Tabs */}
      <div style={{ display: "flex", gap: 0, borderBottom: "1px solid #E2E8F0", marginBottom: 16 }}>
        {TABS.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: "8px 20px", border: "none", cursor: "pointer", fontSize: 14, fontWeight: tab === t.key ? 700 : 400,
              background: "none", color: tab === t.key ? "#3B82F6" : "#718096",
              borderBottom: tab === t.key ? "2px solid #3B82F6" : "2px solid transparent",
            }}>{t.label}</button>
        ))}
      </div>

      {/* Filter bar — shown for comparison and db tabs */}
      {(tab === "comparison" || tab === "db") && FilterBar}

      {tab === "comparison" && ComparisonTab}
      {tab === "db" && DBTab}
      {tab === "vendors" && VendorsTab}
      {tab === "classification" && ClassificationTab}

      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
