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
  model_usage: { model: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number; premium_requests: number }[];
  ide_usage: { ide: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number }[];
  language_usage: { language: string; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number }[];
  code_completions: { language: string; suggestions: number; acceptances: number; lines_suggested: number; lines_accepted: number; engaged_users: number }[];
  premium_detail: { model: string; gross_qty: number; discount_qty: number; net_qty: number; gross_amount: number; net_amount: number }[];
  chat_stats: { ide_chats: number; ide_copy_events: number; ide_insertion_events: number; dotcom_chats: number; pr_summaries: number };
  top_users: { user: string; interactions: number; code_gen: number; code_accept: number; loc_suggested: number; loc_accepted: number; days_active: number; used_agent: boolean; used_chat: boolean }[];
  orgs: string[];
  date_range: { start: string; end: string };
  user_premium_usage: UserPremiumUsage;
}

export interface UserPremiumRecord {
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

export interface UserPremiumUsage {
  has_data: boolean;
  latest_date: string | null;
  users: UserPremiumRecord[];
  daily_trend: { day: string; requests: number; amount: number; active_users: number }[];
  model_breakdown: { model: string; requests: number; amount: number; user_count: number }[];
  org_breakdown: { org: string; requests: number; amount: number; user_count: number }[];
  cost_center_breakdown: { cost_center: string; requests: number; amount: number; user_count: number }[];
  total_requests: number;
  total_cost: number;
}

export interface PremiumCsvInfo {
  has_data: boolean;
  latest_date: string | null;
  earliest_date: string | null;
  file_count: number;
  total_records: number;
  orgs: string[];
  user_count: number;
}
