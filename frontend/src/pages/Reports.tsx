import { useEffect, useMemo, useState, useRef, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, FileText, RefreshCw, Loader2, ChevronDown, ChevronUp,
  Trash2, MessageSquare, Send, X, Eye, EyeOff, Plus, CheckCircle,
  PanelLeft, Copy, Check, StickyNote, ThumbsUp, ThumbsDown,
  Minus, AlertCircle, BarChart2,
} from 'lucide-react'
import { fmtKST } from '../utils/date'
import { Markdown } from '../components/Markdown'
import { ThemeControls } from '../components/ThemeControls'
import { useTheme } from '../contexts/ThemeContext'
import type { ReportComment, HumanResponse, HumanResponseType } from '../types'

interface Report {
  id: string
  ticker_id: string | null
  ticker_symbol: string | null
  ticker_name: string | null
  type: string
  content: string
  created_at: string
  is_read: boolean
  comment_count: number
}

function parseSseEvents(chunk: string): Array<Record<string, unknown>> {
  return chunk
    .split('\n')
    .filter((line) => line.startsWith('data: '))
    .flatMap((line) => {
      try {
        return [JSON.parse(line.slice(6))]
      } catch {
        return []
      }
    })
}

const TYPE_LABEL: Record<string, string> = {
  daily_brief: '주간 브리핑',
  analysis: '종목 심층 분석',
  macro: '매크로',
  discovery: '종목 탐색',
  portfolio_review: '포트폴리오 점검',
}

const TYPE_COLOR: Record<string, string> = {
  daily_brief: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-200',
  analysis: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-200',
  macro: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200',
  discovery: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-200',
  portfolio_review: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900 dark:text-cyan-200',
}

const PORTFOLIO_REVIEW_SECTIONS = [
  { key: 'portfolio_overview', label: '1. 포트폴리오 개요' },
  { key: 'holdings_assessment', label: '2. 종목별 평가' },
  { key: 'concentration_risk', label: '3. 집중도 리스크' },
  { key: 'thesis_health_check', label: '4. Thesis 건전성 체크' },
  { key: 'action_items', label: '5. 실행 항목' },
]

const DISCOVERY_SECTIONS = [
  { key: 'theme_analysis', label: '1. 테마 분석' },
  { key: 'us_picks', label: '2. 미국 추천 종목' },
  { key: 'kr_picks', label: '3. 한국 추천 종목' },
  { key: 'screening_criteria', label: '4. 선별 기준' },
  { key: 'next_steps', label: '5. 다음 단계' },
]

const DEEP_SECTIONS = [
  { key: 'business_overview', label: '1. 기업 개요' },
  { key: 'competitive_position', label: '2. 경쟁 구도' },
  { key: 'financial_analysis', label: '3. 재무 심층 분석' },
  { key: 'management_track_record', label: '4. 경영진 의사결정 이력' },
  { key: 'valuation', label: '5. 밸류에이션' },
  { key: 'risk_matrix', label: '6. 리스크 매트릭스' },
  { key: 'recent_developments', label: '7. 최근 동향' },
  { key: 'bull_bear_synthesis', label: '8. 강세/약세 종합' },
]

const BRIEFING_SECTIONS = [
  { key: 'macro_changes', label: '1. 매크로 변화' },
  { key: 'break_summary', label: '2. 모니터링 요약' },
  { key: 'upcoming_events', label: '3. 예정 이벤트' },
  // legacy daily_brief
  { key: 'macro', label: '1. 매크로 환경' },
  { key: 'portfolio_summary', label: '2. 포트폴리오 브리핑' },
  { key: 'watchlist', label: '3. 관심 종목' },
]

const MACRO_SECTIONS = [
  { key: 'market_overview', label: '1. 시장 환경' },
  { key: 'macro_factors', label: '2. 매크로 요인' },
  { key: 'portfolio_implication', label: '3. 포트폴리오 시사점' },
]

function extractSection(content: string, sectionName: string): string {
  const pattern = new RegExp(`<section name="${sectionName}">(.*?)</section>`, 's')
  const match = content.match(pattern)
  return match ? match[1].trim() : ''
}

