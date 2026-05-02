"use client";
import { useEffect, useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { adminApi, api } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { useRouter } from "next/navigation";
import {
  CheckCircle, XCircle, Shield, UserPlus, X, Save,
  FolderOpen, Loader2, ChevronRight, AlertTriangle, RefreshCw, Trash2,
  BookOpen, RotateCcw, CheckSquare, SkipForward, Edit3, FileText,
} from "lucide-react";

// ── 워크스페이스 단계별 결과 타입 ─────────────────────────────────────────────
interface WsProbe {
  accessible: boolean;
  can_copy: boolean | null;
  reason: string | null;
  metadata?: {
    id?: string;
    name?: string;
    mimeType?: string;
    driveId?: string;
    owners?: unknown[];
    parents?: string[];
  } | null;
}
interface WsStage {
  status: "created" | "reused" | "skipped" | "failed" | "blocked" | "pending" | "saved";
  id?: string;
  error?: string | null;
  api_reason?: string | null;
  probe?: WsProbe | null;
}
interface WsResult {
  ok: boolean;
  stages: {
    folder_create: WsStage;
    customer_copy: WsStage;
    work_copy: WsStage;
    accounts_update: WsStage;
  };
  folder_id: string;
  customer_sheet_key: string;
  work_sheet_key: string;
  is_active: boolean;
  drive_user?: string;
  error?: string;
}

function stageLabel(s: WsStage | undefined, label: string): string {
  if (!s) return `${label}: (unknown)`;
  const icons: Record<string, string> = {
    created: "✅", reused: "♻️", skipped: "⏭️",
    failed: "❌", blocked: "🚫", pending: "⏳", saved: "✅",
  };
  const icon = icons[s.status] ?? "❓";
  const id = s.id ? ` [${s.id.slice(0, 12)}…]` : "";
  // prefer structured api_reason over raw error string
  const errText = s.api_reason || s.error || "";
  const err = errText ? ` — ${errText.slice(0, 120)}` : "";
  // probe diagnostics (only shown on failure)
  let probe = "";
  if (s.probe) {
    if (!s.probe.accessible) {
      probe = ` | probe: NOT accessible, reason=${s.probe.reason ?? "(none)"}`;
    } else {
      probe = ` | probe: accessible, can_copy=${s.probe.can_copy}, file=${s.probe.metadata?.name ?? "?"}, driveId=${s.probe.metadata?.driveId ?? "MyDrive"}`;
      if (s.probe.reason) probe += `, reason=${s.probe.reason}`;
    }
  }
  return `${icon} ${label}: ${s.status}${id}${err}${probe}`;
}

function WsDetailPanel({ result, onClose }: { result: WsResult; onClose: () => void }) {
  return (
    <>
      <div className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.5)" }} onClick={onClose} />
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="hw-card w-full max-w-2xl"
          style={{ maxHeight: "85vh", overflowY: "auto" }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between mb-4">
            <span className="font-semibold text-sm" style={{ color: "#2D3748" }}>
              워크스페이스 진단 결과
            </span>
            <button onClick={onClose} className="p-1 rounded" style={{ color: "#718096" }}>
              <X size={14} />
            </button>
          </div>
          <div className="space-y-3">
            {(["folder_create", "customer_copy", "work_copy", "accounts_update"] as const).map((key) => {
              const s = result.stages?.[key];
              if (!s) return null;
              const failed = s.status === "failed";
              return (
                <div
                  key={key}
                  className="rounded-lg p-3 text-xs font-mono"
                  style={{ background: failed ? "#FFF5F5" : "#F7FAFC", border: `1px solid ${failed ? "#FC8181" : "#E2E8F0"}` }}
                >
                  <div className="font-semibold mb-1" style={{ color: failed ? "#C53030" : "#2D3748" }}>
                    {key} — {s.status}
                  </div>
                  {s.id && <div style={{ color: "#4A5568" }}>id: {s.id}</div>}
                  {s.api_reason && <div style={{ color: "#C53030" }}>api_reason: {s.api_reason}</div>}
                  {s.error && !s.api_reason && <div style={{ color: "#C53030" }}>error: {s.error}</div>}
                  {s.probe && (
                    <div className="mt-2 space-y-0.5" style={{ color: "#4A5568" }}>
                      <div>probe.accessible: <b>{String(s.probe.accessible)}</b></div>
                      <div>probe.can_copy: <b>{s.probe.can_copy === null ? "null" : String(s.probe.can_copy)}</b></div>
                      {s.probe.reason && <div style={{ color: "#C53030" }}>probe.reason: {s.probe.reason}</div>}
                      {s.probe.metadata && (
                        <>
                          <div>file.name: {s.probe.metadata.name ?? "(none)"}</div>
                          <div>file.mimeType: {s.probe.metadata.mimeType ?? "(none)"}</div>
                          <div>file.driveId: {s.probe.metadata.driveId ?? "(MyDrive)"}</div>
                          <div>file.owners: {JSON.stringify(s.probe.metadata.owners)}</div>
                          <div>file.parents: {JSON.stringify(s.probe.metadata.parents)}</div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-4">
            <div className="text-[11px] font-semibold mb-1" style={{ color: "#718096" }}>Raw JSON</div>
            <pre
              className="text-[10px] rounded p-2 overflow-x-auto"
              style={{ background: "#EDF2F7", color: "#2D3748", maxHeight: 240 }}
            >
              {JSON.stringify(result, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </>
  );
}

// ── 신규 계정 생성 모달 ──────────────────────────────────────────────────────
function CreateAccountModal({
  onClose,
  onCreated,
  onWsResult,
}: {
  onClose: () => void;
  onCreated: () => void;
  onWsResult?: (r: WsResult) => void;
}) {
  const [form, setForm] = useState({
    login_id: "",
    password: "",
    office_name: "",
    tenant_id: "",
    office_adr: "",
    biz_reg_no: "",
    agent_rrn: "",
    contact_name: "",
    contact_tel: "",
    customer_sheet_key: "",
    work_sheet_key: "",
    folder_id: "",
    sheet_key: "",
    is_admin: false,
  });
  const [creating, setCreating] = useState(false);
  const [wsCreating, setWsCreating] = useState(false);

  const F = (name: string, label: string, placeholder = "", mono = false) => (
    <div key={name}>
      <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>{label}</label>
      <input
        className={`hw-input w-full text-xs${mono ? " font-mono" : ""}`}
        value={(form as Record<string, string | boolean>)[name] as string}
        onChange={(e) => setForm((p) => ({ ...p, [name]: e.target.value }))}
        placeholder={placeholder}
      />
    </div>
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.login_id.trim() || !form.password.trim() || !form.office_name.trim()) {
      toast.error("ID, 비밀번호, 사무실명은 필수입니다.");
      return;
    }
    setCreating(true);
    try {
      await adminApi.createAccount(form);
      toast.success(`계정 '${form.login_id}' 생성됨`);
      onCreated();
      onClose();
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "계정 생성 실패";
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  };

  const handleCreateWorkspace = async () => {
    if (!form.login_id.trim() || !form.office_name.trim()) {
      toast.error("로그인 ID와 사무실명을 먼저 입력하세요.");
      return;
    }
    setWsCreating(true);
    try {
      const res = await adminApi.createWorkspace(form.login_id, form.office_name);
      const data = res.data as WsResult;
      setForm((prev) => ({
        ...prev,
        customer_sheet_key: data.customer_sheet_key || prev.customer_sheet_key,
        work_sheet_key: data.work_sheet_key || prev.work_sheet_key,
        folder_id: data.folder_id || prev.folder_id,
      }));
      const lines = [
        stageLabel(data.stages?.folder_create,   "폴더"),
        stageLabel(data.stages?.customer_copy,   "고객시트"),
        stageLabel(data.stages?.work_copy,        "업무시트"),
        stageLabel(data.stages?.accounts_update, "Accounts"),
        data.drive_user ? `🔑 Drive 계정: ${data.drive_user}` : "",
      ].filter(Boolean).join("\n");
      if (data.ok) toast.success(`워크스페이스 완료\n${lines}`);
      else {
        onWsResult?.(data);
        toast.warning("워크스페이스 부분 완료 — 진단 패널 확인");
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "워크스페이스 생성 실패";
      toast.error(msg);
    } finally {
      setWsCreating(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.4)" }} onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={(e) => e.stopPropagation()}>
        <form
          onSubmit={handleSubmit}
          className="hw-card w-full max-w-2xl"
          style={{ maxHeight: "90vh", overflowY: "auto" }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* 헤더 */}
          <div className="flex items-center justify-between mb-5">
            <div className="flex items-center gap-2">
              <UserPlus size={16} style={{ color: "var(--hw-gold)" }} />
              <div className="font-semibold text-sm" style={{ color: "#2D3748" }}>신규 테넌트 계정 생성</div>
            </div>
            <button type="button" onClick={onClose} className="p-1 rounded-lg" style={{ color: "#718096" }}>
              <X size={16} />
            </button>
          </div>

          {/* 섹션1: 필수 */}
          <div className="mb-4">
            <div className="text-[11px] font-semibold uppercase px-2 py-1 rounded mb-3" style={{ color: "#718096", background: "#F7FAFC" }}>
              필수 정보
            </div>
            <div className="grid grid-cols-2 gap-3">
              {F("login_id", "로그인 ID *", "예: office01")}
              <div>
                <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>비밀번호 *</label>
                <input
                  type="password"
                  className="hw-input w-full text-xs"
                  value={form.password}
                  onChange={(e) => setForm((p) => ({ ...p, password: e.target.value }))}
                  placeholder="초기 비밀번호"
                  required
                />
              </div>
              <div className="col-span-2">
                {F("office_name", "사무실명 *", "예: 한우리 행정사무소")}
              </div>
              {F("tenant_id", "테넌트 ID", "미입력 시 로그인ID와 동일")}
              {F("office_adr", "사무실 주소", "")}
            </div>
          </div>

          {/* 섹션2: 사업자/행정사 정보 */}
          <div className="mb-4">
            <div className="text-[11px] font-semibold uppercase px-2 py-1 rounded mb-3" style={{ color: "#718096", background: "#F7FAFC" }}>
              사업자 / 행정사 정보
            </div>
            <div className="grid grid-cols-2 gap-3">
              {F("biz_reg_no", "사업자등록번호", "000-00-00000")}
              {F("agent_rrn", "행정사 주민등록번호", "000000-0000000")}
              {F("contact_name", "담당자명", "")}
              {F("contact_tel", "연락처", "010-0000-0000")}
            </div>
          </div>

          {/* 섹션3: Google Sheets 연동 */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[11px] font-semibold uppercase px-2 py-1 rounded" style={{ color: "#718096", background: "#F7FAFC" }}>
                Google Sheets 연동
              </div>
              <button
                type="button"
                onClick={handleCreateWorkspace}
                disabled={wsCreating || !form.login_id.trim() || !form.office_name.trim()}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors disabled:opacity-50"
                style={{ borderColor: "var(--hw-gold)", color: "var(--hw-gold-text)", background: "var(--hw-gold-light)" }}
              >
                {wsCreating ? <><Loader2 size={11} className="animate-spin" /> 생성 중...</> : <><FolderOpen size={11} /> 워크스페이스 자동 생성</>}
              </button>
            </div>
            {(form.customer_sheet_key || form.folder_id) && (
              <div className="text-xs px-3 py-2 rounded-lg mb-3" style={{ background: "#C6F6D5", color: "#276749" }}>
                ✅ 워크스페이스 자동 생성됨
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">{F("customer_sheet_key", "고객 데이터 시트키", "스프레드시트 ID", true)}</div>
              <div className="col-span-2">{F("work_sheet_key", "업무정리 시트키", "업무정리 스프레드시트 ID", true)}</div>
              {F("folder_id", "Drive 폴더 ID", "Google Drive 폴더 ID", true)}
              {F("sheet_key", "마스터 시트키", "공용 시트 ID (일반적으로 비워둠)", true)}
            </div>
          </div>

          {/* 관리자 여부 */}
          <div className="flex items-center gap-2 mb-5">
            <input
              type="checkbox"
              id="is_admin_check"
              checked={form.is_admin}
              onChange={(e) => setForm((p) => ({ ...p, is_admin: e.target.checked }))}
              className="w-3.5 h-3.5"
            />
            <label htmlFor="is_admin_check" className="text-xs" style={{ color: "#4A5568" }}>
              관리자 권한 부여
            </label>
          </div>

          {/* 버튼 */}
          <div className="flex items-center justify-end gap-2">
            <button type="button" onClick={onClose} className="btn-secondary text-xs">취소</button>
            <button type="submit" disabled={creating} className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50">
              <Save size={12} />
              {creating ? "생성 중..." : "계정 생성"}
            </button>
          </div>
        </form>
      </div>
    </>
  );
}


// ── 계정 행 상세 편집 패널 ────────────────────────────────────────────────────
function AccountDetailPanel({
  acc,
  onUpdate,
  onClose,
}: {
  acc: Record<string, string>;
  onUpdate: (loginId: string, data: Record<string, unknown>) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({ ...acc });
  const [saving, setSaving] = useState(false);

  const F = (key: string, label: string, mono = false) => (
    <div key={key}>
      <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>{label}</label>
      <input
        className={`hw-input w-full text-xs${mono ? " font-mono" : ""}`}
        value={form[key] || ""}
        onChange={(e) => setForm((p) => ({ ...p, [key]: e.target.value }))}
      />
    </div>
  );

  const handleSave = async () => {
    setSaving(true);
    try {
      const {
        login_id, password_hash, is_admin, is_active, created_at,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        ...editable
      } = form;
      void login_id; void password_hash; void is_admin; void is_active; void created_at;
      onUpdate(acc.login_id, editable);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.35)" }} onClick={onClose} />
      <div
        className="hw-drawer open"
        style={{ zIndex: 51 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="hw-drawer-header">
          <span>✏️ 계정 상세 편집 — {acc.login_id}</span>
          <button onClick={onClose} style={{ color: "#718096" }}><X size={16} /></button>
        </div>
        <div className="hw-drawer-body space-y-3">
          <div className="grid grid-cols-2 gap-3">
            {F("office_name", "사무실명")}
            {F("tenant_id", "테넌트 ID", true)}
            <div className="col-span-2">{F("office_adr", "사무실 주소")}</div>
            {F("contact_name", "담당자명")}
            {F("contact_tel", "연락처")}
            {F("biz_reg_no", "사업자등록번호")}
            {F("agent_rrn", "행정사 주민등록번호")}
          </div>

          <div className="hw-section-divider mt-4">Google Sheets 연동</div>
          <div className="space-y-2">
            {F("customer_sheet_key", "고객 데이터 시트키", true)}
            {F("work_sheet_key", "업무정리 시트키", true)}
            {F("folder_id", "Drive 폴더 ID", true)}
            {F("sheet_key", "마스터 시트키", true)}
          </div>

          <div className="hw-section-divider mt-4">메타데이터</div>
          <div>
            <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>가입일</label>
            <div className="text-xs" style={{ color: "#A0AEC0" }}>{acc.created_at || "(없음)"}</div>
          </div>
        </div>
        <div className="hw-drawer-footer">
          <button onClick={onClose} className="btn-secondary text-xs">닫기</button>
          <button onClick={handleSave} disabled={saving} className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50">
            <Save size={12} /> {saving ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>
    </>
  );
}


// ── 계정 삭제 확인 모달 ───────────────────────────────────────────────────────
function DeleteConfirmModal({
  acc,
  onConfirm,
  onClose,
  isDeleting,
}: {
  acc: Record<string, string>;
  onConfirm: () => void;
  onClose: () => void;
  isDeleting: boolean;
}) {
  return (
    <>
      <div className="fixed inset-0 z-50" style={{ background: "rgba(0,0,0,0.5)" }} onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={(e) => e.stopPropagation()}>
        <div className="hw-card w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={18} style={{ color: "#E53E3E" }} />
            <span className="font-semibold text-sm" style={{ color: "#2D3748" }}>계정 삭제 확인</span>
          </div>
          <div className="mb-5 space-y-3">
            <div className="text-sm" style={{ color: "#2D3748" }}>
              <strong>{acc.office_name || acc.login_id}</strong> 계정을 삭제하시겠습니까?
            </div>
            <div className="text-xs" style={{ color: "#718096" }}>
              로그인 ID: <span className="font-mono font-semibold">{acc.login_id}</span>
            </div>
            <div className="text-xs p-3 rounded-lg leading-relaxed" style={{ background: "#FFF5F5", color: "#C53030", border: "1px solid #FEB2B2" }}>
              이 작업은 해당 계정의 로그인을 즉시 차단합니다.<br />
              고객 데이터와 Google Sheets는 보존됩니다.
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button onClick={onClose} disabled={isDeleting} className="btn-secondary text-xs">취소</button>
            <button
              onClick={onConfirm}
              disabled={isDeleting}
              className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg font-medium disabled:opacity-50"
              style={{ background: "#E53E3E", color: "#fff" }}
            >
              <Trash2 size={12} />
              {isDeleting ? "처리 중..." : "삭제 확인"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}


// ── 매뉴얼 업데이트 검토 탭 ──────────────────────────────────────────────────
interface RematchRow {
  row_id: string; detailed_code: string; action_type: string; title: string;
  manual: string; current_page_from: number; current_page_to: number;
  found_page: number; found_pages: number[];
  status: "PASS" | "PAGE_CHANGED" | "NOT_FOUND" | "SKIP";
  match_text: string; search_keyword: string; heading_snippet: string;
  auto_apply: boolean; reviewed: boolean; applied: boolean;
}

const STATUS_BADGE: Record<string, { label: string; bg: string; color: string }> = {
  PASS:         { label: "일치",     bg: "#F0FFF4", color: "#276749" },
  PAGE_CHANGED: { label: "페이지 변경", bg: "#FFFFF0", color: "#744210" },
  NOT_FOUND:    { label: "미발견",   bg: "#FFF5F5", color: "#C53030" },
  SKIP:         { label: "건너뜀",   bg: "#F7FAFC", color: "#A0AEC0" },
};

function ManualReviewTab() {
  const [filter, setFilter] = useState<"all" | "changed" | "review" | "done">("all");
  const [runningRematch, setRunningRematch] = useState(false);
  const [rows, setRows] = useState<RematchRow[]>([]);
  const [lastRun, setLastRun] = useState<string | null>(null);
  const [totalOverride, setTotalOverride] = useState(0);
  const [inlineEdit, setInlineEdit] = useState<{ rowId: string; pf: string; pt: string } | null>(null);
  const [pdfPreview, setPdfPreview] = useState<{
    manual: string;
    page: number;
    label: string;
  } | null>(null);

  const loadReview = useCallback(async () => {
    try {
      const res = await api.get("/api/manual/update-review");
      const d = res.data as { rows: RematchRow[]; last_run: string | null; total_override: number };
      setRows(d.rows ?? []);
      setLastRun(d.last_run ?? null);
      setTotalOverride(d.total_override ?? 0);
    } catch { /* 미존재 시 빈 상태 유지 */ }
  }, []);

  useEffect(() => { void loadReview(); }, [loadReview]);

  const handleRunRematch = async () => {
    setRunningRematch(true);
    try {
      await api.post("/api/manual/run-rematch");
      toast.success("재탐색 완료");
      await loadReview();
    } catch { toast.error("재탐색 실패"); }
    finally { setRunningRematch(false); }
  };

  const handleApply = async (row: RematchRow, pf: number, pt: number) => {
    try {
      await api.post(`/api/manual/update-review/${row.row_id}/apply`, { page_from: pf, page_to: pt });
      setRows(prev => prev.map(r => r.row_id === row.row_id ? { ...r, applied: true, reviewed: true, found_page: pf } : r));
      toast.success(`${row.row_id} 적용 완료 (p.${pf})`);
    } catch { toast.error("적용 실패"); }
  };

  const handleSkip = async (row_id: string) => {
    try {
      await api.post(`/api/manual/update-review/${row_id}/skip`);
      setRows(prev => prev.map(r => r.row_id === row_id ? { ...r, reviewed: true } : r));
    } catch { toast.error("건너뜀 실패"); }
  };

  const filtered = rows.filter(r => {
    if (filter === "all") return true;
    if (filter === "changed") return r.status === "PAGE_CHANGED" && !r.reviewed;
    if (filter === "review") return r.status === "NOT_FOUND" && !r.reviewed;
    if (filter === "done") return r.reviewed || r.applied;
    return true;
  });

  const counts = {
    changed: rows.filter(r => r.status === "PAGE_CHANGED" && !r.reviewed).length,
    review:  rows.filter(r => r.status === "NOT_FOUND" && !r.reviewed).length,
    done:    rows.filter(r => r.reviewed || r.applied).length,
  };

  return (
    <div className="space-y-4">
      {/* 상단 */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <span className="text-xs" style={{ color: "#718096" }}>
            마지막 실행: {lastRun ? new Date(lastRun).toLocaleString("ko-KR") : "없음"}
          </span>
          {totalOverride > 0 && (
            <span className="ml-3 text-xs" style={{ color: "#A0AEC0" }}>
              대상 {totalOverride}건
            </span>
          )}
        </div>
        <button onClick={handleRunRematch} disabled={runningRematch}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg font-medium disabled:opacity-50"
          style={{ background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0" }}>
          {runningRematch ? <Loader2 size={13} className="animate-spin" /> : <RotateCcw size={13} />}
          {runningRematch ? "탐색 중..." : "지금 재탐색"}
        </button>
      </div>

      {/* 필터 */}
      <div className="flex gap-2 flex-wrap">
        {([
          { key: "all",     label: "전체",      count: rows.length },
          { key: "changed", label: "페이지 변경", count: counts.changed },
          { key: "review",  label: "재확인 필요", count: counts.review },
          { key: "done",    label: "완료",       count: counts.done },
        ] as const).map(({ key, label, count }) => (
          <button key={key}
            onClick={() => setFilter(key)}
            className={`hw-tab ${filter === key ? "active" : ""}`}>
            {label} {count > 0 && <span className="ml-1 text-xs opacity-70">({count})</span>}
          </button>
        ))}
      </div>

      {/* 테이블 */}
      {filtered.length === 0 ? (
        <div className="hw-card text-sm text-center py-10" style={{ color: "#A0AEC0" }}>
          {rows.length === 0 ? "재탐색을 실행해 주세요." : "해당 항목 없음"}
        </div>
      ) : (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="overflow-x-auto">
            <table className="hw-table w-full text-xs" style={{ minWidth: 900 }}>
              <thead>
                <tr>
                  {["자격코드", "업무", "제목", "매뉴얼", "현재 페이지", "발견 페이지", "상태", "액션"].map(h => (
                    <th key={h} className="text-left whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map(row => {
                  const badge = row.applied
                    ? { label: "적용완료", bg: "#EBF8FF", color: "#2B6CB0" }
                    : row.reviewed
                    ? { label: "확인됨", bg: "#F7FAFC", color: "#A0AEC0" }
                    : STATUS_BADGE[row.status] ?? STATUS_BADGE.SKIP;
                  const canAct = !row.reviewed && !row.applied;

                  return (
                    <tr key={row.row_id}>
                      <td className="font-mono">{row.detailed_code || "—"}</td>
                      <td style={{ color: "#718096" }}>{row.action_type}</td>
                      <td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                        title={row.title}>{row.title}</td>
                      <td>{row.manual}</td>
                      <td className="font-mono text-center" style={{ whiteSpace: "nowrap" }}>
                        <span>{row.current_page_from}{row.current_page_to !== row.current_page_from ? `–${row.current_page_to}` : ""}</span>
                        <button
                          onClick={() => setPdfPreview({ manual: row.manual, page: row.current_page_from, label: "현재 페이지" })}
                          title="현재 페이지 PDF 보기"
                          style={{ marginLeft: 6, background: "none", border: "none", cursor: "pointer", color: "#718096", padding: "2px 4px", borderRadius: 4, verticalAlign: "middle" }}>
                          <FileText size={13} />
                        </button>
                      </td>
                      <td className="font-mono text-center" style={{ whiteSpace: "nowrap" }}>
                        {row.found_page ? (
                          <>
                            <span style={{ color: row.status === "PAGE_CHANGED" ? "#D97706" : "inherit" }}>{row.found_page}</span>
                            <button
                              onClick={() => setPdfPreview({ manual: row.manual, page: row.found_page, label: "발견 페이지" })}
                              title="발견 페이지 PDF 보기"
                              style={{ marginLeft: 6, background: "none", border: "none", cursor: "pointer", color: "#718096", padding: "2px 4px", borderRadius: 4, verticalAlign: "middle" }}>
                              <FileText size={13} />
                            </button>
                          </>
                        ) : <span style={{ color: "#CBD5E0" }}>—</span>}
                      </td>
                      <td>
                        <span className="px-2 py-0.5 rounded-full text-xs font-medium"
                          style={{ background: badge.bg, color: badge.color }}>
                          {badge.label}
                        </span>
                      </td>
                      <td>
                        {canAct && row.status === "PAGE_CHANGED" && (
                          <div className="flex gap-1.5 flex-wrap">
                            {/* 자동 적용 버튼 */}
                            <button onClick={() => handleApply(row, row.found_page, row.found_page)}
                              className="flex items-center gap-1 px-2 py-1 rounded font-medium"
                              style={{ background: "#F0FFF4", border: "1px solid #48BB78", color: "#276749", fontSize: 11 }}>
                              <CheckSquare size={11} /> 적용 (p.{row.found_page})
                            </button>
                            {/* 직접 입력 */}
                            {inlineEdit?.rowId === row.row_id ? (
                              <div className="flex gap-1 items-center">
                                <input value={inlineEdit.pf} onChange={e => setInlineEdit({ ...inlineEdit, pf: e.target.value })}
                                  className="hw-input w-12 text-xs" placeholder="from" />
                                <input value={inlineEdit.pt} onChange={e => setInlineEdit({ ...inlineEdit, pt: e.target.value })}
                                  className="hw-input w-12 text-xs" placeholder="to" />
                                <button onClick={() => { handleApply(row, Number(inlineEdit.pf), Number(inlineEdit.pt)); setInlineEdit(null); }}
                                  style={{ fontSize: 11, padding: "3px 7px", borderRadius: 5, background: "#4299E1", color: "#fff", border: "none", cursor: "pointer" }}>
                                  저장
                                </button>
                                <button onClick={() => setInlineEdit(null)}
                                  style={{ fontSize: 11, padding: "3px 6px", borderRadius: 5, background: "#fff", color: "#718096", border: "1px solid #CBD5E0", cursor: "pointer" }}>
                                  취소
                                </button>
                              </div>
                            ) : (
                              <button onClick={() => setInlineEdit({ rowId: row.row_id, pf: String(row.found_page), pt: String(row.found_page) })}
                                className="flex items-center gap-1 px-2 py-1 rounded font-medium"
                                style={{ background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0", fontSize: 11 }}>
                                <Edit3 size={11} /> 직접 입력
                              </button>
                            )}
                            <button onClick={() => handleSkip(row.row_id)}
                              className="flex items-center gap-1 px-2 py-1 rounded"
                              style={{ border: "1px solid #CBD5E0", color: "#718096", background: "#fff", fontSize: 11, cursor: "pointer" }}>
                              <SkipForward size={11} /> 건너뜀
                            </button>
                          </div>
                        )}
                        {canAct && row.status === "NOT_FOUND" && (
                          <div className="flex gap-1.5 flex-wrap">
                            {inlineEdit?.rowId === row.row_id ? (
                              <div className="flex gap-1 items-center">
                                <input value={inlineEdit.pf} onChange={e => setInlineEdit({ ...inlineEdit, pf: e.target.value })}
                                  className="hw-input w-12 text-xs" placeholder="from" />
                                <input value={inlineEdit.pt} onChange={e => setInlineEdit({ ...inlineEdit, pt: e.target.value })}
                                  className="hw-input w-12 text-xs" placeholder="to" />
                                <button onClick={() => { handleApply(row, Number(inlineEdit.pf), Number(inlineEdit.pt)); setInlineEdit(null); }}
                                  style={{ fontSize: 11, padding: "3px 7px", borderRadius: 5, background: "#4299E1", color: "#fff", border: "none", cursor: "pointer" }}>
                                  저장
                                </button>
                                <button onClick={() => setInlineEdit(null)}
                                  style={{ fontSize: 11, padding: "3px 6px", borderRadius: 5, background: "#fff", color: "#718096", border: "1px solid #CBD5E0", cursor: "pointer" }}>
                                  취소
                                </button>
                              </div>
                            ) : (
                              <button onClick={() => setInlineEdit({ rowId: row.row_id, pf: String(row.current_page_from), pt: String(row.current_page_to) })}
                                className="flex items-center gap-1 px-2 py-1 rounded font-medium"
                                style={{ background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0", fontSize: 11 }}>
                                <Edit3 size={11} /> 직접 입력
                              </button>
                            )}
                            <button onClick={() => handleSkip(row.row_id)}
                              className="flex items-center gap-1 px-2 py-1 rounded"
                              style={{ border: "1px solid #CBD5E0", color: "#718096", background: "#fff", fontSize: 11, cursor: "pointer" }}>
                              <SkipForward size={11} /> 건너뜀
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* PDF 미리보기 모달 */}
      {pdfPreview && (
        <div
          onClick={() => setPdfPreview(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div
            onClick={e => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 12, width: "min(80vw, 900px)", height: "85vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid #E2E8F0", flexShrink: 0 }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                {pdfPreview.manual} — {pdfPreview.label} (p.{pdfPreview.page})
              </span>
              <button onClick={() => setPdfPreview(null)}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "#718096", lineHeight: 1 }}>✕</button>
            </div>
            <iframe
              key={`${pdfPreview.manual}-${pdfPreview.page}`}
              src={`/api/guidelines/manual-pdf/${encodeURIComponent(pdfPreview.manual)}?token=${encodeURIComponent(typeof window !== "undefined" ? (localStorage.getItem("access_token") || "") : "")}#page=${pdfPreview.page}&navpanes=0&pagemode=none&toolbar=1&view=Fit`}
              style={{ flex: 1, border: "none", width: "100%" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}


// ── 메인 어드민 페이지 ────────────────────────────────────────────────────────
export default function AdminPage() {
  const router = useRouter();
  const user = getUser();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"accounts" | "manual-review">("accounts");
  const [showCreate, setShowCreate] = useState(false);
  const [wsLoadingId, setWsLoadingId] = useState<string | null>(null);
  const [detailAcc, setDetailAcc] = useState<Record<string, string> | null>(null);
  const [wsDetail, setWsDetail] = useState<WsResult | null>(null);
  const [confirmDeleteTarget, setConfirmDeleteTarget] = useState<Record<string, string> | null>(null);

  useEffect(() => {
    if (!user?.is_admin) router.replace("/dashboard");
  }, [user, router]);

  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ["admin", "accounts"],
    queryFn: () => adminApi.listAccounts().then((r) => r.data as Record<string, string>[]),
    enabled: !!user?.is_admin,
  });

  const updateMut = useMutation({
    mutationFn: ({ loginId, data }: { loginId: string; data: Record<string, unknown> }) =>
      adminApi.updateAccount(loginId, data),
    onSuccess: () => { toast.success("계정 업데이트됨"); qc.invalidateQueries({ queryKey: ["admin"] }); },
    onError: () => toast.error("업데이트 실패"),
  });

  const deleteMut = useMutation({
    mutationFn: (loginId: string) => adminApi.deleteAccount(loginId),
    onSuccess: (_, loginId) => {
      toast.success(`계정 '${loginId}' 삭제됨`);
      qc.invalidateQueries({ queryKey: ["admin"] });
      setConfirmDeleteTarget(null);
    },
    onError: () => toast.error("계정 삭제 실패"),
  });

  const toggle = (loginId: string, field: "is_active" | "is_admin", current: string) => {
    const newVal = !(current.toLowerCase() === "true" || current === "1");
    updateMut.mutate({ loginId, data: { [field]: newVal } });
  };

  const handleRowWorkspace = async (acc: Record<string, string>) => {
    setWsLoadingId(acc.login_id);
    try {
      const res = await adminApi.createWorkspace(acc.login_id, acc.office_name || acc.login_id);
      const data = res.data as WsResult;
      // Accounts 행은 백엔드에서 이미 업데이트됨. 프론트 캐시만 갱신.
      qc.invalidateQueries({ queryKey: ["admin", "accounts"] });

      const lines = [
        stageLabel(data.stages?.folder_create,   "폴더"),
        stageLabel(data.stages?.customer_copy,   "고객시트"),
        stageLabel(data.stages?.work_copy,        "업무시트"),
        stageLabel(data.stages?.accounts_update, "Accounts 저장"),
        data.drive_user ? `🔑 Drive: ${data.drive_user}` : "",
      ].filter(Boolean).join("\n");

      if (data.ok) toast.success(`${acc.login_id} 완료\n${lines}`);
      else {
        setWsDetail(data);
        toast.warning(`${acc.login_id} 부분 완료 — 진단 패널 확인`);
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "워크스페이스 생성 실패";
      toast.error(msg);
    } finally {
      setWsLoadingId(null);
    }
  };

  if (!user?.is_admin) return null;

  return (
    <div className="space-y-5">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield size={18} style={{ color: "var(--hw-gold)" }} />
          <h1 className="hw-page-title">관리자</h1>
        </div>
        {activeTab === "accounts" && (
          <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-1.5 text-xs">
            <UserPlus size={14} /> 신규 계정 생성
          </button>
        )}
      </div>

      {/* 탭 */}
      <div className="hw-tabs">
        <button
          className={`hw-tab ${activeTab === "accounts" ? "active" : ""}`}
          onClick={() => setActiveTab("accounts")}>
          계정관리
        </button>
        <button
          className={`hw-tab ${activeTab === "manual-review" ? "active" : ""}`}
          onClick={() => setActiveTab("manual-review")}>
          <BookOpen size={12} className="inline mr-1" />
          매뉴얼 업데이트 검토
        </button>
      </div>

      {/* 매뉴얼 검토 탭 */}
      {activeTab === "manual-review" && <ManualReviewTab />}

      {/* 계정 목록 */}
      {activeTab === "accounts" && (<>
      {isLoading ? (
        <div className="hw-card text-sm" style={{ color: "#A0AEC0" }}>불러오는 중...</div>
      ) : accounts.length === 0 ? (
        <div className="hw-card text-sm text-center py-10" style={{ color: "#A0AEC0" }}>등록된 계정이 없습니다.</div>
      ) : (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="overflow-x-auto">
            <table className="hw-table w-full" style={{ minWidth: 1400 }}>
              <thead>
                <tr>
                  {[
                    "ID", "테넌트ID", "사무실명", "주소", "담당자", "연락처",
                    "사업자번호", "행정사RRN", "가입일",
                    "활성", "관리자",
                    "고객시트키", "업무시트키", "폴더", "마스터시트",
                    "워크스페이스", "편집", "삭제",
                  ].map((h) => (
                    <th key={h} className="text-left whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {accounts.map((acc) => {
                  const isActive = acc.is_active?.toLowerCase() === "true" || acc.is_active === "1";
                  const isAdm = acc.is_admin?.toLowerCase() === "true" || acc.is_admin === "1";

                  const InlineEdit = ({
                    field, width = "w-28",
                  }: {
                    field: string; width?: string;
                  }) => (
                    <input
                      className={`hw-input text-xs font-mono ${width}`}
                      defaultValue={(acc as Record<string, string>)[field] || ""}
                      onBlur={(e) => {
                        if (e.target.value !== (acc as Record<string, string>)[field])
                          updateMut.mutate({ loginId: acc.login_id, data: { [field]: e.target.value } });
                      }}
                    />
                  );

                  return (
                    <tr key={acc.login_id}>
                      <td className="font-mono text-xs font-semibold">{acc.login_id}</td>
                      <td className="text-xs" style={{ color: "#718096" }}>{acc.tenant_id || acc.login_id}</td>
                      <td className="text-xs font-medium">{acc.office_name}</td>
                      <td className="text-xs max-w-[140px] truncate" style={{ color: "#718096" }} title={acc.office_adr}>{acc.office_adr}</td>
                      <td className="text-xs" style={{ color: "#718096" }}>{acc.contact_name}</td>
                      <td className="text-xs" style={{ color: "#718096" }}>{acc.contact_tel}</td>
                      <td className="text-xs font-mono" style={{ color: "#718096" }}>{acc.biz_reg_no}</td>
                      <td className="text-xs font-mono" style={{ color: "#718096" }}>
                        {acc.agent_rrn
                          ? String(acc.agent_rrn).replace(/^(\d{6})-?(\d{7})$/, "$1-*******")
                          : ""}
                      </td>
                      <td className="text-xs" style={{ color: "#A0AEC0" }}>{acc.created_at}</td>
                      <td>
                        <button
                          onClick={() => {
                            const newVal = !(acc.is_active?.toLowerCase() === "true" || acc.is_active === "1");
                            const hasWorkspace = !!(acc.folder_id && acc.customer_sheet_key && acc.work_sheet_key);
                            // 비활성 계정을 활성화할 때 워크스페이스가 없으면 자동 생성 (생성 완료 시 is_active=TRUE 자동 설정됨)
                            if (newVal && !hasWorkspace) {
                              handleRowWorkspace(acc);
                            } else {
                              toggle(acc.login_id, "is_active", acc.is_active || "");
                            }
                          }}
                          className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isActive ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}
                        >
                          {isActive ? <CheckCircle size={11} /> : <XCircle size={11} />}
                          {isActive ? "활성" : "비활성"}
                        </button>
                      </td>
                      <td>
                        <button
                          onClick={() => toggle(acc.login_id, "is_admin", acc.is_admin || "")}
                          className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isAdm ? "bg-orange-100 text-orange-700" : "bg-gray-100 text-gray-500"}`}
                        >
                          <Shield size={11} />
                          {isAdm ? "관리자" : "일반"}
                        </button>
                      </td>
                      <td><InlineEdit field="customer_sheet_key" width="w-40" /></td>
                      <td><InlineEdit field="work_sheet_key" width="w-40" /></td>
                      <td><InlineEdit field="folder_id" width="w-32" /></td>
                      <td><InlineEdit field="sheet_key" width="w-32" /></td>
                      <td>
                        {(() => {
                          const hasFolder = !!acc.folder_id;
                          const hasCustomer = !!acc.customer_sheet_key;
                          const hasWork = !!acc.work_sheet_key;
                          const allReady = hasFolder && hasCustomer && hasWork;
                          const partial = hasFolder && (!hasCustomer || !hasWork);
                          const isLoading = wsLoadingId === acc.login_id;

                          if (allReady) {
                            return (
                              <span
                                className="text-xs px-2 py-1 rounded-full"
                                style={{ background: "#C6F6D5", color: "#276749" }}
                                title={`folder: ${acc.folder_id}\ncustomer: ${acc.customer_sheet_key}\nwork: ${acc.work_sheet_key}`}
                              >
                                ✅ 완료
                              </span>
                            );
                          }
                          return (
                            <div className="flex flex-col gap-1">
                              {partial && (
                                <span
                                  className="text-xs px-2 py-0.5 rounded-full"
                                  style={{ background: "#FEFCBF", color: "#744210" }}
                                  title={`folder: ${acc.folder_id || "(없음)"}\ncustomer: ${acc.customer_sheet_key || "(없음)"}\nwork: ${acc.work_sheet_key || "(없음)"}`}
                                >
                                  <AlertTriangle size={9} style={{ display: "inline", marginRight: 2 }} />
                                  부분 생성
                                </span>
                              )}
                              <button
                                onClick={() => handleRowWorkspace(acc)}
                                disabled={isLoading}
                                className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-50"
                                style={{ borderColor: "var(--hw-gold)", color: "var(--hw-gold-text)", background: "var(--hw-gold-light)" }}
                              >
                                {isLoading
                                  ? <><Loader2 size={10} className="animate-spin" /> 생성 중</>
                                  : partial
                                    ? <><RefreshCw size={10} /> 재시도</>
                                    : <><FolderOpen size={10} /> 자동 생성</>}
                              </button>
                            </div>
                          );
                        })()}
                      </td>
                      <td>
                        <button
                          onClick={() => setDetailAcc(acc)}
                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors"
                          style={{ borderColor: "var(--hw-border)", color: "#718096" }}
                        >
                          <ChevronRight size={11} /> 편집
                        </button>
                      </td>
                      <td>
                        {!isActive ? (
                          <span className="text-xs px-2 py-1 rounded-lg" style={{ color: "#A0AEC0", background: "#F7FAFC", border: "1px solid #E2E8F0" }}>
                            삭제됨
                          </span>
                        ) : (
                          <button
                            onClick={() => setConfirmDeleteTarget(acc)}
                            disabled={acc.login_id === user?.login_id}
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                            style={{ borderColor: "#FEB2B2", color: "#C53030", background: "#FFF5F5" }}
                            title={acc.login_id === user?.login_id ? "자신의 계정은 삭제할 수 없습니다" : "계정 삭제"}
                          >
                            <Trash2 size={11} /> 삭제
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-2 border-t text-xs" style={{ borderColor: "#E2E8F0", color: "#A0AEC0" }}>
            총 {accounts.length}개 계정
          </div>
        </div>
      )}
      </>)}
      {/* end accounts tab */}

      {/* 신규 계정 생성 모달 */}
      {showCreate && (
        <CreateAccountModal
          onClose={() => setShowCreate(false)}
          onCreated={() => qc.invalidateQueries({ queryKey: ["admin"] })}
          onWsResult={(r) => setWsDetail(r)}
        />
      )}

      {/* 상세 편집 드로어 */}
      {detailAcc && (
        <AccountDetailPanel
          acc={detailAcc}
          onUpdate={(loginId, data) => updateMut.mutate({ loginId, data })}
          onClose={() => setDetailAcc(null)}
        />
      )}

      {/* 워크스페이스 진단 패널 */}
      {wsDetail && (
        <WsDetailPanel result={wsDetail} onClose={() => setWsDetail(null)} />
      )}

      {/* 계정 삭제 확인 모달 */}
      {confirmDeleteTarget && (
        <DeleteConfirmModal
          acc={confirmDeleteTarget}
          onConfirm={() => deleteMut.mutate(confirmDeleteTarget.login_id)}
          onClose={() => setConfirmDeleteTarget(null)}
          isDeleting={deleteMut.isPending}
        />
      )}
    </div>
  );
}
