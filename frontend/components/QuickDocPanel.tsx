"use client";
import { useState, useRef, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  api,
  quickDocApi,
  type CustomerSearchResult,
  type FullDocGenRequest,
  type AccommodationProvider,
} from "@/lib/api";
import SignatureModal from "@/components/SignatureModal";
import {
  FileText, Download, Loader2, Search, X,
  RotateCcw, User, Home, Shield, Users, UserCheck, Stamp, Zap, Edit2,
} from "lucide-react";
import Link from "next/link";
import { SubmitButton } from "@/components/SubmitButton";

// ─────────────────────────────────────────────────────────────────────────
// 편집 후 재다운로드 패널 필드
// ─────────────────────────────────────────────────────────────────────────
const OVERRIDE_FIELDS: { label: string; key: string; placeholder: string }[] = [
  { label: "신청인 한글이름",   key: "koreanname", placeholder: "예: 왕소명" },
  { label: "신청인 성(영문)",   key: "Surname",    placeholder: "예: WANG" },
  { label: "신청인 이름(영문)", key: "Given names",placeholder: "예: XIAOMING" },
  { label: "신청인 주소",       key: "adress",     placeholder: "거주지 주소" },
  { label: "신청인 전화 앞",    key: "phone1",     placeholder: "010" },
  { label: "신청인 전화 중",    key: "phone2",     placeholder: "0000" },
  { label: "신청인 전화 끝",    key: "phone3",     placeholder: "0000" },
  { label: "숙소제공자 한글이름", key: "hkoreanname", placeholder: "예: 김철수" },
  { label: "숙소제공자 주소",   key: "hadress",    placeholder: "숙소 주소" },
];

const GOLD = "#D4A843";
const GOLD_LIGHT = "rgba(212,168,67,0.10)";
const BORDER = "#E2E8F0";
const GRAY_BG = "#F9FAFB";

