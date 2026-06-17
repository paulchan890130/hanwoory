"use client";
import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { customersApi } from "@/lib/api";
import { Search, UserPlus, Loader2 } from "lucide-react";
import { normalizeDate } from "@/lib/utils";
import SignatureModal from "@/components/SignatureModal";
// 고객카드 + 만기/페이지 helper — 공통 컴포넌트에서 import(고객관리·대시보드 공용)
import {
  CustomerDrawer, TABLE_COLS, rowHighlight, buildPageNums, emptyCustomer, getDaysUntil, expiryBadge,
} from "@/components/customers/CustomerDrawer";


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
    // OCR 스캔 등 다른 창/탭에서 고객을 추가한 뒤 이 창으로 돌아오면 즉시 재조회.
    // (같은 창 내 등록은 scan 페이지의 invalidateQueries(["customers"])가 처리)
    refetchOnWindowFocus: true,
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

  // 행 클릭 → 상세 열기. 목록 레코드는 외국인등록번호 뒷자리(번호)가 마스킹되어 있으므로,
  // 단건 reveal 조회(GET /api/customers/{id})로 평문 번호를 받아 드로어에 표시한다.
  // (대시보드 CustomerCardModal 과 동일 동작 → 고객카드 동일성 유지.)
  const openCustomerDetail = (c: Record<string, string>) => {
    setIsNewMode(false);
    setSelectedCustomer(c); // 즉시 열기(마스킹 상태) → 조회 완료 시 평문으로 교체
    const id = c["고객ID"] || "";
    if (!id) return;
    customersApi.get(id)
      .then((res) => setSelectedCustomer(res.data))
      .catch(() => { /* 조회 실패 시 목록 레코드(마스킹) 유지 */ });
  };

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
            placeholder="이름·전화·국적·여권, 등록번호 뒤4자리/7자리"
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
                    <tr key={id} onClick={() => { openCustomerDetail(c); }}
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

      {/* 우측 드로어 — 문서작성/원클릭/연장 오버레이는 CustomerDrawer 가 자체 소유(단일 진실) */}
      {selectedCustomer && (
        <CustomerDrawer
          customer={selectedCustomer} isNew={isNewMode}
          onClose={() => { setSelectedCustomer(null); setIsNewMode(false); }}
          onSave={handleSave}
          onDelete={!isNewMode ? (id) => deleteMut.mutate(id) : undefined}
          isSaving={updateMut.isPending || addMut.isPending}
        />
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
