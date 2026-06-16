/**
 * API 클라이언트 - axios 기반
 * localStorage에서 토큰을 읽어 자동으로 Authorization 헤더에 포함
 */
import axios from "axios";

const BASE_URL = "";

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: false,
});

// 요청 인터셉터: 토큰 자동 첨부
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    if (
      process.env.NODE_ENV !== "production" &&
      /^\/api\/guidelines\/(?:\?|$)/.test(String(config.url ?? ""))
    ) {
      console.debug("[guidelines:list] Authorization header present:", Boolean(token));
    }
  }
  return config;
});

// 401 redirect 중복 방지 플래그 — 여러 동시 요청이 모두 401을 받아도 한 번만 리다이렉트
let _redirecting401 = false;

// 응답 인터셉터: 401이면 인증 상태 즉시 초기화 후 로그인 페이지로
// - 장시간 미이용 후 만료 시: sessionStorage에 "auth_expired=1" 설정 → 로그인 페이지에서 안내 메시지 표시
// - 수동 로그아웃과 구분: 수동 로그아웃은 clearUser()만 호출하고 이 플래그를 설정하지 않음
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const headers = err.config?.headers;
      const skipAuthRedirect =
        headers?.["X-Skip-Auth-Redirect"] === "1" ||
        headers?.get?.("X-Skip-Auth-Redirect") === "1";
      if (skipAuthRedirect) {
        return Promise.reject(err);
      }
      if (typeof window !== "undefined" && !_redirecting401) {
        _redirecting401 = true;
        // SESSION_REVOKED(다른 기기 로그인) vs 일반 만료 구분
        const detail = (err.response?.data as { detail?: unknown })?.detail;
        const code = detail && typeof detail === "object" ? (detail as { code?: string }).code : undefined;
        localStorage.removeItem("access_token");
        localStorage.removeItem("user_info");
        document.cookie = "kid_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
        try {
          if (code === "ACCOUNT_DISABLED") sessionStorage.setItem("account_disabled", "1");
          else if (code === "SESSION_REVOKED") sessionStorage.setItem("session_revoked", "1");
          else sessionStorage.setItem("auth_expired", "1");
        } catch { /* sessionStorage 차단 환경 무시 */ }
        // replace: 히스토리 스택에 만료된 내부 페이지를 남기지 않음
        window.location.replace("/login");
      }
    }
    return Promise.reject(err);
  }
);

// ── 타입 정의 ──────────────────────────────────────────────────────────────────

export interface UserInfo {
  login_id: string;
  tenant_id: string;
  is_admin: boolean;
  office_name: string;
  access_token: string;
  contact_name?: string;
}

export interface ActiveTask {
  id: string;
  category: string;
  date: string;
  name: string;
  work: string;
  details: string;
  transfer: string;
  cash: string;
  card: string;
  stamp: string;
  receivable: string;
  planned_expense: string;
  processed: boolean | string;
  processed_timestamp: string;
  reception?: string;
  processing?: string;
  storage?: string;
}

export interface CompletedTask {
  id: string;
  category: string;
  date: string;
  name: string;
  work: string;
  details: string;
  complete_date: string;
  reception?: string;
  processing?: string;
  storage?: string;
}

export interface PlannedTask {
  id: string;
  date: string;
  period: string;
  content: string;
  note: string;
}

export interface DailyEntry {
  id: string;
  date: string;
  time: string;
  category: string;
  name: string;
  task: string;
  income_cash: number;
  income_etc: number;
  exp_cash: number;
  exp_etc: number;
  cash_out: number;
  memo: string;
  customer_id?: string; // 고객 자동완성 선택 시 전달 (시트에 저장 안 됨, 위임내역 연동용)
}

export interface BalanceData {
  cash: number;
  profit: number;
}

export interface BoardPost {
  id: string;
  tenant_id: string;
  author_login: string;
  author: string;
  office_name: string;
  is_notice: string;       // "Y" or ""
  category: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
  popup_yn?: string;       // "Y" or ""
  link_url?: string;       // 외부 링크 URL
  view_count?: number;
  comment_count?: number;
}

// ── API 함수들 ─────────────────────────────────────────────────────────────────

// 인증
export const authApi = {
  login: (login_id: string, password: string) =>
    api.post("/api/auth/login", { login_id, password }),
  signup: (data: Record<string, string>) =>
    api.post("/api/auth/signup", data),
  logout: () => api.post("/api/auth/logout", null, { headers: { "X-Skip-Auth-Redirect": "1" } }),
  // 현재 계정 상태 재확인용 — 비활성/삭제 시 401(ACCOUNT_DISABLED) → 인터셉터가 강제 로그아웃.
  me: () => api.get("/api/auth/me"),
};

// 전자명함 (마이페이지)
export interface BusinessCard {
  office_name: string;
  contact_name: string;
  phone: string;        // 표시용(effective): card_phone || contact_tel
  address: string;      // 표시용(effective): card_address || office_adr
  bio: string;
  work_fields: string[];
  logo_url: string;          // 외부 URL(하위호환, 보조)
  has_logo: boolean;         // 업로드 로고 존재(우선 표시)
  logo_updated_at: string;   // 캐시버스트 ?v= 용(ISO)
  public_slug: string;
  is_public: boolean;
  // 편집용 원본값(빈 값이면 fallback이 적용됨을 의미 — 입력칸은 이 raw 값으로 채운다)
  raw?: {
    card_phone: string;
    card_address: string;
    card_logo_url: string;
    card_work_fields: string[];
  };
}
export const businessCardApi = {
  getMine: () => api.get<BusinessCard>("/api/my/business-card"),
  updateMine: (data: Partial<{
    phone: string; address: string; bio: string;
    work_fields: string[]; logo_url: string; public_slug: string; is_public: boolean;
  }>) => api.patch<BusinessCard>("/api/my/business-card", data),
  uploadLogo: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post<{ has_logo: boolean; mime: string; size: number; logo_updated_at: string }>(
      "/api/my/business-card/logo", fd,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
  },
  deleteLogo: () => api.delete<{ has_logo: boolean }>("/api/my/business-card/logo"),
  // 소유자 본인 로고 이미지(blob) — 마이페이지 미리보기용(Bearer 인증).
  getMyLogoBlob: () => api.get<Blob>("/api/my/business-card/logo", { responseType: "blob" }),
};

