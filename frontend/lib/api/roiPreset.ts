// frontend/lib/api/roiPreset.ts
// ROI 프리셋 API 클라이언트 — lib/api.ts의 axios 인스턴스 재사용

import { api } from "@/lib/api";
import type { RoiPreset, RoiPresetData } from "@/lib/types/roiPreset";

export async function fetchRoiPresets(): Promise<(RoiPreset | null)[]> {
  const res = await api.get<{ presets: (RoiPreset | null)[] }>("/api/scan/roi-presets");
  const arr = res.data.presets;
  // 길이 3 보장 (백엔드가 항상 3개 반환하지만 방어적으로 처리)
  return [arr[0] ?? null, arr[1] ?? null, arr[2] ?? null];
}

export async function saveRoiPreset(
  slot: 1 | 2 | 3,
  name: string,
  data: RoiPresetData,
  isDefault: boolean,
): Promise<RoiPreset> {
  const res = await api.put<{ preset: RoiPreset }>(`/api/scan/roi-presets/${slot}`, {
    name,
    data,
    is_default: isDefault,
  });
  return res.data.preset;
}

export async function deleteRoiPreset(
  slot: 1 | 2 | 3,
): Promise<{ deleted: boolean; reset_to_default: boolean }> {
  const res = await api.delete<{ deleted: boolean; reset_to_default: boolean }>(
    `/api/scan/roi-presets/${slot}`,
  );
  return res.data;
}

export async function renameRoiPreset(slot: 1 | 2 | 3, name: string): Promise<RoiPreset> {
  const res = await api.patch<{ preset: RoiPreset }>(`/api/scan/roi-presets/${slot}/rename`, {
    name,
  });
  return res.data.preset;
}
