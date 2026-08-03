export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  toolCalls?: ToolCallInfo[];
}

export interface ToolCallInfo {
  id: string;
  name: string;
  status: "running" | "complete";
}

export interface OrgInfo {
  login: string;
  avatar_url?: string;
  description?: string;
  has_copilot: boolean;
  plan_type?: string;
  price_per_seat?: number;
  total_seats?: number;
  active_seats?: number;
  enterprise?: string;
  pat_user?: string;
}

export interface PATInfo {
  id: string;
  label: string;
  token_masked: string;
  user_login: string;
  user_avatar: string;
  orgs: string[];
  enterprise_slugs: string[];
  include_organizations: boolean;
  created_at: string;
  last_synced_at: string;
}

export interface Overview {
  total_organizations: number;
  orgs_with_copilot: number;
  total_seats: number;
  total_active_seats: number;
  total_inactive_seats: number;
  utilization_pct: number;
  monthly_cost: number;
  monthly_waste: number;
  annual_waste: number;
}

export interface Recommendation {
  id: string;
  timestamp: string;
  org: string;
  type: string;
  affected_users: string[];
  description: string;
  estimated_monthly_savings: number;
  status: string;
}

export interface SSEEvent {
  type: "delta" | "message" | "tool_start" | "tool_complete" | "error" | "thinking_delta" | "usage";
  content: string;
  tool_call_id?: string;
  detail?: string;
}

