"use client";
// components/customers/CustomerCardModal.tsx
// 고객ID(고유키)만으로 기존 CustomerDrawer(고객카드)를 여는 얇은 래퍼.
// 홈 대시보드의 만기 목록 row 클릭 / 진행업무 카드 "고객카드" 버튼에서 재사용한다.
// - 전체 고객 레코드를 GET /api/customers/{id} 로 조회(이름 검색 아님 → 동명이인 오매칭 없음).
// - 저장은 기존 PUT /api/customers/{id} 재사용. 저장 후 드로어 유지 + onSaved() 로 호출측 목록 refresh.
// 새 고객카드 폼을 만들지 않고 CustomerDrawer 를 그대로 사용(중복 구현 금지).

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { customersApi } from "@/lib/api";
import { normalizeDate } from "@/lib/utils";
import { CustomerDrawer } from "@/components/customers/CustomerDrawer";

const DATE_FIELDS = ["발급일", "만기일", "발급", "만기"];

export default function CustomerCardModal({
  customerId,
  onClose,
  onSaved,
}: {
  customerId: string;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const qc = useQueryClient();
  // 저장 후 갱신된 레코드를 즉시 반영하기 위한 로컬 오버라이드.
  const [record, setRecord] = useState<Record<string, string> | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["customer", "by-id", customerId],
    queryFn: () => customersApi.get(customerId).then((r) => r.data),
    enabled: !!customerId,
    staleTime: 2_000,
  });

  useEffect(() => {
    if (data) {
      // 날짜 4개는 표시 전 시간부 제거(YYYY-MM-DD). 마이그레이션 timestamp 데이터 호환.
      const norm = { ...data } as Record<string, string>;
      DATE_FIELDS.forEach((f) => { if (norm[f]) norm[f] = normalizeDate(norm[f]); });
      setRecord(norm);
    }
  }, [data]);

  useEffect(() => {
    if (isError) {
      toast.error("고객 정보를 불러오지 못했습니다.");
      onClose();
    }
  }, [isError, onClose]);

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Record<string, string> }) =>
      customersApi.update(id, payload),
    onSuccess: (_res, variables) => {
      toast.success("저장됨");
      // 드로어는 닫지 않고 저장값으로 갱신(고객관리 페이지와 동일 동작).
      setRecord(variables.payload);
      qc.invalidateQueries({ queryKey: ["customers"] });
      qc.invalidateQueries({ queryKey: ["customer", "by-id", customerId] });
      onSaved?.();
    },
    onError: () => toast.error("저장 실패"),
  });

  const handleSave = (form: Record<string, string>) => {
    const normalized = { ...form };
    DATE_FIELDS.forEach((f) => { if (normalized[f]) normalized[f] = normalizeDate(normalized[f]); });
    const id = normalized["고객ID"] || customerId;
    updateMut.mutate({ id, payload: normalized });
  };

  // 삭제 — 기존 DELETE /api/customers/{id} 재사용(고객관리와 동일). 성공 시 닫고 목록 refresh.
  const deleteMut = useMutation({
    mutationFn: (id: string) => customersApi.delete(id),
    onSuccess: () => {
      toast.success("삭제됨");
      qc.invalidateQueries({ queryKey: ["customers"] });
      onSaved?.();
      onClose();
    },
    onError: () => toast.error("삭제 실패"),
  });

  // 로딩 중 — 드로어와 동일한 우측 패널 위치에 간단한 로딩 표시.
  if (!record) {
    if (isLoading) {
      return (
        <>
          <div className="fixed inset-0 z-40" style={{ background: "rgba(0,0,0,0.2)" }} onClick={onClose} />
          <div className="hw-drawer open" style={{ zIndex: 50, width: "min(480px, 100vw)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <span style={{ fontSize: 13, color: "#718096" }}>고객 정보 불러오는 중…</span>
          </div>
        </>
      );
    }
    return null;
  }

  return (
    <CustomerDrawer
      customer={record}
      isNew={false}
      onClose={onClose}
      onSave={handleSave}
      onDelete={(id) => deleteMut.mutate(id)}
      isSaving={updateMut.isPending}
    />
  );
}
