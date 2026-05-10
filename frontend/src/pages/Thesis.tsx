import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, Sparkles, CheckCircle, AlertTriangle,
  ChevronDown, ChevronUp, Loader2, FileText, Bell, PenLine, RefreshCw,
  Database, BarChart2, ExternalLink, Trash2, Link, GitBranch,
  Globe, Clock, Copy, Check, X, Search,
} from 'lucide-react'
import { api } from '../api'
import { fmtKST } from '../utils/date'
import { Markdown } from '../components/Markdown'
import { ThemeControls } from '../components/ThemeControls'
import { useTheme } from '../contexts/ThemeContext'
import type { Thesis, Ticker, FinancialData, SecSummary, ConversationImport, BreakSignal, VerdictType, InvestmentCycle } from '../types'


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
type ActiveTab = 'thesis' | 'data' | 'reports' | 'versions'

const STOCK_TYPE_OPTIONS = [
  {
    value: 'compounding',
    label: 'Compounding',
    desc: '지속 복리 성장',
    valuation: 'DCF / P/FCF',
    signals: ['ROIC 15%+ 지속', 'FCF 전환율 높음', '경쟁 구조 안정적', '재투자 기회 남아 있음'],
  },
  {
    value: 'growth',
    label: 'Growth',
    desc: '고성장 초기 기업',
    valuation: 'EV/Revenue · Reverse DCF',
    signals: ['매출 CAGR 20%+', 'TAM 대비 침투율 낮음', 'Gross Margin 개선 중', '흑자 전환 경로 보임'],
  },
  {
    value: 'asset_play',
    label: 'Asset Play',
    desc: '저평가 자산',
    valuation: 'NAV · P/B',
    signals: ['P/B < 1 또는 시총 ≈ 보유 현금/자산', '자산 매각·재평가 촉매 존재', '시장이 자산 가치를 무시하는 상황'],
  },
  {
    value: 'turnaround',
    label: 'Turnaround',
    desc: '회복 촉매',
    valuation: '정상화 EV/EBITDA',
    signals: ['최근 실적 부진, 구체적 촉매 존재', '신경영진·구조조정·사업 분리', 'Cash runway 확인 필요'],
  },
  {
    value: 'cyclical',
    label: 'Cyclical',
    desc: '사이클 저점',
    valuation: 'Mid-cycle EV/EBITDA',
    signals: ['현재 이익이 역대 평균보다 낮음', '부채 수준 저점 생존 가능', '사이클 선행지표 바닥 근처'],
  },
  {
    value: 'special_situation',
    label: 'Special Situation',
    desc: '이벤트 드리븐',
    valuation: '이벤트 기대가치',
    signals: ['M&A·스핀오프·구조조정 진행 중', '이벤트 완료 시 가치 실현 명확', '이벤트 무산 시 하방 제한'],
  },
] as const

const STOCK_TYPE_LABEL: Record<string, string> = {
  compounding: 'Compounding',
  growth: 'Growth',
  asset_play: 'Asset Play',
  turnaround: 'Turnaround',
  cyclical: 'Cyclical',
  special_situation: 'Special Situation',
}

// ── TickerPromptButton (Step 3/4 외부 탐색) ───────────────────────────────────

