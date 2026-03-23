"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { adminApi } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { useRouter } from "next/navigation";
import {
  CheckCircle, XCircle, Shield, UserPlus, X, Save,
  FolderOpen, Loader2, ChevronDown, ChevronRight,
} from "lucide-react";

// ── 신규 계정 생성 모달 ──────────────────────────────────────────────────────
function CreateAccountModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
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
      const data = res.data;
      setForm((prev) => ({
        ...prev,
        customer_sheet_key: data.customer_sheet_key || prev.customer_sheet_key,
        work_sheet_key: data.work_sheet_key || prev.work_sheet_key,
        folder_id: data.folder_id || prev.folder_id,
      }));
      if (data.warning) toast.warning(data.warning);
      else toast.success("워크스페이스 자동 생성 완료");
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


// ── 메인 어드민 페이지 ────────────────────────────────────────────────────────
export default function AdminPage() {
  const router = useRouter();
  const user = getUser();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [wsLoadingId, setWsLoadingId] = useState<string | null>(null);
  const [detailAcc, setDetailAcc] = useState<Record<string, string> | null>(null);

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

  const toggle = (loginId: string, field: "is_active" | "is_admin", current: string) => {
    const newVal = !(current.toLowerCase() === "true" || current === "1");
    updateMut.mutate({ loginId, data: { [field]: newVal } });
  };

  const handleRowWorkspace = async (acc: Record<string, string>) => {
    setWsLoadingId(acc.login_id);
    try {
      const res = await adminApi.createWorkspace(acc.login_id, acc.office_name || acc.login_id);
      const data = res.data;
      updateMut.mutate({
        loginId: acc.login_id,
        data: { customer_sheet_key: data.customer_sheet_key, work_sheet_key: data.work_sheet_key, folder_id: data.folder_id },
      });
      if (data.warning) toast.warning(data.warning);
      else toast.success(`${acc.login_id} 워크스페이스 생성 완료`);
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
          <h1 className="hw-page-title">계정 관리</h1>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary flex items-center gap-1.5 text-xs">
          <UserPlus size={14} /> 신규 계정 생성
        </button>
      </div>

      {/* 계정 목록 */}
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
                    "워크스페이스", "편집",
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
                          onClick={() => toggle(acc.login_id, "is_active", acc.is_active || "")}
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
                        {acc.folder_id ? (
                          <span className="text-xs px-2 py-1 rounded-full" style={{ background: "#C6F6D5", color: "#276749" }}>✅ 생성됨</span>
                        ) : (
                          <button
                            onClick={() => handleRowWorkspace(acc)}
                            disabled={wsLoadingId === acc.login_id}
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border transition-colors disabled:opacity-50"
                            style={{ borderColor: "var(--hw-gold)", color: "var(--hw-gold-text)", background: "var(--hw-gold-light)" }}
                          >
                            {wsLoadingId === acc.login_id
                              ? <><Loader2 size={10} className="animate-spin" /> 생성 중</>
                              : <><FolderOpen size={10} /> 자동 생성</>}
                          </button>
                        )}
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

      {/* 신규 계정 생성 모달 */}
      {showCreate && (
        <CreateAccountModal
          onClose={() => setShowCreate(false)}
          onCreated={() => qc.invalidateQueries({ queryKey: ["admin"] })}
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
    </div>
  );
}
