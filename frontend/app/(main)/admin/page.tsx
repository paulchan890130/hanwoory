"use client";
import { useEffect, useState, useCallback, Fragment } from "react";
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
import { useSubmit } from "@/lib/useSubmit";
import { SubmitButton } from "@/components/SubmitButton";
import DocConfigTab from "@/components/admin/DocConfigTab";

// ── PG 저장소 상태 helper ────────────────────────────────────────────────────
// Backend returns storage_mode === "pg+local-mock" when FEATURE_LOCAL_DRIVE_MOCK
// is on; in that case we swap the four Sheet-key columns for two status chips
// (PostgreSQL 저장소 / 파일 저장소).
function isPgMode(rows: Record<string, string>[]): boolean {
  return rows.some((r) => String(r.storage_mode || "").startsWith("pg+"));
}

function PgStorageChip({ acc }: { acc: Record<string, unknown> }) {
  const status = String(acc.pg_storage_status || "");
  const label = String(acc.pg_storage_label || "");
  if (status === "ready") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-full"
        style={{ background: "#C6F6D5", color: "#276749" }}
        title={label}
      >
        ✓ PG 데이터 있음
      </span>
    );
  }
  return (
    <span
      className="text-xs px-2 py-1 rounded-full"
      style={{ background: "#F7FAFC", color: "#A0AEC0", border: "1px solid #E2E8F0" }}
      title={label}
    >
      비어있음
    </span>
  );
}

function FileStorageChip({ acc }: { acc: Record<string, unknown> }) {
  const status = String(acc.file_storage_status || "");
  const label = String(acc.file_storage_label || "");
  if (status === "local-mock") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-full"
        style={{ background: "#FAF5FF", color: "#553C9A", border: "1px solid #D6BCFA" }}
        title="로컬 모의 저장소 (Google Drive 미호출)"
      >
        🧪 {label}
      </span>
    );
  }
  if (status === "google-drive") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-full"
        style={{ background: "#EBF8FF", color: "#2B6CB0" }}
        title="Google Drive 키 (운영 Sheets 참조 — 로컬 PG 모드에서는 더 이상 호출되지 않음)"
      >
        ☁️ {label}
      </span>
    );
  }
  if (status === "partial" || status === "mixed") {
    return (
      <span
        className="text-xs px-2 py-1 rounded-full"
        style={{ background: "#FFF9E6", color: "#6B5314" }}
        title={label}
      >
        ⚠ {label}
      </span>
    );
  }
  return (
    <span
      className="text-xs px-2 py-1 rounded-full"
      style={{ background: "#F7FAFC", color: "#A0AEC0", border: "1px solid #E2E8F0" }}
      title="아직 워크스페이스 생성 안 됨"
    >
      없음
    </span>
  );
}

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
  pgMode = false,
  isLocalMock = false,
}: {
  onClose: () => void;
  onCreated: () => void;
  onWsResult?: (r: WsResult) => void;
  pgMode?: boolean;
  isLocalMock?: boolean;
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
  const { submit: submitCreate, isSubmitting: creating } = useSubmit();
  const { submit: submitWs, isSubmitting: wsCreating } = useSubmit();

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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.login_id.trim() || !form.password.trim() || !form.office_name.trim()) {
      toast.error("ID, 비밀번호, 사무실명은 필수입니다.");
      return;
    }
    submitCreate(
      async () => {
        await adminApi.createAccount(form);
        onCreated();
        onClose();
      },
      {
        successMessage: `계정 '${form.login_id}' 생성됨`,
        errorMessage: "계정 생성 실패",
      }
    );
  };

  const handleCreateWorkspace = () => {
    if (!form.login_id.trim() || !form.office_name.trim()) {
      toast.error("로그인 ID와 사무실명을 먼저 입력하세요.");
      return;
    }
    submitWs(
      async () => {
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
      },
      {
        successMessage: "",
        errorMessage: "워크스페이스 생성 실패",
      }
    );
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
              <div>
                <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>행정사 주민등록번호</label>
                <div className="text-[11px] px-2 py-2 rounded" style={{ color: "#A0AEC0", background: "#F7FAFC" }}>
                  계정 생성 후 ‘수정’에서 암호화 등록
                </div>
              </div>
              {F("contact_name", "담당자명", "")}
              {F("contact_tel", "연락처", "010-0000-0000")}
            </div>
          </div>

          {/* 섹션3: 워크스페이스 (Google Sheets 또는 로컬 모의) */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[11px] font-semibold uppercase px-2 py-1 rounded" style={{ color: "#718096", background: "#F7FAFC" }}>
                {pgMode
                  ? (isLocalMock ? "워크스페이스 (로컬 모의)" : "워크스페이스 (PostgreSQL)")
                  : "Google Sheets 연동"}
              </div>
              <SubmitButton
                type="button"
                isSubmitting={wsCreating}
                disabled={!form.login_id.trim() || !form.office_name.trim()}
                onClick={handleCreateWorkspace}
                loadingText="생성 중..."
                className="text-xs"
                style={{ padding: "6px 12px", fontSize: 11, borderRadius: 8, border: "1px solid var(--hw-gold)", color: "var(--hw-gold-text)", background: "var(--hw-gold-light)" }}
              >
                <><FolderOpen size={11} /> {isLocalMock ? "로컬 모의 생성" : "워크스페이스 자동 생성"}</>
              </SubmitButton>
            </div>
            {(form.customer_sheet_key || form.folder_id) && (
              <div className="text-xs px-3 py-2 rounded-lg mb-3" style={{ background: "#C6F6D5", color: "#276749" }}>
                ✅ 워크스페이스 자동 생성됨
                {isLocalMock && <span className="ml-2 font-mono">(local-* sentinel ID)</span>}
              </div>
            )}
            {pgMode ? (
              <div className="text-[11px] px-3 py-2 rounded-lg" style={{ background: "#F7FAFC", color: "#4A5568" }}>
                로컬 PG 모드에서는 Google Sheets / Drive 키를 직접 입력하지 않습니다.<br />
                위 버튼을 누르면 backend의 <code>local_drive_mock</code> 이 sentinel ID
                <code>(local-folder-… / local-sheet-…)</code> 를 생성하고 PostgreSQL <code>tenants</code> 행에
                저장합니다. Google API는 호출되지 않습니다.
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2">{F("customer_sheet_key", "고객 데이터 시트키", "스프레드시트 ID", true)}</div>
                <div className="col-span-2">{F("work_sheet_key", "업무정리 시트키", "업무정리 스프레드시트 ID", true)}</div>
                {F("folder_id", "Drive 폴더 ID", "Google Drive 폴더 ID", true)}
                {F("sheet_key", "마스터 시트키", "공용 시트 ID (일반적으로 비워둠)", true)}
              </div>
            )}
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
            <SubmitButton
              type="submit"
              isSubmitting={creating}
              onClick={() => {}}
              loadingText="생성 중..."
              className="text-xs"
              style={{ padding: "6px 12px", fontSize: 12 }}
            >
              <><Save size={12} /> 계정 생성</>
            </SubmitButton>
          </div>
        </form>
      </div>
    </>
  );
}


// ── 계정 행 상세 편집 패널 ────────────────────────────────────────────────────
// ── 행정사 주민등록번호 — 암호화 저장 전용 컨트롤 (원문 미표시) ──────────────────
function AgentRrnField({ loginId }: { loginId: string }) {
  const [status, setStatus] = useState<{ has: boolean; last4: string } | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const r = await adminApi.getAgentRrn(loginId);
      setStatus({ has: !!r.data.has_agent_rrn, last4: r.data.agent_rrn_last4 || "" });
    } catch {
      setStatus({ has: false, last4: "" });
    }
  }, [loginId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const save = async () => {
    const v = value.trim();
    if (!v) { toast.error("새 주민등록번호를 입력하세요."); return; }
    setBusy(true);
    try {
      await adminApi.setAgentRrn(loginId, v);
      setValue("");               // 저장 후 입력칸 비움(메모리에 잔류 최소화)
      await refresh();
      toast.success("행정사 주민등록번호 저장됨");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "저장 실패");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await adminApi.setAgentRrn(loginId, "");   // 빈 값 = 삭제
      setValue("");
      await refresh();
      toast.success("행정사 주민등록번호 삭제됨");
    } catch {
      toast.error("삭제 실패");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="col-span-2">
      <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>
        행정사 주민등록번호 (암호화 저장)
      </label>
      <div className="text-xs mb-1" style={{ color: status?.has ? "#276749" : "#A0AEC0" }}>
        {status === null
          ? "확인 중…"
          : status.has
            ? `등록됨: ******-***${status.last4 || "****"}`
            : "저장 안 됨"}
      </div>
      <div className="flex items-center gap-2">
        <input
          type="password"
          autoComplete="off"
          className="hw-input flex-1 text-xs font-mono"
          placeholder="새 번호 입력 후 저장 (000000-0000000)"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="button" onClick={save} disabled={busy}
          className="text-xs px-3 py-1 rounded"
          style={{ background: "var(--hw-gold)", color: "#fff", opacity: busy ? 0.6 : 1 }}>
          저장
        </button>
        {status?.has && (
          <button type="button" onClick={remove} disabled={busy}
            className="text-xs px-3 py-1 rounded"
            style={{ background: "#FED7D7", color: "#9B2C2C", opacity: busy ? 0.6 : 1 }}>
            삭제
          </button>
        )}
      </div>
      <div className="text-[10px] mt-1" style={{ color: "#A0AEC0" }}>
        원문은 화면/응답에 표시되지 않으며 암호문으로만 저장됩니다. 변경하려면 새 번호를 입력하세요.
      </div>
    </div>
  );
}


function AccountDetailPanel({
  acc,
  onUpdate,
  onClose,
  pgMode = false,
}: {
  acc: Record<string, string>;
  onUpdate: (loginId: string, data: Record<string, unknown>) => void;
  onClose: () => void;
  pgMode?: boolean;
}) {
  const [form, setForm] = useState({ ...acc });
  const { submit: submitSave, isSubmitting: saving } = useSubmit();

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

  const handleSave = () => {
    submitSave(
      async () => {
        const {
          login_id, password_hash, is_admin, is_active, created_at,
          // eslint-disable-next-line @typescript-eslint/no-unused-vars
          ...editable
        } = form;
        void login_id; void password_hash; void is_admin; void is_active; void created_at;
        onUpdate(acc.login_id, editable);
        onClose();
      },
      { successMessage: "" }
    );
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
            <AgentRrnField loginId={acc.login_id} />
          </div>

          {pgMode ? (
            <>
              <div className="hw-section-divider mt-4">저장소 상태 (PostgreSQL 모드)</div>
              <div className="text-xs space-y-2" style={{ color: "#4A5568" }}>
                <div>
                  <span style={{ color: "#718096" }}>PostgreSQL: </span>
                  <span className="font-mono">{acc.pg_storage_label || "(없음)"}</span>
                </div>
                <div>
                  <span style={{ color: "#718096" }}>파일 저장소: </span>
                  <span className="font-mono">{acc.file_storage_label || "(없음)"}</span>
                </div>
                <div className="text-[11px]" style={{ color: "#A0AEC0" }}>
                  로컬 PG 모드에서는 Google Sheets / Drive 키를 직접 편집하지 않습니다.<br />
                  워크스페이스가 필요하면 계정 행의 ‘워크스페이스 자동 생성’ 버튼을 사용하세요.
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="hw-section-divider mt-4">Google Sheets 연동</div>
              <div className="space-y-2">
                {F("customer_sheet_key", "고객 데이터 시트키", true)}
                {F("work_sheet_key", "업무정리 시트키", true)}
                {F("folder_id", "Drive 폴더 ID", true)}
                {F("sheet_key", "마스터 시트키", true)}
              </div>
            </>
          )}

          <div className="hw-section-divider mt-4">메타데이터</div>
          <div>
            <label className="block text-[11px] font-medium mb-1" style={{ color: "#718096" }}>가입일</label>
            <div className="text-xs" style={{ color: "#A0AEC0" }}>{acc.created_at || "(없음)"}</div>
          </div>
        </div>
        <div className="hw-drawer-footer">
          <button onClick={onClose} className="btn-secondary text-xs">닫기</button>
          <SubmitButton
            isSubmitting={saving}
            onClick={handleSave}
            loadingText="저장 중..."
            className="text-xs"
            style={{ padding: "6px 12px", fontSize: 12 }}
          >
            <><Save size={12} /> 저장</>
          </SubmitButton>
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
            <SubmitButton
              isSubmitting={isDeleting}
              onClick={onConfirm}
              variant="danger"
              loadingText="처리 중..."
              className="text-xs"
              style={{ padding: "6px 12px", fontSize: 12 }}
            >
              <><Trash2 size={12} /> 삭제 확인</>
            </SubmitButton>
          </div>
        </div>
      </div>
    </>
  );
}


// ── 매뉴얼 업데이트 검토 탭 ──────────────────────────────────────────────────
type Decision =
  | "" | "NEW_CANDIDATE" | "REVIEWED_KEEP_EXISTING" | "REVIEWED_APPROVE_CANDIDATE"
  | "APPLIED" | "REJECTED_BAD_CANDIDATE" | "NEEDS_MANUAL_PAGE" | "UNRESOLVED";

interface RematchRow {
  row_id: string; detailed_code: string; action_type: string; title: string;
  manual: string; current_page_from: number; current_page_to: number;
  found_page: number; found_pages: number[];
  status: "PASS" | "PAGE_CHANGED" | "NOT_FOUND" | "SKIP";
  match_text: string; search_keyword: string; heading_snippet: string;
  // ── 보수적 품질 가드 + 결정 워크플로 (백엔드 manual_ref_rematch.py) ──
  current_snippet?: string; candidate_snippet?: string;
  recommendation?: string; confidence?: "HIGH" | "MEDIUM" | "LOW" | "";
  risk_flags?: string[]; reason?: string;
  decision?: Decision; candidate_changed?: boolean;
  manual_page_from?: number | null; manual_page_to?: number | null;
  auto_apply?: boolean; reviewed: boolean; applied: boolean;
}

// decision 메타: actionable = 기본(검토필요) 뷰에 노출되는 상태
const DECISION_META: Record<string, { label: string; bg: string; color: string; actionable: boolean }> = {
  NEW_CANDIDATE:              { label: "신규 후보",        bg: "#FFFFF0", color: "#6B5314", actionable: true },
  NEEDS_MANUAL_PAGE:          { label: "직접 페이지 필요",  bg: "#FFFAF0", color: "#9C4221", actionable: true },
  UNRESOLVED:                 { label: "미해결",           bg: "#FFF5F5", color: "#C53030", actionable: true },
  REVIEWED_APPROVE_CANDIDATE: { label: "후보 승인(미반영)", bg: "#FEFCBF", color: "#975A16", actionable: true },
  REVIEWED_KEEP_EXISTING:     { label: "기존 유지",        bg: "#F7FAFC", color: "#718096", actionable: false },
  REJECTED_BAD_CANDIDATE:     { label: "후보 기각",        bg: "#F7FAFC", color: "#A0AEC0", actionable: false },
  APPLIED:                    { label: "운영 반영됨",      bg: "#EBF8FF", color: "#2B6CB0", actionable: false },
  "":                         { label: "일치",            bg: "#F0FFF4", color: "#276749", actionable: false },
};
const CONF_META: Record<string, { bg: string; color: string }> = {
  HIGH:   { bg: "#F0FFF4", color: "#276749" },
  MEDIUM: { bg: "#FFFFF0", color: "#975A16" },
  LOW:    { bg: "#FFF5F5", color: "#C53030" },
};
const RISK_LABEL: Record<string, string> = {
  large_move: "큰 이동", weak_code_match: "코드 약일치", common_page: "공통 페이지",
  no_title_match: "제목 불일치", no_pdf_match: "PDF 미발견",
};

