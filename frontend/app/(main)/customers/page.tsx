"use client";
import { useState, useEffect, useCallback, Suspense, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { customersApi, accommodationApi, guarantorApi, quickDocApi, type AccommodationProvider, type GuarantorConnection, type CustomerSearchResult, type WorkSummary } from "@/lib/api";
import { Search, UserPlus, Trash2, X, Save, FolderOpen, ExternalLink, FileText, Home, Zap, Globe, Shield, Loader2 } from "lucide-react";
import { normalizeDate } from "@/lib/utils";
import SignatureModal from "@/components/SignatureModal";
import QuickDocPanel from "@/components/QuickDocPanel";
import QuickPoaPanel from "@/components/QuickPoaPanel";
import { useSubmit } from "@/lib/useSubmit";
import { SubmitButton } from "@/components/SubmitButton";

// ── 만기 D-Day 계산 ────────────────────────────────────────────────────────────
function parseDateStr(s: string): Date | null {
  if (!s) return null;
  const clean = s.replace(/\./g, "-").slice(0, 10);
  const d = new Date(clean);
  return isNaN(d.getTime()) ? null : d;
}

function getDaysUntil(dateStr: string): number | null {
  const d = parseDateStr(dateStr);
  if (!d) return null;
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.floor((d.getTime() - now.getTime()) / 86_400_000);
}

function expiryBadge(days: number | null): { text: string; style: React.CSSProperties } | null {
  if (days === null) return null;
  if (days < 0) return { text: `만료`, style: { background: "#FED7D7", color: "#C53030" } };
  if (days <= 30) return { text: `D-${days}`, style: { background: "#FED7D7", color: "#C53030" } };
  if (days <= 120) return { text: `D-${days}`, style: { background: "#FEEBC8", color: "#9C4221" } };
  return null;
}

function rowHighlight(c: Record<string, string>): React.CSSProperties {
  const cardDays = getDaysUntil(c["만기일"]);
  const passDays = getDaysUntil(c["만기"]);
  const min = [cardDays, passDays].reduce<number | null>((m, d) => {
    if (d === null) return m;
    return m === null ? d : Math.min(m, d);
  }, null);
  if (min === null) return {};
  if (min <= 30) return { background: "#FFF5F5" };
  if (min <= 120) return { background: "#FFF9E6" };
  return {};
}

// ── 원본 시트 컬럼 정의 (기존 Streamlit 화면과 동일) ──────────────────────────
// 시트 컬럼명 그대로 사용 (매핑 없음)
const ALL_FIELDS = [
  "한글", "국적", "성", "명", "연", "락", "처",
  "등록증", "번호", "발급일", "만기일",
  "여권", "발급", "만기",
  "주소", "V", "위임내역", "비고", "폴더",
];

// 테이블에서 보일 컬럼 — 정보밀도 최대화, 원본 Streamlit 동일 컬럼 순서
const TABLE_COLS: { key: string; label: string; w?: string }[] = [
  { key: "한글",     label: "한글이름",    w: "64px" },
  { key: "국적",     label: "국적",       w: "36px" },
  { key: "성",       label: "성",         w: "54px" },
  { key: "명",       label: "명",         w: "70px" },
  { key: "_tel",     label: "연락처",     w: "88px" },
  { key: "V",        label: "체류",       w: "42px" },
  { key: "등록증",   label: "등록앞",     w: "58px" },
  { key: "번호",     label: "등록뒤",     w: "58px" },
  { key: "발급일",   label: "등록발급",   w: "70px" },
  { key: "만기일",   label: "등록만기",   w: "70px" },
  { key: "여권",     label: "여권번호",   w: "78px" },
  { key: "만기",     label: "여권만기",   w: "70px" },
  { key: "주소",     label: "주소",       w: "110px" },
];

// 드로어 필드 그룹 (원본 화면 구조 반영)
const DRAWER_GROUPS = [
  {
    title: "기본정보",
    fields: [
      { key: "한글",   label: "한글이름" },
      { key: "국적",   label: "국적" },
      { key: "성",     label: "영문 성(Last)" },
      { key: "명",     label: "영문 이름(First)" },
      { key: "V",      label: "체류자격" },
    ],
  },
  {
    title: "연락처",
    fields: [
      { key: "연",   label: "전화번호 앞자리" },
      { key: "락",   label: "전화번호 중간" },
      { key: "처",   label: "전화번호 끝자리" },
      { key: "주소", label: "주소", wide: true },
    ],
  },
  {
    title: "등록증",
    fields: [
      { key: "등록증", label: "등록번호 앞자리(생년월일)" },
      { key: "번호",   label: "등록번호 뒷자리" },
      { key: "발급일", label: "등록증 발급일" },
      { key: "만기일", label: "등록증 만기일" },
    ],
  },
  {
    title: "여권",
    fields: [
      { key: "여권", label: "여권번호" },
      { key: "발급", label: "여권 발급일" },
      { key: "만기", label: "여권 만기일" },
    ],
  },
  {
    title: "업무정보",
    fields: [
      { key: "비고",     label: "비고",     wide: true },
      { key: "폴더",     label: "폴더 ID/URL", wide: true },
    ],
  },
];

// 페이지 번호 배열 생성 (최대 7개 표시, 초과 시 … 삽입)
function buildPageNums(current: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | "…")[] = [1];
  if (current > 3) pages.push("…");
  for (let p = Math.max(2, current - 1); p <= Math.min(total - 1, current + 1); p++) {
    pages.push(p);
  }
  if (current < total - 2) pages.push("…");
  pages.push(total);
  return pages;
}

function emptyCustomer(): Record<string, string> {
  const rec: Record<string, string> = { 고객ID: "" };
  ALL_FIELDS.forEach((f) => (rec[f] = ""));
  return rec;
}

