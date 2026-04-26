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
        localStorage.removeItem("access_token");
        localStorage.removeItem("user_info");
        document.cookie = "kid_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
        // 만료 경고 플래그 — 로그인 페이지에서 "장시간 미이용으로 로그아웃" 메시지 표시용
        try { sessionStorage.setItem("auth_expired", "1"); } catch { /* sessionStorage 차단 환경 무시 */ }
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
};

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
};

// 메모
export const memosApi = {
  get: (type: "short" | "mid" | "long") => api.get(`/api/memos/${type}`),
  save: (type: "short" | "mid" | "long", content: string) =>
    api.post(`/api/memos/${type}`, { content }),
};

// 일정
export const eventsApi = {
  get: () => api.get<Record<string, string[]>>("/api/events"),
  save: (events: { date_str: string; event_text: string }[]) =>
    api.post("/api/events", { events }),
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
  /** PDF 위젯 이름 → 값. generate-full 실행 후 편집 내용을 반영해 재생성할 때 사용. */
  direct_overrides?: Record<string, string>;
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

export const manualApi = {
  search: (q: string) =>
    api.get<ManualSearchResult>("/api/manual/search", { params: { q } }),
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
  | "소시넷";

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
  apply_applicant_seal?: boolean;
  apply_agent_seal?: boolean;
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
