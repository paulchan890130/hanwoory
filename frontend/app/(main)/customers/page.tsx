"use client";
import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { customersApi } from "@/lib/api";
import { Search, UserPlus, Trash2, X, Save, FolderOpen, ExternalLink } from "lucide-react";
import { normalizeDate } from "@/lib/utils";

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
  if (min <= 120) return { background: "#FFFBF0" };
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
      { key: "위임내역", label: "위임내역", wide: true },
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

// ── 우측 드로어 ────────────────────────────────────────────────────────────────
function CustomerDrawer({
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

  useEffect(() => {
    if (customer) { setForm({ ...customer }); setDirty(false); }
  }, [customer]);

  if (!customer) return null;

  const id = customer["고객ID"] || "";
  const name = form["한글"] || `${form["성"] ?? ""} ${form["명"] ?? ""}`.trim() || "신규 고객";
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
          <div style={{ display:"flex", gap:8 }}>
            {folderUrl && (
              <a href={folderUrl} target="_blank" rel="noopener noreferrer"
                style={{ display:"flex", alignItems:"center", gap:4, fontSize:12, color:"#3182CE", background:"#EBF8FF", border:"1px solid #BEE3F8", borderRadius:6, padding:"4px 10px" }}>
                <FolderOpen size={13} /> 폴더 <ExternalLink size={11} />
              </a>
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
          {DRAWER_GROUPS.map((grp) => (
            <div key={grp.title} style={{ marginBottom:18 }}>
              <div style={{ fontSize:11, fontWeight:700, color:"#F5A623", marginBottom:8, textTransform:"uppercase", letterSpacing:"0.06em" }}>{grp.title}</div>
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
            </div>
          ))}
        </div>

        {/* 푸터 */}
        <div style={{ padding:"12px 20px", borderTop:"1px solid #E2E8F0", display:"flex", justifyContent:"space-between", alignItems:"center", flexShrink:0 }}>
          <div>
            {!isNew && onDelete && (
              <button className="btn-danger flex items-center gap-1.5 text-xs"
                onClick={() => { if (confirm(`'${name}' 고객을 삭제하시겠습니까?`)) onDelete(id); }}>
                <Trash2 size={12} /> 삭제
              </button>
            )}
          </div>
          <div style={{ display:"flex", gap:8 }}>
            <button onClick={onClose} className="btn-secondary text-xs">취소</button>
            <button onClick={() => onSave(form)} disabled={(!dirty && !isNew) || isSaving}
              className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50">
              <Save size={12} /> {isNew ? "등록" : "저장"}
            </button>
          </div>
        </div>
      </div>
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

  // 400ms 디바운스 + 2자 미만 입력은 전체 목록 표시 (빈 쿼리와 동일)
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search.length < 2 ? "" : search);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);

  const { data: pageData, isLoading, error } = useQuery({
    queryKey: ["customers", debouncedSearch, page],
    queryFn: ({ signal }) =>
      customersApi.list(debouncedSearch || undefined, page, PAGE_SIZE, signal).then((r) => r.data as {
        items: Record<string, string>[];
        total: number;
        page: number;
        page_size: number;
        total_pages: number;
      }),
    staleTime: 30_000,
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
      staleTime: 30_000,
    });
  }, [pageData, page, debouncedSearch, qc]);

  useEffect(() => {
    if (searchParams.get("action") === "new") {
      setSelectedCustomer(emptyCustomer()); setIsNewMode(true);
      router.replace("/customers");
    }
  }, [searchParams, router]);

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Record<string, string> }) => customersApi.update(id, data),
    onSuccess: () => { toast.success("저장됨"); qc.invalidateQueries({ queryKey: ["customers"] }); setSelectedCustomer(null); },
    onError: () => toast.error("저장 실패"),
  });
  const addMut = useMutation({
    mutationFn: (data: Record<string, string>) => customersApi.add(data),
    onSuccess: () => { toast.success("신규 고객 등록됨"); qc.invalidateQueries({ queryKey: ["customers"] }); setSelectedCustomer(null); setIsNewMode(false); },
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
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
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
                    <tr key={id} onClick={() => { setSelectedCustomer(c); setIsNewMode(false); }}
                      style={{ ...rowHighlight(c), cursor:"pointer", borderBottom:"1px solid #EDF2F7",
                        ...(isSelected ? { background:"rgba(245,166,35,0.08)", outline:"2px solid rgba(245,166,35,0.3)" } : {}) }}>
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
                      border: n === page ? "1px solid #F5A623" : "1px solid #E2E8F0",
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
          onClose={() => { setSelectedCustomer(null); setIsNewMode(false); }}
          onSave={handleSave}
          onDelete={!isNewMode ? (id) => deleteMut.mutate(id) : undefined}
          isSaving={updateMut.isPending || addMut.isPending}
        />
      )}
    </div>
  );
}