function effDecision(r: RematchRow): Decision {
  if (r.applied) return "APPLIED";
  if (r.decision) return r.decision;
  if (r.status === "PASS") return "";
  if (r.status === "NOT_FOUND") return "UNRESOLVED";
  if (r.status === "PAGE_CHANGED") return "NEW_CANDIDATE";
  return "";
}
function isActionable(r: RematchRow): boolean {
  if (r.applied) return false;
  if (r.candidate_changed) return true;   // 후보 변경됨 → 재검토 필요
  return DECISION_META[effDecision(r)]?.actionable ?? false;
}

const PRIO_META: Record<string, { label: string; bg: string; color: string; rank: number }> = {
  HIGH:   { label: "HIGH",   bg: "#FFF5F5", color: "#C53030", rank: 3 },
  MEDIUM: { label: "MEDIUM", bg: "#FFFFF0", color: "#975A16", rank: 2 },
  LOW:    { label: "LOW",    bg: "#F7FAFC", color: "#A0AEC0", rank: 1 },
};
// 우선순위: HIGH=미해결·직접입력필요·후보변경·큰이동·LOW신뢰도, MEDIUM=그 외 actionable, LOW=비actionable
function rowPriority(r: RematchRow): "HIGH" | "MEDIUM" | "LOW" {
  if (!isActionable(r)) return "LOW";
  const eff = effDecision(r);
  const risk = r.risk_flags || [];
  if (r.candidate_changed || eff === "UNRESOLVED" || eff === "NEEDS_MANUAL_PAGE"
      || risk.includes("large_move") || r.confidence === "LOW") return "HIGH";
  return "MEDIUM";
}

type RvStatusFilter = "actionable" | "all" | "approve" | "unresolved" | "reviewed" | "applied";
type RvGroupBy = "found_page" | "code" | "action" | "none";

