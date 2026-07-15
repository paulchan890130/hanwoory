"use client";
// v3 자격 트리 편집(CRUD) 공용 UI — FEATURE_GUIDELINES_V3_EDIT(관리자, PG 오버레이).
// 스키마 기반 편집 모달 + 삭제 전 영향 확인 다이얼로그 + 준비서류(3구분) 편집기.
import { CSSProperties, useEffect, useState } from "react";
import { Pencil, Plus, Trash2, X, History, RotateCcw, Search, Loader2 } from "lucide-react";
import {
  guidelinesV3Api, V3DeleteImpact, V3DocRequirement, V3EntityType,
  V3QualificationDetail, V3Block, V3Route,
} from "@/lib/api";

// ── 필드 스키마 ───────────────────────────────────────────────────────────────
export type FieldKind = "text" | "textarea" | "select" | "number" | "bool" | "list";
export interface FieldSpec {
  key: string;
  label: string;
  kind: FieldKind;
  options?: { value: string; label: string }[];
  required?: boolean;
  placeholder?: string;
  help?: string;
  readOnly?: boolean;
}

const inputStyle: CSSProperties = {
  width: "100%", fontSize: 12.5, padding: "7px 10px", borderRadius: 8,
  border: "1px solid #E2E8F0", outline: "none", background: "#fff", color: "#2D3748",
};
const labelStyle: CSSProperties = { fontSize: 11, fontWeight: 700, color: "#4A5568", marginBottom: 4 };

function fieldToInput(value: unknown, kind: FieldKind): string {
  // is_active(유일한 bool 필드) 는 정본 JSON 대다수 행에 키 자체가 없다 — 백엔드 전체가
  // "없음/null = 활성"으로 취급하므로(예: `.get("is_active", True) is not False`), 여기서도
  // 없음을 빈 문자열("")로 두면 select 가 실제로는 미선택 상태인데도 화면엔 "예(활성)"가
  // 보여서(브라우저가 매칭 안 되는 값일 때 첫 옵션을 표시) 저장 시 inputToField 가 ""를
  // false 로 취급해 무관한 필드만 고쳐도 항목이 조용히 비활성화되는 사고가 난다.
  if (kind === "bool") return value === false ? "false" : "true";
  if (value === null || value === undefined) return "";
  if (kind === "list" && Array.isArray(value)) return value.join("\n");
  return String(value);
}

function inputToField(text: string, kind: FieldKind): unknown {
  if (kind === "list") return text.split("\n").map(s => s.trim()).filter(Boolean);
  if (kind === "number") return text.trim() === "" ? null : Number(text);
  if (kind === "bool") return text === "true";
  return text;
}