// 업무
export const tasksApi = {
  getActive: () => api.get<ActiveTask[]>("/api/tasks/active"),
  addActive: (task: Partial<ActiveTask>) => api.post("/api/tasks/active", task),
  updateActive: (id: string, task: Partial<ActiveTask>) => api.put(`/api/tasks/active/${id}`, task),
  deleteActive: (ids: string[]) => api.delete("/api/tasks/active", { data: { task_ids: ids } }),
  completeTasks: (ids: string[]) => api.post("/api/tasks/active/complete", { task_ids: ids }),

  getPlanned: () => api.get<PlannedTask[]>("/api/tasks/planned"),
  addPlanned: (task: Partial<PlannedTask>) => api.post("/api/tasks/planned", task),
  updatePlanned: (id: string, task: Partial<PlannedTask>) => api.put(`/api/tasks/planned/${id}`, task),
  deletePlanned: (ids: string[]) => api.delete("/api/tasks/planned", { data: { task_ids: ids } }),

  getCompleted: () => api.get<CompletedTask[]>("/api/tasks/completed"),
  updateCompleted: (id: string, task: Partial<CompletedTask>) => api.put(`/api/tasks/completed/${id}`, task),
  deleteCompleted: (ids: string[]) => api.delete("/api/tasks/completed", { data: { task_ids: ids } }),

  batchProgress: (updates: { id: string; reception: string; processing: string; storage: string }[]) =>
    api.patch("/api/tasks/active/batch-progress", { updates }),
  batchMoney: (updates: Array<{ id: string; changes: Partial<Record<"transfer"|"cash"|"card"|"stamp"|"receivable"|"planned_expense", string>> }>) =>
    api.patch("/api/tasks/active/batch-money", { updates }),
};

export interface WorkSummary {
  groups: Record<string, number>;
  total: number;
  /** 진행 중인 업무 (customer_id 일치) 개수 — 일일결산 추가/삭제 시 즉시 변동 */
  active_total?: number;
  legacy_groups: Record<string, number>;
  legacy_total: number;
  has_name_duplicate: boolean;
}

// 고객
export const customersApi = {
  list: (search?: string, page?: number, pageSize?: number, signal?: AbortSignal) =>
    api.get("/api/customers", { params: { search, page, page_size: pageSize }, signal }),
  add: (data: Record<string, string>) => api.post("/api/customers", data),
  update: (id: string, data: Record<string, string>) => api.put(`/api/customers/${id}`, data),
  delete: (id: string) => api.delete(`/api/customers/${id}`),
  expiryAlerts: () => api.get<{ card_alerts: ExpiryAlert[]; passport_alerts: ExpiryAlert[] }>("/api/customers/expiry-alerts"),
  appendDelegation: (id: string, entry: string) =>
    api.post(`/api/customers/${id}/delegation-append`, { entry }),
  workSummary: (id: string, name?: string) =>
    api.get<WorkSummary>(`/api/customers/${encodeURIComponent(id)}/work-summary`, { params: { name } }),
  completedTasks: (id: string, name?: string, includeLegacy = false) =>
    api.get<{ tasks: Record<string, string>[]; legacy_tasks: Record<string, string>[] }>(
      `/api/customers/${encodeURIComponent(id)}/completed-tasks`,
      { params: { name, include_legacy: includeLegacy } }
    ),
};

// 숙소제공자 연결
export interface AccommodationProvider {
  target_customer_id: string;
  provider_type: "customer_db" | "manual";
  provider_customer_id: string;
  provider_name: string;        // 한글 성명
  provider_last_name: string;   // 영문 성
  provider_first_name: string;  // 영문 이름
  provider_nation: string;      // 국적
  provider_reg_front: string;   // 등록번호 앞자리
  provider_reg_back: string;    // 등록번호 뒷자리
  provider_birth: string;       // 생년월일 보조
  provider_phone: string;       // 연락처
  provider_address: string;     // 숙소 소재지 / 참고 주소
  provider_relation: string;    // 피제공자와의 관계
  provide_start_date: string;   // 제공 시작일 YYYY-MM-DD
  provide_end_date: string;     // 제공 종료일
  housing_type: string;         // 자가/임대/개인주택/친척/기타
  created_at: string;
  updated_at: string;
}

export const accommodationApi = {
  get: (customerId: string) =>
    api.get<AccommodationProvider | null>(`/api/customers/${encodeURIComponent(customerId)}/accommodation-provider`),
  save: (customerId: string, data: Partial<Omit<AccommodationProvider, "target_customer_id" | "updated_at">>) =>
    api.post<{ ok: boolean; data: AccommodationProvider }>(`/api/customers/${encodeURIComponent(customerId)}/accommodation-provider`, data),
  delete: (customerId: string) =>
    api.delete(`/api/customers/${encodeURIComponent(customerId)}/accommodation-provider`),
};

