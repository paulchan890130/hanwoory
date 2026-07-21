import { Loader2 } from "lucide-react";
import { ReactNode } from "react";

interface Props {
  isSubmitting: boolean;
  onClick: () => void;
  children: ReactNode;
  loadingText?: string;
  variant?: "primary" | "secondary" | "danger";
  disabled?: boolean;
  style?: React.CSSProperties;
  className?: string;
  type?: "button" | "submit";
}

export function SubmitButton({
  isSubmitting,
  onClick,
  children,
  loadingText = "저장 중...",
  variant = "primary",
  disabled = false,
  style,
  className,
  type = "button",
}: Props) {
  const variantStyles: Record<string, React.CSSProperties> = {
    primary: {
      background: "var(--hw-gold-soft-bg, #E7D6A6)",
      color: "var(--hw-gold-soft-text, #1F2937)",
      border: "1px solid var(--hw-gold-soft-border, #D3B96A)",
    },
    secondary: {
      background: "#fff",
      color: "#4A5568",
      border: "1px solid #CBD5E0",
    },
    danger: {
      background: "#E53E3E",
      color: "#fff",
      border: "none",
    },
  };

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={isSubmitting || disabled}
      className={className}
      style={{
        ...variantStyles[variant],
        padding: "10px 18px",
        borderRadius: 8,
        fontSize: 14,
        fontWeight: 600,
        cursor: isSubmitting || disabled ? "not-allowed" : "pointer",
        opacity: isSubmitting || disabled ? 0.7 : 1,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        transition: "opacity 0.2s",
        ...style,
      }}
    >
      {isSubmitting && (
        <Loader2
          size={16}
          style={{ animation: "spin 0.8s linear infinite" }}
        />
      )}
      <span>{isSubmitting ? loadingText : children}</span>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </button>
  );
}
