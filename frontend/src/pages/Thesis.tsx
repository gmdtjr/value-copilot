import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, Sparkles, CheckCircle, AlertTriangle,
  ChevronDown, ChevronUp, Loader2, FileText, Bell, MessageSquare, RefreshCw,
  Database, BarChart2, ExternalLink,
} from 'lucide-react'
import { api } from '../api'
import { fmtKST } from '../utils/date'
import type { Thesis, Ticker, FinancialData, SecSummary } from '../types'

type DataStatus = {
  has_data: boolean
  fetched_at: string | null
  expires_at: string | null
  sec_summaries: number
}

const THESIS_SECTIONS = [
  { key: 'thesis', label: '투자 논거 (Thesis)' },
  { key: 'risk', label: '리스크 (Risk)' },
  { key: 'key_assumptions', label: '핵심 가정 (Key Assumptions)' },
  { key: 'valuation', label: '밸류에이션 (Valuation)' },
] as const

type ThesisSectionKey = (typeof THESIS_SECTIONS)[number]['key']
type AnalyzeState = 'idle' | 'streaming' | 'done' | 'error'
type RefineState = 'idle' | 'streaming' | 'done' | 'error'
type ActiveTab = 'thesis' | 'data' | 'reports'

// ── Ticker Reports Tab ────────────────────────────────────────────────────────

type TickerReport = { id: string; type: string; content: string; created_at: string }

const REPORT_SECTIONS: Record<string, { key: string; label: string }[]> = {
  analysis: [
    { key: 'business_overview', label: '1. 기업 개요' },
    { key: 'moat_analysis', label: '2. 경쟁우위 (Moat)' },
    { key: 'financial_analysis', label: '3. 재무 심층 분석' },
    { key: 'management_quality', label: '4. 경영진 & 자본배분' },
    { key: 'valuation', label: '5. 밸류에이션' },
    { key: 'risk_matrix', label: '6. 리스크 매트릭스' },
    { key: 'recent_developments', label: '7. 최근 동향' },
    { key: 'investment_conclusion', label: '8. 투자 결론' },
  ],
}

function extractSection(content: string, key: string) {
  const m = content.match(new RegExp(`<section name="${key}">(.*?)</section>`, 's'))
  return m ? m[1].trim() : ''
}

