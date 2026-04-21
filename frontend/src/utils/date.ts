const KST = { timeZone: 'Asia/Seoul' } as const

export function fmtKST(dateStr: string | null | undefined, mode: 'datetime' | 'date' | 'time' = 'datetime'): string {
  if (!dateStr) return '–'
  // Append Z if no timezone info so the string is parsed as UTC, not local time
  const normalized = /[Z+\-]\d{2}:?\d{2}$/.test(dateStr) || dateStr.endsWith('Z') ? dateStr : dateStr + 'Z'
  const d = new Date(normalized)
  if (mode === 'date') return d.toLocaleDateString('ko-KR', KST)
  if (mode === 'time') return d.toLocaleTimeString('ko-KR', { ...KST, hour: '2-digit', minute: '2-digit' })
  return d.toLocaleString('ko-KR', KST)
}