// 신원보증인 연결
export interface GuarantorConnection {
  target_customer_id: string;
  guarantor_type: "customer_db" | "manual";
  guarantor_customer_id: string;
  guarantor_name: string;
  guarantor_last_name: string;
  guarantor_first_name: string;
  guarantor_nation: string;
  guarantor_reg_front: string;
  guarantor_reg_back: string;
  guarantor_birth: string;
  guarantor_phone: string;
  guarantor_address: string;
  guarantor_relation: string;
  guarantor_workplace: string;
  guarantor_extra: string;
  created_at: string;
  updated_at: string;
}

export const guarantorApi = {
  get: (customerId: string) =>
    api.get<GuarantorConnection | null>(`/api/customers/${encodeURIComponent(customerId)}/guarantor`),
  save: (customerId: string, data: Partial<Omit<GuarantorConnection, "target_customer_id" | "updated_at">>) =>
    api.post<{ ok: boolean; data: GuarantorConnection }>(`/api/customers/${encodeURIComponent(customerId)}/guarantor`, data),
  delete: (customerId: string) =>
    api.delete(`/api/customers/${encodeURIComponent(customerId)}/guarantor`),
};

export interface ExpiryAlert {
  한글이름: string;
  영문이름: string;
  여권번호: string;
  생년월일: string;
  전화번호: string;
  등록증만기일?: string;
  여권만기일?: string;
}

// 결산
export const dailyApi = {
  getEntries: (date?: string) => api.get<DailyEntry[]>("/api/daily/entries", { params: { date } }),
  addEntry: (entry: Partial<DailyEntry>) => api.post("/api/daily/entries", entry),
  updateEntry: (id: string, entry: Partial<DailyEntry>) => api.put(`/api/daily/entries/${id}`, entry),
  deleteEntry: (id: string) => api.delete(`/api/daily/entries/${id}`),
  getBalance: () => api.get<BalanceData>("/api/daily/balance"),
  saveBalance: (data: BalanceData) => api.post("/api/daily/balance", data),
  getMonthlySummary: (year: number, month: number) =>
    api.get("/api/daily/summary", { params: { year, month } }),
  getMonthlyAnalysis: (year: number, month: number) =>
    api.get("/api/daily/monthly-analysis", { params: { year, month } }),
  getCardExpenseSummary: () =>
    api.get<CardExpenseSummary>("/api/daily/card-expense-summary"),
  getIncomeSummary: () =>
    api.get<CardExpenseSummary>("/api/daily/income-summary"),
  getYearlyOverview: (year: number, month: number) =>
    api.get<YearlyOverview>("/api/daily/yearly-overview", { params: { year, month } }),
  // 고정지출 (PG 전용 — FEATURE_PG_DAILY). effective_month = 해당 월 유효 규칙(매월 자동 반영).
  listFixedExpenses: (params: { effective_month?: string; year_month?: string; year?: string }) =>
    api.get<FixedExpense[]>("/api/daily/fixed-expenses", { params }),
  createFixedExpense: (data: Partial<FixedExpense>) => api.post("/api/daily/fixed-expenses", data),
  updateFixedExpense: (id: string, data: Partial<FixedExpense>) => api.put(`/api/daily/fixed-expenses/${id}`, data),
  deleteFixedExpense: (id: string, effective_month?: string) =>
    api.delete(`/api/daily/fixed-expenses/${id}`, { params: effective_month ? { effective_month } : {} }),
  copyFixedExpenses: (from_ym: string, to_ym: string) =>
    api.post("/api/daily/fixed-expenses/copy", null, { params: { from_ym, to_ym } }),
  // 신고/부가세 (PG 전용)
  getTaxSummary: (year_month: string) =>
    api.get<TaxSummary | Record<string, never>>("/api/daily/tax-summary", { params: { year_month } }),
  saveTaxSummary: (data: Partial<TaxSummary>) => api.put("/api/daily/tax-summary", data),
};

export interface FixedExpense {
  id: string;
  year_month: string;
  name: string;
  amount: number;
  category: string;
  payment_method: string;
  vat_included: boolean;
  vat_amount: number;
  memo: string;
  is_recurring: boolean;
  start_month: string;
  end_month: string;
}

export interface TaxSummary {
  year_month: string;
  reported_revenue: number;
  reported_expense: number;
  reported_output_vat: number;
  reported_input_vat: number;
  expected_vat_payable: number;
  vat_basis: "supply_price" | "tax_included";
  memo: string;
}

export interface CardExpenseSummary {
  today: number;
  month: number;
  today_date: string;
  month_prefix: string;
}

