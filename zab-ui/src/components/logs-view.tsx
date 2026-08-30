import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { Pause, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

type CounterRow = {
  id: string
  count: number
}

type LogFileRow = {
  id: string
  filename: string
  path: string
  exists: boolean
  bytes: number
  updated_at: string | null
}

type LogFilesPayload = {
  log_dir: string
  files: LogFileRow[]
}

type LogEvent = {
  event_id?: string
  ts?: string
  level?: string
  component?: string
  surface?: string
  request_id?: string
  actor?: {
    kind?: string
    id?: string
    client?: string
    source?: string
    pid?: number
    cwd?: string
  }
  request?: {
    name?: string
    method?: string
    path?: string
    tool?: string
    command?: string
    args_redacted?: unknown
    input_hash?: string
  }
  scope?: {
    org?: string | null
    project_id?: string | null
    project_path?: string | null
    task_source_id?: string | null
    resolution?: string | null
  }
  result?: {
    status?: string
    duration_ms?: number
    http_status?: number
    exit_code?: number | null
    error_type?: string
    error_message?: string
  }
  [key: string]: unknown
}

type LogQueryPayload = {
  source?: string
  events: LogEvent[]
  total: number
}

type LogTailPayload = {
  file: string
  path: string
  events: LogEvent[]
}

type LogSummaryPayload = {
  since?: string | null
  source?: string
  total: number
  by_surface: CounterRow[]
  by_component: CounterRow[]
  by_level: CounterRow[]
  by_status: CounterRow[]
  by_actor: CounterRow[]
  by_org: CounterRow[]
  by_project: CounterRow[]
  top_requests: CounterRow[]
  errors: LogEvent[]
}

const LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR']
const SURFACES = ['ALL', 'cli', 'api', 'mcp', 'jobs']
const STATUSES = ['ALL', 'ok', 'error', 'queued', 'running', 'done', 'cancelled']
const LINE_COUNTS = [50, 100, 200, 500]
const INPUT_CLASS = 'border-input bg-background text-foreground h-8 w-full rounded-md border px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/50'
const SINCE = [
  { label: '1h', value: '1h' },
  { label: '6h', value: '6h' },
  { label: '24h', value: '24h' },
  { label: '7d', value: '7d' },
  { label: 'All', value: '' },
]

async function apiJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(await response.text())
  return response.json() as Promise<T>
}

function eventRequestName(event: LogEvent): string {
  return (
    event.request?.name
    || event.request?.tool
    || event.request?.path
    || event.request?.command
    || 'unknown'
  )
}

function formatDate(value?: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function statusTone(status?: string): string {
  const normalized = String(status || '').toLowerCase()
  if (['ok', 'done', 'running', 'queued'].includes(normalized)) {
    return 'border-succes/35 bg-succes/10 text-succes'
  }
  if (['cancelled', 'warning', 'warn'].includes(normalized)) {
    return 'border-alerte/35 bg-alerte/10 text-alerte'
  }
  if (['error', 'fail', 'failed'].includes(normalized)) {
    return 'border-danger/35 bg-danger/10 text-danger'
  }
  return 'border-border bg-muted text-muted-foreground'
}

function levelTone(level?: string): string {
  const normalized = String(level || '').toUpperCase()
  if (normalized === 'ERROR' || normalized === 'CRITICAL') return 'text-danger'
  if (normalized === 'WARNING') return 'text-alerte'
  if (normalized === 'DEBUG') return 'text-muted-foreground'
  return 'text-foreground'
}

function levelRank(level?: string): number {
  return { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 }[String(level || 'INFO').toUpperCase() as 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'] ?? 20
}

function fieldIncludes(value: unknown, needle: string): boolean {
  if (!needle) return true
  return String(value || '').toLowerCase().includes(needle.toLowerCase())
}

function eventMatches(event: LogEvent, filters: LogsFilters): boolean {
  if (filters.level !== 'ALL' && levelRank(event.level) < levelRank(filters.level)) return false
  if (filters.surface !== 'ALL' && !fieldIncludes(event.surface, filters.surface)) return false
  if (filters.status !== 'ALL' && !fieldIncludes(event.result?.status, filters.status)) return false
  if (!fieldIncludes(event.component, filters.component)) return false
  if (!fieldIncludes(event.actor?.id, filters.actor)) return false
  if (!fieldIncludes(event.scope?.org, filters.org)) return false
  if (!fieldIncludes(event.scope?.project_id, filters.project)) return false
  if (filters.q.trim()) {
    const haystack = JSON.stringify(event).toLowerCase()
    if (!haystack.includes(filters.q.trim().toLowerCase())) return false
  }
  return true
}

type LogsFilters = {
  file: string
  lines: number
  level: string
  component: string
  surface: string
  actor: string
  org: string
  project: string
  status: string
  q: string
  since: string
}

const DEFAULT_FILTERS: LogsFilters = {
  file: 'requests',
  lines: 100,
  level: 'ALL',
  component: '',
  surface: 'ALL',
  actor: '',
  org: '',
  project: '',
  status: 'ALL',
  q: '',
  since: '24h',
}

function appendParam(params: URLSearchParams, key: string, value: string | number | undefined): void {
  if (value === undefined || value === '' || value === 'ALL') return
  params.set(key, String(value))
}

function TopList({ title, rows }: { title: string; rows: CounterRow[] }) {
  return (
    <Card size="sm">
      <CardHeader className="pb-1">
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {(rows || []).slice(0, 5).map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 text-xs">
              <span className="min-w-0 truncate font-mono">{row.id}</span>
              <span className="text-muted-foreground shrink-0">{row.count}</span>
            </div>
          ))}
          {!rows?.length ? <div className="text-muted-foreground text-xs">-</div> : null}
        </div>
      </CardContent>
    </Card>
  )
}

