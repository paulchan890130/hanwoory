"use client";
// components/customers/CustomerDrawer.tsx
// 고객카드(고객 상세/편집 드로어) + 하위 모달(숙소제공자/신원보증인/완료업무) + 만기 D-Day helper.
// 고객관리 페이지(app/(main)/customers/page.tsx)에서 분리한 공통 컴포넌트.
// 고객관리 페이지와 홈 대시보드 양쪽에서 동일 컴포넌트를 재사용한다(중복 구현 금지).
import { useState, useEffect, Fragment, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  customersApi, accommodationApi, guarantorApi, quickDocApi,
  type AccommodationProvider, type GuarantorConnection,
  type CustomerSearchResult, type WorkSummary,
} from "@/lib/api";
import { Search, Trash2, X, Save, FolderOpen, ExternalLink, FileText, Home, Zap, Globe, Shield } from "lucide-react";
import SignatureModal from "@/components/SignatureModal";
import QuickDocPanel from "@/components/QuickDocPanel";
import QuickPoaPanel from "@/components/QuickPoaPanel";
import { useSubmit } from "@/lib/useSubmit";
import { SubmitButton } from "@/components/SubmitButton";
import VisaStatusSelect from "@/components/VisaStatusSelect";
import { visaToExtensionWorktype, type ExtensionWorktype } from "@/lib/visa";
import { deriveBirthDateFromArc } from "@/lib/birth";

function parseDateStr(s: string): Date | null {
  if (!s) return null;
  const clean = s.replace(/\./g, "-").slice(0, 10);
  const d = new Date(clean);
  return isNaN(d.getTime()) ? null : d;
}

// 날짜형 표시값을 'YYYY-MM-DD' 로 통일(프론트 방어선 — 정본은 백엔드).
// 'YYYY-MM-DD 00:00:00' / 'YYYY-MM-DDT..' / 'YYYY.MM.DD' / 'YYYYMMDD' 를 정리하되
// 판독 불가/빈값은 원문 그대로 둔다(임의 변환 금지).
function toDateOnly(v: string | undefined | null): string {
  const s = (v ?? "").trim();
  if (!s) return s;
  const m = s.match(/^(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:[ T].*)?$/);
  if (m) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  const m8 = s.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (m8) return `${m8[1]}-${m8[2]}-${m8[3]}`;
  return s;
}
const DATE_FORM_KEYS = ["발급일", "만기일", "발급", "만기"] as const;

export function getDaysUntil(dateStr: string): number | null {
  const d = parseDateStr(dateStr);
  if (!d) return null;
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.floor((d.getTime() - now.getTime()) / 86_400_000);
}

export function expiryBadge(days: number | null): { text: string; style: React.CSSProperties } | null {
  if (days === null) return null;
  if (days < 0) return { text: `만료`, style: { background: "#FED7D7", color: "#C53030" } };
  if (days <= 30) return { text: `D-${days}`, style: { background: "#FED7D7", color: "#C53030" } };
  if (days <= 120) return { text: `D-${days}`, style: { background: "#FEEBC8", color: "#9C4221" } };
  return null;
}