function ReportAccordion({ report }: { report: TickerReport }) {
  const sections = REPORT_SECTIONS[report.type]
  const hasSections = sections?.some(({ key }) => extractSection(report.content, key))
  const [open, setOpen] = useState<Set<string>>(new Set(['business_overview', 'investment_conclusion']))

  if (!sections || !hasSections) {
    return (
      <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
        {report.content}
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {sections.map(({ key, label }) => {
        const text = extractSection(report.content, key)
        if (!text) return null
        const isOpen = open.has(key)
        return (
          <div key={key} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => setOpen(prev => { const s = new Set(prev); isOpen ? s.delete(key) : s.add(key); return s })}
              className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-800 hover:bg-gray-750 transition-colors"
            >
              <span className="text-white text-sm font-medium">{label}</span>
              {isOpen ? <ChevronUp size={14} className="text-gray-400 flex-shrink-0" /> : <ChevronDown size={14} className="text-gray-400 flex-shrink-0" />}
            </button>
            {isOpen && (
              <div className="px-4 py-4 bg-gray-900 border-t border-gray-700">
                <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">{text}</div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function TickerReportsTab({ tickerId }: { tickerId: string }) {
  const [reports, setReports] = useState<TickerReport[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<TickerReport | null>(null)

  useEffect(() => {
    fetch(`/api/tickers/${tickerId}/reports`)
      .then(r => r.ok ? r.json() : [])
      .then((data: TickerReport[]) => { setReports(data); if (data.length) setSelected(data[0]) })
      .finally(() => setLoading(false))
  }, [tickerId])

  if (loading) return <div className="flex items-center justify-center py-20 text-gray-500 gap-2"><Loader2 size={16} className="animate-spin" /> 불러오는 중...</div>

  if (reports.length === 0) return (
    <div className="text-center py-20 text-gray-600">
      <FileText size={40} className="mx-auto mb-3 text-gray-700" />
      <p className="text-gray-500">아직 생성된 보고서가 없습니다.</p>
      <p className="text-sm mt-1">헤더의 "보고서" 버튼으로 생성하세요.</p>
    </div>
  )

  return (
    <div className="space-y-3">
      {/* 보고서 선택 목록 */}
      <div className="flex gap-2 flex-wrap">
        {reports.map((r, idx) => {
          const isLatest = idx === 0
          return (
            <button
              key={r.id}
              onClick={() => setSelected(r)}
              className={`text-left px-3 py-2 rounded-lg border text-xs transition-colors ${
                selected?.id === r.id
                  ? 'bg-gray-700 border-gray-500 text-white'
                  : 'bg-gray-900 border-gray-700 text-gray-400 hover:border-gray-600'
              }`}
            >
              <span className="block font-medium">{fmtKST(r.created_at, 'date')}</span>
              <span className="text-gray-500">{fmtKST(r.created_at, 'time')}</span>
              {isLatest && <span className="ml-1 text-emerald-400">●</span>}
            </button>
          )
        })}
      </div>

      {/* 선택된 보고서 본문 */}
      {selected && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 mb-4">
            {fmtKST(selected.created_at)}
          </p>
          <ReportAccordion report={selected} />
        </div>
      )}
    </div>
  )
}

// ── Financial Data Tab ────────────────────────────────────────────────────────

function fmt(val: number | string | null | undefined, type: 'x' | 'pct' | 'price' | 'cap'): string {
  if (val == null || val === '') return 'N/A'
  const n = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(n)) return 'N/A'
  if (type === 'x') return `${n.toFixed(1)}x`
  if (type === 'pct') return `${(n * 100).toFixed(1)}%`
  if (type === 'price') return n.toLocaleString()
  if (type === 'cap') {
    const abs = Math.abs(n)
    if (abs >= 1e12) return `${(n / 1e12).toFixed(1)}T`
    if (abs >= 1e9) return `${(n / 1e9).toFixed(1)}B`
    if (abs >= 1e6) return `${(n / 1e6).toFixed(1)}M`
    return n.toLocaleString()
  }
  return String(n)
}

function MetricCard({ label, value }: { label: string; value: string }) {
  const isNA = value === 'N/A'
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg px-4 py-3 min-w-0">
      <p className="text-xs text-gray-500 mb-1 truncate">{label}</p>
      <p className={`text-base font-semibold ${isNA ? 'text-gray-600' : 'text-white'}`}>{value}</p>
    </div>
  )
}

function DataSection({
  title, defaultOpen = false, children,
}: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-800/50 transition-colors"
      >
        <span className="text-white font-medium text-sm">{title}</span>
        {open ? <ChevronUp size={15} className="text-gray-400 flex-shrink-0" /> : <ChevronDown size={15} className="text-gray-400 flex-shrink-0" />}
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-gray-800">
          <div className="pt-4">{children}</div>
        </div>
      )}
    </div>
  )
}

function PreText({ text }: { text: string }) {
  return (
    <pre className="text-gray-300 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words">
      {text.trim() || '데이터 없음'}
    </pre>
  )
}

function SecSummaryCard({ s }: { s: SecSummary }) {
  const [open, setOpen] = useState(false)
  const subsections = [
    { label: '사업 개요', text: s.business_summary },
    { label: '위험요소', text: s.risk_summary },
    { label: 'MD&A / 경영 현황', text: s.mda_summary },
  ]
  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden mb-2 last:mb-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-800/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-blue-400 bg-blue-900/30 px-2 py-0.5 rounded">
            {s.filing_type}
          </span>
          <span className="text-sm text-gray-200">{s.report_period}</span>
          <span className="text-xs text-gray-500">
            {fmtKST(s.summarized_at, 'date')}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {s.filing_url && (
            <a
              href={s.filing_url}
              target="_blank"
              rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="text-gray-500 hover:text-gray-300"
            >
              <ExternalLink size={13} />
            </a>
          )}
          {open ? <ChevronUp size={14} className="text-gray-400" /> : <ChevronDown size={14} className="text-gray-400" />}
        </div>
      </button>
      {open && (
        <div className="border-t border-gray-700 divide-y divide-gray-700/50">
          {subsections.map(({ label, text }) => text ? (
            <div key={label} className="px-4 py-3">
              <p className="text-xs font-medium text-gray-400 mb-2">{label}</p>
              <p className="text-xs text-gray-300 leading-relaxed whitespace-pre-wrap">{text}</p>
            </div>
          ) : null)}
        </div>
      )}
    </div>
  )
}

function FinancialDataTab({
  tickerId, hasData, market,
}: { tickerId: string; hasData: boolean; market: string }) {
  const [data, setData] = useState<FinancialData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!hasData) return
    setLoading(true)
    api.getFinancialData(tickerId)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [tickerId, hasData])

  if (!hasData) {
    return (
      <div className="text-center py-20 text-gray-600">
        <Database size={40} className="mx-auto mb-3 text-gray-700" />
        <p className="text-gray-500">재무 데이터가 없습니다.</p>
        <p className="text-sm mt-1">헤더의 "데이터 수집" 버튼으로 먼저 수집하세요.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-500 gap-2">
        <Loader2 size={16} className="animate-spin" /> 불러오는 중...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="py-10 text-center text-red-400 text-sm">
        <AlertTriangle size={16} className="inline mr-2" />
        {error || '데이터를 불러올 수 없습니다.'}
      </div>
    )
  }

  const m = data.metrics
  const metricCards = [
    { label: '현재가', value: fmt(m.current_price, 'price') },
    { label: 'P/E', value: fmt(m.price_to_earnings_ratio, 'x') },
    { label: 'P/B', value: fmt(m.price_to_book_ratio, 'x') },
    { label: 'EV/EBITDA', value: fmt(m.enterprise_value_to_ebitda_ratio, 'x') },
    { label: 'FCF Yield', value: fmt(m.free_cash_flow_yield, 'pct') },
    { label: 'ROE', value: fmt(m.return_on_equity, 'pct') },
    { label: 'ROIC', value: fmt(m.return_on_invested_capital, 'pct') },
    { label: 'ROA', value: fmt(m.return_on_assets, 'pct') },
    { label: '매출 성장', value: fmt(m.revenue_growth, 'pct') },
    { label: '영업이익률', value: fmt(m.operating_margin, 'pct') },
    { label: '배당수익률', value: fmt(m.dividend_yield, 'pct') },
    { label: '시가총액', value: fmt(m.market_cap ?? m.market_capitalization, 'cap') },
  ].filter((c) => c.value !== 'N/A')

  // Cache info: pick the most recent entry
  const cacheEntries = Object.values(data.cache_info)
  const latestFetch = cacheEntries.length > 0
    ? cacheEntries.reduce((a, b) => a.fetched_at > b.fetched_at ? a : b)
    : null

  return (
    <div className="space-y-4">
      {/* Cache timestamp */}
      {latestFetch && (
        <p className="text-xs text-gray-600 text-right">
          마지막 수집: {fmtKST(latestFetch.fetched_at)}
        </p>
      )}

      {/* Key Metrics cards */}
      {metricCards.length > 0 && (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">
          {metricCards.map((c) => <MetricCard key={c.label} label={c.label} value={c.value} />)}
        </div>
      )}

      {/* Company info */}
      <DataSection title="기업 정보" defaultOpen>
        <PreText text={data.company_info} />
      </DataSection>

      {/* Income Statement */}
      <DataSection title="손익계산서 (연간)" defaultOpen>
        <PreText text={data.income_table} />
      </DataSection>

      {/* Balance Sheet */}
      <DataSection title="재무상태표">
        <PreText text={data.bs_table} />
      </DataSection>

      {/* Cash Flow */}
      <DataSection title="현금흐름표">
        <PreText text={data.cf_table} />
      </DataSection>

      {/* 최근 뉴스 */}
      <DataSection title="최근 뉴스">
        <PreText text={data.news_text} />
      </DataSection>

      {/* Insider trades */}
      <DataSection title="내부자 거래">
        <PreText text={data.insider_text} />
      </DataSection>

      {/* SEC summaries (US) */}
      {data.sec_summaries.length > 0 && (
        <DataSection title={`공시 요약 (${data.sec_summaries.length}건)`}>
          <div>
            {data.sec_summaries.map((s) => (
              <SecSummaryCard key={`${s.filing_type}-${s.report_period}`} s={s} />
            ))}
          </div>
        </DataSection>
      )}

    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ThesisPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const [ticker, setTicker] = useState<Ticker | null>(null)
  const [thesis, setThesis] = useState<Thesis | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [analyzeState, setAnalyzeState] = useState<AnalyzeState>('idle')
  const [analyzeError, setAnalyzeError] = useState('')
  const [streamText, setStreamText] = useState('')
  const [openSections, setOpenSections] = useState<Set<ThesisSectionKey>>(new Set(['thesis']))
  const [reporting, setReporting] = useState(false)
  const [reportMsg, setReportMsg] = useState('')
  const [monitoring, setMonitoring] = useState(false)
  const [dataStatus, setDataStatus] = useState<DataStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const [feedback, setFeedback] = useState('')
  const [refineState, setRefineState] = useState<RefineState>('idle')
  const [refineError, setRefineError] = useState('')
  const [refineCount, setRefineCount] = useState(0)

  const [activeTab, setActiveTab] = useState<ActiveTab>('thesis')

  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!id) return
    Promise.all([
      api.getTickers().then((list) => list.find((t) => t.id === id) ?? null),
      api.getThesis(id).catch(() => null),
      api.getDataStatus(id).catch(() => null),
    ])
      .then(([t, th, ds]) => {
        setTicker(t)
        setThesis(th)
        setDataStatus(ds)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [id])

  async function handleRefreshData() {
    if (!id) return
    setRefreshing(true)
    setReportMsg('데이터 수집 중... (30-90초 소요)')
    try {
      await api.refreshData(id)
      let elapsed = 0
      const poll = setInterval(async () => {
        elapsed += 3000
        const status = await api.getDataStatus(id).catch(() => null)
        if (status?.has_data) {
          setDataStatus(status)
          setReportMsg('')
          clearInterval(poll)
          setRefreshing(false)
          return
        }
        if (elapsed >= 120000) {
          clearInterval(poll)
          setRefreshing(false)
          setReportMsg(
            '데이터 수집에 실패했습니다. ' +
            'OPENDART_API_KEY 설정 또는 네트워크를 확인하고 다시 시도하세요. ' +
            '(KR 종목: 연결재무제표가 없는 기업일 수 있습니다)'
          )
        }
      }, 3000)
    } catch (e) {
      setReportMsg(e instanceof Error ? e.message : '새로고침 실패')
      setRefreshing(false)
    }
  }

  function startAnalyze() {
    if (!id) return
    setAnalyzeState('streaming')
    setStreamText('')
    setAnalyzeError('')
    setActiveTab('thesis')

    abortRef.current = api.analyzeStream(id, {
      onStart: () => setStreamText(''),
      onChunk: (text) => setStreamText((prev) => prev + text),
      onComplete: async (sections) => {
        try {
          const updated = await api.getThesis(id)
          setThesis(updated)
          setOpenSections(new Set(THESIS_SECTIONS.map((s) => s.key)))
        } catch {
          setThesis((prev) => prev
            ? { ...prev, ...sections, confirmed: 'draft' }
            : null)
        }
        setAnalyzeState('done')
        setStreamText('')
      },
      onError: (msg) => {
        setAnalyzeError(msg)
        setAnalyzeState('error')
      },
    })
  }

  function startRefine() {
    if (!id || !feedback.trim()) return
    setRefineState('streaming')
    setStreamText('')
    setRefineError('')

    abortRef.current = api.refineStream(id, feedback, {
      onStart: () => setStreamText(''),
      onChunk: (text) => setStreamText((prev) => prev + text),
      onComplete: async (sections) => {
        try {
          const updated = await api.getThesis(id)
          setThesis(updated)
          setOpenSections(new Set(THESIS_SECTIONS.map((s) => s.key)))
        } catch {
          setThesis((prev) => prev ? { ...prev, ...sections, confirmed: 'draft' } : null)
        }
        setRefineState('done')
        setStreamText('')
        setFeedback('')
        setRefineCount((n) => n + 1)
      },
      onError: (msg) => {
        setRefineError(msg)
        setRefineState('error')
      },
    })
  }

  async function handleBreakMonitor() {
    if (!id) return
    setMonitoring(true)
    try {
      await fetch(`/api/tickers/${id}/break-monitor`, { method: 'POST' })
      setReportMsg('Break Monitor 실행됨. 완료 시 Telegram 알림이 옵니다.')
    } catch {
      setReportMsg('오류가 발생했습니다.')
    } finally {
      setMonitoring(false)
    }
  }

  async function handleReport() {
    if (!id) return
    setReporting(true)
    setReportMsg('')
    try {
      const res = await fetch(`/api/tickers/${id}/report`, { method: 'POST' })
      if (res.ok) {
        setReportMsg('보고서 생성 시작됨. 완료 시 Telegram 알림이 옵니다.')
      } else {
        const err = await res.json().catch(() => ({ detail: '오류가 발생했습니다.' }))
        setReportMsg(err.detail || '오류가 발생했습니다.')
      }
    } catch {
      setReportMsg('오류가 발생했습니다.')
    } finally {
      setReporting(false)
    }
  }

  async function handleConfirm() {
    if (!id) return
    try {
      const updated = await api.confirmThesis(id)
      setThesis(updated)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '오류 발생')
    }
  }

  function toggleSection(key: ThesisSectionKey) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const statusColor = {
    draft: 'text-yellow-400',
    confirmed: 'text-emerald-400',
    needs_review: 'text-red-400',
  }
  const statusLabel = {
    draft: '초안 (Draft)',
    confirmed: '확정됨 (Confirmed)',
    needs_review: '재검토 필요',
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500">
        불러오는 중...
      </div>
    )
  }

  if (error || !ticker) {
    return (
      <div className="min-h-screen flex items-center justify-center text-red-400">
        {error || '종목을 찾을 수 없습니다.'}
      </div>
    )
  }

  const hasContent = thesis?.thesis || thesis?.risk || thesis?.key_assumptions || thesis?.valuation

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-800 px-3 py-3 sm:px-6 sm:py-4">
        <div className="max-w-4xl mx-auto flex items-start sm:items-center justify-between gap-2">
          <div className="flex items-center gap-3 flex-shrink-0">
            <button onClick={() => navigate('/')} className="text-gray-400 hover:text-white transition-colors">
              <ArrowLeft size={20} />
            </button>
            <div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-white text-lg sm:text-xl font-bold">{ticker.symbol}</span>
                <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                  {ticker.market === 'US_Stock' ? 'US' : 'KR'}
                </span>
                {thesis && (
                  <span className={`text-xs sm:text-sm font-medium ${statusColor[thesis.confirmed]}`}>
                    {statusLabel[thesis.confirmed]}
                  </span>
                )}
              </div>
              <p className="text-xs sm:text-sm text-gray-400 truncate max-w-[160px] sm:max-w-none">{ticker.name}</p>
            </div>
          </div>

          <div className="flex items-center gap-1 sm:gap-2 flex-wrap justify-end">
            {(thesis?.confirmed === 'draft' || thesis?.confirmed === 'needs_review') && hasContent && (
              <button
                onClick={handleConfirm}
                className={`flex items-center gap-1.5 text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors ${
                  thesis.confirmed === 'needs_review'
                    ? 'bg-orange-700 hover:bg-orange-600'
                    : 'bg-emerald-700 hover:bg-emerald-600'
                }`}
              >
                <CheckCircle size={14} />
                {thesis.confirmed === 'needs_review' ? '재확인' : 'Confirm'}
              </button>
            )}
            {thesis?.confirmed === 'confirmed' && (
              <button
                onClick={handleBreakMonitor}
                disabled={monitoring}
                className="flex items-center gap-1.5 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
              >
                {monitoring
                  ? <Loader2 size={14} className="animate-spin" />
                  : <><Bell size={14} /> <span className="hidden sm:inline">Break Monitor</span><span className="sm:hidden">모니터</span></>
                }
              </button>
            )}
            <button
              onClick={handleRefreshData}
              disabled={refreshing}
              title={dataStatus?.fetched_at
                ? `마지막 업데이트: ${fmtKST(dataStatus.fetched_at)}`
                : '재무 데이터 없음 — 클릭하여 수집'}
              className={`flex items-center gap-1.5 text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors disabled:opacity-50 ${
                dataStatus?.has_data
                  ? 'bg-gray-700 hover:bg-gray-600'
                  : 'bg-orange-700 hover:bg-orange-600'
              }`}
            >
              {refreshing
                ? <Loader2 size={14} className="animate-spin" />
                : <><Database size={14} /> <span className="hidden sm:inline">{dataStatus?.has_data ? '데이터 갱신' : '데이터 수집'}</span><span className="sm:hidden">데이터</span></>
              }
            </button>
            <button
              onClick={handleReport}
              disabled={reporting || !dataStatus?.has_data}
              title={!dataStatus?.has_data ? '먼저 데이터를 수집하세요' : '심층 보고서 생성'}
              className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
            >
              {reporting
                ? <Loader2 size={14} className="animate-spin" />
                : <><FileText size={14} /> 보고서</>
              }
            </button>
            <button
              onClick={startAnalyze}
              disabled={analyzeState === 'streaming'}
              className="flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
            >
              {analyzeState === 'streaming'
                ? <Loader2 size={14} className="animate-spin" />
                : <><Sparkles size={14} /> AI 분석</>
              }
            </button>
          </div>
        </div>
      </header>

      {/* Tab bar */}
      <div className="border-b border-gray-800 px-3 sm:px-6">
        <div className="max-w-4xl mx-auto flex gap-1">
          {([
            { id: 'thesis', label: 'Thesis', icon: <Sparkles size={14} /> },
            { id: 'data', label: '재무 데이터', icon: <BarChart2 size={14} /> },
            { id: 'reports', label: '보고서', icon: <FileText size={14} /> },
          ] as const).map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === tab.id
                  ? 'border-violet-500 text-violet-400'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              {tab.icon}
              {tab.label}
              {tab.id === 'data' && dataStatus?.has_data && (
                <span className="ml-1 text-xs text-emerald-500">●</span>
              )}
            </button>
          ))}
        </div>
      </div>

      <main className="max-w-4xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4">
        {/* ── Thesis Tab ── */}
        {activeTab === 'thesis' && (
          <>
            {/* 데이터 상태 배너 */}
            {dataStatus && (
              <div className={`rounded-lg px-4 py-3 text-sm flex items-center gap-3 ${
                dataStatus.has_data
                  ? 'bg-gray-900 border border-gray-800 text-gray-400'
                  : 'bg-orange-900/20 border border-orange-800 text-orange-300'
              }`}>
                <Database size={15} className="flex-shrink-0" />
                {dataStatus.has_data ? (
                  <span>
                    재무 데이터 수집됨
                    {dataStatus.fetched_at && (
                      <> · {fmtKST(dataStatus.fetched_at)}</>
                    )}
                    {dataStatus.sec_summaries > 0 && (
                      <> · 공시 요약 {dataStatus.sec_summaries}건</>
                    )}
                    <button
                      onClick={() => setActiveTab('data')}
                      className="ml-2 text-violet-400 hover:text-violet-300 underline text-xs"
                    >
                      데이터 보기 →
                    </button>
                  </span>
                ) : (
                  <span>재무 데이터 없음 — "데이터 수집" 버튼으로 먼저 수집하세요. 보고서 생성은 데이터 수집 후 가능합니다.</span>
                )}
              </div>
            )}

            {/* Report / error messages */}
            {reportMsg && (
              <div className="bg-blue-900/30 border border-blue-800 rounded-lg p-4 text-blue-300 text-sm flex items-center gap-2">
                <FileText size={16} /> {reportMsg}
              </div>
            )}
            {analyzeError && (
              <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-300 text-sm flex items-center gap-2">
                <AlertTriangle size={16} /> {analyzeError}
              </div>
            )}

            {/* Streaming indicator */}
            {(analyzeState === 'streaming' || refineState === 'streaming') && (
              <div className="bg-gray-900 border border-violet-800 rounded-xl p-5">
                <div className="flex items-center gap-2 text-violet-400 text-sm mb-3">
                  <Loader2 size={14} className="animate-spin" />
                  {refineState === 'streaming' ? 'AI가 피드백을 반영하여 thesis를 수정하고 있습니다...' : 'AI가 thesis를 생성하고 있습니다...'}
                </div>
                <pre className="text-gray-300 text-sm whitespace-pre-wrap font-mono leading-relaxed max-h-96 overflow-y-auto">
                  {streamText}
                  <span className="animate-pulse">▋</span>
                </pre>
              </div>
            )}

            {/* No content yet */}
            {analyzeState === 'idle' && !hasContent && (
              <div className="text-center py-24 text-gray-600">
                <Sparkles size={48} className="mx-auto mb-4 text-gray-800" />
                <p className="text-lg text-gray-500">아직 Thesis가 없습니다.</p>
                <p className="text-sm mt-1">"AI 분석" 버튼으로 초안을 생성하세요.</p>
              </div>
            )}

            {/* Thesis sections */}
            {hasContent && THESIS_SECTIONS.map(({ key, label }) => {
              const content = thesis?.[key as keyof Thesis] as string | null | undefined
              if (!content) return null
              const isOpen = openSections.has(key)
              return (
                <div key={key} className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                  <button
                    onClick={() => toggleSection(key)}
                    className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-800/50 transition-colors"
                  >
                    <span className="text-white font-medium">{label}</span>
                    {isOpen ? <ChevronUp size={16} className="text-gray-400" /> : <ChevronDown size={16} className="text-gray-400" />}
                  </button>
                  {isOpen && (
                    <div className="px-5 pb-5 border-t border-gray-800">
                      <div className="pt-4 text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
                        {content}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}

            {/* Feedback loop */}
            {hasContent && thesis?.confirmed !== 'confirmed' && analyzeState !== 'streaming' && (
              <div className="bg-gray-900 border border-gray-700 rounded-xl p-5 space-y-3">
                <div className="flex items-center gap-2 text-gray-300 text-sm font-medium">
                  <MessageSquare size={15} />
                  피드백으로 Thesis 수정
                  {refineCount > 0 && (
                    <span className="ml-auto text-xs text-gray-500">{refineCount}회 반영됨</span>
                  )}
                </div>
                <textarea
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  disabled={refineState === 'streaming'}
                  placeholder="예: 경쟁사 대비 해자(moat) 분석을 더 구체적으로 써줘. 밸류에이션에서 DCF 할인율 가정을 더 보수적으로 조정해줘."
                  rows={4}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-violet-600 disabled:opacity-50"
                />
                {refineError && (
                  <div className="flex items-center gap-2 text-red-400 text-sm">
                    <AlertTriangle size={14} /> {refineError}
                  </div>
                )}
                <div className="flex justify-end">
                  <button
                    onClick={startRefine}
                    disabled={refineState === 'streaming' || !feedback.trim()}
                    className="flex items-center gap-2 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                  >
                    {refineState === 'streaming'
                      ? <><Loader2 size={14} className="animate-spin" /> 수정 중...</>
                      : <><RefreshCw size={14} /> 피드백 반영</>
                    }
                  </button>
                </div>
              </div>
            )}

            {thesis?.last_analyzed_at && (
              <p className="text-xs text-gray-600 text-right">
                마지막 분석: {fmtKST(thesis.last_analyzed_at)}
              </p>
            )}
          </>
        )}

        {/* ── Data Tab ── */}
        {activeTab === 'data' && id && (
          <FinancialDataTab tickerId={id} hasData={!!dataStatus?.has_data} market={ticker?.market ?? 'US_Stock'} />
        )}

        {activeTab === 'reports' && id && (
          <TickerReportsTab tickerId={id} />
        )}
      </main>
    </div>
  )
}
