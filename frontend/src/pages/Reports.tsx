import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, RefreshCw, Loader2, ChevronDown, ChevronUp, Search, BarChart2 } from 'lucide-react'
import { fmtKST } from '../utils/date'

interface Report {
  id: string
  ticker_id: string | null
  ticker_symbol: string | null
  type: string
  content: string
  created_at: string
}

const TYPE_LABEL: Record<string, string> = {
  daily_brief: '데일리 브리핑',
  analysis: '종목 심층 분석',
  macro: '매크로',
  discovery: '종목 탐색',
  portfolio_review: '포트폴리오 점검',
}

const TYPE_COLOR: Record<string, string> = {
  daily_brief: 'bg-blue-900 text-blue-200',
  analysis: 'bg-violet-900 text-violet-200',
  macro: 'bg-amber-900 text-amber-200',
  discovery: 'bg-emerald-900 text-emerald-200',
  portfolio_review: 'bg-cyan-900 text-cyan-200',
}

// 포트폴리오 점검 보고서의 5섹션
const PORTFOLIO_REVIEW_SECTIONS = [
  { key: 'portfolio_overview', label: '1. 포트폴리오 개요' },
  { key: 'holdings_assessment', label: '2. 종목별 평가' },
  { key: 'concentration_risk', label: '3. 집중도 리스크' },
  { key: 'thesis_health_check', label: '4. Thesis 건전성 체크' },
  { key: 'action_items', label: '5. 실행 항목' },
]

// 종목 탐색 보고서의 5섹션
const DISCOVERY_SECTIONS = [
  { key: 'theme_analysis', label: '1. 테마 분석' },
  { key: 'us_picks', label: '2. 미국 추천 종목' },
  { key: 'kr_picks', label: '3. 한국 추천 종목' },
  { key: 'screening_criteria', label: '4. 선별 기준' },
  { key: 'next_steps', label: '5. 다음 단계' },
]

// 심층 분석 보고서의 8섹션
const DEEP_SECTIONS = [
  { key: 'business_overview', label: '1. 기업 개요' },
  { key: 'moat_analysis', label: '2. 경쟁우위 (Moat)' },
  { key: 'financial_analysis', label: '3. 재무 심층 분석' },
  { key: 'management_quality', label: '4. 경영진 & 자본배분' },
  { key: 'valuation', label: '5. 밸류에이션' },
  { key: 'risk_matrix', label: '6. 리스크 매트릭스' },
  { key: 'recent_developments', label: '7. 최근 동향' },
  { key: 'investment_conclusion', label: '8. 투자 결론' },
]

function extractSection(content: string, sectionName: string): string {
  const pattern = new RegExp(`<section name="${sectionName}">(.*?)</section>`, 's')
  const match = content.match(pattern)
  return match ? match[1].trim() : ''
}

