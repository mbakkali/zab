export type SystemCheckStatus = 'ok' | 'warn' | 'fail' | 'pending' | 'running'

export type SystemCheckItem = {
  id: string
  label: string
  category: string
  status: SystemCheckStatus
  message: string
  detail?: Record<string, unknown>
}

export type SystemCheckDescriptor = {
  id: string
  label: string
  category: string
}

export type SystemCheckSummary = {
  generated_at_utc: string
  percentage: number
  score: number
  total: number
  ok: number
  warn: number
  fail: number
}

export type SystemCheckReport = SystemCheckSummary & {
  checks: SystemCheckItem[]
}

type StreamHandlers = {
  onRegistry: (items: SystemCheckDescriptor[]) => void
  onCheck: (item: SystemCheckItem) => void
  onDone: (summary: SystemCheckSummary) => void
}

function parseSseBlocks(buffer: string): { events: Array<{ event: string; data: string }>; rest: string } {
  const events: Array<{ event: string; data: string }> = []
  const blocks = buffer.split('\n\n')
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    if (!block.trim()) continue
    let event = 'message'
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7).trim()
      else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
    }
    if (dataLines.length > 0) {
      events.push({ event, data: dataLines.join('\n') })
    }
  }
  return { events, rest }
}

function dispatchSseEvent(event: string, data: string, handlers: StreamHandlers) {
  if (event === 'registry') {
    handlers.onRegistry(JSON.parse(data) as SystemCheckDescriptor[])
    return
  }
  if (event === 'check') {
    handlers.onCheck(JSON.parse(data) as SystemCheckItem)
    return
  }
  if (event === 'done') {
    handlers.onDone(JSON.parse(data) as SystemCheckSummary)
  }
}

async function runSyncFallback(handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  const r = await fetch('/api/system/check', { signal, headers: { Accept: 'application/json' } })
  if (!r.ok) {
    throw new Error((await r.text()) || r.statusText)
  }
  const payload = (await r.json()) as SystemCheckReport
  const checks = payload.checks ?? []
  handlers.onRegistry(
    checks.map((c) => ({
      id: c.id,
      label: c.label,
      category: c.category,
    })),
  )
  for (const chk of checks) {
    handlers.onCheck(chk)
  }
  handlers.onDone({
    generated_at_utc: payload.generated_at_utc,
    percentage: payload.percentage,
    score: payload.score,
    total: payload.total,
    ok: payload.ok,
    warn: payload.warn,
    fail: payload.fail,
  })
}

/** Consomme le flux SSE zab ; retombe sur GET /api/system/check si le stream échoue. */
export async function consumeSystemCheckStream(handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/system/check/stream', {
      signal,
      headers: { Accept: 'text/event-stream' },
    })
  } catch {
    await runSyncFallback(handlers, signal)
    return
  }

  if (!res.ok || !res.body) {
    await runSyncFallback(handlers, signal)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawDone = false

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parsed = parseSseBlocks(buffer)
      buffer = parsed.rest
      for (const block of parsed.events) {
        dispatchSseEvent(block.event, block.data, handlers)
        if (block.event === 'done') sawDone = true
      }
    }
  } catch (err) {
    if (signal?.aborted) return
    if (!sawDone) {
      await runSyncFallback(handlers, signal)
      return
    }
    throw err
  }

  if (!sawDone) {
    const parsed = parseSseBlocks(`${buffer}\n\n`)
    for (const block of parsed.events) {
      dispatchSseEvent(block.event, block.data, handlers)
      if (block.event === 'done') sawDone = true
    }
  }

  if (!sawDone) {
    await runSyncFallback(handlers, signal)
  }
}

export function buildSystemCheckReport(
  summary: SystemCheckSummary,
  checks: Record<string, SystemCheckItem>,
): SystemCheckReport {
  const items = Object.values(checks).filter(
    (c) => c.status === 'ok' || c.status === 'warn' || c.status === 'fail',
  )
  return {
    ...summary,
    checks: items,
  }
}

export function downloadSystemCheckReport(report: SystemCheckReport): void {
  const stamp = report.generated_at_utc.slice(0, 10)
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `zab-system-check-${stamp}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}
