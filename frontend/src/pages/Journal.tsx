import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, Pencil, Check, X, Trash2, Loader2, Lightbulb, Plus, Tag } from 'lucide-react'
import { fmtKST } from '../utils/date'

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
  buy: 'bg-emerald-900 text-emerald-300',
  sell: 'bg-red-900 text-red-300',
  add: 'bg-blue-900 text-blue-300',
  reduce: 'bg-orange-900 text-orange-300',
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
            <p className="text-sm text-gray-300 leading-relaxed flex-1">{log.note}</p>
            <Pencil size={12} className="text-gray-600 group-hover:text-gray-400 flex-shrink-0 mt-0.5 transition-colors" />
          </div>
        ) : (
          <button onClick={() => { setText(''); setEditing(true) }} className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-400 transition-colors">
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
        className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-500 disabled:opacity-50"
      />
      <div className="flex items-center gap-2">
        <button onClick={save} disabled={saving || !text.trim()} className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          저장
        </button>
        <button onClick={() => { setEditing(false); setText(log.note ?? '') }} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors">
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
      <div className="bg-gray-900 border border-blue-700/60 rounded-xl px-4 py-4 space-y-3">
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) save() }}
          rows={4}
          autoFocus
          disabled={saving}
          className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none focus:border-gray-500 disabled:opacity-50"
        />
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 flex-1 max-w-[140px]">
            <Tag size={11} className="text-gray-500 flex-shrink-0" />
            <input
              value={tag}
              onChange={e => setTag(e.target.value.toUpperCase())}
              placeholder="종목 (선택)"
              className="bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none w-full"
            />
          </div>
          <button onClick={save} disabled={saving || !text.trim()} className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors">
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
            저장
          </button>
          <button onClick={cancel} className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors">
            <X size={12} /> 취소
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-4 group">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-gray-200 leading-relaxed flex-1 whitespace-pre-wrap">{memo.content}</p>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button onClick={() => setEditing(true)} className="p-1 text-gray-600 hover:text-gray-300 transition-colors">
            <Pencil size={13} />
          </button>
          <button onClick={() => onDelete(memo.id)} className="p-1 text-gray-700 hover:text-red-400 transition-colors">
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      <div className="flex items-center gap-2 mt-2">
        {memo.ticker_symbol && (
          <span className="text-xs bg-violet-900/50 text-violet-300 border border-violet-800/50 px-2 py-0.5 rounded-full font-medium">
            {memo.ticker_symbol}
          </span>
        )}
        <span className="text-xs text-gray-600 ml-auto">{fmtKST(memo.created_at)}</span>
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
    <div className="bg-gray-900 border border-gray-700 rounded-xl px-4 py-4 space-y-3">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) submit() }}
        placeholder="떠오른 투자 아이디어를 기록하세요... (⌘Enter 저장)"
        rows={3}
        disabled={saving}
        className="w-full bg-transparent text-sm text-gray-200 placeholder-gray-600 resize-none focus:outline-none disabled:opacity-50"
      />
      <div className="flex items-center gap-2">
        <div className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded-lg px-2.5 py-1.5 flex-1 max-w-[140px]">
          <Tag size={11} className="text-gray-500 flex-shrink-0" />
          <input
            value={tag}
            onChange={e => setTag(e.target.value.toUpperCase())}
            placeholder="종목 (선택)"
            className="bg-transparent text-xs text-gray-300 placeholder-gray-600 focus:outline-none w-full"
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

  // idea memo state
  const [ideas, setIdeas] = useState<IdeaMemo[]>([])
  const [ideasLoading, setIdeasLoading] = useState(true)

  useEffect(() => {
    fetchLogs()
    fetchIdeas()
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
    <div className="min-h-screen bg-gray-950">
      <header className="border-b border-gray-800 px-3 py-3 sm:px-6 sm:py-4">
        <div className="max-w-3xl mx-auto flex items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="text-gray-400 hover:text-white transition-colors">
              <ArrowLeft size={20} />
            </button>
            <div className="flex items-center gap-2">
              <BookOpen className="text-violet-400" size={18} />
              <h1 className="text-base sm:text-lg font-bold text-white">투자 일지</h1>
            </div>
            {tab === 'trade' && unnoted > 0 && (
              <span className="text-xs bg-amber-700 text-amber-200 font-medium px-2 py-0.5 rounded-full">
                미작성 {unnoted}건
              </span>
            )}
          </div>

          {/* 세그먼트 탭 */}
          <div className="flex items-center bg-gray-800/60 rounded-lg p-0.5">
            <button
              onClick={() => setTab('trade')}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition-colors ${
                tab === 'trade' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-300'
              }`}
            >
              <BookOpen size={12} />
              거래일지
            </button>
            <button
              onClick={() => setTab('idea')}
              className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition-colors ${
                tab === 'idea' ? 'bg-gray-700 text-white' : 'text-gray-400 hover:text-gray-300'
              }`}
            >
              <Lightbulb size={12} />
              아이디어
              {ideas.length > 0 && (
                <span className="bg-violet-700 text-violet-200 text-xs px-1.5 py-0 rounded-full leading-5">
                  {ideas.length}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-3 sm:px-6 py-6 space-y-6">

        {/* ── 거래일지 탭 ── */}
        {tab === 'trade' && (
          <>
            <div className="flex items-center justify-end gap-1">
              <button
                onClick={() => setTradeFilter('all')}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  tradeFilter === 'all' ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-700 text-gray-400 hover:text-gray-300'
                }`}
              >
                전체 {logs.length}
              </button>
              <button
                onClick={() => setTradeFilter('unnoted')}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  tradeFilter === 'unnoted' ? 'bg-amber-800 border-amber-700 text-amber-200' : 'border-gray-700 text-gray-400 hover:text-gray-300'
                }`}
              >
                미작성 {unnoted}
              </button>
            </div>

            {logsLoading && <p className="text-gray-500 text-sm text-center py-12">불러오는 중...</p>}
            {!logsLoading && logs.length === 0 && (
              <div className="text-center py-16 space-y-2">
                <p className="text-gray-500 text-sm">아직 감지된 거래가 없습니다.</p>
                <p className="text-gray-600 text-xs">KIS 동기화를 실행하면 거래가 자동으로 기록됩니다.</p>
              </div>
            )}
            {!logsLoading && logs.length > 0 && filtered.length === 0 && (
              <p className="text-gray-600 text-sm text-center py-12">미작성 거래가 없습니다.</p>
            )}

            {groupedLogs.map(({ date, items }) => (
              <section key={date} className="space-y-3">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{date}</p>
                {items.map(log => (
                  <div
                    key={log.id}
                    className={`bg-gray-900 border rounded-xl px-4 py-4 ${!log.note ? 'border-amber-800/60' : 'border-gray-800'}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
                        <span className="text-sm">{ACTION_ICON[log.action]}</span>
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${ACTION_COLOR[log.action]}`}>
                          {ACTION_LABEL[log.action]}
                        </span>
                        <span className="text-sm font-bold text-white">{log.symbol}</span>
                        <span className="text-xs text-gray-400 truncate">{log.name}</span>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {!log.note && <span className="text-xs text-amber-500 font-medium">미작성</span>}
                        <button onClick={() => handleDeleteLog(log.id)} className="p-1 text-gray-700 hover:text-red-400 transition-colors">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                    <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                      <span className="text-sm text-gray-300 font-medium">{qtyChange(log)}</span>
                      {priceStr(log) && <span className="text-xs text-gray-500">{priceStr(log)}</span>}
                      <span className="text-xs text-gray-600 ml-auto">{fmtKST(log.detected_at)}</span>
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

            {ideasLoading && <p className="text-gray-500 text-sm text-center py-8">불러오는 중...</p>}
            {!ideasLoading && ideas.length === 0 && (
              <div className="text-center py-16 space-y-2">
                <Lightbulb size={32} className="text-gray-700 mx-auto" />
                <p className="text-gray-500 text-sm">아직 기록된 아이디어가 없습니다.</p>
                <p className="text-gray-600 text-xs">떠오른 투자 아이디어를 바로 메모하세요.</p>
              </div>
            )}

            {groupedIdeas.map(({ date, items }) => (
              <section key={date} className="space-y-3">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider">{date}</p>
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
    </div>
  )
}
