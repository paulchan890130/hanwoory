"use client";

import { useEffect, useState } from "react";
import { VISA_STATUS_OPTIONS, normalizeVisaCode, isKnownVisaCode } from "@/lib/visa";

const CUSTOM = "__custom__";

export interface VisaStatusSelectProps {
  value: string;
  onChange: (v: string) => void;
  /** select/input 공통 인라인 스타일 (스캔 페이지 inputStyle 등) */
  style?: React.CSSProperties;
  /** select/input 공통 className (고객관리 hw-input 등) */
  className?: string;
  placeholder?: string;
}

/**
 * 체류자격 선택 — 문서자동작성과 동일한 코드 체계의 표준 옵션을 select 로 제공하고,
 * 표준에 없는 기존/특수 값은 "직접입력(기타)" 으로 보존한다.
 *
 * - 저장값은 부모가 그대로 보관(파괴적 변환 없음). 사용자가 옵션을 명시 선택하면 코드로 정규화.
 * - 알 수 없는 기존 값(예: "Q-1", 임의 문자열)은 직접입력 칸에 원문 표시 → 삭제되지 않음.
 */
export default function VisaStatusSelect({
  value,
  onChange,
  style,
  className,
  placeholder = "선택",
}: VisaStatusSelectProps) {
  const normalized = normalizeVisaCode(value);
  const known = isKnownVisaCode(value);
  // 직접입력 모드: 값이 있으나 표준 코드가 아님 → 직접입력으로 보존
  const [manual, setManual] = useState<boolean>(!!value && !known);

  // 고객 전환 등으로 value 가 외부에서 바뀌면 모드를 값 기준으로 재동기화
  useEffect(() => {
    if (known) setManual(false);
    else if (value) setManual(true);
    else setManual(false);
  }, [value, known]);

  const showCustom = manual || (!!value && !known);
  const selectValue = showCustom ? CUSTOM : known ? normalized : "";

  const handleSelect = (v: string) => {
    if (v === CUSTOM) {
      setManual(true); // 값은 유지 — 사용자가 직접입력으로 보정
      return;
    }
    setManual(false);
    onChange(v); // "" 선택 시 빈값, 그 외 표준 코드로 정규화 저장
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <select
        className={className}
        style={style}
        value={selectValue}
        onChange={(e) => handleSelect(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {VISA_STATUS_OPTIONS.map((o) => (
          <option key={o.code} value={o.code}>
            {o.label}
          </option>
        ))}
        <option value={CUSTOM}>기타(직접입력)</option>
      </select>
      {showCustom && (
        <input
          type="text"
          className={className}
          style={style}
          value={value}
          placeholder="직접 입력 (예: F-4)"
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
