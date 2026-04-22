import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, Pencil, Check, X, Trash2, Loader2 } from 'lucide-react'
import { fmtKST } from '../utils/date'

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
  buy: '신규매수',
  sell: '전량매도',
  add: '추가매수',
  reduce: '일부매도',
}

const ACTION_COLOR: Record<string, string> = {
  buy: 'bg-emerald-900 text-emerald-300',
  sell: 'bg-red-900 text-red-300',
  add: 'bg-blue-900 text-blue-300',
  reduce: 'bg-orange-900 text-orange-300',
}

const ACTION_ICON: Record<string, string> = {
  buy: '🟢',
  sell: '🔴',
  add: '📈',
  reduce: '📉',
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

function groupByDate(logs: TradeLog[]): { date: string; items: TradeLog[] }[] {
  const map: Record<string, TradeLog[]> = {}
  for (const log of logs) {
    const date = log.detected_at.slice(0, 10)
    if (!map[date]) map[date] = []
    map[date].push(log)
  }
  return Object.entries(map)
    .sort(([a], [b]) => b.localeCompare(a))
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
      if (res.ok) {
        onSave(log.id, text.trim())
        setEditing(false)
      }
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <div className="mt-2">
        {log.note ? (
          <div
            className="group flex items-start gap-2 cursor-pointer"
            onClick={() => { setText(log.note ?? ''); setEditing(true) }}
          >
            <p className="text-sm text-gray-300 leading-relaxed flex-1">{log.note}</p>
            <Pencil size={12} className="text-gray-600 group-hover:text-gray-400 flex-shrink-0 mt-0.5 transition-colors" />
          </div>
        ) : (
          <button
            onClick={() => { setText(''); setEditing(true) }}
            className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-400 transition-colors"
          >
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
        <button
          onClick={save}
          disabled={saving || !text.trim()}
          className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
          저장
        </button>
        <button
          onClick={() => { setEditing(false); setText(log.note ?? '') }}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          <X size={12} /> 취소
        </button>
      </div>
    </div>
  )
}

export default function JournalPage() {
  const navigate = useNavigate()
  const [logs, setLogs] = useState<TradeLog[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'unnoted'>('all')

  async function fetchLogs() {
    setLoading(true)
    try {
      const res = await fetch('/api/tradelog')
      if (res.ok) setLogs(await res.json())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchLogs() }, [])

  function handleSave(id: string, note: string) {
    setLogs(prev => prev.map(l => l.id === id ? { ...l, note, noted_at: new Date().toISOString() } : l))
  }

  async function handleDelete(id: string) {
    if (!confirm('이 거래 기록을 삭제할까요?')) return
    const res = await fetch(`/api/tradelog/${id}`, { method: 'DELETE' })
    if (res.ok || res.status === 204) setLogs(prev => prev.filter(l => l.id !== id))
  }

  const filtered = filter === 'unnoted' ? logs.filter(l => !l.note) : logs
  const unnoted = logs.filter(l => !l.note).length
  const grouped = groupByDate(filtered)

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
            {unnoted > 0 && (
              <span className="text-xs bg-amber-700 text-amber-200 font-medium px-2 py-0.5 rounded-full">
                미작성 {unnoted}건
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setFilter('all')}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                filter === 'all' ? 'bg-gray-700 border-gray-600 text-white' : 'border-gray-700 text-gray-400 hover:text-gray-300'
              }`}
            >
              전체 {logs.length}
            </button>
            <button
              onClick={() => setFilter('unnoted')}
              className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                filter === 'unnoted' ? 'bg-amber-800 border-amber-700 text-amber-200' : 'border-gray-700 text-gray-400 hover:text-gray-300'
              }`}
            >
              미작성 {unnoted}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-3 sm:px-6 py-6 space-y-8">
        {loading && <p className="text-gray-500 text-sm text-center py-12">불러오는 중...</p>}
        {!loading && logs.length === 0 && (
          <div className="text-center py-16 space-y-2">
            <p className="text-gray-500 text-sm">아직 감지된 거래가 없습니다.</p>
            <p className="text-gray-600 text-xs">KIS 동기화를 실행하면 거래가 자동으로 기록됩니다.</p>
          </div>
        )}
        {!loading && logs.length > 0 && filtered.length === 0 && (
          <p className="text-gray-600 text-sm text-center py-12">미작성 거래가 없습니다.</p>
        )}

        {grouped.map(({ date, items }) => (
          <section key={date}>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
              {date}
            </p>
            <div className="space-y-3">
              {items.map(log => (
                <div
                  key={log.id}
                  className={`bg-gray-900 border rounded-xl px-4 py-4 ${
                    !log.note ? 'border-amber-800/60' : 'border-gray-800'
                  }`}
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
                      {!log.note && (
                        <span className="text-xs text-amber-500 font-medium">미작성</span>
                      )}
                      <button
                        onClick={() => handleDelete(log.id)}
                        className="p-1 text-gray-700 hover:text-red-400 transition-colors"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                    <span className="text-sm text-gray-300 font-medium">{qtyChange(log)}</span>
                    {priceStr(log) && (
                      <span className="text-xs text-gray-500">{priceStr(log)}</span>
                    )}
                    <span className="text-xs text-gray-600 ml-auto">{fmtKST(log.detected_at)}</span>
                  </div>

                  <NoteEditor log={log} onSave={handleSave} />
                </div>
              ))}
            </div>
          </section>
        ))}
      </main>
    </div>
  )
}
