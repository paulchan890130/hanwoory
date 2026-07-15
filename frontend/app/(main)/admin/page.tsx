"use client";
import { useEffect, useState, useCallback, useRef, Fragment } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { adminApi, api } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { useRouter } from "next/navigation";
import {
  CheckCircle, XCircle, Shield, UserPlus, X, Save,
  FolderOpen, Loader2, ChevronRight, AlertTriangle, RefreshCw, Trash2,
  BookOpen, RotateCcw, CheckSquare, SkipForward, Edit3, FileText, ExternalLink, GitMerge,
} from "lucide-react";
import { useSubmit } from "@/lib/useSubmit";
import { SubmitButton } from "@/components/SubmitButton";
import DocConfigTab from "@/components/admin/DocConfigTab";
import AccountSecurityPanel from "@/components/admin/AccountSecurityPanel";
import { ManualUpdatePgView, type PgStateResp } from "@/components/admin/ManualReviewView";
import GuidelineUpdateInboxTab from "@/components/admin/GuidelineUpdateInboxTab";
import { ApplyToV3Modal } from "@/components/qualifications/editV3";

// ── PG 저장소 상태 helper ────────────────────────────────────────────────────
// 운영 기준은 PostgreSQL. 계정 목록은 PG 업무 데이터 유무만 "PG 저장소" 칩으로
// 표시한다. 과거 Drive/Sheets 키(레거시 admin/정평 등)는 표 컬럼이 아니라 수정
// 드로어의 접힘 "레거시 정보"로만 노출한다 — 운영 저장소처럼 보이지 않게 한다.
// (local-* sentinel 키는 PG 프로비저닝 placeholder일 뿐 저장소가 아니므로 숨김.)
// 백엔드 detail(예: 마지막 관리자/연결 데이터 차단 사유)을 그대로 노출.
function adminErr(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string" && d.trim()) return d;
  if (d && typeof d === "object" && typeof (d as { message?: string }).message === "string")
    return (d as { message: string }).message;
  return fallback;
}

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
        ✅ PG 데이터 있음
      </span>
    );
  }
  return (
    <span
      className="text-xs px-2 py-1 rounded-full"
      style={{ background: "#FFF9E6", color: "#6B5314", border: "1px solid #FAE0A0" }}
      title="PostgreSQL에 업무 데이터가 아직 없습니다 (Drive 생성 불필요)"
    >
      ⚠️ PG 미초기화
    </span>
  );
}