export interface YearlyMonthCell {
  month: number;
  sales: number;
  expense: number;
  net: number;
  card: number;
  count: number;
  fixed?: number;
  net_after_fixed?: number;
}
export interface YearlyAggRow {
  year: number;
  quarter?: number;
  sales: number;
  expense: number;
  net: number;
  card: number;
  count: number;
  avg: number;
  fixed?: number;
  net_after_fixed?: number;
}
// 기준일까지 누계 비교 / 일별·시간대 분석 (요구사항 1·3·5·6)
export interface PeriodSide {
  sales: number;
  net: number;
  expense: number;
  count: number;
}
export interface PeriodBlock {
  ref_day: number;
  prev_ref_day: number;
  days_in_month: number;
  is_current_month: boolean;
  is_future: boolean;
  cur: PeriodSide;
  prev: PeriodSide;
  avg_daily_sales: number;
  avg_daily_net: number;
  projected_sales: number;
  projected_net: number;
}
export interface DailyPoint {
  day: number;
  cur_sales: number;
  cur_net: number;
  prev_sales: number;
  prev_net: number;
  cur_cum_sales: number | null;
  cur_cum_net: number | null;
  prev_cum_sales: number;
  prev_cum_net: number;
  is_future: boolean;
}
export interface HourComparePoint {
  bucket: string;
  cur_sales: number;
  cur_net: number;
  cur_count: number;
  prev_sales: number;
  prev_net: number;
  prev_count: number;
}
// 업무군별 경영 진단 보고서 (business_insights)
export interface BizCategory {
  category: string;
  cur_count: number;
  cur_sales: number;
  cur_expense: number;
  cur_net: number;
  cur_margin: number | null;
  cur_avg_ticket: number;
  cur_net_per_case: number;
  prev_count: number;
  prev_sales: number;
  prev_net: number;
  prev_margin: number | null;
  has_prev: boolean;
  count_delta: number;
  count_delta_pct: number | null;
  sales_delta: number;
  sales_delta_pct: number | null;
  net_delta: number;
  net_delta_pct: number | null;
  margin_delta: number | null;
  controllability: string;
  risk_factors: string[];
  diagnosis: string;
  recommendation: string;
}
export interface BusinessInsights {
  summary: {
    best_margin_category: string | null;
    best_margin_value: number | null;
    worst_decline_category: string | null;
    worst_decline_net: number | null;
    focus_category: string | null;
    focus_margin: number | null;
  };
  total_comment: string;
  categories: BizCategory[];
  manual_issue: {
    status: "linked" | "not_linked" | "error";
    comment: string;
    related_changes: { version: string; detected_at: string; changed_page_count: number; candidate_count: number }[];
  };
  actions: string[];
}
export interface YearlyOverview {
  years: number[];
  selected: { year: number; month: number; quarter: number };
  pg_daily?: boolean;
  monthly_by_year: Record<string, YearlyMonthCell[]>;
  same_month: YearlyAggRow[];
  same_quarter: YearlyAggRow[];
  ytd: YearlyAggRow[];
  category_compare: { name: string; cur: number; prev: number; delta: number }[];
  tax?: { current: TaxSummary | null; prev: TaxSummary | null; auto_reported_sales?: number };
  diagnosis: { good: string[]; bad: string[] };
  // 신규 (요구사항 1·3·5·6)
  period?: PeriodBlock;
  daily_series?: DailyPoint[];
  hour_compare?: HourComparePoint[];
  analysis?: { good: string[]; bad: string[]; actions: string[] };
  business_insights?: BusinessInsights;
}

// 메모
export const memosApi = {
  get: (type: "short" | "mid" | "long") => api.get(`/api/memos/${type}`),
  save: (type: "short" | "mid" | "long", content: string) =>
    api.post(`/api/memos/${type}`, { content }),
};

// 일정 — per-date API (전체 시트 덮어쓰기 금지)
export const eventsApi = {
  get: () => api.get<Record<string, string[]>>("/api/events"),
  save: (dateStr: string, lines: string[]) =>
    api.post("/api/events", { date_str: dateStr, lines }),
  delete: (dateStr: string) => api.delete(`/api/events/${dateStr}`),
};

// 게시판
export const boardApi = {
  list: () => api.get<BoardPost[]>("/api/board"),
  create: (post: Partial<BoardPost>) => api.post("/api/board", post),
  update: (id: string, post: Partial<BoardPost>) => api.put(`/api/board/${id}`, post),
  delete: (id: string) => api.delete(`/api/board/${id}`),
  getComments: (postId: string) => api.get(`/api/board/${postId}/comments`),
  addComment: (postId: string, content: string) =>
    api.post(`/api/board/${postId}/comments`, { content }),
  deleteComment: (postId: string, commentId: string) =>
    api.delete(`/api/board/${postId}/comments/${commentId}`),
  getPopup: () => api.get<BoardPost[]>("/api/board/popup"),
  checkManual: () => api.get<{ updated: boolean; date: string; previous_date?: string }>("/api/board/check-manual"),
};

// 관리자
export const adminApi = {
  listAccounts: () => api.get("/api/admin/accounts"),
  updateAccount: (loginId: string, data: Record<string, unknown>) =>
    api.put(`/api/admin/accounts/${loginId}`, data),
  createAccount: (data: {
    login_id: string;
    password: string;
    office_name: string;
    contact_name?: string;
    contact_tel?: string;
    customer_sheet_key?: string;
    work_sheet_key?: string;
    folder_id?: string;
    is_admin?: boolean;
  }) => api.post("/api/admin/accounts", data),
  createWorkspace: (login_id: string, office_name: string) =>
    api.post<{
      ok: boolean;
      folder_id: string;
      customer_sheet_key: string;
      work_sheet_key: string;
      message?: string;
      warning?: string;
    }>("/api/admin/workspace", { login_id, office_name }),
  deleteAccount: (loginId: string) =>
    api.delete(`/api/admin/accounts/${loginId}`),
  restoreAccount: (loginId: string) =>
    api.post(`/api/admin/accounts/${loginId}/restore`),
  hardDeleteAccount: (loginId: string, confirmLoginId: string) =>
    api.delete(`/api/admin/accounts/${loginId}/hard`, { params: { confirm_login_id: confirmLoginId } }),
  // 행정사 주민등록번호 — 상태만 조회/저장(원문 미노출). 빈 값 저장 = 삭제.
  getAgentRrn: (loginId: string) =>
    api.get<{ has_agent_rrn: boolean; agent_rrn_last4: string }>(
      `/api/admin/accounts/${loginId}/agent-rrn`
    ),
  setAgentRrn: (loginId: string, agent_rrn: string) =>
    api.put<{ has_agent_rrn: boolean; agent_rrn_last4: string }>(
      `/api/admin/accounts/${loginId}/agent-rrn`, { agent_rrn }
    ),
};