function ManualReviewTab() {
  const [statusFilter, setStatusFilter] = useState<RvStatusFilter>("actionable");
  const [manualFilter, setManualFilter] = useState<string>("");
  const [codeFilter, setCodeFilter] = useState<string>("");
  const [groupBy, setGroupBy] = useState<RvGroupBy>("found_page");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [approvingGroup, setApprovingGroup] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const { submit: submitRematch, isSubmitting: runningRematch } = useSubmit();
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

  const handleRunRematch = () => {
    submitRematch(
      async () => {
        await api.post("/api/manual/run-rematch");
        await loadReview();
      },
      { successMessage: "재탐색 완료", errorMessage: "재탐색 실패" }
    );
  };

  const _errDetail = (err: unknown, fallback: string) => {
    const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return d ? `${fallback}: ${d}` : fallback;
  };

  // 검토 결정 저장 — staging(review JSON)에만 기록. 운영 manual_ref 미반영.
  const decide = async (row: RematchRow, decision: Decision, pf?: number, pt?: number) => {
    setBusyId(row.row_id);
    try {
      await api.post(`/api/manual/update-review/${row.row_id}/decision`, {
        decision, page_from: pf ?? null, page_to: pt ?? null,
      });
      setRows(prev => prev.map(r => r.row_id === row.row_id ? {
        ...r, decision, reviewed: decision !== "NEW_CANDIDATE", candidate_changed: false,
        manual_page_from: decision === "NEEDS_MANUAL_PAGE" ? (pf ?? null) : r.manual_page_from,
        manual_page_to: decision === "NEEDS_MANUAL_PAGE" ? (pt ?? pf ?? null) : r.manual_page_to,
      } : r));
      toast.success(`${DECISION_META[decision]?.label ?? decision} (운영 미반영)`);
    } catch (err) { toast.error(_errDetail(err, "결정 저장 실패")); }
    finally { setBusyId(null); }
  };

  // 운영 반영 — 승인된 후보/직접입력 페이지만. 백업 후 manual_ref 수정(백엔드 가드).
  const applyToProd = async (row: RematchRow) => {
    const eff = effDecision(row);
    let pf = 0, pt = 0;
    if (eff === "REVIEWED_APPROVE_CANDIDATE") { pf = row.found_page; pt = row.found_page; }
    else if (eff === "NEEDS_MANUAL_PAGE") { pf = row.manual_page_from || 0; pt = row.manual_page_to || pf; }
    else { toast.error("운영 반영은 '후보 승인' 또는 '직접 페이지 입력' 상태에서만 가능합니다."); return; }
    if (!pf || pf < 1) { toast.error("반영할 페이지가 없습니다."); return; }
    if (!window.confirm(`운영 manual_ref에 반영합니다 (p.${pf}).\n백업을 생성한 뒤 적용합니다.`)) return;
    setBusyId(row.row_id);
    try {
      const res = await api.post(`/api/manual/update-review/${row.row_id}/apply`, { page_from: pf, page_to: pt });
      setRows(prev => prev.map(r => r.row_id === row.row_id ? { ...r, applied: true, reviewed: true, decision: "APPLIED", found_page: pf } : r));
      toast.success(`운영 반영 완료 (p.${pf})${res.data?.backup ? ` · 백업 ${res.data.backup}` : ""}`);
    } catch (err) { toast.error(_errDetail(err, "운영 반영 실패")); }
    finally { setBusyId(null); }
  };

  // 그룹 기존 유지 = 그룹 내 actionable 을 일괄 '기존 유지'(staging)로 표시. 운영 미반영.
  const handleGroupKeep = async (groupKey: string, groupRows: RematchRow[]) => {
    const targets = groupRows.filter(isActionable);
    if (!targets.length) return;
    if (!window.confirm(`이 그룹 ${targets.length}건을 '기존 유지'로 표시합니다 (운영 미반영).`)) return;
    setApprovingGroup(groupKey);
    try {
      for (const r of targets) {
        await api.post(`/api/manual/update-review/${r.row_id}/decision`, { decision: "REVIEWED_KEEP_EXISTING" });
      }
      const ids = new Set(targets.map(r => r.row_id));
      setRows(prev => prev.map(r => ids.has(r.row_id) ? { ...r, decision: "REVIEWED_KEEP_EXISTING", reviewed: true, candidate_changed: false } : r));
      toast.success(`${targets.length}건 기존 유지 표시 (운영 미반영)`);
    } catch (err) { toast.error(_errDetail(err, "그룹 기존 유지 실패")); }
    finally { setApprovingGroup(null); }
  };

  // ── 요약 카운트 (decision 기반) ──
  const summary = {
    total: rows.length,
    actionable: rows.filter(isActionable).length,
    approve: rows.filter(r => !r.applied && effDecision(r) === "REVIEWED_APPROVE_CANDIDATE").length,
    applied: rows.filter(r => r.applied).length,
    reviewed: rows.filter(r => !r.applied && ["REVIEWED_KEEP_EXISTING", "REJECTED_BAD_CANDIDATE"].includes(effDecision(r))).length,
    unresolved: rows.filter(r => !r.applied && ["UNRESOLVED", "NEEDS_MANUAL_PAGE"].includes(effDecision(r))).length,
  };

  // ── 필터 적용 (기본: actionable 만 → 일치/적용완료/기존유지/기각 숨김) ──
  const manualOptions = Array.from(new Set(rows.map(r => r.manual).filter(Boolean)));
  const visible = rows.filter(r => {
    const eff = effDecision(r);
    if (statusFilter === "actionable" && !isActionable(r)) return false;
    if (statusFilter === "approve" && !(eff === "REVIEWED_APPROVE_CANDIDATE" && !r.applied)) return false;
    if (statusFilter === "unresolved" && !(["UNRESOLVED", "NEEDS_MANUAL_PAGE"].includes(eff) && !r.applied)) return false;
    if (statusFilter === "reviewed" && !["REVIEWED_KEEP_EXISTING", "REJECTED_BAD_CANDIDATE"].includes(eff)) return false;
    if (statusFilter === "applied" && !r.applied) return false;
    if (manualFilter && r.manual !== manualFilter) return false;
    if (codeFilter && !(r.detailed_code || "").toLowerCase().includes(codeFilter.toLowerCase())) return false;
    return true;
  });

  // ── 그룹핑 (발견 페이지 / 자격코드 / 업무 / 없음) ──
  const groupKeyOf = (r: RematchRow): string => {
    if (groupBy === "found_page") return `${r.manual} · 발견 p.${r.found_page || "—"}`;
    if (groupBy === "code") return r.detailed_code || "(코드 없음)";
    if (groupBy === "action") return r.action_type || "(업무 없음)";
    return r.row_id; // none → 행별 단독
  };
  const groupMap = new Map<string, RematchRow[]>();
  for (const r of visible) {
    const k = groupKeyOf(r);
    (groupMap.get(k) ?? groupMap.set(k, []).get(k)!).push(r);
  }
  const groups = Array.from(groupMap.entries()).map(([key, gr]) => {
    const topPrio = gr.reduce<"HIGH" | "MEDIUM" | "LOW">((acc, r) => {
      const p = rowPriority(r);
      return PRIO_META[p].rank > PRIO_META[acc].rank ? p : acc;
    }, "LOW");
    const actionable = gr.filter(isActionable).length;
    return { key, rows: gr, topPrio, actionable };
  }).sort((a, b) => PRIO_META[b.topPrio].rank - PRIO_META[a.topPrio].rank);

  const toggleGroup = (k: string) =>
    setCollapsed(prev => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });

  const SUMMARY_CARDS: { label: string; value: number; filter: RvStatusFilter; bg: string; color: string }[] = [
    { label: "전체",          value: summary.total,      filter: "all",        bg: "#F7FAFC", color: "#2D3748" },
    { label: "검토 필요",      value: summary.actionable, filter: "actionable", bg: "#FFFAF0", color: "#9C4221" },
    { label: "승인 대기",      value: summary.approve,    filter: "approve",    bg: "#FEFCBF", color: "#975A16" },
    { label: "미해결/직접입력", value: summary.unresolved, filter: "unresolved", bg: "#FFF5F5", color: "#C53030" },
    { label: "검토완료(유지/기각)", value: summary.reviewed, filter: "reviewed", bg: "#F7FAFC", color: "#718096" },
    { label: "운영 반영됨",     value: summary.applied,    filter: "applied",    bg: "#EBF8FF", color: "#2B6CB0" },
  ];

  // ── 행 렌더 (decision 기반: 기존유지/후보승인/후보기각/직접입력/운영반영) ──
  const renderRow = (row: RematchRow) => {
    const eff = effDecision(row);
    const dm = DECISION_META[eff] ?? DECISION_META[""];
    const pm = PRIO_META[rowPriority(row)];
    const act = isActionable(row);
    const busy = busyId === row.row_id;
    const hasCand = !!row.found_page;
    const canApply = eff === "REVIEWED_APPROVE_CANDIDATE" || (eff === "NEEDS_MANUAL_PAGE" && !!row.manual_page_from);
    const dim = busy ? 0.5 : 1;
    return (
      <Fragment key={row.row_id}>
        <tr>
          <td><span className="px-1.5 py-0.5 rounded text-xs font-semibold" style={{ background: pm.bg, color: pm.color }}>{pm.label}</span></td>
          <td className="font-mono">{row.detailed_code || "—"}</td>
          <td style={{ color: "#718096" }}>{row.action_type}</td>
          <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={row.title}>{row.title}</td>
          <td>{row.manual}</td>
          <td className="font-mono text-center" style={{ whiteSpace: "nowrap" }}>
            {row.current_page_from || "—"}
            {!!row.current_page_from && (
              <button onClick={() => setPdfPreview({ manual: row.manual, page: row.current_page_from, label: "기존 페이지" })} title="기존 페이지 보기"
                style={{ marginLeft: 5, background: "none", border: "none", cursor: "pointer", color: "#718096", verticalAlign: "middle" }}><FileText size={12} /></button>
            )}
          </td>
          <td className="font-mono text-center" style={{ whiteSpace: "nowrap" }}>
            {hasCand ? (<>
              <span style={{ color: "#D97706" }}>{row.found_page}</span>
              <button onClick={() => setPdfPreview({ manual: row.manual, page: row.found_page, label: "후보 페이지" })} title="후보 페이지 보기"
                style={{ marginLeft: 5, background: "none", border: "none", cursor: "pointer", color: "#718096", verticalAlign: "middle" }}><FileText size={12} /></button>
            </>) : <span style={{ color: "#CBD5E0" }}>—</span>}
          </td>
          <td style={{ whiteSpace: "nowrap" }}>
            <span className="px-2 py-0.5 rounded-full text-xs font-medium" style={{ background: dm.bg, color: dm.color }}>{dm.label}</span>
            {row.candidate_changed && <span className="ml-1 px-1.5 py-0.5 rounded text-xs font-semibold" style={{ background: "#FEFCBF", color: "#975A16" }}>후보 변경됨</span>}
          </td>
          <td>
            {act ? (
              inlineEdit?.rowId === row.row_id ? (
                <div className="flex gap-1 items-center">
                  <input value={inlineEdit.pf} onChange={e => setInlineEdit({ ...inlineEdit, pf: e.target.value })} className="hw-input w-12 text-xs" placeholder="from" />
                  <input value={inlineEdit.pt} onChange={e => setInlineEdit({ ...inlineEdit, pt: e.target.value })} className="hw-input w-12 text-xs" placeholder="to" />
                  <button disabled={busy} onClick={() => { const pf = Number(inlineEdit.pf); const pt = Number(inlineEdit.pt) || pf; if (pf >= 1) { decide(row, "NEEDS_MANUAL_PAGE", pf, pt); setInlineEdit(null); } }}
                    style={{ fontSize: 11, padding: "3px 8px", borderRadius: 5, background: "#4299E1", color: "#fff", border: "none", cursor: "pointer", opacity: dim }}>저장</button>
                  <button onClick={() => setInlineEdit(null)} style={{ fontSize: 11, padding: "3px 7px", borderRadius: 5, background: "#fff", color: "#718096", border: "1px solid #CBD5E0", cursor: "pointer" }}>취소</button>
                </div>
              ) : (
                <div className="flex gap-1 flex-wrap">
                  <button disabled={busy} onClick={() => decide(row, "REVIEWED_KEEP_EXISTING")} title="기존 매핑 유지(권장 기본)"
                    className="px-2 py-1 rounded font-medium" style={{ background: "#F7FAFC", border: "1px solid #CBD5E0", color: "#4A5568", fontSize: 11, opacity: dim }}>기존 유지</button>
                  {hasCand && <button disabled={busy} onClick={() => decide(row, "REVIEWED_APPROVE_CANDIDATE")} title="후보 승인(운영 미반영)"
                    className="px-2 py-1 rounded font-medium" style={{ background: "#FEFCBF", border: "1px solid #D69E2E", color: "#975A16", fontSize: 11, opacity: dim }}>후보 승인</button>}
                  {hasCand && <button disabled={busy} onClick={() => decide(row, "REJECTED_BAD_CANDIDATE")} title="후보 기각"
                    className="px-2 py-1 rounded font-medium" style={{ background: "#FFF5F5", border: "1px solid #FC8181", color: "#C53030", fontSize: 11, opacity: dim }}>후보 기각</button>}
                  <button disabled={busy} onClick={() => setInlineEdit({ rowId: row.row_id, pf: String(row.manual_page_from || row.found_page || row.current_page_from || ""), pt: "" })}
                    className="flex items-center gap-1 px-2 py-1 rounded font-medium" style={{ background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0", fontSize: 11 }}><Edit3 size={11} /> 직접 입력</button>
                  {canApply && <button disabled={busy} onClick={() => applyToProd(row)} title="운영 manual_ref 에 반영(백업 후)"
                    className="flex items-center gap-1 px-2 py-1 rounded font-medium" style={{ background: "#F0FFF4", border: "1px solid #48BB78", color: "#276749", fontSize: 11, opacity: dim }}>
                    {busy ? <Loader2 size={11} className="animate-spin" /> : <CheckSquare size={11} />} 운영 반영</button>}
                </div>
              )
            ) : <span style={{ color: "#CBD5E0", fontSize: 11 }}>—</span>}
          </td>
        </tr>
        {(act || row.reason) && (
          <tr>
            <td></td>
            <td colSpan={8} style={{ paddingTop: 0, paddingBottom: 8 }}>
              <div style={{ fontSize: 11, color: "#718096", display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                {row.confidence && <span className="px-1.5 py-0.5 rounded font-semibold" style={{ background: CONF_META[row.confidence]?.bg, color: CONF_META[row.confidence]?.color }}>신뢰도 {row.confidence}</span>}
                {(row.risk_flags || []).map(f => <span key={f} className="px-1.5 py-0.5 rounded" style={{ background: "#FFF5F5", color: "#C53030" }}>{RISK_LABEL[f] ?? f}</span>)}
                {row.reason && <span>· {row.reason}</span>}
              </div>
              {(row.current_snippet || row.candidate_snippet) && (
                <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 3, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  <div title={row.current_snippet}><b style={{ color: "#718096" }}>기존 p.{row.current_page_from}:</b> {(row.current_snippet || "").slice(0, 90) || "—"}</div>
                  <div title={row.candidate_snippet}><b style={{ color: "#D97706" }}>후보 p.{row.found_page || "—"}:</b> {(row.candidate_snippet || "").slice(0, 90) || "—"}</div>
                </div>
              )}
            </td>
          </tr>
        )}
      </Fragment>
    );
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
        <SubmitButton
          isSubmitting={runningRematch}
          onClick={handleRunRematch}
          loadingText="탐색 중..."
          className="text-xs"
          style={{ padding: "6px 12px", fontSize: 12, background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0" }}
        >
          <><RotateCcw size={13} /> 지금 재탐색</>
        </SubmitButton>
      </div>

      {/* 워크플로 안내 배너 */}
      <div className="hw-card text-xs" style={{ background: "#F7FAFC", borderColor: "#E2E8F0", lineHeight: 1.7 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", color: "#2D3748", fontWeight: 600 }}>
          <span>1단계: 후보 검토</span><span style={{ color: "#CBD5E0" }}>→</span>
          <span>2단계: 승인 후보 확인</span><span style={{ color: "#CBD5E0" }}>→</span>
          <span>3단계: 운영 반영</span>
        </div>
        <div style={{ color: "#C53030", marginTop: 2 }}>운영 반영 전에는 기존 실무지침이 변경되지 않습니다.</div>
        <div style={{ color: "#718096", marginTop: 2 }}>
          기존 유지·후보 승인·후보 기각·직접 입력은 모두 staging 결정(운영 미반영)이며,
          ‘운영 반영’ 버튼을 눌러야만 백업 후 manual_ref 에 적용됩니다. 보수적 기본값은 ‘기존 유지’입니다.
        </div>
      </div>

      {/* 요약 카드 (클릭 시 해당 상태로 필터) */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
        {SUMMARY_CARDS.map(c => (
          <button key={c.label} onClick={() => setStatusFilter(c.filter)}
            className="hw-card text-left"
            style={{
              padding: "10px 12px", cursor: "pointer",
              border: statusFilter === c.filter ? `2px solid ${c.color}` : "1px solid #E2E8F0",
              background: c.bg,
            }}>
            <div style={{ fontSize: 11, color: c.color, fontWeight: 600 }}>{c.label}</div>
            <div style={{ fontSize: 20, fontWeight: 800, color: c.color, lineHeight: 1.2 }}>{c.value}</div>
          </button>
        ))}
      </div>

      {/* 필터 행: 매뉴얼 / 자격코드 / 그룹기준 / 빠른토글 */}
      <div className="flex gap-2 flex-wrap items-center text-xs">
        <select className="hw-input text-xs" style={{ minWidth: 120 }}
          value={manualFilter} onChange={e => setManualFilter(e.target.value)}>
          <option value="">매뉴얼 전체</option>
          {manualOptions.map(m => <option key={m} value={m}>{m}</option>)}
        </select>
        <input className="hw-input text-xs" style={{ width: 130 }} placeholder="자격코드 검색"
          value={codeFilter} onChange={e => setCodeFilter(e.target.value)} />
        <span style={{ color: "#A0AEC0" }}>|</span>
        <span style={{ color: "#718096" }}>그룹</span>
        {([
          { k: "found_page", label: "발견 페이지" },
          { k: "code", label: "자격코드" },
          { k: "action", label: "업무" },
          { k: "none", label: "없음" },
        ] as const).map(({ k, label }) => (
          <button key={k} onClick={() => setGroupBy(k)}
            className={`hw-tab ${groupBy === k ? "active" : ""}`}>{label}</button>
        ))}
        <span style={{ color: "#A0AEC0" }}>|</span>
        <button onClick={() => setStatusFilter("approve")} className={`hw-tab ${statusFilter === "approve" ? "active" : ""}`}>승인 대기만</button>
        <button onClick={() => setStatusFilter("unresolved")} className={`hw-tab ${statusFilter === "unresolved" ? "active" : ""}`}>미해결/직접입력만</button>
      </div>

      {/* 그룹 테이블 */}
      {visible.length === 0 ? (
        <div className="hw-card text-sm text-center py-10" style={{ color: "#A0AEC0" }}>
          {rows.length === 0 ? "재탐색을 실행해 주세요." : "해당 조건의 항목이 없습니다 (일치/적용완료/기존유지/기각은 기본 숨김)."}
        </div>
      ) : (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="overflow-x-auto">
            <table className="hw-table w-full text-xs" style={{ minWidth: 980 }}>
              <thead>
                <tr>
                  {["우선순위", "자격코드", "업무", "제목", "매뉴얼", "현재 페이지", "발견 페이지", "상태", "액션"].map(h => (
                    <th key={h} className="text-left whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {groups.map(g => {
                  const isCollapsed = collapsed.has(g.key);
                  const pm = PRIO_META[g.topPrio];
                  const single = groupBy === "none";
                  return (
                    <Fragment key={g.key}>
                      {!single && (
                        <tr style={{ background: "#F7FAFC" }}>
                          <td colSpan={9} style={{ padding: "6px 10px" }}>
                            <div className="flex items-center gap-2 flex-wrap">
                              <button onClick={() => toggleGroup(g.key)}
                                style={{ background: "none", border: "none", cursor: "pointer", color: "#4A5568", display: "flex", alignItems: "center", gap: 4, fontWeight: 700 }}>
                                <ChevronRight size={14} style={{ transform: isCollapsed ? "none" : "rotate(90deg)", transition: "transform .15s" }} />
                                {g.key}
                              </button>
                              <span style={{ fontSize: 11, color: "#718096" }}>({g.rows.length}건)</span>
                              <span className="px-1.5 py-0.5 rounded text-xs font-semibold" style={{ background: pm.bg, color: pm.color }}>{pm.label}</span>
                              {g.actionable > 0 && (
                                <button onClick={() => handleGroupKeep(g.key, g.rows)}
                                  disabled={approvingGroup === g.key}
                                  title="그룹 전체를 '기존 유지'로 표시 (운영 실무지침 미반영)"
                                  className="flex items-center gap-1 px-2 py-0.5 rounded font-medium"
                                  style={{ background: "#F7FAFC", border: "1px solid #CBD5E0", color: "#4A5568", fontSize: 11, opacity: approvingGroup === g.key ? 0.5 : 1 }}>
                                  {approvingGroup === g.key ? <Loader2 size={11} className="animate-spin" /> : <CheckSquare size={11} />} 그룹 기존 유지
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                      {(single || !isCollapsed) && g.rows.map(renderRow)}
                    </Fragment>
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


// ── 매뉴얼 업데이트 v1 (staging 검토) ─────────────────────────────────────────
// rhwp 텍스트/diff 엔진이 만든 staging 산출물(변경 페이지 · 영향 후보 · 변경 페이지
// 검토 PDF)을 admin 전용으로 조회. 운영 PDF 뷰어/운영 DB 는 절대 변경하지 않는다.
const LABEL_KR: Record<string, string> = {
  residence: "체류민원", visa: "사증민원", revision_history: "수정이력",
};

interface StagingManifest {
  version: string;
  baseline_version: string;
  status: string;
  manuals: Record<string, { source_file: string; page_count: number; pdf_path: string | null }>;
  changed_pages_summary: Record<string, Record<string, number>>;
  changed_page_count: number;
  manual_ref_candidate_count: number;
  pdf_mode: "none" | "changed-pages-only" | "full";
  review_pdf_pages: Record<string, number[]>;
}
interface ChangedPageRow {
  manual_label: string;
  baseline_page: number | null;
  new_page: number | null;
  change_type: string;
  similarity: number | null;
  moved_from?: number | null;
  keywords: string[];
}
interface StagingCandidate {
  row_id: string;
  item_index: number;
  detailed_code: string;
  manual_label: string;
  old_page_from: number;
  old_page_to: number;
  candidate_page_from: number;
  candidate_page_to: number;
  confidence: string;
  action: string;
  reason: string;
  business_name?: string;
  major_action_std?: string;
  user_decision?: string;
}

const CHANGE_BADGE: Record<string, { bg: string; color: string }> = {
  modified: { bg: "#FFFFF0", color: "#6B5314" },
  moved:    { bg: "#EBF8FF", color: "#2B6CB0" },
  added:    { bg: "#F0FFF4", color: "#276749" },
  deleted:  { bg: "#FFF5F5", color: "#C53030" },
};

function ManualUpdateV1Tab() {
  const [versions, setVersions] = useState<string[]>([]);
  const [version, setVersion] = useState<string>("");
  const [manifest, setManifest] = useState<StagingManifest | null>(null);
  const [changed, setChanged] = useState<ChangedPageRow[]>([]);
  const [candidates, setCandidates] = useState<StagingCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [review, setReview] = useState<{ label: string; page: number } | null>(null);

  const token = typeof window !== "undefined" ? (localStorage.getItem("access_token") || "") : "";

  // 버전 목록 로드
  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/api/guidelines/manual-staging/versions");
        const vs = (r.data?.versions ?? []) as string[];
        setVersions(vs);
        if (vs.length && !version) setVersion(vs[vs.length - 1]);
      } catch { /* 무시 */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 선택 버전의 manifest/changed/candidates 로드
  const loadVersion = useCallback(async (v: string) => {
    if (!v) return;
    setLoading(true);
    setManifest(null); setChanged([]); setCandidates([]);
    try {
      const [m, ch, ca] = await Promise.all([
        api.get(`/api/guidelines/manual-staging/${encodeURIComponent(v)}/manifest`),
        api.get(`/api/guidelines/manual-staging/${encodeURIComponent(v)}/changed-pages`),
        api.get(`/api/guidelines/manual-staging/${encodeURIComponent(v)}/candidates`),
      ]);
      setManifest(m.data as StagingManifest);
      setChanged((ch.data?.rows ?? []) as ChangedPageRow[]);
      setCandidates((ca.data?.rows ?? []) as StagingCandidate[]);
    } catch {
      toast.error("staging 자료를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (version) void loadVersion(version); }, [version, loadVersion]);

  // 변경 페이지의 검토 PDF가 생성되어 있는지 (review_pdf_pages 에 포함된 new_page 만)
  const hasReviewPdf = useCallback((label: string, page: number | null) => {
    if (!page || !manifest) return false;
    return (manifest.review_pdf_pages?.[label] ?? []).includes(page);
  }, [manifest]);

  const pdfModeLabel: Record<string, string> = {
    none: "없음 (변경 없음 / 미생성)",
    "changed-pages-only": "변경 페이지만",
    full: "전체 PDF",
  };

  return (
    <div className="space-y-4">
      {/* 안내 배너 */}
      <div className="hw-card text-xs leading-relaxed" style={{ background: "#F7FAFC", borderColor: "#E2E8F0" }}>
        <div style={{ color: "#276749", fontWeight: 600 }}>✅ 기존 실무지침 PDF 조회는 변경되지 않았습니다.</div>
        <div style={{ color: "#4A5568", marginTop: 4 }}>아래 자료는 최신 매뉴얼 후보 검토용 staging 자료입니다.</div>
        <div style={{ color: "#C53030", marginTop: 2 }}>승인 전에는 운영 실무지침에 반영되지 않습니다.</div>
      </div>

      {/* 버전 선택 */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs font-medium" style={{ color: "#718096" }}>staging 버전</span>
        <select
          className="hw-input text-xs"
          style={{ minWidth: 200 }}
          value={version}
          onChange={(e) => setVersion(e.target.value)}>
          {versions.length === 0 && <option value="">(staging 버전 없음)</option>}
          {versions.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <button
          onClick={() => version && loadVersion(version)}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border"
          style={{ borderColor: "#4299E1", color: "#2B6CB0", background: "#EBF8FF" }}>
          <RotateCcw size={12} /> 새로고침
        </button>
        {loading && <Loader2 size={14} className="animate-spin" style={{ color: "#A0AEC0" }} />}
      </div>

      {/* 빈 상태 안내 (staging 검토본 없음) */}
      {!loading && versions.length === 0 && (
        <div className="hw-card text-sm" style={{ color: "#4A5568", lineHeight: 1.7 }}>
          <div style={{ fontWeight: 700, color: "#2D3748", marginBottom: 6 }}>
            아직 생성된 매뉴얼 staging 검토본이 없습니다.
          </div>
          <div>이 화면은 새 매뉴얼을 분석한 뒤 변경 페이지와 manual_ref 후보를 검토하는 곳입니다.</div>
          <div style={{ color: "#276749" }}>기존 실무지침 PDF 조회는 정상 유지됩니다.</div>
          <div style={{ color: "#C53030" }}>승인 전에는 운영 실무지침에 반영되지 않습니다.</div>
        </div>
      )}

      {/* manifest 요약 */}
      {manifest && (
        <div className="hw-card">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            {[
              ["버전", manifest.version],
              ["기준(baseline)", manifest.baseline_version],
              ["상태", manifest.status],
              ["PDF 모드", pdfModeLabel[manifest.pdf_mode] ?? manifest.pdf_mode],
              ["매뉴얼 수", String(Object.keys(manifest.manuals || {}).length)],
              ["변경 페이지 수", String(manifest.changed_page_count ?? 0)],
              ["영향 후보 수", String(manifest.manual_ref_candidate_count ?? 0)],
            ].map(([k, v]) => (
              <div key={k}>
                <div style={{ color: "#A0AEC0" }}>{k}</div>
                <div style={{ color: "#2D3748", fontWeight: 600 }}>{v}</div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(manifest.manuals || {}).map(([label, m]) => (
              <span key={label} className="text-xs px-2 py-1 rounded-full" style={{ background: "#EDF2F7", color: "#4A5568" }}>
                {LABEL_KR[label] ?? label}: {m.page_count}p
              </span>
            ))}
          </div>
          {/* full PDF 생성은 명시적 CLI 옵션 (운영 영향 없음) */}
          <div className="mt-3 text-[11px] p-2 rounded" style={{ background: "#FFFDF7", color: "#6B5314", border: "1px solid #FAF089" }}>
            전체 staging PDF 가 필요하면 로컬에서 명시적으로 생성하세요:
            <code className="ml-1 font-mono">python backend/scripts/manual_update_local.py --version {manifest.version} --full-pdf</code>
            <br />기본 파이프라인은 변경 페이지 ± 이웃만 PDF 로 만들어 불필요한 작업을 최소화합니다.
          </div>
        </div>
      )}

      {/* 변경 페이지 테이블 */}
      <div>
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>변경 페이지 ({changed.length})</div>
        {changed.length === 0 ? (
          <div className="hw-card text-sm text-center py-6" style={{ color: "#A0AEC0" }}>
            {manifest ? "변경된 페이지가 없습니다 (baseline 과 동일)." : "버전을 선택하세요."}
          </div>
        ) : (
          <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="overflow-x-auto">
              <table className="hw-table w-full text-xs" style={{ minWidth: 760 }}>
                <thead>
                  <tr>{["매뉴얼", "baseline p.", "new p.", "변경 유형", "유사도", "키워드", "보기"].map(h =>
                    <th key={h} className="text-left whitespace-nowrap">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {changed.map((r, i) => {
                    const badge = CHANGE_BADGE[r.change_type] ?? { bg: "#F7FAFC", color: "#718096" };
                    const canView = hasReviewPdf(r.manual_label, r.new_page);
                    return (
                      <tr key={`${r.manual_label}-${r.new_page}-${i}`}>
                        <td>{LABEL_KR[r.manual_label] ?? r.manual_label}</td>
                        <td className="font-mono text-center">{r.baseline_page ?? "—"}</td>
                        <td className="font-mono text-center">{r.new_page ?? "—"}</td>
                        <td>
                          <span className="px-2 py-0.5 rounded-full font-medium" style={{ background: badge.bg, color: badge.color }}>
                            {r.change_type}{r.moved_from ? ` (←p.${r.moved_from})` : ""}
                          </span>
                        </td>
                        <td className="font-mono text-center">{r.similarity != null ? r.similarity.toFixed(2) : "—"}</td>
                        <td style={{ maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                          title={(r.keywords || []).join(", ")}>{(r.keywords || []).join(", ") || "—"}</td>
                        <td>
                          {canView ? (
                            <button onClick={() => setReview({ label: r.manual_label, page: r.new_page! })}
                              className="flex items-center gap-1 px-2 py-1 rounded font-medium"
                              style={{ background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0", fontSize: 11 }}>
                              <FileText size={11} /> 변경 페이지 보기
                            </button>
                          ) : <span style={{ color: "#CBD5E0" }}>—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* 후보 테이블 */}
      <div>
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>
          영향 받은 manual_ref 후보 ({candidates.length}) — 승인 전 자동 반영 안 됨
        </div>
        {candidates.length === 0 ? (
          <div className="hw-card text-sm text-center py-6" style={{ color: "#A0AEC0" }}>
            영향 받은 후보가 없습니다.
          </div>
        ) : (
          <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="overflow-x-auto">
              <table className="hw-table w-full text-xs" style={{ minWidth: 920 }}>
                <thead>
                  <tr>{["row_id", "자격코드", "매뉴얼", "기존 p.", "후보 p.", "신뢰도", "액션", "사유", "결정", "보기"].map(h =>
                    <th key={h} className="text-left whitespace-nowrap">{h}</th>)}</tr>
                </thead>
                <tbody>
                  {candidates.map((c) => {
                    const canView = hasReviewPdf(c.manual_label, c.candidate_page_from);
                    return (
                      <tr key={`${c.row_id}-${c.item_index}`}>
                        <td className="font-mono">{c.row_id}</td>
                        <td className="font-mono">{c.detailed_code || "—"}</td>
                        <td>{LABEL_KR[c.manual_label] ?? c.manual_label}</td>
                        <td className="font-mono text-center">p.{c.old_page_from}-{c.old_page_to}</td>
                        <td className="font-mono text-center">p.{c.candidate_page_from}-{c.candidate_page_to}</td>
                        <td>{c.confidence}</td>
                        <td>{c.action}</td>
                        <td style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                          title={c.reason}>{c.reason}</td>
                        <td style={{ color: "#A0AEC0" }}>{c.user_decision || "미정"}</td>
                        <td>
                          {canView ? (
                            <button onClick={() => setReview({ label: c.manual_label, page: c.candidate_page_from })}
                              className="flex items-center gap-1 px-2 py-1 rounded"
                              style={{ background: "#EBF8FF", border: "1px solid #4299E1", color: "#2B6CB0", fontSize: 11 }}>
                              <FileText size={11} /> 보기
                            </button>
                          ) : <span style={{ color: "#CBD5E0" }}>—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* 변경 페이지 검토 PDF 뷰어 (운영 뷰어와 분리된 staging 전용) */}
      {review && version && (
        <div
          onClick={() => setReview(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div onClick={(e) => e.stopPropagation()}
            style={{ background: "#fff", borderRadius: 12, width: "min(80vw, 900px)", height: "85vh", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 20px 60px rgba(0,0,0,0.3)" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: "1px solid #E2E8F0", flexShrink: 0 }}>
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                [검토용 staging] {LABEL_KR[review.label] ?? review.label} — p.{review.page}
              </span>
              <button onClick={() => setReview(null)}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "#718096", lineHeight: 1 }}>✕</button>
            </div>
            <iframe
              key={`${version}-${review.label}-${review.page}`}
              src={`/api/guidelines/manual-staging/${encodeURIComponent(version)}/${encodeURIComponent(review.label)}/review-page/${review.page}/pdf?token=${encodeURIComponent(token)}#toolbar=1&view=Fit`}
              style={{ flex: 1, border: "none", width: "100%" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}


// ── 매뉴얼 업데이트 (PostgreSQL 단일 출처) ───────────────────────────────────
// FEATURE_PG_MANUAL_UPDATE=true 이면 /api/guidelines/manual-update/state 가
// source:"pg" 를 반환 → PG 화면. 아니면 source:"file" → 기존 파일 staging 화면.
type PgStateResp = {
  source: "pg" | "file";
  state?: {
    status?: string;
    last_run_at?: string | null;
    last_success_at?: string | null;
    last_run_date_kst?: string | null;
    last_checked_version?: string | null;
    last_detected_version?: string | null;
    last_staging_version?: string | null;
    needs_review?: boolean;
    needs_review_stored?: boolean;
    review_reason?: string;
    candidate_count?: number;
    changed_count?: number;
    review_target_count?: number;
    noop_count?: number;
    pending_count?: number;
    reviewed_count?: number;
    applied_count?: number;
    approved_pending_apply?: number;
    error?: string | null;
    updated_at?: string | null;
  };
  baseline?: {
    loaded?: boolean;
    versions?: { manual_label: string; version: string; page_count: number }[];
    refs_count?: number;
    total_pages?: number;
  };
};
type PgVersion = {
  version: string;
  detected_at?: string | null;
  changed_page_count?: number;
  candidate_count?: number;
  status?: string | null;
  label_timestamps?: Record<string, string>;
};
type PgChangedPage = {
  manual_label?: string; change_type?: string;
  baseline_page?: number | null; new_page?: number | null;
  similarity?: number | null; new_snippet?: string; baseline_snippet?: string;
};
type PgCandidate = {
  row_id: string; item_index?: number | null; manual_label?: string;
  old_page_from?: number | null; old_page_to?: number | null;
  candidate_page_from?: number | null; candidate_page_to?: number | null;
  reason?: string; change_type?: string; confidence?: string; action?: string;
  match_text?: string; new_snippet?: string; detailed_code?: string; business_name?: string;
  change_kind?: "new" | "page_moved" | "text_changed" | "uncertain" | "noop";
  needs_review?: boolean; similarity?: number | null; page_changed?: boolean; text_changed?: boolean;
  changed_detail?: { baseline_page?: number; new_page?: number; change_type?: string; similarity?: number | null; baseline_snippet?: string; new_snippet?: string }[];
};
type DiffSeg = { op: "equal" | "insert" | "delete"; text: string };
type PgCandidateDetail = {
  row_id: string; manual_label?: string; change_kind?: string; similarity?: number | null;
  existing: { title?: string; code?: string; page_from?: number | null; page_to?: number | null; manual_ref?: string; match_text?: string; text?: string };
  candidate: { code?: string; page_from?: number | null; page_to?: number | null; staging?: string; text?: string };
  changed_pages: { baseline_page?: number; new_page?: number; change_type?: string; similarity?: number | null; baseline_snippet?: string; new_snippet?: string; diff_segments?: DiffSeg[]; has_text_change?: boolean }[];
};
const CHANGE_KIND: Record<string, { label: string; color: string; bg: string }> = {
  new: { label: "신규", color: "#22543D", bg: "#C6F6D5" },
  page_moved: { label: "페이지 변경", color: "#744210", bg: "#FEEBC8" },
  text_changed: { label: "본문 변경", color: "#822727", bg: "#FED7D7" },
  uncertain: { label: "매칭 불확실", color: "#553C9A", bg: "#E9D8FD" },
  noop: { label: "실질 변경 없음", color: "#4A5568", bg: "#EDF2F7" },
};
// 검토 우선순위: 매칭불확실 > 본문변경 > 페이지변경 > 신규 > noop
const KIND_ORDER: Record<string, number> = { uncertain: 0, text_changed: 1, page_moved: 2, new: 3, noop: 9 };
type PgDecision = {
  row_id: string; decision?: string; decision_note?: string; reviewed?: boolean;
  reviewed_candidate_page?: number | null;
  manual_page_from?: number | null; manual_page_to?: number | null;
  applied?: boolean; source_version?: string | null; previous_version?: string | null;
  orphaned?: boolean; orphaned_at?: string | null;
  needs_recheck?: boolean; candidate_changed?: boolean; updated_at?: string | null;
  reviewer_baseline_from?: number | null; reviewer_baseline_to?: number | null;
  reviewer_candidate_from?: number | null; reviewer_candidate_to?: number | null;
  reviewer_override_reason?: string | null; reviewer_override_by?: string | null;
};
type RecompareResp = { existing_text?: string; candidate_text?: string; candidate_partial?: boolean; diff_segments?: DiffSeg[]; has_text_change?: boolean };
type PdfStatus = {
  manual: string; kr_label?: string; viewer_source: string; viewer_file: string; staging_pdf_exists: boolean;
  deployed: { filename: string; exists: boolean; mtime?: string | null; page_count?: number | null };
  generator_present: boolean; source_hwp_present: boolean; replace_pipeline_wired: boolean;
  can_refresh_now: boolean; reason: string;
  artifacts?: { total?: number; generated?: number; promoted?: number; failed?: number };
  artifacts_total?: number; full_pdf_artifact?: { id: number } | null;
};

const PG_STATUS_KR: Record<string, string> = {
  never_run: "실행 이력 없음",
  no_change: "변경 없음",
  staged: "검토 대기 (staged)",
  running: "실행 중",
  error: "오류",
  pg_disabled: "PG 비활성",
};

// UI 결정 키 → 한글 라벨 (백엔드가 vocabulary 로 매핑)
const DEC_UI_KR: Record<string, string> = {
  approve: "승인", keep_existing: "기존 유지", hold: "보류", reject: "제외", manual_page: "직접입력",
};
// 저장된 decision(vocabulary) → 배지 표시
const DEC_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  "": { label: "미검토", color: "#975A16", bg: "#FEFCBF" },
  NEW_CANDIDATE: { label: "미검토", color: "#975A16", bg: "#FEFCBF" },
  UNRESOLVED: { label: "보류", color: "#744210", bg: "#FAF089" },
  REVIEWED_APPROVE_CANDIDATE: { label: "승인", color: "#22543D", bg: "#C6F6D5" },
  REVIEWED_KEEP_EXISTING: { label: "기존 유지", color: "#2A4365", bg: "#BEE3F8" },
  REJECTED_BAD_CANDIDATE: { label: "제외", color: "#822727", bg: "#FED7D7" },
  NEEDS_MANUAL_PAGE: { label: "직접입력", color: "#22543D", bg: "#C6F6D5" },
  APPLIED: { label: "운영반영됨", color: "#FFFFFF", bg: "#38A169" },
};
const DEC_APPLYABLE = new Set(["REVIEWED_APPROVE_CANDIDATE", "NEEDS_MANUAL_PAGE"]);

// 후보 상세 — 3단 비교(기존 / 차이 / 후보) + 본문 diff + 수동 페이지 지정 + PDF
function CandidateDetailView({ d, version, cand, decision, onOpenPdf, onOpenCandidatePdf, onOverrideChanged }: {
  d: PgCandidateDetail; version: string; cand: PgCandidate; decision?: PgDecision;
  onOpenPdf: (manual: string, page: number) => void;
  onOpenCandidatePdf: (rowId: string, manual: string, fallbackPage: number) => void;
  onOverrideChanged: () => void;
}) {
  const [showFull, setShowFull] = useState(false);
  const [bf, setBf] = useState(String(decision?.reviewer_baseline_from ?? cand.old_page_from ?? ""));
  const [bt, setBt] = useState(String(decision?.reviewer_baseline_to ?? cand.old_page_to ?? ""));
  const [cf, setCf] = useState(String(decision?.reviewer_candidate_from ?? cand.candidate_page_from ?? ""));
  const [ct, setCt] = useState(String(decision?.reviewer_candidate_to ?? cand.candidate_page_to ?? ""));
  const [reason, setReason] = useState(decision?.reviewer_override_reason ?? "");
  const [recmp, setRecmp] = useState<RecompareResp | null>(null);
  const [busy, setBusy] = useState(false);
  const hasOverride = decision?.reviewer_baseline_from != null || decision?.reviewer_candidate_from != null;
  const manual = cand.manual_label || d.manual_label || "visa";
  const LIMIT = 800;
  const clip = (t?: string) => { const s = t || ""; return (showFull || s.length <= LIMIT) ? s : s.slice(0, LIMIT) + " …"; };
  const err = (e: unknown, fb: string) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fb;

  // 표시 텍스트/diff: 재비교 결과가 있으면 그 값을, 없으면 원본 detail 값.
  const existingText = recmp ? (recmp.existing_text ?? "") : (d.existing.text ?? "");
  const candidateText = recmp ? (recmp.candidate_text ?? "") : (d.candidate.text ?? "");
  const col: React.CSSProperties = { flex: 1, minWidth: 220, background: "#fff", border: "1px solid #E2E8F0", borderRadius: 6, padding: 8 };
  const head: React.CSSProperties = { fontSize: 11, fontWeight: 700, marginBottom: 4 };
  const body: React.CSSProperties = { fontSize: 11, color: "#4A5568", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5, maxHeight: 320, overflow: "auto" };

  const doRecompare = async () => {
    setBusy(true);
    try {
      const r = await api.get(`/api/guidelines/manual-update/recompare`, { params: {
        version, label: manual, baseline_from: Number(bf) || 0, baseline_to: Number(bt) || Number(bf) || 0,
        candidate_from: Number(cf) || 0, candidate_to: Number(ct) || Number(cf) || 0 } });
      setRecmp(r.data as RecompareResp);
      toast.success("재추출·재비교 완료");
    } catch (e) { toast.error(err(e, "재비교 실패")); }
    finally { setBusy(false); }
  };
  const saveOverride = async () => {
    setBusy(true);
    try {
      await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(cand.row_id)}/override`, {
        baseline_from: Number(bf) || null, baseline_to: Number(bt) || null,
        candidate_from: Number(cf) || null, candidate_to: Number(ct) || null, reason });
      toast.success("관리자 지정 페이지 저장됨");
      onOverrideChanged();
    } catch (e) { toast.error(err(e, "저장 실패")); }
    finally { setBusy(false); }
  };
  const clearOverride = async () => {
    setBusy(true);
    try {
      await api.delete(`/api/guidelines/manual-update/decisions/${encodeURIComponent(cand.row_id)}/override`);
      setBf(String(cand.old_page_from ?? "")); setBt(String(cand.old_page_to ?? ""));
      setCf(String(cand.candidate_page_from ?? "")); setCt(String(cand.candidate_page_to ?? "")); setReason(""); setRecmp(null);
      toast.success("override 초기화됨");
      onOverrideChanged();
    } catch (e) { toast.error(err(e, "초기화 실패")); }
    finally { setBusy(false); }
  };

  const diffSegs = recmp ? (recmp.diff_segments ?? []) : null;

  return (
    <div>
      {/* PDF + 자동/관리자 페이지 요약 바 */}
      <div className="flex items-center gap-2 flex-wrap mb-2 text-[11px]">
        <span style={{ color: "#718096" }}>자동: 기준 {cand.old_page_from}-{cand.old_page_to} / 후보 {cand.candidate_page_from}-{cand.candidate_page_to}</span>
        {hasOverride && <span style={{ color: "#C05621", fontWeight: 700 }}>· 관리자 지정: 기준 {decision?.reviewer_baseline_from}-{decision?.reviewer_baseline_to} / 후보 {decision?.reviewer_candidate_from}-{decision?.reviewer_candidate_to}</span>}
        <span style={{ color: "#CBD5E0" }}>|</span>
        <button onClick={() => onOpenCandidatePdf(cand.row_id, manual, Number(cf) || cand.candidate_page_from || 1)}
          title="변경 페이지 PDF artifact 우선, 없으면 배포본 fallback" className="px-2 py-0.5 rounded font-bold" style={{ background: "#C6F6D5", color: "#22543D", border: "1px solid #9AE6B4" }}>변경 페이지 PDF 보기</button>
        <button onClick={() => onOpenPdf(manual, Number(cf) || cand.candidate_page_from || 1)} className="px-2 py-0.5 rounded" style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>최신/배포 전체 PDF</button>
        <button onClick={() => onOpenPdf(manual, cand.candidate_page_from || 1)} className="px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#4A5568" }}>후보 페이지 열기</button>
        <button onClick={() => onOpenPdf(manual, cand.old_page_from || 1)} className="px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#4A5568" }}>기존 페이지 열기</button>
      </div>

      {/* 수동 페이지 지정 */}
      <div className="flex items-center gap-2 flex-wrap mb-2 p-2 rounded" style={{ background: "#FFFBEB", border: "1px solid #FDE68A" }}>
        <span className="text-[11px] font-bold" style={{ color: "#92400E" }}>수동 페이지 지정</span>
        <span className="text-[11px]" style={{ color: "#718096" }}>기준</span>
        <input value={bf} onChange={(e) => setBf(e.target.value)} className="hw-input" style={{ width: 48 }} />
        <span>-</span>
        <input value={bt} onChange={(e) => setBt(e.target.value)} className="hw-input" style={{ width: 48 }} />
        <span className="text-[11px]" style={{ color: "#718096" }}>후보</span>
        <input value={cf} onChange={(e) => setCf(e.target.value)} className="hw-input" style={{ width: 48 }} />
        <span>-</span>
        <input value={ct} onChange={(e) => setCt(e.target.value)} className="hw-input" style={{ width: 48 }} />
        <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="사유 (예: 자동매칭 오류, 실제 p.40)" className="hw-input" style={{ flex: 1, minWidth: 160 }} />
        <button disabled={busy} onClick={() => void doRecompare()} className="text-[11px] px-2 py-1 rounded" style={{ background: "#2B6CB0", color: "#fff", border: "none" }}>다시 비교</button>
        <button disabled={busy} onClick={() => void saveOverride()} className="text-[11px] px-2 py-1 rounded" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>페이지 저장</button>
        <button disabled={busy} onClick={() => void clearOverride()} className="text-[11px] px-2 py-1 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>초기화</button>
      </div>
      {recmp?.candidate_partial && <div className="text-[10px] mb-2" style={{ color: "#C05621" }}>※ 후보(신규) 본문은 변경 페이지 스니펫 기반입니다(전체 본문 미보유) — 정확한 페이지는 PDF로 확인하세요.</div>}

      <div className="flex gap-2 flex-wrap" style={{ alignItems: "stretch" }}>
        {/* 왼쪽: 기존 */}
        <div style={col}>
          <div style={{ ...head, color: "#2A4365" }}>기존 기준 항목{recmp ? " (재추출)" : ""}</div>
          <div style={{ fontSize: 11, color: "#718096" }}>제목: {d.existing.title || "-"}</div>
          <div style={{ fontSize: 11, color: "#718096" }}>코드: {d.existing.code || "-"} · manual_ref {d.existing.manual_ref}</div>
          {d.existing.match_text && <div style={{ fontSize: 10, color: "#A0AEC0", marginTop: 2 }}>match_text: {d.existing.match_text}</div>}
          <div style={{ ...body, marginTop: 6 }}>{clip(existingText) || <span style={{ color: "#CBD5E0" }}>(추출 텍스트 없음)</span>}</div>
        </div>
        {/* 가운데: 차이 */}
        <div style={{ ...col, maxWidth: 360 }}>
          <div style={{ ...head, color: "#822727" }}>차이{recmp ? " (재계산)" : ""}</div>
          <div style={body}>
            {diffSegs ? (
              diffSegs.length === 0 ? <span style={{ color: "#276749" }}>실질 변경 없음</span> :
              diffSegs.map((seg, j) => (
                <span key={j} style={{ background: seg.op === "insert" ? "#C6F6D5" : seg.op === "delete" ? "#FED7D7" : "transparent", color: seg.op === "delete" ? "#822727" : seg.op === "insert" ? "#22543D" : "#4A5568", textDecoration: seg.op === "delete" ? "line-through" : "none" }}>{seg.text}</span>
              ))
            ) : (
              <>
                {(d.changed_pages || []).map((cp, i) => (
                  <div key={i} style={{ marginBottom: 6 }}>
                    <div style={{ color: "#A0AEC0", fontSize: 10 }}>p.{cp.baseline_page}→{cp.new_page} ({cp.change_type}{cp.similarity != null ? `, ${Math.round(cp.similarity * 100)}%` : ""})</div>
                    <div>{(cp.diff_segments || []).map((seg, j) => (
                      <span key={j} style={{ background: seg.op === "insert" ? "#C6F6D5" : seg.op === "delete" ? "#FED7D7" : "transparent", color: seg.op === "delete" ? "#822727" : seg.op === "insert" ? "#22543D" : "#4A5568", textDecoration: seg.op === "delete" ? "line-through" : "none" }}>{seg.text}</span>
                    ))}</div>
                  </div>
                ))}
                {(d.changed_pages || []).length === 0 && <span style={{ color: "#CBD5E0" }}>(변경 페이지 정보 없음)</span>}
              </>
            )}
          </div>
        </div>
        {/* 오른쪽: 후보 */}
        <div style={col}>
          <div style={{ ...head, color: "#22543D" }}>후보 항목 (staging){recmp ? " (재추출)" : ""}</div>
          <div style={{ fontSize: 11, color: "#718096" }}>코드: {d.candidate.code || "-"} · staging {d.candidate.staging}</div>
          <div style={{ ...body, marginTop: 6 }}>{clip(candidateText) || <span style={{ color: "#CBD5E0" }}>(추출 텍스트 없음 — PDF로 확인)</span>}</div>
        </div>
      </div>
      {((existingText || "").length > LIMIT || (candidateText || "").length > LIMIT) && (
        <button onClick={() => setShowFull((v) => !v)} className="text-[11px] mt-2 px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#2B6CB0", background: "#fff" }}>
          {showFull ? "접기" : "전체 보기"}
        </button>
      )}
    </div>
  );
}

function ManualUpdatePgView({ state }: { state: PgStateResp | null }) {
  const [versions, setVersions] = useState<PgVersion[]>([]);
  const [version, setVersion] = useState<string>("");
  const [changed, setChanged] = useState<PgChangedPage[]>([]);
  const [candidates, setCandidates] = useState<PgCandidate[]>([]);
  const [decisions, setDecisions] = useState<PgDecision[]>([]);
  const [loading, setLoading] = useState(false);
  // 상태 카드는 결정/반영 후 다시 갱신해야 하므로 prop(state)을 로컬로 복제해 둔다.
  const [liveState, setLiveState] = useState<PgStateResp | null>(state);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);              // 진행 중 row_id 또는 "bulk"
  const [applyModal, setApplyModal] = useState<{ rowId: string; pf: string; pt: string } | null>(null);
  const [filter, setFilter] = useState<string>("review");             // 기본: 미검토 + 실질 변경 있음
  const [expanded, setExpanded] = useState<string | null>(null);      // 펼친 후보 row_id
  const [detailCache, setDetailCache] = useState<Record<string, PgCandidateDetail>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const [bulkApply, setBulkApply] = useState(false);                  // 운영 반영 요약 모달
  const [pdfView, setPdfView] = useState<{ manual?: string; page: number; isStaging?: boolean; artifactId?: number; label?: string } | null>(null);
  const [pdfStatus, setPdfStatus] = useState<Record<string, PdfStatus>>({});
  const [runCap, setRunCap] = useState<{ can_diagnose?: boolean; can_record_update?: boolean; can_generate_pdf?: boolean; node_available?: boolean; extract_mjs_exists?: boolean; rhwp_available?: boolean; runtime?: string; reason?: string } | null>(null);
  const [runBusy, setRunBusy] = useState<"diagnose" | "record" | "generate_pdf_artifacts" | null>(null);
  const [runResult, setRunResult] = useState<{ mode?: string; result?: { status?: string; version?: string; source_deleted?: boolean; wrote_to_pg?: boolean; stages?: Record<string, unknown>; error?: string; error_stage?: string } } | null>(null);
  // row_id → artifact id (해당 후보에 생성된 변경 페이지 PDF artifact). note "candidate <row_id>" 로 매칭.
  const [artifactByRow, setArtifactByRow] = useState<Record<string, number>>({});

  const token = (typeof window !== "undefined" ? localStorage.getItem("access_token") || "" : "");
  // PDF 열기: staging 있으면 staging, 없으면 배포본 (백엔드가 자동 선택). 배너용으로 source 조회.
  const openPdf = useCallback(async (manual: string, page: number) => {
    let isStaging = false;
    try {
      const r = await api.get(`/api/guidelines/manual-update/pdf-source`, { params: { manual, version } });
      isStaging = !!r.data?.is_staging;
    } catch { /* 기본 deployed */ }
    setPdfView({ manual, page: page || 1, isStaging });
  }, [version]);

  // 후보 상세: 변경 페이지 artifact 우선 → 있으면 artifact PDF, 없으면 배포본 fallback.
  const openCandidatePdf = useCallback(async (rowId: string, manual: string, fallbackPage: number) => {
    try {
      const r = await api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(version)}/candidates/${encodeURIComponent(rowId)}/pdf-artifact`);
      if (r.data?.artifact_id) {
        setPdfView({ artifactId: r.data.artifact_id, page: 1, label: `변경 페이지 artifact #${r.data.artifact_id} (p.${r.data.page_from}-${r.data.page_to})` });
        return;
      }
      toast.message("변경 페이지 artifact 없음 — 배포본 PDF로 엽니다.");
    } catch { toast.message("artifact 조회 실패 — 배포본 PDF로 엽니다."); }
    void openPdf(manual, fallbackPage);
  }, [version, openPdf]);

  const loadCapability = useCallback(async () => {
    try {
      const r = await api.get(`/api/guidelines/manual-update/capabilities`);
      setRunCap(r.data);
    } catch { /* skip */ }
  }, []);
  useEffect(() => { void loadCapability(); }, [loadCapability]);

  // 관리자 수동 실행: diagnose(진단, PG 미기록) | record(실제 기록, capability 통과 시).
  const runNow = useCallback(async (mode: "diagnose" | "record" | "generate_pdf_artifacts") => {
    if (mode === "record" && !window.confirm("실제 업데이트를 실행합니다(PG staging 기록). 계속할까요?")) return;
    if (mode === "generate_pdf_artifacts" && !window.confirm("변경 페이지 PDF artifact를 생성합니다(node+chromium 필요). 계속할까요?")) return;
    setRunBusy(mode); setRunResult(null);
    try {
      const r = await api.post(`/api/guidelines/manual-update/run-now`, { mode });
      setRunResult(r.data);
      toast.success(`${mode === "diagnose" ? "진단" : "실제"} 실행 완료: ${r.data?.result?.status}`);
      void loadCapability();
    } catch (e) {
      const det = (e as { response?: { status?: number } })?.response;
      if (det?.status === 409) toast.error("실행 차단(409): 이미 실행 중이거나 실행 불가 환경입니다.");
      else toast.error("실행 실패");
    } finally { setRunBusy(null); }
  }, [loadCapability]);

  const reloadState = useCallback(async () => {
    try {
      const r = await api.get("/api/guidelines/manual-update/state");
      setLiveState(r.data as PgStateResp);
    } catch { /* 상태 갱신 실패는 치명적이지 않음 */ }
  }, []);

  const loadTop = useCallback(async () => {
    try {
      const [vr, dr] = await Promise.all([
        api.get("/api/guidelines/manual-update/versions"),
        api.get("/api/guidelines/manual-update/decisions/active"),
      ]);
      const vs = (vr.data?.versions ?? []) as PgVersion[];
      setVersions(vs);
      setDecisions((dr.data?.rows ?? []) as PgDecision[]);
      if (vs.length) setVersion((cur) => cur || vs[0].version);
      void reloadState();
    } catch { toast.error("PG manual update 자료를 불러오지 못했습니다."); }
  }, [reloadState]);

  useEffect(() => { void loadTop(); }, [loadTop]);

  // 결정만 다시 불러오기(후보/버전 재조회 없이 빠르게).
  const reloadDecisions = useCallback(async () => {
    try {
      const dr = await api.get("/api/guidelines/manual-update/decisions/active");
      setDecisions((dr.data?.rows ?? []) as PgDecision[]);
    } catch { /* ignore */ }
    void reloadState();
  }, [reloadState]);

  const errText = (e: unknown, fb: string) =>
    (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fb;

  // 단일 결정 저장(승인/기존유지/보류/제외). 승인 시 후보 페이지는 백엔드가 자동 채움.
  const setDecision = useCallback(async (c: PgCandidate, ui: string) => {
    setBusy(c.row_id);
    try {
      await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(c.row_id)}`, {
        decision: ui,
        candidate_page_from: c.candidate_page_from ?? undefined,
        candidate_page_to: c.candidate_page_to ?? undefined,
      });
      toast.success(`결정 저장: ${DEC_UI_KR[ui] ?? ui}`);
      await reloadDecisions();
    } catch (e) { toast.error(errText(e, "결정 저장 실패")); }
    finally { setBusy(null); }
  }, [reloadDecisions]);

  // 일괄 결정(선택 또는 전체).
  const bulkDecision = useCallback(async (ui: string, rowIds: string[]) => {
    if (rowIds.length === 0) { toast.message("선택된 후보가 없습니다."); return; }
    setBusy("bulk");
    try {
      const r = await api.post("/api/guidelines/manual-update/decisions/bulk", { row_ids: rowIds, decision: ui });
      toast.success(`${DEC_UI_KR[ui] ?? ui} ${r.data?.count ?? rowIds.length}건 저장`);
      setSelected(new Set());
      await reloadDecisions();
    } catch (e) { toast.error(errText(e, "일괄 처리 실패")); }
    finally { setBusy(null); }
  }, [reloadDecisions]);

  // 운영 반영(확인 모달에서 호출).
  const doApply = useCallback(async () => {
    if (!applyModal) return;
    const pf = parseInt(applyModal.pf, 10);
    const pt = parseInt(applyModal.pt, 10) || pf;
    if (!(pf >= 1)) { toast.error("page_from은 1 이상이어야 합니다."); return; }
    setBusy(applyModal.rowId);
    try {
      const r = await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(applyModal.rowId)}/apply`, { page_from: pf, page_to: pt });
      toast.success(`운영 반영 완료 (백업: ${r.data?.backup ?? "-"})`);
      setApplyModal(null);
      await reloadDecisions();
    } catch (e) { toast.error(errText(e, "운영 반영 실패")); }
    finally { setBusy(null); }
  }, [applyModal, reloadDecisions]);

  // 행 펼침 → 상세(3단 비교) 로드(캐시).
  const toggleExpand = useCallback(async (c: PgCandidate) => {
    if (expanded === c.row_id) { setExpanded(null); return; }
    setExpanded(c.row_id);
    if (detailCache[c.row_id] || !version) return;
    setDetailLoading(c.row_id);
    try {
      const r = await api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(version)}/candidates/${encodeURIComponent(c.row_id)}/detail`);
      setDetailCache((prev) => ({ ...prev, [c.row_id]: r.data as PgCandidateDetail }));
    } catch (e) { toast.error(errText(e, "상세를 불러오지 못했습니다.")); }
    finally { setDetailLoading(null); }
  }, [expanded, detailCache, version]);

  // 운영 반영 일괄: 승인(approve/manual_page)했으나 아직 미반영인 후보 전부 반영.
  const doBulkApply = useCallback(async () => {
    const dmap: Record<string, PgDecision> = {};
    for (const d of decisions) dmap[d.row_id] = d;
    const targets = candidates.filter((c) => {
      const d = dmap[c.row_id];
      return d && !d.applied && DEC_APPLYABLE.has(d.decision ?? "");
    });
    if (targets.length === 0) { toast.message("운영 반영할 승인 항목이 없습니다."); setBulkApply(false); return; }
    setBusy("bulk");
    let ok = 0;
    for (const c of targets) {
      const dd = dmap[c.row_id];
      // 관리자 지정(override)이 있으면 그 페이지로 반영, 없으면 자동 후보 페이지.
      const pf = dd?.reviewer_candidate_from ?? c.candidate_page_from ?? 1;
      const pt = dd?.reviewer_candidate_to ?? c.candidate_page_to ?? pf;
      try {
        await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(c.row_id)}/apply`, {
          page_from: pf, page_to: pt,
        });
        ok += 1;
      } catch { /* 개별 실패는 계속 */ }
    }
    toast.success(`운영 반영 ${ok}/${targets.length}건 완료`);
    setBulkApply(false); setBusy(null);
    await reloadDecisions();
  }, [candidates, decisions, reloadDecisions]);

  const loadVersion = useCallback(async (v: string) => {
    if (!v) return;
    setLoading(true); setChanged([]); setCandidates([]); setExpanded(null); setDetailCache({});
    try {
      const [ch, ca] = await Promise.all([
        api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(v)}/changed-pages`),
        api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(v)}/candidates`),
      ]);
      setChanged((ch.data?.rows ?? []) as PgChangedPage[]);
      setCandidates((ca.data?.rows ?? []) as PgCandidate[]);
    } catch { toast.error("버전 자료를 불러오지 못했습니다."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (version) void loadVersion(version); }, [version, loadVersion]);

  // 후보별 PDF artifact 매핑(version 단위) — note "candidate <row_id>" 파싱.
  useEffect(() => {
    if (!version) { setArtifactByRow({}); return; }
    (async () => {
      try {
        const r = await api.get(`/api/guidelines/manual-update/pdf-artifacts`, { params: { version } });
        const map: Record<string, number> = {};
        for (const a of (r.data?.rows ?? []) as { id: number; note?: string }[]) {
          const m = /candidate\s+(\S+)/.exec(a.note || "");
          if (m) map[m[1]] = a.id;
        }
        setArtifactByRow(map);
      } catch { setArtifactByRow({}); }
    })();
  }, [version, runResult]);

  // PDF 최신화 진단(visa/stay) — 뷰어가 여는 파일/소스/파이프라인 연결 상태.
  useEffect(() => {
    (async () => {
      const out: Record<string, PdfStatus> = {};
      for (const m of ["visa", "stay"]) {
        try {
          const r = await api.get(`/api/guidelines/manual-update/pdf-status`, { params: { manual: m, version } });
          out[m] = r.data as PdfStatus;
        } catch { /* skip */ }
      }
      setPdfStatus(out);
    })();
  }, [version]);

  const s = liveState?.state ?? {};
  const bl = liveState?.baseline ?? {};
  const blVersions = bl.versions ?? [];
  // row_id → 저장된 decision (후보 행에 현재 결정/배지/반영버튼 표시)
  const decByRow: Record<string, PgDecision> = {};
  for (const d of decisions) decByRow[d.row_id] = d;

  // 필터 + 정렬 + 코드 그룹핑
  const matchFilter = (c: PgCandidate): boolean => {
    const dec = decByRow[c.row_id]?.decision ?? "";
    const kind = c.change_kind ?? "text_changed";
    const decided = dec && dec !== "NEW_CANDIDATE";
    switch (filter) {
      case "all": return true;
      case "review": return c.needs_review !== false && !decided;   // 미검토 + 실질 변경 있음 (기본)
      case "unreviewed": return !decided;
      case "page_moved": return kind === "page_moved";
      case "text_changed": return kind === "text_changed";
      case "uncertain": return kind === "uncertain";
      case "new": return kind === "new";
      case "noop": return c.needs_review === false;
      case "has_pdf": return !!artifactByRow[c.row_id];
      case "approve": return dec === "REVIEWED_APPROVE_CANDIDATE";
      case "keep_existing": return dec === "REVIEWED_KEEP_EXISTING";
      case "hold": return dec === "UNRESOLVED";
      case "reject": return dec === "REJECTED_BAD_CANDIDATE";
      default: return true;
    }
  };
  const filteredCands = candidates.filter(matchFilter).sort((a, b) => {
    const ka = KIND_ORDER[a.change_kind ?? "text_changed"] ?? 5;
    const kb = KIND_ORDER[b.change_kind ?? "text_changed"] ?? 5;
    if (ka !== kb) return ka - kb;
    const ga = (a.detailed_code || a.row_id), gb = (b.detailed_code || b.row_id);
    return ga.localeCompare(gb);   // 같은 코드/업무명 묶음
  });
  const FILTERS: [string, string][] = [
    ["review", "검토 대상"], ["unreviewed", "미검토"], ["text_changed", "본문 변경"],
    ["page_moved", "페이지 변경"], ["uncertain", "매칭 불확실"], ["new", "신규"],
    ["noop", "실질 변경 없음"], ["has_pdf", "PDF 있음"], ["approve", "승인"], ["keep_existing", "기존유지"],
    ["hold", "보류"], ["reject", "제외"], ["all", "전체"],
  ];
  const filterCount = (f: string) => candidates.filter((c) => {
    const saved = filter; let r: boolean;
    // 임시로 평가(간단히 재사용): 동일 로직
    const dec = decByRow[c.row_id]?.decision ?? "";
    const kind = c.change_kind ?? "text_changed";
    const decided = dec && dec !== "NEW_CANDIDATE";
    switch (f) {
      case "all": r = true; break;
      case "review": r = c.needs_review !== false && !decided; break;
      case "unreviewed": r = !decided; break;
      case "page_moved": r = kind === "page_moved"; break;
      case "text_changed": r = kind === "text_changed"; break;
      case "uncertain": r = kind === "uncertain"; break;
      case "new": r = kind === "new"; break;
      case "noop": r = c.needs_review === false; break;
      case "has_pdf": r = !!artifactByRow[c.row_id]; break;
      case "approve": r = dec === "REVIEWED_APPROVE_CANDIDATE"; break;
      case "keep_existing": r = dec === "REVIEWED_KEEP_EXISTING"; break;
      case "hold": r = dec === "UNRESOLVED"; break;
      case "reject": r = dec === "REJECTED_BAD_CANDIDATE"; break;
      default: r = true;
    }
    void saved; return r;
  }).length;
  // 운영 반영 요약(모달용)
  const applySummary = (() => {
    let approve = 0, keep = 0, hold = 0, reject = 0, applyable = 0, noop = 0, applied = 0;
    for (const c of candidates) {
      if (c.needs_review === false) noop++;
      const d = decByRow[c.row_id];
      const dk = d?.decision ?? "";
      if (d?.applied) { applied++; }
      if (dk === "REVIEWED_APPROVE_CANDIDATE" || dk === "NEEDS_MANUAL_PAGE") { approve++; if (!d?.applied) applyable++; }
      else if (dk === "REVIEWED_KEEP_EXISTING") keep++;
      else if (dk === "UNRESOLVED") hold++;
      else if (dk === "REJECTED_BAD_CANDIDATE") reject++;
    }
    return { approve, keep, hold, reject, applyable, noop, applied };
  })();

  return (
    <div className="space-y-4">
      {/* 안내 배너 — PG 단일 출처 */}
      <div className="hw-card text-xs leading-relaxed" style={{ background: "#EBF8FF", borderColor: "#BEE3F8" }}>
        <div style={{ color: "#2B6CB0", fontWeight: 700 }}>🗄 PostgreSQL 기반 매뉴얼 업데이트 (단일 출처 · 검토/운영반영 가능)</div>
        <div style={{ color: "#4A5568", marginTop: 4 }}>변경 감지·후보·검토 결정이 PG에 저장됩니다. 후보별 승인/기존유지/보류/제외 후, ‘운영 반영’ 버튼으로만 실무지침에 반영됩니다.</div>
        <div style={{ color: "#C53030", marginTop: 2 }}>운영 manual_ref는 관리자가 ‘운영 반영’을 누르기 전에는 절대 변경되지 않습니다(자동 반영 없음).</div>
      </div>

      {/* 상태 카드 */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>자동화 상태</div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-xs">
          {[
            ["원문 변경", (s.changed_count ?? 0) > 0 ? `있음 (${s.changed_count}p)` : "없음"],
            ["후보", `${s.candidate_count ?? 0}건 (검토대상 ${s.review_target_count ?? 0} · no-op ${s.noop_count ?? 0})`],
            ["실질 검토 필요", s.needs_review ? `예 ⚠ (미검토 ${s.pending_count ?? 0})` : "없음"],
            ["운영 반영 대기", `${s.approved_pending_apply ?? 0}건 (반영 완료 ${s.applied_count ?? 0})`],
            ["최근 staging 버전", s.last_staging_version ?? "-"],
            ["오류", s.error ?? "-"],
          ].map(([k, v]) => (
            <div key={k as string}>
              <div style={{ color: "#A0AEC0" }}>{k}</div>
              <div style={{ color: "#2D3748", fontWeight: 600, wordBreak: "break-all" }}>{v as string}</div>
            </div>
          ))}
        </div>
        {/* 검토 필요 사유 — req 6/7/8: 예이면 사유/후보가 반드시 보이도록 */}
        {(s.review_reason || s.needs_review) && (
          <div className="text-xs mt-2 px-2 py-1.5 rounded"
            style={{ background: s.needs_review ? "#FFFAF0" : "#F0FFF4", color: s.needs_review ? "#C05621" : "#276749", border: `1px solid ${s.needs_review ? "#FEEBC8" : "#C6F6D5"}` }}>
            {s.needs_review ? "⚠ " : "✓ "}{s.review_reason || (s.needs_review ? "검토 필요" : "검토 완료")}
          </div>
        )}
      </div>

      {/* baseline 요약 */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>
          기준 DB (baseline) {bl.loaded ? "✅ 적재됨" : "⚠ 미적재"}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          {blVersions.map((v) => (
            <div key={v.manual_label}>
              <div style={{ color: "#A0AEC0" }}>{v.manual_label} (v{v.version})</div>
              <div style={{ color: "#2D3748", fontWeight: 600 }}>{v.page_count} pages</div>
            </div>
          ))}
          <div>
            <div style={{ color: "#A0AEC0" }}>manual_base_refs</div>
            <div style={{ color: "#2D3748", fontWeight: 600 }}>{bl.refs_count ?? 0} rows</div>
          </div>
        </div>
      </div>

      {/* 매뉴얼 최신화 수동 실행 (진단 / 실제) */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>매뉴얼 최신화 실행</div>
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <button disabled={runBusy !== null} onClick={() => void runNow("diagnose")}
            className="text-xs px-3 py-1.5 rounded" style={{ background: "#2B6CB0", color: "#fff", border: "none" }}>
            {runBusy === "diagnose" ? "진단 중..." : "최신 매뉴얼 진단 실행"}
          </button>
          <button disabled={runBusy !== null || !runCap?.can_record_update}
            title={runCap?.can_record_update ? "실제 업데이트(PG 기록) 실행" : (runCap?.reason || "실행 불가")}
            onClick={() => void runNow("record")}
            className="text-xs px-3 py-1.5 rounded"
            style={{ background: runCap?.can_record_update ? "#DD6B20" : "#E2E8F0", color: runCap?.can_record_update ? "#fff" : "#A0AEC0", border: "none", cursor: runCap?.can_record_update ? "pointer" : "not-allowed" }}>
            {runBusy === "record" ? "실행 중..." : "실제 업데이트 실행"}
          </button>
          <button disabled={runBusy !== null || !runCap?.can_generate_pdf}
            title={runCap?.can_generate_pdf ? "변경 페이지 PDF artifact 생성(node+chromium)" : "node/chromium 실행 환경 없음 — 로컬/워커에서만 생성"}
            onClick={() => void runNow("generate_pdf_artifacts")}
            className="text-xs px-3 py-1.5 rounded"
            style={{ background: runCap?.can_generate_pdf ? "#38A169" : "#E2E8F0", color: runCap?.can_generate_pdf ? "#fff" : "#A0AEC0", border: "none", cursor: runCap?.can_generate_pdf ? "pointer" : "not-allowed" }}>
            {runBusy === "generate_pdf_artifacts" ? "생성 중..." : "변경 페이지 PDF 생성"}
          </button>
          {runCap && (
            <span className="text-[11px]" style={{ color: "#718096" }}>
              런타임 {runCap.runtime} · node {runCap.node_available ? "✅" : "❌"} · rhwp {runCap.rhwp_available ? "✅" : "❌"} · 실제기록 {runCap.can_record_update ? "✅" : "❌"} · PDF생성 {runCap.can_generate_pdf ? "✅" : "❌"}
            </span>
          )}
        </div>
        {runCap && !runCap.can_record_update && (
          <div className="text-xs px-2 py-1.5 rounded" style={{ background: "#FFFAF0", color: "#C05621", border: "1px solid #FEEBC8" }}>
            ⚠ 현재 backend/Render 런타임에는 node/rhwp 실행 환경이 없어 <b>실제 업데이트 실행이 비활성화</b>되어 있습니다. 로컬 호스트 또는 별도 worker 실행 환경이 연결되면 활성화됩니다. (진단 실행은 가능 — 감지까지, 다운로드/추출은 node 가능 환경에서만 완주)
          </div>
        )}
        {runResult && (() => {
          const r = runResult.result || {}; const s = (r.stages || {}) as Record<string, unknown>;
          const dl = Array.isArray(s.downloaded) ? (s.downloaded as { name: string; bytes: number }[]) : [];
          const ep = (s.extracted_pages || {}) as Record<string, number>;
          const ch = Array.isArray(s.changed) ? s.changed.length : undefined;
          return (
            <div className="text-[11px] mt-2 p-2 rounded" style={{ background: "#F7FAFC", color: "#2D3748", lineHeight: 1.8 }}>
              <div><b>{runResult.mode === "diagnose" ? "진단" : "실제"} 실행 결과</b> — status=<b>{r.status}</b>{r.version && <> · version {r.version}</>}</div>
              <div>하이코리아 접속: {s.detail_fetch_bytes ? `성공(${String(s.detail_fetch_bytes)} bytes)` : "-"} · 첨부 탐지: {s.attachments_found != null ? String(s.attachments_found) : "-"}건{ch != null && <> · 변경 감지 {ch}건</>}</div>
              {dl.length > 0 && <div>다운로드: {dl.map((f) => `${f.name} (${Math.round(f.bytes / 1024)}KB)`).join(", ")}</div>}
              {s.tmp_dir != null && <div>/tmp 저장: {String(s.tmp_dir)}</div>}
              {Object.keys(ep).length > 0 && <div>rhwp 추출: {Object.entries(ep).map(([k, v]) => `${k} ${v}p`).join(", ")}</div>}
              {s.changed_pages != null && <div>baseline diff 변경 페이지: {String(s.changed_pages)} · 후보: {String(s.candidates ?? "-")}</div>}
              <div>PG staging 기록: <b style={{ color: r.wrote_to_pg ? "#C05621" : "#276749" }}>{r.wrote_to_pg ? "기록함(record)" : "미기록(diagnose)"}</b>{r.source_deleted != null && <> · 원본 삭제: {r.source_deleted ? "✅" : "❌"}</>}</div>
              {s.note != null && <div style={{ color: "#C05621" }}>{String(s.note)}</div>}
              {r.error != null && <div style={{ color: "#C53030" }}>오류[{r.error_stage}]: {r.error}</div>}
            </div>
          );
        })()}
      </div>

      {/* PDF 최신화 상태 (왜 배포본 PDF 가 보이는지 투명하게 — 미구현 숨김 금지) */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>PDF 최신화 상태</div>
        <div className="text-xs mb-2 px-2 py-1.5 rounded" style={{ background: "#FFFAF0", color: "#C05621", border: "1px solid #FEEBC8" }}>
          ⚠ 변경 페이지 → 전체 PDF 교체 파이프라인 <b>미연결</b>. 현재 “전체 PDF 보기”는 최신 staging PDF 가 없어
          <b> 배포본(현행 운영) PDF</b>로 표시됩니다. 텍스트 diff·후보 검토·페이지 override 는 정상 동작하나, PDF 자체 최신화는 다음 단계 구현 예정입니다.
        </div>
        <div className="overflow-x-auto">
          <table className="hw-table w-full text-xs" style={{ minWidth: 720 }}>
            <thead><tr>{["매뉴얼", "뷰어 소스", "여는 파일", "배포본 날짜", "배포본 페이지", "최신 staging PDF", "PDF artifact", "생성기", "교체 파이프라인"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {["visa", "stay"].map((m) => {
                const ps = pdfStatus[m];
                if (!ps) return <tr key={m}><td>{m}</td><td colSpan={8} style={{ color: "#A0AEC0" }}>조회 중…</td></tr>;
                const af = ps.artifacts || {};
                const vs = ps.viewer_source === "artifact" ? "artifact" : ps.viewer_source === "staging" ? "staging" : "배포본 fallback";
                return (
                  <tr key={m}>
                    <td>{m} ({ps.kr_label ?? ps.manual})</td>
                    <td><span style={{ fontWeight: 700, color: ps.viewer_source === "deployed" ? "#C05621" : "#22543D" }}>{vs}</span></td>
                    <td style={{ fontSize: 10 }}>{ps.viewer_file}</td>
                    <td>{ps.deployed?.mtime ?? "-"}</td>
                    <td>{ps.deployed?.page_count ?? "-"}p</td>
                    <td>{ps.staging_pdf_exists ? "있음 ✅" : "없음 ⚠"}</td>
                    <td>총 {af.total ?? 0} {ps.full_pdf_artifact ? "(full ✅)" : af.total ? "(changed)" : ""}</td>
                    <td>{ps.generator_present ? "설치됨" : "없음"}</td>
                    <td><span style={{ color: ps.replace_pipeline_wired ? "#22543D" : "#C53030", fontWeight: 700 }}>{ps.replace_pipeline_wired ? "연결됨" : "미구현"}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {(() => {
          const tot = (pdfStatus.visa?.artifacts_total ?? 0) + (pdfStatus.stay?.artifacts_total ?? 0);
          const anyFull = !!(pdfStatus.visa?.full_pdf_artifact || pdfStatus.stay?.full_pdf_artifact);
          if (tot === 0) return (
            <div className="text-xs mt-2 px-2 py-1.5 rounded" style={{ background: "#F7FAFC", color: "#718096" }}>
              현재 생성된 PDF artifact가 없습니다. viewer는 배포본 PDF fallback을 사용 중입니다.
            </div>
          );
          return (
            <div className="text-xs mt-2 px-2 py-1.5 rounded" style={{ background: "#F0FFF4", color: "#276749", border: "1px solid #C6F6D5" }}>
              PDF artifact {tot}건 저장됨{anyFull ? " — full_pdf artifact 있음(viewer 우선 사용)" : " (changed_page 검토용; viewer는 full_pdf artifact가 있어야 우선 사용)"}.
            </div>
          );
        })()}
      </div>

      {/* 버전 선택 */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs font-medium" style={{ color: "#718096" }}>업데이트 버전</span>
        <select className="hw-input text-xs" style={{ minWidth: 200 }} value={version}
          onChange={(e) => setVersion(e.target.value)}>
          {versions.length === 0 && <option value="">(버전 없음)</option>}
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              {v.version} · 변경 {v.changed_page_count ?? 0} · 후보 {v.candidate_count ?? 0}
            </option>
          ))}
        </select>
        <button onClick={() => void loadTop()}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border"
          style={{ borderColor: "#4299E1", color: "#2B6CB0", background: "#EBF8FF" }}>
          <RotateCcw size={12} /> 새로고침
        </button>
        {loading && <Loader2 size={14} className="animate-spin" style={{ color: "#A0AEC0" }} />}
      </div>

      {/* 버전 0건 안내 (정상) */}
      {versions.length === 0 && (
        <div className="hw-card text-sm" style={{ color: "#4A5568", lineHeight: 1.7 }}>
          <div style={{ fontWeight: 700, color: "#2D3748", marginBottom: 6 }}>
            기준 DB는 적재되었습니다. 아직 매뉴얼 변경 감지 실행 이력이 없습니다.
          </div>
          <div>매일 자동 감지(또는 수동 실행)가 변경을 발견하면 이 목록에 버전이 나타납니다.</div>
          <div style={{ color: "#276749" }}>기존 실무지침 PDF 조회는 정상 유지됩니다.</div>
        </div>
      )}

      {/* 변경 페이지 */}
      {version && (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="text-xs font-semibold px-3 py-2" style={{ color: "#2D3748", borderBottom: "1px solid #EDF2F7" }}>
            변경 페이지 ({changed.length})
          </div>
          <div className="overflow-x-auto">
            <table className="hw-table w-full text-xs" style={{ minWidth: 700 }}>
              <thead><tr>
                {["매뉴얼", "변경", "baseline p.", "new p.", "유사도", "new 스니펫"].map((h) => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {changed.length === 0 && <tr><td colSpan={6} style={{ color: "#A0AEC0", textAlign: "center", padding: 16 }}>변경 페이지 없음</td></tr>}
                {changed.map((c, i) => (
                  <tr key={i}>
                    <td>{c.manual_label}</td><td>{c.change_type}</td>
                    <td>{c.baseline_page ?? "-"}</td><td>{c.new_page ?? "-"}</td>
                    <td>{c.similarity ?? "-"}</td>
                    <td style={{ maxWidth: 320, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.new_snippet}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* manual_ref 후보 — 검토/승인/운영반영 */}
      {version && (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="px-3 py-2" style={{ borderBottom: "1px solid #EDF2F7" }}>
            <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
              <span className="text-xs font-semibold" style={{ color: "#2D3748" }}>
                영향 manual_ref 후보 — 표시 {filteredCands.length} / 전체 {candidates.length} · 선택 {selected.size}
              </span>
              <div className="flex items-center gap-1 flex-wrap">
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("approve", Array.from(selected))}
                  title="선택 후보를 운영 반영 대상으로 승인" className="text-[11px] px-2 py-1 rounded" style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>선택 승인</button>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("keep_existing", Array.from(selected))}
                  title="기존 manual_ref 유지" className="text-[11px] px-2 py-1 rounded" style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>선택 기존유지</button>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("hold", Array.from(selected))}
                  title="나중에 다시 검토" className="text-[11px] px-2 py-1 rounded" style={{ background: "#FFFFF0", color: "#975A16", border: "1px solid #FAF089" }}>선택 보류</button>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("reject", Array.from(selected))}
                  title="이번 후보에서 제외" className="text-[11px] px-2 py-1 rounded" style={{ background: "#FFF5F5", color: "#C53030", border: "1px solid #FED7D7" }}>선택 제외</button>
                <span style={{ color: "#CBD5E0" }}>|</span>
                <button disabled={busy === "bulk" || applySummary.applyable === 0} onClick={() => setBulkApply(true)}
                  title="승인 항목을 운영 실무지침에 반영" className="text-[11px] px-2 py-1 rounded font-bold" style={{ background: applySummary.applyable ? "#DD6B20" : "#E2E8F0", color: applySummary.applyable ? "#fff" : "#A0AEC0", border: "none" }}>
                  운영 반영 ({applySummary.applyable})
                </button>
              </div>
            </div>
            {/* 필터 칩 */}
            <div className="flex items-center gap-1 flex-wrap">
              {FILTERS.map(([f, label]) => (
                <button key={f} onClick={() => setFilter(f)}
                  className="text-[11px] px-2 py-0.5 rounded-full"
                  style={{ border: `1px solid ${filter === f ? "#2B6CB0" : "#E2E8F0"}`, background: filter === f ? "#2B6CB0" : "#fff", color: filter === f ? "#fff" : "#718096", fontWeight: filter === f ? 700 : 400 }}>
                  {label} {filterCount(f)}
                </button>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="hw-table w-full text-xs" style={{ minWidth: 1040 }}>
              <thead><tr>
                <th style={{ width: 24 }}>
                  <input type="checkbox" aria-label="전체 선택"
                    checked={filteredCands.length > 0 && filteredCands.every((c) => selected.has(c.row_id))}
                    onChange={(e) => setSelected(e.target.checked ? new Set(filteredCands.map((c) => c.row_id)) : new Set())} />
                </th>
                <th style={{ width: 24 }}></th>
                {["코드/업무명", "매뉴얼", "기존 p.", "후보 p.", "신뢰도", "변경 유형", "매칭 사유", "현재 결정", "결정", "운영 반영"].map((h) => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {filteredCands.length === 0 && <tr><td colSpan={12} style={{ color: "#A0AEC0", textAlign: "center", padding: 16 }}>해당 필터에 후보 없음</td></tr>}
                {filteredCands.map((c) => {
                  const dec = decByRow[c.row_id];
                  const decKey = dec?.decision ?? "";
                  const badge = DEC_BADGE[decKey] ?? DEC_BADGE[""];
                  const kind = CHANGE_KIND[c.change_kind ?? "text_changed"] ?? CHANGE_KIND.text_changed;
                  const applied = !!dec?.applied;
                  const canApply = !applied && DEC_APPLYABLE.has(decKey);
                  const rowBusy = busy === c.row_id;
                  const isOpen = expanded === c.row_id;
                  const detail = detailCache[c.row_id];
                  return (
                    <Fragment key={c.row_id}>
                      <tr style={{ background: selected.has(c.row_id) ? "#F7FAFC" : c.needs_review === false ? "#FAFAFA" : undefined }}>
                        <td>
                          <input type="checkbox" checked={selected.has(c.row_id)}
                            onChange={(e) => setSelected((prev) => { const n = new Set(prev); if (e.target.checked) n.add(c.row_id); else n.delete(c.row_id); return n; })} />
                        </td>
                        <td>
                          <button onClick={() => void toggleExpand(c)} title="상세 비교"
                            style={{ background: "none", border: "none", cursor: "pointer", color: "#718096" }}>
                            {isOpen ? "▼" : "▶"}
                          </button>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>
                            {c.detailed_code || "(코드없음)"}
                            {artifactByRow[c.row_id] && (
                              <button onClick={() => setPdfView({ artifactId: artifactByRow[c.row_id], page: 1, label: `변경 페이지 PDF — ${c.detailed_code || c.row_id} (#${artifactByRow[c.row_id]})` })}
                                title="이 후보의 변경 페이지 PDF artifact 보기" className="ml-1" style={{ fontSize: 10, padding: "0 5px", borderRadius: 8, background: "#C6F6D5", color: "#22543D", border: "1px solid #9AE6B4", cursor: "pointer", fontWeight: 700 }}>
                                📄 PDF
                              </button>
                            )}
                          </div>
                          <div style={{ color: "#A0AEC0", fontSize: 10 }}>{c.row_id}{c.business_name ? ` · ${c.business_name}` : ""}</div>
                        </td>
                        <td><span style={{ fontSize: 10, padding: "1px 5px", borderRadius: 8, background: c.manual_label === "visa" ? "#E9D8FD" : "#BEE3F8", color: "#4A5568" }}>{c.manual_label}</span></td>
                        <td>{c.old_page_from}-{c.old_page_to}</td>
                        <td style={{ fontWeight: 600, color: c.page_changed ? "#DD6B20" : "#2B6CB0" }}>
                          {c.candidate_page_from}-{c.candidate_page_to}
                          {dec?.reviewer_candidate_from != null && (
                            <div style={{ fontSize: 10, color: "#C05621", fontWeight: 700 }} title="관리자 지정 (현재 검토 기준)">
                              ★지정 {dec.reviewer_candidate_from}-{dec.reviewer_candidate_to}
                            </div>
                          )}
                        </td>
                        <td>{c.confidence}{c.similarity != null && <span style={{ color: "#A0AEC0" }}> ({Math.round(c.similarity * 100)}%)</span>}</td>
                        <td><span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 10, background: kind.bg, color: kind.color, fontWeight: 700 }}>{kind.label}</span></td>
                        <td style={{ maxWidth: 200, fontSize: 10, color: "#718096", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={c.reason}>{c.reason}</td>
                        <td><span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 10, background: badge.bg, color: badge.color, fontWeight: 700 }}>{badge.label}</span></td>
                        <td>
                          <div className="flex items-center gap-1">
                            <button disabled={rowBusy} title="후보 내용을 운영 반영 대상으로 선택" onClick={() => setDecision(c, "approve")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#9AE6B4", color: "#22543D", background: "#fff" }}>승인</button>
                            <button disabled={rowBusy} title="기존 manual_ref를 유지" onClick={() => setDecision(c, "keep_existing")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#BEE3F8", color: "#2A4365", background: "#fff" }}>기존유지</button>
                            <button disabled={rowBusy} title="나중에 다시 검토" onClick={() => setDecision(c, "hold")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#FAF089", color: "#744210", background: "#fff" }}>보류</button>
                            <button disabled={rowBusy} title="이번 후보에서 제외" onClick={() => setDecision(c, "reject")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#FED7D7", color: "#822727", background: "#fff" }}>제외</button>
                          </div>
                        </td>
                        <td>
                          {applied ? <span style={{ color: "#38A169", fontWeight: 700 }}>반영됨</span>
                            : canApply ? (
                              <button disabled={rowBusy} onClick={() => setApplyModal({ rowId: c.row_id, pf: String(dec?.reviewer_candidate_from ?? c.candidate_page_from ?? ""), pt: String(dec?.reviewer_candidate_to ?? c.candidate_page_to ?? dec?.reviewer_candidate_from ?? c.candidate_page_from ?? "") })}
                                className="text-[11px] px-2 py-0.5 rounded" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>운영 반영</button>
                            ) : <span style={{ color: "#CBD5E0" }}>—</span>}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={12} style={{ background: "#F7FAFC", padding: 10 }}>
                            {detailLoading === c.row_id ? <div style={{ color: "#A0AEC0" }}>상세 불러오는 중…</div>
                              : detail ? (
                                <CandidateDetailView d={detail} version={version} cand={c} decision={dec}
                                  onOpenPdf={openPdf} onOpenCandidatePdf={openCandidatePdf}
                                  onOverrideChanged={() => void reloadDecisions()} />
                              ) : <div style={{ color: "#A0AEC0" }}>상세 없음</div>}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* active decisions (현재 + 이번 orphaned 1회만; archive 제외) */}
      <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="text-xs font-semibold px-3 py-2" style={{ color: "#2D3748", borderBottom: "1px solid #EDF2F7" }}>
          검토 결정 (active · {decisions.length})
        </div>
        <div className="overflow-x-auto">
          <table className="hw-table w-full text-xs" style={{ minWidth: 800 }}>
            <thead><tr>
              {["row_id", "결정", "검토", "후보p.", "재검토", "후보변경", "orphaned", "source ver"].map((h) => <th key={h}>{h}</th>)}
            </tr></thead>
            <tbody>
              {decisions.length === 0 && <tr><td colSpan={8} style={{ color: "#A0AEC0", textAlign: "center", padding: 16 }}>검토 결정 없음 (PG 신규 시작)</td></tr>}
              {decisions.map((d, i) => (
                <tr key={i}>
                  <td>{d.row_id}</td><td>{d.decision || "-"}</td>
                  <td>{d.reviewed ? "✓" : ""}</td>
                  <td>{d.reviewed_candidate_page ?? "-"}</td>
                  <td>{d.needs_recheck ? "⚠" : ""}</td>
                  <td>{d.candidate_changed ? "✓" : ""}</td>
                  <td>{d.orphaned ? `예(${d.orphaned_at ?? ""})` : ""}</td>
                  <td>{d.source_version ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 운영 반영 확인 모달 */}
      {applyModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => busy !== applyModal.rowId && setApplyModal(null)}>
          <div className="hw-card" style={{ width: 420, maxWidth: "90vw", background: "#fff" }} onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-bold mb-1" style={{ color: "#C05621" }}>⚠ 운영 반영 확인</div>
            {(() => {
              const c = candidates.find((x) => x.row_id === applyModal.rowId);
              const dd = decByRow[applyModal.rowId];
              return (
                <div className="text-xs mb-2 p-2 rounded" style={{ background: "#F7FAFC", lineHeight: 1.8 }}>
                  <div style={{ color: "#718096" }}>자동 기준 p.: {c?.old_page_from}-{c?.old_page_to} · 자동 후보 p.: {c?.candidate_page_from}-{c?.candidate_page_to}</div>
                  <div style={{ color: "#C05621" }}>관리자 지정 기준 p.: {dd?.reviewer_baseline_from ?? "-"}-{dd?.reviewer_baseline_to ?? "-"} · 관리자 지정 후보 p.: {dd?.reviewer_candidate_from ?? "-"}-{dd?.reviewer_candidate_to ?? "-"}</div>
                  <div style={{ color: "#822727", fontWeight: 700 }}>실제 반영될 페이지: {applyModal.pf}-{applyModal.pt}</div>
                </div>
              );
            })()}
            <div className="text-xs mb-3" style={{ color: "#4A5568", lineHeight: 1.6 }}>
              <b>{applyModal.rowId}</b> 의 manual_ref 페이지를 운영 실무지침(immigration DB)에 <b>실제로 반영</b>합니다.
              반영 전 자동 백업되며, 승인/직접입력 상태에서만 가능합니다. 되돌리려면 백업본으로 복원해야 합니다.
            </div>
            <div className="flex items-center gap-2 mb-3 text-xs">
              <label style={{ color: "#718096" }}>page_from</label>
              <input className="hw-input" style={{ width: 70 }} value={applyModal.pf}
                onChange={(e) => setApplyModal((m) => m && { ...m, pf: e.target.value })} />
              <label style={{ color: "#718096" }}>page_to</label>
              <input className="hw-input" style={{ width: 70 }} value={applyModal.pt}
                onChange={(e) => setApplyModal((m) => m && { ...m, pt: e.target.value })} />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setApplyModal(null)} disabled={busy === applyModal.rowId}
                className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>취소</button>
              <button onClick={() => void doApply()} disabled={busy === applyModal.rowId}
                className="text-xs px-3 py-1.5 rounded" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>
                {busy === applyModal.rowId ? "반영 중..." : "운영 반영 실행"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 운영 반영 일괄 요약 모달 (req 9) */}
      {bulkApply && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => busy !== "bulk" && setBulkApply(false)}>
          <div className="hw-card" style={{ width: 420, maxWidth: "90vw", background: "#fff" }} onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-bold mb-2" style={{ color: "#C05621" }}>⚠ 운영 반영 — 요약 확인</div>
            <div className="text-xs mb-3" style={{ color: "#4A5568", lineHeight: 1.9 }}>
              <div>승인: <b>{applySummary.approve}</b>건</div>
              <div>기존유지: <b>{applySummary.keep}</b>건</div>
              <div>보류: <b>{applySummary.hold}</b>건</div>
              <div>제외: <b>{applySummary.reject}</b>건</div>
              <div>실질 변경 없음(no-op): <b>{applySummary.noop}</b>건</div>
              <div style={{ color: "#C05621", marginTop: 4 }}>이번에 실제 운영 반영될 항목(승인·미반영): <b>{applySummary.applyable}</b>건</div>
              <div style={{ color: "#A0AEC0" }}>이미 반영됨: {applySummary.applied}건</div>
            </div>
            <div className="text-xs mb-3" style={{ color: "#822727" }}>
              승인 항목의 후보 페이지를 운영 실무지침(immigration DB)에 반영합니다. 각 건 반영 전 자동 백업됩니다.
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setBulkApply(false)} disabled={busy === "bulk"}
                className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>취소</button>
              <button onClick={() => void doBulkApply()} disabled={busy === "bulk" || applySummary.applyable === 0}
                className="text-xs px-3 py-1.5 rounded" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>
                {busy === "bulk" ? "반영 중..." : `운영 반영 실행 (${applySummary.applyable}건)`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 전체 PDF 보기 모달 (staging 우선, 없으면 배포본) */}
      {pdfView && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1100, display: "flex", flexDirection: "column", padding: 20 }}
          onClick={() => setPdfView(null)}>
          <div className="hw-card" style={{ flex: 1, display: "flex", flexDirection: "column", background: "#fff", overflow: "hidden" }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <div className="text-sm font-bold" style={{ color: "#2D3748" }}>
                {pdfView.artifactId ? (pdfView.label || `변경 페이지 artifact #${pdfView.artifactId}`)
                  : `${pdfView.isStaging ? "최신 staging PDF" : "배포본 PDF"} — ${pdfView.manual} · p.${pdfView.page}`}
              </div>
              <div className="flex items-center gap-2 text-xs">
                {!pdfView.artifactId && <>
                  <span style={{ color: "#718096" }}>페이지</span>
                  <input defaultValue={String(pdfView.page)} className="hw-input" style={{ width: 60 }}
                    onKeyDown={(e) => { if (e.key === "Enter") { const n = parseInt((e.target as HTMLInputElement).value, 10); if (n >= 1) setPdfView((p) => p && { ...p, page: n }); } }} />
                </>}
                <button onClick={() => setPdfView(null)} className="px-2 py-1 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096" }}>닫기</button>
              </div>
            </div>
            {pdfView.artifactId ? (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#F0FFF4", color: "#276749", border: "1px solid #C6F6D5" }}>
                ✅ 최신 변경 페이지 PDF artifact 표시 중 (staging 생성본)
              </div>
            ) : !pdfView.isStaging && (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#FFFAF0", color: "#C05621", border: "1px solid #FEEBC8" }}>
                ⚠ 최신 staging PDF 미배포 — 현재 배포된 매뉴얼 PDF를 표시 중입니다. (페이지 번호가 최신본과 다를 수 있음)
              </div>
            )}
            <iframe key={pdfView.artifactId ? `art-${pdfView.artifactId}` : `${pdfView.manual}-${pdfView.page}`} style={{ flex: 1, border: "1px solid #E2E8F0", borderRadius: 6 }}
              src={pdfView.artifactId
                ? `/api/guidelines/manual-update/pdf-artifacts/${pdfView.artifactId}/content?token=${encodeURIComponent(token)}#toolbar=1&view=Fit`
                : `/api/guidelines/manual-update/pdf?manual=${encodeURIComponent(pdfView.manual || "")}&version=${encodeURIComponent(version)}&token=${encodeURIComponent(token)}#page=${pdfView.page}&toolbar=1&view=Fit`} />
          </div>
        </div>
      )}
    </div>
  );
}

function ManualUpdateTab() {
  const [mode, setMode] = useState<"loading" | "pg" | "file">("loading");
  const [st, setSt] = useState<PgStateResp | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/api/guidelines/manual-update/state");
        const data = r.data as PgStateResp;
        setSt(data);
        setMode(data?.source === "pg" ? "pg" : "file");
      } catch {
        setMode("file"); // 안전: 상태 조회 실패 시 기존 파일 화면 fallback
      }
    })();
  }, []);

  if (mode === "loading") {
    return <div className="hw-card text-sm" style={{ color: "#A0AEC0" }}>상태 확인 중...</div>;
  }
  if (mode === "file") {
    return <ManualUpdateV1Tab />;  // FEATURE_PG_MANUAL_UPDATE off → 기존 파일 staging 화면
  }
  return <ManualUpdatePgView state={st} />;
}


// ── 메인 어드민 페이지 ────────────────────────────────────────────────────────
export default function AdminPage() {
  const router = useRouter();
  const user = getUser();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"accounts" | "manual-review" | "manual-v1" | "doc-config">("accounts");
  const [showCreate, setShowCreate] = useState(false);
  const [wsLoadingId, setWsLoadingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
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

  // Detected from backend response. When ``storage_mode`` starts with ``pg+``
  // we hide the four Google-Sheets-key inputs and surface storage status
  // chips instead. Pure-Sheets installations have ``storage_mode`` absent
  // and the original 4-key view is preserved.
  const pgMode = isPgMode(accounts);
  const isLocalMock = accounts.some(
    (r) => String(r.storage_mode || "") === "pg+local-mock",
  );

  const updateMut = useMutation({
    mutationFn: ({ loginId, data }: { loginId: string; data: Record<string, unknown> }) =>
      adminApi.updateAccount(loginId, data),
    onSuccess: () => { toast.success("계정 업데이트됨"); qc.invalidateQueries({ queryKey: ["admin"] }); },
    onError: () => toast.error("업데이트 실패"),
    onSettled: () => setTogglingId(null),
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
    if (togglingId) return;
    setTogglingId(loginId);
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
          {pgMode && (
            <span
              className="text-[10px] px-2 py-0.5 rounded-full"
              style={{
                background: isLocalMock ? "#FAF5FF" : "#EBF8FF",
                color: isLocalMock ? "#553C9A" : "#2B6CB0",
                border: `1px solid ${isLocalMock ? "#D6BCFA" : "#BEE3F8"}`,
              }}
              title={
                isLocalMock
                  ? "PostgreSQL + 로컬 모의 저장소 모드 — Google Sheets/Drive는 호출되지 않습니다"
                  : "PostgreSQL 모드"
              }
            >
              {isLocalMock ? "🧪 PG + 로컬 모의" : "🗄 PG 모드"}
            </span>
          )}
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
        {/* 문서자동작성 선택 구조/필요서류 편집 */}
        <button
          className={`hw-tab ${activeTab === "doc-config" ? "active" : ""}`}
          onClick={() => setActiveTab("doc-config")}>
          <FileText size={12} className="inline mr-1" />
          문서자동작성 설정
        </button>
        {/* PG 기반 매뉴얼 업데이트 (기본/주) — 먼저 노출 */}
        <button
          className={`hw-tab ${activeTab === "manual-v1" ? "active" : ""}`}
          onClick={() => setActiveTab("manual-v1")}>
          <FileText size={12} className="inline mr-1" />
          매뉴얼 업데이트
        </button>
        {/* 레거시 파일/rematch 검토 — 표시만 유지 */}
        <button
          className={`hw-tab ${activeTab === "manual-review" ? "active" : ""}`}
          onClick={() => setActiveTab("manual-review")}>
          <BookOpen size={12} className="inline mr-1" />
          매뉴얼 업데이트 검토 (레거시)
        </button>
      </div>

      {/* 문서자동작성 설정 (편집형 선택 트리 + 필요서류) */}
      {activeTab === "doc-config" && <DocConfigTab />}

      {/* 매뉴얼 업데이트 (PG 단일 출처; PG off 시 파일 staging fallback) */}
      {activeTab === "manual-v1" && <ManualUpdateTab />}

      {/* 레거시 검토 탭 (manual_update_review.json + rematch) */}
      {activeTab === "manual-review" && (
        <>
          <div className="hw-card text-xs leading-relaxed mb-3" style={{ background: "#FFFAF0", borderColor: "#FEEBC8" }}>
            <div style={{ color: "#C05621", fontWeight: 700 }}>⚠ 레거시 화면 (파일 기반 manual_update_review.json + rematch) — 실사용 경로 아님</div>
            <div style={{ color: "#4A5568", marginTop: 4 }}>
              실제 검토·승인·<b>운영 반영</b>은 상단 <b>“매뉴얼 업데이트”</b> 탭(PostgreSQL)에서 수행하세요.
              이 화면은 파일 기반 구버전으로, 호환을 위해 조회용으로만 유지됩니다.
            </div>
          </div>
          <ManualReviewTab />
        </>
      )}

      {/* 계정 목록 */}
      {activeTab === "accounts" && (<>
      {isLoading ? (
        <div className="hw-card text-sm" style={{ color: "#A0AEC0" }}>불러오는 중...</div>
      ) : accounts.length === 0 ? (
        <div className="hw-card text-sm text-center py-10" style={{ color: "#A0AEC0" }}>등록된 계정이 없습니다.</div>
      ) : (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="overflow-x-auto">
            <table className="hw-table w-full" style={{ minWidth: pgMode ? 1200 : 1400 }}>
              <thead>
                <tr>
                  {(pgMode
                    ? [
                        "ID", "테넌트ID", "사무실명", "주소", "담당자", "연락처",
                        "사업자번호", "행정사RRN", "가입일",
                        "활성", "관리자",
                        "PG 저장소", "파일 저장소",
                        "워크스페이스", "편집", "삭제",
                      ]
                    : [
                        "ID", "테넌트ID", "사무실명", "주소", "담당자", "연락처",
                        "사업자번호", "행정사RRN", "가입일",
                        "활성", "관리자",
                        "고객시트키", "업무시트키", "폴더", "마스터시트",
                        "워크스페이스", "편집", "삭제",
                      ]
                  ).map((h) => (
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
                        {String(acc.has_agent_rrn) === "true"
                          ? `등록됨 ***${acc.agent_rrn_last4 || ""}`
                          : "—"}
                      </td>
                      <td className="text-xs" style={{ color: "#A0AEC0" }}>{acc.created_at}</td>
                      <td>
                        <button
                          onClick={() => {
                            const newVal = !(acc.is_active?.toLowerCase() === "true" || acc.is_active === "1");
                            const hasWorkspace = !!(acc.folder_id && acc.customer_sheet_key && acc.work_sheet_key);
                            if (newVal && !hasWorkspace) {
                              handleRowWorkspace(acc);
                            } else {
                              toggle(acc.login_id, "is_active", acc.is_active || "");
                            }
                          }}
                          disabled={togglingId === acc.login_id}
                          className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isActive ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}
                          style={{ opacity: togglingId === acc.login_id ? 0.5 : 1 }}
                        >
                          {togglingId === acc.login_id ? <Loader2 size={11} className="animate-spin" /> : isActive ? <CheckCircle size={11} /> : <XCircle size={11} />}
                          {isActive ? "활성" : "비활성"}
                        </button>
                      </td>
                      <td>
                        <button
                          onClick={() => toggle(acc.login_id, "is_admin", acc.is_admin || "")}
                          disabled={togglingId === acc.login_id}
                          className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isAdm ? "bg-orange-100 text-orange-700" : "bg-gray-100 text-gray-500"}`}
                          style={{ opacity: togglingId === acc.login_id ? 0.5 : 1 }}
                        >
                          {togglingId === acc.login_id ? <Loader2 size={11} className="animate-spin" /> : <Shield size={11} />}
                          {isAdm ? "관리자" : "일반"}
                        </button>
                      </td>
                      {pgMode ? (
                        <>
                          <td><PgStorageChip acc={acc as Record<string, unknown>} /></td>
                          <td><FileStorageChip acc={acc as Record<string, unknown>} /></td>
                        </>
                      ) : (
                        <>
                          <td><InlineEdit field="customer_sheet_key" width="w-40" /></td>
                          <td><InlineEdit field="work_sheet_key" width="w-40" /></td>
                          <td><InlineEdit field="folder_id" width="w-32" /></td>
                          <td><InlineEdit field="sheet_key" width="w-32" /></td>
                        </>
                      )}
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
                                  style={{ background: "#FFF9E6", color: "#6B5314" }}
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
          pgMode={pgMode}
          isLocalMock={isLocalMock}
        />
      )}

      {/* 상세 편집 드로어 */}
      {detailAcc && (
        <AccountDetailPanel
          acc={detailAcc}
          onUpdate={(loginId, data) => updateMut.mutate({ loginId, data })}
          onClose={() => setDetailAcc(null)}
          pgMode={pgMode}
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
