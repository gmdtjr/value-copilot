import type { Ticker, Thesis, FinancialData } from './types'

const BASE = '/api'

export const api = {
  async getTickers(): Promise<Ticker[]> {
    const res = await fetch(`${BASE}/tickers`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  async addTicker(data: { symbol: string; name: string; market: string; status?: string }): Promise<Ticker> {
    const res = await fetch(`${BASE}/tickers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  },

  async getThesis(tickerId: string): Promise<Thesis> {
    const res = await fetch(`${BASE}/thesis/${tickerId}`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  async patchThesis(tickerId: string, data: Partial<Thesis>): Promise<Thesis> {
    const res = await fetch(`${BASE}/thesis/${tickerId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  async confirmThesis(tickerId: string): Promise<Thesis> {
    const res = await fetch(`${BASE}/thesis/${tickerId}/confirm`, {
      method: 'POST',
    })
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  async getDataStatus(tickerId: string): Promise<{
    has_data: boolean
    fetched_at: string | null
    expires_at: string | null
    sec_summaries: number
  }> {
    const res = await fetch(`${BASE}/tickers/${tickerId}/data-status`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  async refreshData(tickerId: string): Promise<void> {
    const res = await fetch(`${BASE}/tickers/${tickerId}/refresh-data`, { method: 'POST' })
    if (!res.ok) throw new Error(await res.text())
  },

  async getFinancialData(tickerId: string): Promise<FinancialData> {
    const res = await fetch(`${BASE}/tickers/${tickerId}/financial-data`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  /**
   * SSE 스트림으로 피드백 기반 Thesis 재생성.
   */
  refineStream(
    tickerId: string,
    feedback: string,
    callbacks: {
      onStart?: (symbol: string) => void
      onChunk: (text: string) => void
      onComplete: (sections: Record<string, string>) => void
      onError: (msg: string) => void
    },
  ): AbortController {
    const controller = new AbortController()

    fetch(`${BASE}/tickers/${tickerId}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback }),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }))
          callbacks.onError(err.detail || `HTTP ${res.status}`)
          return
        }
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })

          const events = buf.split('\n\n')
          buf = events.pop() ?? ''

          for (const evt of events) {
            const line = evt.trim()
            if (!line.startsWith('data:')) continue
            try {
              const payload = JSON.parse(line.slice(5).trim())
              if (payload.type === 'start') callbacks.onStart?.(payload.symbol)
              else if (payload.type === 'chunk') callbacks.onChunk(payload.text)
              else if (payload.type === 'complete') callbacks.onComplete(payload.sections)
              else if (payload.type === 'error') callbacks.onError(payload.message)
            } catch {
              // skip malformed
            }
          }
        }
      })
      .catch((e) => {
        if (e.name !== 'AbortError') callbacks.onError(String(e))
      })

    return controller
  },

  /**
   * SSE 스트림으로 Thesis 생성.
   * onChunk: 실시간 텍스트 청크
   * onComplete: 완성된 4섹션
   * Returns AbortController to cancel.
   */
  analyzeStream(
    tickerId: string,
    callbacks: {
      onStart?: (symbol: string) => void
      onChunk: (text: string) => void
      onComplete: (sections: Record<string, string>) => void
      onError: (msg: string) => void
    },
  ): AbortController {
    const controller = new AbortController()

    fetch(`${BASE}/tickers/${tickerId}/analyze`, {
      method: 'POST',
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          callbacks.onError(`HTTP ${res.status}`)
          return
        }
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buf = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })

          const events = buf.split('\n\n')
          buf = events.pop() ?? ''

          for (const evt of events) {
            const line = evt.trim()
            if (!line.startsWith('data:')) continue
            try {
              const payload = JSON.parse(line.slice(5).trim())
              if (payload.type === 'start') callbacks.onStart?.(payload.symbol)
              else if (payload.type === 'chunk') callbacks.onChunk(payload.text)
              else if (payload.type === 'complete') callbacks.onComplete(payload.sections)
              else if (payload.type === 'error') callbacks.onError(payload.message)
            } catch {
              // skip malformed
            }
          }
        }
      })
      .catch((e) => {
        if (e.name !== 'AbortError') callbacks.onError(String(e))
      })

    return controller
  },
}