// 업무참고
export const referenceApi = {
  listSheets: () => api.get<{ sheet_key: string; sheets: string[] }>("/api/reference/sheets"),
  getSheetData: (sheet: string) =>
    api.get<{ sheet: string; headers: string[]; rows: Record<string, string>[] }>(
      "/api/reference/data",
      { params: { sheet } }
    ),
};

// 문서 자동작성
export interface DocTree {
  categories: string[];
  minwon: Record<string, string[]>;
  types: Record<string, string[]>;
  subtypes: Record<string, string[]>;
}

export interface RequiredDocsResponse {
  key: string;
  main_docs: string[];
  agent_docs: string[];
}

export interface CustomerSearchResult {
  id: string;
  label: string;
  name: string;
  name_en?: string;
  /** 생년월일 (YYYY-MM-DD), 등록증 앞 6자리에서 추정 — 동명이인 구분용 */
  birth?: string;
  /** 전화번호 — 동명이인 구분용 */
  phone?: string;
  reg_no: string;
}

export interface FullDocGenRequest {
  category: string;
  minwon: string;
  kind: string;
  detail: string;
  applicant_id?: string;           // DB 고객 선택 시
  applicant_name?: string;         // 직접 이름 입력 시 (DB 미등록)
  accommodation_id?: string;
  guarantor_id?: string;
  guardian_id?: string;
  aggregator_id?: string;
  accommodation_name?: string;
  guarantor_name?: string;
  guardian_name?: string;
  aggregator_name?: string;
  selected_docs: string[];
  seal_applicant?: boolean;
  seal_accommodation?: boolean;
  seal_guarantor?: boolean;
  seal_guardian?: boolean;
  seal_aggregator?: boolean;
  seal_agent?: boolean;
  sign_applicant?: boolean;
  sign_accommodation?: boolean;
  sign_guarantor?: boolean;
  sign_guardian?: boolean;
  sign_aggregator?: boolean;
  sign_agent?: boolean;
  /** PDF 위젯 이름 → 값. generate-full 실행 후 편집 내용을 반영해 재생성할 때 사용. */
  direct_overrides?: Record<string, string>;
  /** 숙소제공자연결 탭 전체 데이터 — 관계/날짜/체크박스 매핑에 사용 */
  accommodation_provider?: AccommodationProvider | null;
  /** 신원보증인연결 탭 전체 데이터 — 보증인 b* 필드 자동 매핑에 사용 */
  guarantor_connection?: GuarantorConnection | null;
  /** 작성년/월/일 삽입 여부 (기본 true) */
  include_date?: boolean;
  /** 직접 지정 날짜 YYYY-MM-DD; 미지정 시 오늘 날짜 자동 삽입 */
  custom_date?: string;
  use_english_stamp?: boolean;  // true=신청인 도장에 영문 이니셜(성+명 첫글자), 기본 false=한글 도장
  // "acroform"(기본) | "field_ap"(보기안정형: 필드 유지+/AP 통일) | "overlay_legacy"(구 overlay, dev 전용)
  render_mode?: "acroform" | "field_ap" | "overlay_legacy" | "overlay";
}

export const quickDocApi = {
  getTree: () => api.get<DocTree>("/api/quick-doc/tree"),
  getRequiredDocs: (category: string, minwon: string, kind: string, detail: string, reg_no?: string) =>
    api.post<RequiredDocsResponse>("/api/quick-doc/required-docs", {
      category, minwon, kind, detail, reg_no: reg_no ?? "",
    }),
  searchCustomers: (q: string) =>
    api.get<CustomerSearchResult[]>("/api/quick-doc/customers/search", { params: { q } }),
  generateFull: (data: FullDocGenRequest) =>
    api.post("/api/quick-doc/generate-full", data, { responseType: "blob" }),
  generate: (data: {
    category: string;
    minwon: string;
    kind: string;
    detail: string;
    selected_docs: string[];
    customer_id?: string;
  }) => api.post("/api/quick-doc/generate", data, { responseType: "blob" }),
};

// 문서자동작성 설정(관리자 전용) — 편집형 선택 트리 + 필요서류 (Phase I-1J-6O)
export type DocNodeLevel = "category" | "petition" | "type" | "subtype";

export interface AdminReqDoc {
  id: number;
  name: string;
  doc_group: "main" | "agent";
  sort_order: number;
  is_active: boolean;
  template_filename: string;
  template_status: "mapped" | "missing";
}
export interface AdminDocNode {
  id: number;
  parent_id: number | null;
  level: DocNodeLevel;
  name: string;
  sort_order: number;
  is_active: boolean;
  docs?: AdminReqDoc[];
  subtypes?: AdminDocNode[];
  types?: AdminDocNode[];
  petitions?: AdminDocNode[];
}
export interface AdminDocTree {
  categories: AdminDocNode[];
}
export interface TemplateFile {
  filename: string;
  display_name: string;
  exists: boolean;
}

export const docConfigApi = {
  getTree: () => api.get<AdminDocTree>("/api/quick-doc/admin/tree"),
  getTemplates: () =>
    api.get<{ templates: TemplateFile[] }>("/api/quick-doc/admin/templates"),
  createNode: (data: { parent_id: number | null; level: DocNodeLevel; name: string; sort_order?: number }) =>
    api.post<AdminDocNode>("/api/quick-doc/admin/nodes", data),
  updateNode: (id: number, data: { name?: string; sort_order?: number; is_active?: boolean }) =>
    api.patch<AdminDocNode>(`/api/quick-doc/admin/nodes/${id}`, data),
  deleteNode: (id: number) => api.delete(`/api/quick-doc/admin/nodes/${id}`),
  createDoc: (data: {
    node_id: number; name: string; doc_group?: "main" | "agent";
    sort_order?: number; template_filename?: string;
  }) => api.post<AdminReqDoc>("/api/quick-doc/admin/required-documents", data),
  updateDoc: (id: number, data: {
    name?: string; doc_group?: "main" | "agent"; sort_order?: number;
    is_active?: boolean; template_filename?: string;
  }) => api.patch<AdminReqDoc>(`/api/quick-doc/admin/required-documents/${id}`, data),
  deleteDoc: (id: number) => api.delete(`/api/quick-doc/admin/required-documents/${id}`),
  remapDoc: (id: number) =>
    api.post<AdminReqDoc>(`/api/quick-doc/admin/required-documents/${id}/auto-map-template`),
};

