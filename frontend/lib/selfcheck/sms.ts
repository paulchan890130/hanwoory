// 문자 본문 생성 + 플랫폼별 문자 앱 실행/복사. 전부 로컬(메모리)에서만 수행한다.
// 웹사이트/백엔드가 문자를 자동 전송하지 않는다. SMS API 없음. 네트워크 요청 없음.
import type { SelfCheckConfig, SelfCheckAnswer } from "./types";
import { getResult } from "./logic";

// 수신번호는 프론트 상수(관리자 편집 필드 아님).
export const SMS_RECIPIENT = "01047028886";
export const SMS_RECIPIENT_DISPLAY = "010-4702-8886";

// 문자 본문(메모리에서만 생성). 개인정보/서버저장문구/전체분기/국가목록 미포함.
export function buildSmsBody(
  cfg: SelfCheckConfig, answers: SelfCheckAnswer[], resultId: string | null,
): string {
  const r = resultId ? getResult(cfg, resultId) : null;
  const itemName = (r?.item_name || cfg.item_name || "").trim();
  const resultText = (r?.headline || "").trim();
  const answerLines = answers.map(
    (a, i) => `${i + 1}. ${a.summary}: ${a.answer === "yes" ? "예" : "아니오"}`,
  );
  const pathSteps = answers.map((a, i) => `${i + 1}-${a.answer === "yes" ? "예" : "아니오"}`);
  if (r) pathSteps.push(r.label || r.headline);
  const lines = [
    "[한우리 공통기준 점검]",
    "",
    `항목: ${itemName}`,
    `결과: ${resultText}`,
    "",
    "본인 답변",
    ...answerLines,
    "",
    "판정경로",
    pathSteps.join(" → "),
    "",
    `적용로직: ${cfg.logic_version}`,
    "",
    "위 내용은 본인이 직접 선택한 답변에 따른 결과입니다.",
  ];
  return lines.join("\n");
}

export type Platform = "android" | "ios" | "pc";

// UA만 과신하지 않고 여러 신호를 조합. iPadOS(Macintosh 위장)도 고려. 실패 시 pc(안전 기본값).
export function detectPlatform(): Platform {
  try {
    const nav = typeof navigator !== "undefined" ? navigator : undefined;
    if (!nav) return "pc";
    const uaData = (nav as unknown as { userAgentData?: { platform?: string; mobile?: boolean } }).userAgentData;
    const ua = (nav.userAgent || "").toLowerCase();
    const platform = (nav.platform || "").toLowerCase();
    const touch = (nav.maxTouchPoints || 0) > 1;
    if (uaData?.platform) {
      const p = uaData.platform.toLowerCase();
      if (p.includes("android")) return "android";
      if (p.includes("ios") || p.includes("iphone") || p.includes("ipad")) return "ios";
    }
    if (/android/.test(ua)) return "android";
    if (/iphone|ipad|ipod/.test(ua)) return "ios";
    // iPadOS 13+ 는 Macintosh 로 위장 + 터치 지원.
    if (platform.includes("mac") && touch) return "ios";
    if (/mobi/.test(ua) && touch) return "android";
    return "pc";
  } catch {
    return "pc";
  }
}

// clipboard 복사(로컬). navigator.clipboard 실패 시 hidden textarea + execCommand fallback.
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fallthrough to legacy */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export interface SmsActionResult {
  platform: Platform;
  copied: boolean;
  opened: boolean;
  toast: string;
}

// 사용자 클릭 핸들러 안에서만 호출. 서버 요청 없음.
// - android: sms:번호?body=… 로 문자 앱 실행(+ 안전하게 본문 복사 병행)
// - ios: 본문 복사 후 sms:번호(본문 파라미터 불신) 실행
// - pc/미지원: 본문 복사만
export async function sendOrCopy(
  cfg: SelfCheckConfig, answers: SelfCheckAnswer[], resultId: string | null,
): Promise<SmsActionResult> {
  const body = buildSmsBody(cfg, answers, resultId);
  const platform = detectPlatform();
  const copied = await copyToClipboard(body);
  let opened = false;
  const openSms = (uri: string) => {
    try { window.location.href = uri; opened = true; } catch { opened = false; }
  };
  const enc = encodeURIComponent(body);
  if (platform === "android") {
    openSms(`sms:${SMS_RECIPIENT}?body=${enc}`);
    return { platform, copied, opened,
      toast: "문자 앱을 실행합니다. 전송 버튼을 눌러주세요. (본문이 자동 입력되지 않으면 붙여넣기 하세요.)" };
  }
  if (platform === "ios") {
    openSms(`sms:${SMS_RECIPIENT}`);
    return { platform, copied, opened,
      toast: copied
        ? "문자 내용이 복사되었습니다. 문자 입력창에 붙여넣은 후 전송해 주세요."
        : `수신번호: ${SMS_RECIPIENT_DISPLAY} · 내용을 직접 입력해 전송해 주세요.` };
  }
  // pc / 미지원
  return { platform, copied, opened,
    toast: copied
      ? `결과 내용이 복사되었습니다. 수신번호: ${SMS_RECIPIENT_DISPLAY}`
      : `수신번호: ${SMS_RECIPIENT_DISPLAY} · 복사가 지원되지 않아 내용을 직접 복사해 주세요.` };
}
