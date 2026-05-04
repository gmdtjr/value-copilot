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