// 통합검색
export interface SearchResult {
  id: string;
  type: "customer" | "task" | "board" | "reference" | "memo";
  title: string;
  summary: string;
  highlight?: string;
  url: string;
}

export interface SearchResponse {
  query: string;
  type: string;
  total: number;
  results: SearchResult[];
}

export const searchApi = {
  search: (q: string, type: string = "all") =>
    api.get<SearchResponse>("/api/search", { params: { q, type } }),
};

// ── OCR 스캔 ─────────────────────────────────────────────────────────────────

export interface ScanUpsertResult {
  status: "created" | "updated";
  고객ID: string;
  message: string;
}

export const scanApi = {
  /** OCR 결과를 고객 시트에 upsert (기존 고객이면 업데이트, 신규면 추가) */
  register: (data: Record<string, string>) =>
    api.post<ScanUpsertResult>("/api/scan/register", data),
};

// ── 메뉴얼 검색 ───────────────────────────────────────────────────────────────

export interface ManualSearchResult {
  question: string;
  answer: string;
}

export interface ManualAlert {
  id: number;
  manual: string;
  manual_kr: string;
  new_title: string;
  version_label: string;
  detected_at: string | null;
}

export const manualApi = {
  search: (q: string) =>
    api.get<ManualSearchResult>("/api/manual/search", { params: { q } }),
  // 사용자 알림용: 최신 매뉴얼 업데이트 식별자(비관리자 허용, 데이터 없으면 version=null)
  latest: () =>
    api.get<{ version: string | null; detected_at: string | null }>("/api/manual/latest"),
  // 매뉴얼 업데이트 알림(첨부 제목 변동) — 로그인 사용자 최초 1회 표시용(가벼운 조회)
  activeAlerts: () =>
    api.get<{ alerts: ManualAlert[]; is_admin: boolean }>("/api/manual/alerts/active"),
  dismissAlert: (eventId: number) =>
    api.post<{ ok: boolean }>(`/api/manual/alerts/${eventId}/dismiss`),
  runAlertDetect: () =>
    api.post<{ status: string; checked?: number; created?: number }>("/api/manual/alerts/run-detect"),
};

// ── 매뉴얼 업데이트: 관리자 최신 PDF 업로드(PG staging) ────────────────────────
export interface ManualUploadResult {
  manual: string;
  manual_kr: string;
  version: string;
  page_count: number;
  file_size: number;
  artifact_id: number | null;
  review_only: boolean;
  change_detection: string;          // "pending" — 변경감지는 별도 단계
  prior_uploads_removed: number;     // 새 업로드 시 정리된 이전 업로드본 수
  supports_change_detection: boolean;
}

export interface ManualDetectResult {
  status: string;                    // ok | baseline_init | no_diff
  manual: string;
  version: string;
  extracted_pages?: number;
  changed: number;
  candidates: number;
  message?: string;
}

