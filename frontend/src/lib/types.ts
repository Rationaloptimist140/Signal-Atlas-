export type DataSource = "live_github" | "demo_fixture";
export type Confidence = "low" | "medium" | "high";
export type Basis = "verified_fact" | "calculated_metric" | "interpretation" | "hypothesis";

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type Plan = {
  key: string; name: string; price_gbp_month: number | null; price_gbp_year: number | null; purchasable: boolean; tagline: string;
  watchlist_items: number | null; competitors: number | null; reports_per_month: number | null; live_syncs_per_month: number | null;
  api_keys: number | null; api_requests_per_month: number | null; api_rate_per_minute: number;
  ai_enrichment: boolean; custom_scoring_weights: boolean; seats: number | null;
};

export type Me = {
  user: { id: number; email: string; full_name: string; job_title: string | null; has_password: boolean; created_at: string; email_verified: boolean };
  email: { verification_required: boolean; delivery_configured: boolean };
  organisation: { id: number; name: string; slug: string };
  role: "owner" | "admin" | "analyst" | "viewer";
  plan: Plan;
  csrf_token: string;
  github: { connected: boolean; login: string | null; avatar_url: string | null; scopes: string | null; oauth_configured: boolean };
};

export type Repository = {
  id: number; full_name: string; owner_login: string; owner_type: string | null; name: string; description: string | null;
  html_url: string | null; homepage: string | null; primary_language: string | null; license_spdx: string | null; license_name: string | null;
  topics: string[]; category: string | null; stars: number; forks: number; watchers: number | null; open_issues: number | null;
  closed_issues: number | null; open_prs: number | null; merged_prs: number | null; contributors_count: number | null; is_fork: boolean;
  archived: boolean; parent_full_name: string | null; created_at_github: string | null; pushed_at_github: string | null;
  data_source: DataSource; sync_level: "search" | "full"; missing_data: string[]; last_synced_at: string | null; first_seen_at: string;
  score?: number | null; score_confidence?: Confidence | null; opportunity_id?: number | null;
};

export type Evidence = { label: string; value: string; kind: "verified" | "calculated" | "inferred"; source_url: string | null };

export type Metric = {
  key: string; label: string; score: number | null; explanation: string; evidence: Evidence[]; missing: string[]; confidence: number; weight: number;
};

export type Score = {
  total: number; raw_total?: number; default_total: number; metrics: Metric[]; weights: Record<string, number>; custom_weights: boolean; confidence: Confidence;
  confidence_value: number; coverage: number; missing: string[];
  data_freshness: { last_synced_at: string | null; age_hours: number | null; status: string };
  computed_at: string; methodology_note: string; history?: { date: string; total_default: number }[];
};

export type Signal = {
  id: number; repository_id: number | null; repository_full_name: string | null; category: string | null; signal_type: string;
  time_window: "daily" | "weekly" | "monthly"; strength: number; confidence: Confidence; title: string; summary: string;
  evidence: Evidence[]; data_source: DataSource; detected_at: string;
};

export type Opportunity = {
  id: number; repository_id: number; repository_full_name: string | null; repository_html_url: string | null; title: string;
  category: string | null; summary: string; score: number; confidence: Confidence; risk_level: "low" | "medium" | "high";
  maturity: string; data_source: DataSource; updated_at: string; recommended_action: string | null; stars: number | null;
  primary_language: string | null; license_spdx: string | null; metrics: { key: string; label: string; score: number | null }[];
};

export type Statement = { text: string; basis: Basis; severity?: string; source_url?: string | null; model?: string; maturity?: string };

export type Analysis = {
  problem: Statement; target_customers: Statement[]; demand_indicators: Statement[]; commercial_applications: Statement[];
  monetisation: Statement[]; enterprise_applications: Statement[];
  adjacent_projects: { repository_id: number; full_name: string; stars: number; note: string }[];
  differentiation: Statement[]; technical_feasibility: Statement; licensing_risks: Statement[]; commercialisation_risks: Statement[];
  risk_level: string; recommended_action: { key: string; text: string }; recommended_next_steps: string[]; disclaimer: string;
};

export type Developer = {
  id: number; login: string; account_type: string; name: string | null; avatar_url: string | null; html_url: string | null;
  company: string | null; location: string | null; bio: string | null; followers: number | null; following: number | null;
  public_repos: number | null; created_at_github: string | null; data_source: DataSource; sync_level: string; last_synced_at: string | null;
  tracked_repositories?: number; tracked_contributions?: number; top_languages?: string[];
};

export type ReportStatement = { text: string; generated_by: "rules" | "ai"; confidence?: Confidence; references?: string[]; topic?: string };
export type Fact = { id: string; label: string; value: string; kind: string; source_url: string | null; explanation: string | null };

export type ReportContent = {
  report_type: string; subject: Record<string, unknown>; executive_summary: { text: string; generated_by: "rules" | "ai" };
  verified_facts: Fact[]; calculated_metrics: Fact[]; interpretations: ReportStatement[]; hypotheses: ReportStatement[];
  commercial_use_cases: ReportStatement[]; score: Score | null; analysis: Analysis | null;
  recommended_next_steps: { text: string; generated_by: "rules" | "ai" }[]; sources: { label: string; url: string }[];
  provenance: {
    generated_at: string; provider: string; model: string | null; ai_enriched: boolean; ai_error: string | null;
    guardrails: { statements_removed: number } | null; data_source: DataSource; legend: Record<string, string>;
  };
  disclaimer: string;
};

export type Report = {
  id: number; report_type: string; subject_type: string; subject_id: number; title: string; status: string; provider: string;
  model: string | null; data_source: DataSource; created_at: string; updated_at: string; summary: string | null; content: ReportContent | null;
};

export type Dashboard = {
  summary: Record<string, number>; summary_definitions: Record<string, string>;
  provenance: {
    mode: "empty" | "live" | "demo" | "mixed"; showing: string; live_repositories: number; demo_repositories: number;
    fully_synced_repositories: number; last_synced_at: string | null; message: string;
  };
  signals: Signal[]; top_opportunities: Opportunity[];
  setup: { github_token_configured: boolean; github_oauth_configured: boolean; llm_configured: boolean; llm_provider: string };
};

export type WatchlistEntry = {
  id: number; item_type: "repository" | "opportunity" | "developer"; item_id: number; note: string | null; created_at: string;
  available: boolean; title: string; subtitle: string | null; link: string | null; data_source?: DataSource; stars?: number; score?: number;
};
export type Watchlist = { id: number; name: string; description: string | null; created_at: string; items: WatchlistEntry[] };

export type BillingState = {
  provider: string; checkout_available: boolean; webhooks_configured: boolean; test_mode: boolean | null; payments_live: boolean;
  self_serve_plan_change: boolean; currency: string; grace_days: number; message: string;
};
export type PlanCatalogue = { plans: Plan[]; intervals: string[]; billing: BillingState; note: string };
export type SubscriptionInfo = {
  plan: Plan; subscribed_plan: Plan; status: "pending" | "active" | "past_due" | "cancelled" | "expired"; billing_interval: "month" | "year" | null; provider: string;
  current_period_start: string | null; current_period_end: string | null; cancel_at_period_end: boolean; cancelled_at: string | null; grace_until: string | null;
  manageable: boolean; usage: { key: string; label: string; used: number; limit: number | null }[]; billing: BillingState;
};
export type PaymentRow = {
  id: number; amount_minor: number; refunded_minor: number; currency: string; status: string; plan: string | null; billing_interval: string | null;
  description: string | null; receipt_url: string | null; paid_at: string | null; created_at: string;
};