// 과거 Drive/Sheets 키(레거시 admin/정평 등) — 운영 저장소가 아니라 참고용 흔적.
// 실제 Google ID(비 local-*)가 남아 있을 때만 접힘으로 노출한다. local-* sentinel은
// PG 프로비저닝 placeholder일 뿐이므로(운영 저장소 아님) 표시하지 않는다.
function LegacyFieldNote({ acc }: { acc: Record<string, string> }) {
  const folder = String(acc.folder_id || "");
  const ckey = String(acc.customer_sheet_key || "");
  const wkey = String(acc.work_sheet_key || "");
  const legacy = [
    ["folder_id", folder],
    ["customer_sheet_key", ckey],
    ["work_sheet_key", wkey],
  ].filter(([, v]) => v && !v.startsWith("local-")) as [string, string][];
  if (legacy.length === 0) return null;
  return (
    <details className="text-[11px]" style={{ color: "#A0AEC0" }}>
      <summary style={{ cursor: "pointer" }}>
        과거 Drive/Sheets 필드 (레거시 · 현재 미사용)
      </summary>
      <div className="mt-1 space-y-0.5 font-mono">
        {legacy.map(([k, v]) => (
          <div key={k}>{k}: {v}</div>
        ))}
      </div>
    </details>
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

          {/* 섹션3: 워크스페이스 (PostgreSQL) */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="text-[11px] font-semibold uppercase px-2 py-1 rounded" style={{ color: "#718096", background: "#F7FAFC" }}>
                {isLocalMock ? "워크스페이스 (PostgreSQL · 개발용 mock)" : "워크스페이스 (PostgreSQL)"}
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
                <><FolderOpen size={11} /> 워크스페이스 자동 생성</>
              </SubmitButton>
            </div>
            {(form.customer_sheet_key || form.folder_id) && (
              <div className="text-xs px-3 py-2 rounded-lg mb-3" style={{ background: "#C6F6D5", color: "#276749" }}>
                ✅ 워크스페이스 초기화 완료
              </div>
            )}
            <div className="text-[11px] px-3 py-2 rounded-lg" style={{ background: "#F7FAFC", color: "#4A5568" }}>
              신규 계정은 PostgreSQL 기준으로 생성됩니다. 위 버튼은 PostgreSQL
              <code>tenants</code> 행을 초기화하고 계정을 활성화합니다.
              외부 시트/드라이브는 사용하지 않습니다.
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

          <div className="hw-section-divider mt-4">저장소 상태</div>
          <div className="text-xs space-y-2" style={{ color: "#4A5568" }}>
            <div>
              <span style={{ color: "#718096" }}>PostgreSQL: </span>
              <span className="font-mono">{acc.pg_storage_label || "(없음)"}</span>
            </div>
            <LegacyFieldNote acc={acc} />
            <div className="text-[11px]" style={{ color: "#A0AEC0" }}>
              운영 데이터는 PostgreSQL에만 저장됩니다. (외부 시트/드라이브 미사용)
            </div>
          </div>

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
              고객 데이터는 보존됩니다.
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
  const router = useRouter();
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
  const [applyV3Row, setApplyV3Row] = useState<RematchRow | null>(null);

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
          <td className="font-mono">
            {row.detailed_code || "—"}
            {!!row.detailed_code && (
              <>
                <button
                  onClick={() => router.push(`/qualifications/${encodeURIComponent(row.detailed_code)}?work=${encodeURIComponent(row.action_type || "")}`)}
                  title="해당 업무 화면 열기"
                  style={{ marginLeft: 5, background: "none", border: "none", cursor: "pointer", color: "#3182CE", verticalAlign: "middle" }}
                ><ExternalLink size={12} /></button>
                <button
                  onClick={() => setApplyV3Row(row)}
                  title="v3에 적용 — 자격/체류업무/사증경로/준비서류 오버레이 편집"
                  style={{ marginLeft: 3, background: "none", border: "none", cursor: "pointer", color: "#6B46C1", verticalAlign: "middle" }}
                ><GitMerge size={12} /></button>
              </>
            )}
          </td>
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
      {applyV3Row && (
        <ApplyToV3Modal
          hintCode={applyV3Row.detailed_code}
          hintActionType={applyV3Row.action_type}
          hintTitle={`${applyV3Row.detailed_code || applyV3Row.row_id} — ${applyV3Row.title}`}
          onClose={() => setApplyV3Row(null)}
          onApplied={() => toast.success("v3 오버레이에 반영되었습니다.")}
        />
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
          {/* full PDF 생성은 개발용 CLI fallback (운영 영향 없음). 운영 자동화는 Render Cron/Worker. */}
          <div className="mt-3 text-[11px] p-2 rounded" style={{ background: "#FFFDF7", color: "#6B5314", border: "1px solid #FAF089" }}>
            운영 자동화는 <b>Render Cron/Worker(Dockerfile.worker)</b>가 담당합니다. 아래는 개발용 fallback CLI입니다:
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
  const [activeTab, setActiveTab] = useState<"accounts" | "manual-review" | "manual-v1" | "doc-config" | "security">("accounts");
  // "매뉴얼 업데이트" 탭 내부 서브탭 — PG 페이지단위 diff 검토(기존, 자동감지 118p 등
  // 스크롤이 긴 화면)와 반영내역·패키지 검토(구 "실무지침 업데이트 검토함")를 한
  // 화면에 이어붙이면 관리자가 전자를 다 지나쳐야 후자에 닿는 문제가 있어 분리한다.
  const [manualSubTab, setManualSubTab] = useState<"pg-review" | "package-review">("pg-review");
  const [showCreate, setShowCreate] = useState(false);
  const [wsLoadingId, setWsLoadingId] = useState<string | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [detailAcc, setDetailAcc] = useState<Record<string, string> | null>(null);
  const [wsDetail, setWsDetail] = useState<WsResult | null>(null);
  const [confirmDeleteTarget, setConfirmDeleteTarget] = useState<Record<string, string> | null>(null);
  const [hardDeleteTarget, setHardDeleteTarget] = useState<Record<string, string> | null>(null);


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
      toast.success(`계정 '${loginId}' 비활성화됨`);
      qc.invalidateQueries({ queryKey: ["admin"] });
      setConfirmDeleteTarget(null);
    },
    onError: (e: unknown) => toast.error(adminErr(e, "비활성화 실패")),
  });

  const restoreMut = useMutation({
    mutationFn: (loginId: string) => adminApi.restoreAccount(loginId),
    onSuccess: (_, loginId) => {
      toast.success(`계정 '${loginId}' 복구됨`);
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (e: unknown) => toast.error(adminErr(e, "복구 실패")),
  });

  const hardDeleteMut = useMutation({
    mutationFn: ({ loginId, confirm }: { loginId: string; confirm: string }) =>
      adminApi.hardDeleteAccount(loginId, confirm),
    onSuccess: (_, { loginId }) => {
      toast.success(`계정 '${loginId}' 완전 삭제됨`);
      qc.invalidateQueries({ queryKey: ["admin"] });
      setHardDeleteTarget(null);
    },
    onError: (e: unknown) => toast.error(adminErr(e, "완전 삭제 실패")),
  });

  const toggle = (loginId: string, field: "is_active" | "is_admin", current: string) => {
    if (togglingId) return;
    setTogglingId(loginId);
    const newVal = !(current.toLowerCase() === "true" || current === "1");
    updateMut.mutate({ loginId, data: { [field]: newVal } });
  };

  // 준 관리자 권한 부여/회수 — role: 'sub_admin' | 'user'.
  const setRoleMut = useMutation({
    mutationFn: ({ loginId, role }: { loginId: string; role: "sub_admin" | "user" }) =>
      adminApi.setAccountRole(loginId, role),
    onSuccess: (_, { role }) => {
      toast.success(role === "sub_admin" ? "준 관리자 권한 부여됨" : "준 관리자 권한 회수됨");
      qc.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (e: unknown) => toast.error(adminErr(e, "권한 변경 실패")),
    onSettled: () => setTogglingId(null),
  });

  const toggleSubAdmin = (loginId: string, currentRole: string) => {
    if (togglingId) return;
    setTogglingId(loginId);
    setRoleMut.mutate({ loginId, role: currentRole === "sub_admin" ? "user" : "sub_admin" });
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
                  ? "개발 환경 — PostgreSQL + 개발용 mock 어댑터 (운영 아님, 외부 시트/드라이브 미호출)"
                  : "PostgreSQL 모드"
              }
            >
              {isLocalMock ? "🧪 개발용 mock" : "🗄 PG 모드"}
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
        {/* 매뉴얼 업데이트 — PG 페이지검토(관리자 승인 워크플로) + 원문 PDF 관리 +
            패키지 검토(구 "실무지침 업데이트 검토함", 이제 이 탭 안에 통합됨) */}
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
        {/* 로그인 보안 / 계정공유 의심 (베타) */}
        <button
          className={`hw-tab ${activeTab === "security" ? "active" : ""}`}
          onClick={() => setActiveTab("security")}>
          <Shield size={12} className="inline mr-1" />
          로그인 보안
        </button>
      </div>

      {activeTab === "security" && (
        <div style={{ marginTop: 12 }}>
          <AccountSecurityPanel />
        </div>
      )}

      {/* 문서자동작성 설정 (편집형 선택 트리 + 필요서류) */}
      {activeTab === "doc-config" && <DocConfigTab />}

      {/* 매뉴얼 업데이트 (PG 단일 출처; PG off 시 파일 staging fallback)
          + 원문 PDF 관리·패키지 검토(구 "실무지침 업데이트 검토함") 통합.
          두 하위 화면은 서로 다른 시스템(자동 페이지단위 diff 검토 vs 이번
          batch 반영내역·패키지 검토)이라 스크롤 한 줄로 이어붙이지 않고
          서브탭으로 분리한다. */}
      {activeTab === "manual-v1" && (
        <div style={{ marginTop: 12 }}>
          <div className="hw-tabs" style={{ marginBottom: 10 }}>
            <button
              className={`hw-tab ${manualSubTab === "pg-review" ? "active" : ""}`}
              onClick={() => setManualSubTab("pg-review")}>
              PG 페이지 검토
            </button>
            <button
              className={`hw-tab ${manualSubTab === "package-review" ? "active" : ""}`}
              onClick={() => setManualSubTab("package-review")}>
              반영 내역 · 패키지 검토
            </button>
          </div>
          {manualSubTab === "pg-review" && <ManualUpdateTab />}
          {manualSubTab === "package-review" && <GuidelineUpdateInboxTab />}
        </div>
      )}

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
                        "PG 저장소",
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
                  const isMaster = String((acc as Record<string, unknown>).is_master) === "true";
                  const accRole = String((acc as Record<string, unknown>).role || "user");
                  const isSubAdm = !isAdm && !isMaster && accRole === "sub_admin";

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
                          disabled={togglingId === acc.login_id || isMaster}
                          className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isActive ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}
                          style={{ opacity: togglingId === acc.login_id ? 0.5 : 1, cursor: isMaster ? "not-allowed" : undefined }}
                          title={isMaster ? "마스터 계정은 비활성화할 수 없습니다" : undefined}
                        >
                          {togglingId === acc.login_id ? <Loader2 size={11} className="animate-spin" /> : isActive ? <CheckCircle size={11} /> : <XCircle size={11} />}
                          {isActive ? "활성" : "비활성"}
                        </button>
                      </td>
                      <td>
                        {isMaster ? (
                          <span
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded-full"
                            style={{ background: "#FEF3C7", color: "#92400E", fontWeight: 700, border: "1px solid #D4A843" }}
                            title="마스터 계정 — 비활성화/삭제/강등 불가"
                          >
                            <Shield size={11} /> 마스터
                          </span>
                        ) : (
                          <div className="flex flex-col gap-1 items-start">
                            <button
                              onClick={() => toggle(acc.login_id, "is_admin", acc.is_admin || "")}
                              disabled={togglingId === acc.login_id}
                              className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isAdm ? "bg-orange-100 text-orange-700" : "bg-gray-100 text-gray-500"}`}
                              style={{ opacity: togglingId === acc.login_id ? 0.5 : 1 }}
                            >
                              {togglingId === acc.login_id ? <Loader2 size={11} className="animate-spin" /> : <Shield size={11} />}
                              {isAdm ? "관리자" : "일반"}
                            </button>
                            {!isAdm && (
                              <button
                                onClick={() => toggleSubAdmin(acc.login_id, accRole)}
                                disabled={togglingId === acc.login_id}
                                className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full ${isSubAdm ? "bg-blue-100 text-blue-700" : "bg-gray-50 text-gray-400 border border-gray-200"}`}
                                style={{ opacity: togglingId === acc.login_id ? 0.5 : 1 }}
                                title={isSubAdm ? "준 관리자 권한 회수(일반 사용자로)" : "준 관리자 권한 부여(실무지침·게시판 관리)"}
                              >
                                {isSubAdm ? "준 관리자" : "준관리자 부여"}
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                      {pgMode ? (
                        <td><PgStorageChip acc={acc as Record<string, unknown>} /></td>
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

                          // PG 모드: 워크스페이스 = PostgreSQL 활성화(가짜 Drive/Sheets 키 미생성).
                          // is_active 기준으로 표시하고, 비활성 계정만 활성화 버튼을 보인다.
                          if (pgMode) {
                            if (isActive) {
                              return (
                                <span
                                  className="text-xs px-2 py-1 rounded-full"
                                  style={{ background: "#C6F6D5", color: "#276749" }}
                                  title="PostgreSQL 활성화됨"
                                >
                                  ✅ 활성
                                </span>
                              );
                            }
                            return (
                              <button
                                onClick={() => handleRowWorkspace(acc)}
                                disabled={isLoading}
                                className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-50"
                                style={{ borderColor: "var(--hw-gold)", color: "var(--hw-gold-text)", background: "var(--hw-gold-light)" }}
                              >
                                {isLoading
                                  ? <><Loader2 size={10} className="animate-spin" /> 활성화 중</>
                                  : <><FolderOpen size={10} /> 활성화</>}
                              </button>
                            );
                          }

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
                        {isActive ? (
                          // 활성 계정: 비활성화만(완전삭제 숨김)
                          <button
                            onClick={() => setConfirmDeleteTarget(acc)}
                            disabled={acc.login_id === user?.login_id || isMaster}
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                            style={{ borderColor: "#FEB2B2", color: "#C53030", background: "#FFF5F5" }}
                            title={isMaster ? "마스터 계정은 비활성화할 수 없습니다" : acc.login_id === user?.login_id ? "자신의 계정은 비활성화할 수 없습니다" : "계정 비활성화"}
                          >
                            <XCircle size={11} /> 비활성화
                          </button>
                        ) : (
                          // 비활성 계정: 복구 + 완전삭제
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => restoreMut.mutate(acc.login_id)}
                              disabled={restoreMut.isPending}
                              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-50"
                              style={{ borderColor: "#9AE6B4", color: "#276749", background: "#F0FFF4" }}
                              title="계정 복구(활성화)"
                            >
                              <RefreshCw size={11} /> 복구
                            </button>
                            <button
                              onClick={() => setHardDeleteTarget(acc)}
                              disabled={acc.login_id === user?.login_id}
                              className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                              style={{ color: "#fff", background: "#C53030", border: "1px solid #9B2C2C" }}
                              title={acc.login_id === user?.login_id ? "자신의 계정은 완전 삭제할 수 없습니다" : "완전 삭제(복구 불가)"}
                            >
                              <Trash2 size={11} /> 완전삭제
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

      {/* 계정 비활성화 확인 모달 */}
      {confirmDeleteTarget && (
        <DeleteConfirmModal
          acc={confirmDeleteTarget}
          onConfirm={() => deleteMut.mutate(confirmDeleteTarget.login_id)}
          onClose={() => setConfirmDeleteTarget(null)}
          isDeleting={deleteMut.isPending}
        />
      )}

      {/* 완전 삭제(물리 삭제) 2단계 확인 모달 — 계정 아이디 직접 입력 필요 */}
      {hardDeleteTarget && (
        <HardDeleteModal
          acc={hardDeleteTarget}
          onConfirm={(confirm) => hardDeleteMut.mutate({ loginId: hardDeleteTarget.login_id, confirm })}
          onClose={() => setHardDeleteTarget(null)}
          isDeleting={hardDeleteMut.isPending}
        />
      )}
    </div>
  );
}

// ── 완전 삭제 확인 모달 (계정 아이디 직접 입력) ────────────────────────────────
function HardDeleteModal({
  acc, onConfirm, onClose, isDeleting,
}: {
  acc: Record<string, string>;
  onConfirm: (confirmLoginId: string) => void;
  onClose: () => void;
  isDeleting: boolean;
}) {
  const [text, setText] = useState("");
  const matches = text.trim() === acc.login_id;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}
      onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="hw-card" style={{ width: 440, maxWidth: "92vw", background: "#fff" }}>
        <div className="flex items-center gap-2 mb-2">
          <Trash2 size={16} style={{ color: "#C53030" }} />
          <span className="font-semibold text-sm" style={{ color: "#C53030" }}>계정 완전 삭제 (복구 불가)</span>
        </div>
        <div className="text-sm mb-3" style={{ color: "#4A5568", lineHeight: 1.6 }}>
          <strong>{acc.office_name || acc.login_id}</strong> (<code className="font-mono">{acc.login_id}</code>) 계정을
          <b style={{ color: "#C53030" }}> 영구적으로 삭제</b>합니다. 이 작업은 되돌릴 수 없습니다.
          <div className="mt-1" style={{ color: "#718096", fontSize: 12 }}>
            연결된 업무 데이터(고객·결산·문서 등)가 있으면 삭제가 차단됩니다.
          </div>
        </div>
        <div className="text-xs mb-1" style={{ color: "#718096" }}>삭제하려면 계정 아이디 <b className="font-mono" style={{ color: "#2D3748" }}>{acc.login_id}</b> 를 입력하세요.</div>
        <input
          autoFocus
          className="hw-input w-full font-mono text-sm mb-3"
          placeholder={acc.login_id}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && matches && !isDeleting) onConfirm(text.trim()); }}
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded-lg border" style={{ borderColor: "#E2E8F0", color: "#718096", background: "#fff" }}>
            취소
          </button>
          <button
            onClick={() => onConfirm(text.trim())}
            disabled={!matches || isDeleting}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ color: "#fff", background: "#C53030", border: "1px solid #9B2C2C" }}
          >
            {isDeleting ? <><Loader2 size={12} className="animate-spin" /> 삭제 중</> : <><Trash2 size={12} /> 완전 삭제</>}
          </button>
        </div>
      </div>
    </div>
  );
}