export const manualUpdateApi = {
  uploadPdf: (manual: string, version: string, file: File, memo = "") => {
    const fd = new FormData();
    fd.append("manual", manual);
    fd.append("version", version);
    fd.append("memo", memo);
    fd.append("file", file);
    return api.post<ManualUploadResult>("/api/guidelines/manual-update/upload-pdf", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  detectChanges: (manual: string, version: string) =>
    api.post<ManualDetectResult>("/api/guidelines/manual-update/detect-changes", { manual, version }),
  promotePdf: (manual: string, version: string) =>
    api.post<{ ok: boolean; deployed_artifact_id: number; previous_count: number }>(
      "/api/guidelines/manual-update/promote-pdf", { manual, version }),
  listUploads: (manual = "") =>
    api.get<{ rows: Array<Record<string, unknown>> }>(
      "/api/guidelines/manual-update/uploads", { params: manual ? { manual } : {} }),
};

// ── 원클릭 작성 ──────────────────────────────────────────────────────────────

// Output types recognised by the one-click generator.
// Only "위임장" has a working backend path right now.
// Add entries here as new output types are implemented.
export type OneClickOutput =
  | "위임장"
  | "건강보험(세대합가)"
  | "건강보험(피부양자)"
  | "하이코리아"
  | "소시넷(등록증)"
  | "소시넷(여권)";

export interface QuickPoaRequest {
  kor_name: string;
  surname?: string;
  given?: string;
  stay_status?: string;
  reg6?: string;
  no7?: string;
  addr?: string;
  phone1?: string;
  phone2?: string;
  phone3?: string;
  passport?: string;
  customer_id?: string;
  site_id?: string;
  old_passport?: string;
  apply_applicant_seal?: boolean;
  apply_agent_seal?: boolean;
  apply_applicant_sign?: boolean;
  apply_agent_sign?: boolean;
  dpi?: number;
  ck_extension?: boolean;
  ck_registration?: boolean;
  ck_card?: boolean;
  ck_adrc?: boolean;
  ck_change?: boolean;
  ck_granting?: boolean;
  ck_ant?: boolean;
  /** Which one-click output types to generate. Default: ["위임장"]. */
  selected_outputs?: OneClickOutput[];
}

export const oneClickApi = {
  generate: (data: QuickPoaRequest) =>
    api.post("/api/quick-doc/quick-poa", data, { responseType: "blob" }),
};

// ── 실무지침 ──────────────────────────────────────────────────────────────────

export interface GuidelineSubType {
  label: string;
  condition: string;
  form_docs: string;
  supporting_docs: string;
  practical_notes?: string;
}

export interface ManualRef {
  manual: "체류민원" | "사증민원";
  page_from: number;
  page_to: number;
  match_text?: string;
  match_type?: "action_exact" | "action_prefix" | "section_only";
  section_pf?: number;
  section_pt?: number;
}

export interface GuidelineRow {
  row_id: string;
  domain: string;
  major_action_std: string;
  action_type: string;
  business_name: string;
  detailed_code: string;
  overview_short: string;
  form_docs: string;           // 사무소 준비서류 (| 구분)
  supporting_docs: string;     // 필요서류 / 고객 준비 (| 구분)
  exceptions_summary: string;
  fee_rule: string;
  basis_section: string;
  status: string;
  // 실무 확장 필드
  practical_notes?: string;    // 실무 주의사항 (| 구분)
  step_after?: string;         // 허가 후 다음 단계 (| 구분)
  apply_channel?: string;      // 신청 경로 안내
  sub_types?: GuidelineSubType[]; // 조건별 분기 (L4)
  manual_ref?: ManualRef[];    // 매뉴얼 PDF 페이지 매핑
  // 문서자동작성 딥링크용 (데이터 마이그레이션 후 채워짐)
  quickdoc_category?: string;
  quickdoc_minwon?: string;
  quickdoc_kind?: string;
  quickdoc_detail?: string;
  search_keys?: { key_type: string; key_value: string }[];
  related_rules?: Record<string, string>[];
  related_exceptions?: Record<string, string>[];
}

export interface GuidelineListResponse {
  total: number;
  page: number;
  limit: number;
  pages: number;
  data: GuidelineRow[];
}

export interface GuidelineEntryPoint {
  id: string;
  label: string;
  subtitle: string;
  codes: string;
  color: string;
  search_query: string;
  action_types: string[];
  count?: number;
}

export interface TbEvaluateRequest {
  nationality_iso3: string;
  action_type: string;
  detailed_code?: string;
  age?: number;
}

export interface TbEvaluateResult {
  required: boolean;
  stage: string | null;
  reason: string;
  is_high_risk_country: boolean;
  rule_id: string | null;
  instruction?: string;
}

// ── 마케팅 (홈페이지 게시물) ──────────────────────────────────────────────────

export interface MarketingPost {
  id: string;
  title: string;
  slug: string;
  category: string;
  summary: string;
  content: string;
  thumbnail_url: string;
  is_published: string;   // "TRUE" | "FALSE"
  is_featured: string;    // "TRUE" | "FALSE"
  created_by: string;
  created_at: string;
  updated_at: string;
  image_file_id?: string;
  image_url?: string;
  image_alt?: string;
  meta_description?: string;
  tags?: string;
}

export const marketingApi = {
  publicList: () => api.get<MarketingPost[]>("/api/marketing/posts"),
  adminList: () => api.get<MarketingPost[]>("/api/marketing/admin/posts"),
  create: (data: Omit<MarketingPost, "id" | "is_published" | "created_by" | "created_at" | "updated_at">) =>
    api.post<MarketingPost>("/api/marketing/admin/posts", data),
  update: (id: string, data: Partial<MarketingPost>) =>
    api.put<MarketingPost>(`/api/marketing/admin/posts/${id}`, data),
  delete: (id: string) => api.delete(`/api/marketing/admin/posts/${id}`),
  togglePublish: (id: string) =>
    api.patch<MarketingPost>(`/api/marketing/admin/posts/${id}/publish`),
  uploadImage: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    // /api/upload-image 는 Next.js API Route (app/api/upload-image/route.ts).
    // rewrites()를 통한 multipart 포워딩이 불안정하므로 이 경로를 사용.
    // Content-Type 헤더를 명시하지 않아야 axios가 boundary를 자동 생성함.
    return api.post<{ url: string; file_id: string }>("/api/upload-image", form);
  },
};

export const guidelinesApi = {
  search: (q: string, action_type?: string, page = 1, limit = 30) =>
    api.get<GuidelineListResponse>("/api/guidelines/search/query", {
      params: { q, action_type, page, limit },
    }),
  listByCode: (code: string) =>
    api.get<{ code: string; count: number; action_types: string[]; data: GuidelineRow[] }>(
      `/api/guidelines/code/${encodeURIComponent(code)}`
    ),
  list: (params?: { action_type?: string; domain?: string; page?: number; limit?: number; status?: string }) => {
    const search = new URLSearchParams();
    Object.entries(params ?? {}).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    });
    const query = search.toString();
    return api.get<GuidelineListResponse>(`/api/guidelines/${query ? `?${query}` : ""}`, {
      headers: { "X-Skip-Auth-Redirect": "1" },
    });
  },
  getDetail: (row_id: string) =>
    api.get<GuidelineRow>(`/api/guidelines/${row_id}`),
  stats: () =>
    api.get<{ version: string; updated_at: string; total_rows: number }>("/api/guidelines/stats"),
  // 트리 모드
  getEntryPoints: () =>
    api.get<{ total: number; data: GuidelineEntryPoint[] }>("/api/guidelines/tree/entry-points"),
  getTreeResults: (params: {
    category?: string; minwon?: string; kind?: string; detail?: string;
    action_type?: string; search_query?: string; page?: number; limit?: number;
  }) =>
    api.get<GuidelineListResponse>("/api/guidelines/tree/results", { params }),
  // TB 평가
  evaluateTb: (req: TbEvaluateRequest) =>
    api.post<TbEvaluateResult>("/api/guidelines/tb/evaluate", req),
  getTbCountries: () =>
    api.get<{ total: number; countries: string[] }>("/api/guidelines/tb/high-risk-countries"),
};

