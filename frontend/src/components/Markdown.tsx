import React from 'react'

// ── Inline parser ─────────────────────────────────────────────────────────────

function parseInline(text: string, keyPrefix: string): React.ReactNode {
  const parts: React.ReactNode[] = []
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g
  let last = 0
  let match: RegExpExecArray | null
  let idx = 0
  while ((match = regex.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    const raw = match[0]
    const k = `${keyPrefix}-i${idx++}`
    if (raw.startsWith('**'))
      parts.push(<strong key={k} className="font-semibold text-gray-900 dark:text-white">{raw.slice(2, -2)}</strong>)
    else if (raw.startsWith('*'))
      parts.push(<em key={k} className="italic text-gray-700 dark:text-gray-200">{raw.slice(1, -1)}</em>)
    else
      parts.push(<code key={k} className="bg-gray-100 dark:bg-gray-800 text-emerald-600 dark:text-emerald-300 px-1 py-0.5 rounded text-xs font-mono">{raw.slice(1, -1)}</code>)
    last = match.index + raw.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts.length === 0 ? '' : parts.length === 1 ? parts[0] : <>{parts}</>
}

// ── Table helpers ─────────────────────────────────────────────────────────────

function isTableRow(line: string): boolean {
  const t = line.trim()
  return t.startsWith('|') && t.endsWith('|') && t.length > 2
}

function isSeparatorRow(line: string): boolean {
  return /^\|[\s\-|:]+\|$/.test(line.trim())
}

function splitTableRow(line: string): string[] {
  return line.trim().slice(1, -1).split('|').map((c) => c.trim())
}

function TableBlock({ lines, blockKey }: { lines: string[]; blockKey: string }) {
  // Filter out separator rows; first non-separator row is the header
  const nonSep = lines.filter((l) => !isSeparatorRow(l))
  if (nonSep.length === 0) return null

  const [headerLine, ...dataLines] = nonSep
  const headers = splitTableRow(headerLine)
  const rows = dataLines.map(splitTableRow)

  return (
    <div className="overflow-x-auto my-4 rounded-lg border border-gray-300 dark:border-gray-700">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-200 dark:bg-gray-800/80">
            {headers.map((h, j) => (
              <th
                key={j}
                className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600 dark:text-gray-300 whitespace-nowrap border-b border-gray-300 dark:border-gray-700"
              >
                {parseInline(h, `${blockKey}-h${j}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((cells, ri) => (
            <tr key={ri} className="border-b border-gray-200 dark:border-gray-800 last:border-0 hover:bg-gray-100 dark:hover:bg-gray-800/30 transition-colors">
              {cells.map((cell, ci) => (
                <td key={ci} className="px-4 py-2.5 text-gray-600 dark:text-gray-300 text-sm align-top">
                  {parseInline(cell, `${blockKey}-r${ri}c${ci}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function Markdown({ content, className }: { content: string; className?: string }) {
  if (!content?.trim()) return null

  // Strip XML section tags (e.g. <section name="..."> and </section>)
  const cleaned = content.replace(/<section[^>]*>/g, '').replace(/<\/section>/g, '')

  const elements: React.ReactNode[] = []
  const lines = cleaned.split('\n')
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const key = `${i}`

    // ── Fenced code block ─────────────────────────────────────────────────────
    if (line.trimStart().startsWith('```')) {
      const codeLines: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) {
        codeLines.push(lines[i])
        i++
      }
      i++ // closing ```
      if (codeLines.length > 0) {
        elements.push(
          <pre key={`code-${key}`} className="bg-gray-100 dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-3 my-3 overflow-x-auto text-xs text-gray-600 dark:text-gray-300 font-mono leading-relaxed whitespace-pre-wrap">
            {codeLines.join('\n')}
          </pre>
        )
      }
      continue
    }

    // ── Blockquote ────────────────────────────────────────────────────────────
    if (line.startsWith('> ') || line === '>') {
      const items: string[] = []
      while (i < lines.length && (lines[i].startsWith('> ') || lines[i] === '>')) {
        items.push(lines[i].startsWith('> ') ? lines[i].slice(2) : '')
        i++
      }
      elements.push(
        <blockquote key={`bq-${key}`} className="border-l-2 border-gray-400 dark:border-gray-600 pl-4 my-3 space-y-1">
          {items.map((text, idx) =>
            text
              ? <p key={idx} className="text-gray-500 dark:text-gray-400 text-sm italic leading-relaxed">{parseInline(text, `bq-${key}-${idx}`)}</p>
              : null
          )}
        </blockquote>
      )
      continue
    }

    // ── Table: collect consecutive |rows| with blank lines between them ──────
    if (isTableRow(line)) {
      const tableLines: string[] = []
      while (i < lines.length) {
        if (isTableRow(lines[i])) {
          tableLines.push(lines[i])
          i++
        } else if (
          lines[i].trim() === '' &&
          i + 1 < lines.length &&
          isTableRow(lines[i + 1])
        ) {
          i++ // skip blank between rows
        } else {
          break
        }
      }
      if (tableLines.length >= 1) {
        elements.push(<TableBlock key={`table-${key}`} lines={tableLines} blockKey={key} />)
      }
      continue
    }

    // ── Headings ──────────────────────────────────────────────────────────────
    if (line.startsWith('### ')) {
      elements.push(
        <h3 key={key} className="text-sm font-semibold text-gray-900 dark:text-white mt-5 mb-1.5 first:mt-0">
          {parseInline(line.slice(4), key)}
        </h3>
      )
      i++
    } else if (line.startsWith('## ')) {
      elements.push(
        <h2 key={key} className="text-base font-semibold text-gray-900 dark:text-white mt-6 mb-2 first:mt-0 border-b border-gray-300 dark:border-gray-700 pb-1">
          {parseInline(line.slice(3), key)}
        </h2>
      )
      i++
    } else if (line.startsWith('# ')) {
      elements.push(
        <h1 key={key} className="text-lg font-bold text-gray-900 dark:text-white mt-6 mb-2 first:mt-0">
          {parseInline(line.slice(2), key)}
        </h1>
      )
      i++

    // ── Horizontal rule ───────────────────────────────────────────────────────
    } else if (/^-{3,}$/.test(line.trim())) {
      elements.push(<hr key={key} className="border-gray-300 dark:border-gray-700 my-4" />)
      i++

    // ── Unordered list ────────────────────────────────────────────────────────
    } else if (line.startsWith('- ') || line.startsWith('* ')) {
      const isUL = (l: string) => l.startsWith('- ') || l.startsWith('* ')
      const items: React.ReactNode[] = []
      while (i < lines.length) {
        if (isUL(lines[i])) {
          items.push(
            <li key={i} className="text-gray-600 dark:text-gray-300 text-sm leading-relaxed">
              {parseInline(lines[i].slice(2), `${i}`)}
            </li>
          )
          i++
        } else if (lines[i].trim() === '' && i + 1 < lines.length && isUL(lines[i + 1])) {
          i++ // skip blank between items
        } else {
          break
        }
      }
      elements.push(
        <ul key={`ul-${key}`} className="list-disc list-outside ml-5 space-y-1.5 my-3">
          {items}
        </ul>
      )

    // ── Ordered list ──────────────────────────────────────────────────────────
    } else if (/^\d+\. /.test(line)) {
      const isOL = (l: string) => /^\d+\. /.test(l)
      const items: React.ReactNode[] = []
      while (i < lines.length) {
        if (isOL(lines[i])) {
          items.push(
            <li key={i} className="text-gray-600 dark:text-gray-300 text-sm leading-relaxed">
              {parseInline(lines[i].replace(/^\d+\. /, ''), `${i}`)}
            </li>
          )
          i++
        } else if (lines[i].trim() === '' && i + 1 < lines.length && isOL(lines[i + 1])) {
          i++ // skip blank between items
        } else {
          break
        }
      }
      elements.push(
        <ol key={`ol-${key}`} className="list-decimal list-outside ml-5 space-y-1.5 my-3">
          {items}
        </ol>
      )

    // ── Blank line ────────────────────────────────────────────────────────────
    } else if (line.trim() === '') {
      i++

    // ── Paragraph ─────────────────────────────────────────────────────────────
    } else {
      elements.push(
        <p key={key} className="text-gray-600 dark:text-gray-300 text-sm leading-relaxed mb-2.5">
          {parseInline(line, key)}
        </p>
      )
      i++
    }
  }

  return <div className={`space-y-1 ${className ?? ''}`}>{elements}</div>
}