// ── HumanResponse 슬롯 ────────────────────────────────────────────────────────

const RESPONSE_OPTIONS: { value: HumanResponseType; label: string; icon: ReactNode; color: string }[] = [
  { value: 'agree',     label: '동의',     icon: <ThumbsUp size={12} />,    color: 'text-emerald-600 dark:text-emerald-400' },
  { value: 'disagree',  label: '반대',     icon: <ThumbsDown size={12} />,  color: 'text-red-600 dark:text-red-400' },
  { value: 'partial',   label: '부분동의', icon: <Minus size={12} />,       color: 'text-amber-600 dark:text-amber-400' },
  { value: 'override',  label: '내 판단',  icon: <AlertCircle size={12} />, color: 'text-blue-600 dark:text-blue-400' },
  { value: 'note',      label: '메모',     icon: <StickyNote size={12} />,  color: 'text-gray-600 dark:text-gray-400' },
]

const RESPONSE_COLOR: Record<HumanResponseType, string> = {
  agree:    'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  disagree: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  partial:  'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  override: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  note:     'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
}

function SectionResponseSlot({
  reportId,
  sectionKey,
}: {
  reportId: string
  sectionKey: string
}) {
  const [open, setOpen] = useState(false)
  const [responses, setResponses] = useState<HumanResponse[]>([])
  const [loaded, setLoaded] = useState(false)
  const [type, setType] = useState<HumanResponseType>('note')
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)

  async function load() {
    if (loaded) return
    const res = await fetch(`/api/human-responses?target_type=report&target_id=${reportId}`)
    if (res.ok) {
      const all: HumanResponse[] = await res.json()
      setResponses(all.filter(r => r.section_key === sectionKey))
    }
    setLoaded(true)
  }

  function toggle() {
    if (!open) load()
    setOpen(v => !v)
  }

  async function submit() {
    if (!text.trim()) return
    setSaving(true)
    try {
      const res = await fetch('/api/human-responses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_type: 'report',
          target_id: reportId,
          section_key: sectionKey,
          response_type: type,
          content: text.trim(),
        }),
      })
      if (res.ok) {
        const created: HumanResponse = await res.json()
        setResponses(prev => [...prev, created])
        setText('')
      }
    } finally {
      setSaving(false)
    }
  }

  async function del(id: string) {
    const res = await fetch(`/api/human-responses/${id}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) setResponses(prev => prev.filter(r => r.id !== id))
  }

  const count = responses.length

  return (
    <div className="mt-1">
      <button
        onClick={toggle}
        className={`flex items-center gap-1 text-xs transition-colors ${
          count > 0
            ? 'text-blue-600 dark:text-blue-400'
            : 'text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-400'
        }`}
        title="내 메모 추가"
      >
        <StickyNote size={12} />
        {count > 0 && <span>{count}</span>}
      </button>

      {open && (
        <div className="mt-2 bg-gray-100 dark:bg-gray-800/60 border border-gray-300 dark:border-gray-700 rounded-lg p-3 space-y-3">
          {responses.length > 0 && (
            <div className="space-y-2">
              {responses.map(r => (
                <div key={r.id} className="group flex items-start gap-2">
                  <span className={`text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${RESPONSE_COLOR[r.response_type as HumanResponseType]}`}>
                    {RESPONSE_OPTIONS.find(o => o.value === r.response_type)?.label}
                  </span>
                  <p className="text-xs text-gray-700 dark:text-gray-300 leading-relaxed flex-1">{r.content}</p>
                  <button
                    onClick={() => del(r.id)}
                    className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-400 transition-all"
                  >
                    <X size={11} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-1 flex-wrap">
            {RESPONSE_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setType(opt.value)}
                className={`flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors ${
                  type === opt.value
                    ? RESPONSE_COLOR[opt.value] + ' border-transparent'
                    : 'border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                }`}
              >
                {opt.icon}
                {opt.label}
              </button>
            ))}
          </div>

          <div className="flex gap-2">
            <input
              value={text}
              onChange={e => setText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
              placeholder="이 섹션에 대한 내 생각..."
              className="flex-1 bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded px-2 py-1.5 text-xs text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 focus:outline-none focus:border-gray-400 dark:focus:border-gray-500"
              disabled={saving}
            />
            <button
              onClick={submit}
              disabled={saving || !text.trim()}
              className="flex-shrink-0 bg-gray-200 dark:bg-gray-700 hover:bg-gray-300 dark:hover:bg-gray-600 disabled:opacity-40 text-gray-900 dark:text-white px-2 rounded transition-colors"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Report View Components ────────────────────────────────────────────────────

function CollapsibleSectionView({
  sections,
  defaultOpen,
  report,
  withResponse = false,
}: {
  sections: { key: string; label: string }[]
  defaultOpen: string[]
  report: Report
  withResponse?: boolean
}) {
  const [openSections, setOpenSections] = useState<Set<string>>(new Set(defaultOpen))

  function toggle(key: string) {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const hasSections = sections.some(({ key }) => extractSection(report.content, key))
  if (!hasSections) return <Markdown content={report.content} />

  return (
    <div className="space-y-2">
      {sections.map(({ key, label }) => {
        const text = extractSection(report.content, key)
        if (!text) return null
        const isOpen = openSections.has(key)
        return (
          <div key={key} className="border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(key)}
              className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-100 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-750 transition-colors"
            >
              <span className="text-gray-900 dark:text-white text-sm font-medium">{label}</span>
              {isOpen
                ? <ChevronUp size={15} className="text-gray-500 dark:text-gray-400 flex-shrink-0" />
                : <ChevronDown size={15} className="text-gray-500 dark:text-gray-400 flex-shrink-0" />
              }
            </button>
            {isOpen && (
              <div className="px-4 py-4 bg-gray-50 dark:bg-gray-900 border-t border-gray-300 dark:border-gray-700">
                <Markdown content={text} />
                {withResponse && (
                  <SectionResponseSlot reportId={report.id} sectionKey={key} />
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function DeepReportView({ report }: { report: Report }) {
  return (
    <CollapsibleSectionView
      sections={DEEP_SECTIONS}
      defaultOpen={['business_overview', 'bull_bear_synthesis']}
      report={report}
      withResponse
    />
  )
}

function PortfolioReviewView({ report }: { report: Report }) {
  return (
    <CollapsibleSectionView
      sections={PORTFOLIO_REVIEW_SECTIONS}
      defaultOpen={['portfolio_overview', 'holdings_assessment', 'action_items']}
      report={report}
      withResponse
    />
  )
}

type AddState = 'idle' | 'loading' | 'added' | 'exists'
interface ExtractedTicker { symbol: string; name: string; market: 'US_Stock' | 'KR_Stock' }

function extractDiscoveryTickers(content: string): ExtractedTicker[] {
  const RE = /\*\*\[([A-Z0-9]+)\]\s+([^\*\n]+?)\*\*/g
  const result: ExtractedTicker[] = []
  const seen = new Set<string>()
  for (const [section, market] of [['us_picks', 'US_Stock'], ['kr_picks', 'KR_Stock']] as const) {
    const text = extractSection(content, section)
    RE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = RE.exec(text)) !== null) {
      const symbol = m[1].trim()
      if (!seen.has(symbol)) {
        seen.add(symbol)
        result.push({ symbol, name: m[2].trim(), market })
      }
    }
  }
  return result
}

function DiscoveryReportView({ report }: { report: Report }) {
  const [addStates, setAddStates] = useState<Record<string, AddState>>({})
  useEffect(() => { setAddStates({}) }, [report.id])
  const extractedTickers = useMemo(() => extractDiscoveryTickers(report.content), [report.content])

  async function addToWatchlist(ticker: ExtractedTicker) {
    const cur = addStates[ticker.symbol] ?? 'idle'
    if (cur === 'loading' || cur === 'added' || cur === 'exists') return
    setAddStates(prev => ({ ...prev, [ticker.symbol]: 'loading' }))
    try {
      const res = await fetch('/api/tickers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: ticker.symbol, name: ticker.name, market: ticker.market, status: 'watchlist' }),
      })
      setAddStates(prev => ({ ...prev, [ticker.symbol]: res.status === 201 ? 'added' : 'exists' }))
    } catch {
      setAddStates(prev => ({ ...prev, [ticker.symbol]: 'idle' }))
    }
  }

  return (
    <div className="space-y-3">
      {extractedTickers.length > 0 && (
        <div className="bg-gray-100 dark:bg-gray-800/40 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-3 space-y-2.5">
          <p className="text-xs text-gray-500 dark:text-gray-400 font-medium">추천 종목 — 관심 목록 추가</p>
          <div className="flex flex-wrap gap-2">
            {extractedTickers.map(t => {
              const state = addStates[t.symbol] ?? 'idle'
              const done = state === 'added' || state === 'exists'
              const isKr = t.market === 'KR_Stock'
              return (
                <button
                  key={t.symbol}
                  onClick={() => addToWatchlist(t)}
                  disabled={done || state === 'loading'}
                  title={done ? (state === 'added' ? '관심 목록에 추가됨' : '이미 추가된 종목') : t.name}
                  className={`flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-lg border transition-colors ${
                    done
                      ? 'border-emerald-700 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 cursor-default'
                      : state === 'loading'
                      ? 'border-gray-400 dark:border-gray-600 bg-gray-100 dark:bg-gray-800 text-gray-400 dark:text-gray-500 cursor-wait'
                      : 'border-gray-400 dark:border-gray-600 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:border-emerald-500 dark:hover:border-emerald-600 hover:text-gray-900 dark:hover:text-white'
                  }`}
                >
                  <span className={`font-medium px-1 py-0.5 rounded text-xs ${isKr ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300' : 'bg-violet-100 text-violet-600 dark:bg-violet-900/60 dark:text-violet-300'}`}>
                    {isKr ? 'KR' : 'US'}
                  </span>
                  <span className="font-semibold">{t.symbol}</span>
                  {state === 'loading' ? <Loader2 size={11} className="animate-spin" /> : done ? <CheckCircle size={11} /> : <Plus size={11} />}
                </button>
              )
            })}
          </div>
        </div>
      )}
      <CollapsibleSectionView
        sections={DISCOVERY_SECTIONS}
        defaultOpen={['theme_analysis', 'us_picks', 'kr_picks']}
        report={report}
        withResponse
      />
    </div>
  )
}

function BriefingView({ report }: { report: Report }) {
  // 주간 브리핑 섹션 먼저, 없으면 구형 daily_brief 섹션
  const weeklyKeys = ['macro_changes', 'break_summary', 'upcoming_events']
  const isWeekly = weeklyKeys.some(k => extractSection(report.content, k))
  const sections = isWeekly
    ? BRIEFING_SECTIONS.filter(s => weeklyKeys.includes(s.key))
    : BRIEFING_SECTIONS.filter(s => ['macro', 'portfolio_summary', 'watchlist'].includes(s.key))
  return (
    <CollapsibleSectionView
      sections={sections}
      defaultOpen={sections.map(s => s.key)}
      report={report}
    />
  )
}

function MacroReportView({ report }: { report: Report }) {
  return (
    <CollapsibleSectionView
      sections={MACRO_SECTIONS}
      defaultOpen={MACRO_SECTIONS.map(s => s.key)}
      report={report}
    />
  )
}

// ── CopyPromptButton ──────────────────────────────────────────────────────────

function PromptModal({ text, title, onClose }: { text: string; title: string; onClose: () => void }) {
  const [innerCopied, setInnerCopied] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  function selectAll() {
    taRef.current?.select()
  }

  async function doCopy() {
    if (!text) return
    try {
      if (navigator.clipboard) {
        await navigator.clipboard.writeText(text)
      } else {
        taRef.current?.select()
        document.execCommand('copy')
      }
      setInnerCopied(true)
      setTimeout(() => setInnerCopied(false), 2000)
    } catch { /* ignore */ }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-2xl w-full max-w-2xl p-5 space-y-4 max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between">
          <h2 className="text-gray-900 dark:text-white font-semibold text-base">{title}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X size={18} />
          </button>
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400">아래 텍스트를 복사해서 Claude에 붙여넣으세요.</p>
        <textarea
          ref={taRef}
          readOnly
          value={text}
          onClick={selectAll}
          rows={14}
          className="flex-1 w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-700 dark:text-gray-200 font-mono resize-none focus:outline-none focus:border-gray-400 cursor-pointer"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">
            닫기
          </button>
          <button
            onClick={doCopy}
            className="flex items-center gap-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {innerCopied ? <><Check size={14} /> 복사됨!</> : <><Copy size={14} /> 전체 복사</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function CopyPromptButton({
  type,
  label,
  title,
  className,
}: {
  type: string
  label: ReactNode
  title: string
  className: string
}) {
  const [state, setState] = useState<'idle' | 'loading' | 'copied' | 'error'>('idle')
  const [promptText, setPromptText] = useState<string | null>(null)

  async function copyPrompt() {
    if (state === 'loading' || state === 'copied') return
    setState('loading')
    setPromptText(null)
    try {
      const res = await fetch(`/api/reports/explore-prompt?type=${type}`)
      if (!res.ok) {
        setState('error')
        setTimeout(() => setState('idle'), 3000)
        return
      }
      const { prompt } = await res.json()

      // 클립보드 API 시도 (HTTPS 또는 localhost에서만 작동)
      if (navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(prompt)
          setState('copied')
          setTimeout(() => setState('idle'), 2500)
          return
        } catch { /* fallthrough to modal */ }
      }

      // 폴백: 모달로 텍스트 표시
      setPromptText(prompt)
      setState('idle')
    } catch {
      setState('error')
      setTimeout(() => setState('idle'), 3000)
    }
  }

  return (
    <>
      <button
        onClick={copyPrompt}
        disabled={state === 'loading'}
        className={`flex items-center gap-1.5 text-white text-xs font-medium px-2.5 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors disabled:opacity-50 ${className}`}
      >
        {state === 'loading'
          ? <Loader2 size={13} className="animate-spin" />
          : state === 'copied'
          ? <><Check size={13} /> 복사됨</>
          : state === 'error'
          ? <><X size={13} /> 오류</>
          : <>{label}</>
        }
      </button>
      {promptText && (
        <PromptModal
          text={promptText}
          title={title}
          onClose={() => setPromptText(null)}
        />
      )}
    </>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const navigate = useNavigate()
  const { fontSize } = useTheme()
  const [searchParams] = useSearchParams()
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [triggeringMacro, setTriggeringMacro] = useState(false)
  const [selected, setSelected] = useState<Report | null>(null)
  const [mobileShowDetail, setMobileShowDetail] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  const [filterType, setFilterType] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [deletingBulk, setDeletingBulk] = useState(false)

  const filteredReports = filterType ? reports.filter(r => r.type === filterType) : reports

  const [comments, setComments] = useState<ReportComment[]>([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [commentText, setCommentText] = useState('')
  const [submittingComment, setSubmittingComment] = useState(false)
  const [showComments, setShowComments] = useState(false)

  async function fetchReports() {
    setLoading(true)
    try {
      const res = await fetch('/api/reports')
      if (res.ok) {
        const data: Report[] = await res.json()
        setReports(data)
        const targetId = searchParams.get('id')
        if (targetId) {
          const found = data.find(r => r.id === targetId)
          if (found) selectReport(found)
        }
      }
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
    if (!confirm(`"${TYPE_LABEL[r.type] ?? r.type}${r.ticker_name ?? r.ticker_symbol ? ` — ${r.ticker_name ?? r.ticker_symbol}` : ''}" 보고서를 삭제할까요?`)) return
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
    if (selectedIds.size === filteredReports.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(filteredReports.map(r => r.id)))
  }

  async function deleteSelected() {
    if (selectedIds.size === 0) return
    if (!confirm(`선택한 보고서 ${selectedIds.size}개를 삭제할까요?`)) return
    setDeletingBulk(true)
    try {
      await Promise.all([...selectedIds].map(id => fetch(`/api/reports/${id}`, { method: 'DELETE' })))
      const remaining = reports.filter(r => !selectedIds.has(r.id))
      setReports(remaining)
      setSelectedIds(new Set())
      if (selected && selectedIds.has(selected.id)) {
        setSelected(remaining[0] ?? null)
        if (!remaining[0]) setMobileShowDetail(false)
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

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      <header className="border-b border-gray-200 dark:border-gray-800 px-3 py-3 sm:px-6 sm:py-4">
        <div className="max-w-[1400px] mx-auto">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 flex-shrink-0">
              <button onClick={() => navigate('/')} className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
                <ArrowLeft size={20} />
              </button>
              <button
                onClick={() => setSidebarCollapsed(v => !v)}
                className="hidden lg:flex items-center justify-center w-8 h-8 rounded-lg transition-colors text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800"
                title={sidebarCollapsed ? '목록 펼치기' : '목록 접기'}
              >
                <PanelLeft size={17} className={sidebarCollapsed ? 'opacity-40' : ''} />
              </button>
              <div className="flex items-center gap-2">
                <FileText className="text-blue-600 dark:text-blue-400" size={18} />
                <h1 className="text-base sm:text-lg font-bold text-gray-900 dark:text-white">보고서</h1>
              </div>
            </div>
            <div className="flex items-center gap-1.5 flex-wrap justify-end">
              <ThemeControls />
              <CopyPromptButton
                type="portfolio_review"
                label={<><BarChart2 size={13} /><span className="hidden sm:inline">포트폴리오 점검 프롬프트</span><span className="sm:hidden">점검 프롬프트</span></>}
                title="포트폴리오 점검 프롬프트"
                className="bg-cyan-700 hover:bg-cyan-600"
              />
              <CopyPromptButton
                type="discovery"
                label={<><Copy size={13} /><span className="hidden sm:inline">종목 탐색 프롬프트</span><span className="sm:hidden">탐색 프롬프트</span></>}
                title="종목 탐색 프롬프트"
                className="bg-emerald-700 hover:bg-emerald-600"
              />
              <button
                onClick={triggerMacro}
                disabled={triggeringMacro}
                className="flex items-center gap-1.5 bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-xs font-medium px-2.5 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors"
              >
                {triggeringMacro
                  ? <Loader2 size={13} className="animate-spin" />
                  : <><RefreshCw size={13} /> 매크로</>
                }
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-[1400px] mx-auto px-3 sm:px-6 py-4 sm:py-8">
        <div className="lg:flex lg:gap-6">
          {/* 목록 */}
          <div className={`flex-shrink-0 overflow-hidden transition-[width] duration-200 ease-in-out ${mobileShowDetail ? 'hidden lg:block' : 'block'} ${sidebarCollapsed ? 'lg:w-0' : 'lg:w-72'}`}>
            {!loading && reports.length > 0 && (
              <div className="flex gap-1 overflow-x-auto pb-2 mb-3 scrollbar-hide">
                <button
                  onClick={() => { setFilterType(null); setSelectedIds(new Set()) }}
                  className={`flex-shrink-0 text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    filterType === null
                      ? 'bg-gray-200 dark:bg-gray-700 border-gray-400 dark:border-gray-600 text-gray-900 dark:text-white'
                      : 'bg-transparent border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
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
                          ? `border-transparent text-gray-900 dark:text-white ${TYPE_COLOR[type]}`
                          : 'bg-transparent border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
                      }`}
                    >
                      {label} {count}
                    </button>
                  )
                })}
              </div>
            )}

            {filteredReports.length > 0 && (
              <div className="flex items-center gap-2 mb-2 px-1">
                <input
                  type="checkbox"
                  checked={selectedIds.size > 0 && selectedIds.size === filteredReports.length}
                  ref={(el: HTMLInputElement | null) => { if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < filteredReports.length }}
                  onChange={toggleSelectAll}
                  className="w-3.5 h-3.5 rounded border-gray-400 dark:border-gray-600 bg-gray-100 dark:bg-gray-800 accent-blue-500 cursor-pointer"
                />
                {selectedIds.size > 0 ? (
                  <>
                    <span className="text-xs text-gray-500 dark:text-gray-400 flex-1">{selectedIds.size}개 선택됨</span>
                    <button
                      onClick={deleteSelected}
                      disabled={deletingBulk}
                      className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400 hover:text-red-300 disabled:opacity-50 transition-colors"
                    >
                      {deletingBulk ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      삭제
                    </button>
                  </>
                ) : (
                  <span className="text-xs text-gray-500 dark:text-gray-600">전체선택</span>
                )}
              </div>
            )}

            {loading && <p className="text-gray-400 dark:text-gray-500 text-sm text-center py-8">불러오는 중...</p>}
            {!loading && reports.length === 0 && (
              <p className="text-gray-500 dark:text-gray-600 text-sm text-center py-8">보고서가 없습니다.</p>
            )}
            {!loading && filteredReports.length === 0 && reports.length > 0 && (
              <p className="text-gray-500 dark:text-gray-600 text-sm text-center py-6">해당 종류의 보고서가 없습니다.</p>
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
                        ? 'bg-gray-100 dark:bg-gray-800 border-gray-400 dark:border-gray-600'
                        : isSelected
                        ? 'bg-gray-200 dark:bg-gray-800/60 border-gray-300 dark:border-gray-700'
                        : 'bg-gray-50 dark:bg-gray-900 border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700'
                    }`}
                  >
                    <div className="flex items-center pl-3 pr-1 cursor-pointer" onClick={(e) => toggleSelect(r.id, e)}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => {}}
                        className="w-3.5 h-3.5 rounded border-gray-400 dark:border-gray-600 bg-gray-100 dark:bg-gray-800 accent-blue-500 pointer-events-none"
                      />
                    </div>
                    <button className="flex-1 text-left px-3 py-3 min-w-0" onClick={() => selectReport(r)}>
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        {!r.is_read && (
                          <span className="w-1.5 h-1.5 rounded-full bg-blue-400 flex-shrink-0" title="읽지 않음" />
                        )}
                        {!filterType && (
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${TYPE_COLOR[r.type] ?? 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300'}`}>
                            {TYPE_LABEL[r.type] ?? r.type}
                          </span>
                        )}
                        {(r.ticker_name ?? r.ticker_symbol) && (
                          <span className="text-xs font-semibold text-gray-900 dark:text-white">
                            {r.ticker_name ?? r.ticker_symbol}
                            {r.ticker_name && r.ticker_symbol && (
                              <span className="ml-1 font-normal text-gray-400 dark:text-gray-500">{r.ticker_symbol}</span>
                            )}
                          </span>
                        )}
                        {isLatest && (
                          <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">최신</span>
                        )}
                        {r.comment_count > 0 && (
                          <span className="ml-auto flex items-center gap-0.5 text-xs text-gray-400 dark:text-gray-500">
                            <MessageSquare size={10} />
                            {r.comment_count}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-400 dark:text-gray-500">{fmtKST(r.created_at)}</p>
                    </button>
                  </div>
                )
              })}
            </div>
          </div>

          {/* 본문 */}
          <div className={`flex-1 min-w-0 ${mobileShowDetail ? 'block' : 'hidden lg:block'}`}>
            {selected ? (
              <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 sm:px-6 py-4 border-b border-gray-200 dark:border-gray-800 flex-wrap">
                  <button
                    onClick={() => setMobileShowDetail(false)}
                    className="lg:hidden text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors flex-shrink-0"
                  >
                    <ArrowLeft size={18} />
                  </button>
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${TYPE_COLOR[selected.type] ?? ''}`}>
                    {TYPE_LABEL[selected.type] ?? selected.type}
                  </span>
                  {(selected.ticker_name ?? selected.ticker_symbol) && (
                    <span className="text-sm font-bold text-gray-900 dark:text-white">
                      {selected.ticker_name ?? selected.ticker_symbol}
                      {selected.ticker_name && selected.ticker_symbol && (
                        <span className="ml-1.5 text-xs font-normal text-gray-400 dark:text-gray-500">{selected.ticker_symbol}</span>
                      )}
                    </span>
                  )}
                  <span className="text-xs text-gray-400 dark:text-gray-500">{fmtKST(selected.created_at)}</span>
                  <div className="ml-auto flex items-center gap-1">
                    <button
                      onClick={(e) => toggleRead(selected, e)}
                      title={selected.is_read ? '읽지 않음으로 표시' : '읽음으로 표시'}
                      className="p-1.5 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                    >
                      {selected.is_read ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                    <button
                      onClick={() => deleteReport(selected)}
                      title="보고서 삭제"
                      className="p-1.5 rounded-lg text-gray-400 dark:text-gray-500 hover:text-red-400 transition-colors"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                <div className={`p-4 sm:p-6 fs-${fontSize}`}>
                  {selected.type === 'analysis'
                    ? <DeepReportView report={selected} />
                    : selected.type === 'discovery'
                    ? <DiscoveryReportView report={selected} />
                    : selected.type === 'portfolio_review'
                    ? <PortfolioReviewView report={selected} />
                    : selected.type === 'macro'
                    ? <MacroReportView report={selected} />
                    : selected.type === 'daily_brief'
                    ? <BriefingView report={selected} />
                    : <Markdown content={selected.content} />
                  }
                </div>

                <div className="border-t border-gray-200 dark:border-gray-800">
                  <button
                    onClick={toggleComments}
                    className="w-full flex items-center gap-2 px-4 sm:px-6 py-3 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors"
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
                      {commentsLoading ? (
                        <div className="flex items-center gap-2 text-gray-400 dark:text-gray-500 text-sm py-2">
                          <Loader2 size={13} className="animate-spin" /> 불러오는 중...
                        </div>
                      ) : comments.length > 0 ? (
                        <div className="space-y-2">
                          {comments.map(c => (
                            <div key={c.id} className="group bg-gray-200 dark:bg-gray-800/50 rounded-lg px-4 py-3">
                              <div className="flex items-start justify-between gap-2">
                                <p className="text-sm text-gray-700 dark:text-gray-200 leading-relaxed flex-1">{c.content}</p>
                                <button
                                  onClick={() => deleteComment(c.id)}
                                  className="opacity-0 group-hover:opacity-100 text-gray-500 dark:text-gray-600 hover:text-red-400 transition-all flex-shrink-0 mt-0.5"
                                >
                                  <X size={13} />
                                </button>
                              </div>
                              <p className="text-xs text-gray-500 dark:text-gray-600 mt-1.5">{fmtKST(c.created_at)}</p>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-gray-500 dark:text-gray-600 py-1">아직 코멘트가 없습니다.</p>
                      )}

                      <div className="flex gap-2">
                        <textarea
                          value={commentText}
                          onChange={e => setCommentText(e.target.value)}
                          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submitComment() }}
                          placeholder="투자 인사이트, 후속 관찰 사항... (⌘Enter로 저장)"
                          rows={2}
                          disabled={submittingComment}
                          className="flex-1 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-gray-400 dark:focus:border-gray-500 disabled:opacity-50"
                        />
                        <button
                          onClick={submitComment}
                          disabled={submittingComment || !commentText.trim()}
                          className="flex-shrink-0 bg-gray-200 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-40 text-gray-900 dark:text-white px-3 rounded-lg transition-colors"
                        >
                          {submittingComment ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="hidden lg:flex items-center justify-center h-64 text-gray-500 dark:text-gray-600">
                <p>왼쪽에서 보고서를 선택하세요.</p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
