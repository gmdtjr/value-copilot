import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, Pencil, Check, X, Trash2, Loader2, Lightbulb, Plus, Tag, PenLine } from 'lucide-react'
import { fmtKST } from '../utils/date'
import { ThemeControls } from '../components/ThemeControls'
import type { Ticker } from '../types'

// ── TradeLog types & helpers ──────────────────────────────────────────────────

interface TradeLog {
  id: string
  ticker_id: string | null
  symbol: string
  name: string
  action: 'buy' | 'sell' | 'add' | 'reduce'
  quantity_before: number
  quantity_after: number
  avg_price_before: number
  avg_price_after: number
  note: string | null
  detected_at: string
  noted_at: string | null
}

const ACTION_LABEL: Record<string, string> = {
  buy: '신규매수', sell: '전량매도', add: '추가매수', reduce: '일부매도',
}
const ACTION_COLOR: Record<string, string> = {
  buy: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300',
  sell: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  add: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  reduce: 'bg-orange-100 text-orange-700 dark:bg-orange-900 dark:text-orange-300',
}
const ACTION_ICON: Record<string, string> = {
  buy: '🟢', sell: '🔴', add: '📈', reduce: '📉',
}

function qtyChange(log: TradeLog): string {
  const { action, quantity_before: b, quantity_after: a } = log
  if (action === 'buy') return `${a.toFixed(2)}주`
  if (action === 'sell') return `${b.toFixed(2)}주 전량`
  if (action === 'add') return `+${(a - b).toFixed(2)}주 (${b.toFixed(2)}→${a.toFixed(2)})`
  return `-${(b - a).toFixed(2)}주 (${b.toFixed(2)}→${a.toFixed(2)})`
}

function priceStr(log: TradeLog): string {
  if (log.action === 'buy' || log.action === 'sell') {
    const p = log.action === 'buy' ? log.avg_price_after : log.avg_price_before
    return p > 0 ? `@${p.toLocaleString()}` : ''
  }
  return log.avg_price_after > 0 ? `평균단가 ${log.avg_price_after.toLocaleString()}` : ''
}

function groupByDate<T extends { detected_at?: string; created_at?: string }>(
  items: T[],
  dateKey: 'detected_at' | 'created_at',
): { date: string; items: T[] }[] {
  const map: Record<string, T[]> = {}
  for (const item of items) {
    const raw = item[dateKey] as string
    // KST 날짜로 그룹핑
    const normalized = /[Z+\-]\d{2}:?\d{2}$/.test(raw) || raw.endsWith('Z') ? raw : raw + 'Z'
    const date = new Date(normalized).toLocaleDateString('ko-KR', { timeZone: 'Asia/Seoul' })
    if (!map[date]) map[date] = []
    map[date].push(item)
  }
  return Object.entries(map)
    .sort(([a], [b]) => {
      const toMs = (d: string) => new Date(d.replace(/(\d+)\. (\d+)\. (\d+)\./, '$1-$2-$3')).getTime()
      return toMs(b) - toMs(a)
    })
    .map(([date, items]) => ({ date, items }))
}

// ── Manual TradeLog Composer ──────────────────────────────────────────────────

const ACTION_OPTIONS = [
  { value: 'buy',    label: '신규매수' },
  { value: 'add',    label: '추가매수' },
  { value: 'reduce', label: '일부매도' },
  { value: 'sell',   label: '전량매도' },
] as const

