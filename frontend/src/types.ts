export type Market = 'US_Stock' | 'KR_Stock'
export type TickerStatus = 'portfolio' | 'watchlist'
export type ThesisStatus = 'draft' | 'confirmed' | 'needs_review' | 'retired'
export type StockType = 'compounding' | 'growth' | 'asset_play' | 'turnaround' | 'cyclical' | 'special_situation'

export interface Ticker {
  id: string
  symbol: string
  name: string
  market: Market
  status: TickerStatus
  daily_alert: boolean
  thesis_status: ThesisStatus | null
  has_content: boolean
  created_at: string
  portfolio_quantity: number | null
  portfolio_avg_price: number | null
  portfolio_current_price: number | null
  portfolio_daily_pct: number | null
  portfolio_pnl_pct: number | null
  valley_url?: string | null
  open_cycle_opened_at?: string | null  // 진행 중인 InvestmentCycle 시작일
}

export interface Thesis {
  id: string
  ticker_id: string
  confirmed: ThesisStatus
  confirmed_at: string | null
  thesis: string | null
  risk: string | null
  key_assumptions: string | null
  valuation: string | null
  last_analyzed_at: string | null
  stock_type: StockType | null
  seed_memo: string | null
  // Phase 2
  version_number: number
  parent_version_id: string | null
  key_logic: string | null
  monitoring_contract: string | null
  exploration_note: string | null
  retired_at: string | null
  retirement_reason: string | null
}

export interface SecSummary {
  filing_type: string
  report_period: string
  filing_url: string | null
  business_summary: string | null
  risk_summary: string | null
  mda_summary: string | null
  summarized_at: string
}

export interface FinancialData {
  company_info: string
  income_table: string
  cf_table: string
  bs_table: string
  key_metrics_text: string
  news_text: string
  insider_text: string
  metrics: Record<string, number | string | null>
  income: Record<string, unknown>[]
  cache_info: Record<string, { fetched_at: string; expires_at: string }>
  sec_summaries: SecSummary[]
}

export interface ReportComment {
  id: string
  report_id: string
  content: string
  created_at: string
}

export type SseEvent =
  | { type: 'start'; symbol: string }
  | { type: 'chunk'; text: string }
  | { type: 'complete'; sections: Record<string, string> }
  | { type: 'error'; message: string }

export type ExitReasonType = 'logic_broken' | 'target_reached' | 'better_opportunity' | 'mistake' | 'other'

export interface InvestmentCycle {
  id: string
  ticker_id: string
  ticker_symbol: string | null
  ticker_name: string | null
  thesis_id: string | null
  thesis_key_logic: string | null
  status: 'open' | 'closed'
  opened_at: string
  closed_at: string | null
  exit_reason: ExitReasonType | null
  exit_reason_note: string | null
  pnl_pct: number | null
  has_retrospective: boolean
}

export interface Retrospective {
  id: string
  cycle_id: string
  is_draft: boolean
  original_logic: string
  what_changed: string | null
  logic_held: boolean | null
  weak_link: string | null
  if_wrong_why: string | null
  if_right_why: string | null
  next_time: string | null
  completed_at: string | null
}

export type VerdictType = 'strengthening' | 'intact' | 'weakening' | 'broken'

export interface BreakSignal {
  id: string
  thesis_id: string
  ticker_id: string | null
  ticker_symbol: string | null
  ticker_name: string | null
  checked_at: string
  key_logic_snapshot: string | null
  observations: string
  positive_signals: string | null
  negative_signals: string | null
  watch_items: string | null
  verdict: VerdictType | null
  human_note: string | null
  reviewed_at: string | null
}

export type ConversationImportType = 'discovery' | 'thesis_challenge' | 'portfolio_review' | 'deep_analysis'

export interface ConversationImport {
  id: string
  ticker_id: string | null
  ticker_symbol: string | null
  ticker_name: string | null
  import_type: ConversationImportType
  summary: string
  raw_excerpt: string | null
  created_at: string
}

export type HumanResponseType = 'agree' | 'disagree' | 'partial' | 'override' | 'note'
export type HumanResponseTargetType = 'report' | 'thesis' | 'break_signal' | 'retrospective'

export interface HumanResponse {
  id: string
  target_type: HumanResponseTargetType
  target_id: string
  section_key: string | null
  response_type: HumanResponseType
  content: string
  recorded_at: string
}