// ── 실무지침 분류 오버레이 (A+ 방식, PG 전용) ───────────────────────────────
export interface GuidelineCategory {
  id: number;
  parent_id: number | null;
  level: "major" | "middle" | "minor" | string;
  source_key: string;
  display_name: string;
  sort_order: number;
  is_active: boolean;
  is_custom: boolean;
}
export interface GuidelineCategoryOverlay {
  categories: GuidelineCategory[];
  overrides: Record<string, number>; // row_id → category_id
}

export const guidelineCategoriesApi = {
  // 조회(로그인 사용자). 관리자만 include_inactive 효과. 플래그 off면 409.
  list: (includeInactive = false) =>
    api.get<GuidelineCategoryOverlay>("/api/guideline-categories", {
      params: { include_inactive: includeInactive },
      headers: { "X-Skip-Auth-Redirect": "1" },
    }),
  create: (data: { level: string; parent_id?: number | null; display_name: string; sort_order?: number; is_active?: boolean }) =>
    api.post<GuidelineCategory>("/api/guideline-categories", data),
  update: (id: number, data: { display_name?: string; sort_order?: number; is_active?: boolean; parent_id?: number | null }) =>
    api.put<GuidelineCategory>(`/api/guideline-categories/${id}`, data),
  deactivate: (id: number) =>
    api.patch<GuidelineCategory>(`/api/guideline-categories/${id}/deactivate`),
  move: (id: number, parent_id: number | null, sort_order?: number) =>
    api.put<GuidelineCategory>(`/api/guideline-categories/${id}/move`, { parent_id, sort_order }),
  setOverride: (row_id: string, category_id: number) =>
    api.post("/api/guideline-categories/overrides", { row_id, category_id }),
  clearOverride: (row_id: string) =>
    api.delete(`/api/guideline-categories/overrides/${encodeURIComponent(row_id)}`),
  seedFromJson: () =>
    api.post<{ created: number; total_source_keys: number }>("/api/guideline-categories/seed-from-json"),
};

// ── 각종공인증 ──────────────────────────────────────────────────────────────────

export interface CertVendor {
  id: string; name: string; contact: string; memo: string;
  active: string; created_at: string; updated_at: string;
}
export interface CertDirection {
  id: string; name: string; sort_order: string;
  active: string; created_at: string; updated_at: string;
}
export interface CertGroup {
  id: string; group_name: string; aliases: string; default_direction: string;
  applicable_directions: string;
  sort_order: string; active: string; created_at: string; updated_at: string;
}
export interface CertRegion {
  id: string; name: string;
  applicable_directions: string; applicable_group_ids: string;
  sort_order: string; active: string; created_at: string; updated_at: string;
}
export interface CertPrice {
  id: string; vendor_id: string; group_id: string;
  direction: string; region: string; condition: string;
  price: string; possible: string; documents: string;
  lead_time: string; strength: string; risk: string;
  source: string; last_checked: string;
  created_at: string; updated_at: string;
}
export interface CertBootstrap {
  vendors: CertVendor[];
  directions: CertDirection[];
  groups: CertGroup[];
  regions: CertRegion[];
  prices: CertPrice[];
}

const CERT_BASE = "/api/certification-services";

export const certApi = {
  bootstrap: () => api.get<CertBootstrap>(`${CERT_BASE}/bootstrap`),

  createVendor: (data: Partial<CertVendor>) => api.post<CertVendor>(`${CERT_BASE}/vendors`, data),
  updateVendor: (id: string, data: Partial<CertVendor>) => api.put<CertVendor>(`${CERT_BASE}/vendors/${id}`, data),
  deleteVendor: (id: string) => api.delete<{ action: string; ref_count: number }>(`${CERT_BASE}/vendors/${id}`),

  createDirection: (data: Partial<CertDirection>) => api.post<CertDirection>(`${CERT_BASE}/directions`, data),
  updateDirection: (id: string, data: Partial<CertDirection>) => api.put<CertDirection>(`${CERT_BASE}/directions/${id}`, data),
  deleteDirection: (id: string) => api.delete(`${CERT_BASE}/directions/${id}`),

  createGroup: (data: Partial<CertGroup>) => api.post<CertGroup>(`${CERT_BASE}/groups`, data),
  updateGroup: (id: string, data: Partial<CertGroup>) => api.put<CertGroup>(`${CERT_BASE}/groups/${id}`, data),
  deleteGroup: (id: string) => api.delete(`${CERT_BASE}/groups/${id}`),

  createRegion: (data: Partial<CertRegion>) => api.post<CertRegion>(`${CERT_BASE}/regions`, data),
  updateRegion: (id: string, data: Partial<CertRegion>) => api.put<CertRegion>(`${CERT_BASE}/regions/${id}`, data),
  deleteRegion: (id: string) => api.delete(`${CERT_BASE}/regions/${id}`),

  createPrice: (data: Partial<CertPrice>) => api.post<CertPrice>(`${CERT_BASE}/prices`, data),
  updatePrice: (id: string, data: Partial<CertPrice>) => api.put<CertPrice>(`${CERT_BASE}/prices/${id}`, data),
  deletePrice: (id: string) => api.delete(`${CERT_BASE}/prices/${id}`),
};
