"use client";
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  certApi,
  CertBootstrap, CertVendor, CertDirection, CertGroup, CertRegion, CertPrice,
} from "@/lib/api";
import { RefreshCw, Plus, Trash2, Edit2, Save, X, Copy, Search } from "lucide-react";

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
    width: "100%", padding: "5px 8px", border: "1px solid #CBD5E0", borderRadius: 6,
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
        style={{ width: "100%", padding: "5px 8px", border: "1px solid #CBD5E0", borderRadius: 6, fontSize: 13, background: "#fff" }}>
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
        setError("구글시트 읽기 한도를 초과했습니다. 잠시 후 다시 시도하거나 새로고침 횟수를 줄여주세요.");
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

  // PriceForm: 대분류 선택에 따라 중분류/소분류 후보를 동적으로 계산
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

    // 대분류+중분류 기준 소분류 후보
    const formRgns = allRegions.filter(r => {
      const dirs = (r.applicable_directions ?? "").split(",").map(s => s.trim()).filter(Boolean);
      const grps = (r.applicable_group_ids ?? "").split(",").map(s => s.trim()).filter(Boolean);
      if (draft.direction) {
        if (dirs.length > 0 && !dirs.includes(draft.direction)) return false;
        if ((draft.direction === "중국 → 한국" || draft.direction === "중국 현지 내부처리") && r.name === "한국") return false;
      }
      if (draft.group_id) {
        if (grps.length > 0 && !grps.includes(draft.group_id)) return false;
      }
      return true;
    });

    // 현재 region 이 후보에 없으면 보존
    const rgnInVisible = !draft.region || formRgns.some(r => r.name === draft.region);
    const formRgnOpts = [
      ...(!rgnInVisible && draft.region
        ? [{ value: draft.region, label: `현재값: ${draft.region}` }]
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
          <PriceForm draft={newPrice} setDraft={setNewPrice} />
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
                <PriceForm draft={priceDraft} setDraft={setPriceDraft} />
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
          <VendorForm draft={newVendor} setDraft={setNewVendor} />
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
                <VendorForm draft={vendorDraft} setDraft={setVendorDraft} />
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

  function ClassList<T extends { id: string; active: string }>({
    title, items, editId, draft, setDraft, onEdit, onSave, onCancel,
    onAdd, addingItem, newItem, setNewItem, onSaveNew, onDelete,
    renderRow, renderForm,
  }: {
    title: string; items: T[];
    editId: string | null; draft: Partial<T>; setDraft: (d: Partial<T>) => void;
    onEdit: (id: string, item: T) => void; onSave: () => void; onCancel: () => void;
    onAdd: () => void; addingItem: boolean; newItem: Partial<T>; setNewItem: (d: Partial<T>) => void;
    onSaveNew: () => void; onDelete: (id: string) => void;
    renderRow: (item: T) => React.ReactNode; renderForm: (d: Partial<T>, setD: (v: Partial<T>) => void) => React.ReactNode;
  }) {
    return (
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: "#1A202C" }}>{title}</div>
          <Btn onClick={onAdd} color="green" size="xs"><Plus size={12} /> 추가</Btn>
        </div>
        {addingItem && (
          <div style={{ border: "2px dashed #3B82F6", borderRadius: 8, padding: 12, marginBottom: 10, background: "#EFF6FF" }}>
            {renderForm(newItem, setNewItem as any)}
            <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
              <Btn onClick={onSaveNew} color="green" size="xs"><Save size={11} /> 저장</Btn>
              <Btn onClick={onCancel} size="xs"><X size={11} /> 취소</Btn>
            </div>
          </div>
        )}
        {items.map(item => (
          <div key={item.id} style={{ border: editId === item.id ? "2px solid #3B82F6" : "1px solid #E2E8F0", borderRadius: 8, padding: 10, marginBottom: 6, background: "#fff" }}>
            {editId === item.id ? (
              <>
                {renderForm(draft as Partial<T>, setDraft as any)}
                <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  <Btn onClick={onSave} color="green" size="xs"><Save size={11} /> 저장</Btn>
                  <Btn onClick={onCancel} size="xs"><X size={11} /> 취소</Btn>
                </div>
              </>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ flex: 1 }}>{renderRow(item)}</div>
                <Btn onClick={() => onEdit(item.id, item)} size="xs"><Edit2 size={11} /> 수정</Btn>
                <Btn onClick={() => onDelete(item.id)} color="red" size="xs"><Trash2 size={11} /></Btn>
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  const ClassificationTab = (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20 }}>
      <ClassList<CertDirection>
        title="대분류 관리" items={data?.directions ?? []}
        editId={editDirId} draft={dirDraft} setDraft={setDirDraft as any}
        onEdit={(id, item) => { setEditDirId(id); setDirDraft({ ...item }); }} onSave={saveDirEdit}
        onCancel={() => { setEditDirId(null); setAddingDir(false); }}
        onAdd={() => { setAddingDir(true); setNewDir({ ...EMPTY_DIR }); }}
        addingItem={addingDir} newItem={newDir} setNewItem={setNewDir as any} onSaveNew={saveNewDir}
        onDelete={deleteDir}
        renderRow={d => <span style={{ fontSize: 13 }}>{d.name} <span style={{ fontSize: 11, color: "#A0AEC0" }}>({d.sort_order})</span></span>}
        renderForm={(d, set) => (
          <>
            <Input label="이름" value={(d as Partial<CertDirection>).name ?? ""} onChange={v => set({ ...d, name: v } as any)} />
            <Input label="정렬순서" value={(d as Partial<CertDirection>).sort_order ?? "0"} onChange={v => set({ ...d, sort_order: v } as any)} />
          </>
        )}
      />
      <ClassList<CertGroup>
        title="중분류 관리" items={data?.groups ?? []}
        editId={editGrpId} draft={grpDraft} setDraft={setGrpDraft as any}
        onEdit={(id, item) => { setEditGrpId(id); setGrpDraft({ ...item }); }} onSave={saveGrpEdit}
        onCancel={() => { setEditGrpId(null); setAddingGrp(false); }}
        onAdd={() => { setAddingGrp(true); setNewGrp({ ...EMPTY_GRP }); }}
        addingItem={addingGrp} newItem={newGrp} setNewItem={setNewGrp as any} onSaveNew={saveNewGrp}
        onDelete={deleteGrp}
        renderRow={g => <div><span style={{ fontSize: 13, fontWeight: 600 }}>{(g as CertGroup).group_name}</span>
          {(g as CertGroup).aliases && <div style={{ fontSize: 11, color: "#718096", marginTop: 1 }}>{(g as CertGroup).aliases}</div>}</div>}
        renderForm={(d, set) => (
          <>
            <Input label="그룹명" value={(d as Partial<CertGroup>).group_name ?? ""} onChange={v => set({ ...d, group_name: v } as any)} />
            <Input label="별칭/키워드 (쉼표구분)" value={(d as Partial<CertGroup>).aliases ?? ""} onChange={v => set({ ...d, aliases: v } as any)} multiline />
            <Select label="기본 대분류" value={(d as Partial<CertGroup>).default_direction ?? ""} onChange={v => set({ ...d, default_direction: v } as any)} options={dirOpts} />
            <Input label="정렬순서" value={(d as Partial<CertGroup>).sort_order ?? "0"} onChange={v => set({ ...d, sort_order: v } as any)} />
          </>
        )}
      />
      <ClassList<CertRegion>
        title="소분류/지역 관리" items={data?.regions ?? []}
        editId={editRgnId} draft={rgnDraft} setDraft={setRgnDraft as any}
        onEdit={(id, item) => { setEditRgnId(id); setRgnDraft({ ...item }); }} onSave={saveRgnEdit}
        onCancel={() => { setEditRgnId(null); setAddingRgn(false); }}
        onAdd={() => { setAddingRgn(true); setNewRgn({ ...EMPTY_RGN }); }}
        addingItem={addingRgn} newItem={newRgn} setNewItem={setNewRgn as any} onSaveNew={saveNewRgn}
        onDelete={deleteRgn}
        renderRow={r => <span style={{ fontSize: 13 }}>{(r as CertRegion).name}</span>}
        renderForm={(d, set) => (
          <>
            <Input label="이름" value={(d as Partial<CertRegion>).name ?? ""} onChange={v => set({ ...d, name: v } as any)} />
            <Input label="정렬순서" value={(d as Partial<CertRegion>).sort_order ?? "0"} onChange={v => set({ ...d, sort_order: v } as any)} />
          </>
        )}
      />
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
        <h1 style={{ fontSize: 20, fontWeight: 800, color: "#1A202C", margin: 0 }}>각종공인증</h1>
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
