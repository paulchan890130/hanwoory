"use client";
// v3 자격 트리 편집(CRUD) 공용 UI — FEATURE_GUIDELINES_V3_EDIT(관리자, PG 오버레이).
// 스키마 기반 편집 모달 + 삭제 전 영향 확인 다이얼로그 + 준비서류(3구분) 편집기.
import { CSSProperties, useEffect, useState } from "react";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { guidelinesV3Api, V3DeleteImpact, V3DocRequirement, V3EntityType } from "@/lib/api";

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
  if (value === null || value === undefined) return "";
  if (kind === "list" && Array.isArray(value)) return value.join("\n");
  if (kind === "bool") return value ? "true" : "false";
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