export interface SessionInfo {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ConsoleEntry {
  id: string;
  timestamp: number;
  type: "tool_start" | "tool_complete" | "thinking" | "usage" | "error" | "user" | "assistant" | "sync";
  title: string;
  detail?: string;
}

// Dashboard types
export interface DashboardKPI {
  total_seats: number;
  active_seats: number;
  inactive_seats: number;
  utilization_pct: number;
  monthly_cost: number;
  monthly_waste: number;
}

export interface SeatRecord {
  user: string;
  avatar: string;
  org: string;
  plan_type: string;
  created_at: string;
  last_activity_at: string | null;
  last_activity_editor: string | null;
  pending_cancellation_date: string | null;
  team: string;
}

export interface SeatInfo {
  breakdown: { pending_invitation: number; pending_cancellation: number; added_this_cycle: number };
  plans: Record<string, number>;
  features: Record<string, string>;
  seats: SeatRecord[];
}

export interface DashboardData {
  kpi: DashboardKPI;
  seat_info: SeatInfo;
  daily_trend: {
    day: string; dau: number; wau: number; mau: number;
    chat_users: number; agent_users: number;
    interactions: number; code_gen: number; code_accept: number;
    loc_suggested: number; loc_accepted: number;
  }[];
  feature_usage: { feature: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number }[];
  model_usage: { model: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number; ai_credits: number }[];
  ide_usage: { ide: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number }[];
  language_usage: { language: string; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number }[];
  code_completions: { language: string; suggestions: number; acceptances: number; lines_suggested: number; lines_accepted: number; engaged_users: number }[];
  ai_credit_detail: { model: string; gross_qty: number; discount_qty: number; net_qty: number; gross_amount: number; net_amount: number }[];
  chat_stats: { ide_chats: number; ide_copy_events: number; ide_insertion_events: number; dotcom_chats: number; pr_summaries: number };
  top_users: { user: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number; days_active: number; used_agent: boolean; used_chat: boolean }[];
  orgs: string[];
  date_range: { start: string; end: string };
  user_ai_usage: AiUsage;
}

export interface AiUsageRecord {
  user: string;
  org: string;
  cost_center: string;
  requests: number;
  gross_amount: number;
  net_amount: number;
  days_active: number;
  quota: number;
  usage_pct: number;
  models: { model: string; requests: number }[];
}

export interface AiUsage {
  has_data: boolean;
  latest_date: string | null;
  users: AiUsageRecord[];
  daily_trend: { day: string; requests: number; amount: number; active_users: number }[];
  model_breakdown: { model: string; requests: number; amount: number; user_count: number }[];
  org_breakdown: { org: string; requests: number; amount: number; user_count: number }[];
  cost_center_breakdown: { cost_center: string; requests: number; amount: number; user_count: number }[];
  total_requests: number;
  total_cost: number;
}

export interface CsvTypeInfo {
  has_data: boolean;
  latest_date: string | null;
  earliest_date: string | null;
  file_count: number;
  total_records: number;
  orgs: string[];
  user_count: number;
}

export interface CsvInfo {
  ai_usage: CsvTypeInfo;
  usage_report: CsvTypeInfo;
}

export interface CsvUploadResult {
  status?: "ok" | "no_new_data";
  csv_type?: "ai_usage" | "usage_report";
  date_range?: { start: string; end: string };
  total_rows?: number;
  new_rows?: number;
  duplicates_skipped?: number;
  file_saved?: string;
  error?: string;
  status_code?: number;
}

// CSV Dashboard types
export interface AiUsageSection {
  has_data: boolean;
  date_range: { start: string; end: string };
  kpi: { total_requests: number; total_cost: number; unique_users: number; unique_orgs: number };
  daily_trend: { day: string; requests: number; amount: number; active_users: number }[];
  model_breakdown: { model: string; requests: number; amount: number; user_count: number }[];
  org_breakdown: { org: string; requests: number; amount: number; user_count: number }[];
  cost_center_breakdown: { cost_center: string; requests: number; amount: number; user_count: number }[];
  users: AiUsageRecord[];
}

export interface UsageReportUser {
  user: string;
  org: string;
  cost_center: string;
  gross_amount: number;
  net_amount: number;
  quantity: number;
  days_active: number;
  skus: { sku: string; amount: number }[];
}

export interface UsageReportSection {
  has_data: boolean;
  date_range: { start: string; end: string };
  kpi: { total_gross: number; total_net: number; total_discount: number; unique_users: number; unique_orgs: number };
  daily_trend: { day: string; gross_amount: number; net_amount: number; active_users: number }[];
  product_breakdown: { product: string; gross_amount: number; net_amount: number; quantity: number; user_count: number }[];
  sku_breakdown: { sku: string; gross_amount: number; net_amount: number; quantity: number; user_count: number }[];
  org_breakdown: { org: string; gross_amount: number; net_amount: number; user_count: number }[];
  cost_center_breakdown: { cost_center: string; gross_amount: number; net_amount: number; user_count: number }[];
  users: UsageReportUser[];
}

export interface CsvDashboardData {
  ai_usage: AiUsageSection;
  usage_report: UsageReportSection;
  filters: {
    orgs: string[];
    cost_centers: string[];
    products: string[];
    skus: string[];
  };
}

// Cost Center dashboard types
export interface CostCenterMember {
  login: string;
  avatar_url: string;
  html_url: string;
  source_type: "User" | "Org" | "Team";
  source_name: string;
}

export interface CostCenter {
  id: string;
  name: string;
  state: "active" | "archived";
  resources: { type: string; name: string }[];
  members: CostCenterMember[];
  member_count: number;
}

export interface UserCostCenterEntry {
  login: string;
  avatar_url: string;
  html_url: string;
  cost_centers: { name: string; id: string; source_type: string; source_name: string }[];
}

export interface CostCenterShareInfo {
  cc_id: string;
  cc_name: string;
  token: string;
  mode: "public" | "password";
  url: string;
  created_at: string;
  updated_at: string;
}

export interface CostCenterDashboardData {
  enterprises: { slug: string; name: string }[];
  selected_enterprise: string;
  enterprise_name: string;
  cost_centers: CostCenter[];
  total_cost_centers: number;
  total_unique_members: number;
  user_map: UserCostCenterEntry[];
  no_data: boolean;
}

export interface CostCenterOption {
  id: string;
  name: string;
  state: "active" | "archived";
  member_count: number;
}

export interface UnassignedCostCenterUser {
  login: string;
  avatar_url: string;
  html_url: string;
  orgs: string[];
  teams: string[];
  plan_types: string[];
  last_activity_at: string;
  last_activity_editor: string;
  seat_count: number;
}

export interface UnassignedCostCenterUsersData {
  enterprises: { slug: string; name: string }[];
  selected_enterprise: string;
  enterprise_name: string;
  cost_centers: CostCenterOption[];
  unassigned_users: UnassignedCostCenterUser[];
  total_unassigned: number;
  total_copilot_users: number;
  assigned_user_count: number;
  orgs: string[];
  no_data: boolean;
}

export interface AssignCostCenterUsersResult {
  status?: string;
  error?: string;
  enterprise?: string;
  cost_center?: { id: string; name: string };
  assigned_users?: string[];
}

// Budgets dashboard types
export interface Budget {
  id: string;
  budget_type: string;
  scope: string;
  entity_name: string;
  skus: string[];
  amount: number;
  consumed_amount: number | null;
  remaining_amount: number | null;
  usage_pct: number | null;
  prevent_further_usage: boolean;
  will_alert: boolean;
  alert_recipients: string[];
}

export interface BudgetsDashboardData {
  enterprises: { slug: string; name: string }[];
  selected_enterprise: string;
  enterprise_name: string;
  budgets: Budget[];
  total_budgets: number;
  total_amount: number;
  hard_limit_count: number;
  alerting_count: number;
  scope_breakdown: { scope: string; count: number; amount: number }[];
  scopes: string[];
  live?: boolean;
  period?: string;
  current_month?: { start: string; end: string };
  total_consumed: number;
  total_remaining: number;
  tracked_budgets: number;
  no_data: boolean;
}

// ---------------------------------------------------------------------------
// Auth / identity
// ---------------------------------------------------------------------------

export interface AuthUser {
  login: string;
  name: string;
  avatar_url: string;
  auth_type: "local" | "github";
  is_admin: boolean;
  github_id?: number | null;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
  user: AuthUser | null;
  is_admin: boolean;
  github_enabled: boolean;
  version?: string;
}

export interface GithubOAuthConfig {
  client_id: string;
  client_secret_set: boolean;
  client_secret_masked: string;
  callback_url: string;
  admins: string[];
  allow_all_users: boolean;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Budget requests
// ---------------------------------------------------------------------------

export type BudgetRequestStatus = "pending" | "approved" | "rejected";

export interface BudgetRequestHistoryEntry {
  action: string;
  by: string;
  at: string;
  amount?: number | null;
  comment?: string;
}

export interface GithubBudgetSync {
  status: "created" | "updated" | "failed" | "skipped";
  entity_type?: string;
  entity_name?: string;
  budget_id?: string;
  amount?: number;
  scope?: string;
  error?: string;
  reason?: string;
  synced_at?: string;
}

export interface BudgetRequest {
  id: string;
  user_login: string;
  user_name: string;
  avatar_url: string;
  requested_amount: number;
  approved_amount: number | null;
  currency: string;
  period: string;
  org: string;
  cost_center: string;
  reason: string;
  status: BudgetRequestStatus;
  created_at: string;
  updated_at: string;
  reviewed_by: string;
  reviewed_at: string;
  review_comment: string;
  history: BudgetRequestHistoryEntry[];
  github_budget?: GithubBudgetSync | null;
}

export interface BudgetAuditEntry {
  request_id: string;
  user_login: string;
  avatar_url: string;
  requested_amount: number;
  org: string;
  cost_center: string;
  reason: string;
  action: string;
  by: string;
  at: string;
  amount: number | null;
  comment: string;
  github_budget_status?: string | null;
  github_budget_error?: string | null;
}

/** A budget as reported by the GitHub Billing Budgets API. */
export interface UserBudget {
  id: string;
  scope: string;
  entity_type: string;
  entity_name: string;
  target_name: string;
  skus: string[];
  amount: number;
  consumed_amount: number | null;
  remaining_amount: number | null;
  usage_pct: number | null;
  prevent_further_usage: boolean;
  will_alert: boolean;
}

export interface MyCostCenter {
  id: string;
  name: string;
  enterprise: string;
  enterprise_name: string;
  state: string;
  ai_credit_pool_enabled: boolean;
  member_count: number;
  membership_source: string;
  membership_source_name: string;
  resources: { type: string; name: string }[];
  budget: UserBudget | null;
}

export interface BudgetRequestsData {
  requests: BudgetRequest[];
  is_admin: boolean;
  summary: {
    total: number;
    pending: number;
    approved: number;
    rejected: number;
    approved_amount: number;
    pending_amount: number;
  };
}

// ---------------------------------------------------------------------------
// Personal ("me") dashboard
// ---------------------------------------------------------------------------

export interface MySeat {
  org: string;
  plan_type: string;
  price_per_seat: number;
  created_at: string;
  last_activity_at: string;
  last_activity_editor: string;
  days_inactive: number | null;
  assigning_team: string;
  pending_cancellation_date: string | null;
}

export interface MyDashboardData {
  profile: AuthUser;
  seats: MySeat[];
  seat_summary: { seat_count: number; monthly_seat_cost: number; orgs: string[] };
  activity: {
    has_data: boolean;
    orgs: string[];
    kpi: {
      total_interactions: number;
      code_generated: number;
      code_accepted: number;
      acceptance_rate: number;
      active_days: number;
    };
    daily_trend: { day: string; interactions: number; generated: number; accepted: number }[];
    feature_breakdown: { feature: string; interactions: number; generated: number; accepted: number }[];
    language_breakdown: { language: string; generated: number; accepted: number; loc_added: number }[];
    model_breakdown: { model: string; generated: number; accepted: number }[];
    editor_breakdown: { ide: string; interactions: number; generated: number; accepted: number }[];
  };
  ai_usage: {
    has_data: boolean;
    org?: string;
    cost_center?: string;
    date_range: { start?: string; end?: string };
    kpi: {
      total_requests: number;
      total_cost: number;
      net_cost: number;
      quota: number;
      usage_pct: number;
      active_days: number;
      models_used: number;
    };
    daily_trend: { day: string; requests: number; amount: number }[];
    model_breakdown: { model: string; requests: number; amount: number }[];
  };
  spend: {
    has_data: boolean;
    date_range: { start?: string; end?: string };
    kpi: { total_gross: number; total_net: number; active_days: number };
    daily_trend: { day: string; gross_amount: number; net_amount: number }[];
    sku_breakdown: { sku: string; gross_amount: number; net_amount: number; quantity: number }[];
    product_breakdown: { product: string; gross_amount: number; net_amount: number; quantity: number }[];
  };
  period: { mode: "all" | "current_month"; date_from: string; date_to: string; label: string };
  budget: {
    live: boolean;
    personal: UserBudget | null;
    universal: UserBudget | null;
    effective: UserBudget | null;
    effective_source: "personal" | "universal" | null;
    amount: number;
    consumed: number;
    consumed_source: "github" | "usage_data";
    remaining: number | null;
    usage_pct: number | null;
    error?: string;
  };
  cost_centers: MyCostCenter[];
  totals: {
    monthly_seat_cost: number;
    ai_credit_cost: number;
    estimated_total: number;
    budget_amount: number;
    budget_remaining: number | null;
  };
  budget_requests: BudgetRequest[];
  has_any_data: boolean;
}
