import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { PlusCircle, TrendingUp, Eye, AlertCircle, FileText, RefreshCw, Bell, BellOff, X, Sparkles, Settings, BookOpen } from 'lucide-react'
import { api } from '../api'
import type { Ticker, Market } from '../types'

function PipelineRow({ label, value, tag, tagLabel }: {
  label: string
  value: string
  tag?: 'ok' | 'warn' | 'error'
  tagLabel?: string
}) {
  const tagStyle = tag === 'ok'
    ? 'bg-emerald-900/60 text-emerald-400'
    : tag === 'warn'
    ? 'bg-amber-900/60 text-amber-400'
    : tag === 'error'
    ? 'bg-red-900/60 text-red-400'
    : ''
  return (
    <div className="bg-gray-800/30 px-4 py-2.5 flex items-start justify-between gap-3">
      <span className="text-xs text-gray-400 flex-shrink-0 w-36">{label}</span>
      <div className="flex-1 flex items-start justify-between gap-2 min-w-0">
        {value && <span className="text-xs text-gray-300 leading-relaxed">{value}</span>}
        {tag && tagLabel && (
          <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${tagStyle}`}>
            {tagLabel}
          </span>
        )}
      </div>
    </div>
  )
}

const STATUS_BADGE: Record<string, string> = {
  draft: 'bg-yellow-900 text-yellow-200',
  confirmed: 'bg-green-900 text-green-200',
  needs_review: 'bg-red-900 text-red-200',
}

const STATUS_LABEL: Record<string, string> = {
  draft: '초안',
  confirmed: '확정',
  needs_review: '재검토',
}

const WATCHLIST_STATUS_ORDER: Record<string, number> = {
  confirmed: 0,
  draft: 1,
  needs_review: 2,
}

type BulkAction = 'refresh' | 'analyze' | 'report'
type JobStatus = 'waiting' | 'running' | 'done' | 'error'

interface JobState {
  status: JobStatus
  msg?: string
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [tickers, setTickers] = useState<Ticker[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({ symbol: '', name: '', market: 'US_Stock' as Market, status: 'watchlist' })
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')
  const [indicators, setIndicators] = useState<any>(null)

  // Settings state
  const [showSettings, setShowSettings] = useState(false)
  const [settings, setSettings] = useState<Record<string, string>>({ us_data_source: 'yfinance' })
  const [savingSettings, setSavingSettings] = useState(false)
  const [sysInfo, setSysInfo] = useState<Record<string, boolean>>({})

  // Multi-select state
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkRunning, setBulkRunning] = useState(false)
  const [bulkAction, setBulkAction] = useState<BulkAction | null>(null)
  const [jobStatuses, setJobStatuses] = useState<Record<string, JobState>>({})
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    api.getTickers()
      .then(setTickers)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
    fetch('/api/market/indicators')
      .then((r) => r.ok ? r.json() : null)
      .then(setIndicators)
      .catch(() => null)
    fetch('/api/settings')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setSettings(d) })
      .catch(() => null)
    fetch('/api/settings/system-info')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setSysInfo(d) })
      .catch(() => null)
    // 진행 중인 bulk 작업 복원
    restoreBulkStatus()
    return () => stopPolling()
  }, [])

  // ── Bulk status polling ────────────────────────────────────────────────────

  function applyBulkStatus(data: any) {
    if (!data.active || !data.items?.length) return
    const statuses: Record<string, JobState> = {}
    for (const item of data.items) {
      statuses[item.ticker_id] = { status: item.status as JobStatus, msg: item.msg ?? undefined }
    }
    setJobStatuses(statuses)
    setBulkAction(data.action as BulkAction)
  }

  async function restoreBulkStatus() {
    try {
      const res = await fetch('/api/tickers/bulk-status')
      if (!res.ok) return
      const data = await res.json()
      if (!data.active || !data.items?.length) return
      applyBulkStatus(data)
      const allDone = data.items.every((i: any) => i.status === 'done' || i.status === 'error')
      if (!allDone) startPolling()
    } catch { /* ignore */ }
  }

  function startPolling() {
    if (pollRef.current) return
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch('/api/tickers/bulk-status')
        if (!res.ok) return
        const data = await res.json()
        if (!data.active) { stopPolling(); return }
        applyBulkStatus(data)
        const allDone = data.items.every((i: any) => i.status === 'done' || i.status === 'error')
        if (allDone) {
          stopPolling()
          api.getTickers().then(setTickers)
        }
      } catch { /* ignore */ }
    }, 5000)
  }

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  async function saveSetting(key: string, value: string) {
    setSavingSettings(true)
    try {
      const res = await fetch(`/api/settings/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      })
      if (res.ok) setSettings(prev => ({ ...prev, [key]: value }))
    } finally {
      setSavingSettings(false)
    }
  }

  function exitSelectMode() {
    setSelectMode(false)
    setSelectedIds(new Set())
    if (!bulkRunning) {
      setBulkAction(null)
      setJobStatuses({})
    }
  }

  function toggleSelect(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAll() {
    setSelectedIds(new Set(tickers.map(t => t.id)))
  }

  async function runBulkAction(action: BulkAction) {
    const activeJob = Object.values(jobStatuses).some(j => j.status === 'running' || j.status === 'waiting')
    if (bulkRunning || activeJob) return

    const ids = Array.from(selectedIds)
    if (ids.length === 0) return

    setBulkAction(action)
    setBulkRunning(true)
    stopPolling()

    const endpoints: Record<BulkAction, string> = {
      refresh: '/api/tickers/bulk-refresh',
      analyze: '/api/tickers/bulk-analyze',
      report:  '/api/tickers/bulk-report',
    }
    const res = await fetch(endpoints[action], {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker_ids: ids }),
    })
    setBulkRunning(false)

    if (!res.ok) {
      const initial: Record<string, JobState> = {}
      for (const id of ids) initial[id] = { status: 'error', msg: `HTTP ${res.status}` }
      setJobStatuses(initial)
      return
    }

    // 백엔드가 job_init까지 완료한 상태 — 즉시 상태 조회 후 polling 시작
    await restoreBulkStatus()
    startPolling()
  }

  async function toggleDailyAlert(ticker: Ticker) {
    const res = await fetch(`/api/tickers/${ticker.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ daily_alert: !ticker.daily_alert }),
    })
    if (res.ok) {
      const updated = await res.json()
      setTickers((prev) => prev.map((t) => t.id === ticker.id ? { ...t, daily_alert: updated.daily_alert } : t))
    }
  }

  async function handleSync() {
    setSyncing(true)
    setSyncMsg('')
    try {
      const res = await fetch('/api/portfolio/sync', { method: 'POST' })
      if (res.ok) {
        setSyncMsg('동기화 시작됨. 잠시 후 새로고침하세요.')
        setTimeout(() => {
          api.getTickers().then(setTickers)
          setSyncMsg('')
        }, 5000)
      }
    } finally {
      setSyncing(false)
    }
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!form.symbol || !form.name) return
    setAdding(true)
    setAddError('')
    try {
      const ticker = await api.addTicker(form)
      setTickers((prev) => [ticker, ...prev])
      setShowForm(false)
      setForm({ symbol: '', name: '', market: 'US_Stock', status: 'watchlist' })
    } catch (e: unknown) {
      setAddError(e instanceof Error ? e.message : '오류 발생')
    } finally {
      setAdding(false)
    }
  }

  const JOB_LABEL: Record<JobStatus, string> = {
    waiting: '대기',
    running: '진행중',
    done: '완료',
    error: '오류',
  }
  const JOB_COLOR: Record<JobStatus, string> = {
    waiting: 'text-gray-400',
    running: 'text-blue-400',
    done: 'text-emerald-400',
    error: 'text-red-400',
  }
  const ACTION_LABEL: Record<BulkAction, string> = {
    refresh: '데이터 수집',
    analyze: 'Thesis 생성',
    report: '리포트 생성',
  }

  const jobTickerIds = Object.keys(jobStatuses)
  const showProgress = jobTickerIds.length > 0
  const bulkInProgress = Object.values(jobStatuses).some(j => j.status === 'running' || j.status === 'waiting')

  return (
    <div className="min-h-screen bg-gray-950">
      {/* Header */}
      <header className="border-b border-gray-800 px-3 py-3 sm:px-6 sm:py-4 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">
          <TrendingUp className="text-emerald-400" size={22} />
          <h1 className="text-base sm:text-xl font-bold text-white">Value Copilot</h1>
          <span className="hidden sm:block text-xs text-gray-500 ml-2">가치투자 AI 코파일럿</span>
        </div>
        <div className="flex items-center gap-1 sm:gap-2 flex-wrap justify-end">
          <button
            onClick={() => setShowSettings(true)}
            className="text-gray-400 hover:text-white p-1.5 sm:p-2 rounded-lg transition-colors"
            title="설정"
          >
            <Settings size={16} />
          </button>
          <button
            onClick={() => navigate('/reports')}
            className="flex items-center gap-1.5 text-gray-400 hover:text-white text-xs sm:text-sm font-medium px-2 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
          >
            <FileText size={15} />
            보고서
          </button>
          <button
            onClick={() => navigate('/journal')}
            className="flex items-center gap-1.5 text-gray-400 hover:text-white text-xs sm:text-sm font-medium px-2 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
          >
            <BookOpen size={15} />
            일지
          </button>
          <button
            onClick={() => {
              if (selectMode) exitSelectMode()
              else setSelectMode(true)
            }}
            className={`flex items-center gap-1.5 text-xs sm:text-sm font-medium px-2 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors ${
              selectMode
                ? 'bg-violet-700 text-white hover:bg-violet-600'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            <span className="hidden sm:inline">{selectMode ? '✕ 선택 종료' : '☑ 종목 선택'}</span>
            <span className="sm:hidden">{selectMode ? '종료' : '선택'}</span>
          </button>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-1.5 text-gray-400 hover:text-white disabled:opacity-50 text-xs sm:text-sm font-medium px-2 py-1.5 sm:px-3 sm:py-2 rounded-lg transition-colors"
          >
            <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
            <span className="hidden sm:inline">KIS 동기화</span>
            <span className="sm:hidden">동기화</span>
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs sm:text-sm font-medium px-3 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors"
          >
            <PlusCircle size={15} />
            <span className="hidden sm:inline">종목 추가</span>
            <span className="sm:hidden">추가</span>
          </button>
        </div>
      </header>

      {/* Bulk Action Bar */}
      {selectMode && (
        <div className="border-b border-gray-800 bg-gray-900 px-3 sm:px-6 py-2 flex items-center gap-2 flex-wrap">
          <span className="text-sm text-gray-400 mr-1">
            {selectedIds.size > 0 ? `${selectedIds.size}개 선택됨` : '종목을 선택하세요'}
          </span>
          {selectedIds.size < tickers.length && (
            <button
              onClick={selectAll}
              className="text-xs text-gray-500 hover:text-gray-300 underline"
            >
              전체 선택
            </button>
          )}
          {selectedIds.size > 0 && (
            <>
              <div className="flex-1" />
              <button
                onClick={() => runBulkAction('refresh')}
                disabled={bulkRunning || bulkInProgress}
                className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
              >
                데이터 수집
              </button>
              <button
                onClick={() => runBulkAction('analyze')}
                disabled={bulkRunning || bulkInProgress}
                className="flex items-center gap-1.5 bg-violet-700 hover:bg-violet-600 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
              >
                <Sparkles size={13} />
                Thesis 생성
              </button>
              <button
                onClick={() => runBulkAction('report')}
                disabled={bulkRunning || bulkInProgress}
                className="flex items-center gap-1.5 bg-blue-700 hover:bg-blue-600 disabled:opacity-50 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
              >
                <TrendingUp size={13} />
                리포트 생성
              </button>
              <button
                onClick={() => setSelectedIds(new Set())}
                disabled={bulkRunning}
                className="text-gray-500 hover:text-gray-300 disabled:opacity-50 p-1.5 rounded-lg transition-colors"
                title="선택 해제"
              >
                <X size={14} />
              </button>
            </>
          )}
        </div>
      )}

      <main className="max-w-5xl mx-auto px-3 sm:px-6 py-4 sm:py-8">
        {/* Add ticker modal */}
        {showForm && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
            <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 sm:p-6 w-full max-w-md mx-3">
              <h2 className="text-lg font-semibold text-white mb-4">종목 추가</h2>
              <form onSubmit={handleAdd} className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1">심볼</label>
                  <input
                    value={form.symbol}
                    onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })}
                    placeholder="NVDA"
                    className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">회사명</label>
                  <input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="NVIDIA Corporation"
                    className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">시장</label>
                  <select
                    value={form.market}
                    onChange={(e) => setForm({ ...form, market: e.target.value as Market })}
                    className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    <option value="US_Stock">US Stock</option>
                    <option value="KR_Stock">KR Stock</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1">구분</label>
                  <select
                    value={form.status}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}
                    className="w-full bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-emerald-500"
                  >
                    <option value="watchlist">관심 종목</option>
                    <option value="portfolio">포트폴리오</option>
                  </select>
                </div>
                {addError && (
                  <p className="text-red-400 text-sm flex items-center gap-1">
                    <AlertCircle size={14} /> {addError}
                  </p>
                )}
                <div className="flex gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => { setShowForm(false); setAddError('') }}
                    className="flex-1 bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm font-medium py-2 rounded-lg transition-colors"
                  >
                    취소
                  </button>
                  <button
                    type="submit"
                    disabled={adding}
                    className="flex-1 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
                  >
                    {adding ? '추가 중...' : '추가'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Settings modal */}
        {showSettings && (
          <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-3">
            <div className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-gray-800 sticky top-0 bg-gray-900 z-10">
                <h2 className="text-base font-semibold text-white flex items-center gap-2">
                  <Settings size={16} className="text-gray-400" />
                  시스템 파이프라인
                </h2>
                <button onClick={() => setShowSettings(false)} className="text-gray-500 hover:text-gray-300 p-1 rounded">
                  <X size={16} />
                </button>
              </div>

              <div className="p-5 space-y-6">

                {/* US 주식 */}
                <section>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">🇺🇸 US 주식</p>
                  <div className="space-y-px rounded-lg overflow-hidden border border-gray-800">

                    {/* 재무 데이터 — 선택 가능 */}
                    <div className="bg-gray-800/50 px-4 py-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs text-gray-400">재무 데이터</span>
                        {savingSettings && <span className="text-xs text-gray-500">저장 중...</span>}
                      </div>
                      <div className="flex gap-2">
                        {[
                          { value: 'yfinance', label: 'yfinance', desc: '기본 · 안정적' },
                          { value: 'financialdatasets', label: 'financialdatasets.ai', desc: 'API 키 필요 · 내부자 거래 포함' },
                        ].map((opt) => (
                          <label
                            key={opt.value}
                            className={`flex-1 flex items-start gap-2 p-2.5 rounded-lg border cursor-pointer transition-colors text-xs ${
                              settings.us_data_source === opt.value
                                ? 'border-emerald-600 bg-emerald-950/40'
                                : 'border-gray-700 hover:border-gray-600'
                            }`}
                          >
                            <input
                              type="radio"
                              name="us_data_source"
                              value={opt.value}
                              checked={settings.us_data_source === opt.value}
                              onChange={() => saveSetting('us_data_source', opt.value)}
                              disabled={savingSettings}
                              className="mt-0.5 accent-emerald-500 flex-shrink-0"
                            />
                            <div>
                              <p className="text-white font-medium">{opt.label}</p>
                              <p className="text-gray-500 mt-0.5">{opt.desc}</p>
                            </div>
                          </label>
                        ))}
                      </div>
                      {settings.us_data_source === 'financialdatasets' && (
                        <p className={`text-xs mt-2 ${sysInfo.has_financial_datasets_key ? 'text-emerald-400' : 'text-amber-400'}`}>
                          {sysInfo.has_financial_datasets_key
                            ? '✓ FINANCIAL_DATASETS_API_KEY 설정됨 · 한도 초과 시 yfinance로 자동 전환'
                            : '⚠ FINANCIAL_DATASETS_API_KEY 미설정 · yfinance로 자동 전환됩니다'}
                        </p>
                      )}
                    </div>

                    <PipelineRow label="뉴스" value="yfinance (재무 데이터와 통합, 최대 10건)" />
                    <PipelineRow label="SEC 공시 요약" value="EDGAR submissions API → primary HTML → claude-haiku-4-5" />
                  </div>
                </section>

                {/* KR 주식 */}
                <section>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">🇰🇷 KR 주식</p>
                  <div className="space-y-px rounded-lg overflow-hidden border border-gray-800">
                    <PipelineRow
                      label="재무제표"
                      value="OpenDART fnlttSinglAcntAll (IS/BS/CF 단일 호출, CFS 우선)"
                      tag={sysInfo.has_opendart_key ? 'ok' : 'warn'}
                      tagLabel={sysInfo.has_opendart_key ? 'API 키 설정됨' : 'OPENDART_API_KEY 미설정'}
                    />
                    <PipelineRow label="시장 지표 (PER/PBR/시총)" value="yfinance — .KS (KOSPI) / .KQ (KOSDAQ) 자동 판별" />
                    <PipelineRow
                      label="뉴스"
                      value="네이버 뉴스 검색 API (최근 10건)"
                      tag={sysInfo.has_naver_client_id ? 'ok' : 'warn'}
                      tagLabel={sysInfo.has_naver_client_id ? '설정됨' : 'NAVER_CLIENT_ID 미설정'}
                    />
                    <PipelineRow
                      label="공시"
                      value="OpenDART list.json — 최근 60일, 모든 공시 유형"
                      tag={sysInfo.has_opendart_key ? 'ok' : 'warn'}
                      tagLabel={sysInfo.has_opendart_key ? 'API 키 설정됨' : '미설정'}
                    />
                    <PipelineRow
                      label="내부자 거래"
                      value="OpenDART majorstock.json — 최근 180일 임원/주요주주 변동"
                      tag={sysInfo.has_opendart_key ? 'ok' : 'warn'}
                      tagLabel={sysInfo.has_opendart_key ? 'API 키 설정됨' : '미설정'}
                    />
                    <PipelineRow label="정기공시 요약" value="DART main.do TOC → viewer.do 섹션 HTML → claude-haiku-4-5" />
                  </div>
                </section>

                {/* KIS */}
                <section>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">💼 포트폴리오</p>
                  <div className="rounded-lg overflow-hidden border border-gray-800">
                    <PipelineRow
                      label="KIS 동기화"
                      value="한국투자증권 API — 5개 계좌 잔고 조회"
                      tag={sysInfo.has_kis_key ? 'ok' : 'warn'}
                      tagLabel={sysInfo.has_kis_key ? 'API 키 설정됨' : 'KIS_APP_KEY 미설정'}
                    />
                  </div>
                </section>

                {/* AI 모델 */}
                <section>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">🤖 AI 모델</p>
                  <div className="space-y-px rounded-lg overflow-hidden border border-gray-800">
                    <div className="flex items-center justify-between px-3 py-2.5 bg-gray-900">
                      <div className="flex items-center gap-2 flex-1 min-w-0">
                        <span className="text-sm text-gray-300 flex-shrink-0">Anthropic API</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${sysInfo.has_anthropic_key ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'}`}>
                          {sysInfo.has_anthropic_key ? 'API 키 설정됨' : 'ANTHROPIC_API_KEY 미설정'}
                        </span>
                      </div>
                      <a
                        href="https://console.anthropic.com/settings/billing"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex-shrink-0 text-xs text-blue-400 hover:text-blue-300 underline underline-offset-2 transition-colors ml-2"
                      >
                        잔액 확인 →
                      </a>
                    </div>
                    <PipelineRow label="공시 요약 (SEC / DART)" value="claude-haiku-4-5-20251001 · max_tokens 600" />
                    <PipelineRow label="Thesis 생성 / 리포트" value="claude-sonnet-4-6 · max_tokens 8192" />
                    <PipelineRow label="Break Monitor / 브리핑" value="claude-sonnet-4-6" />
                    <PipelineRow label="종목 탐색 / 포트폴리오 점검" value="claude-sonnet-4-6 · SSE 스트리밍" />
                  </div>
                </section>

                {/* 스케줄러 */}
                <section>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">⏰ 자동 스케줄</p>
                  <div className="space-y-px rounded-lg overflow-hidden border border-gray-800">
                    <PipelineRow label="06:00 KST" value="light_refresh — news / metrics / insider_trades + 포트폴리오 현재가/일간등락 갱신" />
                    <PipelineRow label="07:00 KST" value="daily_briefing — 뉴스 + 포트폴리오 + 매크로 브리핑" />
                    <PipelineRow label="08:00 KST" value="break_monitor — confirmed 종목 thesis 이탈 감지" />
                  </div>
                </section>

              </div>
            </div>
          </div>
        )}

        {/* Market Indicators */}
        {indicators && (
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              {
                label: 'VIX',
                value: indicators.vix?.price ?? '–',
                pct: indicators.vix?.change_pct,
                hint: indicators.vix?.price >= 30 ? '공포' : indicators.vix?.price >= 20 ? '주의' : '안정',
              },
              {
                label: 'S&P 500',
                value: indicators.sp500?.price?.toLocaleString() ?? '–',
                pct: indicators.sp500?.change_pct,
              },
              {
                label: 'KOSPI',
                value: indicators.kospi?.price?.toLocaleString() ?? '–',
                pct: indicators.kospi?.change_pct,
              },
              {
                label: 'Fear & Greed',
                value: indicators.fear_greed?.score ?? '–',
                hint: indicators.fear_greed?.rating ?? '',
              },
            ].map((item) => (
              <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3">
                <p className="text-xs text-gray-500 mb-1">{item.label}</p>
                <p className="text-white font-semibold text-lg">{item.value}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  {item.pct !== undefined && (
                    <span className={`text-xs font-medium ${item.pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {item.pct >= 0 ? '+' : ''}{item.pct}%
                    </span>
                  )}
                  {item.hint && <span className="text-xs text-gray-500">{item.hint}</span>}
                </div>
              </div>
            ))}
          </div>
        )}

        {syncMsg && (
          <div className="mb-4 bg-blue-900/30 border border-blue-800 rounded-lg p-3 text-blue-300 text-sm">
            {syncMsg}
          </div>
        )}

        {/* Bulk Progress Panel */}
        {showProgress && bulkAction && (
          <div className="mb-6 bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
              <div className="flex items-center gap-2 flex-wrap">
                {Object.values(jobStatuses).some(j => j.status === 'running') && (
                  <RefreshCw size={13} className="animate-spin text-blue-400" />
                )}
                <span className="text-sm font-medium text-white">
                  {ACTION_LABEL[bulkAction]}
                </span>
                <span className="text-xs text-gray-500">
                  ({Object.values(jobStatuses).filter(j => j.status === 'done').length}/{jobTickerIds.length} 완료)
                </span>
                {Object.values(jobStatuses).some(j => j.status === 'running' || j.status === 'waiting') && (
                  <span className="text-xs text-gray-500">· 페이지 이동해도 계속 진행됩니다</span>
                )}
              </div>
              {!bulkRunning && (
                <button
                  onClick={() => { setBulkAction(null); setJobStatuses({}) }}
                  className="text-gray-500 hover:text-gray-300 p-1 rounded"
                >
                  <X size={14} />
                </button>
              )}
            </div>
            <div className="divide-y divide-gray-800">
              {jobTickerIds.map(id => {
                const ticker = tickers.find(t => t.id === id)
                const job = jobStatuses[id]
                return (
                  <div key={id} className="flex items-center justify-between px-4 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-white font-medium">{ticker?.symbol ?? id}</span>
                      <span className="text-xs text-gray-500">{ticker?.name}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {job.status === 'running' && <RefreshCw size={11} className="animate-spin text-blue-400" />}
                      <span className={`text-xs font-medium ${JOB_COLOR[job.status]}`}>
                        {JOB_LABEL[job.status]}
                      </span>
                      {job.msg && job.status === 'error' && (
                        <span className="text-xs text-red-400 ml-1 truncate max-w-32" title={job.msg}>
                          {job.msg}
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Content */}
        {loading && (
          <p className="text-gray-500 text-center py-16">불러오는 중...</p>
        )}
        {error && (
          <div className="bg-red-900/30 border border-red-800 rounded-lg p-4 text-red-300 text-sm">
            <AlertCircle size={16} className="inline mr-2" />
            {error}
          </div>
        )}

        {!loading && !error && tickers.length === 0 && (
          <div className="text-center py-24 text-gray-500">
            <TrendingUp size={48} className="mx-auto mb-4 text-gray-700" />
            <p className="text-lg">종목이 없습니다.</p>
            <p className="text-sm mt-1">오른쪽 위 "추가" 버튼을 눌러 시작하세요.</p>
          </div>
        )}

        {tickers.length > 0 && (() => {
          const portfolio = tickers
            .filter(t => t.status === 'portfolio')
            .sort((a, b) => {
              const aReview = a.thesis_status === 'needs_review' ? 0 : 1
              const bReview = b.thesis_status === 'needs_review' ? 0 : 1
              if (aReview !== bReview) return aReview - bReview

              const aMove = Math.abs(a.portfolio_daily_pct ?? 0)
              const bMove = Math.abs(b.portfolio_daily_pct ?? 0)
              if (aMove !== bMove) return bMove - aMove

              return a.symbol.localeCompare(b.symbol)
            })
          const watchlist = tickers
            .filter(t => t.status === 'watchlist')
            .sort((a, b) => {
              const aStatus = WATCHLIST_STATUS_ORDER[a.thesis_status ?? ''] ?? 3
              const bStatus = WATCHLIST_STATUS_ORDER[b.thesis_status ?? ''] ?? 3
              if (aStatus !== bStatus) return aStatus - bStatus
              return a.symbol.localeCompare(b.symbol)
            })

          function TickerCard({ ticker }: { ticker: typeof tickers[0] }) {
            const p = ticker.status === 'portfolio' && ticker.portfolio_current_price != null
            const dailyPct = ticker.portfolio_daily_pct ?? 0
            const pnlPct = ticker.portfolio_pnl_pct ?? 0
            const isSelected = selectedIds.has(ticker.id)
            return (
              <div
                className={`bg-gray-900 border rounded-xl px-5 py-4 transition-colors ${
                  selectMode
                    ? isSelected
                      ? 'border-violet-500 cursor-pointer hover:border-violet-400'
                      : 'border-gray-800 cursor-pointer hover:border-gray-600'
                    : 'border-gray-800 hover:border-gray-700'
                }`}
                onClick={selectMode ? () => toggleSelect(ticker.id) : undefined}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 min-w-0">
                    {selectMode && (
                      <div className={`flex-shrink-0 w-4 h-4 rounded border flex items-center justify-center text-xs font-bold ${
                        isSelected ? 'bg-violet-500 border-violet-500 text-white' : 'border-gray-600'
                      }`}>
                        {isSelected && '✓'}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-white font-semibold text-lg">{ticker.symbol}</span>
                        <span className="text-xs text-gray-500 bg-gray-800 px-2 py-0.5 rounded">
                          {ticker.market === 'US_Stock' ? 'US' : 'KR'}
                        </span>
                        {p && ticker.portfolio_current_price != null && (
                          <span className="text-sm font-medium text-white">
                            {ticker.portfolio_current_price.toLocaleString()}
                          </span>
                        )}
                        {p && (
                          <span className={`text-xs font-medium ${dailyPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {dailyPct >= 0 ? '+' : ''}{dailyPct.toFixed(2)}%
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-400 mt-0.5 truncate">{ticker.name}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 flex-shrink-0 ml-3">
                    {/* 포트폴리오 수익률 */}
                    {p && ticker.portfolio_avg_price != null && (
                      <div className="text-right hidden sm:block">
                        <p className={`text-sm font-medium ${pnlPct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(1)}%
                        </p>
                        <p className="text-xs text-gray-500">
                          평균 {ticker.portfolio_avg_price.toLocaleString()}
                          {ticker.portfolio_quantity != null && ` · ${ticker.portfolio_quantity}주`}
                        </p>
                      </div>
                    )}

                    {ticker.has_content && ticker.thesis_status ? (
                      <span className={`text-xs font-medium px-2 py-1 rounded-full ${STATUS_BADGE[ticker.thesis_status] ?? ''}`}>
                        {STATUS_LABEL[ticker.thesis_status] ?? ticker.thesis_status}
                      </span>
                    ) : (
                      <span className="text-xs font-medium px-2 py-1 rounded-full bg-gray-800 text-gray-500">
                        미분석
                      </span>
                    )}
                    {!selectMode && ticker.thesis_status === 'confirmed' && (
                      <button
                        onClick={() => toggleDailyAlert(ticker)}
                        title={ticker.daily_alert ? 'Break Monitor 비활성화' : 'Break Monitor 활성화'}
                        className={`transition-colors ${ticker.daily_alert ? 'text-amber-400 hover:text-amber-300' : 'text-gray-600 hover:text-gray-400'}`}
                      >
                        {ticker.daily_alert ? <Bell size={15} /> : <BellOff size={15} />}
                      </button>
                    )}
                    {!selectMode && (
                      <button
                        onClick={() => navigate(`/tickers/${ticker.id}/thesis`)}
                        className="flex items-center gap-1.5 text-sm text-emerald-400 hover:text-emerald-300 transition-colors"
                      >
                        <Eye size={15} />
                        Thesis
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          }

          return (
            <div className="space-y-6">
              {portfolio.length > 0 && (
                <div>
                  <h2 className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-3">
                    포트폴리오 ({portfolio.length})
                  </h2>
                  <div className="space-y-2">
                    {portfolio.map(t => <TickerCard key={t.id} ticker={t} />)}
                  </div>
                </div>
              )}
              {watchlist.length > 0 && (
                <div>
                  <h2 className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-3">
                    관심 종목 ({watchlist.length})
                  </h2>
                  <div className="space-y-2">
                    {watchlist.map(t => <TickerCard key={t.id} ticker={t} />)}
                  </div>
                </div>
              )}
            </div>
          )
        })()}
      </main>
    </div>
  )
}
