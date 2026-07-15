"use client";
// 삭제 전 공용 확인 모달 — 게시판(관리자 마케팅·내부 게시판) 등 삭제 진입점 공통 사용.
// 기본 포커스=취소, ESC=취소, 배경 클릭=취소. 확인 전에는 onConfirm(삭제 API)이 호출되지 않는다.
import { useEffect, useRef } from "react";
import { AlertTriangle, Loader2, Trash2 } from "lucide-react";

export function ConfirmDeleteModal({
  title = "삭제하시겠습니까?",
  subjectLabel,
  subjectValue,
  warning = "삭제한 내용은 복구할 수 없습니다.",
  isDeleting,
  error,
  onConfirm,
  onClose,
}: {
  title?: string;
  subjectLabel?: string;
  subjectValue?: string;
  warning?: string;
  isDeleting: boolean;
  error?: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isDeleting) onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.5)" }}
      onClick={() => { if (!isDeleting) onClose(); }}
    >
      <div
        className="hw-card w-full max-w-sm"
        role="alertdialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-4">
          <AlertTriangle size={18} style={{ color: "#E53E3E" }} />
          <span className="font-semibold text-sm" style={{ color: "#2D3748" }}>{title}</span>
        </div>
        <div className="mb-5 space-y-2">
          {subjectValue && (
            <div className="text-sm" style={{ color: "#2D3748" }}>
              {subjectLabel ?? "제목"}: <strong>{subjectValue}</strong>
            </div>
          )}
          <div className="text-xs" style={{ color: "#C53030" }}>{warning}</div>
          {error && (
            <div className="text-xs p-2 rounded" style={{ background: "#FFF5F5", color: "#C53030", border: "1px solid #FEB2B2" }}>
              {error}
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onClose}
            disabled={isDeleting}
            className="btn-secondary text-xs"
          >
            취소
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="text-xs"
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              padding: "6px 14px", borderRadius: 6, border: "none",
              background: "#E53E3E", color: "#fff", fontWeight: 600,
              cursor: isDeleting ? "not-allowed" : "pointer", opacity: isDeleting ? 0.6 : 1,
            }}
          >
            {isDeleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
            삭제
          </button>
        </div>
      </div>
    </div>
  );
}
