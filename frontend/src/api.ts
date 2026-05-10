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

  async confirmThesis(tickerId: string, monitoringContract?: string): Promise<Thesis> {
    const res = await fetch(`${BASE}/thesis/${tickerId}/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ monitoring_contract: monitoringContract ?? null }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  },

  async getThesisVersions(tickerId: string): Promise<Thesis[]> {
    const res = await fetch(`${BASE}/thesis/${tickerId}/versions`)
    if (!res.ok) throw new Error(await res.text())
    return res.json()
  },

  async createNewVersion(tickerId: string): Promise<Thesis> {
    const res = await fetch(`${BASE}/thesis/${tickerId}/new-version`, { method: 'POST' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
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

  async deleteTicker(tickerId: string): Promise<void> {
    const res = await fetch(`${BASE}/tickers/${tickerId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await res.text())
  },

  async resolveValley(tickerId: string): Promise<void> {
    const res = await fetch(`${BASE}/tickers/${tickerId}/resolve-valley`, { method: 'POST' })
    if (!res.ok) throw new Error(await res.text())
  },

  async createThesisDirect(
    tickerId: string,
    data: {
      stock_type: string
      thesis?: string
      risk?: string
      key_assumptions?: string
      valuation?: string
      key_logic?: string
      monitoring_contract?: string
    },
  ): Promise<void> {
    const res = await fetch(`${BASE}/tickers/${tickerId}/thesis/direct`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
  },
}