// ── 신원보증인 설정 모달 ──────────────────────────────────────────────────────
function GuarantorModal({
  customerId, customerName, current, onClose, onSaved,
}: {
  customerId: string;
  customerName: string;
  current: GuarantorConnection | null;
  onClose: () => void;
  onSaved: (g: GuarantorConnection | null) => void;
}) {
  const isDB = current?.guarantor_type === "customer_db";
  const [tab, setTab] = useState<"search" | "manual">(isDB ? "search" : "manual");
  const [searchQ, setSearchQ] = useState(isDB ? (current?.guarantor_name || "") : "");
  const [searchResults, setSearchResults] = useState<CustomerSearchResult[]>([]);
  const [selectedDB, setSelectedDB] = useState<CustomerSearchResult | null>(
    isDB && current
      ? { id: current.guarantor_customer_id, name: current.guarantor_name, label: current.guarantor_name, reg_no: current.guarantor_reg_front }
      : null
  );

  // manual 타입 필드용 (초기값은 manual 타입일 때만)
  const m = (key: keyof GuarantorConnection) =>
    current?.guarantor_type === "manual" ? (current[key] as string || "") : "";
  const [mName,      setMName]      = useState(m("guarantor_name"));
  const [mLastName,  setMLastName]  = useState(m("guarantor_last_name"));
  const [mFirstName, setMFirstName] = useState(m("guarantor_first_name"));
  const [mNation,    setMNation]    = useState(m("guarantor_nation"));
  const [mRegFront,  setMRegFront]  = useState(m("guarantor_reg_front"));
  const [mRegBack,   setMRegBack]   = useState(m("guarantor_reg_back"));
  const [mPhone,     setMPhone]     = useState(m("guarantor_phone"));
  const [mAddress,   setMAddress]   = useState(m("guarantor_address"));
  // 관계는 타입 무관하게 기존값 표시 (DB 검색/수동 입력 모두 사용)
  const [mRelation,  setMRelation]  = useState<string>(current?.guarantor_relation || "");
  // DB 검색 탭 보완 주소 — DB 고객 주소가 빈값일 때 사용자가 보완 입력
  const [mSearchAddress, setMSearchAddress] = useState<string>(
    isDB ? (current?.guarantor_address || "") : ""
  );
  const [saving,     setSaving]     = useState(false);
  const [deleting,   setDeleting]   = useState(false);

  const BORDER = "#E2E8F0"; const GOLD = "#D4A843";
  const inp: React.CSSProperties = {
    width:"100%", padding:"6px 9px", border:`1px solid ${BORDER}`,
    borderRadius:6, fontSize:12, boxSizing:"border-box",
  };

  useEffect(() => {
    if (tab !== "search" || searchQ.length < 1) { setSearchResults([]); return; }
    const t = setTimeout(() => {
      quickDocApi.searchCustomers(searchQ).then(r => setSearchResults(r.data)).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [searchQ, tab]);

  const handleSave = async () => {
    setSaving(true);
    try {
      let payload: Partial<GuarantorConnection>;
      if (tab === "search") {
        if (!selectedDB) { toast.error("고객을 선택하세요."); setSaving(false); return; }
        payload = {
          guarantor_type:         "customer_db",
          guarantor_customer_id:  selectedDB.id,
          guarantor_name:         selectedDB.name,
          guarantor_reg_front:    selectedDB.reg_no || "",
          guarantor_relation:     mRelation.trim(),       // 관계: 사용자 입력값
          guarantor_address:      mSearchAddress.trim(),  // 주소: DB 빈값 보완용
        };
      } else {
        if (!mName.trim()) { toast.error("성명을 입력하세요."); setSaving(false); return; }
        payload = {
          guarantor_type:        "manual",
          guarantor_customer_id: "",
          guarantor_name:        mName.trim(),
          guarantor_last_name:   mLastName.trim(),
          guarantor_first_name:  mFirstName.trim(),
          guarantor_nation:      mNation.trim(),
          guarantor_reg_front:   mRegFront.trim(),
          guarantor_reg_back:    mRegBack.trim(),
          guarantor_phone:       mPhone.trim(),
          guarantor_address:     mAddress.trim(),
          guarantor_relation:    mRelation.trim(),
        };
      }
      const res = await guarantorApi.save(customerId, payload);
      toast.success("신원보증인이 고정되었습니다.");
      onSaved(res.data.data);
      onClose();
    } catch { toast.error("저장 실패"); }
    finally { setSaving(false); }
  };

  const handleDelete = async () => {
    if (!confirm("신원보증인 연결을 해제하시겠습니까?")) return;
    setDeleting(true);
    try {
      await guarantorApi.delete(customerId);
      toast.success("신원보증인 연결이 해제되었습니다.");
      onSaved(null); onClose();
    } catch { toast.error("해제 실패"); }
    finally { setDeleting(false); }
  };

  return (
    <>
      <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.35)", zIndex:300 }} onClick={onClose} />
      <div style={{
        position:"fixed", top:"50%", left:"50%",
        transform:"translate(-50%,-50%)",
        zIndex:301, width:"min(420px, 96vw)",
        background:"#fff", borderRadius:14,
        boxShadow:"0 8px 40px rgba(0,0,0,0.18)",
        display:"flex", flexDirection:"column", maxHeight:"90vh",
      }}>
        {/* 헤더 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"13px 18px", borderBottom:`1px solid ${BORDER}`, background:"#F0FFF4", flexShrink:0 }}>
          <div>
            <div style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>신원보증인 설정</div>
            <div style={{ fontSize:11, color:"#718096" }}>대상: {customerName}</div>
          </div>
          <button onClick={onClose} style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}><X size={16} /></button>
        </div>

        <div style={{ overflowY:"auto", flex:1, padding:"14px 18px" }}>
          {/* 현재 설정 표시 */}
          {current && (
            <div style={{ marginBottom:12, padding:"9px 12px", background:"#F0FFF4", borderRadius:8, border:"1px solid #C6F6D5", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <div>
                <div style={{ fontSize:12, fontWeight:700, color:"#276749" }}>현재: {current.guarantor_name}</div>
                {current.guarantor_type === "customer_db" && <div style={{ fontSize:10, color:"#718096" }}>고객 DB 연결</div>}
              </div>
              <button onClick={handleDelete} disabled={deleting}
                style={{ fontSize:11, padding:"4px 10px", borderRadius:5, border:"1px solid #FC8181", background:"#FFF5F5", color:"#C53030", cursor:"pointer", flexShrink:0 }}>
                {deleting ? "해제 중..." : "연결 해제"}
              </button>
            </div>
          )}

          {/* 탭 */}
          <div style={{ display:"flex", gap:4, marginBottom:12, background:"#F7FAFC", borderRadius:8, padding:4 }}>
            {(["search", "manual"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex:1, padding:"6px 0", borderRadius:6, fontSize:12, fontWeight:600,
                border:"none", cursor:"pointer",
                background: tab === t ? "#fff" : "transparent",
                color: tab === t ? GOLD : "#718096",
                boxShadow: tab === t ? "0 1px 4px rgba(0,0,0,0.08)" : "none",
              }}>
                {t === "search" ? "고객 DB 검색" : "직접 입력"}
              </button>
            ))}
          </div>

          {/* DB 검색 탭 */}
          {tab === "search" && (
            <div>
              <div style={{ position:"relative", marginBottom:8 }}>
                <Search size={12} style={{ position:"absolute", left:9, top:"50%", transform:"translateY(-50%)", color:"#A0AEC0" }} />
                <input autoFocus value={searchQ}
                  onChange={e => { setSearchQ(e.target.value); if (selectedDB && e.target.value !== selectedDB.name) setSelectedDB(null); }}
                  placeholder="이름 / 전화번호 / 고객ID 검색"
                  style={{ ...inp, paddingLeft:28 }} />
              </div>
              {searchResults.length > 0 && (
                <div style={{ border:`1px solid ${BORDER}`, borderRadius:8, maxHeight:160, overflowY:"auto", marginBottom:8 }}>
                  {searchResults.map(c => (
                    <button key={c.id} onClick={() => { setSelectedDB(c); setSearchQ(c.name); setSearchResults([]); }}
                      style={{ display:"block", width:"100%", textAlign:"left", padding:"7px 12px", border:"none", borderBottom:`1px solid ${BORDER}`, background: selectedDB?.id === c.id ? "#F0FFF4" : "#fff", cursor:"pointer", fontSize:12, color:"#2D3748" }}>
                      {c.name}
                      {c.name_en && <span style={{ fontSize:10, color:"#A0AEC0", marginLeft:4 }}>({c.name_en})</span>}
                    </button>
                  ))}
                </div>
              )}
              {selectedDB && (
                <div style={{ padding:"7px 10px", background:"#F0FFF4", borderRadius:7, fontSize:12, color:"#276749", marginBottom:8 }}>
                  ✅ {selectedDB.name} 선택됨
                </div>
              )}
              {/* 관계 — DB 검색 후에도 사용자가 직접 입력 */}
              <div style={{ marginTop:4 }}>
                <label style={{ display:"block", fontSize:10, color:"#718096", marginBottom:2 }}>관계</label>
                <input value={mRelation} onChange={e => setMRelation(e.target.value)}
                  placeholder="예) 배우자, 부모, 자녀, 친척, 지인, 고용주 등" style={inp} />
              </div>
              {/* 주소 보완 — DB 고객 주소가 비어 있을 때 입력 */}
              <div style={{ marginTop:6 }}>
                <label style={{ display:"block", fontSize:10, color:"#718096", marginBottom:2 }}>
                  주소 <span style={{ color:"#A0AEC0" }}>(DB 주소가 없을 때 직접 입력)</span>
                </label>
                <input value={mSearchAddress} onChange={e => setMSearchAddress(e.target.value)}
                  placeholder="보증인 주소 (선택 고객의 주소가 있으면 생략 가능)" style={inp} />
              </div>
            </div>
          )}

          {/* 직접 입력 탭 */}
          {tab === "manual" && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:7 }}>
              {([
                { label:"한글 성명*",  val:mName,      set:setMName,      wide:true  },
                { label:"영문 성",     val:mLastName,  set:setMLastName,  wide:false },
                { label:"영문 이름",   val:mFirstName, set:setMFirstName, wide:false },
                { label:"국적",        val:mNation,    set:setMNation,    wide:false },
                { label:"등록번호 앞", val:mRegFront,  set:setMRegFront,  wide:false },
                { label:"등록번호 뒤", val:mRegBack,   set:setMRegBack,   wide:false },
                { label:"연락처",      val:mPhone,     set:setMPhone,     wide:true  },
                { label:"주소",        val:mAddress,   set:setMAddress,   wide:true  },
                { label:"관계",        val:mRelation,  set:setMRelation,  wide:false },
              ] as { label:string; val:string; set:(v:string)=>void; wide:boolean }[]).map(({ label, val, set, wide }) => (
                <div key={label} style={wide ? { gridColumn:"1/-1" } : {}}>
                  <label style={{ display:"block", fontSize:10, color:"#718096", marginBottom:2 }}>{label}</label>
                  <input value={val} onChange={e => set(e.target.value)} style={inp} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 저장 버튼 */}
        <div style={{ padding:"12px 18px", borderTop:`1px solid ${BORDER}`, flexShrink:0 }}>
          <button onClick={handleSave} disabled={saving}
            style={{ width:"100%", padding:"11px 0", borderRadius:8, fontSize:13, fontWeight:700, background: saving ? "#E2E8F0" : "#276749", color:"#fff", border:"none", cursor: saving ? "default" : "pointer" }}>
            {saving ? "저장 중..." : "신원보증인 고정"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── 완료업무 팝업 ─────────────────────────────────────────────────────────────
const CAT_GROUPS = [
  { key: "전체",     cats: null },
  { key: "출입국",   cats: ["출입국", "영주권"] },
  { key: "전자민원", cats: ["전자민원"] },
  { key: "공증",     cats: ["공증"] },
  { key: "여권·초청", cats: ["여권", "초청"] },
  { key: "기타",     cats: null, isEtc: true },
] as const;

function CompletedTasksModal({
  customerId, customerName, hasNameDuplicate, onClose,
}: {
  customerId: string;
  customerName: string;
  hasNameDuplicate: boolean;
  onClose: () => void;
}) {
  const [tasks, setTasks] = useState<Record<string, string>[]>([]);
  const [legacyTasks, setLegacyTasks] = useState<Record<string, string>[]>([]);
  const [loading, setLoading] = useState(true);
  const [catFilter, setCatFilter] = useState("전체");
  const [showLegacy, setShowLegacy] = useState(false);

  useEffect(() => {
    setLoading(true);
    customersApi.completedTasks(customerId, customerName, true)
      .then(r => { setTasks(r.data.tasks || []); setLegacyTasks(r.data.legacy_tasks || []); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [customerId, customerName]);

  const filterTask = (t: Record<string, string>) => {
    if (catFilter === "전체") return true;
    const g = CAT_GROUPS.find(g => g.key === catFilter);
    if (!g) return true;
    if (g.cats === null && (g as { isEtc?: boolean }).isEtc) {
      const knownCats = ["출입국","영주권","전자민원","공증","여권","초청"];
      return !knownCats.includes(t.category || "");
    }
    return (g.cats as readonly string[]).includes(t.category || "");
  };

  const filtered = tasks.filter(filterTask);

  const BORDER = "#E2E8F0";
  const statusDot = (val: string) => val ? "✅" : "○";

  const TaskTable = ({ rows, isLegacy }: { rows: Record<string, string>[]; isLegacy?: boolean }) => (
    <div style={{ overflowX:"auto" }}>
      <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12 }}>
        <thead>
          <tr style={{ background:"#F7FAFC", borderBottom:`2px solid ${BORDER}` }}>
            {["접수일","구분","업무명","세부내용","완료일","접수","처리","보관"].map(h => (
              <th key={h} style={{ padding:"6px 8px", textAlign:"left", fontWeight:600, fontSize:11, color:"#718096", whiteSpace:"nowrap" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={8} style={{ padding:"20px", textAlign:"center", color:"#A0AEC0", fontSize:12 }}>
              {isLegacy ? "이름 기준 과거 업무 없음" : "완료업무 없음"}
            </td></tr>
          ) : rows.map((t, i) => (
            <tr key={t.id || i} style={{ borderBottom:`1px solid ${BORDER}`, background: i % 2 === 0 ? "#fff" : "#FAFAFA" }}>
              <td style={{ padding:"6px 8px", whiteSpace:"nowrap", color:"#4A5568" }}>{t.date || ""}</td>
              <td style={{ padding:"6px 8px", whiteSpace:"nowrap" }}>
                <span style={{ background:"#EDF2F7", borderRadius:4, padding:"1px 6px", fontSize:10, fontWeight:600, color:"#4A5568" }}>{t.category || ""}</span>
              </td>
              <td style={{ padding:"6px 8px", maxWidth:120, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{t.work || ""}</td>
              <td style={{ padding:"6px 8px", maxWidth:150, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", color:"#718096" }}>{t.details || ""}</td>
              <td style={{ padding:"6px 8px", whiteSpace:"nowrap", color:"#4A5568" }}>{t.complete_date || ""}</td>
              <td style={{ padding:"6px 8px", textAlign:"center", fontSize:11 }}>{statusDot(t.reception)}</td>
              <td style={{ padding:"6px 8px", textAlign:"center", fontSize:11 }}>{statusDot(t.processing)}</td>
              <td style={{ padding:"6px 8px", textAlign:"center", fontSize:11 }}>{statusDot(t.storage)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <>
      <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.45)", zIndex:400 }} onClick={onClose} />
      <div style={{
        position:"fixed", top:"50%", left:"50%",
        transform:"translate(-50%,-50%)",
        zIndex:401, width:"min(820px, 96vw)", maxHeight:"85vh",
        background:"#fff", borderRadius:14,
        boxShadow:"0 8px 40px rgba(0,0,0,0.2)",
        display:"flex", flexDirection:"column",
      }}>
        {/* 헤더 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"14px 20px", borderBottom:`1px solid ${BORDER}`, flexShrink:0 }}>
          <div>
            <div style={{ fontSize:15, fontWeight:700, color:"#1A202C" }}>{customerName} — 완료업무 내역</div>
            <div style={{ fontSize:11, color:"#A0AEC0", marginTop:2 }}>
              customer_id 기준 {tasks.length}건{legacyTasks.length > 0 ? ` + 이름 기준 참고 ${legacyTasks.length}건` : ""}
            </div>
          </div>
          <button onClick={onClose} style={{ padding:6, color:"#718096", background:"none", border:"none", cursor:"pointer" }}><X size={18} /></button>
        </div>

        {/* 카테고리 필터 */}
        <div style={{ display:"flex", gap:6, padding:"10px 20px", borderBottom:`1px solid ${BORDER}`, flexWrap:"wrap", flexShrink:0 }}>
          {CAT_GROUPS.map(g => (
            <button key={g.key} onClick={() => setCatFilter(g.key)}
              style={{
                padding:"4px 12px", borderRadius:20, fontSize:12, fontWeight:600, cursor:"pointer",
                border: catFilter === g.key ? "1px solid #D4A843" : "1px solid #E2E8F0",
                background: catFilter === g.key ? "#FFF9E6" : "#F7FAFC",
                color: catFilter === g.key ? "#7A5C10" : "#718096",
              }}>
              {g.key}
            </button>
          ))}
        </div>

        {/* 목록 */}
        <div style={{ flex:1, overflowY:"auto", padding:"0 0 12px" }}>
          {loading ? (
            <div style={{ padding:"32px", textAlign:"center", color:"#A0AEC0", fontSize:13 }}>불러오는 중...</div>
          ) : (
            <>
              <TaskTable rows={filtered} />
              {/* Legacy 섹션 */}
              {legacyTasks.length > 0 && (
                <div style={{ margin:"12px 20px 0" }}>
                  <button onClick={() => setShowLegacy(v => !v)}
                    style={{ fontSize:11, color:"#A0AEC0", background:"none", border:"none", cursor:"pointer", fontWeight:600 }}>
                    {showLegacy ? "▾" : "▸"} 이름 기준 과거 업무 ({legacyTasks.length}건, 참고자료)
                  </button>
                  {hasNameDuplicate && (
                    <span style={{ marginLeft:8, fontSize:10, color:"#E53E3E", fontWeight:600 }}>
                      ⚠️ 동명이인 가능성 — 정확하지 않을 수 있습니다.
                    </span>
                  )}
                  {!hasNameDuplicate && (
                    <span style={{ marginLeft:8, fontSize:10, color:"#A0AEC0" }}>
                      customer_id가 없는 과거 업무는 이름 기준 참고자료입니다.
                    </span>
                  )}
                  {showLegacy && (
                    <div style={{ marginTop:8, border:`1px solid ${BORDER}`, borderRadius:8, overflow:"hidden" }}>
                      <TaskTable rows={legacyTasks.filter(filterTask)} isLegacy />
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

// ── 숙소제공자 설정 모달 ───────────────────────────────────────────────────────
function AccommodationProviderModal({
  customerId, customerName, current, onClose, onSaved,
}: {
  customerId: string;
  customerName: string;
  current: AccommodationProvider | null;
  onClose: () => void;
  onSaved: (p: AccommodationProvider | null) => void;
}) {
  const isDB = current?.provider_type === "customer_db";
  const [tab, setTab] = useState<"search" | "manual">(isDB ? "search" : "manual");

  // DB 검색 state
  const [searchQ, setSearchQ] = useState(isDB ? (current?.provider_name || "") : "");
  const [searchResults, setSearchResults] = useState<CustomerSearchResult[]>([]);
  const [selectedDB, setSelectedDB] = useState<CustomerSearchResult | null>(
    isDB && current
      ? { id: current.provider_customer_id, name: current.provider_name, label: current.provider_name, reg_no: current.provider_reg_front }
      : null
  );

  // 수동 입력 state (한글성명/영문성/영문명/국적/등록번호앞뒤/연락처)
  const m = (key: keyof AccommodationProvider) =>
    current?.provider_type === "manual" ? (current[key] as string || "") : "";
  const [mName,      setMName]      = useState(m("provider_name"));
  const [mLastName,  setMLastName]  = useState(m("provider_last_name"));
  const [mFirstName, setMFirstName] = useState(m("provider_first_name"));
  const [mNation,    setMNation]    = useState(m("provider_nation"));
  const [mRegFront,  setMRegFront]  = useState(m("provider_reg_front"));
  const [mRegBack,   setMRegBack]   = useState(m("provider_reg_back"));
  const [mPhone,     setMPhone]     = useState(m("provider_phone"));

  const [saving,   setSaving]   = useState(false);
  const [deleting, setDeleting] = useState(false);

  const BORDER = "#E2E8F0";
  const GOLD   = "#D4A843";
  const inp: React.CSSProperties = {
    width:"100%", padding:"6px 9px", border:`1px solid ${BORDER}`,
    borderRadius:6, fontSize:12, boxSizing:"border-box",
  };

  // 검색 디바운스
  useEffect(() => {
    if (tab !== "search" || searchQ.length < 1) { setSearchResults([]); return; }
    const t = setTimeout(() => {
      quickDocApi.searchCustomers(searchQ).then(r => setSearchResults(r.data)).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [searchQ, tab]);

  const handleSave = async () => {
    setSaving(true);
    try {
      let payload: Partial<AccommodationProvider>;
      if (tab === "search") {
        if (!selectedDB) { toast.error("고객을 선택하세요."); setSaving(false); return; }
        payload = {
          provider_type:         "customer_db",
          provider_customer_id:  selectedDB.id,
          provider_name:         selectedDB.name,
          provider_reg_front:    selectedDB.reg_no || "",
        };
      } else {
        if (!mName.trim()) { toast.error("성명을 입력하세요."); setSaving(false); return; }
        payload = {
          provider_type:        "manual",
          provider_customer_id: "",
          provider_name:        mName.trim(),
          provider_last_name:   mLastName.trim(),
          provider_first_name:  mFirstName.trim(),
          provider_nation:      mNation.trim(),
          provider_reg_front:   mRegFront.trim(),
          provider_reg_back:    mRegBack.trim(),
          provider_phone:       mPhone.trim(),
        };
      }
      const res = await accommodationApi.save(customerId, payload);
      toast.success("숙소제공자가 고정되었습니다.");
      onSaved(res.data.data);
      onClose();
    } catch { toast.error("저장 실패"); }
    finally { setSaving(false); }
  };

  const handleDelete = async () => {
    if (!confirm("숙소제공자 연결을 해제하시겠습니까?")) return;
    setDeleting(true);
    try {
      await accommodationApi.delete(customerId);
      toast.success("숙소제공자 연결이 해제되었습니다.");
      onSaved(null); onClose();
    } catch { toast.error("해제 실패"); }
    finally { setDeleting(false); }
  };

  return (
    <>
      <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.35)", zIndex:300 }} onClick={onClose} />
      <div style={{
        position:"fixed", top:"50%", left:"50%",
        transform:"translate(-50%,-50%)",
        zIndex:301, width:"min(400px, 96vw)",
        background:"#fff", borderRadius:14,
        boxShadow:"0 8px 40px rgba(0,0,0,0.18)",
        display:"flex", flexDirection:"column",
        maxHeight:"90vh",
      }}>
        {/* 헤더 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"13px 18px", borderBottom:`1px solid ${BORDER}`, background:"#F7FAFC", flexShrink:0 }}>
          <div>
            <div style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>숙소제공자 설정</div>
            <div style={{ fontSize:11, color:"#718096" }}>대상: {customerName}</div>
          </div>
          <button onClick={onClose} style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}><X size={16} /></button>
        </div>

        <div style={{ overflowY:"auto", flex:1, padding:"14px 18px" }}>
          {/* 현재 설정 표시 */}
          {current && (
            <div style={{ marginBottom:12, padding:"9px 12px", background:"#EBF8FF", borderRadius:8, border:"1px solid #BEE3F8", display:"flex", alignItems:"center", justifyContent:"space-between" }}>
              <div>
                <div style={{ fontSize:12, fontWeight:700, color:"#2B6CB0" }}>현재: {current.provider_name}</div>
                {current.provider_type === "customer_db" && <div style={{ fontSize:10, color:"#718096" }}>고객 DB 연결</div>}
              </div>
              <button onClick={handleDelete} disabled={deleting}
                style={{ fontSize:11, padding:"4px 10px", borderRadius:5, border:"1px solid #FC8181", background:"#FFF5F5", color:"#C53030", cursor:"pointer", flexShrink:0 }}>
                {deleting ? "해제 중..." : "연결 해제"}
              </button>
            </div>
          )}

          {/* 탭 */}
          <div style={{ display:"flex", gap:4, marginBottom:12, background:"#F7FAFC", borderRadius:8, padding:4 }}>
            {(["search", "manual"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex:1, padding:"6px 0", borderRadius:6, fontSize:12, fontWeight:600,
                border:"none", cursor:"pointer",
                background: tab === t ? "#fff" : "transparent",
                color: tab === t ? GOLD : "#718096",
                boxShadow: tab === t ? "0 1px 4px rgba(0,0,0,0.08)" : "none",
              }}>
                {t === "search" ? "고객 DB 검색" : "직접 입력"}
              </button>
            ))}
          </div>

          {/* DB 검색 탭 */}
          {tab === "search" && (
            <div>
              <div style={{ position:"relative", marginBottom:8 }}>
                <Search size={12} style={{ position:"absolute", left:9, top:"50%", transform:"translateY(-50%)", color:"#A0AEC0" }} />
                <input autoFocus value={searchQ}
                  onChange={e => { setSearchQ(e.target.value); if (selectedDB && e.target.value !== selectedDB.name) setSelectedDB(null); }}
                  placeholder="이름 / 전화번호 / 고객ID 검색"
                  style={{ ...inp, paddingLeft:28 }} />
              </div>
              {searchResults.length > 0 && (
                <div style={{ border:`1px solid ${BORDER}`, borderRadius:8, maxHeight:160, overflowY:"auto", marginBottom:8 }}>
                  {searchResults.map(c => (
                    <button key={c.id} onClick={() => { setSelectedDB(c); setSearchQ(c.name); setSearchResults([]); }}
                      style={{ display:"block", width:"100%", textAlign:"left", padding:"7px 12px", border:"none", borderBottom:`1px solid ${BORDER}`, background: selectedDB?.id === c.id ? "#FFF9E6" : "#fff", cursor:"pointer", fontSize:12, color:"#2D3748" }}>
                      {c.name}
                      {c.name_en && <span style={{ fontSize:10, color:"#A0AEC0", marginLeft:4 }}>({c.name_en})</span>}
                    </button>
                  ))}
                </div>
              )}
              {selectedDB && (
                <div style={{ padding:"7px 10px", background:"#F0FFF4", borderRadius:7, fontSize:12, color:"#276749" }}>
                  ✅ {selectedDB.name} 선택됨
                </div>
              )}
            </div>
          )}

          {/* 수동 입력 탭 — 핵심 인적사항만 */}
          {tab === "manual" && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:7 }}>
              {([
                { label:"한글 성명*",  val:mName,      set:setMName,      wide:true  },
                { label:"영문 성",     val:mLastName,  set:setMLastName,  wide:false },
                { label:"영문 이름",   val:mFirstName, set:setMFirstName, wide:false },
                { label:"국적",        val:mNation,    set:setMNation,    wide:false },
                { label:"등록번호 앞", val:mRegFront,  set:setMRegFront,  wide:false },
                { label:"등록번호 뒤", val:mRegBack,   set:setMRegBack,   wide:false },
                { label:"연락처",      val:mPhone,     set:setMPhone,     wide:true  },
              ] as { label:string; val:string; set:(v:string)=>void; wide:boolean }[]).map(({ label, val, set, wide }) => (
                <div key={label} style={wide ? { gridColumn:"1/-1" } : {}}>
                  <label style={{ display:"block", fontSize:10, color:"#718096", marginBottom:2 }}>{label}</label>
                  <input value={val} onChange={e => set(e.target.value)} style={inp} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 저장 버튼 */}
        <div style={{ padding:"12px 18px", borderTop:`1px solid ${BORDER}`, flexShrink:0 }}>
          <button onClick={handleSave} disabled={saving}
            style={{ width:"100%", padding:"11px 0", borderRadius:8, fontSize:13, fontWeight:700, background: saving ? "#E2E8F0" : GOLD, color:"#fff", border:"none", cursor: saving ? "default" : "pointer" }}>
            {saving ? "저장 중..." : "숙소제공자 고정"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── 우측 드로어 ────────────────────────────────────────────────────────────────
function CustomerDrawer({
  customer, isNew, onClose, onSave, onDelete, isSaving,
  onOpenDocOverlay, onOpenQuickPoaOverlay,
}: {
  customer: Record<string, string> | null;
  isNew: boolean;
  onClose: () => void;
  onSave: (d: Record<string, string>) => void;
  onDelete?: (id: string) => void;
  isSaving: boolean;
  onOpenDocOverlay?: () => void;
  onOpenQuickPoaOverlay?: () => void;
}) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);

  // ── 서명 상태 ──
  const [hasSignature, setHasSignature] = useState<boolean | null>(null);
  const [signatureData, setSignatureData] = useState<string | null>(null);
  const [showSignatureFull, setShowSignatureFull] = useState(false);
  const [showSignModal, setShowSignModal] = useState(false);

  // ── 임시저장 슬롯 ──
  const [tempSlots, setTempSlots] = useState<{ slot: number; has_data: boolean; 비고: string }[]>([]);
  const [showTempSlots, setShowTempSlots] = useState(false);
  const { submit: submitSlotMap, isSubmitting: slotMapping } = useSubmit();

  // ── 숙소제공자 ──
  const [providerData, setProviderData] = useState<AccommodationProvider | null>(null);
  const [providerLoading, setProviderLoading] = useState(false);
  const [showProviderModal, setShowProviderModal] = useState(false);

  // ── 신원보증인 ──
  const [guarantorData, setGuarantorData] = useState<GuarantorConnection | null>(null);
  const [guarantorLoading, setGuarantorLoading] = useState(false);
  const [showGuarantorModal, setShowGuarantorModal] = useState(false);

  // ── 업무 현황 ──
  const [workSummary, setWorkSummary] = useState<WorkSummary | null>(null);
  const [showCompletedPopup, setShowCompletedPopup] = useState(false);
  const [showLegacyDelegation, setShowLegacyDelegation] = useState(false);

  // ── 하이코리아 만료일(동포) 보조 패널 ──
  const [showHikoreaPanel, setShowHikoreaPanel] = useState(false);
  const [hikoreaExpiry, setHikoreaExpiry] = useState("");

  // ── 하이코리아 ID찾기 보조 패널 ──
  const [showIdFindPanel, setShowIdFindPanel] = useState(false);

  // customer 객체 변경 시 form/UI 상태 초기화 (객체 참조 변경마다 실행)
  useEffect(() => {
    if (customer) {
      setForm({ ...customer });
      setDirty(false);
      setShowSignatureFull(false);
      setShowTempSlots(false);
      setShowHikoreaPanel(false);
      setHikoreaExpiry("");
      setShowIdFindPanel(false);
    }
  }, [customer]);

  // ── customerId/isNew 기준 외부 API 조회 ──────────────────────────────────
  // customer 객체 전체가 아닌 customerId 문자열만 dependency로 사용.
  // 저장 후 같은 customerId로 setSelectedCustomer해도 재조회하지 않음.
  const customerId = customer?.["고객ID"] || "";
  const customerName = customer?.["한글"] || "";

  // 서명 존재 여부 확인 (신규 고객 제외)
  useEffect(() => {
    if (!customerId || isNew) { setHasSignature(null); return; }
    fetch(`/api/signature/customer/${encodeURIComponent(customerId)}/exists`, {
      headers: { Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` },
    })
      .then((r) => { if (!r.ok) return; return r.json(); })
      .then((j) => { if (j) setHasSignature(j.exists ?? false); })
      .catch(() => {});
  }, [customerId, isNew]);

  // 임시저장 슬롯 로드 (서명 없는 고객 드로어에서만)
  useEffect(() => {
    if (isNew || hasSignature !== false) return;
    fetch("/api/signature/temp-slots", {
      headers: { Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` },
    })
      .then((r) => r.json())
      .then((j) => setTempSlots(Array.isArray(j) ? j : []))
      .catch(() => {});
  }, [isNew, hasSignature]);

  // 숙소제공자 조회 (신규 고객 제외)
  useEffect(() => {
    setProviderData(null);
    if (!customerId || isNew) { setProviderLoading(false); return; }
    setProviderLoading(true);
    accommodationApi.get(customerId)
      .then(r => { setProviderData(r.data || null); setProviderLoading(false); })
      .catch(() => { setProviderData(null); setProviderLoading(false); });
  }, [customerId, isNew]);

  // 신원보증인 조회 (신규 고객 제외)
  useEffect(() => {
    setGuarantorData(null);
    if (!customerId || isNew) { setGuarantorLoading(false); return; }
    setGuarantorLoading(true);
    guarantorApi.get(customerId)
      .then(r => { setGuarantorData(r.data || null); setGuarantorLoading(false); })
      .catch(() => { setGuarantorData(null); setGuarantorLoading(false); });
  }, [customerId, isNew]);

  // 업무 현황 로드 (신규 고객 제외)
  useEffect(() => {
    if (!customerId || isNew) { setWorkSummary(null); return; }
    customersApi.workSummary(customerId, customerName || undefined)
      .then(r => setWorkSummary(r.data))
      .catch(() => setWorkSummary(null));
  }, [customerId, isNew]);

  if (!customer) return null;

  const id = customer["고객ID"] || "";
  const name = form["한글"] || `${form["성"] ?? ""} ${form["명"] ?? ""}`.trim() || "신규 고객";

  // ── Dual popup helper: 외부 사이트(왼쪽) + 복붙용 고객카드(오른쪽) ─────────
  const openDualPopup = (externalUrl: string, winName: string, mode: string) => {
    const margin = 8, gap = 8;
    const availW = window.screen.availWidth;
    const availH = window.screen.availHeight;
    const totalW = availW - margin * 2;
    const totalH = availH - margin * 2;
    const rightW = Math.max(420, Math.min(520, Math.floor(totalW * 0.32)));
    const leftW  = Math.max(760, totalW - rightW - gap);
    const featLeft  = `width=${leftW},height=${totalH},left=${margin},top=${margin},resizable=yes,scrollbars=yes`;
    const featRight = `width=${rightW},height=${totalH},left=${margin + leftW + gap},top=${margin},resizable=yes,scrollbars=yes`;

    // 팝업별 고유 nonce — 크로스-고객 데이터 오염 방지
    const nonce = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const storageKey = `customer_copy_popup_data_${id}_${mode}_${nonce}`;

    // 고객 데이터 + 검증 메타데이터 저장 (nonce 키 → 로드 후 즉시 삭제됨)
    localStorage.setItem(storageKey, JSON.stringify({
      customerId: id,
      mode,
      savedAt: Date.now(),
      data: form,
    }));

    // 두 팝업을 동일 이벤트 내에서 즉시 열어 팝업 차단 방지
    const externalWin = window.open(externalUrl, winName, featLeft);
    const cardWin     = window.open(
      `/customer-copy-popup?customerId=${encodeURIComponent(id)}&mode=${encodeURIComponent(mode)}&nonce=${encodeURIComponent(nonce)}`,
      `customer-copy-popup-${id}-${nonce.slice(0, 8)}`,
      featRight,
    );

    if (!externalWin || !cardWin) {
      // 하나라도 차단됐으면 이미 열린 창도 닫고 스토리지 정리
      if (externalWin && !externalWin.closed) externalWin.close();
      if (cardWin     && !cardWin.closed)     cardWin.close();
      localStorage.removeItem(storageKey);
      toast.error("팝업이 차단되었습니다. 브라우저에서 팝업 허용 후 다시 시도해 주세요.");
      return;
    }

    // 왼쪽(외부 사이트) 닫힘 감시 → 오른쪽 고객카드 자동 닫기
    const timer = window.setInterval(() => {
      if (!externalWin || externalWin.closed) {
        if (cardWin && !cardWin.closed) cardWin.close();
        window.clearInterval(timer);
      }
    }, 500);
  };
  const rawFolder = form["폴더"] || "";
  const folderId = rawFolder.includes("drive.google.com")
    ? rawFolder.split("/").pop()?.split("?")[0] || "" : rawFolder;
  const folderUrl = folderId ? `https://drive.google.com/drive/folders/${folderId}` : null;

  const change = (k: string, v: string) => { setForm((p) => ({ ...p, [k]: v })); setDirty(true); };

  const cardDays = getDaysUntil(form["만기일"]);
  const passDays = getDaysUntil(form["만기"]);

  return (
    <>
      <div className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.2)" }} onClick={onClose} />
      <div className="hw-drawer open" style={{ zIndex: 50, width: "min(480px, 100vw)" }}>
        {/* 헤더 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"14px 20px", borderBottom:"1px solid #E2E8F0", flexShrink:0 }}>
          <div>
            <div style={{ fontWeight:600, fontSize:14, color:"#2D3748" }}>{isNew ? "신규 고객 등록" : name}</div>
            {!isNew && id && <div style={{ fontSize:11, color:"#A0AEC0", marginTop:2 }}>ID: {id}</div>}
          </div>
          <div style={{ display:"flex", gap:6, alignItems:"center" }}>
            {folderUrl && (
              <a href={folderUrl} target="_blank" rel="noopener noreferrer"
                style={{ display:"flex", alignItems:"center", gap:4, fontSize:12, color:"#3182CE", background:"#EBF8FF", border:"1px solid #BEE3F8", borderRadius:6, padding:"4px 10px" }}>
                <FolderOpen size={13} /> 폴더 <ExternalLink size={11} />
              </a>
            )}
            {!isNew && (
              <button
                onClick={() => {
                  localStorage.setItem("pinned_customer", JSON.stringify(customer));
                  const popup = window.open(
                    "/customer-popup",
                    "customer_card_popup",
                    "width=300,height=680,resizable=yes,scrollbars=yes"
                  );
                  if (popup) {
                    popup.focus();
                    toast.success(`${name} 고객카드 열림`);
                  } else {
                    window.dispatchEvent(new CustomEvent("pin-customer", { detail: customer }));
                    toast.success(`${name} 참조 고정됨 (팝업 차단 → 사이드 패널)`);
                  }
                }}
                title="새 창으로 고객카드 열기"
                style={{ display:"flex", alignItems:"center", gap:3, fontSize:11, padding:"4px 8px", border:"1px solid #E2E8F0", borderRadius:6, background:"#F7FAFC", color:"#718096" }}
              >
                <ExternalLink size={12} /> 팝업창
              </button>
            )}
            <button onClick={onClose} style={{ padding:6, color:"#718096" }}><X size={16} /></button>
          </div>
        </div>

        {/* 만기 D-Day */}
        {!isNew && (cardDays !== null || passDays !== null) && (
          <div style={{ padding:"8px 20px", background:"#F7FAFC", borderBottom:"1px solid #E2E8F0", display:"flex", gap:8, flexWrap:"wrap", flexShrink:0 }}>
            {[{ label:"등록증만기", days:cardDays }, { label:"여권만기", days:passDays }].map(({ label, days }) => {
              const badge = expiryBadge(days);
              if (!badge) return null;
              return (
                <span key={label} style={{ ...badge.style, borderRadius:20, padding:"2px 10px", fontSize:11, fontWeight:600 }}>
                  {label}: {badge.text}
                </span>
              );
            })}
          </div>
        )}

        {/* 필드 그룹 */}
        <div style={{ flex:1, overflowY:"auto", overflowX:"hidden", padding:"16px 20px", minHeight:0, boxSizing:"border-box" }}>
          {/* 업무 현황 섹션 — 기본정보 다음에 삽입 */}
          {!isNew && workSummary !== null && (() => {
            const CAT_GROUPS = [
              { key: "출입국",   label: "출입국" },
              { key: "전자민원", label: "전자민원" },
              { key: "공증",     label: "공증" },
              { key: "여권·초청", label: "여권·초청" },
              { key: "기타",     label: "기타" },
            ];
            const total = workSummary.total;
            const legacyTotal = workSummary.legacy_total;
            return (
              <div style={{ marginBottom:18 }}>
                <div style={{ fontSize:11, fontWeight:700, color:"#D4A843", marginBottom:8, textTransform:"uppercase", letterSpacing:"0.06em" }}>업무 현황</div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:6, marginBottom:8 }}>
                  {CAT_GROUPS.map(({ key, label }) => {
                    const cnt = workSummary.groups[key] ?? 0;
                    return (
                      <span key={key} style={{
                        display:"inline-flex", alignItems:"center", gap:4,
                        padding:"3px 8px", borderRadius:6, fontSize:11, fontWeight:600,
                        background: cnt > 0 ? "#EBF8FF" : "#F7FAFC",
                        color: cnt > 0 ? "#2B6CB0" : "#A0AEC0",
                        border: cnt > 0 ? "1px solid #BEE3F8" : "1px solid #E2E8F0",
                      }}>
                        {label} <strong>{cnt}</strong>
                      </span>
                    );
                  })}
                </div>
                {total > 0 && (
                  <button
                    onClick={() => setShowCompletedPopup(true)}
                    style={{
                      fontSize:11, padding:"4px 12px", borderRadius:6,
                      border:"1px solid #BEE3F8", background:"#EBF8FF",
                      color:"#2B6CB0", cursor:"pointer", fontWeight:600,
                    }}
                  >
                    완료업무 보기 ({total}건)
                  </button>
                )}
                {total === 0 && legacyTotal > 0 && (
                  <button
                    onClick={() => setShowCompletedPopup(true)}
                    style={{
                      fontSize:11, padding:"4px 12px", borderRadius:6,
                      border:"1px solid #E2E8F0", background:"#F7FAFC",
                      color:"#718096", cursor:"pointer", fontWeight:600,
                    }}
                  >
                    이름 기준 과거 업무 보기 ({legacyTotal}건)
                  </button>
                )}
                {total === 0 && legacyTotal === 0 && (
                  <span style={{ fontSize:11, color:"#A0AEC0" }}>완료업무 없음</span>
                )}
              </div>
            );
          })()}

          {DRAWER_GROUPS.map((grp) => (
            <div key={grp.title} style={{ marginBottom:18 }}>
              <div style={{ fontSize:11, fontWeight:700, color:"#D4A843", marginBottom:8, textTransform:"uppercase", letterSpacing:"0.06em" }}>{grp.title}</div>
              <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
                {grp.fields.map((f) => {
                  const wide = (f as { wide?: boolean }).wide;
                  return (
                    <div key={f.key} style={{ minWidth:0, overflow:"hidden", ...(wide ? { gridColumn:"1/-1" } : {}) }}>
                      <label style={{ display:"block", fontSize:11, color:"#718096", marginBottom:3 }}>{f.label}</label>
                      <input
                        type="text"
                        className="hw-input"
                        style={{ width:"100%", boxSizing:"border-box" }}
                        value={form[f.key] ?? ""}
                        onChange={(e) => change(f.key, e.target.value)}
                        placeholder={f.label}
                      />
                    </div>
                  );
                })}
              </div>
              {/* 기본정보 섹션 아래 — 액션 버튼들 */}
              {grp.title === "기본정보" && !isNew && (
                <>
                <div style={{ marginTop:8, display:"flex", gap:6, flexWrap:"wrap" }}>
                  {onOpenDocOverlay && (
                    <button
                      onClick={onOpenDocOverlay}
                      style={{
                        display:"flex", alignItems:"center", gap:5,
                        fontSize:11, padding:"5px 12px", borderRadius:6,
                        border:"1px solid #D4A843", color:"#6B5314",
                        background:"#FFF9E6", cursor:"pointer", fontWeight:600,
                      }}
                    >
                      <FileText size={11} /> 문서자동작성
                    </button>
                  )}
                  <button
                    onClick={() => setShowProviderModal(true)}
                    style={{
                      display:"flex", alignItems:"center", gap:5,
                      fontSize:11, padding:"5px 12px", borderRadius:6,
                      border: providerData ? "1px solid #BEE3F8" : "1px solid #CBD5E0",
                      color: providerLoading ? "#A0AEC0" : providerData ? "#2B6CB0" : "#4A5568",
                      background: providerData ? "#EBF8FF" : "#F7FAFC",
                      cursor:"pointer", fontWeight:600,
                    }}
                  >
                    <Home size={11} />
                    {providerLoading ? "숙소 확인 중..." : providerData ? `숙소: ${providerData.provider_name}` : "숙소제공자"}
                  </button>
                  <button
                    onClick={() => setShowGuarantorModal(true)}
                    style={{
                      display:"flex", alignItems:"center", gap:5,
                      fontSize:11, padding:"5px 12px", borderRadius:6,
                      border: guarantorData ? "1px solid #C6F6D5" : "1px solid #CBD5E0",
                      color: guarantorLoading ? "#A0AEC0" : guarantorData ? "#276749" : "#4A5568",
                      background: guarantorData ? "#F0FFF4" : "#F7FAFC",
                      cursor:"pointer", fontWeight:600,
                    }}
                  >
                    <Shield size={11} />
                    {guarantorLoading ? "보증인 확인 중..." : guarantorData ? `보증인: ${guarantorData.guarantor_name}` : "신원보증인"}
                  </button>
                  {onOpenQuickPoaOverlay && (
                    <button
                      onClick={onOpenQuickPoaOverlay}
                      title="원클릭 작성"
                      style={{
                        display:"flex", alignItems:"center", justifyContent:"center",
                        width:28, height:28, borderRadius:6,
                        border:"1px solid #BEE3F8",
                        background:"#EBF8FF", color:"#2B6CB0",
                        cursor:"pointer", flexShrink:0,
                      }}
                    >
                      <Zap size={12} />
                    </button>
                  )}
                  {!isNew && (
                    <button
                      onClick={() => { setShowHikoreaPanel(v => !v); setShowIdFindPanel(false); }}
                      title="체류만료조회(동포)"
                      style={{
                        display:"flex", alignItems:"center", justifyContent:"center",
                        width:28, height:28, borderRadius:6,
                        border: showHikoreaPanel ? "1px solid #9AE6B4" : "1px solid #C6F6D5",
                        background: showHikoreaPanel ? "#C6F6D5" : "#F0FFF4",
                        color:"#276749",
                        cursor:"pointer", flexShrink:0,
                      }}
                    >
                      <Globe size={12} />
                    </button>
                  )}
                  {!isNew && (
                    <button
                      onClick={() => { setShowIdFindPanel(v => !v); setShowHikoreaPanel(false); }}
                      title="하이코리아 ID찾기"
                      style={{
                        display:"flex", alignItems:"center", justifyContent:"center",
                        width:28, height:28, borderRadius:6,
                        border: showIdFindPanel ? "1px solid #B794F4" : "1px solid #D6BCFA",
                        background: showIdFindPanel ? "#D6BCFA" : "#FAF5FF",
                        color:"#553C9A",
                        cursor:"pointer", flexShrink:0, fontWeight:700, fontSize:9,
                      }}
                    >
                      ID
                    </button>
                  )}
                </div>
                {/* ── 하이코리아 만료일 보조 패널: 버튼 바로 아래 렌더 ── */}
                {showHikoreaPanel && (() => {
                  const passport  = (form["여권"] || "").trim();
                  const reg6      = (form["등록증"] || "").trim();
                  const birthdate = reg6 ? "19" + reg6 : "";
                  const NATION    = "한국계 중국인";
                  const copyVal = (text: string, label: string) => {
                    navigator.clipboard.writeText(text).catch(() => {});
                    toast.success(`${label} 복사됨`);
                  };
                  return (
                    <div style={{
                      marginTop:10, padding:"11px 13px", borderRadius:8,
                      border:"1px solid #9AE6B4", background:"#F0FFF4",
                      fontSize:12,
                    }}>
                      {/* 헤더 */}
                      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:9 }}>
                        <span style={{ fontSize:11, fontWeight:700, color:"#276749" }}>
                          체류만료조회 보조
                        </span>
                        <div style={{ display:"flex", gap:5, alignItems:"center" }}>
                          <button
                            onClick={() => openDualPopup(
                              "https://www.hikorea.go.kr/info/CheckExprYmdByPassNoR.pt",
                              "hikorea-expiry-check",
                              "expiry",
                            )}
                            style={{ fontSize:10, padding:"2px 9px", borderRadius:4, border:"1px solid #9AE6B4", background:"#C6F6D5", color:"#276749", cursor:"pointer", fontWeight:600, whiteSpace:"nowrap" }}
                          >
                            하이코리아 열기
                          </button>
                          <button
                            onClick={() => setShowHikoreaPanel(false)}
                            style={{ padding:2, background:"none", border:"none", cursor:"pointer", color:"#A0AEC0", lineHeight:1 }}
                          >
                            <X size={13} />
                          </button>
                        </div>
                      </div>
                      {/* 복사 항목 */}
                      {[
                        { label: "여권번호",       value: passport,  warn: !passport ? "여권번호 없음" : "" },
                        { label: "국적",           value: NATION,    warn: "" },
                        { label: "생년월일",       value: birthdate, warn: !reg6 ? "등록번호 없음" : "" },
                      ].map(({ label, value, warn }) => (
                        <div key={label} style={{ display:"flex", alignItems:"center", gap:6, marginBottom:5 }}>
                          <span style={{ fontSize:10, color:"#4A5568", width:52, flexShrink:0 }}>{label}</span>
                          {warn
                            ? <span style={{ fontSize:10, color:"#E53E3E" }}>⚠️ {warn}</span>
                            : <>
                                <span style={{ fontSize:11, fontWeight:600, color:"#1A202C", flex:1, fontFamily:"monospace" }}>{value}</span>
                                <button onClick={() => copyVal(value, label)}
                                  style={{ fontSize:10, padding:"1px 7px", borderRadius:4, border:"1px solid #9AE6B4", background:"#fff", color:"#276749", cursor:"pointer", flexShrink:0 }}>
                                  복사
                                </button>
                              </>
                          }
                        </div>
                      ))}
                      {/* 입력확인 안내 */}
                      <div style={{ marginTop:7, padding:"5px 8px", borderRadius:5, background:"#FFFBEB", border:"1px solid #F6E05E", fontSize:10, color:"#744210" }}>
                        입력확인란(보안숫자)은 화면의 숫자를 직접 입력해야 합니다.
                      </div>
                      {/* 체류만료일 반영 */}
                      <div style={{ marginTop:9, borderTop:"1px solid #C6F6D5", paddingTop:9 }}>
                        <div style={{ fontSize:10, color:"#276749", fontWeight:600, marginBottom:5 }}>
                          조회 결과 반영
                        </div>
                        <div style={{ display:"flex", gap:6, alignItems:"center" }}>
                          <input
                            type="text"
                            placeholder="YYYY-MM-DD"
                            value={hikoreaExpiry}
                            onChange={(e) => setHikoreaExpiry(e.target.value)}
                            style={{
                              flex:1, padding:"4px 7px", border:"1px solid #9AE6B4",
                              borderRadius:5, fontSize:11, background:"#fff",
                              outline:"none", boxSizing:"border-box",
                            }}
                          />
                          <button
                            disabled={!hikoreaExpiry.trim()}
                            onClick={() => {
                              if (!hikoreaExpiry.trim()) return;
                              change("만기일", hikoreaExpiry.trim());
                              toast.success("등록만기일에 반영되었습니다. 저장 버튼을 눌러 저장하세요.");
                            }}
                            style={{
                              fontSize:10, padding:"4px 9px", borderRadius:5, whiteSpace:"nowrap",
                              border:"1px solid #9AE6B4", background: hikoreaExpiry.trim() ? "#C6F6D5" : "#E2E8F0",
                              color: hikoreaExpiry.trim() ? "#276749" : "#A0AEC0",
                              cursor: hikoreaExpiry.trim() ? "pointer" : "not-allowed", fontWeight:600,
                            }}
                          >
                            등록만기일에 반영
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })()}
                {/* ── 하이코리아 ID찾기 보조 패널: 버튼 바로 아래 렌더 ── */}
                {showIdFindPanel && (() => {
                  const surname  = (form["성"] || "").trim().toUpperCase();
                  const given    = (form["명"] || "").trim().toUpperCase();
                  const engName  = [surname, given].filter(Boolean).join(" ");
                  const reg6     = (form["등록증"] || "").trim();
                  const reg7     = (form["번호"]   || "").trim();
                  const birthdate = reg6 ? "19" + reg6 : "";
                  const regNoRaw = reg6 + reg7;
                  const copyVal = (text: string, label: string) => {
                    if (!text) { toast.error(`${label} 값이 없습니다.`); return; }
                    navigator.clipboard.writeText(text).catch(() => {});
                    toast.success(`${label} 복사됨`);
                  };
                  return (
                    <div style={{
                      marginTop:10, padding:"11px 13px", borderRadius:8,
                      border:"1px solid #B794F4", background:"#FAF5FF",
                      fontSize:12,
                    }}>
                      {/* 헤더 */}
                      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:9 }}>
                        <span style={{ fontSize:11, fontWeight:700, color:"#553C9A" }}>
                          하이코리아 ID찾기 보조
                        </span>
                        <div style={{ display:"flex", gap:5, alignItems:"center" }}>
                          <button
                            onClick={() => openDualPopup(
                              "https://www.hikorea.go.kr/memb/membIdFindRM.pt",
                              "hikorea-id-find",
                              "hikorea-id",
                            )}
                            style={{ fontSize:10, padding:"2px 9px", borderRadius:4, border:"1px solid #B794F4", background:"#D6BCFA", color:"#553C9A", cursor:"pointer", fontWeight:600, whiteSpace:"nowrap" }}
                          >
                            ID찾기 열기
                          </button>
                          <button
                            onClick={() => setShowIdFindPanel(false)}
                            style={{ padding:2, background:"none", border:"none", cursor:"pointer", color:"#A0AEC0", lineHeight:1 }}
                          >
                            <X size={13} />
                          </button>
                        </div>
                      </div>
                      {/* 복사 항목 */}
                      {[
                        { label: "영문이름",        value: engName,     warn: !engName  ? "영문 성/이름 없음" : "",        copyVal: engName     },
                        { label: "생년월일",        value: birthdate,   warn: !reg6     ? "등록번호 앞자리 없음" : "",     copyVal: birthdate   },
                        { label: "외국인등록번호",  value: regNoRaw,     warn: !reg6 || !reg7 ? (!reg6 ? "등록번호 앞자리 없음" : "등록번호 뒷자리 없음") : "", copyVal: regNoRaw },
                      ].map(({ label, value, warn, copyVal: cv }) => (
                        <div key={label} style={{ display:"flex", alignItems:"center", gap:6, marginBottom:5 }}>
                          <span style={{ fontSize:10, color:"#4A5568", width:74, flexShrink:0 }}>{label}</span>
                          {warn
                            ? <span style={{ fontSize:10, color:"#E53E3E" }}>⚠️ {warn}</span>
                            : <>
                                <span style={{ fontSize:11, fontWeight:600, color:"#1A202C", flex:1, fontFamily:"monospace" }}>{value}</span>
                                <button onClick={() => copyVal(cv, label)}
                                  style={{ fontSize:10, padding:"1px 7px", borderRadius:4, border:"1px solid #B794F4", background:"#fff", color:"#553C9A", cursor:"pointer", flexShrink:0 }}>
                                  복사
                                </button>
                              </>
                          }
                        </div>
                      ))}
                    </div>
                  );
                })()}
                {/* ── 소시넷 ID찾기 보조 패널: 하이코리아 ID찾기 패널 바로 아래 ── */}
                {showIdFindPanel && (() => {
                  const surname2  = (form["성"] || "").trim().toUpperCase();
                  const given2    = (form["명"] || "").trim().toUpperCase();
                  const engName2  = [surname2, given2].filter(Boolean).join(" ");
                  const reg6s     = (form["등록증"] || "").trim();
                  const reg7s     = (form["번호"]   || "").trim();
                  const passport2 = (form["여권"]   || "").trim();
                  const phone2    = [form["연"] || "", form["락"] || "", form["처"] || ""]
                    .map(s => s.replace(/\D/g, "")).join("");
                  const copyVal2 = (text: string, label: string) => {
                    if (!text) { toast.error(`${label} 값이 없습니다.`); return; }
                    navigator.clipboard.writeText(text).catch(() => {});
                    toast.success(`${label} 복사됨`);
                  };
                  return (
                    <div style={{
                      marginTop:8, padding:"11px 13px", borderRadius:8,
                      border:"1px solid #9AE6B4", background:"#F0FFF4",
                      fontSize:12,
                    }}>
                      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:9 }}>
                        <span style={{ fontSize:11, fontWeight:700, color:"#276749" }}>
                          소시넷 ID찾기 보조
                        </span>
                        <button
                          onClick={() => openDualPopup(
                            "https://www.socinet.go.kr/sPopup/FindIdPwPopup.jsp",
                            "socinet-id-find",
                            "socinet-id",
                          )}
                          style={{ fontSize:10, padding:"2px 9px", borderRadius:4, border:"1px solid #9AE6B4", background:"#C6F6D5", color:"#276749", cursor:"pointer", fontWeight:600, whiteSpace:"nowrap" }}
                        >
                          ID찾기 열기
                        </button>
                      </div>
                      {[
                        { label: "영문이름",        value: engName2,  warn: !engName2  ? "영문 성/이름 없음" : ""        },
                        { label: "등록증 앞 6자리", value: reg6s,     warn: !reg6s     ? "등록번호 앞자리 없음" : ""     },
                        { label: "등록증 뒤 7자리", value: reg7s,     warn: !reg7s     ? "등록번호 뒷자리 없음" : ""     },
                        { label: "여권번호",        value: passport2, warn: !passport2 ? "여권번호 없음" : ""           },
                        { label: "휴대폰번호",      value: phone2,    warn: !phone2    ? "전화번호 없음" : ""            },
                      ].map(({ label, value, warn }) => (
                        <div key={label} style={{ display:"flex", alignItems:"center", gap:6, marginBottom:5 }}>
                          <span style={{ fontSize:10, color:"#4A5568", width:80, flexShrink:0 }}>{label}</span>
                          {warn
                            ? <span style={{ fontSize:10, color:"#E53E3E" }}>⚠️ {warn}</span>
                            : <>
                                <span style={{ fontSize:11, fontWeight:600, color:"#1A202C", flex:1, fontFamily:"monospace" }}>{value}</span>
                                <button onClick={() => copyVal2(value, label)}
                                  style={{ fontSize:10, padding:"1px 7px", borderRadius:4, border:"1px solid #9AE6B4", background:"#fff", color:"#276749", cursor:"pointer", flexShrink:0 }}>
                                  복사
                                </button>
                              </>
                          }
                        </div>
                      ))}
                    </div>
                  );
                })()}
                </>
              )}
            </div>
          ))}

          {/* 위임내역 — 읽기전용 접힘 섹션 */}
          {!isNew && form["위임내역"] && (
            <div style={{ marginBottom:18 }}>
              <button
                onClick={() => setShowLegacyDelegation(v => !v)}
                style={{
                  display:"flex", alignItems:"center", gap:6,
                  fontSize:11, fontWeight:700, color:"#A0AEC0",
                  background:"none", border:"none", cursor:"pointer", padding:0,
                  textTransform:"uppercase", letterSpacing:"0.06em",
                }}
              >
                {showLegacyDelegation ? "▾" : "▸"} 기존 위임내역 (참고용)
              </button>
              {showLegacyDelegation && (
                <textarea
                  readOnly
                  value={form["위임내역"] ?? ""}
                  style={{
                    marginTop:6, width:"100%", height:120, resize:"vertical",
                    border:"1px solid #E2E8F0", borderRadius:6,
                    padding:"7px 10px", fontSize:11, color:"#718096",
                    background:"#F7FAFC", boxSizing:"border-box",
                    fontFamily:"inherit", lineHeight:1.6,
                  }}
                />
              )}
            </div>
          )}

          {/* 서명 섹션 (신규 등록 제외) */}
          {!isNew && (
            <div style={{ marginBottom:18 }}>
              <div style={{ fontSize:11, fontWeight:700, color:"#D4A843", marginBottom:8, textTransform:"uppercase", letterSpacing:"0.06em" }}>서명</div>
              <div style={{ border:"1px solid #E2E8F0", borderRadius:8, padding:"10px 12px", background:"#FAFAFA" }}>
                <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:8 }}>
                  {hasSignature === null && <span style={{ fontSize:12, color:"#A0AEC0" }}>확인 중...</span>}
                  {hasSignature === true && (
                    <span style={{ fontSize:12, color:"#276749", fontWeight:600 }}>● 서명 있음</span>
                  )}
                  {hasSignature === false && (
                    <span style={{ fontSize:12, color:"#A0AEC0" }}>○ 서명 없음</span>
                  )}
                  {hasSignature === true && !showSignatureFull && (
                    <button
                      onClick={() => {
                        const id = customer?.["고객ID"] || "";
                        fetch(`/api/signature/customer/${encodeURIComponent(id)}`, {
                          headers: { Authorization: `Bearer ${localStorage.getItem("access_token") || ""}` },
                        })
                          .then((r) => r.json())
                          .then((j) => { setSignatureData(j.data ?? null); setShowSignatureFull(true); })
                          .catch(() => toast.error("서명 로딩 실패"));
                      }}
                      style={{ fontSize:11, color:"#3182CE", background:"none", border:"none", cursor:"pointer", padding:0 }}
                    >
                      서명 확인
                    </button>
                  )}
                </div>
                {showSignatureFull && signatureData && (
                  <img src={signatureData} alt="고객 서명" style={{ maxWidth:"100%", border:"1px solid #E2E8F0", borderRadius:6, marginBottom:8 }} />
                )}
                <div style={{ display:"flex", gap:8, flexWrap:"wrap" }}>
                  <button
                    onClick={() => setShowSignModal(true)}
                    style={{
                      fontSize:11, padding:"5px 12px", borderRadius:6,
                      border:"1px solid #D4A843", color:"#C27800",
                      background:"#FFF8EC", cursor:"pointer", fontWeight:600,
                    }}
                  >
                    {hasSignature ? "서명 재등록" : "서명 등록"}
                  </button>
                  {/* 임시저장 서명 사용 — 서명 없고 슬롯에 데이터 있을 때만 표시 */}
                  {hasSignature === false && tempSlots.some((s) => s.has_data) && (
                    <button
                      onClick={() => setShowTempSlots((v) => !v)}
                      style={{
                        fontSize:11, padding:"5px 12px", borderRadius:6,
                        border:"1px solid #CBD5E0", color:"#4A5568",
                        background:"#F7FAFC", cursor:"pointer", fontWeight:600,
                      }}
                    >
                      임시저장 서명 사용
                    </button>
                  )}
                </div>
                {/* 슬롯 선택 목록 */}
                {showTempSlots && (
                  <div style={{ marginTop:8, border:"1px solid #E2E8F0", borderRadius:6, overflow:"hidden" }}>
                    {tempSlots.map((s) => (
                      <button
                        key={s.slot}
                        disabled={!s.has_data}
                        onClick={() => {
                          if (!s.has_data || slotMapping) return;
                          submitSlotMap(
                            async () => {
                              const res = await fetch(
                                `/api/signature/temp-slots/${s.slot}/map/${encodeURIComponent(id)}`,
                                { method:"POST", headers:{ Authorization:`Bearer ${localStorage.getItem("access_token") || ""}` } }
                              );
                              if (!res.ok) throw new Error();
                              const dataRes = await fetch(
                                `/api/signature/customer/${encodeURIComponent(id)}`,
                                { headers:{ Authorization:`Bearer ${localStorage.getItem("access_token") || ""}` } }
                              );
                              const dataJson = await dataRes.json();
                              setHasSignature(true);
                              setSignatureData(dataJson.data ?? null);
                              setShowSignatureFull(true);
                              setShowTempSlots(false);
                            },
                            { successMessage: "임시저장 서명이 고객에 연결되었습니다.", errorMessage: "매핑 실패" }
                          );
                        }}
                        style={{
                          display:"block", width:"100%", textAlign:"left",
                          padding:"7px 12px", background: s.has_data ? "#fff" : "#F7FAFC",
                          border:"none", borderBottom:"1px solid #E2E8F0",
                          cursor: s.has_data ? "pointer" : "default",
                          fontSize:12,
                          color: s.has_data ? "#2D3748" : "#A0AEC0",
                        }}
                      >
                        슬롯 {s.slot}: {s.has_data ? (s.비고 || "서명 있음") : "비어있음"}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* 푸터 */}
        <div style={{ padding:"12px 20px", borderTop:"1px solid #E2E8F0", display:"flex", justifyContent:"space-between", alignItems:"center", flexShrink:0 }}>
          <div>
            {!isNew && onDelete && (
              <SubmitButton
                isSubmitting={false}
                onClick={() => { if (confirm(`'${name}' 고객을 삭제하시겠습니까?`)) onDelete(id); }}
                variant="danger"
                className="text-xs"
                style={{ padding: "6px 12px", fontSize: 12 }}
              >
                <><Trash2 size={12} /> 삭제</>
              </SubmitButton>
            )}
          </div>
          <div style={{ display:"flex", gap:8 }}>
            <button onClick={onClose} className="btn-secondary text-xs">취소</button>
            <SubmitButton
              isSubmitting={isSaving}
              disabled={!dirty && !isNew}
              onClick={() => onSave(form)}
              loadingText={isNew ? "등록 중..." : "저장 중..."}
              className="text-xs"
              style={{ padding: "6px 12px", fontSize: 12 }}
            >
              <><Save size={12} /> {isNew ? "등록" : "저장"}</>
            </SubmitButton>
          </div>
        </div>
      </div>

      {/* 서명 모달 */}
      {showSignModal && (
        <SignatureModal
          type="customer"
          customerId={id}
          onSave={(data) => {
            setHasSignature(true);
            setSignatureData(data);
            setShowSignatureFull(true);
          }}
          onClose={() => setShowSignModal(false)}
        />
      )}

      {/* 숙소제공자 설정 모달 */}
      {showProviderModal && (
        <AccommodationProviderModal
          customerId={id}
          customerName={name}
          current={providerData}
          onClose={() => setShowProviderModal(false)}
          onSaved={(p) => setProviderData(p)}
        />
      )}

      {/* 신원보증인 설정 모달 */}
      {showGuarantorModal && (
        <GuarantorModal
          customerId={id}
          customerName={name}
          current={guarantorData}
          onClose={() => setShowGuarantorModal(false)}
          onSaved={(g) => setGuarantorData(g)}
        />
      )}

      {/* 완료업무 팝업 */}
      {showCompletedPopup && (
        <CompletedTasksModal
          customerId={id}
          customerName={form["한글"] || name}
          hasNameDuplicate={workSummary?.has_name_duplicate ?? false}
          onClose={() => setShowCompletedPopup(false)}
        />
      )}
    </>
  );
}

// ── 메인 페이지 ────────────────────────────────────────────────────────────────
export default function CustomersPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState<Record<string, string> | null>(null);
  const [isNewMode, setIsNewMode] = useState(false);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;

  // 신규 등록 후 서명 프롬프트
  const [signPrompt, setSignPrompt] = useState<{ name: string; customerId: string } | null>(null);
  const [showSignModal, setShowSignModal] = useState(false);
  const [awaitingRefresh, setAwaitingRefresh] = useState(false);

  // 문서자동작성 오버레이
  const [docOverlayOpen, setDocOverlayOpen] = useState(false);
  // 원클릭 작성 오버레이
  const [quickPoaOverlayOpen, setQuickPoaOverlayOpen] = useState(false);

  // 400ms 디바운스 + 2자 미만 입력은 전체 목록 표시 (빈 쿼리와 동일)
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search.length < 2 ? "" : search);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);

  const { data: pageData, isLoading, isFetching, error } = useQuery({
    queryKey: ["customers", debouncedSearch, page],
    queryFn: ({ signal }) =>
      customersApi.list(debouncedSearch || undefined, page, PAGE_SIZE, signal).then((r) => r.data as {
        items: Record<string, string>[];
        total: number;
        page: number;
        page_size: number;
        total_pages: number;
      }),
    staleTime: 2_000,
  });

  const customers = pageData?.items ?? [];
  const total = pageData?.total ?? 0;
  const totalPages = pageData?.total_pages ?? 0;

  // 현재 페이지 로드 완료 시 다음 페이지 미리 prefetch
  useEffect(() => {
    if (!pageData || page >= pageData.total_pages) return;
    qc.prefetchQuery({
      queryKey: ["customers", debouncedSearch, page + 1],
      queryFn: () =>
        customersApi.list(debouncedSearch || undefined, page + 1, PAGE_SIZE)
          .then((r) => r.data),
      staleTime: 2_000,
    });
  }, [pageData, page, debouncedSearch, qc]);

  useEffect(() => {
    if (awaitingRefresh && !isFetching) setAwaitingRefresh(false);
  }, [isFetching, awaitingRefresh]);

  useEffect(() => {
    if (searchParams.get("action") === "new") {
      setSelectedCustomer(emptyCustomer()); setIsNewMode(true);
      router.replace("/customers");
    }
  }, [searchParams, router]);

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, string> }) => customersApi.update(id, data),
    onSuccess: (_, variables) => {
      toast.success("저장됨");
      qc.invalidateQueries({ queryKey: ["customers"] });
      // 드로어를 닫지 않고 저장된 데이터로 업데이트 → 바로 반영된 내용 확인 가능
      setSelectedCustomer(variables.data);
    },
    onError: () => toast.error("저장 실패"),
  });
  const addMut = useMutation({
    mutationFn: (data: Record<string, string>) => customersApi.add(data),
    onSuccess: (res, variables) => {
      const newId = (res.data as { 고객ID?: string })?.["고객ID"] ?? "";
      const name = (variables["한글"] || `${variables["성"] ?? ""} ${variables["명"] ?? ""}`.trim()) || "신규 고객";
      toast.success("신규 고객 등록됨");
      setAwaitingRefresh(true);
      qc.invalidateQueries({ queryKey: ["customers"] });
      setSelectedCustomer(null);
      setIsNewMode(false);
      if (newId) setSignPrompt({ name, customerId: newId });
    },
    onError: () => toast.error("등록 실패"),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => customersApi.delete(id),
    onSuccess: () => { toast.success("삭제됨"); qc.invalidateQueries({ queryKey: ["customers"] }); setSelectedCustomer(null); },
    onError: () => toast.error("삭제 실패"),
  });

  const DATE_FIELDS = ["발급일", "만기일", "발급", "만기"];
  const handleSave = (form: Record<string, string>) => {
    const normalized = { ...form };
    DATE_FIELDS.forEach((f) => { if (normalized[f]) normalized[f] = normalizeDate(normalized[f]); });
    if (isNewMode) { addMut.mutate(normalized); }
    else { const id = normalized["고객ID"] || selectedCustomer?.["고객ID"] || ""; updateMut.mutate({ id, data: normalized }); }
  };

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14, position:"relative", minHeight:"100%", marginTop:-10 }}>
      {/* 툴바 — flex row, 각 아이템에 명시적 shrink/grow 지정 */}
      <div style={{ display:"flex", alignItems:"center", gap:10 }}>
        <h1 className="hw-page-title" style={{ flexShrink:0 }}>고객관리</h1>
        {/* hw-search-bar CSS 클래스 사용 안 함: flex:1 / max-width:520px 가 버튼 overlap 유발 */}
        <div style={{ position:"relative", width:260, flexShrink:0 }}>
          <Search size={13} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"#A0AEC0", pointerEvents:"none" }} />
          <input
            type="text"
            placeholder="이름, 여권번호, 국적 검색..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onFocus={() => { setDocOverlayOpen(false); setQuickPoaOverlayOpen(false); }}
            style={{
              width:"100%", height:36, border:"1px solid #E2E8F0", borderRadius:20,
              padding:"0 16px 0 38px", fontSize:13, outline:"none", boxSizing:"border-box",
              background:"#F8F9FA", color:"var(--hw-text)",
            }}
          />
        </div>
        <button
          onClick={() => { setSelectedCustomer(emptyCustomer()); setIsNewMode(true); }}
          className="btn-primary"
          style={{ flexShrink:0, display:"flex", alignItems:"center", gap:6, fontSize:12 }}
        >
          <UserPlus size={14} /> 신규 고객
        </button>
        {total > 0 && (
          <span style={{ fontSize:12, color:"#718096", marginLeft:"auto", flexShrink:0 }}>
            총 <strong style={{ color:"#2D3748" }}>{total}</strong>명
          </span>
        )}
      </div>

      {/* 테이블 */}
      {(addMut.isPending || awaitingRefresh) && (
        <div style={{
          display:"flex", alignItems:"center", gap:10,
          padding:"10px 16px", borderRadius:8,
          background:"#EBF8FF", border:"1px solid #BEE3F8",
          fontSize:13, color:"#2B6CB0", fontWeight:600,
        }}>
          <Loader2 size={16} style={{ animation:"spin 1s linear infinite", flexShrink:0 }} />
          {addMut.isPending ? "고객 정보를 저장하는 중입니다..." : "고객 목록을 업데이트하는 중입니다..."}
        </div>
      )}
      {isLoading ? (
        <div className="hw-card" style={{ color:"#A0AEC0", fontSize:13 }}>불러오는 중...</div>
      ) : error ? (
        <div className="hw-card" style={{ color:"#C53030", fontSize:13 }}>데이터 로딩 오류. 새로고침 해주세요.</div>
      ) : customers.length === 0 ? (
        <div className="hw-card" style={{ color:"#A0AEC0", fontSize:13, textAlign:"center", padding:"40px 0" }}>
          {search ? `'${search}' 검색 결과가 없습니다.` : "등록된 고객이 없습니다."}
        </div>
      ) : (
        <div className="hw-card" style={{ padding:0, overflow:"hidden" }}>
          <div style={{ overflowX:"auto" }}>
            <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12, tableLayout:"fixed" }}>
              <colgroup>
                {TABLE_COLS.map((col) => (
                  <col key={col.key} style={{ width: col.w }} />
                ))}
              </colgroup>
              <thead>
                <tr style={{ background:"#F7FAFC", borderBottom:"2px solid #E2E8F0" }}>
                  {TABLE_COLS.map((col) => (
                    <th key={col.key} style={{
                      padding:"8px 6px", textAlign:"left", fontWeight:600,
                      fontSize:11, color:"#718096", whiteSpace:"nowrap",
                      overflow:"hidden", textOverflow:"ellipsis",
                    }}>{col.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {customers.map((c) => {
                  const id = c["고객ID"] || "";
                  const tel = [c["연"] || "", c["락"] || "", c["처"] || ""].filter(Boolean).join("-");
                  const isSelected = selectedCustomer?.["고객ID"] === id;
                  return (
                    <tr key={id} onClick={() => { setSelectedCustomer(c); setIsNewMode(false); setDocOverlayOpen(false); setQuickPoaOverlayOpen(false); }}
                      style={{ ...rowHighlight(c), cursor:"pointer", borderBottom:"1px solid #EDF2F7",
                        ...(isSelected ? { background:"rgba(212,168,67,0.08)", outline:"2px solid rgba(212,168,67,0.3)" } : {}) }}>
                      {TABLE_COLS.map((col) => {
                        const val = col.key === "_tel" ? tel : (c[col.key] || "");
                        const isExpiry = col.key === "만기일" || col.key === "만기";
                        const badge = isExpiry ? expiryBadge(getDaysUntil(val)) : null;
                        return (
                          <td key={col.key} style={{ padding:"7px 6px", whiteSpace:"nowrap",
                            overflow:"hidden", textOverflow:"ellipsis" }}>
                            {badge ? (
                              <span>
                                <span style={{ marginRight:4 }}>{val}</span>
                                <span style={{ ...badge.style, borderRadius:10, padding:"1px 6px", fontSize:10, fontWeight:600 }}>{badge.text}</span>
                              </span>
                            ) : val}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* 페이지네이션 */}
          {totalPages > 1 && (
            <div style={{ display:"flex", alignItems:"center", justifyContent:"center", gap:4, padding:"10px 16px", borderTop:"1px solid #EDF2F7" }}>
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                style={{ padding:"4px 10px", fontSize:12, border:"1px solid #E2E8F0", borderRadius:6, background:"#fff", color:"#4A5568", cursor: page <= 1 ? "default" : "pointer", opacity: page <= 1 ? 0.35 : 1 }}
              >‹</button>
              {buildPageNums(page, totalPages).map((n, i) =>
                n === "…" ? (
                  <span key={`ellipsis-${i}`} style={{ padding:"0 4px", fontSize:12, color:"#A0AEC0" }}>…</span>
                ) : (
                  <button
                    key={n}
                    onClick={() => setPage(n)}
                    style={{
                      padding:"4px 9px", fontSize:12, borderRadius:6, cursor:"pointer",
                      border: n === page ? "1px solid #D4A843" : "1px solid #E2E8F0",
                      background: n === page ? "#FFF8EC" : "#fff",
                      color: n === page ? "#C27800" : "#4A5568",
                      fontWeight: n === page ? 700 : 400,
                    }}
                  >{n}</button>
                )
              )}
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                style={{ padding:"4px 10px", fontSize:12, border:"1px solid #E2E8F0", borderRadius:6, background:"#fff", color:"#4A5568", cursor: page >= totalPages ? "default" : "pointer", opacity: page >= totalPages ? 0.35 : 1 }}
              >›</button>
            </div>
          )}
        </div>
      )}

      {/* 우측 드로어 */}
      {selectedCustomer && (
        <CustomerDrawer
          customer={selectedCustomer} isNew={isNewMode}
          onClose={() => { setSelectedCustomer(null); setIsNewMode(false); setDocOverlayOpen(false); setQuickPoaOverlayOpen(false); }}
          onSave={handleSave}
          onDelete={!isNewMode ? (id) => deleteMut.mutate(id) : undefined}
          isSaving={updateMut.isPending || addMut.isPending}
          onOpenDocOverlay={!isNewMode ? () => { setQuickPoaOverlayOpen(false); setDocOverlayOpen(true); } : undefined}
          onOpenQuickPoaOverlay={!isNewMode ? () => { setDocOverlayOpen(false); setQuickPoaOverlayOpen(true); } : undefined}
        />
      )}

      {/* 문서자동작성 오버레이 — position:fixed, 사이드바·상단바 미침범 */}
      {docOverlayOpen && selectedCustomer && !isNewMode && (
        <div style={{
          position:"fixed",
          top:120,                           // 상단바(56px) + 고객 툴바(~64px) 아래
          bottom:0,
          left:"var(--hw-main-left, 0px)",   // 사이드바 오른쪽부터
          right:"min(480px, 100vw)",         // 고객카드 480px 제외
          zIndex:45,
          background:"#fff",
          display:"flex", flexDirection:"column",
          boxShadow:"0 4px 20px rgba(0,0,0,0.14)",
          overflow:"hidden",
        }}>
          {/* 헤더 — flex 고정 */}
          <div style={{
            display:"flex", alignItems:"center", justifyContent:"space-between",
            padding:"11px 18px", borderBottom:"1px solid #E2E8F0",
            flexShrink:0, background:"#FFF9E6",
          }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <FileText size={15} style={{ color:"#D4A843" }} />
              <span style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>문서 자동작성</span>
              <span style={{ fontSize:12, color:"#718096" }}>
                — {selectedCustomer["한글"] || [selectedCustomer["성"], selectedCustomer["명"]].filter(Boolean).join(" ") || "고객"}
              </span>
            </div>
            <button
              onClick={() => setDocOverlayOpen(false)}
              style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}
            >
              <X size={18} />
            </button>
          </div>
          {/* 컨텐츠 — flex:1로 남은 높이 전부 사용, 내부 스크롤 */}
          <div style={{ flex:"1 1 0", minHeight:0, overflowY:"auto", padding:"20px" }}>
            <Suspense>
              <QuickDocPanel
                initialCustomer={{
                  id:      selectedCustomer["고객ID"] || "",
                  name:    selectedCustomer["한글"] || "",
                  name_en: [selectedCustomer["성"], selectedCustomer["명"]].filter(Boolean).join(" ") || undefined,
                  label:   selectedCustomer["한글"] || selectedCustomer["고객ID"] || "",
                  reg_no:  [selectedCustomer["등록증"], selectedCustomer["번호"]].filter(Boolean).join("-"),
                }}
                embedded
                onClose={() => setDocOverlayOpen(false)}
              />
            </Suspense>
          </div>
        </div>
      )}

      {/* 원클릭 작성 오버레이 — position:fixed, 사이드바·상단바 미침범 */}
      {quickPoaOverlayOpen && selectedCustomer && !isNewMode && (
        <div style={{
          position:"fixed",
          top:120,
          bottom:0,
          left:"var(--hw-main-left, 0px)",
          right:"min(480px, 100vw)",
          zIndex:45,
          background:"#fff",
          display:"flex", flexDirection:"column",
          boxShadow:"0 4px 20px rgba(0,0,0,0.14)",
          overflow:"hidden",
        }}>
          {/* 헤더 */}
          <div style={{
            display:"flex", alignItems:"center", justifyContent:"space-between",
            padding:"11px 18px", borderBottom:"1px solid #E2E8F0",
            flexShrink:0, background:"#EBF8FF",
          }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <Zap size={15} style={{ color:"#2B6CB0" }} />
              <span style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>원클릭 작성</span>
              <span style={{ fontSize:12, color:"#718096" }}>
                — {selectedCustomer["한글"] || [selectedCustomer["성"], selectedCustomer["명"]].filter(Boolean).join(" ") || "고객"}
              </span>
            </div>
            <button
              onClick={() => setQuickPoaOverlayOpen(false)}
              style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}
            >
              <X size={18} />
            </button>
          </div>
          {/* 컨텐츠 — flex:1로 남은 높이 전부 사용, 내부 스크롤 */}
          <div style={{ flex:"1 1 0", minHeight:0, overflowY:"auto", padding:"16px 20px" }}>
            <QuickPoaPanel
              initialCustomer={{
                customer_id: selectedCustomer["고객ID"]  || undefined,
                kor_name:    selectedCustomer["한글"]    || "",
                surname:     selectedCustomer["성"]      || "",
                given:       selectedCustomer["명"]      || "",
                stay_status: selectedCustomer["V"]       || "",
                reg6:        selectedCustomer["등록증"]   || "",
                no7:         selectedCustomer["번호"]    || "",
                addr:        selectedCustomer["주소"]    || "",
                phone1:      selectedCustomer["연"]      || "010",
                phone2:      selectedCustomer["락"]      || "",
                phone3:      selectedCustomer["처"]      || "",
                passport:    selectedCustomer["여권"]    || "",
              }}
              embedded
              onClose={() => setQuickPoaOverlayOpen(false)}
            />
          </div>
        </div>
      )}

      {/* 신규 고객 등록 직후 서명 프롬프트 */}
      {signPrompt && !showSignModal && (
        <>
          <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.35)", zIndex:200 }}
            onClick={() => setSignPrompt(null)} />
          <div style={{
            position:"fixed", top:"50%", left:"50%",
            transform:"translate(-50%,-50%)", zIndex:201,
            width:"min(340px,92vw)", background:"#fff",
            borderRadius:14, boxShadow:"0 8px 32px rgba(0,0,0,0.16)",
            padding:"28px 24px",
          }}>
            <div style={{ fontSize:15, fontWeight:700, color:"#1A202C", marginBottom:10 }}>
              신규 고객 서명 등록
            </div>
            <div style={{ fontSize:13, color:"#4A5568", marginBottom:24, lineHeight:1.6 }}>
              <strong>{signPrompt.name}</strong> 고객의 서명을 등록하시겠습니까?
            </div>
            <div style={{ display:"flex", gap:10, justifyContent:"flex-end" }}>
              <button
                onClick={() => setSignPrompt(null)}
                style={{ padding:"9px 18px", borderRadius:8, border:"1px solid #E2E8F0", background:"#fff", color:"#718096", fontSize:13, cursor:"pointer", fontWeight:600 }}>
                나중에
              </button>
              <button
                onClick={() => setShowSignModal(true)}
                style={{ padding:"9px 18px", borderRadius:8, border:"none", background:"#F5A623", color:"#fff", fontSize:13, cursor:"pointer", fontWeight:700 }}>
                서명 등록하기
              </button>
            </div>
          </div>
        </>
      )}

      {/* 서명 모달 (프롬프트에서 "등록하기" 클릭 시) */}
      {showSignModal && signPrompt && (
        <SignatureModal
          type="customer"
          customerId={signPrompt.customerId}
          onSave={() => {
            toast.success("서명이 등록되었습니다");
            setShowSignModal(false);
            setSignPrompt(null);
          }}
          onClose={() => {
            setShowSignModal(false);
            setSignPrompt(null);
          }}
        />
      )}
    </div>
  );
}
