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
  }
  return config;
});

// 응답 인터셉터: 401이면 로그인 페이지로
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      if (typeof window !== "undefined") {
        localStorage.removeItem("access_token");
        localStorage.removeItem("user_info");
        document.cookie = "kid_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
        window.location.href = "/login";
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
  list: (search?: string) => api.get("/api/customers", { params: { search } }),
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