export function LogsView() {
  const [filters, setFilters] = useState<LogsFilters>(DEFAULT_FILTERS)
  const [files, setFiles] = useState<LogFileRow[]>([])
  const [events, setEvents] = useState<LogEvent[]>([])
  const [summary, setSummary] = useState<LogSummaryPayload | null>(null)
  const [source, setSource] = useState<string>('-')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const summaryParams = new URLSearchParams()
      if (filters.since) summaryParams.set('since', filters.since)
      const [filesPayload, summaryPayload] = await Promise.all([
        apiJson<LogFilesPayload>('/api/logs/files'),
        apiJson<LogSummaryPayload>(`/api/logs/summary${summaryParams.toString() ? `?${summaryParams}` : ''}`),
      ])
      setFiles(filesPayload.files || [])
      setSummary(summaryPayload)

      if (filters.file === 'requests') {
        const params = new URLSearchParams()
        appendParam(params, 'limit', filters.lines)
        appendParam(params, 'level', filters.level)
        appendParam(params, 'component', filters.component)
        appendParam(params, 'surface', filters.surface)
        appendParam(params, 'actor', filters.actor)
        appendParam(params, 'org', filters.org)
        appendParam(params, 'project', filters.project)
        appendParam(params, 'status', filters.status)
        appendParam(params, 'q', filters.q)
        appendParam(params, 'since', filters.since)
        const payload = await apiJson<LogQueryPayload>(`/api/logs/events?${params}`)
        setEvents(payload.events || [])
        setSource(payload.source || 'events')
      } else {
        const params = new URLSearchParams({ file: filters.file, lines: String(filters.lines) })
        const payload = await apiJson<LogTailPayload>(`/api/logs/tail?${params}`)
        setEvents((payload.events || []).filter((event) => eventMatches(event, filters)).slice(0, filters.lines))
        setSource(`tail:${payload.file}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!autoRefresh) return undefined
    const id = window.setInterval(() => void load(), 5000)
    return () => window.clearInterval(id)
  }, [autoRefresh, load])

  const errorCount = useMemo(() => summary?.errors?.length ?? events.filter((event) => {
    const status = String(event.result?.status || '').toLowerCase()
    return ['error', 'fail', 'failed'].includes(status) || ['ERROR', 'CRITICAL'].includes(String(event.level || '').toUpperCase())
  }).length, [events, summary])
  const topSurface = summary?.by_surface?.[0]?.id ?? '-'
  const topActor = summary?.by_actor?.[0]?.id ?? '-'

  const updateFilter = <K extends keyof LogsFilters>(key: K, value: LogsFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value }))
  }

  if (loading && events.length === 0 && !summary) {
    return (
      <section className="space-y-6" data-testid="logs-view">
        <LoadingState label="Chargement des logs…" />
      </section>
    )
  }

  return (
    <section className="space-y-6" data-testid="logs-view">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Observability</p>
          <h1 className="text-3xl font-semibold tracking-tight">Logs</h1>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
            CLI, API, MCP and job request events with actor and project attribution.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="border-border bg-background inline-flex h-8 items-center gap-2 rounded-md border px-2 text-xs">
            <input
              data-testid="logs-auto-refresh"
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.currentTarget.checked)}
            />
            {autoRefresh ? <Pause className="size-3.5" /> : <RefreshCw className="size-3.5" />}
            Auto-refresh
          </label>
          <Button type="button" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={cn('mr-2 size-4', loading ? 'animate-spin' : '')} />
            Refresh
          </Button>
        </div>
      </div>

      {error ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Unable to load logs</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Events</CardDescription>
            <CardTitle className="text-3xl" data-testid="logs-total">{summary?.total ?? events.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Errors</CardDescription>
            <CardTitle className="text-3xl text-danger" data-testid="logs-errors">{errorCount}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Top surface</CardDescription>
            <CardTitle className="truncate text-sm font-mono">{topSurface}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Top actor</CardDescription>
            <CardTitle className="truncate text-sm font-mono">{topActor}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>{source} - {events.length} visible event(s)</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-6">
            <Field label="File">
              <select className={INPUT_CLASS} value={filters.file} onChange={(event) => updateFilter('file', event.currentTarget.value)}>
                {files.length ? files.map((file) => (
                  <option key={file.id} value={file.id}>{file.id}</option>
                )) : ['requests', 'cli', 'api', 'mcp', 'jobs', 'errors'].map((file) => (
                  <option key={file} value={file}>{file}</option>
                ))}
              </select>
            </Field>
            <Field label="Level">
              <select className={INPUT_CLASS} value={filters.level} onChange={(event) => updateFilter('level', event.currentTarget.value)}>
                {LEVELS.map((level) => <option key={level} value={level}>{level}</option>)}
              </select>
            </Field>
            <Field label="Surface">
              <select
                data-testid="logs-filter-surface"
                className={INPUT_CLASS}
                value={filters.surface}
                onChange={(event) => updateFilter('surface', event.currentTarget.value)}
              >
                {SURFACES.map((surface) => <option key={surface} value={surface}>{surface}</option>)}
              </select>
            </Field>
            <Field label="Status">
              <select className={INPUT_CLASS} value={filters.status} onChange={(event) => updateFilter('status', event.currentTarget.value)}>
                {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
              </select>
            </Field>
            <Field label="Lines">
              <select className={INPUT_CLASS} value={filters.lines} onChange={(event) => updateFilter('lines', Number(event.currentTarget.value))}>
                {LINE_COUNTS.map((count) => <option key={count} value={count}>{count}</option>)}
              </select>
            </Field>
            <Field label="Since">
              <select className={INPUT_CLASS} value={filters.since} onChange={(event) => updateFilter('since', event.currentTarget.value)}>
                {SINCE.map((item) => <option key={item.label} value={item.value}>{item.label}</option>)}
              </select>
            </Field>
            <Field label="Component">
              <input className={INPUT_CLASS} value={filters.component} onChange={(event) => updateFilter('component', event.currentTarget.value)} />
            </Field>
            <Field label="Actor">
              <input className={INPUT_CLASS} value={filters.actor} onChange={(event) => updateFilter('actor', event.currentTarget.value)} />
            </Field>
            <Field label="Org">
              <input className={INPUT_CLASS} value={filters.org} onChange={(event) => updateFilter('org', event.currentTarget.value)} />
            </Field>
            <Field label="Project">
              <input className={INPUT_CLASS} value={filters.project} onChange={(event) => updateFilter('project', event.currentTarget.value)} />
            </Field>
            <Field label="Search" className="md:col-span-2">
              <div className="relative">
                <Search className="text-muted-foreground pointer-events-none absolute top-2 left-2 size-4" />
                <input
                  className={cn(INPUT_CLASS, 'pl-8')}
                  value={filters.q}
                  onChange={(event) => updateFilter('q', event.currentTarget.value)}
                />
              </div>
            </Field>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-4">
        <TopList title="Requests" rows={summary?.top_requests || []} />
        <TopList title="Components" rows={summary?.by_component || []} />
        <TopList title="Actors" rows={summary?.by_actor || []} />
        <TopList title="Organizations" rows={summary?.by_org || []} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
          <CardDescription>{loading ? 'Loading...' : `${events.length} row(s)`}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Level</TableHead>
                <TableHead>Surface</TableHead>
                <TableHead>Request</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Scope</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!events.length && !loading ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-muted-foreground py-8 text-center">No events</TableCell>
                </TableRow>
              ) : null}
              {events.map((event, index) => (
                <TableRow key={event.event_id || `${event.ts}-${index}`}>
                  <TableCell className="text-muted-foreground font-mono text-xs align-top">{formatDate(event.ts)}</TableCell>
                  <TableCell className={cn('font-mono text-xs align-top', levelTone(event.level))}>{event.level || 'INFO'}</TableCell>
                  <TableCell className="font-mono text-xs align-top">{event.surface || '-'}</TableCell>
                  <TableCell className="align-top">
                    <div className="max-w-xs truncate font-mono text-xs font-semibold">{eventRequestName(event)}</div>
                    <div className="text-muted-foreground mt-1 max-w-xs truncate text-xs">{event.component || '-'}</div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="max-w-[10rem] truncate font-mono text-xs">{event.actor?.id || '-'}</div>
                    <div className="text-muted-foreground mt-1 text-xs">{event.actor?.kind || '-'}</div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="max-w-[10rem] truncate font-mono text-xs">{event.scope?.project_id || event.scope?.org || '-'}</div>
                    <div className="text-muted-foreground mt-1 max-w-[10rem] truncate text-xs">{event.scope?.resolution || '-'}</div>
                  </TableCell>
                  <TableCell className="align-top">
                    <span className={cn('inline-flex rounded-full border px-2 py-1 text-xs font-medium', statusTone(event.result?.status))}>
                      {event.result?.status || '-'}
                    </span>
                    {event.result?.duration_ms != null ? (
                      <div className="text-muted-foreground mt-1 font-mono text-xs">{event.result.duration_ms} ms</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="min-w-[18rem] align-top">
                    <details className="rounded-md border bg-muted/20 p-2 text-xs">
                      <summary className="cursor-pointer select-none font-medium">JSON</summary>
                      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px]">
                        {JSON.stringify(event, null, 2)}
                      </pre>
                    </details>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  )
}

function Field({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <label className={cn('space-y-1 text-xs font-medium', className)}>
      <span className="text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}
