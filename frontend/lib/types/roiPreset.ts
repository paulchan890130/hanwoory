// frontend/lib/types/roiPreset.ts
// ROI 프리셋 타입 정의 — ARC 키는 백엔드 API와 일치 (한글/등록증/번호/발급일/만기일/주소)

export interface RoiBox {
  x: number; // 0~1 컨테이너 비율
  y: number;
  w: number;
  h: number;
}

export interface ArcRoiBoxes {
  한글: RoiBox;
  등록증: RoiBox;
  번호: RoiBox;
  발급일: RoiBox;
  만기일: RoiBox;
  주소: RoiBox;
}

export interface ImageTransform {
  rotation: number;            // 0 | 90 | 180 | 270
  zoom: number;                // = WsTf.scale
  pan: { x: number; y: number }; // = WsTf.tx, WsTf.ty
}

export interface RoiPresetData {
  passport: { mrz: RoiBox } & ImageTransform;
  arc: ArcRoiBoxes & ImageTransform;
}

export interface RoiPreset {
  slot: 1 | 2 | 3;
  name: string;
  data: RoiPresetData;
  is_default: boolean;
}

// 화면 표시용 라벨 (키는 절대 변경 금지, 라벨만 표시 목적)
export const ARC_LABELS: Record<keyof ArcRoiBoxes, string> = {
  한글:   "한글 이름",
  등록증: "등록증 앞 6자리",
  번호:   "등록증 뒤 7자리",
  발급일: "발급일",
  만기일: "만기일",
  주소:   "주소",
};

// WsTf ↔ ImageTransform 변환 헬퍼
export function wsTfToTransform(tf: {
  scale: number; tx: number; ty: number; rot: number;
}): ImageTransform {
  return { rotation: tf.rot, zoom: tf.scale, pan: { x: tf.tx, y: tf.ty } };
}

export function transformToWsTf(t: ImageTransform): {
  scale: number; tx: number; ty: number; rot: number;
} {
  return { scale: t.zoom, tx: t.pan.x, ty: t.pan.y, rot: t.rotation };
}