// ── 편집 모달(추가/수정 공용) ─────────────────────────────────────────────────
export function EntityEditModal({ title, fields, initial, onSave, onClose }: {
  title: string;
  fields: FieldSpec[];
  initial: Record<string, unknown>;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onClose: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map(f => [f.key, fieldToInput(initial[f.key], f.kind)])));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async () => {
    for (const f of fields) {
      if (f.required && !(values[f.key] ?? "").trim()) {
        setError(`필수값 누락: ${f.label}`);
        return;
      }
    }
    setSaving(true); setError("");
    const payload: Record<string, unknown> = {};
    for (const f of fields) {
      if (f.readOnly) continue;
      payload[f.key] = inputToField(values[f.key] ?? "", f.kind);
    }
    try {
      await onSave(payload);
      onClose();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail
        : detail ? JSON.stringify(detail) : "저장에 실패했습니다. 입력값을 확인해 주세요.");
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 300,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
      onClick={onClose}>
      <div style={{ background: "#fff", borderRadius: 14, width: "100%", maxWidth: 560,
        maxHeight: "88vh", overflowY: "auto", padding: "18px 20px" }}
        onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#2D3748", flex: 1 }}>{title}</div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0" }}>
            <X size={16} />
          </button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {fields.map(f => (
            <div key={f.key}>
              <div style={labelStyle}>
                {f.label}{f.required && <span style={{ color: "#C53030" }}> *</span>}
                {f.help && <span style={{ fontWeight: 400, color: "#A0AEC0", marginLeft: 6 }}>{f.help}</span>}
              </div>
              {f.kind === "select" || f.kind === "bool" ? (
                <select value={values[f.key] ?? ""} disabled={f.readOnly}
                  onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                  style={inputStyle}>
                  {f.kind === "bool"
                    ? <><option value="true">예(활성)</option><option value="false">아니오(비활성)</option></>
                    : <>
                        {!f.required && <option value="">(없음)</option>}
                        {(f.options ?? []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </>}
                </select>
              ) : f.kind === "textarea" || f.kind === "list" ? (
                <textarea value={values[f.key] ?? ""} readOnly={f.readOnly}
                  rows={f.kind === "list" ? 3 : 4}
                  placeholder={f.placeholder ?? (f.kind === "list" ? "한 줄에 한 항목" : "")}
                  onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                  style={{ ...inputStyle, resize: "vertical", lineHeight: 1.6 }} />
              ) : (
                <input value={values[f.key] ?? ""} readOnly={f.readOnly}
                  placeholder={f.placeholder ?? ""}
                  onChange={e => setValues(v => ({ ...v, [f.key]: e.target.value }))}
                  style={{ ...inputStyle, background: f.readOnly ? "#F7FAFC" : "#fff" }} />
              )}
            </div>
          ))}
        </div>
        {error && (
          <div style={{ marginTop: 12, padding: "9px 12px", borderRadius: 8, background: "#FFF5F5",
            border: "1px solid #FEB2B2", fontSize: 12, color: "#C53030", lineHeight: 1.5 }}>{error}</div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 16 }}>
          <button onClick={onClose} disabled={saving}
            style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "1px solid #E2E8F0",
              background: "#fff", color: "#718096", cursor: "pointer" }}>취소</button>
          <button onClick={submit} disabled={saving}
            style={{ fontSize: 12.5, fontWeight: 700, padding: "7px 18px", borderRadius: 8, border: "none",
              background: "var(--hw-gold)", color: "#fff", cursor: "pointer", opacity: saving ? 0.6 : 1 }}>
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 삭제 전 영향 확인 다이얼로그 ─────────────────────────────────────────────
export function ImpactDialog({ entityLabel, impact, onCascade, onClose }: {
  entityLabel: string;
  impact: V3DeleteImpact;
  onCascade: (() => Promise<void>) | null; // null = 삭제 불가(하위 이동/삭제 필요)
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rows: [string, string[]][] = [
    ["세부약호(하위 자격)", impact.qualifications],
    ["체류업무", impact.blocks],
    ["사증 경로", impact.routes],
    ["준비서류", impact.doc_requirements],
  ];
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 300,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div style={{ background: "#fff", borderRadius: 14, width: "100%", maxWidth: 520,
        maxHeight: "85vh", overflowY: "auto", padding: "18px 20px" }} onClick={e => e.stopPropagation()}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#C53030", marginBottom: 10 }}>
          삭제 전 영향 확인 — {entityLabel}
        </div>
        <div style={{ fontSize: 12.5, color: "#4A5568", marginBottom: 10, lineHeight: 1.6 }}>
          {entityLabel} 을(를) 삭제하면 다음 데이터가 영향을 받습니다.
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
          {rows.filter(([, list]) => list.length > 0).map(([label, list]) => (
            <div key={label} style={{ padding: "8px 12px", borderRadius: 8, background: "#F7FAFC",
              border: "1px solid #E2E8F0" }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: "#2D3748" }}>{label} {list.length}건</div>
              <div style={{ fontSize: 11, color: "#718096", marginTop: 3, lineHeight: 1.6,
                overflowWrap: "anywhere" }}>
                {list.slice(0, 30).join(", ")}{list.length > 30 ? ` 외 ${list.length - 30}건` : ""}
              </div>
            </div>
          ))}
        </div>
        {onCascade === null && (
          <div style={{ padding: "9px 12px", borderRadius: 8, background: "#FFF5F5",
            border: "1px solid #FEB2B2", fontSize: 12, color: "#C53030", marginBottom: 12, lineHeight: 1.6 }}>
            이 항목은 연결 데이터 포함 삭제가 허용되지 않습니다. 하위 자격을 먼저 이동하거나 삭제하세요.
          </div>
        )}
        {error && (
          <div style={{ padding: "9px 12px", borderRadius: 8, background: "#FFF5F5",
            border: "1px solid #FEB2B2", fontSize: 12, color: "#C53030", marginBottom: 12 }}>{error}</div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose} disabled={busy}
            style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "1px solid #E2E8F0",
              background: "#fff", color: "#718096", cursor: "pointer" }}>취소</button>
          {onCascade && (
            <button disabled={busy}
              onClick={async () => {
                setBusy(true); setError("");
                try { await onCascade(); onClose(); }
                catch (e) {
                  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
                  setError(typeof detail === "string" ? detail : "삭제에 실패했습니다.");
                  setBusy(false);
                }
              }}
              style={{ fontSize: 12.5, fontWeight: 700, padding: "7px 18px", borderRadius: 8, border: "none",
                background: "#C53030", color: "#fff", cursor: "pointer", opacity: busy ? 0.6 : 1 }}>
              {busy ? "삭제 중…" : "연결 데이터 포함 삭제"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 삭제 흐름 헬퍼: 영향 조회 → (연결 있으면 다이얼로그) → 삭제 ────────────────
export async function runDelete(
  etype: V3EntityType, id: string, label: string,
  showImpact: (impact: V3DeleteImpact, cascadeAllowed: boolean) => void,
  onDone: () => void,
): Promise<void> {
  const res = await guidelinesV3Api.editImpact(etype, id);
  const impact = res.data.impact;
  if (impact.blocking) {
    showImpact(impact, impact.cascade_allowed);
    return;
  }
  if (!window.confirm(`${label} 을(를) 삭제할까요?\n(${id})`)) return;
  await guidelinesV3Api.editDelete(etype, id, false);
  onDone();
}

// ── 소형 편집 버튼 ───────────────────────────────────────────────────────────
export function EditIconButton({ kind, onClick, title }: {
  kind: "add" | "edit" | "delete"; onClick: () => void; title: string;
}) {
  const Icon = kind === "add" ? Plus : kind === "edit" ? Pencil : Trash2;
  const color = kind === "delete" ? "#C53030" : "#4A5568";
  return (
    <button type="button" title={title} aria-label={title}
      onClick={e => { e.stopPropagation(); onClick(); }}
      style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: 22, height: 22, borderRadius: 6, border: "1px solid #E2E8F0",
        background: "#fff", color, cursor: "pointer", flexShrink: 0 }}>
      <Icon size={12} />
    </button>
  );
}

// ── 필드 스키마 정의(레벨별) ─────────────────────────────────────────────────
export const GROUP_FIELDS: FieldSpec[] = [
  { key: "group_key", label: "대분류 키", kind: "text", required: true, placeholder: "예: A, SPECIAL", help: "영문 대문자·숫자" },
  { key: "label", label: "대분류명", kind: "text", required: true, placeholder: "예: A 계열 (외교·공무·협정)" },
  { key: "description", label: "설명", kind: "textarea" },
  { key: "sort_order", label: "표시 순서", kind: "number", placeholder: "10" },
  { key: "is_active", label: "활성 여부", kind: "bool" },
];

export function qualFields(groups: { value: string; label: string }[], isChild: boolean): FieldSpec[] {
  return [
    { key: "code", label: isChild ? "세부약호" : "자격 코드", kind: "text", required: true, placeholder: isChild ? "예: F-2-7S" : "예: F-2" },
    { key: "name_ko", label: "한글명", kind: "text", required: true },
    { key: "name_en", label: "영문명·보조명", kind: "text" },
    ...(isChild
      ? [{ key: "parent_qualification_id", label: "상위 자격", kind: "text", readOnly: true } as FieldSpec]
      : [{ key: "group", label: "상위 대분류", kind: "select", required: true, options: groups } as FieldSpec]),
    { key: "activity_scope", label: "활동범위", kind: "textarea" },
    { key: "eligible_persons", label: "해당자", kind: "textarea" },
    { key: "stay_limit", label: "1회 체류기간 상한", kind: "text", placeholder: "예: 2년, 협정상의 체류기간" },
    { key: "display_order", label: "표시 순서", kind: "number" },
    { key: "is_active", label: "활성 여부", kind: "bool" },
  ];
}

export const BLOCK_TYPE_OPTIONS = [
  { value: "EXTRA_WORK", label: "체류자격외 활동" },
  { value: "WORKPLACE", label: "근무처 변경·추가" },
  { value: "GRANT", label: "체류자격 부여" },
  { value: "CHANGE", label: "체류자격 변경허가" },
  { value: "EXTEND", label: "체류기간 연장허가" },
  { value: "REENTRY", label: "재입국허가" },
  { value: "REGISTRATION", label: "외국인등록" },
];

export function blockFields(creating: boolean): FieldSpec[] {
  return [
    { key: "block_type", label: "업무 유형", kind: "select", required: true, options: BLOCK_TYPE_OPTIONS, readOnly: !creating },
    { key: "block_label", label: "업무명", kind: "text", required: true },
    { key: "applicability", label: "상태", kind: "select", required: true, options: [
      { value: "applicable", label: "가능" },
      { value: "conditional", label: "조건부 가능" },
      { value: "not_applicable", label: "불가·해당 없음" },
    ] },
    { key: "na_reason", label: "불가 사유", kind: "textarea", help: "불가·해당 없음일 때 필수" },
    { key: "fee", label: "수수료", kind: "text", placeholder: "예: 6만원" },
    { key: "exceptions", label: "제한·예외·주의사항", kind: "list" },
    { key: "display_order", label: "표시 순서", kind: "number" },
    { key: "is_active", label: "활성 여부", kind: "bool" },
  ];
}

export const ROUTE_TYPE_OPTIONS = [
  { value: "recognition", label: "사증발급인정서" },
  { value: "consulate", label: "재외공관 사증" },
  { value: "evisa", label: "전자사증" },
  { value: "domestic_only", label: "국내 부여·변경 경로" },
  { value: "alternative_route", label: "대체 신청 경로" },
  { value: "not_applicable", label: "대상 아님" },
  { value: "discontinued", label: "신청 중단" },
];

export function routeFields(): FieldSpec[] {
  return [
    { key: "route_type", label: "route 유형", kind: "select", required: true, options: ROUTE_TYPE_OPTIONS },
    { key: "route_label", label: "경로명(업무명)", kind: "text", required: true },
    { key: "application_place", label: "신청처", kind: "textarea", help: "실제 신청 경로는 필수" },
    { key: "application_form", label: "신청 서식", kind: "text", placeholder: "예: 별지 제17호 사증발급신청서" },
    { key: "fee", label: "수수료", kind: "text", placeholder: "예: 있음(공관별 상이) / 없음" },
    { key: "exceptions", label: "대상자·조건·예외", kind: "list" },
    { key: "alt_apply_as", label: "대체 경로: 신청 자격·경로", kind: "text", help: "대체 신청 경로 유형만" },
    { key: "alt_relation", label: "대체 경로: 현재 자격과의 관계", kind: "textarea" },
    { key: "alt_follow_up", label: "대체 경로: 입국 후 절차", kind: "textarea" },
    { key: "alt_caution", label: "대체 경로: 주의", kind: "textarea" },
    { key: "display_order", label: "표시 순서", kind: "number" },
    { key: "is_active", label: "활성 여부", kind: "bool" },
  ];
}

export function auxFields(creating: boolean): FieldSpec[] {
  return [
    ...(creating ? [] : [{ key: "aux_id", label: "고유 ID", kind: "text", readOnly: true } as FieldSpec]),
    { key: "name", label: "보조 민원명", kind: "text", required: true, placeholder: "예: 외국인등록증 재발급" },
    { key: "description", label: "설명", kind: "textarea" },
    { key: "kind", label: "업무 분류", kind: "text", placeholder: "application_claim", help: "기본 application_claim" },
    { key: "application_place", label: "신청처", kind: "text", placeholder: "예: 관할 출입국·외국인관서" },
    { key: "application_method", label: "신청 방식", kind: "text", placeholder: "예: 방문 / 온라인(하이코리아)" },
    { key: "application_form", label: "신청 서식", kind: "text", placeholder: "예: 별지 제34호" },
    { key: "fee", label: "수수료", kind: "text", placeholder: "예: 3만원 / 없음" },
    { key: "processing_note", label: "처리기간·안내", kind: "text" },
    { key: "notes", label: "주의사항", kind: "textarea" },
    { key: "display_order", label: "표시 순서", kind: "number" },
    { key: "is_active", label: "활성 여부", kind: "bool" },
  ];
}

export function drFields(): FieldSpec[] {
  return [
    { key: "doc_name", label: "서류명", kind: "text", required: true },
    { key: "doc_role", label: "서류 구분", kind: "select", required: true, options: [
      { value: "client", label: "신청인 준비서류" },
      { value: "office", label: "행정사 사무소 준비서류" },
      { value: "conditional", label: "해당 시 추가서류" },
    ] },
    { key: "doc_kind", label: "종류", kind: "select", options: [
      { value: "form", label: "서식" }, { value: "evidence", label: "입증서류" },
    ] },
    { key: "condition", label: "조건", kind: "textarea", help: "'해당 시 추가서류'일 때 필수" },
    { key: "display_condition", label: "조건 표시 문구", kind: "text", placeholder: "예: ~인 경우 제출" },
    { key: "form_ref", label: "서식 번호", kind: "text", placeholder: "예: 별지 제34호" },
    { key: "display_order", label: "표시 순서", kind: "number" },
  ];
}

// ── 준비서류 편집기(상세 패널용) ─────────────────────────────────────────────
export function DrEditor({ targetId, drs, onChanged }: {
  targetId: string;
  drs: V3DocRequirement[];
  onChanged: () => void;
}) {
  const [modal, setModal] = useState<{ mode: "create" | "edit"; dr?: V3DocRequirement } | null>(null);
  const [impactState, setImpactState] = useState<{ impact: V3DeleteImpact; id: string; label: string } | null>(null);

  const save = async (payload: Record<string, unknown>) => {
    if (modal?.mode === "edit" && modal.dr) {
      await guidelinesV3Api.editUpdate("doc_requirement", modal.dr.requirement_id, payload);
    } else {
      await guidelinesV3Api.editCreate("doc_requirement", { ...payload, target_id: targetId });
    }
    onChanged();
  };

  return (
    <div style={{ marginBottom: 12, padding: "10px 12px", borderRadius: 10,
      background: "#FFFDF5", border: "1px dashed rgba(212,168,67,0.5)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: "var(--hw-gold-text)" }}>준비서류 편집</span>
        <EditIconButton kind="add" title="서류 추가" onClick={() => setModal({ mode: "create" })} />
      </div>
      {drs.length === 0 && (
        <div style={{ fontSize: 11.5, color: "#A0AEC0" }}>등록된 서류가 없습니다 — 추가 버튼으로 등록하세요.</div>
      )}
      {drs.map(d => (
        <div key={d.requirement_id} style={{ display: "flex", alignItems: "center", gap: 6, padding: "3px 0" }}>
          <span style={{ fontSize: 11.5, color: "#4A5568", flex: 1, overflowWrap: "anywhere" }}>
            [{d.doc_role === "client" ? "신청인" : d.doc_role === "office" ? "사무소" : "해당 시"}] {d.doc_name}
          </span>
          <EditIconButton kind="edit" title="서류 수정" onClick={() => setModal({ mode: "edit", dr: d })} />
          <EditIconButton kind="delete" title="서류 삭제" onClick={async () => {
            await runDelete("doc_requirement", d.requirement_id, d.doc_name,
              (impact) => setImpactState({ impact, id: d.requirement_id, label: d.doc_name }), onChanged);
          }} />
        </div>
      ))}
      {modal && (
        <EntityEditModal
          title={modal.mode === "edit" ? `서류 수정 — ${modal.dr?.doc_name}` : "서류 추가"}
          fields={drFields()}
          initial={(modal.dr as unknown as Record<string, unknown>) ?? { doc_role: "client", doc_kind: "evidence" }}
          onSave={save} onClose={() => setModal(null)} />
      )}
      {impactState && (
        <ImpactDialog entityLabel={impactState.label} impact={impactState.impact}
          onCascade={async () => {
            await guidelinesV3Api.editDelete("doc_requirement", impactState.id, true);
            onChanged();
          }}
          onClose={() => setImpactState(null)} />
      )}
    </div>
  );
}

// ── 매뉴얼 검토 → v3 적용 모달 ─────────────────────────────────────────────────
// 매뉴얼 검토 화면(관리자)에서 특정 후보를 v3 자격/체류업무/사증경로/준비서류에 반영할 때
// 사용. 정본 JSON은 그대로 두고 기존 오버레이 편집 API(EntityEditModal·DrEditor·revert)를
// 그대로 재사용한다 — 새 저장 계층·migration 없음. "적용 제외"/"기존값 유지"는 API 호출 없이
// 닫기만 한다(오버레이에 아무것도 쓰지 않는 것 자체가 '기존값 유지' 상태).
function OverlayBadge({ etype, id }: { etype: V3EntityType; id: string }) {
  const [info, setInfo] = useState<{ has_overlay: boolean; updated_by?: string | null; updated_at?: string | null } | null>(null);
  const [checked, setChecked] = useState(false);
  const check = async () => {
    try {
      const r = await guidelinesV3Api.editOverlayStatus(etype, id);
      setInfo(r.data);
    } catch { setInfo(null); }
    setChecked(true);
  };
  if (!checked) {
    return (
      <button onClick={check} title="적용 이력 보기"
        style={{ fontSize: 10.5, padding: "1px 7px", borderRadius: 10, border: "1px solid #E2E8F0",
          background: "#fff", color: "#718096", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 3 }}>
        <History size={10} /> 적용 이력
      </button>
    );
  }
  if (!info?.has_overlay) {
    return <span style={{ fontSize: 10.5, color: "#A0AEC0" }}>편집 없음(정본 값)</span>;
  }
  const when = info.updated_at ? new Date(info.updated_at).toLocaleString("ko-KR") : "";
  return (
    <span style={{ fontSize: 10.5, color: "#975A16", display: "inline-flex", alignItems: "center", gap: 5 }}>
      편집됨 — {info.updated_by || "관리자"} · {when}
    </span>
  );
}

export function ApplyToV3Modal({
  hintCode, hintActionType, hintTitle, candidateContext, onClose, onApplied,
}: {
  hintCode?: string; hintActionType?: string; hintTitle?: string;
  candidateContext?: { existingText?: string; candidateText?: string; reason?: string };
  onClose: () => void; onApplied: () => void;
}) {
  const [showSource, setShowSource] = useState(false);
  const [code, setCode] = useState(hintCode ?? "");
  const [detail, setDetail] = useState<V3QualificationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [modal, setModal] = useState<{
    etype: V3EntityType; mode: "create" | "edit"; title: string;
    fields: FieldSpec[]; initial: Record<string, unknown>; id?: string;
  } | null>(null);
  const [drTarget, setDrTarget] = useState<string | null>(null); // 준비서류 편집기 펼침 대상(block_id/route_id)

  const lookup = async (c: string) => {
    if (!c.trim()) return;
    setLoading(true); setError(""); setDetail(null);
    try {
      const res = await guidelinesV3Api.getQualification(c.trim());
      setDetail(res.data);
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      setError(status === 404
        ? `자격 코드 "${c.trim()}"를 찾을 수 없습니다. 코드를 확인하거나 아래에서 대분류를 먼저 만들어야 할 수 있습니다.`
        : "조회에 실패했습니다.");
    } finally { setLoading(false); }
  };

  useEffect(() => { if (hintCode) lookup(hintCode); }, [hintCode]);

  const refresh = async () => { if (code.trim()) await lookup(code.trim()); onApplied(); };

  const saveModal = async (payload: Record<string, unknown>) => {
    if (!modal) return;
    if (modal.mode === "edit" && modal.id) {
      await guidelinesV3Api.editUpdate(modal.etype, modal.id, payload);
    } else {
      await guidelinesV3Api.editCreate(modal.etype, { ...modal.initial, ...payload });
    }
    setModal(null);
    await refresh();
  };

  const revertEntity = async (etype: V3EntityType, id: string, label: string) => {
    if (!window.confirm(`${label}을(를) 정본(원본 JSON) 값으로 되돌릴까요?\n이 오버레이 편집으로 신설된 항목이면 사라집니다.`)) return;
    try {
      await guidelinesV3Api.editRevert(etype, id);
      await refresh();
    } catch { window.alert("복원에 실패했습니다."); }
  };

  const qid = detail?.master.qualification_id ?? "";

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 500,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }} onClick={onClose}>
      <div style={{ background: "#fff", borderRadius: 14, width: "100%", maxWidth: 720,
        maxHeight: "90vh", overflowY: "auto", padding: "20px 22px" }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", alignItems: "flex-start", marginBottom: 6 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#2D3748" }}>매뉴얼 검토 → v3 적용</div>
            {hintTitle && <div style={{ fontSize: 12, color: "#718096", marginTop: 2 }}>근거: {hintTitle}</div>}
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0" }}><X size={18} /></button>
        </div>
        {candidateContext && (candidateContext.existingText || candidateContext.candidateText || candidateContext.reason) && (
          <div style={{ marginBottom: 10 }}>
            <button onClick={() => setShowSource(v => !v)}
              style={{ fontSize: 11, color: "#6B46C1", background: "none", border: "none", cursor: "pointer",
                padding: 0, display: "flex", alignItems: "center", gap: 4 }}>
              {showSource ? "▼" : "▶"} 매뉴얼 원문 비교(참고용, 자동 반영 아님)
            </button>
            {showSource && (
              <div style={{ marginTop: 6, display: "flex", gap: 8, flexWrap: "wrap" }}>
                {candidateContext.reason && (
                  <div style={{ flex: "1 1 100%", fontSize: 11, color: "#718096" }}>매칭 사유: {candidateContext.reason}</div>
                )}
                <div style={{ flex: 1, minWidth: 220, background: "#F7FAFC", border: "1px solid #E2E8F0",
                  borderRadius: 6, padding: 8, fontSize: 11, color: "#4A5568", whiteSpace: "pre-wrap",
                  wordBreak: "break-word", maxHeight: 220, overflow: "auto" }}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>기존(정본 근거)</div>
                  {candidateContext.existingText || "(없음)"}
                </div>
                <div style={{ flex: 1, minWidth: 220, background: "#FFFBEB", border: "1px solid #F6E05E",
                  borderRadius: 6, padding: 8, fontSize: 11, color: "#4A5568", whiteSpace: "pre-wrap",
                  wordBreak: "break-word", maxHeight: 220, overflow: "auto" }}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>후보(신규 매뉴얼)</div>
                  {candidateContext.candidateText || "(없음)"}
                </div>
              </div>
            )}
          </div>
        )}
        <div style={{ fontSize: 11.5, color: "#975A16", background: "#FFFBEB", border: "1px solid #F6E05E",
          borderRadius: 8, padding: "7px 10px", marginBottom: 14, lineHeight: 1.6 }}>
          매뉴얼 업로드·분석만으로는 아무것도 바뀌지 않습니다. 아래에서 자격을 조회한 뒤 항목을
          직접 수정·추가하고 저장해야만 운영 데이터(오버레이)에 반영됩니다. 저장하지 않고 닫으면
          "적용 제외/기존값 유지"와 동일합니다.
        </div>

        <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
          <input value={code} onChange={e => setCode(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter") lookup(code); }}
            placeholder="자격 코드 (예: F-2-7S)"
            style={{ flex: 1, fontSize: 13, padding: "7px 10px", borderRadius: 8, border: "1px solid #E2E8F0" }} />
          <button onClick={() => lookup(code)} disabled={loading}
            style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12.5, fontWeight: 600,
              padding: "7px 14px", borderRadius: 8, border: "none", background: "var(--hw-gold)", color: "#fff",
              cursor: loading ? "not-allowed" : "pointer", opacity: loading ? 0.6 : 1 }}>
            {loading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />} 조회
          </button>
        </div>
        {error && (
          <div style={{ marginBottom: 14, padding: "9px 12px", borderRadius: 8, background: "#FFF5F5",
            border: "1px solid #FEB2B2", fontSize: 12.5, color: "#C53030" }}>{error}</div>
        )}

        {detail && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {/* 자격 정보 */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 14, fontWeight: 700 }}>{detail.master.code} {detail.master.name_ko}</span>
              <EditIconButton kind="edit" title="자격 정보 수정" onClick={() => setModal({
                etype: "qualification", mode: "edit", id: qid, title: `자격 정보 수정 — ${detail.master.code}`,
                fields: qualFields([{ value: detail.master.group, label: detail.master.group }], !!detail.parent)
                  .map(f => f.key === "code" ? { ...f, readOnly: true } : f),
                initial: detail.master as unknown as Record<string, unknown>,
              })} />
              <OverlayBadge etype="qualification" id={qid} />
            </div>

            {/* 체류업무 */}
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#4A5568" }}>체류업무</span>
                <button onClick={() => setModal({
                  etype: "stay_block", mode: "create", title: "체류업무 추가",
                  fields: blockFields(true),
                  initial: { qualification_id: qid, applicability: "applicable", is_active: true,
                    ...(hintActionType ? { block_type: hintActionType } : {}) },
                })} style={{ fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 20,
                  border: "1px solid rgba(212,168,67,0.55)", background: "rgba(212,168,67,0.08)",
                  color: "var(--hw-gold-text)", cursor: "pointer" }}>+ 체류업무</button>
              </div>
              {detail.blocks.map((b: V3Block) => (
                <div key={b.block_id} style={{ border: "1px solid #E2E8F0", borderRadius: 8, padding: "8px 10px", marginBottom: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>{b.block_label}</span>
                    <span style={{ fontSize: 10.5, color: "#718096" }}>{b.block_type} · {b.applicability}</span>
                    <EditIconButton kind="edit" title="업무 수정" onClick={() => setModal({
                      etype: "stay_block", mode: "edit", id: b.block_id, title: `체류업무 수정 — ${b.block_label}`,
                      fields: blockFields(false), initial: b as unknown as Record<string, unknown>,
                    })} />
                    <button onClick={() => setDrTarget(t => t === b.block_id ? null : b.block_id)}
                      style={{ fontSize: 10.5, padding: "1px 7px", borderRadius: 10, border: "1px solid #E2E8F0",
                        background: "#fff", color: "#4A5568", cursor: "pointer" }}>준비서류</button>
                    <OverlayBadge etype="stay_block" id={b.block_id} />
                    <button onClick={() => revertEntity("stay_block", b.block_id, b.block_label)} title="정본 복원"
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0" }}>
                      <RotateCcw size={12} />
                    </button>
                  </div>
                  {drTarget === b.block_id && (
                    <div style={{ marginTop: 8 }}>
                      <DrEditor targetId={b.block_id} drs={detail.doc_requirements[b.block_id] ?? []} onChanged={refresh} />
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* 사증 경로 */}
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#4A5568" }}>사증 경로</span>
                <button onClick={() => setModal({
                  etype: "visa_route", mode: "create", title: "사증 경로 추가",
                  fields: routeFields(),
                  initial: { qualification_id: qid, route_type: "recognition", is_active: true },
                })} style={{ fontSize: 11, fontWeight: 700, padding: "2px 10px", borderRadius: 20,
                  border: "1px solid rgba(212,168,67,0.55)", background: "rgba(212,168,67,0.08)",
                  color: "var(--hw-gold-text)", cursor: "pointer" }}>+ 사증 경로</button>
              </div>
              {detail.routes.map((r: V3Route) => (
                <div key={r.route_id} style={{ border: "1px solid #E2E8F0", borderRadius: 8, padding: "8px 10px", marginBottom: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>{r.route_label}</span>
                    <span style={{ fontSize: 10.5, color: "#718096" }}>{r.route_type}</span>
                    <EditIconButton kind="edit" title="경로 수정" onClick={() => setModal({
                      etype: "visa_route", mode: "edit", id: r.route_id, title: `사증 경로 수정 — ${r.route_label}`,
                      fields: routeFields(), initial: r as unknown as Record<string, unknown>,
                    })} />
                    <button onClick={() => setDrTarget(t => t === r.route_id ? null : r.route_id)}
                      style={{ fontSize: 10.5, padding: "1px 7px", borderRadius: 10, border: "1px solid #E2E8F0",
                        background: "#fff", color: "#4A5568", cursor: "pointer" }}>준비서류</button>
                    <OverlayBadge etype="visa_route" id={r.route_id} />
                    <button onClick={() => revertEntity("visa_route", r.route_id, r.route_label)} title="정본 복원"
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0" }}>
                      <RotateCcw size={12} />
                    </button>
                  </div>
                  {drTarget === r.route_id && (
                    <div style={{ marginTop: 8 }}>
                      <DrEditor targetId={r.route_id} drs={detail.doc_requirements[r.route_id] ?? []} onChanged={refresh} />
                    </div>
                  )}
                </div>
              ))}
              {detail.routes.length === 0 && <div style={{ fontSize: 12, color: "#A0AEC0" }}>사증 경로 없음</div>}
            </div>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
          <button onClick={onClose}
            style={{ fontSize: 12.5, padding: "7px 16px", borderRadius: 8, border: "1px solid #E2E8F0",
              background: "#fff", color: "#718096", cursor: "pointer" }}>
            닫기(적용 제외 / 기존값 유지)
          </button>
        </div>
      </div>

      {modal && (
        <EntityEditModal title={modal.title} fields={modal.fields} initial={modal.initial}
          onSave={saveModal} onClose={() => setModal(null)} />
      )}
    </div>
  );
}
