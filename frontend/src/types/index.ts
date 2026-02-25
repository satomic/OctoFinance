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

export interface DashboardData {
  kpi: DashboardKPI;
  daily_trend: { day: string; dau: number; wau: number; mau: number; interactions: number }[];
  feature_usage: { feature: string; interactions: number; code_gen: number; code_accept: number }[];
  model_usage: { model: string; interactions: number; code_gen: number; premium_requests: number }[];
  ide_usage: { ide: string; interactions: number; code_gen: number }[];
  top_users: { user: string; interactions: number; code_gen: number; days_active: number }[];
  orgs: string[];
  date_range: { start: string; end: string };
}