function getLocalDateString(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function needGuarantor(cat: string, min: string, kind: string, detail: string) {
  if (cat !== "체류" || kind !== "F") return false;
  if (["등록", "연장"].includes(min)) return ["1","2","3","6"].includes(detail);
  if (min === "변경") return ["1","2","3","5","6"].includes(detail);
  if (min === "부여") return ["2","3","5"].includes(detail);
  return false;
}

function needAggregator(cat: string, min: string, kind: string, detail: string) {
  return cat === "체류" && min === "변경" && kind === "F" && detail === "5";
}

function calcIsMinor(regNo: string): boolean {
  const reg = regNo.replace(/-/g, "");
  if (reg.length < 6 || !/^\d{6}/.test(reg)) return false;
  const yy = parseInt(reg.slice(0, 2), 10);
  const now = new Date();
  const currentShort = now.getFullYear() % 100;
  const century = yy <= currentShort ? 2000 : 1900;
  try {
    const birth = new Date(century + yy, parseInt(reg.slice(2,4),10) - 1, parseInt(reg.slice(4,6),10));
    const age = Math.floor((now.getTime() - birth.getTime()) / (365.25 * 24 * 3600 * 1000));
    return age < 18;
  } catch { return false; }
}

interface RoleState {
  customer: CustomerSearchResult | null;
  directName: string;
  seal: boolean;
  sign: boolean;
  hasSignature: boolean;
  signatureLookupError?: boolean;
}

type LinkStatus = "unknown" | "loading" | "none" | "linked" | "error";

function emptyRole(sealDefault = true): RoleState {
  return { customer: null, directName: "", seal: sealDefault, sign: false, hasSignature: false, signatureLookupError: false };
}

function roleDisplayName(r: RoleState): string {
  if (r.customer) return r.customer.name;
  return r.directName.trim();
}

function roleIsSet(r: RoleState): boolean {
  return !!(r.customer || r.directName.trim());
}

interface RoleSelectorProps {
  label: string;
  icon: React.ReactNode;
  required?: boolean;
  role: RoleState;
  allowDirectInput?: boolean;
  directInputPlaceholder?: string;
  onChange: (updated: RoleState) => void;
}

function RoleSelector({
  label, icon, required = false,
  role, allowDirectInput = false, directInputPlaceholder = "이름 직접 입력",
  onChange,
}: RoleSelectorProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const isSet = roleIsSet(role);

  const searchQ = useQuery({
    queryKey: ["qd-cust", query],
    queryFn: () => quickDocApi.searchCustomers(query).then((r) => r.data),
    enabled: open && query.length >= 1,
    staleTime: 30_000,
  });

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectCustomer = async (c: CustomerSearchResult) => {
    let hasSign = false;
    try {
      const r = await fetch(`/api/signature/customer/${encodeURIComponent(c.id)}/exists`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` },
      });
      const j = await r.json();
      hasSign = j.exists ?? false;
    } catch { /* 실패 시 도장 기본값 */ }
    onChange({ ...role, customer: c, directName: "", hasSignature: hasSign, sign: hasSign, seal: !hasSign });
    setOpen(false);
    setQuery("");
  };

  const clearRole = () => { onChange({ ...role, customer: null, directName: "" }); setQuery(""); };

  return (
    <div style={{
      border: `1px solid ${isSet ? GOLD : BORDER}`,
      borderRadius: 10, padding: "10px 14px",
      background: isSet ? GOLD_LIGHT : "#FAFAFA", marginBottom: 8,
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ color: GOLD }}>{icon}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>
            {label} {required && <span style={{ color: "#E53E3E" }}>*</span>}
          </span>
          {isSet && <span style={{ fontSize: 12, color: "#276749", fontWeight: 600 }}>✅ {roleDisplayName(role)}</span>}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "#718096" }}>
          {(["sign", "seal", "none"] as const).map((opt) => {
            const labels = { sign: "서명", seal: "도장", none: "없음" };
            const isChecked =
              opt === "sign" ? role.sign :
              opt === "seal" ? (!role.sign && role.seal) :
              (!role.sign && !role.seal);
            const disabled = opt === "sign" && !role.hasSignature;
            return (
              <label key={opt} style={{ display: "flex", alignItems: "center", gap: 3, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1 }}>
                <input
                  type="radio" name={`role-opt-${label}`} checked={isChecked} disabled={disabled}
                  onChange={() => {
                    if (opt === "sign") onChange({ ...role, sign: true, seal: false });
                    else if (opt === "seal") onChange({ ...role, sign: false, seal: true });
                    else onChange({ ...role, sign: false, seal: false });
                  }}
                  style={{ accentColor: GOLD }}
                />
                {labels[opt]}
              </label>
            );
          })}
          {role.signatureLookupError && (
            <span style={{ fontSize: 10, color: "#E53E3E", marginLeft: 2 }}>서명 조회 실패</span>
          )}
        </div>
      </div>

      {!role.customer && (
        <div style={{ display: "flex", gap: 6 }}>
          <div ref={dropdownRef} style={{ position: "relative", flex: 1 }}>
            <div style={{ position: "relative" }}>
              <Search size={12} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "#A0AEC0" }} />
              <input
                value={query}
                onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
                onFocus={() => setOpen(true)}
                placeholder="고객 DB 검색"
                style={{ width: "100%", paddingLeft: 26, paddingRight: 8, padding: "7px 8px 7px 26px", border: `1px solid ${BORDER}`, borderRadius: 7, fontSize: 12, background: "#fff", boxSizing: "border-box" }}
              />
            </div>
            {open && query.length >= 1 && (
              <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50, background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.10)", maxHeight: 180, overflowY: "auto" }}>
                {searchQ.isLoading && <div style={{ padding: "8px 12px", fontSize: 12, color: "#A0AEC0" }}>검색 중...</div>}
                {!searchQ.isLoading && (searchQ.data ?? []).length === 0 && <div style={{ padding: "8px 12px", fontSize: 12, color: "#A0AEC0" }}>결과 없음</div>}
                {(searchQ.data ?? []).map((c) => (
                  <button key={c.id} onClick={() => selectCustomer(c)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 12px", fontSize: 12, background: "transparent", border: "none", cursor: "pointer", color: "#2D3748", borderBottom: `1px solid ${BORDER}` }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = GOLD_LIGHT)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    {c.name}
                    {c.name_en && <span style={{ fontSize: 10, color: "#A0AEC0", marginLeft: 4 }}>({c.name_en})</span>}
                    <span style={{ fontSize: 10, color: "#CBD5E0", marginLeft: 4 }}>{c.label.split(" / ").slice(1).join(" / ")}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
          {allowDirectInput && (
            <input
              value={role.directName}
              onChange={(e) => onChange({ ...role, directName: e.target.value })}
              placeholder={directInputPlaceholder}
              style={{ flex: 1, padding: "7px 10px", border: `1px solid ${BORDER}`, borderRadius: 7, fontSize: 12, background: "#fff" }}
            />
          )}
        </div>
      )}

      {isSet && (
        <button onClick={clearRole} style={{ fontSize: 11, color: "#A0AEC0", background: "none", border: "none", cursor: "pointer", padding: "2px 0", display: "flex", alignItems: "center", gap: 3 }}>
          <X size={10} /> 선택 해제
        </button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────
export interface QuickDocPanelProps {
  initialCustomer?: CustomerSearchResult;
  embedded?: boolean;
  onClose?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────
// Inner component (needs useSearchParams → Suspense boundary required)
// ─────────────────────────────────────────────────────────────────────────
function QuickDocPanelInner({ initialCustomer, embedded, onClose }: QuickDocPanelProps) {
  const searchParams = useSearchParams();

  const [category, setCategory] = useState("");
  const [minwon, setMinwon]     = useState("");
  const [kind, setKind]         = useState("");
  const [detail, setDetail]     = useState("");
  const [checkedDocs, setCheckedDocs]   = useState<Set<string>>(new Set());
  const [applicant, setApplicant]       = useState<RoleState>(emptyRole(true));
  const [accommodation, setAccommodation] = useState<RoleState>(emptyRole(true));
  const [guarantor, setGuarantor]       = useState<RoleState>(emptyRole(true));
  const [guardian, setGuardian]         = useState<RoleState>(emptyRole(true));
  const [aggregator, setAggregator]     = useState<RoleState>(emptyRole(true));
  const [agentSeal, setAgentSeal]   = useState(true);
  const [agentSign, setAgentSign]   = useState(false);
  const [agentHasSign, setAgentHasSign] = useState(false);
  const [pdfUrl, setPdfUrl]         = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [confirmMissing, setConfirmMissing] = useState<string[] | null>(null);
  const [showEditPanel, setShowEditPanel]     = useState(false);
  const [editOverrides, setEditOverrides]     = useState<Record<string, string>>({});
  const [lastPayload, setLastPayload]         = useState<FullDocGenRequest | null>(null);
  const [regenLoading, setRegenLoading]       = useState(false);
  const [agentInfo, setAgentInfo] = useState<{ office_name: string; contact_name: string } | null>(null);
  const [accommodationProvider, setAccommodationProvider] = useState<AccommodationProvider | null>(null);
  const [guarantorConnection, setGuarantorConnection]   = useState<import("@/lib/api").GuarantorConnection | null>(null);
  const [includeDate, setIncludeDate] = useState(true);
  const [customDate, setCustomDate]   = useState(() => getLocalDateString());
  // Explicit link-status for each related role.
  // "unknown" = before effect fires; "loading" = fetch in-flight;
  // "none" = no fixed person; "linked" = fixed person found and role applied; "error" = fetch/parse failure.
  const [accommodationStatus, setAccommodationStatus] = useState<LinkStatus>("unknown");
  const [guarantorStatus, setGuarantorStatus]         = useState<LinkStatus>("unknown");

  // 행정사 정보 + 서명 확인
  useEffect(() => {
    const raw = typeof window !== "undefined" ? localStorage.getItem("user_info") : null;
    if (raw) { try { setAgentInfo(JSON.parse(raw)); } catch { /* ignore */ } }
    api.get<{ data: string | null }>("/api/signature/agent")
      .then((r) => {
        if (r.data.data) { setAgentHasSign(true); setAgentSign(true); setAgentSeal(false); }
        else { setAgentHasSign(false); setAgentSign(false); setAgentSeal(true); }
      })
      .catch(() => {});
  }, []);

  // 딥링크 파라미터 처리 (독립 페이지 모드에서만)
  useEffect(() => {
    if (embedded) return;
    const paramCategory = searchParams.get("category");
    const paramMinwon   = searchParams.get("minwon");
    const paramKind     = searchParams.get("kind");
    const paramDetail   = searchParams.get("detail");
    const fromLabel     = searchParams.get("from_label");
    if (!paramCategory) return;
    if (paramCategory) setCategory(paramCategory);
    if (paramMinwon)   setMinwon(paramMinwon);
    if (paramKind)     setKind(paramKind);
    if (paramDetail)   setDetail(paramDetail);
    if (fromLabel) toast.info(`실무지침에서 이동: ${fromLabel}`, { duration: 3000 });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // initialCustomer → 신청인 자동 설정 + 숙소제공자/신원보증인 preload
  const initId = initialCustomer?.id;
  useEffect(() => {
    if (!initId || !initialCustomer) {
      // No customer — no linked roles to check. Both are "none" (not applicable).
      setAccommodationStatus("none");
      setGuarantorStatus("none");
      return;
    }
    let cancelled = false;
    setAccommodationStatus("loading");
    setGuarantorStatus("loading");
    const authHeader = { Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` };

    // Per-effect signature lookup deduplication.
    // When accommodation provider and guarantor share the same customer_id (e.g. 2026051104),
    // only one GET /api/signature/customer/{id}/exists request is sent; both roles await the same Promise.
    type SignatureStatus = { hasSignature: boolean; signatureLookupError: boolean };
    const signatureStatusCache = new Map<string, Promise<SignatureStatus>>();
    const checkSignatureOnce = (customerId: string): Promise<SignatureStatus> => {
      const key = String(customerId || "").trim();
      if (!key) return Promise.resolve({ hasSignature: false, signatureLookupError: false });
      const cached = signatureStatusCache.get(key);
      if (cached) return cached;
      const promise = fetch(`/api/signature/customer/${encodeURIComponent(key)}/exists`, { headers: authHeader })
        .then(async (sr) => {
          if (!sr.ok) return { hasSignature: false, signatureLookupError: true };
          const sj = await sr.json();
          return { hasSignature: !!sj.exists, signatureLookupError: false };
        })
        .catch((err: unknown) => {
          console.warn("[QuickDoc] 서명 조회 실패:", key, err);
          return { hasSignature: false, signatureLookupError: true };
        });
      signatureStatusCache.set(key, promise);
      return promise;
    };

    // 1) 신청인 서명 확인
    checkSignatureOnce(initId)
      .then((s) => {
        if (cancelled) return;
        setApplicant({ customer: initialCustomer, directName: "", hasSignature: s.hasSignature, sign: s.hasSignature, seal: !s.hasSignature, signatureLookupError: s.signatureLookupError });
      });

    // 2) 숙소제공자 preload → 관계 API + 서명 확인 후 단일 setAccommodation
    // Status transitions: "loading" → "none" | "linked" | "error"
    fetch(`/api/customers/${encodeURIComponent(initId)}/accommodation-provider`, { headers: authHeader })
      .then(async (r) => {
        // 404 = no fixed provider linked (not an error, just "none")
        if (!r.ok) { if (!cancelled) setAccommodationStatus("none"); return; }
        let p: unknown;
        try { p = await r.json(); } catch { if (!cancelled) setAccommodationStatus("error"); return; }
        if (cancelled) return;
        if (!p || typeof p !== "object") { setAccommodationStatus("error"); return; }
        const pd = p as Record<string, unknown>;
        setAccommodationProvider(pd as unknown as AccommodationProvider);
        if (pd.provider_type === "customer_db" && pd.provider_customer_id) {
          const linkedId = String(pd.provider_customer_id);
          const customerObj: CustomerSearchResult = {
            id: linkedId, name: String(pd.provider_name || ""),
            label: String(pd.provider_name || ""), reg_no: String(pd.provider_reg_front || ""),
          };
          const sig = await checkSignatureOnce(linkedId);
          if (cancelled) return;
          // setAccommodation and setAccommodationStatus("linked") batched in same React 18 render.
          setAccommodation({ customer: customerObj, directName: "", seal: !sig.hasSignature, sign: sig.hasSignature, hasSignature: sig.hasSignature, signatureLookupError: sig.signatureLookupError });
          setAccommodationStatus("linked");
        } else if (pd.provider_name) {
          if (cancelled) return;
          setAccommodation({ customer: null, directName: String(pd.provider_name), seal: true, sign: false, hasSignature: false, signatureLookupError: false });
          setAccommodationStatus("linked");
        } else {
          // Valid response but no linked provider data — treat as none.
          if (!cancelled) setAccommodationStatus("none");
        }
      })
      .catch(() => { if (!cancelled) setAccommodationStatus("error"); });

    // 3) 신원보증인 preload → 관계 API + 서명 확인 후 단일 setGuarantor
    // Status transitions: "loading" → "none" | "linked" | "error"
    fetch(`/api/customers/${encodeURIComponent(initId)}/guarantor`, { headers: authHeader })
      .then(async (r) => {
        if (!r.ok) { if (!cancelled) setGuarantorStatus("none"); return; }
        let g: unknown;
        try { g = await r.json(); } catch { if (!cancelled) setGuarantorStatus("error"); return; }
        if (cancelled) return;
        if (!g || typeof g !== "object") { setGuarantorStatus("error"); return; }
        const gd = g as Record<string, unknown>;
        setGuarantorConnection(gd as unknown as import("@/lib/api").GuarantorConnection);
        if (gd.guarantor_type === "customer_db" && gd.guarantor_customer_id) {
          const linkedId = String(gd.guarantor_customer_id);
          const customerObj: CustomerSearchResult = {
            id: linkedId, name: String(gd.guarantor_name || ""),
            label: String(gd.guarantor_name || ""), reg_no: String(gd.guarantor_reg_front || ""),
          };
          const sig = await checkSignatureOnce(linkedId);
          if (cancelled) return;
          setGuarantor({ customer: customerObj, directName: "", seal: !sig.hasSignature, sign: sig.hasSignature, hasSignature: sig.hasSignature, signatureLookupError: sig.signatureLookupError });
          setGuarantorStatus("linked");
        } else if (gd.guarantor_name) {
          if (cancelled) return;
          setGuarantor({ customer: null, directName: String(gd.guarantor_name), seal: true, sign: false, hasSignature: false, signatureLookupError: false });
          setGuarantorStatus("linked");
        } else {
          if (!cancelled) setGuarantorStatus("none");
        }
      })
      .catch(() => { if (!cancelled) setGuarantorStatus("error"); });

    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initId]);

  const { data: tree } = useQuery({
    queryKey: ["qd-tree"],
    queryFn: () => quickDocApi.getTree().then((r) => r.data),
  });

  const typeOptions    = tree?.types[`${category}|${minwon}`] ?? [];
  const subtypeOptions = tree?.subtypes[`${category}|${minwon}|${kind}`] ?? [];

  const selectionComplete =
    !!category && !!minwon &&
    (typeOptions.length === 0 || !!kind) &&
    (subtypeOptions.length === 0 || !!detail);

  // "none" → no fixed person, proceed freely.
  // "linked"/"error" + roleIsSet → person found/or fallback and role is visible, proceed.
  // "linked"/"error" without role → blocked.
  // "unknown"/"loading" → always blocked.
  const accommodationReady =
    accommodationStatus === "none" ||
    (accommodationStatus === "linked" && roleIsSet(accommodation)) ||
    (accommodationStatus === "error"  && roleIsSet(accommodation));
  const guarantorReady =
    guarantorStatus === "none" ||
    (guarantorStatus === "linked" && roleIsSet(guarantor)) ||
    (guarantorStatus === "error"  && roleIsSet(guarantor));

  const effectiveKind   = kind   || "";
  const effectiveDetail = detail || "";

  const showGuarantor  = selectionComplete && needGuarantor(category, minwon, effectiveKind, effectiveDetail);
  const showAggregator = selectionComplete && needAggregator(category, minwon, effectiveKind, effectiveDetail);
  const isMinor        = calcIsMinor(applicant.customer?.reg_no ?? "");
  const showGuardian   = isMinor;

  const docsUserModified = useRef(false);
  const fetchTrigger     = useRef<"worktype" | "applicant">("worktype");

  const docsMut = useMutation({
    mutationFn: () =>
      quickDocApi.getRequiredDocs(
        category, minwon, effectiveKind, effectiveDetail,
        applicant.customer?.reg_no ?? "",
      ).then((r) => r.data),
    onSuccess: (data) => {
      if (fetchTrigger.current === "worktype" || !docsUserModified.current) {
        setCheckedDocs(new Set([...data.main_docs, ...data.agent_docs]));
        docsUserModified.current = false;
      }
    },
  });

  useEffect(() => {
    fetchTrigger.current = "worktype";
    docsUserModified.current = false;
    if (selectionComplete) docsMut.mutate();
    else setCheckedDocs(new Set());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, minwon, kind, detail]);

  useEffect(() => {
    if (selectionComplete) { fetchTrigger.current = "applicant"; docsMut.mutate(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicant.customer?.reg_no]);

  const resetAll = () => {
    setCategory(""); setMinwon(""); setKind(""); setDetail("");
    setCheckedDocs(new Set());
    docsUserModified.current = false;
    setApplicant(emptyRole(true));
    setAccommodation(emptyRole(true));
    setGuarantor(emptyRole(true));
    setGuardian(emptyRole(true));
    setAggregator(emptyRole(true));
    setAgentSeal(!agentHasSign);
    setAgentSign(agentHasSign);
    setIncludeDate(true);
    setCustomDate(getLocalDateString());
    if (pdfUrl) { URL.revokeObjectURL(pdfUrl); setPdfUrl(null); }
    setConfirmMissing(null);
    setShowEditPanel(false);
    setEditOverrides({});
    setLastPayload(null);
  };

  const selectCategory = (v: string) => { setCategory(v); setMinwon(""); setKind(""); setDetail(""); };
  const selectMinwon   = (v: string) => { setMinwon(v);   setKind(""); setDetail(""); };
  const selectKind     = (v: string) => { setKind(v);     setDetail(""); };

  const _runGenerate = useCallback(async (payload: FullDocGenRequest, opts: { isRegen?: boolean } = {}) => {
    if (!opts.isRegen) {
      setGenerating(true); setConfirmMissing(null); setShowEditPanel(false); setEditOverrides({});
      if (pdfUrl) { URL.revokeObjectURL(pdfUrl); setPdfUrl(null); }
    } else { setRegenLoading(true); }
    try {
      const res = await quickDocApi.generateFull(payload);
      const blob = res.data as Blob;
      if (blob.type?.includes("application/json")) {
        const text = await blob.text();
        try { toast.error("PDF 생성 실패: " + (JSON.parse(text)?.detail || text)); } catch { toast.error("PDF 생성 실패"); }
        return null;
      }
      return blob;
    } catch (err: unknown) {
      const errData = (err as { response?: { data?: Blob | { detail?: string } } })?.response?.data;
      if (errData instanceof Blob) {
        try {
          const text = await errData.text();
          const json = JSON.parse(text);
          toast.error("PDF 생성 실패: " + String(json?.detail?.message || json?.detail || text).slice(0, 200));
        } catch { toast.error("PDF 생성 실패 (파싱 오류)"); }
      } else { toast.error((errData as { detail?: string })?.detail || "PDF 생성 실패"); }
      return null;
    } finally {
      if (!opts.isRegen) setGenerating(false);
      else setRegenLoading(false);
    }
  }, [pdfUrl]);

  const doGenerate = useCallback(async () => {
    if (!roleIsSet(applicant)) { toast.error("신청인을 선택하거나 이름을 입력해 주세요."); return; }
    if (checkedDocs.size === 0) { toast.error("서류를 하나 이상 선택하세요."); return; }
    const payload: FullDocGenRequest = {
      category, minwon, kind: effectiveKind, detail: effectiveDetail,
      applicant_id:   applicant.customer?.id,
      applicant_name: !applicant.customer ? applicant.directName.trim() || undefined : undefined,
      accommodation_id:       accommodation.customer?.id,
      accommodation_name:     !accommodation.customer ? accommodation.directName.trim() || undefined : undefined,
      accommodation_provider: accommodationProvider || undefined,
      guarantor_connection:   guarantorConnection || undefined,
      guarantor_id:  guarantor.customer?.id,
      guarantor_name: !guarantor.customer ? guarantor.directName.trim() || undefined : undefined,
      guardian_id:   guardian.customer?.id,
      guardian_name: !guardian.customer ? guardian.directName.trim() || undefined : undefined,
      aggregator_id: aggregator.customer?.id,
      aggregator_name: !aggregator.customer ? aggregator.directName.trim() || undefined : undefined,
      selected_docs: Array.from(checkedDocs),
      seal_applicant: applicant.seal, seal_accommodation: accommodation.seal,
      seal_guarantor: guarantor.seal, seal_guardian: guardian.seal,
      seal_aggregator: aggregator.seal, seal_agent: agentSeal,
      sign_applicant: applicant.sign, sign_accommodation: accommodation.sign,
      sign_guarantor: guarantor.sign, sign_guardian: guardian.sign,
      sign_aggregator: aggregator.sign, sign_agent: agentSign,
      include_date: includeDate,
      custom_date:  customDate,
    };
    const blob = await _runGenerate(payload);
    if (blob) { setLastPayload(payload); setPdfUrl(URL.createObjectURL(blob)); toast.success("PDF 생성 완료"); }
  }, [applicant, accommodation, guarantor, guardian, aggregator, agentSeal, agentSign, checkedDocs, category, minwon, effectiveKind, effectiveDetail, _runGenerate, customDate, includeDate, accommodationProvider, guarantorConnection]);

  const handleEditDownload = useCallback(async () => {
    if (!lastPayload) return;
    const activeOverrides: Record<string, string> = {};
    for (const [k, v] of Object.entries(editOverrides)) { if (v.trim() !== "") activeOverrides[k] = v.trim(); }
    if (Object.keys(activeOverrides).length === 0) {
      const a = document.createElement("a");
      a.href = pdfUrl!;
      a.download = `${roleDisplayName(applicant) || "고객"}_${category}_${minwon}.pdf`;
      a.click();
      return;
    }
    const regenPayload = { ...lastPayload, direct_overrides: activeOverrides };
    const blob = await _runGenerate(regenPayload, { isRegen: true });
    if (blob) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${roleDisplayName(applicant) || "고객"}_${category}_${minwon}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      toast.success("수정된 PDF 다운로드");
    }
  }, [lastPayload, editOverrides, pdfUrl, applicant, category, minwon, _runGenerate]);

  const handleGenerate = () => {
    const missing: string[] = [];
    const accommodationDocSelected = Array.from(checkedDocs).some((d) => d.includes("숙소"));
    if (accommodationDocSelected && !roleIsSet(accommodation)) missing.push("숙소제공자");
    if (showGuarantor && !roleIsSet(guarantor)) missing.push("신원보증인");
    if (showGuardian  && !roleIsSet(guardian))  missing.push("대리인");
    if (showAggregator && !roleIsSet(aggregator)) missing.push("합산자");
    if (missing.length > 0) { setConfirmMissing(missing); return; }
    doGenerate();
  };

  const docs = docsMut.data;

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>

      {/* 헤더 — 독립 페이지 모드에서만 표시 */}
      {!embedded && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <FileText size={18} style={{ color: GOLD }} />
            <h1 style={{ fontSize: 20, fontWeight: 800, color: "#1A202C", margin: 0 }}>문서 자동작성</h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {agentInfo && (
              <span style={{ fontSize: 12, color: "#718096" }}>
                <b>{agentInfo.office_name}</b> / {agentInfo.contact_name}
              </span>
            )}
            <Link
              href="/quick-doc/quick-poa"
              style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 8, border: `1px solid ${GOLD}`, fontSize: 12, background: "#FFF9E6", cursor: "pointer", color: "#6B5314", textDecoration: "none", fontWeight: 600 }}
            >
              <Zap size={11} /> 원클릭 작성
            </Link>
            {(category || roleIsSet(applicant)) && (
              <button onClick={resetAll} style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 8, border: `1px solid ${BORDER}`, fontSize: 12, background: "#fff", cursor: "pointer", color: "#718096" }}>
                <RotateCcw size={11} /> 처음부터
              </button>
            )}
          </div>
        </div>
      )}

      {/* embedded 모드 — 처음부터 버튼만 */}
      {embedded && (category || roleIsSet(applicant)) && (
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
          <button onClick={resetAll} style={{ display: "flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 8, border: `1px solid ${BORDER}`, fontSize: 12, background: "#fff", cursor: "pointer", color: "#718096" }}>
            <RotateCcw size={11} /> 처음부터
          </button>
        </div>
      )}

      {/* 브레드크럼 */}
      {category && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 12, padding: "7px 12px", borderRadius: 8, marginBottom: 14, background: GOLD_LIGHT, color: "#6B5314" }}>
          {[category, minwon, kind, detail].filter(Boolean).map((v, i) => (
            <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, fontWeight: 600 }}>
              {i > 0 && <span style={{ opacity: 0.5 }}>›</span>}
              {v}
            </span>
          ))}
          {selectionComplete && <span style={{ marginLeft: "auto", color: "#276749", fontWeight: 600 }}>✓ 업무 선택 완료</span>}
        </div>
      )}

      {/* 3단 레이아웃 */}
      <div style={{ display: "grid", gridTemplateColumns: "200px 220px 1fr", gap: 16, alignItems: "start" }}>

        {/* 열 1: 업무 선택 */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "16px 14px", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 12 }}>① 업무 선택</div>
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>구분</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {(tree?.categories ?? ["체류", "사증"]).map((c) => (
                <button key={c} onClick={() => selectCategory(c)} style={{ padding: "5px 12px", borderRadius: 99, fontSize: 12, cursor: "pointer", border: `1.5px solid ${category === c ? GOLD : BORDER}`, background: category === c ? GOLD : "#fff", color: category === c ? "#fff" : "#4A5568", fontWeight: category === c ? 700 : 400, transition: "all 0.1s" }}>
                  {c}
                </button>
              ))}
            </div>
          </div>
          {category && (tree?.minwon[category] ?? []).length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>민원</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {(tree?.minwon[category] ?? []).map((m) => (
                  <button key={m} onClick={() => selectMinwon(m)} style={{ padding: "5px 10px", borderRadius: 99, fontSize: 12, cursor: "pointer", border: `1.5px solid ${minwon === m ? GOLD : BORDER}`, background: minwon === m ? GOLD : "#fff", color: minwon === m ? "#fff" : "#4A5568", fontWeight: minwon === m ? 700 : 400 }}>
                    {m}
                  </button>
                ))}
              </div>
            </div>
          )}
          {minwon && typeOptions.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>종류</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {typeOptions.map((k) => (
                  <button key={k} onClick={() => selectKind(k)} style={{ padding: "5px 10px", borderRadius: 99, fontSize: 12, cursor: "pointer", border: `1.5px solid ${kind === k ? GOLD : BORDER}`, background: kind === k ? GOLD : "#fff", color: kind === k ? "#fff" : "#4A5568", fontWeight: kind === k ? 700 : 400 }}>
                    {k}
                  </button>
                ))}
              </div>
            </div>
          )}
          {kind && subtypeOptions.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>세부</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {subtypeOptions.map((d) => (
                  <button key={d} onClick={() => setDetail(d)} style={{ padding: "5px 10px", borderRadius: 99, fontSize: 12, cursor: "pointer", border: `1.5px solid ${detail === d ? GOLD : BORDER}`, background: detail === d ? GOLD : "#fff", color: detail === d ? "#fff" : "#4A5568", fontWeight: detail === d ? 700 : 400 }}>
                    {kind === "F" ? `F-${d}` : d}
                  </button>
                ))}
              </div>
            </div>
          )}
          {!selectionComplete && category && (
            <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 8 }}>
              {!minwon ? "민원을 선택하세요" : !kind && typeOptions.length > 0 ? "종류를 선택하세요" : !detail && subtypeOptions.length > 0 ? "세부를 선택하세요" : ""}
            </div>
          )}
        </div>

        {/* 열 2: 필요 서류 */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "16px 14px", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 12 }}>② 필요 서류</div>
          {!selectionComplete && <div style={{ fontSize: 12, color: "#A0AEC0", padding: "12px 0" }}>업무를 선택하면<br />필요 서류가 자동으로 표시됩니다.</div>}
          {selectionComplete && docsMut.isPending && <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#A0AEC0" }}><Loader2 size={13} className="animate-spin" /> 조회 중...</div>}
          {selectionComplete && !docsMut.isPending && !docs && <div style={{ fontSize: 12, color: "#A0AEC0" }}>선택한 업무에 해당하는 서류 설정이 없습니다.</div>}
          {docs && (
            <>
              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <button onClick={() => setCheckedDocs(new Set([...docs.main_docs, ...docs.agent_docs]))} style={{ fontSize: 11, color: "#3182CE", background: "none", border: "none", cursor: "pointer", padding: 0 }}>전체 선택</button>
                <button onClick={() => setCheckedDocs(new Set())} style={{ fontSize: 11, color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 0 }}>전체 해제</button>
                <span style={{ fontSize: 11, color: "#A0AEC0", marginLeft: "auto" }}>{checkedDocs.size}개 선택</span>
              </div>
              {docs.main_docs.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 5 }}>민원 서류</div>
                  {docs.main_docs.map((doc) => (
                    <label key={doc} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5, cursor: "pointer" }}>
                      <input type="checkbox" checked={checkedDocs.has(doc)} onChange={(e) => { docsUserModified.current = true; const n = new Set(checkedDocs); e.target.checked ? n.add(doc) : n.delete(doc); setCheckedDocs(n); }} style={{ accentColor: GOLD, width: 13, height: 13 }} />
                      <span style={{ fontSize: 12, color: "#2D3748" }}>{doc}</span>
                    </label>
                  ))}
                </div>
              )}
              {docs.agent_docs.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 5 }}>행정사 서류</div>
                  {docs.agent_docs.map((doc) => (
                    <label key={doc} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5, cursor: "pointer" }}>
                      <input type="checkbox" checked={checkedDocs.has(doc)} onChange={(e) => { docsUserModified.current = true; const n = new Set(checkedDocs); e.target.checked ? n.add(doc) : n.delete(doc); setCheckedDocs(n); }} style={{ accentColor: GOLD, width: 13, height: 13 }} />
                      <span style={{ fontSize: 12, color: "#2D3748" }}>{doc}</span>
                    </label>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* 열 3: 관계인 + 도장 + PDF */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "16px 18px", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 12 }}>③ 관계인 배정 &amp; 도장</div>
          <RoleSelector label="신청인" icon={<User size={13} />} required role={applicant} onChange={setApplicant} allowDirectInput directInputPlaceholder="DB에 없으면 이름 직접 입력" />
          <RoleSelector label="숙소제공자" icon={<Home size={13} />} role={accommodation} onChange={setAccommodation} allowDirectInput directInputPlaceholder="이름 직접 입력 가능" />
          {showGuarantor && <RoleSelector label="신원보증인" icon={<Shield size={13} />} role={guarantor} onChange={setGuarantor} allowDirectInput directInputPlaceholder="이름 직접 입력 가능" />}
          {showGuardian  && <RoleSelector label="대리인 (미성년 법정대리인)" icon={<UserCheck size={13} />} role={guardian} onChange={setGuardian} allowDirectInput directInputPlaceholder="이름 직접 입력 가능" />}
          {showAggregator && <RoleSelector label="합산자 (소득 합산)" icon={<Users size={13} />} role={aggregator} onChange={setAggregator} allowDirectInput directInputPlaceholder="이름 직접 입력 가능" />}
          <div style={{ padding: "9px 12px", border: `1px solid ${BORDER}`, borderRadius: 10, background: GRAY_BG, marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <Stamp size={13} style={{ color: GOLD }} />
                <span style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>행정사</span>
                <span style={{ fontSize: 12, color: "#718096" }}>{agentInfo?.contact_name || agentInfo?.office_name || "계정 정보 없음"} — 자동 채움</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: "#718096" }}>
                {(["sign", "seal", "none"] as const).map((opt) => {
                  const labels = { sign: "서명", seal: "도장", none: "없음" };
                  const isChecked = opt === "sign" ? agentSign : opt === "seal" ? (!agentSign && agentSeal) : (!agentSign && !agentSeal);
                  const disabled = opt === "sign" && !agentHasSign;
                  return (
                    <label key={opt} style={{ display: "flex", alignItems: "center", gap: 3, cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.4 : 1 }}>
                      <input type="radio" name="agent-opt" checked={isChecked} disabled={disabled}
                        onChange={() => { if (opt === "sign") { setAgentSign(true); setAgentSeal(false); } else if (opt === "seal") { setAgentSign(false); setAgentSeal(true); } else { setAgentSign(false); setAgentSeal(false); } }}
                        style={{ accentColor: GOLD }} />
                      {labels[opt]}
                    </label>
                  );
                })}
              </div>
            </div>
          </div>
          {selectionComplete && (
            <div style={{ fontSize: 11, color: "#718096", marginBottom: 10, padding: "6px 10px", background: "#EBF8FF", borderRadius: 6, lineHeight: 1.6 }}>
              {showGuarantor ? "✓ 신원보증인 필요 (F계열)" : ""}
              {showAggregator ? " ✓ 합산자 필요 (F-5 변경)" : ""}
              {showGuardian ? " ✓ 대리인 필요 (미성년 신청인)" : ""}
              {!showGuarantor && !showAggregator && !showGuardian ? "이 업무는 신청인 + 숙소제공자만 필요합니다." : ""}
            </div>
          )}
          {confirmMissing && (
            <div style={{ padding: "12px 14px", background: "#FFF5F5", border: "1px solid #FEB2B2", borderRadius: 8, marginBottom: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#C53030", marginBottom: 6 }}>누락 항목이 있습니다:</div>
              {confirmMissing.map((r) => (<div key={r} style={{ fontSize: 12, color: "#9B2C2C", marginBottom: 2 }}>• {r}이(가) 입력되지 않았습니다.</div>))}
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <button onClick={() => { setConfirmMissing(null); doGenerate(); }} style={{ padding: "6px 14px", borderRadius: 8, fontSize: 12, cursor: "pointer", background: GOLD, color: "#fff", border: "none", fontWeight: 600 }}>그대로 작성</button>
                <button onClick={() => setConfirmMissing(null)} style={{ padding: "6px 14px", borderRadius: 8, fontSize: 12, cursor: "pointer", background: "#fff", border: `1px solid ${BORDER}`, color: "#718096" }}>취소</button>
              </div>
            </div>
          )}
          {/* 작성일 삽입 옵션 */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", border: `1px solid ${BORDER}`, borderRadius: 8, background: GRAY_BG, marginBottom: 8, flexWrap: "wrap" }}>
            <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", userSelect: "none" as const }}>
              <input type="checkbox" checked={includeDate} onChange={(e) => setIncludeDate(e.target.checked)} style={{ accentColor: GOLD }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: "#2D3748" }}>작성일 삽입</span>
            </label>
            {includeDate && (
              <>
                <input
                  type="date"
                  value={customDate}
                  onChange={(e) => setCustomDate(e.target.value)}
                  style={{ fontSize: 12, border: `1px solid ${BORDER}`, borderRadius: 6, padding: "3px 8px", color: "#2D3748", background: "#fff" }}
                />
                <button onClick={() => setCustomDate(getLocalDateString())} style={{ fontSize: 11, color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 0 }}>오늘로</button>
                <button onClick={() => setCustomDate("")} style={{ fontSize: 11, color: "#A0AEC0", background: "none", border: "none", cursor: "pointer", padding: 0 }}>비우기</button>
              </>
            )}
          </div>
          <SubmitButton
            isSubmitting={generating}
            disabled={!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0 || !accommodationReady || !guarantorReady}
            onClick={handleGenerate}
            loadingText="PDF 생성 중..."
            style={{ width: "100%", padding: "12px 0", background: (!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0 || !accommodationReady || !guarantorReady) ? "#E2E8F0" : GOLD, color: (!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0 || !accommodationReady || !guarantorReady) ? "#A0AEC0" : "#fff", borderRadius: 10, fontSize: 14, fontWeight: 700, transition: "all 0.15s", marginBottom: 12 }}
          >
            <><FileText size={14} /> 🖨 PDF 생성</>
          </SubmitButton>
          {(!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0 || !accommodationReady || !guarantorReady) && !generating && (
            <div style={{ fontSize: 11, color: (accommodationStatus === "error" && !roleIsSet(accommodation)) || (guarantorStatus === "error" && !roleIsSet(guarantor)) ? "#C53030" : "#A0AEC0", textAlign: "center", marginBottom: 8 }}>
              {!selectionComplete ? "업무를 완전히 선택해 주세요"
                : !roleIsSet(applicant) ? "신청인을 입력해 주세요"
                : checkedDocs.size === 0 ? "서류를 하나 이상 선택해 주세요"
                : (accommodationStatus === "error" && !roleIsSet(accommodation)) || (guarantorStatus === "error" && !roleIsSet(guarantor))
                  ? "관계인 조회 실패 — 다시 시도하거나 직접 입력해 주세요"
                  : "고정 관계인 확인 중..."}
            </div>
          )}
        </div>
      </div>

      {/* PDF 결과 */}
      {pdfUrl && (
        <div style={{ border: "2px solid #276749", borderRadius: 12, background: "#F0FFF4", padding: "16px 20px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#276749" }}>✅ PDF 생성 완료</span>
              <span style={{ fontSize: 12, color: "#38A169", marginLeft: 10 }}>{roleDisplayName(applicant) || "고객"}_{category}_{minwon}</span>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => setShowEditPanel((v) => !v)} style={{ display: "flex", alignItems: "center", gap: 5, padding: "8px 14px", borderRadius: 8, fontSize: 13, background: showEditPanel ? "#EBF8FF" : "#fff", color: "#3182CE", border: `1px solid ${showEditPanel ? "#3182CE" : BORDER}`, cursor: "pointer", fontWeight: 600 }}>
                <Edit2 size={13} /> 내용 수정
              </button>
              <SubmitButton isSubmitting={regenLoading} onClick={handleEditDownload} loadingText="재생성 중..." style={{ padding: "8px 18px", borderRadius: 8, fontSize: 13, fontWeight: 700 }}>
                <><Download size={14} /> {Object.values(editOverrides).some(v => v.trim()) ? "수정 후 다운로드" : "다운로드"}</>
              </SubmitButton>
            </div>
          </div>
          {showEditPanel && (
            <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 10, padding: "14px 18px", marginBottom: 14 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 10 }}>📝 내용 수정 — 바꿀 항목만 입력하세요 (비워두면 원본 유지)</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px 16px" }}>
                {OVERRIDE_FIELDS.map(({ label, key, placeholder }) => (
                  <div key={key}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 3 }}>{label}</div>
                    <input value={editOverrides[key] ?? ""} onChange={(e) => setEditOverrides((prev) => ({ ...prev, [key]: e.target.value }))} placeholder={placeholder}
                      style={{ width: "100%", padding: "6px 10px", border: `1px solid ${editOverrides[key]?.trim() ? GOLD : BORDER}`, borderRadius: 6, fontSize: 12, boxSizing: "border-box", background: editOverrides[key]?.trim() ? "#FFF9E6" : "#fff" }} />
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 8 }}>수정 후 "수정 후 다운로드"를 클릭하면 입력한 값이 반영된 새 PDF가 생성됩니다.</div>
            </div>
          )}
          <iframe src={`${pdfUrl}#pagemode=none`} style={{ width: "100%", height: "max(900px, calc(100vh - 200px))", borderRadius: 8, border: "1px solid #C6F6D5", display: "block" }} title="PDF 미리보기" />
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Public export — wraps inner in Suspense for useSearchParams
// ─────────────────────────────────────────────────────────────────────────
export default function QuickDocPanel(props: QuickDocPanelProps) {
  return (
    <Suspense>
      <QuickDocPanelInner {...props} />
    </Suspense>
  );
}
