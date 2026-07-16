export type Role = "admin" | "operator" | "viewer";

export type OrderStatus = "new" | "viewed" | "contacted" | "irrelevant" | "archived";

export interface Order {
  id: string;
  message_id: string;
  source_id: string;
  project_type: string | null;
  title: string | null;
  summary: string | null;
  budget_from: string | null;
  budget_to: string | null;
  budget_currency: string | null;
  budget_negotiable: boolean;
  deadline: string | null;
  deadline_text: string | null;
  contacts: Record<string, string[]> | null;
  published_at: string;
  relevance_score: number;
  status: OrderStatus;
  is_fresh: boolean;
  version: number;
  message_url: string | null;
}

export interface OrderListResponse {
  items: Order[];
  total: number;
  page: number;
  size: number;
}

export interface OrderFilters {
  q?: string;
  status?: OrderStatus;
  project_type?: string;
  relevance_min?: number;
  source_id?: string;
  budget_min?: number;
  budget_max?: number;
  date_from?: string;
  date_to?: string;
  page?: number;
  size?: number;
}

export interface Source {
  id: string;
  tg_peer_id: number | null;
  username: string | null;
  normalized_username: string | null;
  title: string | null;
  type: string;
  is_public: boolean;
  enabled: boolean;
  access_status: string;
  activity_score: number;
  activity_status: string;
  poll_mode: string;
  participants_count: number | null;
  last_seen_message_id: number;
  last_checked_at: string | null;
  pause_until: string | null;
  created_at: string;
  updated_at: string;
}

export interface SourceListResponse {
  items: Source[];
  total: number;
  page: number;
  size: number;
}

export interface Keyword {
  id: string;
  phrase: string;
  lang: string;
  weight: number;
  category: string;
  is_regex: boolean;
  enabled: boolean;
}

export interface NegativeKeyword {
  id: string;
  phrase: string;
  lang: string;
  weight: number;
  is_regex: boolean;
  enabled: boolean;
}

export interface KeywordPayload {
  phrase: string;
  lang: string;
  weight: number;
  category?: string;
  is_regex: boolean;
  enabled: boolean;
}

export interface StatsSummary {
  orders_total: number;
  sources_total: number;
  classes: Record<string, number>;
  order_statuses: Record<string, number>;
}

export interface Favorite {
  id: string;
  order_id: string;
  created_at: string;
  order: Order | null;
}

export interface Subscription {
  id: string;
  user_id: string;
  name: string;
  enabled: boolean;
  min_relevance_score: number | null;
  project_types: string[];
  budget_min: string | null;
  budget_max: string | null;
  currencies: string[];
  source_ids: string[];
  positive_keywords: string[];
  negative_keywords: string[];
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  timezone: string;
  freshness_days: number | null;
  max_notifications_per_period: number | null;
  rate_limit_period_minutes: number;
  similar_cooldown_minutes: number | null;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionPayload {
  name: string;
  enabled: boolean;
  min_relevance_score?: number | null;
  project_types: string[];
  budget_min?: string | null;
  budget_max?: string | null;
  currencies: string[];
  source_ids: string[];
  positive_keywords: string[];
  negative_keywords: string[];
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  timezone: string;
  freshness_days?: number | null;
  max_notifications_per_period?: number | null;
  rate_limit_period_minutes: number;
  similar_cooldown_minutes?: number | null;
  tg_chat_id?: number | null;
}