function TickerPromptModal({ text, title, onClose }: { text: string; title: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const taRef = useRef<HTMLTextAreaElement>(null)

  async function doCopy() {
    try {
      if (navigator.clipboard) await navigator.clipboard.writeText(text)
      else { taRef.current?.select(); document.execCommand('copy') }
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
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
        <p className="text-xs text-gray-500 dark:text-gray-400">
          아래 텍스트를 복사해서 외부 Claude에 붙여넣으세요. 탐색 후 결과를 Journal → 탐색결과 탭에 기록하세요.
        </p>
        <textarea
          ref={taRef}
          readOnly
          value={text}
          onClick={() => taRef.current?.select()}
          rows={16}
          className="flex-1 w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-700 dark:text-gray-200 font-mono resize-none focus:outline-none cursor-pointer"
        />
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200">닫기</button>
          <button
            onClick={doCopy}
            className="flex items-center gap-1.5 bg-emerald-700 hover:bg-emerald-600 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            {copied ? <><Check size={14} /> 복사됨!</> : <><Copy size={14} /> 전체 복사</>}
          </button>
        </div>
      </div>
    </div>
  )
}

function TickerPromptButton({
  tickerId,
  promptType,
  label,
  title,
  className,
  signalId,
}: {
  tickerId: string
  promptType: string
  label: ReactNode
  title: string
  className: string
  signalId?: string
}) {
  const [state, setState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [promptText, setPromptText] = useState<string | null>(null)

  async function fetchPrompt() {
    if (state === 'loading') return
    setState('loading')
    setPromptText(null)
    try {
      const params = new URLSearchParams({ type: promptType })
      if (signalId) params.set('signal_id', signalId)
      const res = await fetch(`/api/tickers/${tickerId}/explore-prompt?${params.toString()}`)
      if (!res.ok) { setState('error'); setTimeout(() => setState('idle'), 3000); return }
      const { prompt } = await res.json()

      if (navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(prompt)
          setState('idle')
          // 복사 성공이면 그냥 모달 없이 토스트처럼 — 하지만 모달도 열어서 내용 확인 가능하게
          setPromptText(prompt)
          return
        } catch { /* fallthrough */ }
      }
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
        onClick={fetchPrompt}
        disabled={state === 'loading'}
        className={`flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors disabled:opacity-50 ${className}`}
      >
        {state === 'loading'
          ? <Loader2 size={12} className="animate-spin" />
          : state === 'error'
          ? <><X size={12} /> 오류</>
          : <>{label}</>
        }
      </button>
      {promptText && (
        <TickerPromptModal
          text={promptText}
          title={title}
          onClose={() => setPromptText(null)}
        />
      )}
    </>
  )
}

// ── BreakSignalSection ────────────────────────────────────────────────────────

const VERDICT_OPTIONS: { value: VerdictType; label: string; color: string; bg: string }[] = [
  { value: 'strengthening', label: '강화', color: 'text-blue-700 dark:text-blue-300', bg: 'bg-blue-100 dark:bg-blue-900/40 border-blue-300 dark:border-blue-700' },
  { value: 'intact',    label: '✅ Intact',    color: 'text-emerald-700 dark:text-emerald-300', bg: 'bg-emerald-100 dark:bg-emerald-900/40 border-emerald-300 dark:border-emerald-700' },
  { value: 'weakening', label: '⚠️ Weakening', color: 'text-amber-700 dark:text-amber-300',   bg: 'bg-amber-100 dark:bg-amber-900/40 border-amber-300 dark:border-amber-700' },
  { value: 'broken',    label: '🚨 Broken',    color: 'text-red-700 dark:text-red-300',       bg: 'bg-red-100 dark:bg-red-900/40 border-red-300 dark:border-red-700' },
]

function VerdictBadge({ verdict }: { verdict: VerdictType }) {
  const opt = VERDICT_OPTIONS.find(o => o.value === verdict)
  if (!opt) return null
  return (
    <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${opt.bg} ${opt.color}`}>
      {opt.label}
    </span>
  )
}

function BreakSignalCard({
  signal,
  onVerdictSet,
  onCreateRevision,
}: {
  signal: BreakSignal
  onVerdictSet: (id: string, verdict: VerdictType, note: string) => Promise<void>
  onCreateRevision: (signal: BreakSignal) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(!signal.verdict)
  const [selectedVerdict, setSelectedVerdict] = useState<VerdictType | null>(signal.verdict)
  const [note, setNote] = useState(signal.human_note ?? '')
  const [saving, setSaving] = useState(false)
  const [creatingRevision, setCreatingRevision] = useState(false)

  const isPending = !signal.verdict
  const { fmtKST } = { fmtKST: (s: string) => new Date(s.endsWith('Z') ? s : s + 'Z').toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }

  async function submit() {
    if (!selectedVerdict) return
    setSaving(true)
    try {
      await onVerdictSet(signal.id, selectedVerdict, note)
    } finally {
      setSaving(false)
    }
  }

  async function createRevision() {
    setCreatingRevision(true)
    try {
      await onCreateRevision(signal)
    } finally {
      setCreatingRevision(false)
    }
  }

  return (
    <div className={`border rounded-xl overflow-hidden ${isPending ? 'border-amber-400 dark:border-amber-600' : 'border-gray-200 dark:border-gray-800'}`}>
      {/* 헤더 */}
      <button
        onClick={() => setExpanded(v => !v)}
        className={`w-full flex items-center gap-2 px-4 py-3 text-left ${isPending ? 'bg-amber-50 dark:bg-amber-900/20' : 'bg-gray-50 dark:bg-gray-900'}`}
      >
        {isPending && <span className="text-xs font-semibold text-amber-600 dark:text-amber-400 flex-shrink-0">판정 필요</span>}
        {signal.verdict && <VerdictBadge verdict={signal.verdict} />}
        <span className="text-xs text-gray-400 dark:text-gray-500 ml-auto flex-shrink-0">
          {new Date(signal.checked_at.endsWith('Z') ? signal.checked_at : signal.checked_at + 'Z')
            .toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
        </span>
        {expanded ? <ChevronUp size={13} className="text-gray-400 flex-shrink-0" /> : <ChevronDown size={13} className="text-gray-400 flex-shrink-0" />}
      </button>

      {expanded && (
        <div className="px-4 py-4 space-y-4 bg-white dark:bg-gray-950">
          {/* 관찰 내용 */}
          <div>
            <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2 flex items-center gap-1">
              <Bell size={11} /> 오늘의 관찰
            </p>
            <p className="text-sm text-gray-700 dark:text-gray-200 leading-relaxed whitespace-pre-wrap">
              {signal.observations}
            </p>
          </div>

          {signal.positive_signals && signal.positive_signals !== '특이사항 없음' && (
            <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg px-3 py-2">
              <p className="text-xs font-medium text-blue-700 dark:text-blue-300 mb-1.5">Thesis 강화 신호</p>
              <p className="text-sm text-blue-800 dark:text-blue-200 leading-relaxed whitespace-pre-wrap">{signal.positive_signals}</p>
            </div>
          )}

          {signal.negative_signals && signal.negative_signals !== '특이사항 없음' && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg px-3 py-2">
              <p className="text-xs font-medium text-red-700 dark:text-red-300 mb-1.5">Thesis 약화 신호</p>
              <p className="text-sm text-red-800 dark:text-red-200 leading-relaxed whitespace-pre-wrap">{signal.negative_signals}</p>
            </div>
          )}

          {/* 주목 항목 */}
          {signal.watch_items && (
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5">다음 확인 항목</p>
              <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">{signal.watch_items}</p>
            </div>
          )}

          {/* 감시 기준 스냅샷 */}
          {signal.key_logic_snapshot && (
            <div className="border-l-2 border-violet-400 pl-3">
              <p className="text-xs font-medium text-violet-500 dark:text-violet-400 mb-1 flex items-center gap-1"><Bell size={11} /> 모니터링 기준 (체크 시점)</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">{signal.key_logic_snapshot}</p>
            </div>
          )}

          {/* Verdict 입력 */}
          <div className="pt-2 border-t border-gray-100 dark:border-gray-800 space-y-3">
            <p className="text-xs font-medium text-gray-600 dark:text-gray-300">사람 판정</p>
            <div className="flex gap-2 flex-wrap">
              {VERDICT_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  onClick={() => setSelectedVerdict(opt.value)}
                  className={`text-xs font-medium px-3 py-1.5 rounded-lg border transition-colors ${
                    selectedVerdict === opt.value
                      ? opt.bg + ' ' + opt.color
                      : 'border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <textarea
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder="판정 이유 (선택) — 왜 이 판단을 내렸는가..."
              rows={2}
              className="w-full bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-violet-500"
            />
            <div className="flex justify-end">
              <button
                onClick={submit}
                disabled={saving || !selectedVerdict}
                className="flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white text-xs font-medium px-4 py-1.5 rounded-lg transition-colors"
              >
                {saving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
                판정 저장
              </button>
            </div>
          </div>

          <div className="pt-2 border-t border-gray-100 dark:border-gray-800 flex flex-wrap gap-2 justify-end">
            {signal.ticker_id && (
              <TickerPromptButton
                tickerId={signal.ticker_id}
                signalId={signal.id}
                promptType="thesis_revision"
                label={<><Globe size={12} /> 외부 재검토 프롬프트</>}
                title={`${signal.ticker_name ?? signal.ticker_symbol ?? ''} Thesis 재검토 프롬프트`}
                className="bg-blue-900/20 border-blue-700/50 text-blue-600 dark:text-blue-300 hover:bg-blue-900/40"
              />
            )}
            <button
              onClick={createRevision}
              disabled={creatingRevision}
              className="flex items-center gap-1.5 bg-gray-200 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 text-gray-800 dark:text-gray-200 text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-700 transition-colors"
            >
              {creatingRevision ? <Loader2 size={12} className="animate-spin" /> : <GitBranch size={12} />}
              새 버전 반영
            </button>
          </div>

          {/* 이미 판정된 경우 메모 표시 */}
          {signal.verdict && signal.human_note && !isPending && (
            <div className="bg-gray-50 dark:bg-gray-900 rounded-lg px-3 py-2">
              <p className="text-xs text-gray-500 dark:text-gray-400">내 판정 메모: {signal.human_note}</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function BreakSignalSection({
  signals,
  loaded,
  onRefresh,
  onVerdictSet,
  onCreateRevision,
}: {
  signals: BreakSignal[]
  loaded: boolean
  onRefresh: () => void
  onVerdictSet: (id: string, verdict: VerdictType, note: string) => Promise<void>
  onCreateRevision: (signal: BreakSignal) => Promise<void>
}) {
  const pending = signals.filter(s => !s.verdict)
  const [showAll, setShowAll] = useState(false)
  const displayed = showAll ? signals : signals.slice(0, 3)

  return (
    <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Bell size={14} className={pending.length > 0 ? 'text-amber-500' : 'text-gray-400 dark:text-gray-500'} />
        <span className="text-sm font-medium text-gray-900 dark:text-white">Break Monitor</span>
        {!loaded
          ? <Loader2 size={12} className="animate-spin text-gray-400" />
          : pending.length > 0
          ? <span className="text-xs bg-amber-100 text-amber-700 dark:bg-amber-900/60 dark:text-amber-300 px-1.5 py-0 rounded-full leading-5 font-medium">{pending.length} 판정 필요</span>
          : signals.length > 0
          ? <span className="text-xs text-gray-400 dark:text-gray-600">최근 {signals.length}건</span>
          : <span className="text-xs text-gray-400 dark:text-gray-600">기록 없음</span>
        }
        <button onClick={onRefresh} className="ml-auto text-gray-400 hover:text-gray-600 dark:hover:text-gray-300" title="새로고침">
          <RefreshCw size={11} />
        </button>
      </div>

      {loaded && signals.length === 0 && (
        <p className="text-xs text-gray-400 dark:text-gray-600">
          Break Monitor 실행 시 관찰 결과가 여기에 기록됩니다.
        </p>
      )}

      {displayed.map(s => (
        <BreakSignalCard key={s.id} signal={s} onVerdictSet={onVerdictSet} onCreateRevision={onCreateRevision} />
      ))}

      {signals.length > 3 && (
        <button
          onClick={() => setShowAll(v => !v)}
          className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 w-full text-center"
        >
          {showAll ? '▲ 접기' : `▼ 전체 보기 (${signals.length}건)`}
        </button>
      )}
    </div>
  )
}

// ── TickerConvImports (종목별 탐색 기록) ──────────────────────────────────────

const CONV_TYPE_LABEL: Record<string, string> = {
  discovery:        '종목 탐색',
  thesis_challenge: '반대 논거',
  portfolio_review: '포트폴리오',
  deep_analysis:    '심층 분석',
}
const CONV_TYPE_COLOR: Record<string, string> = {
  discovery:        'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  thesis_challenge: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  portfolio_review: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  deep_analysis:    'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
}

function TickerConvImports({
  items,
  loaded,
  onRefresh,
  onDelete,
}: {
  items: ConversationImport[]
  loaded: boolean
  onRefresh: () => void
  onDelete: (id: string) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  function toggleItem(id: string) {
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <div className="mt-3 border-t border-gray-200 dark:border-gray-700 pt-3">
      <div className="flex items-center gap-2">
        <button
          onClick={() => setExpanded(v => !v)}
          className="flex items-center gap-2 flex-1 text-left"
        >
          <Globe size={12} className="text-gray-400 dark:text-gray-500 flex-shrink-0" />
          <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
            이 종목 탐색 기록
          </span>
          {!loaded
            ? <Loader2 size={11} className="animate-spin text-gray-400" />
            : items.length > 0
            ? <span className="text-xs bg-blue-100 text-blue-700 dark:bg-blue-900/60 dark:text-blue-300 px-1.5 py-0 rounded-full leading-5 font-medium">{items.length}</span>
            : <span className="text-xs text-gray-400 dark:text-gray-600">없음</span>
          }
          {loaded && items.length > 0 && (
            expanded
              ? <ChevronUp size={13} className="text-gray-400 dark:text-gray-500" />
              : <ChevronDown size={13} className="text-gray-400 dark:text-gray-500" />
          )}
        </button>
        <button
          onClick={onRefresh}
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors flex-shrink-0"
          title="새로고침"
        >
          <RefreshCw size={11} />
        </button>
      </div>

      {expanded && items.length > 0 && (
        <div className="mt-2 space-y-2">
          {items.map(item => {
            const isOpen = expandedIds.has(item.id)
            const typeColor = CONV_TYPE_COLOR[item.import_type] ?? 'bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300'
            const typeLabel = CONV_TYPE_LABEL[item.import_type] ?? item.import_type
            return (
              <div key={item.id} className="bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-lg p-3">
                <div className="flex items-start gap-2">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded flex-shrink-0 ${typeColor}`}>
                    {typeLabel}
                  </span>
                  <p className="text-xs text-gray-700 dark:text-gray-200 leading-relaxed flex-1">
                    {item.summary}
                  </p>
                  <button
                    onClick={() => onDelete(item.id)}
                    className="text-gray-300 dark:text-gray-700 hover:text-red-400 transition-colors flex-shrink-0"
                  >
                    <X size={12} />
                  </button>
                </div>
                <div className="flex items-center gap-2 mt-1.5">
                  <span className="text-xs text-gray-400 dark:text-gray-600">{fmtKST(item.created_at)}</span>
                  {item.raw_excerpt && (
                    <button
                      onClick={() => toggleItem(item.id)}
                      className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 flex items-center gap-0.5"
                    >
                      {isOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                      원문
                    </button>
                  )}
                </div>
                {isOpen && item.raw_excerpt && (
                  <div className="mt-2 bg-gray-50 dark:bg-gray-900 rounded px-2 py-2">
                    <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed whitespace-pre-wrap font-mono">{item.raw_excerpt}</p>
                  </div>
                )}
              </div>
            )
          })}
          <p className="text-xs text-gray-400 dark:text-gray-600 text-center pt-1">
            Journal → 탐색결과 탭에서 이 종목으로 기록된 항목이 표시됩니다.
          </p>
        </div>
      )}

      {loaded && items.length === 0 && (
        <p className="mt-1.5 text-xs text-gray-400 dark:text-gray-600">
          Journal → 탐색결과 탭에서 이 종목을 선택하여 기록하세요.
        </p>
      )}
    </div>
  )
}

function MonitoringContractCard({
  thesis,
  onSave,
}: {
  thesis: Thesis | null
  onSave: (contract: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(thesis?.monitoring_contract ?? '')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!editing) setText(thesis?.monitoring_contract ?? '')
  }, [thesis?.monitoring_contract, editing])

  const isConfirmed = thesis?.confirmed === 'confirmed'
  const hasContract = !!(thesis?.monitoring_contract?.trim())

  async function save() {
    if (!text.trim()) return
    setSaving(true)
    try {
      await onSave(text.trim())
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`border rounded-xl p-4 space-y-2 ${
      hasContract
        ? 'bg-gray-50 dark:bg-gray-900 border-gray-200 dark:border-gray-800'
        : 'bg-amber-900/10 border-amber-700/50'
    }`}>
      <div className="flex items-center gap-2">
        <Bell size={14} className={hasContract ? 'text-emerald-500' : 'text-amber-500'} />
        <span className="text-sm font-medium text-gray-900 dark:text-white">Monitoring Contract</span>
        <span className="text-xs text-gray-400 dark:text-gray-500">Break Monitor 기준</span>
        {!hasContract && (
          <span className="text-xs text-amber-600 dark:text-amber-400 font-medium">
            Confirm 전 필수
          </span>
        )}
        {hasContract && !isConfirmed && !editing && (
          <button
            onClick={() => { setText(thesis?.monitoring_contract ?? ''); setEditing(true) }}
            className="ml-auto text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
          >
            수정
          </button>
        )}
      </div>

      {!editing && hasContract ? (
        <div className="text-sm text-gray-700 dark:text-gray-200 leading-relaxed whitespace-pre-wrap border-l-2 border-emerald-500 pl-3">
          {thesis!.monitoring_contract}
        </div>
      ) : !editing ? (
        <button
          onClick={() => { setText(''); setEditing(true) }}
          className="text-sm text-amber-600 dark:text-amber-400 hover:text-amber-500 transition-colors text-left"
        >
          외부 Claude에서 뽑은 Core Logic / Break Conditions / Watch Metrics를 붙여넣으세요.
        </button>
      ) : null}

      {editing && (
        <div className="space-y-2">
          <textarea
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save() }}
            placeholder={'## Core Logic\n...\n\n## Break Conditions\n- ...\n\n## Strengthening Signals\n- ...\n\n## Watch Metrics\n- ...'}
            rows={8}
            autoFocus
            disabled={saving}
            className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-400 dark:border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-emerald-600 disabled:opacity-50"
          />
          <p className="text-xs text-gray-400 dark:text-gray-500">⌘Enter 저장 · Break Monitor는 이 계약서를 기준으로 관찰합니다.</p>
          <div className="flex gap-2">
            <button
              onClick={save}
              disabled={saving || !text.trim()}
              className="flex items-center gap-1.5 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
            >
              {saving ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle size={12} />}
              저장
            </button>
            <button
              onClick={() => { setEditing(false); setText(thesis?.monitoring_contract ?? '') }}
              className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            >
              취소
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Ticker Reports Tab ────────────────────────────────────────────────────────

type TickerReport = { id: string; type: string; content: string; created_at: string }

const REPORT_SECTIONS: Record<string, { key: string; label: string }[]> = {
  analysis: [
    { key: 'business_overview', label: '1. 기업 개요' },
    { key: 'competitive_position', label: '2. 경쟁 구도' },
    { key: 'financial_analysis', label: '3. 재무 심층 분석' },
    { key: 'management_track_record', label: '4. 경영진 의사결정 이력' },
    { key: 'valuation', label: '5. 밸류에이션' },
    { key: 'risk_matrix', label: '6. 리스크 매트릭스' },
    { key: 'recent_developments', label: '7. 최근 동향' },
    { key: 'bull_bear_synthesis', label: '8. 강세/약세 종합' },
  ],
}

function extractSection(content: string, key: string) {
  const m = content.match(new RegExp(`<section name="${key}">(.*?)</section>`, 's'))
  return m ? m[1].trim() : ''
}

function ReportAccordion({ report }: { report: TickerReport }) {
  const sections = REPORT_SECTIONS[report.type]
  const hasSections = sections?.some(({ key }) => extractSection(report.content, key))
  const [open, setOpen] = useState<Set<string>>(new Set(['business_overview', 'bull_bear_synthesis']))

  if (!sections || !hasSections) {
    return <Markdown content={report.content} />
  }
  return (
    <div className="space-y-2">
      {sections.map(({ key, label }) => {
        const text = extractSection(report.content, key)
        if (!text) return null
        const isOpen = open.has(key)
        return (
          <div key={key} className="border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => setOpen(prev => { const s = new Set(prev); isOpen ? s.delete(key) : s.add(key); return s })}
              className="w-full flex items-center justify-between px-4 py-3 text-left bg-gray-100 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-750 transition-colors"
            >
              <span className="text-gray-900 dark:text-white text-sm font-medium">{label}</span>
              {isOpen ? <ChevronUp size={14} className="text-gray-500 dark:text-gray-400 flex-shrink-0" /> : <ChevronDown size={14} className="text-gray-500 dark:text-gray-400 flex-shrink-0" />}
            </button>
            {isOpen && (
              <div className="px-4 py-4 bg-gray-50 dark:bg-gray-900 border-t border-gray-300 dark:border-gray-700">
                <Markdown content={text} />
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

  if (loading) return <div className="flex items-center justify-center py-20 text-gray-400 dark:text-gray-500 gap-2"><Loader2 size={16} className="animate-spin" /> 불러오는 중...</div>

  if (reports.length === 0) return (
    <div className="text-center py-20 text-gray-500 dark:text-gray-600">
      <FileText size={40} className="mx-auto mb-3 text-gray-700" />
      <p className="text-gray-400 dark:text-gray-500">아직 생성된 보고서가 없습니다.</p>
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
                  ? 'bg-gray-200 dark:bg-gray-700 border-gray-400 dark:border-gray-500 text-gray-900 dark:text-white'
                  : 'bg-gray-50 dark:bg-gray-900 border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400 dark:hover:border-gray-600'
              }`}
            >
              <span className="block font-medium">{fmtKST(r.created_at, 'date')}</span>
              <span className="text-gray-400 dark:text-gray-500">{fmtKST(r.created_at, 'time')}</span>
              {isLatest && <span className="ml-1 text-emerald-600 dark:text-emerald-400">●</span>}
            </button>
          )
        })}
      </div>

      {/* 선택된 보고서 본문 */}
      {selected && (
        <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
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
    <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-4 py-3 min-w-0">
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-1 truncate">{label}</p>
      <p className={`text-base font-semibold ${isNA ? 'text-gray-500 dark:text-gray-600' : 'text-gray-900 dark:text-white'}`}>{value}</p>
    </div>
  )
}

function DataSection({
  title, defaultOpen = false, children,
}: { title: string; defaultOpen?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors"
      >
        <span className="text-gray-900 dark:text-white font-medium text-sm">{title}</span>
        {open ? <ChevronUp size={15} className="text-gray-500 dark:text-gray-400 flex-shrink-0" /> : <ChevronDown size={15} className="text-gray-500 dark:text-gray-400 flex-shrink-0" />}
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-gray-200 dark:border-gray-800">
          <div className="pt-4">{children}</div>
        </div>
      )}
    </div>
  )
}

function PreText({ text }: { text: string }) {
  return (
    <pre className="text-gray-600 dark:text-gray-300 text-xs font-mono leading-relaxed whitespace-pre-wrap break-words">
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
    <div className="border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden mb-2 last:mb-0">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-blue-600 dark:text-blue-400 bg-blue-900/30 px-2 py-0.5 rounded">
            {s.filing_type}
          </span>
          <span className="text-sm text-gray-700 dark:text-gray-200">{s.report_period}</span>
          <span className="text-xs text-gray-400 dark:text-gray-500">
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
              className="text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
            >
              <ExternalLink size={13} />
            </a>
          )}
          {open ? <ChevronUp size={14} className="text-gray-500 dark:text-gray-400" /> : <ChevronDown size={14} className="text-gray-500 dark:text-gray-400" />}
        </div>
      </button>
      {open && (
        <div className="border-t border-gray-300 dark:border-gray-700 divide-y divide-gray-700/50">
          {subsections.map(({ label, text }) => text ? (
            <div key={label} className="px-4 py-3">
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">{label}</p>
              <Markdown content={text} />
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
      <div className="text-center py-20 text-gray-500 dark:text-gray-600">
        <Database size={40} className="mx-auto mb-3 text-gray-700" />
        <p className="text-gray-400 dark:text-gray-500">재무 데이터가 없습니다.</p>
        <p className="text-sm mt-1">헤더의 "데이터 수집" 버튼으로 먼저 수집하세요.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-gray-400 dark:text-gray-500 gap-2">
        <Loader2 size={16} className="animate-spin" /> 불러오는 중...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="py-10 text-center text-red-600 dark:text-red-400 text-sm">
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
        <p className="text-xs text-gray-500 dark:text-gray-600 text-right">
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

// ── VersionCard ───────────────────────────────────────────────────────────────

const VERSION_FIELDS = [
  { key: 'thesis', label: '투자 논거' },
  { key: 'risk', label: '리스크' },
  { key: 'key_assumptions', label: '핵심 가정' },
  { key: 'valuation', label: '밸류에이션' },
  { key: 'monitoring_contract', label: 'Monitoring Contract' },
] as const

function VersionCard({
  v, isActive, onDelete,
}: {
  v: Thesis
  isActive: boolean
  onDelete: (id: string) => void
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (key: string) =>
    setExpanded(prev => { const s = new Set(prev); s.has(key) ? s.delete(key) : s.add(key); return s })

  const statusC: Record<string, string> = {
    draft: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
    confirmed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    needs_review: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
    retired: 'bg-gray-200 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
  }
  const statusL: Record<string, string> = {
    draft: 'Draft', confirmed: 'Confirmed', needs_review: '재검토', retired: '아카이브',
  }

  return (
    <div className={`bg-gray-50 dark:bg-gray-900 border rounded-xl p-5 space-y-3 ${
      isActive ? 'border-violet-500 ring-1 ring-violet-500/30' : 'border-gray-200 dark:border-gray-800'
    }`}>
      {/* 헤더 */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-bold text-gray-900 dark:text-white">v{v.version_number}</span>
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${statusC[v.confirmed] ?? ''}`}>
          {statusL[v.confirmed] ?? v.confirmed}
        </span>
        {isActive && (
          <span className="text-xs bg-violet-100 text-violet-700 dark:bg-violet-900/60 dark:text-violet-300 px-1.5 py-0.5 rounded font-medium">현재</span>
        )}
        {v.stock_type && (
          <span className="text-xs text-gray-400 dark:text-gray-500 bg-gray-200 dark:bg-gray-800 px-1.5 py-0.5 rounded">{v.stock_type}</span>
        )}
        <span className="ml-auto text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1">
          <Clock size={11} />
          {v.confirmed_at ? fmtKST(v.confirmed_at) : (v.last_analyzed_at ? fmtKST(v.last_analyzed_at) : '-')}
        </span>
      </div>

      {/* 필드 목록 */}
      {VERSION_FIELDS.map(({ key, label }) => {
        const content = v[key as keyof Thesis] as string | null | undefined
        if (!content) return null
        const open = expanded.has(key)
        return (
          <div key={key} className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
            <button
              onClick={() => toggle(key)}
              className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors"
            >
              <span className="text-xs font-medium text-gray-600 dark:text-gray-300">{label}</span>
              {open ? <ChevronUp size={13} className="text-gray-400" /> : <ChevronDown size={13} className="text-gray-400" />}
            </button>
            {open && (
              <div className="px-4 pb-4 pt-1 border-t border-gray-200 dark:border-gray-700">
                <p className="text-sm text-gray-700 dark:text-gray-200 whitespace-pre-wrap leading-relaxed">{content}</p>
              </div>
            )}
          </div>
        )
      })}

      {v.retired_at && v.retirement_reason && (
        <p className="text-xs text-gray-400 dark:text-gray-500">
          아카이브 사유: {v.retirement_reason} · {fmtKST(v.retired_at)}
        </p>
      )}

      {!isActive && (
        <div className="flex justify-end">
          <button
            onClick={() => onDelete(v.id)}
            className="flex items-center gap-1 text-xs text-gray-400 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400 transition-colors"
          >
            <Trash2 size={12} /> 버전 삭제
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ThesisPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { fontSize } = useTheme()

  const [ticker, setTicker] = useState<Ticker | null>(null)
  const [thesis, setThesis] = useState<Thesis | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showDirectModal, setShowDirectModal] = useState(false)
  const [directFields, setDirectFields] = useState({
    stock_type: 'compounding',
    thesis: '',
    risk: '',
    key_assumptions: '',
    valuation: '',
    monitoring_contract: '',
  })
  const [directSaving, setDirectSaving] = useState(false)
  const [directError, setDirectError] = useState('')
  const [pasteText, setPasteText] = useState('')

  // Monitoring Contract confirm flow
  const [showConfirmModal, setShowConfirmModal] = useState(false)
  const [confirmMonitoringContract, setConfirmMonitoringContract] = useState('')

  // version history
  const [versions, setVersions] = useState<Thesis[]>([])
  const [versionsLoading, setVersionsLoading] = useState(false)
  const [versionsLoaded, setVersionsLoaded] = useState(false)

  // 종목별 탐색 기록
  const [convImports, setConvImports] = useState<ConversationImport[]>([])
  const [convLoaded, setConvLoaded] = useState(false)

  // Break Signals
  const [breakSignals, setBreakSignals] = useState<BreakSignal[]>([])
  const [breakSignalsLoaded, setBreakSignalsLoaded] = useState(false)

  // Open cycle
  const [openCycle, setOpenCycle] = useState<InvestmentCycle | null>(null)
  const [openSections, setOpenSections] = useState<Set<ThesisSectionKey>>(new Set(['thesis']))
  const [reporting, setReporting] = useState(false)
  const [reportMsg, setReportMsg] = useState('')
  const [monitoring, setMonitoring] = useState(false)
  const [dataStatus, setDataStatus] = useState<DataStatus | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [valleyUrl, setValleyUrl] = useState<string | null>(null)
  const [resolvingValley, setResolvingValley] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const [activeTab, setActiveTab] = useState<ActiveTab>('thesis')

  useEffect(() => {
    if (activeTab === 'versions' && !versionsLoaded) loadVersionHistory()
  }, [activeTab])

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
        setValleyUrl(t?.valley_url ?? null)
        // 탐색 기록 + Break Signals + Open Cycle 백그라운드 로드
        if (id) {
          loadConvImports(id)
          loadBreakSignals(id)
          fetch(`/api/cycles?ticker_id=${id}&status=open&limit=1`)
            .then(r => r.ok ? r.json() : [])
            .then((list: InvestmentCycle[]) => setOpenCycle(list[0] ?? null))
            .catch(() => null)
        }
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

  function parsePasteText(text: string) {
    const tags = ['THESIS', 'RISK', 'KEY_ASSUMPTIONS', 'VALUATION', 'MONITORING_CONTRACT'] as const
    const map: Record<string, string> = {}
    for (let i = 0; i < tags.length; i++) {
      const tag = tags[i]
      const start = text.indexOf(`[${tag}]`)
      if (start === -1) continue
      const contentStart = start + tag.length + 2
      const next = tags.slice(i + 1).map(t => text.indexOf(`[${t}]`)).find(p => p > start) ?? text.length
      map[tag.toLowerCase()] = text.slice(contentStart, next).trim()
    }
    if (Object.keys(map).length > 0) {
      setDirectFields(f => ({
        ...f,
        ...(map['thesis'] && { thesis: map['thesis'] }),
        ...(map['risk'] && { risk: map['risk'] }),
        ...(map['key_assumptions'] && { key_assumptions: map['key_assumptions'] }),
        ...(map['valuation'] && { valuation: map['valuation'] }),
        ...(map['monitoring_contract'] && { monitoring_contract: map['monitoring_contract'] }),
      }))
      setPasteText('')
    }
  }

  function openDirectModal() {
    setDirectFields({
      stock_type: thesis?.stock_type ?? 'compounding',
      thesis: thesis?.confirmed !== 'confirmed' ? (thesis?.thesis ?? '') : '',
      risk: thesis?.confirmed !== 'confirmed' ? (thesis?.risk ?? '') : '',
      key_assumptions: thesis?.confirmed !== 'confirmed' ? (thesis?.key_assumptions ?? '') : '',
      valuation: thesis?.confirmed !== 'confirmed' ? (thesis?.valuation ?? '') : '',
      monitoring_contract: thesis?.confirmed !== 'confirmed' ? (thesis?.monitoring_contract ?? '') : '',
    })
    setDirectError('')
    setPasteText('')
    setShowDirectModal(true)
  }

  async function handleDirectSave() {
    if (!id) return
    setDirectSaving(true)
    setDirectError('')
    try {
      await api.createThesisDirect(id, directFields)
      const updated = await api.getThesis(id)
      setThesis(updated)
      setOpenSections(new Set(THESIS_SECTIONS.map((s) => s.key)))
      setShowDirectModal(false)
      setActiveTab('thesis')
    } catch (e) {
      setDirectError(e instanceof Error ? e.message : '저장 실패')
    } finally {
      setDirectSaving(false)
    }
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

  async function handleResolveValley() {
    if (!id) return
    setResolvingValley(true)
    setReportMsg('Valley 링크 조회 중... (10-30초 소요)')
    try {
      await api.resolveValley(id)
      // poll for result
      let elapsed = 0
      const poll = setInterval(async () => {
        elapsed += 3000
        const list = await api.getTickers().catch(() => null)
        const updated = list?.find((t) => t.id === id)
        if (updated?.valley_url) {
          setValleyUrl(updated.valley_url)
          setReportMsg('')
          clearInterval(poll)
          setResolvingValley(false)
          return
        }
        if (elapsed >= 60000) {
          clearInterval(poll)
          setResolvingValley(false)
          setReportMsg('Valley 링크 조회 실패. Valley 계정 정보(VALLEY_EMAIL/PASSWORD)를 확인하세요.')
        }
      }, 3000)
    } catch (e) {
      setReportMsg(e instanceof Error ? e.message : 'Valley 조회 실패')
      setResolvingValley(false)
    }
  }

  async function handleDelete() {
    if (!id) return
    setDeleting(true)
    try {
      await api.deleteTicker(id)
      navigate('/')
    } catch (e) {
      alert(e instanceof Error ? e.message : '삭제 실패')
      setDeleting(false)
      setShowDeleteConfirm(false)
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

  function openConfirmModal() {
    if (!id) return
    setConfirmMonitoringContract(thesis?.monitoring_contract ?? '')
    setShowConfirmModal(true)
  }

  async function handleConfirm() {
    if (!id) return
    if (!thesis?.monitoring_contract && !confirmMonitoringContract.trim()) {
      openConfirmModal()
      return
    }
    try {
      const updated = await api.confirmThesis(
        id,
        confirmMonitoringContract.trim() || undefined,
      )
      setThesis(updated)
      setShowConfirmModal(false)
      setVersionsLoaded(false) // version history 캐시 무효화
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '오류 발생')
    }
  }

  async function handleDeleteThesisVersion(thesisId: string) {
    const msg = thesis?.confirmed === 'confirmed'
      ? '이 confirmed thesis 버전을 삭제할까요? 다른 버전이 없으면 삭제 불가합니다.'
      : 'Thesis 초안을 삭제할까요? 이 작업은 되돌릴 수 없습니다.'
    if (!confirm(msg)) return
    const res = await fetch(`/api/thesis/versions/${thesisId}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) {
      if (!id) return
      const [updated, allVersions] = await Promise.all([
        api.getThesis(id).catch(() => null),
        api.getThesisVersions(id).catch(() => []),
      ])
      setThesis(updated)
      setVersions(allVersions)
    } else {
      const err = await res.json().catch(() => ({ detail: '삭제 실패' }))
      alert(err.detail || '삭제 실패')
    }
  }

  async function handleCreateNewVersion() {
    if (!id) return
    try {
      const newVersion = await api.createNewVersion(id)
      setThesis(newVersion)
      setVersionsLoaded(false)
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : '오류 발생')
    }
  }

  function buildSignalFeedback(signal: BreakSignal) {
    const parts = [
      '아래 Break Monitor 관찰 결과를 반영해서 thesis/risk/key_assumptions/Monitoring Contract를 보완해줘.',
      '',
      '## Observations',
      signal.observations,
    ]
    if (signal.positive_signals) parts.push('', '## Thesis 강화 신호', signal.positive_signals)
    if (signal.negative_signals) parts.push('', '## Thesis 약화 신호', signal.negative_signals)
    if (signal.watch_items) parts.push('', '## 다음 확인 항목', signal.watch_items)
    if (signal.verdict) parts.push('', '## 사람 판정', signal.verdict)
    if (signal.human_note) parts.push('', '## 사람 메모', signal.human_note)
    parts.push(
      '',
      '요청:',
      '- 기존 thesis가 유지되는 부분과 수정해야 하는 부분을 구분해줘.',
      '- Strengthening Signals와 Break Conditions를 Monitoring Contract에 반영해줘.',
      '- 매수/매도 지시는 하지 말고, 사람이 확인할 추가 질문을 남겨줘.',
    )
    return parts.join('\n')
  }

  async function handleCreateVersionFromSignal(signal: BreakSignal) {
    try {
      const res = await fetch(`/api/break-signals/${signal.id}/thesis-version`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '새 버전 생성 실패' }))
        throw new Error(err.detail || '새 버전 생성 실패')
      }
      const newVersion: Thesis = await res.json()
      setThesis(newVersion)
      setVersionsLoaded(false)
      setActiveTab('thesis')
      setOpenSections(new Set(THESIS_SECTIONS.map((s) => s.key)))
      setReportMsg('Break Monitor 신호를 반영할 새 draft 버전을 만들었습니다. "Thesis 작성" 버튼으로 내용을 수정하세요.')
    } catch (e) {
      alert(e instanceof Error ? e.message : '새 버전 생성 실패')
    }
  }

  async function loadBreakSignals(tickerId: string) {
    setBreakSignalsLoaded(false)
    try {
      const res = await fetch(`/api/break-signals?ticker_id=${tickerId}`)
      if (res.ok) setBreakSignals(await res.json())
    } catch { /* ignore */ } finally {
      setBreakSignalsLoaded(true)
    }
  }

  async function loadConvImports(tickerId: string) {
    setConvLoaded(false)
    try {
      const res = await fetch(`/api/conversations?ticker_id=${tickerId}`)
      if (res.ok) setConvImports(await res.json())
    } catch { /* ignore */ } finally {
      setConvLoaded(true)
    }
  }

  async function loadVersionHistory() {
    if (!id || versionsLoaded) return
    setVersionsLoading(true)
    try {
      const data = await api.getThesisVersions(id)
      setVersions(data)
      setVersionsLoaded(true)
    } catch {
      // ignore
    } finally {
      setVersionsLoading(false)
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

  const statusColor: Record<string, string> = {
    draft: 'text-yellow-600 dark:text-yellow-400',
    confirmed: 'text-emerald-600 dark:text-emerald-400',
    needs_review: 'text-red-600 dark:text-red-400',
    retired: 'text-gray-500 dark:text-gray-500',
  }
  const statusLabel: Record<string, string> = {
    draft: '초안 (Draft)',
    confirmed: '확정됨 (Confirmed)',
    needs_review: '재검토 필요',
    retired: '아카이브됨',
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400 dark:text-gray-500">
        불러오는 중...
      </div>
    )
  }

  if (error || !ticker) {
    return (
      <div className="min-h-screen flex items-center justify-center text-red-600 dark:text-red-400">
        {error || '종목을 찾을 수 없습니다.'}
      </div>
    )
  }

  const hasContent = thesis?.thesis || thesis?.risk || thesis?.key_assumptions || thesis?.valuation

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-200 dark:border-gray-800 px-3 py-3 sm:px-6 sm:py-4">
        <div className="max-w-4xl mx-auto flex items-start sm:items-center justify-between gap-2">
          <div className="flex items-center gap-3 flex-shrink-0">
            <button onClick={() => navigate('/')} className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
              <ArrowLeft size={20} />
            </button>
            <div>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="text-gray-900 dark:text-white text-lg sm:text-xl font-bold">{ticker.name}</span>
                {thesis && (
                  <span className={`text-xs sm:text-sm font-medium ${statusColor[thesis.confirmed] ?? 'text-gray-500'}`}>
                    {statusLabel[thesis.confirmed] ?? thesis.confirmed}
                  </span>
                )}
                {thesis && thesis.version_number > 1 && (
                  <span className="text-xs font-medium px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 dark:bg-violet-900/60 dark:text-violet-300">
                    v{thesis.version_number}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">{ticker.symbol}</span>
                <span className="text-xs text-gray-500 dark:text-gray-600">·</span>
                <span className="text-xs text-gray-400 dark:text-gray-500">
                  {ticker.market === 'US_Stock' ? 'US' : 'KR'}
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 sm:gap-2 flex-wrap justify-end">
            <ThemeControls />
            {valleyUrl ? (
              <a
                href={valleyUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
                title="Valley AI에서 보기"
              >
                <ExternalLink size={14} /> Valley
              </a>
            ) : (
              <button
                onClick={handleResolveValley}
                disabled={resolvingValley}
                title="Valley.town 링크 조회"
                className="flex items-center gap-1.5 bg-gray-200 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 disabled:opacity-50 text-gray-900 dark:text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
              >
                {resolvingValley
                  ? <Loader2 size={14} className="animate-spin" />
                  : <Link size={14} />
                }
                <span className="hidden sm:inline">Valley 링크</span>
              </button>
            )}
            <button
              onClick={() => setShowDeleteConfirm(true)}
              title="종목 삭제"
              className="flex items-center gap-1.5 text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 text-xs sm:text-sm font-medium px-2 py-1.5 rounded-lg transition-colors"
            >
              <Trash2 size={14} />
              <span className="hidden sm:inline">삭제</span>
            </button>
            {thesis?.confirmed === 'confirmed' && (
              <button
                onClick={handleCreateNewVersion}
                title="현재 confirmed thesis를 복사하여 새 draft 버전 생성"
                className="flex items-center gap-1.5 bg-gray-200 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-900 dark:text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
              >
                <GitBranch size={14} /> <span className="hidden sm:inline">새 버전</span>
              </button>
            )}
            {(thesis?.confirmed === 'draft' || thesis?.confirmed === 'needs_review') && hasContent && (
              <>
                <button
                  onClick={() => handleDeleteThesisVersion(thesis.id)}
                  title="이 thesis 초안 삭제"
                  className="flex items-center gap-1 text-gray-400 dark:text-gray-500 hover:text-red-500 dark:hover:text-red-400 text-xs px-1.5 py-1.5 rounded-lg transition-colors"
                >
                  <Trash2 size={13} />
                  <span className="hidden sm:inline text-xs">초기화</span>
                </button>
                <button
                  onClick={handleConfirm}
                  className={`flex items-center gap-1.5 text-gray-900 dark:text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors ${
                    thesis.confirmed === 'needs_review'
                      ? 'bg-orange-700 hover:bg-orange-600'
                      : 'bg-emerald-700 hover:bg-emerald-600'
                  }`}
                >
                  <CheckCircle size={14} />
                  {thesis.confirmed === 'needs_review' ? '재확인' : 'Confirm'}
                </button>
              </>
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
              className={`flex items-center gap-1.5 text-gray-900 dark:text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors disabled:opacity-50 ${
                dataStatus?.has_data
                  ? 'bg-gray-200 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600'
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
              onClick={openDirectModal}
              className="flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 text-white text-xs sm:text-sm font-medium px-2.5 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
            >
              <PenLine size={14} /> Thesis 작성
            </button>
          </div>
        </div>
      </header>

      {/* Tab bar */}
      <div className="border-b border-gray-200 dark:border-gray-800 px-3 sm:px-6">
        <div className="max-w-4xl mx-auto flex gap-1">
          {([
            { id: 'thesis', label: 'Thesis', icon: <Sparkles size={14} /> },
            { id: 'data', label: '재무 데이터', icon: <BarChart2 size={14} /> },
            { id: 'reports', label: '보고서', icon: <FileText size={14} /> },
            { id: 'versions', label: '버전 히스토리', icon: <GitBranch size={14} /> },
          ] as const).map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px ${
                activeTab === tab.id
                  ? 'border-violet-500 text-violet-400'
                  : 'border-transparent text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300'
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

      <main className={`max-w-4xl mx-auto px-3 sm:px-6 py-4 sm:py-6 space-y-4 fs-${fontSize}`}>
        {/* ── Thesis Tab ── */}
        {activeTab === 'thesis' && (
          <>
            {/* 데이터 상태 배너 */}
            {dataStatus && (
              <div className={`rounded-lg px-4 py-3 text-sm flex items-center gap-3 ${
                dataStatus.has_data
                  ? 'bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400'
                  : 'bg-orange-900/20 border border-orange-800 text-orange-700 dark:text-orange-300'
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

            {/* 진행 중 사이클 배너 */}
            {openCycle && (
              <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg px-4 py-2.5 flex items-center gap-3 text-sm">
                <span className="text-blue-600 dark:text-blue-400 font-medium flex-shrink-0">📈 사이클 진행 중</span>
                <span className="text-blue-700 dark:text-blue-300 text-xs">
                  {fmtKST(openCycle.opened_at, 'date')} 시작
                  {' · '}
                  {Math.floor((Date.now() - new Date(openCycle.opened_at.endsWith('Z') ? openCycle.opened_at : openCycle.opened_at + 'Z').getTime()) / 86400000)}일째 보유
                  {openCycle.pnl_pct != null && (
                    <span className={openCycle.pnl_pct >= 0 ? ' text-emerald-600 dark:text-emerald-400' : ' text-red-600 dark:text-red-400'}>
                      {' · '}{openCycle.pnl_pct >= 0 ? '+' : ''}{openCycle.pnl_pct.toFixed(1)}%
                    </span>
                  )}
                </span>
              </div>
            )}

            {/* Report / error messages */}
            {reportMsg && (
              <div className="bg-blue-900/30 border border-blue-800 rounded-lg p-4 text-blue-700 dark:text-blue-300 text-sm flex items-center gap-2">
                <FileText size={16} /> {reportMsg}
              </div>
            )}
            {/* 외부 탐색 도구 */}
            {id && (
              <div className="bg-gray-50 dark:bg-gray-900/50 border border-gray-200 dark:border-gray-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Globe size={14} className="text-blue-400 flex-shrink-0" />
                  <span className="text-xs font-medium text-gray-600 dark:text-gray-300">외부 탐색 도구</span>
                  <span className="text-xs text-gray-400 dark:text-gray-500">— 결과는 Journal → 탐색결과 탭에 기록하세요</span>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <TickerPromptButton
                    tickerId={id}
                    promptType="deep_analysis"
                    label={<><Search size={12} /> 심층 분석 프롬프트</>}
                    title={`${ticker?.name ?? ''} 종목 집중 분석 프롬프트`}
                    className="bg-blue-900/20 border-blue-700/50 text-blue-600 dark:text-blue-300 hover:bg-blue-900/40"
                  />
                  <TickerPromptButton
                    tickerId={id}
                    promptType="monitoring_contract"
                    label={<><PenLine size={12} /> Thesis 완성 프롬프트</>}
                    title={`${ticker?.name ?? ''} 최종 Thesis 완성 (5개 필드 산출)`}
                    className="bg-emerald-900/20 border-emerald-700/50 text-emerald-600 dark:text-emerald-300 hover:bg-emerald-900/40"
                  />
                </div>
                {!hasContent && (
                  <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
                    심층 분석 프롬프트로 외부 대화 시작 → 논의 완료 후 Thesis 완성 프롬프트로 5개 필드 산출 → "Thesis 작성"으로 입력
                  </p>
                )}

                {/* 이 종목의 탐색 기록 — 항상 표시 */}
                <TickerConvImports
                  items={convImports}
                  loaded={convLoaded}
                  onRefresh={() => { if (id) loadConvImports(id) }}
                  onDelete={async (itemId) => {
                    await fetch(`/api/conversations/${itemId}`, { method: 'DELETE' })
                    setConvImports(prev => prev.filter(c => c.id !== itemId))
                  }}
                />
              </div>
            )}

            {/* No content yet */}
            {!hasContent && (
              <div className="text-center py-12 text-gray-500 dark:text-gray-600">
                <PenLine size={40} className="mx-auto mb-3 text-gray-800" />
                <p className="text-gray-400 dark:text-gray-500">아직 Thesis가 없습니다.</p>
                <p className="text-sm mt-1 text-gray-500 dark:text-gray-600">외부 Claude에서 분석 완료 후 "Thesis 작성" 버튼으로 결과를 입력하세요.</p>
              </div>
            )}

            {/* stock_type 배지 */}
            {hasContent && thesis?.stock_type && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400 dark:text-gray-500">투자 유형</span>
                <span className="px-2.5 py-1 bg-violet-900/50 border border-violet-700 text-violet-600 dark:text-violet-300 text-xs font-medium rounded-full">
                  {STOCK_TYPE_LABEL[thesis.stock_type] ?? thesis.stock_type}
                </span>
              </div>
            )}

            {/* Thesis sections */}
            {hasContent && THESIS_SECTIONS.map(({ key, label }) => {
              const content = thesis?.[key as keyof Thesis] as string | null | undefined
              if (!content) return null
              const isOpen = openSections.has(key)
              return (
                <div key={key} className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden">
                  <button
                    onClick={() => toggleSection(key)}
                    className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-gray-100 dark:hover:bg-gray-800/50 transition-colors"
                  >
                    <span className="text-gray-900 dark:text-white font-medium">{label}</span>
                    {isOpen ? <ChevronUp size={16} className="text-gray-500 dark:text-gray-400" /> : <ChevronDown size={16} className="text-gray-500 dark:text-gray-400" />}
                  </button>
                  {isOpen && (
                    <div className="px-5 pb-5 border-t border-gray-200 dark:border-gray-800">
                      <div className="pt-4">
                        <Markdown content={content} />
                      </div>
                    </div>
                  )}
                </div>
              )
            })}

            {/* Monitoring Contract */}
            {hasContent && (
              <MonitoringContractCard
                thesis={thesis}
                onSave={async (contract) => {
                  if (!id) return
                  const updated = await api.patchThesis(id, { monitoring_contract: contract })
                  setThesis(updated)
                }}
              />
            )}

            {thesis?.last_analyzed_at && (
              <p className="text-xs text-gray-500 dark:text-gray-600 text-right">
                마지막 분석: {fmtKST(thesis.last_analyzed_at)}
              </p>
            )}

            {/* Break Signal 섹션 — confirmed thesis에서만 표시 */}
            {thesis?.confirmed === 'confirmed' && id && (
              <BreakSignalSection
                signals={breakSignals}
                loaded={breakSignalsLoaded}
                onRefresh={() => loadBreakSignals(id)}
                onCreateRevision={handleCreateVersionFromSignal}
                onVerdictSet={async (signalId, verdict, note) => {
                  const res = await fetch(`/api/break-signals/${signalId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ verdict, human_note: note || null }),
                  })
                  if (res.ok) {
                    const updated: BreakSignal = await res.json()
                    setBreakSignals(prev => prev.map(s => s.id === signalId ? updated : s))
                  }
                }}
              />
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

        {/* ── 버전 히스토리 탭 ── */}
        {activeTab === 'versions' && (
          <div className="space-y-3">
            {versionsLoading && (
              <div className="flex items-center justify-center py-12 text-gray-400 gap-2">
                <Loader2 size={16} className="animate-spin" /> 불러오는 중...
              </div>
            )}
            {!versionsLoading && versions.length === 0 && (
              <div className="text-center py-16 text-gray-500 dark:text-gray-600">
                <GitBranch size={40} className="mx-auto mb-3 text-gray-700" />
                <p>버전 기록이 없습니다.</p>
              </div>
            )}
            {versions.map((v) => (
              <VersionCard
                key={v.id}
                v={v}
                isActive={v.id === thesis?.id}
                onDelete={handleDeleteThesisVersion}
              />
            ))}
          </div>
        )}
      </main>

      {/* 삭제 확인 모달 */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
          <div className="bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-2xl w-full max-w-sm p-6 space-y-4">
            <h2 className="text-gray-900 dark:text-white font-semibold text-base flex items-center gap-2">
              <Trash2 size={16} className="text-red-500" /> 종목 삭제
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-300">
              <span className="font-medium text-gray-900 dark:text-white">{ticker?.name}</span>
              {ticker && <span className="text-gray-400 dark:text-gray-500"> ({ticker.symbol})</span>}을 삭제합니다.
            </p>
            <p className="text-xs text-red-600 dark:text-red-400">
              Thesis, 보고서, 재무 데이터가 모두 삭제됩니다. 이 작업은 되돌릴 수 없습니다.
            </p>
            <div className="flex gap-3 justify-end pt-1">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={deleting}
                className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors disabled:opacity-50"
              >
                취소
              </button>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="flex items-center gap-2 bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                삭제
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Monitoring Contract Confirm 모달 */}
      {showConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
          <div className="bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-2xl w-full max-w-2xl p-6 space-y-4 max-h-[90vh] overflow-y-auto">
            <div>
              <h2 className="text-gray-900 dark:text-white font-semibold text-base flex items-center gap-2">
                <Bell size={16} className="text-emerald-400" /> Monitoring Contract 입력 후 Confirm
              </h2>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Confirm 전 Break Monitor가 감시할 계약서를 확정하세요.
              </p>
            </div>

            <div className="space-y-2">
              <label className="text-sm text-gray-600 dark:text-gray-300 font-medium">
                Monitoring Contract <span className="text-gray-400 dark:text-gray-500 font-normal">(Break Monitor 기준)</span>
              </label>
              <textarea
                value={confirmMonitoringContract}
                onChange={e => setConfirmMonitoringContract(e.target.value)}
                placeholder={'## Core Logic\n...\n\n## Break Conditions\n- ...\n\n## Strengthening Signals\n- ...\n\n## Watch Metrics\n- ...'}
                rows={10}
                autoFocus
                className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-emerald-600"
              />
              <p className="text-xs text-gray-400 dark:text-gray-500">
                Core Logic, Break Conditions, Strengthening Signals, Watch Metrics를 포함하세요.
              </p>
            </div>

            <div className="flex gap-3 justify-end pt-1">
              <button
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-200 transition-colors"
              >
                취소
              </button>
              <button
                onClick={handleConfirm}
                disabled={!confirmMonitoringContract.trim()}
                className="flex items-center gap-2 bg-emerald-700 hover:bg-emerald-600 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors"
              >
                <CheckCircle size={14} /> Confirm
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 직접 입력 모달 */}
      {showDirectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
          <div className="bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-2xl w-full max-w-2xl p-6 space-y-5 max-h-[90vh] overflow-y-auto">
            <div>
              <h2 className="text-gray-900 dark:text-white font-semibold text-lg flex items-center gap-2">
                <PenLine size={18} className="text-violet-400" /> Thesis 직접 입력
              </h2>
              <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">
                외부 Claude 분석 결과를 그대로 붙여넣으세요.
              </p>
            </div>

            {/* 일괄 붙여넣기 */}
            <div className="space-y-2">
              <label className="text-sm text-gray-600 dark:text-gray-300 font-medium flex items-center gap-1.5">
                <Copy size={13} className="text-violet-400" /> 전체 붙여넣기
                <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">— [THESIS] [RISK] ... 형식 자동 파싱</span>
              </label>
              <div className="flex gap-2">
                <textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  placeholder={'외부 Claude 결과 전체를 여기에 붙여넣고 "채우기" 클릭\n\n[THESIS]\n...\n[RISK]\n...\n[KEY_ASSUMPTIONS]\n...\n[VALUATION]\n...\n[MONITORING_CONTRACT]\n...'}
                  rows={4}
                  className="flex-1 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-violet-600 font-mono"
                />
                <button
                  onClick={() => parsePasteText(pasteText)}
                  disabled={!pasteText.trim()}
                  className="self-end flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium px-3 py-2 rounded-lg transition-colors whitespace-nowrap"
                >
                  <Check size={14} /> 채우기
                </button>
              </div>
            </div>

            <div className="border-t border-gray-200 dark:border-gray-700" />

            {/* 투자 유형 */}
            <div className="space-y-2">
              <label className="text-sm text-gray-600 dark:text-gray-300 font-medium">투자 유형 (Stock Type)</label>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                {STOCK_TYPE_OPTIONS.map((opt) => {
                  const selected = directFields.stock_type === opt.value
                  return (
                    <button
                      key={opt.value}
                      onClick={() => setDirectFields((f) => ({ ...f, stock_type: opt.value }))}
                      className={`text-left px-3 py-2 rounded-lg border transition-colors ${
                        selected
                          ? 'bg-violet-900/40 border-violet-600'
                          : 'bg-gray-100 dark:bg-gray-800 border-gray-300 dark:border-gray-700 hover:border-gray-500'
                      }`}
                    >
                      <div className={`font-semibold text-sm ${selected ? 'text-violet-700 dark:text-violet-200' : 'text-gray-900 dark:text-white'}`}>
                        {opt.label}
                      </div>
                      <div className="text-xs text-gray-400 dark:text-gray-500">{opt.desc}</div>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* 6개 필드 */}
            {([
              { key: 'thesis', label: '투자 논거 (Thesis)', rows: 6, placeholder: '이 종목에 투자하는 핵심 논거를 서술하세요...' },
              { key: 'risk', label: '리스크 (Risk)', rows: 4, placeholder: '주요 리스크와 thesis가 틀릴 수 있는 시나리오...' },
              { key: 'key_assumptions', label: '핵심 가정 (Key Assumptions)', rows: 4, placeholder: '이 thesis가 성립하기 위한 측정 가능한 핵심 가정들...' },
              { key: 'valuation', label: '밸류에이션 (Valuation)', rows: 3, placeholder: '현재 가격이 내포하는 기대치와 Fair Value 추정...' },
            ] as const).map(({ key, label, rows, placeholder }) => (
              <div key={key} className="space-y-1.5">
                <label className="text-sm text-gray-600 dark:text-gray-300 font-medium">{label}</label>
                <textarea
                  value={directFields[key]}
                  onChange={(e) => setDirectFields((f) => ({ ...f, [key]: e.target.value }))}
                  placeholder={placeholder}
                  rows={rows}
                  className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-violet-600"
                />
              </div>
            ))}

            <div className="space-y-1.5">
              <label className="text-sm text-gray-600 dark:text-gray-300 font-medium flex items-center gap-1.5">
                <Bell size={14} className="text-emerald-400" /> Monitoring Contract
                <span className="text-xs text-gray-400 dark:text-gray-500 font-normal">(Break Monitor 기준)</span>
              </label>
              <textarea
                value={directFields.monitoring_contract}
                onChange={(e) => setDirectFields((f) => ({ ...f, monitoring_contract: e.target.value }))}
                placeholder={'## Core Logic\n...\n\n## Break Conditions\n- ...\n\n## Strengthening Signals\n- ...\n\n## Watch Metrics\n- ...'}
                rows={8}
                className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-3 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-emerald-600 font-mono"
              />
            </div>

            {directError && (
              <div className="flex items-center gap-2 text-red-600 dark:text-red-400 text-sm">
                <AlertTriangle size={14} /> {directError}
              </div>
            )}

            <div className="flex gap-3 justify-end pt-1">
              <button
                onClick={() => setShowDirectModal(false)}
                disabled={directSaving}
                className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-200 transition-colors disabled:opacity-50"
              >
                취소
              </button>
              <button
                onClick={handleDirectSave}
                disabled={directSaving}
                className="flex items-center gap-2 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition-colors"
              >
                {directSaving
                  ? <><Loader2 size={14} className="animate-spin" /> 저장 중...</>
                  : <><PenLine size={14} /> 저장</>
                }
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
