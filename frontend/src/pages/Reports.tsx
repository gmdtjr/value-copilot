import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, FileText, RefreshCw, Loader2, ChevronDown, ChevronUp, Search, BarChart2, Trash2, MessageSquare, Send, X, Eye, EyeOff } from 'lucide-react'
import { fmtKST } from '../utils/date'
import { Markdown } from '../components/Markdown'
import type { ReportComment } from '../types'

interface Report {
  id: string
  ticker_id: string | null
  ticker_symbol: string | null
  type: string
  content: string
  created_at: string
  is_read: boolean
  comment_count: number
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
    return <Markdown content={report.content} />
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
                <Markdown content={text} />
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
    return <Markdown content={report.content} />
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
                <Markdown content={text} />
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
    return <Markdown content={report.content} />
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
                <Markdown content={text} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

const BRIEFING_SECTIONS = [
  { key: 'macro', label: '1. 매크로 환경' },
  { key: 'portfolio_summary', label: '2. 포트폴리오 브리핑' },
  { key: 'watchlist', label: '3. 관심 종목' },
]

function DailyBriefingView({ report }: { report: Report }) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(['macro', 'portfolio_summary', 'watchlist'])
  )

  function toggle(key: string) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const hasSections = BRIEFING_SECTIONS.some(({ key }) => extractSection(report.content, key))
  if (!hasSections) return <Markdown content={report.content} />

  return (
    <div className="space-y-2">
      {BRIEFING_SECTIONS.map(({ key, label }) => {
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
                <Markdown content={text} />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

const MACRO_SECTIONS = [
  { key: 'market_overview', label: '1. 시장 환경' },
  { key: 'macro_factors', label: '2. 매크로 요인' },
  { key: 'portfolio_implication', label: '3. 포트폴리오 시사점' },
]

function MacroReportView({ report }: { report: Report }) {
  const [openSections, setOpenSections] = useState<Set<string>>(
    new Set(['market_overview', 'macro_factors', 'portfolio_implication'])
  )

  function toggle(key: string) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const hasSections = MACRO_SECTIONS.some(({ key }) => extractSection(report.content, key))

  if (!hasSections) return <Markdown content={report.content} />

  return (
    <div className="space-y-2">
      {MACRO_SECTIONS.map(({ key, label }) => {
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
                <Markdown content={text} />
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

  // Filter & multi-select
  const [filterType, setFilterType] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [deletingBulk, setDeletingBulk] = useState(false)

  const filteredReports = filterType ? reports.filter(r => r.type === filterType) : reports

  // Comments state
  const [comments, setComments] = useState<ReportComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentText, setCommentText] = useState('')
  const [submittingComment, setSubmittingComment] = useState(false)
  const [showComments, setShowComments] = useState(false)

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

  async function selectReport(r: Report) {
    setSelected(r)
    setMobileShowDetail(true)
    setCommentText('')
    setShowComments(false)
    setComments([])
    // 읽음 처리
    if (!r.is_read) {
      const res = await fetch(`/api/reports/${r.id}/read`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_read: true }),
      })
      if (res.ok) {
        setReports(prev => prev.map(x => x.id === r.id ? { ...x, is_read: true } : x))
        setSelected(prev => prev?.id === r.id ? { ...prev, is_read: true } : prev)
      }
    }
  }

  async function toggleRead(r: Report, e: React.MouseEvent) {
    e.stopPropagation()
    const next = !r.is_read
    const res = await fetch(`/api/reports/${r.id}/read`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_read: next }),
    })
    if (res.ok) {
      setReports(prev => prev.map(x => x.id === r.id ? { ...x, is_read: next } : x))
      setSelected(prev => prev?.id === r.id ? { ...prev, is_read: next } : prev)
    }
  }

  async function deleteReport(r: Report) {
    if (!confirm(`"${TYPE_LABEL[r.type] ?? r.type}${r.ticker_symbol ? ` — ${r.ticker_symbol}` : ''}" 보고서를 삭제할까요? 코멘트도 함께 삭제됩니다.`)) return
    const res = await fetch(`/api/reports/${r.id}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) {
      const next = reports.filter(x => x.id !== r.id)
      setReports(next)
      if (selected?.id === r.id) {
        setSelected(next[0] ?? null)
        if (next[0]) selectReport(next[0])
        else setMobileShowDetail(false)
      }
    }
  }

  function toggleSelect(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAll() {
    if (selectedIds.size === filteredReports.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredReports.map(r => r.id)))
    }
  }

  async function deleteSelected() {
    if (selectedIds.size === 0) return
    if (!confirm(`선택한 보고서 ${selectedIds.size}개를 삭제할까요? 코멘트도 함께 삭제됩니다.`)) return
    setDeletingBulk(true)
    try {
      await Promise.all(
        [...selectedIds].map(id => fetch(`/api/reports/${id}`, { method: 'DELETE' }))
      )
      const remaining = reports.filter(r => !selectedIds.has(r.id))
      setReports(remaining)
      setSelectedIds(new Set())
      if (selected && selectedIds.has(selected.id)) {
        const next = remaining[0] ?? null
        setSelected(next)
        if (!next) setMobileShowDetail(false)
      }
    } finally {
      setDeletingBulk(false)
    }
  }

  async function loadComments(reportId: string) {
    setCommentsLoading(true)
    try {
      const res = await fetch(`/api/reports/${reportId}/comments`)
      if (res.ok) setComments(await res.json())
    } finally {
      setCommentsLoading(false)
    }
  }

  function toggleComments() {
    if (!showComments && selected) loadComments(selected.id)
    setShowComments(v => !v)
  }

  async function submitComment() {
    if (!commentText.trim() || !selected) return
    setSubmittingComment(true)
    try {
      const res = await fetch(`/api/reports/${selected.id}/comments`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: commentText.trim() }),
      })
      if (res.ok) {
        const c: ReportComment = await res.json()
        setComments(prev => [...prev, c])
        setCommentText('')
        setReports(prev => prev.map(x => x.id === selected.id ? { ...x, comment_count: x.comment_count + 1 } : x))
        setSelected(prev => prev?.id === selected.id ? { ...prev, comment_count: prev.comment_count + 1 } : prev)
      }
    } finally {
      setSubmittingComment(false)
    }
  }

  async function deleteComment(commentId: string) {
    if (!selected) return
    const res = await fetch(`/api/reports/${selected.id}/comments/${commentId}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) {
      setComments(prev => prev.filter(c => c.id !== commentId))
      setReports(prev => prev.map(x => x.id === selected.id ? { ...x, comment_count: Math.max(0, x.comment_count - 1) } : x))
      setSelected(prev => prev?.id === selected.id ? { ...prev, comment_count: Math.max(0, prev.comment_count - 1) } : prev)
    }
  }

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
          <div className={`lg:w-72 lg:flex-shrink-0 lg:block ${mobileShowDetail ? 'hidden' : 'block'}`}>
            {/* 종류 필터 탭 */}
            {!loading && reports.length > 0 && (
              <div className="flex gap-1 overflow-x-auto pb-2 mb-3 scrollbar-hide">
                <button
                  onClick={() => { setFilterType(null); setSelectedIds(new Set()) }}
                  className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    filterType === null
                      ? 'bg-gray-700 border-gray-600 text-white'
                      : 'bg-transparent border-gray-700 text-gray-400 hover:text-gray-300'
                  }`}
                >
                  전체 {reports.length}
                </button>
                {Object.entries(TYPE_LABEL).map(([type, label]) => {
                  const count = reports.filter(r => r.type === type).length
                  if (!count) return null
                  return (
                    <button
                      key={type}
                      onClick={() => { setFilterType(type); setSelectedIds(new Set()) }}
                      className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                        filterType === type
                          ? `border-transparent text-white ${TYPE_COLOR[type]}`
                          : 'bg-transparent border-gray-700 text-gray-400 hover:text-gray-300'
                      }`}
                    >
                      {label} {count}
                    </button>
                  )
                })}
              </div>
            )}

            {/* 멀티셀렉트 액션 바 */}
            {filteredReports.length > 0 && (
              <div className="flex items-center gap-2 mb-2 px-1">
                <input
                  type="checkbox"
                  checked={selectedIds.size > 0 && selectedIds.size === filteredReports.length}
                  ref={(el: HTMLInputElement | null) => { if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < filteredReports.length }}
                  onChange={toggleSelectAll}
                  className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 accent-blue-500 cursor-pointer"
                />
                {selectedIds.size > 0 ? (
                  <>
                    <span className="text-xs text-gray-400 flex-1">{selectedIds.size}개 선택됨</span>
                    <button
                      onClick={deleteSelected}
                      disabled={deletingBulk}
                      className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 disabled:opacity-50 transition-colors"
                    >
                      {deletingBulk ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      삭제
                    </button>
                  </>
                ) : (
                  <span className="text-xs text-gray-600">전체선택</span>
                )}
              </div>
            )}

            {loading && <p className="text-gray-500 text-sm text-center py-8">불러오는 중...</p>}
            {!loading && reports.length === 0 && (
              <p className="text-gray-600 text-sm text-center py-8">보고서가 없습니다.</p>
            )}
            {!loading && filteredReports.length === 0 && reports.length > 0 && (
              <p className="text-gray-600 text-sm text-center py-6">해당 종류의 보고서가 없습니다.</p>
            )}
            <div className="space-y-2">
              {filteredReports.map((r) => {
                const isLatest = reports.findIndex(x => x.ticker_id === r.ticker_id && x.type === r.type) === reports.indexOf(r)
                const isSelected = selectedIds.has(r.id)
                return (
                  <div
                    key={r.id}
                    className={`flex items-stretch rounded-xl border transition-colors ${
                      selected?.id === r.id
                        ? 'bg-gray-800 border-gray-600'
                        : isSelected
                        ? 'bg-gray-800/60 border-gray-700'
                        : 'bg-gray-900 border-gray-800 hover:border-gray-700'
                    }`}
                  >
                    {/* 체크박스 */}
                    <div
                      className="flex items-center pl-3 pr-1 cursor-pointer"
                      onClick={(e) => toggleSelect(r.id, e)}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {}}
                        className="w-3.5 h-3.5 rounded border-gray-600 bg-gray-800 accent-blue-500 pointer-events-none"
                      />
                    </div>
                    {/* 내용 */}
                    <button
                      className="flex-1 text-left px-3 py-3 min-w-0"
                      onClick={() => selectReport(r)}
                    >
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        {!r.is_read && (
                          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" title="읽지 않음" />
                        )}
                        {!filterType && (
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${TYPE_COLOR[r.type] ?? 'bg-gray-700 text-gray-300'}`}>
                            {TYPE_LABEL[r.type] ?? r.type}
                          </span>
                        )}
                        {r.ticker_symbol && (
                          <span className="text-xs font-semibold text-white">{r.ticker_symbol}</span>
                        )}
                        {isLatest && (
                          <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-emerald-900 text-emerald-300">최신</span>
                        )}
                        {r.comment_count > 0 && (
                          <span className="ml-auto flex items-center gap-0.5 text-xs text-gray-500">
                            <MessageSquare size={10} />
                            {r.comment_count}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500">{fmtKST(r.created_at)}</p>
                    </button>
                  </div>
                )
              })}
            </div>
          </div>

          {/* 본문 — lg 미만에서는 목록 볼 때 숨김 */}
          <div className={`lg:flex-1 lg:min-w-0 lg:block ${mobileShowDetail ? 'block' : 'hidden'}`}>
            {selected ? (
              <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                {/* 상세 헤더 */}
                <div className="flex items-center gap-2 px-4 sm:px-6 py-4 border-b border-gray-800 flex-wrap">
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
                  <span className="text-xs text-gray-500">{fmtKST(selected.created_at)}</span>
                  <div className="ml-auto flex items-center gap-1">
                    <button
                      onClick={(e) => toggleRead(selected, e)}
                      title={selected.is_read ? '읽지 않음으로 표시' : '읽음으로 표시'}
                      className="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 transition-colors"
                    >
                      {selected.is_read ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                    <button
                      onClick={() => deleteReport(selected)}
                      title="보고서 삭제"
                      className="p-1.5 rounded-lg text-gray-500 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                {/* 보고서 본문 */}
                <div className="p-4 sm:p-6">
                  {selected.type === 'analysis'
                    ? <DeepReportView report={selected} />
                    : selected.type === 'discovery'
                    ? <DiscoveryReportView report={selected} />
                    : selected.type === 'portfolio_review'
                    ? <PortfolioReviewView report={selected} />
                    : selected.type === 'macro'
                    ? <MacroReportView report={selected} />
                    : selected.type === 'daily_brief'
                    ? <DailyBriefingView report={selected} />
                    : <Markdown content={selected.content} />
                  }
                </div>

                {/* 코멘트 섹션 */}
                <div className="border-t border-gray-800">
                  <button
                    onClick={toggleComments}
                    className="w-full flex items-center gap-2 px-4 sm:px-6 py-3 text-sm text-gray-400 hover:text-gray-300 hover:bg-gray-800/30 transition-colors"
                  >
                    <MessageSquare size={14} />
                    <span>코멘트 {selected.comment_count > 0 ? `(${selected.comment_count})` : ''}</span>
                    {showComments
                      ? <ChevronUp size={13} className="ml-auto" />
                      : <ChevronDown size={13} className="ml-auto" />
                    }
                  </button>

                  {showComments && (
                    <div className="px-4 sm:px-6 pb-5 space-y-4">
                      {/* 기존 코멘트 */}
                      {commentsLoading ? (
                        <div className="flex items-center gap-2 text-gray-500 text-sm py-2">
                          <Loader2 size={13} className="animate-spin" /> 불러오는 중...
                        </div>
                      ) : comments.length > 0 ? (
                        <div className="space-y-2">
                          {comments.map(c => (
                            <div key={c.id} className="group bg-gray-800/50 rounded-lg px-4 py-3">
                              <div className="flex items-start justify-between gap-2">
                                <p className="text-sm text-gray-200 leading-relaxed flex-1">{c.content}</p>
                                <button
                                  onClick={() => deleteComment(c.id)}
                                  className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400 transition-all flex-shrink-0 mt-0.5"
                                >
                                  <X size={13} />
                                </button>
                              </div>
                              <p className="text-xs text-gray-600 mt-1.5">{fmtKST(c.created_at)}</p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-600 py-1">아직 코멘트가 없습니다.</p>
                      )}

                      {/* 코멘트 입력 */}
                      <div className="flex gap-2">
                        <textarea
                          value={commentText}
                          onChange={e => setCommentText(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitComment() }}
                          placeholder="투자 인사이트, 후속 관찰 사항... (⌘Enter로 저장)"
                          rows={2}
                          disabled={submittingComment}
                          className="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-500 disabled:opacity-50"
                        />
                        <button
                          onClick={submitComment}
                          disabled={submittingComment || !commentText.trim()}
                          className="flex-shrink-0 bg-gray-700 hover:bg-gray-600 disabled:opacity-40 text-white px-3 rounded-lg transition-colors"
                        >
                          {submittingComment ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
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