export function rowHighlight(c: Record<string, string>): React.CSSProperties {
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
export const TABLE_COLS: { key: string; label: string; w?: string }[] = [
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
export function buildPageNums(current: number, total: number): (number | "…")[] {
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

export function emptyCustomer(): Record<string, string> {
  const rec: Record<string, string> = { 고객ID: "" };
  ALL_FIELDS.forEach((f) => (rec[f] = ""));
  return rec;
}

// ── 고객 검색 최소 길이 가드 ──────────────────────────────────────────────────
// Korean: 2자, English: 2자, 숫자: 3자. 혼합 입력은 하나라도 통과하면 OK.
// Backend (`/api/quick-doc/customers/search`) 도 동일 floor 를 강제하므로
// 클라이언트 가드를 우회하더라도 결과가 노출되지 않는다.
const HANGUL_REGEX = /[가-힯]/g;

function classifyCustomerQuery(q: string): { korean: number; english: number; digits: number } {
  const t = q.trim();
  const korean = (t.match(HANGUL_REGEX) || []).length;
  const english = (t.match(/[A-Za-z]/g) || []).length;
  const digits = (t.match(/\d/g) || []).length;
  return { korean, english, digits };
}

function customerQueryFloorMessage(q: string): string | null {
  const t = q.trim();
  if (!t) return null;          // 빈 입력 — 안내 메시지 없이 그냥 검색 안 함
  const { korean, english, digits } = classifyCustomerQuery(t);
  if (korean >= 2 || english >= 2 || digits >= 3) return null;
  if (korean === 1) return "한글은 2글자 이상 입력하세요.";
  if (english === 1) return "영문은 2글자 이상 입력하세요.";
  if (digits > 0 && digits < 3) return "숫자는 3자리 이상 입력하세요.";
  return "한글 2자 · 영문 2자 · 숫자 3자 이상 입력하세요.";
}

// ── 숙소제공자 / 신원보증인 해소(resolution) helper ──────────────────────────
// Backend ``GET /api/customers/{id}/accommodation`` returns ``null`` when no
// relationship row exists at all. When a row *does* exist but the linked
// provider can no longer be resolved (e.g. the source customer was deleted,
// or the row was written with empty fields by an old migration) the API still
// returns an object — just one whose ``provider_name`` is empty. The
// previous UI treated *any* object as "connected" which yielded
// ``숙소: undefined`` badges + an empty modal "current" block + a still-shown
// disconnect button. Both modals + the customer card badge now ask
// ``resolveProviderName`` / ``resolveGuarantorName`` — the single source of
// truth for "is this relationship actually usable?".

function resolveProviderName(p: AccommodationProvider | null | undefined): string | null {
  if (!p) return null;
  const name = (p.provider_name || "").trim();
  const last = (p.provider_last_name || "").trim();
  const first = (p.provider_first_name || "").trim();
  if (name) return name;
  const eng = `${last} ${first}`.trim();
  return eng || null;
}

function resolveGuarantorName(g: GuarantorConnection | null | undefined): string | null {
  if (!g) return null;
  const name = (g.guarantor_name || "").trim();
  const last = (g.guarantor_last_name || "").trim();
  const first = (g.guarantor_first_name || "").trim();
  if (name) return name;
  const eng = `${last} ${first}`.trim();
  return eng || null;
}

// Relationship status surface — the card badge and the modal "current" block
// both ask this. ``broken`` means the row exists in DB but has no usable
// provider/guarantor name. UX wise we treat ``broken`` the SAME as
// ``none``: the user gets a clean connectable surface with no blocking
// warning. The actual underlying broken row is harmlessly upserted away
// the moment the user saves a new selection.
function providerStatus(p: AccommodationProvider | null | undefined):
  "none" | "connected" | "broken" {
  if (!p) return "none";
  return resolveProviderName(p) ? "connected" : "broken";
}

function guarantorStatus(g: GuarantorConnection | null | undefined):
  "none" | "connected" | "broken" {
  if (!g) return "none";
  return resolveGuarantorName(g) ? "connected" : "broken";
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
  // broken row 는 fresh 상태로 시작 (accommodation 모달과 동일 규칙).
  const hasResolved = !!resolveGuarantorName(current);
  const isDB = hasResolved && current?.guarantor_type === "customer_db";
  const [tab, setTab] = useState<"search" | "manual">(isDB ? "search" : "manual");
  const [searchQ, setSearchQ] = useState(isDB ? (current?.guarantor_name || "") : "");
  const [searchResults, setSearchResults] = useState<CustomerSearchResult[]>([]);
  const [selectedDB, setSelectedDB] = useState<CustomerSearchResult | null>(
    isDB && current
      ? { id: current.guarantor_customer_id, name: current.guarantor_name, label: current.guarantor_name, reg_no: current.guarantor_reg_front }
      : null
  );

  // manual 타입 필드용 (초기값은 정상 manual 타입일 때만 — broken 시 빈값)
  const m = (key: keyof GuarantorConnection) =>
    hasResolved && current?.guarantor_type === "manual" ? (current[key] as string || "") : "";
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
    width:"100%", height:30, padding:"0 10px",
    border:`1px solid ${BORDER}`,
    borderRadius:6, fontSize:12, boxSizing:"border-box",
    lineHeight:"28px",
  };

  // 검색 디바운스 — Korean 2자 / English 2자 / 숫자 3자 미만이면 호출 자체 차단.
  // floor 미달 시 안내 문구만 표시하고 결과 리스트는 빈 상태로 둔다. 백엔드도
  // 동일 floor 를 강제하므로 클라이언트 가드를 건너뛰더라도 결과가 노출되지 않음.
  const floorMessage = customerQueryFloorMessage(searchQ);
  useEffect(() => {
    if (tab !== "search") { setSearchResults([]); return; }
    if (floorMessage !== null || !searchQ.trim()) { setSearchResults([]); return; }
    const t = setTimeout(() => {
      quickDocApi.searchCustomers(searchQ).then(r => setSearchResults(r.data)).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [searchQ, tab, floorMessage]);

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
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `신원보증인 저장 실패: ${detail}` : "신원보증인 저장 실패");
    }
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
        zIndex:301, width:"min(440px, 96vw)",
        background:"#fff", borderRadius:14,
        boxShadow:"0 8px 40px rgba(0,0,0,0.18)",
        display:"flex", flexDirection:"column", maxHeight:"90vh",
      }}>
        {/* 헤더 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"14px 20px", borderBottom:`1px solid ${BORDER}`, background:"#F0FFF4", flexShrink:0 }}>
          <div>
            <div style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>신원보증인 설정</div>
            <div style={{ fontSize:11, color:"#718096" }}>대상: {customerName}</div>
          </div>
          <button onClick={onClose} style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}><X size={16} /></button>
        </div>

        <div style={{ overflowY:"auto", flex:1, padding:"16px 20px" }}>
          {/* 현재 설정 표시 — 보증인이 실제로 resolve 된 경우에만 노출.
              broken (관계 행만 있고 이름 해소 불가) 은 "연결 안 됨" 과 동일 UX 로
              취급 → 아래 탭(검색/직접 입력) 이 즉시 사용 가능. 작은 회색 안내만 표시. */}
          {current && resolveGuarantorName(current) ? (
            <div style={{
              marginBottom:12, padding:"9px 12px",
              background:"#F0FFF4", borderRadius:8, border:"1px solid #C6F6D5",
              display:"flex", alignItems:"center", justifyContent:"space-between",
            }}>
              <div>
                <div style={{ fontSize:12, fontWeight:700, color:"#276749" }}>
                  현재: {resolveGuarantorName(current)}
                </div>
                {current.guarantor_type === "customer_db" && (
                  <div style={{ fontSize:10, color:"#718096" }}>고객 DB 연결</div>
                )}
              </div>
              <button onClick={handleDelete} disabled={deleting}
                style={{ fontSize:11, padding:"4px 10px", borderRadius:5, border:"1px solid #FC8181", background:"#FFF5F5", color:"#C53030", cursor:"pointer", flexShrink:0 }}>
                {deleting ? "해제 중..." : "연결 해제"}
              </button>
            </div>
          ) : current ? (
            <div style={{
              marginBottom:12, padding:"7px 12px",
              background:"#F7FAFC", borderRadius:8, border:"1px solid #E2E8F0",
              fontSize:11, color:"#A0AEC0",
            }}>
              기존 연결 정보가 비어 있어 새로 연결할 수 있습니다.
            </div>
          ) : null}

          {/* 탭 — 두 모달 공통 모양 (높이 36px 일치) */}
          <div style={{
            display:"flex", gap:4, marginBottom:14,
            background:"#F7FAFC", borderRadius:8, padding:4,
            height:36, boxSizing:"border-box",
          }}>
            {(["search", "manual"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex:1, height:28, padding:"0",
                borderRadius:6, fontSize:12, fontWeight:600,
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
                  placeholder="한글 2자 · 영문 2자 · 숫자 3자 이상"
                  style={{ ...inp, paddingLeft:28 }} />
              </div>
              {floorMessage && (
                <div style={{
                  padding:"6px 10px", marginBottom:8,
                  background:"#FFFAF0", borderRadius:6,
                  border:"1px solid #F6E05E",
                  fontSize:11, color:"#6B5314",
                }}>
                  {floorMessage}
                </div>
              )}
              {searchResults.length > 0 && (
                <div style={{ border:`1px solid ${BORDER}`, borderRadius:8, maxHeight:200, overflowY:"auto", marginBottom:8 }}>
                  {searchResults.map(c => (
                    <button key={c.id} onClick={() => { setSelectedDB(c); setSearchQ(c.name); setSearchResults([]); }}
                      style={{ display:"block", width:"100%", textAlign:"left", padding:"8px 12px", border:"none", borderBottom:`1px solid ${BORDER}`, background: selectedDB?.id === c.id ? "#F0FFF4" : "#fff", cursor:"pointer", fontSize:12, color:"#2D3748" }}>
                      <div style={{ fontWeight:600 }}>
                        {c.name || "(이름없음)"}
                        {c.name_en && <span style={{ fontSize:10, color:"#718096", fontWeight:500, marginLeft:6 }}>({c.name_en})</span>}
                      </div>
                      {(c.birth || c.phone) && (
                        <div style={{ fontSize:10, color:"#A0AEC0", marginTop:2 }}>
                          {c.birth && <span>{c.birth}</span>}
                          {c.birth && c.phone && <span style={{ margin:"0 6px" }}>·</span>}
                          {c.phone && <span>{c.phone}</span>}
                        </div>
                      )}
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

          {/* 직접 입력 탭 — 2-column 그리드, 논리적 페어 순서:
                row 1: 한글 성명 (wide)
                row 2: 영문 성 / 영문 이름
                row 3: 국적 / 연락처
                row 4: 등록번호 앞 / 등록번호 뒤
                row 5: 주소 (wide)
                row 6: 관계 (wide) */}
          {tab === "manual" && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 }}>
              {([
                { label:"한글 성명*",  val:mName,      set:setMName,      wide:true  },
                { label:"영문 성",     val:mLastName,  set:setMLastName,  wide:false },
                { label:"영문 이름",   val:mFirstName, set:setMFirstName, wide:false },
                { label:"국적",        val:mNation,    set:setMNation,    wide:false },
                { label:"연락처",      val:mPhone,     set:setMPhone,     wide:false },
                { label:"등록번호 앞", val:mRegFront,  set:setMRegFront,  wide:false },
                { label:"등록번호 뒤", val:mRegBack,   set:setMRegBack,   wide:false },
                { label:"주소",        val:mAddress,   set:setMAddress,   wide:true  },
                { label:"관계",        val:mRelation,  set:setMRelation,  wide:true  },
              ] as { label:string; val:string; set:(v:string)=>void; wide:boolean }[]).map(({ label, val, set, wide }) => (
                <div key={label} style={wide ? { gridColumn:"1/-1" } : {}}>
                  <label style={{ display:"block", fontSize:11, color:"#4A5568", marginBottom:4, fontWeight:600, letterSpacing:0.1 }}>{label}</label>
                  <input value={val} onChange={e => set(e.target.value)} style={inp} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 저장 버튼 */}
        <div style={{ padding:"14px 20px", borderTop:`1px solid ${BORDER}`, flexShrink:0 }}>
          <button onClick={handleSave} disabled={saving}
            style={{ width:"100%", height:42, padding:"0", borderRadius:8, fontSize:13, fontWeight:700, background: saving ? "#E2E8F0" : "#276749", color:"#fff", border:"none", cursor: saving ? "default" : "pointer" }}>
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
  // useQuery 로 fetch → 일일결산이 완료업무를 만들/지울 때 ["customer",
  // "work-summary", ...] / ["tasks"] invalidate 가 prefix 매칭으로 같이
  // refetch. summary 가 보여주는 카운트와 모달 리스트가 동일한 backend
  // resolver 의 결과이므로 둘은 항상 일치한다.
  const { data: ctData, isLoading: loading } = useQuery({
    queryKey: ["customer", "completed-tasks", customerId, customerName],
    queryFn: () =>
      customersApi.completedTasks(customerId, customerName, true)
        .then(r => r.data as {
          tasks: Record<string, string>[];
          legacy_tasks: Record<string, string>[];
          has_name_duplicate?: boolean;
        }),
    enabled: !!customerId,
    staleTime: 0,
  });
  const tasks = ctData?.tasks ?? [];
  const legacyTasks = ctData?.legacy_tasks ?? [];
  const [catFilter, setCatFilter] = useState("전체");
  const [showLegacy, setShowLegacy] = useState(false);

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
  // 지불금액(일일결산 수입 연동): 값 없거나 0 이면 '—', 있으면 원화 포맷.
  const paidWon = (v: unknown): string => {
    const n = Number(String(v ?? "").replace(/[^0-9.-]/g, ""));
    return v && Number.isFinite(n) && n > 0 ? n.toLocaleString("ko-KR") + "원" : "—";
  };

  const TaskTable = ({ rows, isLegacy }: { rows: Record<string, string>[]; isLegacy?: boolean }) => (
    <div style={{ overflowX:"auto" }}>
      <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12 }}>
        <thead>
          <tr style={{ background:"#F7FAFC", borderBottom:`2px solid ${BORDER}` }}>
            {["접수일","구분","업무명","세부내용","완료일","지불","접수","처리","보관"].map(h => (
              <th key={h} style={{ padding:"6px 8px", textAlign:"left", fontWeight:600, fontSize:11, color:"#718096", whiteSpace:"nowrap" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={9} style={{ padding:"20px", textAlign:"center", color:"#A0AEC0", fontSize:12 }}>
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
              <td style={{ padding:"6px 8px", whiteSpace:"nowrap", textAlign:"right", fontWeight:600, color: paidWon(t.paid_amount) === "—" ? "#A0AEC0" : "#2D3748" }}>{paidWon(t.paid_amount)}</td>
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
              {tasks.length + legacyTasks.length === 0 ? "0건" :
                tasks.length > 0 && legacyTasks.length > 0
                  ? `고객ID 기준 ${tasks.length}건 + 이름 기준 ${legacyTasks.length}건 (총 ${tasks.length + legacyTasks.length}건)`
                  : tasks.length > 0
                    ? `고객ID 기준 ${tasks.length}건`
                    : `이름 기준 ${legacyTasks.length}건`}
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
  // broken row (관계 행은 있지만 이름 해소 불가) 는 fresh 상태로 시작.
  // 그렇지 않은 정상 연결은 기존 입력값을 그대로 미리 채워 사용자가 수정만 하면 됨.
  const hasResolved = !!resolveProviderName(current);
  const isDB = hasResolved && current?.provider_type === "customer_db";
  const [tab, setTab] = useState<"search" | "manual">(isDB ? "search" : "manual");

  // DB 검색 state
  const [searchQ, setSearchQ] = useState(isDB ? (current?.provider_name || "") : "");
  const [searchResults, setSearchResults] = useState<CustomerSearchResult[]>([]);
  const [selectedDB, setSelectedDB] = useState<CustomerSearchResult | null>(
    isDB && current
      ? { id: current.provider_customer_id, name: current.provider_name, label: current.provider_name, reg_no: current.provider_reg_front }
      : null
  );

  // 수동 입력 state (한글성명/영문성/영문명/국적/등록번호앞뒤/연락처) —
  // broken 행은 빈 값으로 시작하므로 m() helper 가 빈 문자열 반환.
  const m = (key: keyof AccommodationProvider) =>
    hasResolved && current?.provider_type === "manual" ? (current[key] as string || "") : "";
  const [mName,      setMName]      = useState(m("provider_name"));
  const [mLastName,  setMLastName]  = useState(m("provider_last_name"));
  const [mFirstName, setMFirstName] = useState(m("provider_first_name"));
  const [mNation,    setMNation]    = useState(m("provider_nation"));
  const [mRegFront,  setMRegFront]  = useState(m("provider_reg_front"));
  const [mRegBack,   setMRegBack]   = useState(m("provider_reg_back"));
  const [mPhone,     setMPhone]     = useState(m("provider_phone"));

  // 숙소 제공일자(제공년/제공월/제공일) — 검색/직접입력 공통. provide_start_date(YYYY-MM-DD)로 저장.
  // 표시는 앞 0 제거(제공월 "06" → "6"), 자동작성 시 HWPX/PDF 누름틀 제공년/제공월/제공일에 반영.
  const _pd = (current?.provide_start_date || "").split(/[-./]/);
  const _pdNorm = (v: string | undefined) => (v && /^\d+$/.test(v) ? String(Number(v)) : "");
  const [provYear,  setProvYear]  = useState(_pd[0] && /^\d+$/.test(_pd[0]) ? _pd[0] : "");
  const [provMonth, setProvMonth] = useState(_pdNorm(_pd[1]));
  const [provDay,   setProvDay]   = useState(_pdNorm(_pd[2]));

  // 세 칸이 모두 있을 때만 유효 ISO(YYYY-MM-DD) 로 합친다. 하나라도 비면 "" → 저장 시 제공일자 비움.
  const buildProvideStartDate = (): string => {
    const y = provYear.trim(), mo = provMonth.trim(), d = provDay.trim();
    if (y && mo && d) return `${y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}`;
    return "";
  };

  const [saving,   setSaving]   = useState(false);
  const [deleting, setDeleting] = useState(false);

  const BORDER = "#E2E8F0";
  const GOLD   = "#D4A843";
  const inp: React.CSSProperties = {
    width:"100%", height:30, padding:"0 10px",
    border:`1px solid ${BORDER}`,
    borderRadius:6, fontSize:12, boxSizing:"border-box",
    lineHeight:"28px",
  };

  // 검색 디바운스
  // 검색 디바운스 — Korean 2자 / English 2자 / 숫자 3자 미만이면 호출 자체 차단.
  // floor 미달 시 안내 문구만 표시하고 결과 리스트는 빈 상태로 둔다. 백엔드도
  // 동일 floor 를 강제하므로 클라이언트 가드를 건너뛰더라도 결과가 노출되지 않음.
  const floorMessage = customerQueryFloorMessage(searchQ);
  useEffect(() => {
    if (tab !== "search") { setSearchResults([]); return; }
    if (floorMessage !== null || !searchQ.trim()) { setSearchResults([]); return; }
    const t = setTimeout(() => {
      quickDocApi.searchCustomers(searchQ).then(r => setSearchResults(r.data)).catch(() => {});
    }, 300);
    return () => clearTimeout(t);
  }, [searchQ, tab, floorMessage]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const provideStart = buildProvideStartDate();   // 제공일자 — 검색/직접입력 공통
      let payload: Partial<AccommodationProvider>;
      if (tab === "search") {
        if (!selectedDB) { toast.error("고객을 선택하세요."); setSaving(false); return; }
        payload = {
          provider_type:         "customer_db",
          provider_customer_id:  selectedDB.id,
          provider_name:         selectedDB.name,
          provider_reg_front:    selectedDB.reg_no || "",
          provide_start_date:    provideStart,
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
          provide_start_date:   provideStart,
        };
      }
      const res = await accommodationApi.save(customerId, payload);
      toast.success("숙소제공자가 고정되었습니다.");
      onSaved(res.data.data);
      onClose();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail ? `숙소제공자 저장 실패: ${detail}` : "숙소제공자 저장 실패");
    }
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
        zIndex:301, width:"min(440px, 96vw)",
        background:"#fff", borderRadius:14,
        boxShadow:"0 8px 40px rgba(0,0,0,0.18)",
        display:"flex", flexDirection:"column",
        maxHeight:"90vh",
      }}>
        {/* 헤더 */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"14px 20px", borderBottom:`1px solid ${BORDER}`, background:"#F7FAFC", flexShrink:0 }}>
          <div>
            <div style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>숙소제공자 설정</div>
            <div style={{ fontSize:11, color:"#718096" }}>대상: {customerName}</div>
          </div>
          <button onClick={onClose} style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}><X size={16} /></button>
        </div>

        <div style={{ overflowY:"auto", flex:1, padding:"16px 20px" }}>
          {/* 현재 설정 표시 — 숙소제공자가 실제로 resolve 된 경우에만 노출.
              broken (관계 행만 있고 이름 해소 불가) 은 "연결 안 됨" 과 동일 UX 로
              취급 → 아래 탭(검색/직접 입력) 이 즉시 사용 가능.
              guarantor 모달과 동일한 구조를 유지해 시각 대칭. */}
          {current && resolveProviderName(current) ? (
            <div style={{
              marginBottom:12, padding:"9px 12px",
              background:"#EBF8FF", borderRadius:8, border:"1px solid #BEE3F8",
              display:"flex", alignItems:"center", justifyContent:"space-between",
            }}>
              <div>
                <div style={{ fontSize:12, fontWeight:700, color:"#2B6CB0" }}>
                  현재: {resolveProviderName(current)}
                </div>
                {current.provider_type === "customer_db" && (
                  <div style={{ fontSize:10, color:"#718096" }}>고객 DB 연결</div>
                )}
              </div>
              <button onClick={handleDelete} disabled={deleting}
                style={{ fontSize:11, padding:"4px 10px", borderRadius:5, border:"1px solid #FC8181", background:"#FFF5F5", color:"#C53030", cursor:"pointer", flexShrink:0 }}>
                {deleting ? "해제 중..." : "연결 해제"}
              </button>
            </div>
          ) : current ? (
            <div style={{
              marginBottom:12, padding:"7px 12px",
              background:"#F7FAFC", borderRadius:8, border:"1px solid #E2E8F0",
              fontSize:11, color:"#A0AEC0",
            }}>
              기존 연결 정보가 비어 있어 새로 연결할 수 있습니다.
            </div>
          ) : null}

          {/* 탭 — 두 모달 공통 모양 (높이 36px 일치) */}
          <div style={{
            display:"flex", gap:4, marginBottom:14,
            background:"#F7FAFC", borderRadius:8, padding:4,
            height:36, boxSizing:"border-box",
          }}>
            {(["search", "manual"] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex:1, height:28, padding:"0",
                borderRadius:6, fontSize:12, fontWeight:600,
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
                  placeholder="한글 2자 · 영문 2자 · 숫자 3자 이상"
                  style={{ ...inp, paddingLeft:28 }} />
              </div>
              {floorMessage && (
                <div style={{
                  padding:"6px 10px", marginBottom:8,
                  background:"#FFFAF0", borderRadius:6,
                  border:"1px solid #F6E05E",
                  fontSize:11, color:"#6B5314",
                }}>
                  {floorMessage}
                </div>
              )}
              {searchResults.length > 0 && (
                <div style={{ border:`1px solid ${BORDER}`, borderRadius:8, maxHeight:200, overflowY:"auto", marginBottom:8 }}>
                  {searchResults.map(c => (
                    <button key={c.id} onClick={() => { setSelectedDB(c); setSearchQ(c.name); setSearchResults([]); }}
                      style={{ display:"block", width:"100%", textAlign:"left", padding:"8px 12px", border:"none", borderBottom:`1px solid ${BORDER}`, background: selectedDB?.id === c.id ? "#FFF9E6" : "#fff", cursor:"pointer", fontSize:12, color:"#2D3748" }}>
                      <div style={{ fontWeight:600 }}>
                        {c.name || "(이름없음)"}
                        {c.name_en && <span style={{ fontSize:10, color:"#718096", fontWeight:500, marginLeft:6 }}>({c.name_en})</span>}
                      </div>
                      {(c.birth || c.phone) && (
                        <div style={{ fontSize:10, color:"#A0AEC0", marginTop:2 }}>
                          {c.birth && <span>{c.birth}</span>}
                          {c.birth && c.phone && <span style={{ margin:"0 6px" }}>·</span>}
                          {c.phone && <span>{c.phone}</span>}
                        </div>
                      )}
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

          {/* 수동 입력 탭 — 핵심 인적사항만. 논리적 페어로 2-column 그리드 정렬:
                row 1: 한글 성명 (wide)
                row 2: 영문 성 / 영문 이름
                row 3: 국적 / 연락처
                row 4: 등록번호 앞 / 등록번호 뒤 */}
          {tab === "manual" && (
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 }}>
              {([
                { label:"한글 성명*",  val:mName,      set:setMName,      wide:true  },
                { label:"영문 성",     val:mLastName,  set:setMLastName,  wide:false },
                { label:"영문 이름",   val:mFirstName, set:setMFirstName, wide:false },
                { label:"국적",        val:mNation,    set:setMNation,    wide:false },
                { label:"연락처",      val:mPhone,     set:setMPhone,     wide:false },
                { label:"등록번호 앞", val:mRegFront,  set:setMRegFront,  wide:false },
                { label:"등록번호 뒤", val:mRegBack,   set:setMRegBack,   wide:false },
              ] as { label:string; val:string; set:(v:string)=>void; wide:boolean }[]).map(({ label, val, set, wide }) => (
                <div key={label} style={wide ? { gridColumn:"1/-1" } : {}}>
                  <label style={{ display:"block", fontSize:11, color:"#4A5568", marginBottom:4, fontWeight:600, letterSpacing:0.1 }}>{label}</label>
                  <input value={val} onChange={e => set(e.target.value)} style={inp} />
                </div>
              ))}
            </div>
          )}

          {/* 숙소 제공일자 — 검색/직접입력 공통. 자동작성 시 제공년/제공월/제공일 누름틀에 반영.
              신청일/작성일과 다르며, 비워두면 문서에서 공란으로 처리(오늘 날짜 자동입력 안 함). */}
          <div style={{ marginTop:14, paddingTop:14, borderTop:`1px dashed ${BORDER}` }}>
            <label style={{ display:"block", fontSize:11, color:"#4A5568", marginBottom:6, fontWeight:600, letterSpacing:0.1 }}>
              숙소 제공일자 <span style={{ color:"#A0AEC0", fontWeight:500 }}>(선택 · 비우면 공란)</span>
            </label>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              {([
                { ph:"2026", val:provYear,  set:setProvYear,  max:4, suffix:"년", grow:1.4 },
                { ph:"6",    val:provMonth, set:setProvMonth, max:2, suffix:"월", grow:1 },
                { ph:"29",   val:provDay,   set:setProvDay,   max:2, suffix:"일", grow:1 },
              ] as { ph:string; val:string; set:(v:string)=>void; max:number; suffix:string; grow:number }[]).map(({ ph, val, set, max, suffix, grow }) => (
                <div key={suffix} style={{ display:"flex", alignItems:"center", gap:4, flex:grow }}>
                  <input
                    value={val}
                    inputMode="numeric"
                    maxLength={max}
                    placeholder={ph}
                    onChange={e => set(e.target.value.replace(/\D/g, "").slice(0, max))}
                    style={{ ...inp, textAlign:"center" }} />
                  <span style={{ fontSize:11, color:"#718096", flexShrink:0 }}>{suffix}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 저장 버튼 */}
        <div style={{ padding:"14px 20px", borderTop:`1px solid ${BORDER}`, flexShrink:0 }}>
          <button onClick={handleSave} disabled={saving}
            style={{ width:"100%", height:42, padding:"0", borderRadius:8, fontSize:13, fontWeight:700, background: saving ? "#E2E8F0" : GOLD, color:"#fff", border:"none", cursor: saving ? "default" : "pointer" }}>
            {saving ? "저장 중..." : "숙소제공자 고정"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── 우측 드로어 ────────────────────────────────────────────────────────────────
export function CustomerDrawer({
  customer, isNew, onClose, onSave, onDelete, isSaving,
}: {
  customer: Record<string, string> | null;
  isNew: boolean;
  onClose: () => void;
  onSave: (d: Record<string, string>) => void;
  onDelete?: (id: string) => void;
  isSaving: boolean;
}) {
  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);

  // ── 문서자동작성 / 원클릭 작성 오버레이 (컴포넌트 자체가 책임 → 어느 화면에서 열어도 동일) ──
  const [docOverlayOpen, setDocOverlayOpen] = useState(false);
  const [docPreset, setDocPreset] = useState<ExtensionWorktype | null>(null);
  const [quickPoaOverlayOpen, setQuickPoaOverlayOpen] = useState(false);

  // ── 서명 상태 ──
  const [hasSignature, setHasSignature] = useState<boolean | null>(null);
  const [signatureData, setSignatureData] = useState<string | null>(null);
  const [showSignatureFull, setShowSignatureFull] = useState(false);
  const [showSignModal, setShowSignModal] = useState(false);
  // 서명 삭제(2단계 확인: 모달 + 체크박스)
  const [showDeleteSign, setShowDeleteSign] = useState(false);
  const [deleteSignConfirm, setDeleteSignConfirm] = useState(false);
  const { submit: submitDeleteSign, isSubmitting: deletingSign } = useSubmit();

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
  // useQuery 로 관리 → 일일결산 mutation 이 ["customer","work-summary"] 키를
  // invalidate 하면 드로어가 열려 있어도 즉시 refetch 된다. (이전 라운드의
  // useEffect 구현은 invalidate 신호를 받지 않아 드로어를 닫았다 다시 열어야만
  // 갱신되는 문제가 있었다.)
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
      const seed: Record<string, string> = { ...customer };
      for (const k of DATE_FORM_KEYS) if (k in seed) seed[k] = toDateOnly(seed[k]);
      setForm(seed);
      setDirty(false);
      setShowSignatureFull(false);
      setShowTempSlots(false);
      setShowDeleteSign(false);
      setDeleteSignConfirm(false);
      setShowHikoreaPanel(false);
      setHikoreaExpiry("");
      setShowIdFindPanel(false);
      setDocOverlayOpen(false);
      setQuickPoaOverlayOpen(false);
      setDocPreset(null);
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

  // 업무 현황 로드 — useQuery 로 변경.
  // queryKey 에 customerId 와 customerName 을 모두 포함하면 (a) 다른 고객으로
  // 이동 시 캐시 분리, (b) 이름 기반 legacy 검색 결과 변화도 반영됨.
  // staleTime: 0 → 일일결산 add/edit/delete 후 invalidate 가 즉시 refetch 트리거.
  const { data: workSummary = null } = useQuery({
    queryKey: ["customer", "work-summary", customerId, customerName],
    queryFn: () =>
      customersApi.workSummary(customerId, customerName || undefined)
        .then(r => r.data as WorkSummary),
    enabled: !!customerId && !isNew,
    staleTime: 0,
  });

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
            const activeTotal = workSummary.active_total ?? 0;
            return (
              <div style={{ marginBottom:18 }}>
                <div style={{ fontSize:11, fontWeight:700, color:"#D4A843", marginBottom:8, textTransform:"uppercase", letterSpacing:"0.06em" }}>업무 현황</div>
                {/* 진행 중 — 일일결산이 추가/삭제될 때 즉시 변동 */}
                {activeTotal > 0 && (
                  <div style={{
                    display:"inline-flex", alignItems:"center", gap:6,
                    marginBottom:8, padding:"4px 10px", borderRadius:6,
                    background:"#FFF9E6", border:"1px solid #F6E05E",
                    color:"#6B5314", fontSize:11, fontWeight:700,
                  }}>
                    진행 중 <strong>{activeTotal}</strong>건
                  </div>
                )}
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
                  // 체류자격(V): 문서자동작성과 동일한 코드 체계 select + 오른쪽 빈칸에 "연장" 버튼
                  if (f.key === "V") {
                    return (
                      <Fragment key={f.key}>
                        <div style={{ minWidth:0, overflow:"hidden" }}>
                          <label style={{ display:"block", fontSize:11, color:"#718096", marginBottom:3 }}>{f.label}</label>
                          <VisaStatusSelect
                            className="hw-input"
                            style={{ width:"100%", boxSizing:"border-box" }}
                            value={form[f.key] ?? ""}
                            onChange={(v) => change(f.key, v)}
                          />
                        </div>
                        {!isNew && (
                          <div style={{ minWidth:0, display:"flex", alignItems:"flex-end" }}>
                            <button
                              type="button"
                              onClick={() => { setQuickPoaOverlayOpen(false); setDocPreset(visaToExtensionWorktype(form["V"] ?? "")); setDocOverlayOpen(true); }}
                              title="체류기간 연장 문서 작성으로 이동"
                              style={{
                                height:32, padding:"0 16px", borderRadius:6,
                                border:"1px solid #9AE6B4", background:"#F0FFF4",
                                color:"#276749", fontSize:12, fontWeight:700,
                                cursor:"pointer", whiteSpace:"nowrap",
                              }}
                            >
                              연장
                            </button>
                          </div>
                        )}
                      </Fragment>
                    );
                  }
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
                  <button
                    onClick={() => { setQuickPoaOverlayOpen(false); setDocPreset(null); setDocOverlayOpen(true); }}
                    style={{
                      display:"flex", alignItems:"center", gap:5,
                      fontSize:11, padding:"5px 12px", borderRadius:6,
                      border:"1px solid #D4A843", color:"#6B5314",
                      background:"#FFF9E6", cursor:"pointer", fontWeight:600,
                    }}
                  >
                    <FileText size={11} /> 문서자동작성
                  </button>
                  {(() => {
                    // broken 행은 사용자 입장에서 "연결 안 됨" 과 동일하게 취급한다.
                    // 빨간 경고 뱃지를 보여주는 대신 평범한 회색 "숙소제공자"
                    // 칩으로 노출 → 즉시 새로 연결 가능한 상태로 인식.
                    const pStatus = providerStatus(providerData);
                    const pName = resolveProviderName(providerData);
                    const isConnected = pStatus === "connected";
                    const labelText = providerLoading ? "숙소 확인 중..."
                      : isConnected ? `숙소: ${pName}`
                      : "숙소제공자";
                    return (
                      <button
                        onClick={() => setShowProviderModal(true)}
                        style={{
                          display:"flex", alignItems:"center", gap:5,
                          fontSize:11, padding:"5px 12px", borderRadius:6,
                          border: isConnected ? "1px solid #BEE3F8" : "1px solid #CBD5E0",
                          color: providerLoading ? "#A0AEC0" : isConnected ? "#2B6CB0" : "#4A5568",
                          background: isConnected ? "#EBF8FF" : "#F7FAFC",
                          cursor:"pointer", fontWeight:600,
                        }}
                      >
                        <Home size={11} />
                        {labelText}
                      </button>
                    );
                  })()}
                  {(() => {
                    // 신원보증인도 동일: broken 은 unlinked 와 동일 UX.
                    const gStatus = guarantorStatus(guarantorData);
                    const gName = resolveGuarantorName(guarantorData);
                    const isConnected = gStatus === "connected";
                    const labelText = guarantorLoading ? "보증인 확인 중..."
                      : isConnected ? `보증인: ${gName}`
                      : "신원보증인";
                    return (
                      <button
                        onClick={() => setShowGuarantorModal(true)}
                        style={{
                          display:"flex", alignItems:"center", gap:5,
                          fontSize:11, padding:"5px 12px", borderRadius:6,
                          border: isConnected ? "1px solid #C6F6D5" : "1px solid #CBD5E0",
                          color: guarantorLoading ? "#A0AEC0" : isConnected ? "#276749" : "#4A5568",
                          background: isConnected ? "#F0FFF4" : "#F7FAFC",
                          cursor:"pointer", fontWeight:600,
                        }}
                      >
                        <Shield size={11} />
                        {labelText}
                      </button>
                    );
                  })()}
                  <button
                    onClick={() => { setDocOverlayOpen(false); setQuickPoaOverlayOpen(true); }}
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
                  const reg7      = (form["번호"]   || "").trim();
                  // 세기는 등록번호 뒷자리 첫 숫자 기준(공통 helper) — 2000년대 출생자 정정.
                  const birthdate = deriveBirthDateFromArc(reg6, reg7);
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
                            체류만료일 조회
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
                  // 세기는 등록번호 뒷자리 첫 숫자 기준(공통 helper) — 2000년대 출생자 정정.
                  const birthdate = deriveBirthDateFromArc(reg6, reg7);
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
                  {/* 서명 삭제 — 적용된 고객서명이 있을 때만 (임시서명 1·2·3은 비접촉) */}
                  {hasSignature === true && (
                    <button
                      onClick={() => { setDeleteSignConfirm(false); setShowDeleteSign(true); }}
                      style={{
                        fontSize:11, padding:"5px 12px", borderRadius:6,
                        border:"1px solid #FEB2B2", color:"#C53030",
                        background:"#FFF5F5", cursor:"pointer", fontWeight:600,
                      }}
                    >
                      서명 삭제
                    </button>
                  )}
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

      {/* 서명 삭제 확인 모달 (2단계: 모달 + 체크박스) */}
      {showDeleteSign && (
        <div
          onClick={() => { if (!deletingSign) setShowDeleteSign(false); }}
          style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.4)", zIndex:500, display:"flex", alignItems:"center", justifyContent:"center" }}
        >
          <div onClick={(e) => e.stopPropagation()}
            style={{ width:"min(380px,92vw)", background:"#fff", borderRadius:12, boxShadow:"0 8px 32px rgba(0,0,0,0.18)", overflow:"hidden" }}>
            <div style={{ padding:"14px 18px", borderBottom:"1px solid #E2E8F0", fontSize:15, fontWeight:700, color:"#C53030" }}>서명 삭제</div>
            <div style={{ padding:18, display:"flex", flexDirection:"column", gap:14 }}>
              <div style={{ fontSize:13, color:"#2D3748", lineHeight:1.6 }}>
                <strong>{name}</strong> 고객의 저장된 서명을 삭제하시겠습니까?<br />
                이 작업은 되돌릴 수 없습니다.
              </div>
              <label style={{ display:"flex", alignItems:"center", gap:8, fontSize:12, color:"#4A5568", cursor:"pointer" }}>
                <input type="checkbox" checked={deleteSignConfirm} onChange={(e) => setDeleteSignConfirm(e.target.checked)} />
                서명 삭제를 확인했습니다
              </label>
              <div style={{ display:"flex", gap:8, justifyContent:"flex-end" }}>
                <button onClick={() => setShowDeleteSign(false)} disabled={deletingSign} className="btn-secondary text-xs">취소</button>
                <button
                  disabled={!deleteSignConfirm || deletingSign}
                  onClick={() => {
                    submitDeleteSign(
                      async () => {
                        const res = await fetch(`/api/signature/customer/${encodeURIComponent(id)}`, {
                          method:"DELETE",
                          headers:{ Authorization:`Bearer ${localStorage.getItem("access_token") || ""}` },
                        });
                        if (!res.ok) throw new Error();
                        setHasSignature(false);
                        setSignatureData(null);
                        setShowSignatureFull(false);
                        setShowDeleteSign(false);
                        setDeleteSignConfirm(false);
                      },
                      { successMessage:"서명이 삭제되었습니다.", errorMessage:"서명 삭제에 실패했습니다." }
                    );
                  }}
                  style={{
                    fontSize:12, padding:"6px 14px", borderRadius:6, border:"none",
                    background:(!deleteSignConfirm || deletingSign) ? "#FEB2B2" : "#E53E3E",
                    color:"#fff", fontWeight:700,
                    cursor:(!deleteSignConfirm || deletingSign) ? "default" : "pointer",
                    opacity:(!deleteSignConfirm || deletingSign) ? 0.7 : 1,
                  }}
                >
                  {deletingSign ? "삭제 중..." : "삭제"}
                </button>
              </div>
            </div>
          </div>
        </div>
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

      {/* 문서자동작성 오버레이 — position:fixed, 사이드바·상단바 미침범 (드로어가 자체 소유) */}
      {docOverlayOpen && customer && !isNew && (
        <div style={{
          position:"fixed",
          top:120,                           // 상단바(56px) + 툴바(~64px) 아래
          bottom:0,
          left:"var(--hw-main-left, 0px)",   // 사이드바 오른쪽부터
          right:"min(480px, 100vw)",         // 고객카드 480px 제외
          zIndex:45,
          background:"#fff",
          display:"flex", flexDirection:"column",
          boxShadow:"0 4px 20px rgba(0,0,0,0.14)",
          overflow:"hidden",
        }}>
          <div style={{
            display:"flex", alignItems:"center", justifyContent:"space-between",
            padding:"11px 18px", borderBottom:"1px solid #E2E8F0",
            flexShrink:0, background:"#FFF9E6",
          }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <FileText size={15} style={{ color:"#D4A843" }} />
              <span style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>문서 자동작성</span>
              <span style={{ fontSize:12, color:"#718096" }}>
                — {customer["한글"] || [customer["성"], customer["명"]].filter(Boolean).join(" ") || "고객"}
              </span>
            </div>
            <button
              onClick={() => setDocOverlayOpen(false)}
              style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}
            >
              <X size={18} />
            </button>
          </div>
          <div style={{ flex:"1 1 0", minHeight:0, overflowY:"auto", padding:"20px" }}>
            <Suspense>
              <QuickDocPanel
                initialCustomer={{
                  id:      customer["고객ID"] || "",
                  name:    customer["한글"] || "",
                  name_en: [customer["성"], customer["명"]].filter(Boolean).join(" ") || undefined,
                  label:   customer["한글"] || customer["고객ID"] || "",
                  reg_no:  [customer["등록증"], customer["번호"]].filter(Boolean).join("-"),
                }}
                presetWorktype={docPreset}
                embedded
                onClose={() => setDocOverlayOpen(false)}
              />
            </Suspense>
          </div>
        </div>
      )}

      {/* 원클릭 작성 오버레이 — position:fixed, 사이드바·상단바 미침범 (드로어가 자체 소유) */}
      {quickPoaOverlayOpen && customer && !isNew && (
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
          <div style={{
            display:"flex", alignItems:"center", justifyContent:"space-between",
            padding:"11px 18px", borderBottom:"1px solid #E2E8F0",
            flexShrink:0, background:"#EBF8FF",
          }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <Zap size={15} style={{ color:"#2B6CB0" }} />
              <span style={{ fontSize:14, fontWeight:700, color:"#1A202C" }}>원클릭 작성</span>
              <span style={{ fontSize:12, color:"#718096" }}>
                — {customer["한글"] || [customer["성"], customer["명"]].filter(Boolean).join(" ") || "고객"}
              </span>
            </div>
            <button
              onClick={() => setQuickPoaOverlayOpen(false)}
              style={{ padding:4, color:"#718096", background:"none", border:"none", cursor:"pointer" }}
            >
              <X size={18} />
            </button>
          </div>
          <div style={{ flex:"1 1 0", minHeight:0, overflowY:"auto", padding:"16px 20px" }}>
            <QuickPoaPanel
              initialCustomer={{
                customer_id: customer["고객ID"]  || undefined,
                kor_name:    customer["한글"]    || "",
                surname:     customer["성"]      || "",
                given:       customer["명"]      || "",
                stay_status: customer["V"]       || "",
                reg6:        customer["등록증"]   || "",
                no7:         customer["번호"]    || "",
                addr:        customer["주소"]    || "",
                phone1:      customer["연"]      || "010",
                phone2:      customer["락"]      || "",
                phone3:      customer["처"]      || "",
                passport:    customer["여권"]    || "",
              }}
              embedded
              onClose={() => setQuickPoaOverlayOpen(false)}
            />
          </div>
        </div>
      )}
    </>
  );
}