function ManualTradeComposer({
  tickers,
  onCreated,
  onClose,
}: {
  tickers: Ticker[]
  onCreated: (log: TradeLog) => void
  onClose: () => void
}) {
  const portfolioTickers = tickers.filter(t => t.status === 'portfolio')

  const [tickerId, setTickerId] = useState(portfolioTickers[0]?.id ?? '')
  const [action, setAction] = useState<'buy' | 'sell' | 'add' | 'reduce'>('buy')
  const [qtyBefore, setQtyBefore] = useState('0')
  const [qtyAfter, setQtyAfter] = useState('')
  const [priceBefore, setPriceBefore] = useState('0')
  const [priceAfter, setPriceAfter] = useState('')
  const [detectedAt, setDetectedAt] = useState(() => new Date().toISOString().slice(0, 10))
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  // 종목 선택 시 포트폴리오 수량/단가 자동 입력
  function handleTickerChange(id: string) {
    setTickerId(id)
    const t = tickers.find(t => t.id === id)
    if (!t) return
    const qty = t.portfolio_quantity?.toString() ?? ''
    const price = t.portfolio_avg_price?.toString() ?? ''
    applyActionDefaults(action, qty, price)
  }

  function applyActionDefaults(act: typeof action, qty: string, price: string) {
    if (act === 'buy') {
      setQtyBefore('0'); setQtyAfter(qty)
      setPriceBefore('0'); setPriceAfter(price)
    } else if (act === 'sell') {
      setQtyBefore(qty); setQtyAfter('0')
      setPriceBefore(price); setPriceAfter('0')
    } else {
      setQtyBefore(qty); setQtyAfter(qty)
      setPriceBefore(price); setPriceAfter(price)
    }
  }

  function handleActionChange(act: typeof action) {
    setAction(act)
    const t = tickers.find(t => t.id === tickerId)
    const qty = t?.portfolio_quantity?.toString() ?? ''
    const price = t?.portfolio_avg_price?.toString() ?? ''
    applyActionDefaults(act, qty, price)
  }

  // 초기 자동입력
  useEffect(() => {
    if (portfolioTickers.length > 0) handleTickerChange(portfolioTickers[0].id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function submit() {
    setError('')
    if (!tickerId) { setError('종목을 선택하세요'); return }
    setSaving(true)
    try {
      const res = await fetch('/api/tradelog', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker_id: tickerId,
          action,
          quantity_before: parseFloat(qtyBefore) || 0,
          quantity_after: parseFloat(qtyAfter) || 0,
          avg_price_before: parseFloat(priceBefore) || 0,
          avg_price_after: parseFloat(priceAfter) || 0,
          detected_at: detectedAt ? new Date(detectedAt).toISOString() : undefined,
          note: note.trim() || undefined,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '오류 발생' }))
        setError(err.detail || '오류 발생')
        return
      }
      const created: TradeLog = await res.json()
      onCreated(created)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  const selectedTicker = tickers.find(t => t.id === tickerId)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
      <div className="bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-2xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="text-gray-900 dark:text-white font-semibold text-base flex items-center gap-2">
            <PenLine size={16} className="text-violet-400" /> 거래 수동 기록
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
            <X size={18} />
          </button>
        </div>

        {portfolioTickers.length === 0 ? (
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-4">
            포트폴리오에 종목이 없습니다. KIS 동기화 후 다시 시도하세요.
          </p>
        ) : (
          <>
            {/* 종목 선택 */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400">종목</label>
              <select
                value={tickerId}
                onChange={e => handleTickerChange(e.target.value)}
                className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-violet-500"
              >
                {portfolioTickers.map(t => (
                  <option key={t.id} value={t.id}>{t.name} ({t.symbol})</option>
                ))}
              </select>
              {selectedTicker && (
                <p className="text-xs text-gray-400 dark:text-gray-500">
                  현재 포트폴리오: {selectedTicker.portfolio_quantity?.toFixed(2) ?? '-'}주
                  {selectedTicker.portfolio_avg_price ? ` · 평균단가 ${selectedTicker.portfolio_avg_price.toLocaleString()}` : ''}
                </p>
              )}
            </div>

            {/* 거래 유형 */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 유형</label>
              <div className="grid grid-cols-4 gap-1.5">
                {ACTION_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => handleActionChange(opt.value)}
                    className={`py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                      action === opt.value
                        ? ACTION_COLOR[opt.value] + ' border-transparent'
                        : 'bg-gray-100 dark:bg-gray-800 border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:border-gray-400'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* 수량 */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 전 수량</label>
                <input
                  type="number" min="0" step="any"
                  value={qtyBefore}
                  onChange={e => setQtyBefore(e.target.value)}
                  className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-violet-500"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 후 수량</label>
                <input
                  type="number" min="0" step="any"
                  value={qtyAfter}
                  onChange={e => setQtyAfter(e.target.value)}
                  className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-violet-500"
                />
              </div>
            </div>

            {/* 평균단가 */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 전 평균단가</label>
                <input
                  type="number" min="0" step="any"
                  value={priceBefore}
                  onChange={e => setPriceBefore(e.target.value)}
                  className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-violet-500"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 후 평균단가</label>
                <input
                  type="number" min="0" step="any"
                  value={priceAfter}
                  onChange={e => setPriceAfter(e.target.value)}
                  className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-violet-500"
                />
              </div>
            </div>

            {/* 날짜 */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 날짜</label>
              <input
                type="date"
                value={detectedAt}
                onChange={e => setDetectedAt(e.target.value)}
                className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-900 dark:text-white focus:outline-none focus:border-violet-500"
              />
            </div>

            {/* 메모 (선택) */}
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-gray-500 dark:text-gray-400">거래 이유 (선택)</label>
              <textarea
                value={note}
                onChange={e => setNote(e.target.value)}
                placeholder="매수/매도 이유, thesis 관련 판단..."
                rows={2}
                className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-violet-500"
              />
            </div>

            {error && <p className="text-xs text-red-500 dark:text-red-400">{error}</p>}

            <div className="flex gap-3 justify-end pt-1">
              <button onClick={onClose} className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors">
                취소
              </button>
              <button
                onClick={submit}
                disabled={saving || !tickerId}
                className="flex items-center gap-2 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                {saving ? <Loader2 size={14} className="animate-spin" /> : <PenLine size={14} />}
                기록 추가
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function NoteEditor({ log, onSave }: { log: TradeLog; onSave: (id: string, note: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(log.note ?? '')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!text.trim()) return
    setSaving(true)
    try {
      const res = await fetch(`/api/tradelog/${log.id}/note`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: text.trim() }),
      })
      if (res.ok) { onSave(log.id, text.trim()); setEditing(false) }
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <div className="mt-2">
        {log.note ? (
          <div className="group flex items-start gap-2 cursor-pointer" onClick={() => { setText(log.note ?? ''); setEditing(true) }}>
            <p className="text-sm text-gray-600 dark:text-gray-300 leading-relaxed flex-1">{log.note}</p>
            <Pencil size={12} className="text-gray-500 dark:text-gray-600 group-hover:text-gray-400 flex-shrink-0 mt-0.5 transition-colors" />
          </div>
        ) : (
          <button onClick={() => { setText(''); setEditing(true) }} className="flex items-center gap-1.5 text-xs text-gray-500 dark:text-gray-600 hover:text-gray-400 transition-colors">
            <Pencil size={12} />
            거래 이유를 기록하세요...
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="mt-2 space-y-2">
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save() }}
        placeholder="매수/매도 이유, thesis 관련 판단, 시장 환경... (⌘Enter 저장)"
        rows={3}
        autoFocus
        disabled={saving}
        className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-400 dark:border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-gray-400 dark:focus:border-gray-500 disabled:opacity-50"
      />
      <div className="flex items-center gap-2">
        <button onClick={save} disabled={saving || !text.trim()} className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          저장
        </button>
        <button onClick={() => { setEditing(false); setText(log.note ?? '') }} className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
          <X size={12} /> 취소
        </button>
      </div>
    </div>
  )
}

// ── IdeaMemo types & components ───────────────────────────────────────────────

interface IdeaMemo {
  id: string
  content: string
  ticker_symbol: string | null
  created_at: string
  updated_at: string
}

function IdeaCard({ memo, onUpdate, onDelete }: {
  memo: IdeaMemo
  onUpdate: (id: string, content: string, ticker_symbol: string | null) => void
  onDelete: (id: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(memo.content)
  const [tag, setTag] = useState(memo.ticker_symbol ?? '')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!text.trim()) return
    setSaving(true)
    try {
      const res = await fetch(`/api/ideas/${memo.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text.trim(), ticker_symbol: tag.trim() || null }),
      })
      if (res.ok) {
        const updated: IdeaMemo = await res.json()
        onUpdate(memo.id, updated.content, updated.ticker_symbol)
        setEditing(false)
      }
    } finally {
      setSaving(false)
    }
  }

  function cancel() {
    setText(memo.content)
    setTag(memo.ticker_symbol ?? '')
    setEditing(false)
  }

  if (editing) {
    return (
      <div className="bg-gray-50 dark:bg-gray-900 border border-blue-700/60 rounded-xl px-4 py-4 space-y-3">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save() }}
          rows={4}
          autoFocus
          disabled={saving}
          className="w-full bg-gray-100 dark:bg-gray-800 border border-gray-400 dark:border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-gray-400 dark:focus:border-gray-500 disabled:opacity-50"
        />
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2.5 py-1.5 flex-1 max-w-[140px]">
            <Tag size={11} className="text-gray-400 dark:text-gray-500 flex-shrink-0" />
            <input
              value={tag}
              onChange={e => setTag(e.target.value.toUpperCase())}
              placeholder="종목 (선택)"
              className="bg-transparent text-xs text-gray-600 dark:text-gray-300 placeholder-gray-300 dark:placeholder-gray-600 focus:outline-none w-full"
            />
          </div>
          <button onClick={save} disabled={saving || !text.trim()} className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            저장
          </button>
          <button onClick={cancel} className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
            <X size={12} /> 취소
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl px-4 py-4 group">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-gray-700 dark:text-gray-200 leading-relaxed flex-1 whitespace-pre-wrap">{memo.content}</p>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button onClick={() => setEditing(true)} className="p-1 text-gray-500 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors">
            <Pencil size={13} />
          </button>
          <button onClick={() => onDelete(memo.id)} className="p-1 text-gray-700 hover:text-red-400 transition-colors">
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      <div className="flex items-center gap-2 mt-2">
        {memo.ticker_symbol && (
          <span className="text-xs bg-violet-900/50 text-violet-600 dark:text-violet-300 border border-violet-800/50 px-2 py-0.5 rounded-full font-medium">
            {memo.ticker_symbol}
          </span>
        )}
        <span className="text-xs text-gray-500 dark:text-gray-600 ml-auto">{fmtKST(memo.created_at)}</span>
      </div>
    </div>
  )
}

function IdeaComposer({ onCreated }: { onCreated: (memo: IdeaMemo) => void }) {
  const [text, setText] = useState('')
  const [tag, setTag] = useState('')
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  async function submit() {
    if (!text.trim()) return
    setSaving(true)
    try {
      const res = await fetch('/api/ideas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text.trim(), ticker_symbol: tag.trim() || null }),
      })
      if (res.ok) {
        const memo: IdeaMemo = await res.json()
        onCreated(memo)
        setText('')
        setTag('')
        textareaRef.current?.focus()
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-gray-50 dark:bg-gray-900 border border-gray-300 dark:border-gray-700 rounded-xl px-4 py-4 space-y-3">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
        placeholder="떠오른 투자 아이디어를 기록하세요... (⌘Enter 저장)"
        rows={3}
        disabled={saving}
        className="w-full bg-transparent text-sm text-gray-700 dark:text-gray-200 placeholder-gray-300 dark:placeholder-gray-600 resize-none focus:outline-none disabled:opacity-50"
      />
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-2.5 py-1.5 flex-1 max-w-[140px]">
          <Tag size={11} className="text-gray-400 dark:text-gray-500 flex-shrink-0" />
          <input
            value={tag}
            onChange={e => setTag(e.target.value.toUpperCase())}
            placeholder="종목 (선택)"
            className="bg-transparent text-xs text-gray-600 dark:text-gray-300 placeholder-gray-300 dark:placeholder-gray-600 focus:outline-none w-full"
          />
        </div>
        <button
          onClick={submit}
          disabled={saving || !text.trim()}
          className="flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors ml-auto"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />}
          기록
        </button>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = 'trade' | 'idea'

export default function JournalPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('trade')

  // trade log state
  const [logs, setLogs] = useState<TradeLog[]>([])
  const [logsLoading, setLogsLoading] = useState(true)
  const [tradeFilter, setTradeFilter] = useState<'all' | 'unnoted'>('all')
  const [showManualForm, setShowManualForm] = useState(false)
  const [tickers, setTickers] = useState<Ticker[]>([])

  // idea memo state
  const [ideas, setIdeas] = useState<IdeaMemo[]>([])
  const [ideasLoading, setIdeasLoading] = useState(true)

  useEffect(() => {
    fetchLogs()
    fetchIdeas()
    fetch('/api/tickers').then(r => r.ok ? r.json() : []).then(setTickers).catch(() => null)
  }, [])

  async function fetchLogs() {
    setLogsLoading(true)
    try {
      const res = await fetch('/api/tradelog')
      if (res.ok) setLogs(await res.json())
    } finally {
      setLogsLoading(false)
    }
  }

  async function fetchIdeas() {
    setIdeasLoading(true)
    try {
      const res = await fetch('/api/ideas')
      if (res.ok) setIdeas(await res.json())
    } finally {
      setIdeasLoading(false)
    }
  }

  function handleLogCreated(log: TradeLog) {
    setLogs(prev => [log, ...prev].sort((a, b) => b.detected_at.localeCompare(a.detected_at)))
  }

  function handleSaveNote(id: string, note: string) {
    setLogs(prev => prev.map(l => l.id === id ? { ...l, note, noted_at: new Date().toISOString() } : l))
  }

  async function handleDeleteLog(id: string) {
    if (!confirm('이 거래 기록을 삭제할까요?')) return
    const res = await fetch(`/api/tradelog/${id}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) setLogs(prev => prev.filter(l => l.id !== id))
  }

  function handleIdeaCreated(memo: IdeaMemo) {
    setIdeas(prev => [memo, ...prev])
  }

  function handleIdeaUpdated(id: string, content: string, ticker_symbol: string | null) {
    setIdeas(prev => prev.map(m => m.id === id ? { ...m, content, ticker_symbol, updated_at: new Date().toISOString() } : m))
  }

  async function handleIdeaDeleted(id: string) {
    if (!confirm('이 메모를 삭제할까요?')) return
    const res = await fetch(`/api/ideas/${id}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) setIdeas(prev => prev.filter(m => m.id !== id))
  }

  const filtered = tradeFilter === 'unnoted' ? logs.filter(l => !l.note) : logs
  const unnoted = logs.filter(l => !l.note).length
  const groupedLogs = groupByDate(filtered, 'detected_at')
  const groupedIdeas = groupByDate(ideas, 'created_at')

  return (
    <div className="min-h-screen bg-white dark:bg-gray-950">
      <header className="border-b border-gray-200 dark:border-gray-800 px-3 py-3 sm:px-6 sm:py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-2">
              <BookOpen className="text-violet-400" size={18} />
              <h1 className="text-base sm:text-lg font-bold text-gray-900 dark:text-white">투자 일지</h1>
            </div>
            {tab === 'trade' && unnoted > 0 && (
              <span className="text-xs bg-amber-100 text-amber-700 dark:bg-amber-700 dark:text-amber-200 font-medium px-2 py-0.5 rounded-full">
                미작성 {unnoted}건
              </span>
            )}
          </div>

          {/* 세그먼트 탭 + 테마 */}
          <div className="flex items-center gap-2">
          <ThemeControls />
          <div className="flex items-center bg-gray-200 dark:bg-gray-800/60 rounded-lg p-0.5">
            <button
              onClick={() => setTab('trade')}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition-colors ${
                tab === 'trade' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
              }`}
            >
              <BookOpen size={12} />
              거래일지
            </button>
            <button
              onClick={() => setTab('idea')}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition-colors ${
                tab === 'idea' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
              }`}
            >
              <Lightbulb size={12} />
              아이디어
              {ideas.length > 0 && (
                <span className="bg-violet-100 text-violet-700 dark:bg-violet-700 dark:text-violet-200 text-xs px-1.5 py-0 rounded-full leading-5">
                  {ideas.length}
                </span>
              )}
            </button>
          </div>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-3 sm:px-6 py-6 space-y-6">

        {/* ── 거래일지 탭 ── */}
        {tab === 'trade' && (
          <>
            <div className="flex items-center justify-between gap-2">
              <button
                onClick={() => setShowManualForm(true)}
                className="flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
              >
                <PenLine size={12} /> 수동 기록
              </button>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setTradeFilter('all')}
                  className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    tradeFilter === 'all' ? 'bg-gray-200 dark:bg-gray-700 border-gray-400 dark:border-gray-600 text-gray-900 dark:text-white' : 'border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
                  }`}
                >
                  전체 {logs.length}
                </button>
                <button
                  onClick={() => setTradeFilter('unnoted')}
                  className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                    tradeFilter === 'unnoted' ? 'bg-amber-100 border-amber-300 dark:bg-amber-800 dark:border-amber-700 text-amber-700 dark:text-amber-200' : 'border-gray-300 dark:border-gray-700 text-gray-500 dark:text-gray-400 hover:text-gray-600 dark:hover:text-gray-300'
                  }`}
                >
                  미작성 {unnoted}
                </button>
              </div>
            </div>

            {logsLoading && <p className="text-gray-400 dark:text-gray-500 text-sm text-center py-12">불러오는 중...</p>}
            {!logsLoading && logs.length === 0 && (
              <div className="text-center py-16 space-y-2">
                <p className="text-gray-400 dark:text-gray-500 text-sm">아직 감지된 거래가 없습니다.</p>
                <p className="text-gray-500 dark:text-gray-600 text-xs">KIS 동기화를 실행하면 거래가 자동으로 기록됩니다.</p>
              </div>
            )}
            {!logsLoading && logs.length > 0 && filtered.length === 0 && (
              <p className="text-gray-500 dark:text-gray-600 text-sm text-center py-12">미작성 거래가 없습니다.</p>
            )}

            {groupedLogs.map(({ date, items }) => (
              <section key={date} className="space-y-3">
                <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">{date}</p>
                {items.map(log => (
                  <div
                    key={log.id}
                    className={`bg-gray-50 dark:bg-gray-900 border rounded-xl px-4 py-4 ${!log.note ? 'border-amber-800/60' : 'border-gray-200 dark:border-gray-800'}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
                        <span className="text-sm">{ACTION_ICON[log.action]}</span>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${ACTION_COLOR[log.action]}`}>
                          {ACTION_LABEL[log.action]}
                        </span>
                        <span className="text-sm font-bold text-gray-900 dark:text-white">{log.symbol}</span>
                        <span className="text-xs text-gray-500 dark:text-gray-400 truncate">{log.name}</span>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {!log.note && <span className="text-xs text-amber-500 font-medium">미작성</span>}
                        <button onClick={() => handleDeleteLog(log.id)} className="p-1 text-gray-700 hover:text-red-400 transition-colors">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                      <span className="text-sm text-gray-600 dark:text-gray-300 font-medium">{qtyChange(log)}</span>
                      {priceStr(log) && <span className="text-xs text-gray-400 dark:text-gray-500">{priceStr(log)}</span>}
                      <span className="text-xs text-gray-500 dark:text-gray-600 ml-auto">{fmtKST(log.detected_at)}</span>
                    </div>
                    <NoteEditor log={log} onSave={handleSaveNote} />
                  </div>
                ))}
              </section>
            ))}
          </>
        )}

        {/* ── 아이디어 탭 ── */}
        {tab === 'idea' && (
          <>
            <IdeaComposer onCreated={handleIdeaCreated} />

            {ideasLoading && <p className="text-gray-400 dark:text-gray-500 text-sm text-center py-8">불러오는 중...</p>}
            {!ideasLoading && ideas.length === 0 && (
              <div className="text-center py-16 space-y-2">
                <Lightbulb size={32} className="text-gray-700 mx-auto" />
                <p className="text-gray-400 dark:text-gray-500 text-sm">아직 기록된 아이디어가 없습니다.</p>
                <p className="text-gray-500 dark:text-gray-600 text-xs">떠오른 투자 아이디어를 바로 메모하세요.</p>
              </div>
            )}

            {groupedIdeas.map(({ date, items }) => (
              <section key={date} className="space-y-3">
                <p className="text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">{date}</p>
                {items.map(memo => (
                  <IdeaCard
                    key={memo.id}
                    memo={memo}
                    onUpdate={handleIdeaUpdated}
                    onDelete={handleIdeaDeleted}
                  />
                ))}
              </section>
            ))}
          </>
        )}

      </main>

      {showManualForm && (
        <ManualTradeComposer
          tickers={tickers}
          onCreated={handleLogCreated}
          onClose={() => setShowManualForm(false)}
        />
      )}
    </div>
  )
}