function DeepReportView({ report }: { report: Report }) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(['business_overview', 'investment_conclusion'])
  )

  function toggle(key: string) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 섹션이 파싱되는지 확인
  const hasSections = DEEP_SECTIONS.some(({ key }) => extractSection(report.content, key))

  if (!hasSections) {
    // 구 형식 보고서는 plain text로 표시
    return (
      <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap font-mono">
        {report.content}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {DEEP_SECTIONS.map(({ key, label }) => {
        const text = extractSection(report.content, key)
        if (!text) return null
        const isOpen = openSections.has(key)
        return (
          <div key={key} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(key)}
              className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-800 hover:bg-gray-750 transition-colors"
            >
              <span className="text-white text-sm font-medium">{label}</span>
              {isOpen
                ? <ChevronUp size={15} className="text-gray-400 flex-shrink-0" />
                : <ChevronDown size={15} className="text-gray-400 flex-shrink-0" />
              }
            </button>
            {isOpen && (
              <div className="px-4 py-4 bg-gray-900 border-t border-gray-700">
                <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
                  {text}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function PortfolioReviewView({ report }: { report: Report }) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(['portfolio_overview', 'holdings_assessment', 'action_items'])
  )

  function toggle(key: string) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const hasSections = PORTFOLIO_REVIEW_SECTIONS.some(({ key }) => extractSection(report.content, key))

  if (!hasSections) {
    return (
      <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap font-mono">
        {report.content}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {PORTFOLIO_REVIEW_SECTIONS.map(({ key, label }) => {
        const text = extractSection(report.content, key)
        if (!text) return null
        const isOpen = openSections.has(key)
        return (
          <div key={key} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(key)}
              className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-800 hover:bg-gray-750 transition-colors"
            >
              <span className="text-white text-sm font-medium">{label}</span>
              {isOpen
                ? <ChevronUp size={15} className="text-gray-400 flex-shrink-0" />
                : <ChevronDown size={15} className="text-gray-400 flex-shrink-0" />
              }
            </button>
            {isOpen && (
              <div className="px-4 py-4 bg-gray-900 border-t border-gray-700">
                <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
                  {text}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function DiscoveryReportView({ report }: { report: Report }) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(['theme_analysis', 'us_picks', 'kr_picks'])
  )

  function toggle(key: string) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const hasSections = DISCOVERY_SECTIONS.some(({ key }) => extractSection(report.content, key))

  if (!hasSections) {
    return (
      <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap font-mono">
        {report.content}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {DISCOVERY_SECTIONS.map(({ key, label }) => {
        const text = extractSection(report.content, key)
        if (!text) return null
        const isOpen = openSections.has(key)
        return (
          <div key={key} className="border border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(key)}
              className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-800 hover:bg-gray-750 transition-colors"
            >
              <span className="text-white text-sm font-medium">{label}</span>
              {isOpen
                ? <ChevronUp size={15} className="text-gray-400 flex-shrink-0" />
                : <ChevronDown size={15} className="text-gray-400 flex-shrink-0" />
              }
            </button>
            {isOpen && (
              <div className="px-4 py-4 bg-gray-900 border-t border-gray-700">
                <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
                  {text}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function ReportsPage() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [triggeringMacro, setTriggeringMacro] = useState(false)
  const [selected, setSelected] = useState<Report | null>(null)
  const [mobileShowDetail, setMobileShowDetail] = useState(false)
  const [showDiscovery, setShowDiscovery] = useState(false)
  const [discoveryIdea, setDiscoveryIdea] = useState('')
  const [discovering, setDiscovering] = useState(false)
  const [discoveryStream, setDiscoveryStream] = useState('')
  const discoveryRef = useRef<HTMLDivElement>(null)
  const [reviewingPortfolio, setReviewingPortfolio] = useState(false)
  const [portfolioReviewStream, setPortfolioReviewStream] = useState('')
  const [showPortfolioStream, setShowPortfolioStream] = useState(false)
  const portfolioReviewRef = useRef<HTMLDivElement>(null)

  async function fetchReports() {
    setLoading(true)
    try {
      const res = await fetch('/api/reports')
      if (res.ok) setReports(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchReports() }, [])

  async function triggerBriefing() {
    setTriggering(true)
    const beforeId = reports[0]?.id ?? null
    try {
      await fetch('/api/reports/daily-briefing/trigger', { method: 'POST' })
      let elapsed = 0
      const poll = setInterval(async () => {
        elapsed += 3000
        const res = await fetch('/api/reports')
        if (res.ok) {
          const data: Report[] = await res.json()
          if (data[0]?.id !== beforeId) {
            setReports(data)
            setSelected(data[0])
            clearInterval(poll)
            setTriggering(false)
          }
        }
        if (elapsed >= 60000) { clearInterval(poll); setTriggering(false) }
      }, 3000)
    } catch {
      setTriggering(false)
    }
  }

  async function triggerMacro() {
    setTriggeringMacro(true)
    const beforeId = reports[0]?.id ?? null
    try {
      await fetch('/api/reports/macro/trigger', { method: 'POST' })
      let elapsed = 0
      const poll = setInterval(async () => {
        elapsed += 3000
        const res = await fetch('/api/reports')
        if (res.ok) {
          const data: Report[] = await res.json()
          if (data[0]?.id !== beforeId) {
            setReports(data)
            setSelected(data[0])
            clearInterval(poll)
            setTriggeringMacro(false)
          }
        }
        if (elapsed >= 60000) { clearInterval(poll); setTriggeringMacro(false) }
      }, 3000)
    } catch {
      setTriggeringMacro(false)
    }
  }

  async function runPortfolioReview() {
    if (reviewingPortfolio) return
    setReviewingPortfolio(true)
    setPortfolioReviewStream('')
    setShowPortfolioStream(true)
    try {
      const res = await fetch('/api/reports/portfolio-review', { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '오류 발생' }))
        setPortfolioReviewStream(err.detail ?? '오류 발생')
        return
      }
      if (!res.body) return
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'chunk') {
              setPortfolioReviewStream((prev) => prev + data.text)
              if (portfolioReviewRef.current) {
                portfolioReviewRef.current.scrollTop = portfolioReviewRef.current.scrollHeight
              }
            } else if (data.type === 'saved') {
              const savedId: string | undefined = data.report_id
              const res2 = await fetch('/api/reports')
              if (res2.ok) {
                const updated: Report[] = await res2.json()
                setReports(updated)
                if (savedId) {
                  const found = updated.find(r => r.id === savedId)
                  if (found) setSelected(found)
                }
              }
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      console.error(e)
    } finally {
      setReviewingPortfolio(false)
    }
  }

  async function runDiscovery() {
    if (!discoveryIdea.trim() || discovering) return
    setDiscovering(true)
    setDiscoveryStream('')
    try {
      const res = await fetch('/api/reports/discovery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idea: discoveryIdea }),
      })
      if (!res.ok || !res.body) throw new Error('discovery request failed')
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const data = JSON.parse(line.slice(6))
            if (data.type === 'chunk') {
              setDiscoveryStream((prev) => prev + data.text)
              if (discoveryRef.current) {
                discoveryRef.current.scrollTop = discoveryRef.current.scrollHeight
              }
            } else if (data.type === 'saved') {
              const savedId: string | undefined = data.report_id
              const res2 = await fetch('/api/reports')
              if (res2.ok) {
                const updated: Report[] = await res2.json()
                setReports(updated)
                if (savedId) {
                  const found = updated.find(r => r.id === savedId)
                  if (found) setSelected(found)
                }
              }
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      console.error(e)
    } finally {
      setDiscovering(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 px-3 py-3 sm:px-6 sm:py-4">
        <div className="max-w-5xl mx-auto">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-3 flex-shrink-0">
              <button onClick={() => navigate('/')} className="text-gray-400 hover:text-white transition-colors">
                <ArrowLeft size={20} />
              </button>
              <div className="flex items-center gap-2">
                <FileText className="text-blue-400" size={18} />
                <h1 className="text-base sm:text-lg font-bold text-white">보고서</h1>
              </div>
            </div>
            <div className="flex items-center gap-1.5 flex-wrap justify-end">
              <button
                onClick={runPortfolioReview}
                disabled={reviewingPortfolio}
                className="flex items-center gap-1.5 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white text-xs font-medium px-2.5 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors"
              >
                {reviewingPortfolio
                  ? <><Loader2 size={13} className="animate-spin" /> <span className="hidden sm:inline">점검 중...</span></>
                  : <><BarChart2 size={13} /> <span className="hidden xs:inline sm:inline">포트폴리오</span><span className="sm:hidden">점검</span><span className="hidden sm:inline"> 점검</span></>
                }
              </button>
              <button
                onClick={() => { setShowDiscovery((v) => !v); setDiscoveryStream('') }}
                className="flex items-center gap-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-xs font-medium px-2.5 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors"
              >
                <Search size={13} /> 종목탐색
              </button>
              <button
                onClick={triggerMacro}
                disabled={triggeringMacro}
                className="flex items-center gap-1.5 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs font-medium px-2.5 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors"
              >
                {triggeringMacro
                  ? <><Loader2 size={13} className="animate-spin" /></>
                  : <><RefreshCw size={13} /> 매크로</>
                }
              </button>
              <button
                onClick={triggerBriefing}
                disabled={triggering}
                className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-xs font-medium px-2.5 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors"
              >
                {triggering
                  ? <><Loader2 size={13} className="animate-spin" /></>
                  : <><RefreshCw size={13} /> 브리핑</>
                }
              </button>
            </div>
          </div>
        </div>
      </header>

      {showPortfolioStream && (portfolioReviewStream || reviewingPortfolio) && (
        <div className="border-b border-gray-800 bg-gray-900">
          <div className="max-w-5xl mx-auto px-3 sm:px-6 py-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-cyan-400 font-medium">포트폴리오 점검 진행 중...</span>
              {!reviewingPortfolio && (
                <button
                  onClick={() => setShowPortfolioStream(false)}
                  className="text-xs text-gray-500 hover:text-gray-300"
                >
                  닫기
                </button>
              )}
            </div>
            <div
              ref={portfolioReviewRef}
              className="bg-gray-950 border border-gray-700 rounded-lg p-4 max-h-64 overflow-y-auto"
            >
              <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                {portfolioReviewStream || ''}
                {reviewingPortfolio && <span className="animate-pulse">▊</span>}
              </pre>
            </div>
            {!reviewingPortfolio && portfolioReviewStream && (
              <p className="text-xs text-cyan-400">완료 — 보고서 목록에 저장됨</p>
            )}
          </div>
        </div>
      )}

      {showDiscovery && (
        <div className="border-b border-gray-800 bg-gray-900">
          <div className="max-w-5xl mx-auto px-3 sm:px-6 py-5 space-y-3">
            <p className="text-sm text-gray-400">투자 아이디어를 입력하면 미국·한국 유망 종목을 탐색합니다.</p>
            <textarea
              value={discoveryIdea}
              onChange={(e) => setDiscoveryIdea(e.target.value)}
              placeholder="예: AI 인프라 수요 급증에서 소외된 수혜주, 고령화 사회 헬스케어 중 재무 건전한 기업, 미국 리쇼어링 수혜 산업재..."
              rows={3}
              disabled={discovering}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-sm text-white placeholder-gray-500 resize-none focus:outline-none focus:border-emerald-600 disabled:opacity-50"
            />
            <div className="flex items-center gap-3">
              <button
                onClick={runDiscovery}
                disabled={discovering || !discoveryIdea.trim()}
                className="flex items-center gap-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors"
              >
                {discovering
                  ? <><Loader2 size={14} className="animate-spin" /> 탐색 중...</>
                  : <><Search size={14} /> 종목 탐색 시작</>
                }
              </button>
              {discoveryStream && !discovering && (
                <span className="text-xs text-emerald-400">완료 — 보고서 목록에 저장됨</span>
              )}
            </div>
            {(discoveryStream || discovering) && (
              <div
                ref={discoveryRef}
                className="mt-2 bg-gray-950 border border-gray-700 rounded-lg p-4 max-h-80 overflow-y-auto"
              >
                <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono leading-relaxed">
                  {discoveryStream || ''}
                  {discovering && <span className="animate-pulse">▊</span>}
                </pre>
              </div>
            )}
          </div>
        </div>
      )}

      <main className="max-w-5xl mx-auto px-3 sm:px-6 py-4 sm:py-8">
        {/* 모바일/태블릿(<1024px): 목록 또는 본문 전환. 데스크탑(1024px+): 사이드바 레이아웃 */}
        <div className="lg:flex lg:gap-6">
          {/* 목록 — lg 미만에서는 detail 볼 때 숨김 */}
          <div className={`lg:w-72 lg:flex-shrink-0 lg:block space-y-2 ${mobileShowDetail ? 'hidden' : 'block'}`}>
            {loading && <p className="text-gray-500 text-sm text-center py-8">불러오는 중...</p>}
            {!loading && reports.length === 0 && (
              <p className="text-gray-600 text-sm text-center py-8">보고서가 없습니다.</p>
            )}
            {reports.map((r, idx) => {
              const isLatest = idx === reports.findIndex(
                (x) => x.ticker_id === r.ticker_id && x.type === r.type
              )
              return (
                <button
                  key={r.id}
                  onClick={() => { setSelected(r); setMobileShowDetail(true) }}
                  className={`w-full text-left px-4 py-3 rounded-xl border transition-colors ${
                    selected?.id === r.id
                      ? 'bg-gray-800 border-gray-600'
                      : 'bg-gray-900 border-gray-800 hover:border-gray-700'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${TYPE_COLOR[r.type] ?? 'bg-gray-700 text-gray-300'}`}>
                      {TYPE_LABEL[r.type] ?? r.type}
                    </span>
                    {r.ticker_symbol && (
                      <span className="text-xs font-semibold text-white">{r.ticker_symbol}</span>
                    )}
                    {isLatest && (
                      <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-emerald-900 text-emerald-300">최신</span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500">
                    {fmtKST(r.created_at)}
                  </p>
                </button>
              )
            })}
          </div>

          {/* 본문 — lg 미만에서는 목록 볼 때 숨김 */}
          <div className={`lg:flex-1 lg:min-w-0 lg:block ${mobileShowDetail ? 'block' : 'hidden'}`}>
            {selected ? (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 sm:p-6">
                <div className="flex items-center gap-3 mb-4 sm:mb-5 flex-wrap">
                  {/* 모바일/태블릿 뒤로가기 버튼 */}
                  <button
                    onClick={() => setMobileShowDetail(false)}
                    className="lg:hidden text-gray-400 hover:text-white transition-colors flex-shrink-0"
                  >
                    <ArrowLeft size={18} />
                  </button>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${TYPE_COLOR[selected.type] ?? ''}`}>
                    {TYPE_LABEL[selected.type] ?? selected.type}
                  </span>
                  {selected.ticker_symbol && (
                    <span className="text-sm font-bold text-white">{selected.ticker_symbol}</span>
                  )}
                  <span className="text-xs text-gray-500 ml-auto">
                    {fmtKST(selected.created_at)}
                  </span>
                </div>

                {selected.type === 'analysis'
                  ? <DeepReportView report={selected} />
                  : selected.type === 'discovery'
                  ? <DiscoveryReportView report={selected} />
                  : selected.type === 'portfolio_review'
                  ? <PortfolioReviewView report={selected} />
                  : (
                    <div className="text-gray-300 text-sm leading-relaxed whitespace-pre-wrap">
                      {selected.content}
                    </div>
                  )
                }
              </div>
            ) : (
              <div className="hidden lg:flex items-center justify-center h-64 text-gray-600">
                <p>왼쪽에서 보고서를 선택하세요.</p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
