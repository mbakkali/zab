import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleDot, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

type SourceStatus = 'ok' | 'local_ok' | 'needs_auth' | 'error' | 'legacy_reference' | 'not_verified' | 'stale'

type SourceHealthRow = {
  id: string
  kind: string
  status: SourceStatus
  freshness: string
  last_checked_at: string
  last_success_at: string | null
  item_count: number | null
  auth: { status: string; secret_names?: string[]; secret_values_exposed: boolean }
  safe_message: string
  warnings: string[]
}

type SourceHealthPayload = {
  contract: 'source-health'
  contract_version: string
  generated_at_utc: string
  refresh: boolean
  status_counts: Record<string, number>
  sources: SourceHealthRow[]
}

function statusTone(status: SourceStatus): string {
  if (status === 'ok' || status === 'local_ok') return 'border-succes/35 bg-succes/10 text-succes'
  if (status === 'needs_auth' || status === 'stale' || status === 'not_verified') return 'border-alerte/35 bg-alerte/10 text-alerte'
  if (status === 'error') return 'border-danger/35 bg-danger/10 text-danger'
  return 'border-border bg-muted text-muted-foreground'
}

function StatusIcon({ status }: { status: SourceStatus }) {
  if (status === 'ok' || status === 'local_ok') return <CheckCircle2 className="size-4" />
  if (status === 'error' || status === 'needs_auth' || status === 'stale') return <AlertTriangle className="size-4" />
  return <CircleDot className="size-4" />
}

export function SourceHealthView() {
  const [payload, setPayload] = useState<SourceHealthPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (refresh = false) => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`/api/source-health${refresh ? '?refresh=true' : ''}`)
      if (!response.ok) throw new Error(await response.text())
      const data = (await response.json()) as SourceHealthPayload
      if (!Array.isArray(data.sources)) throw new Error('Invalid source-health payload')
      setPayload(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(false)
  }, [load])

  const total = payload?.sources.length ?? 0
  const needsAttention = useMemo(() => {
    if (!payload) return 0
    return payload.sources.filter((row) => !['ok', 'local_ok'].includes(row.status)).length
  }, [payload])

  return (
    <section className="space-y-6" data-testid="source-health-view">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Agent Center</p>
          <h1 className="text-3xl font-semibold tracking-tight">Source Health</h1>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
            Availability, freshness and masked auth readiness for the sources used by Zab packets.
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => void load(true)} disabled={loading}>
          <RefreshCw className={cn('mr-2 size-4', loading ? 'animate-spin' : '')} />
          Refresh
        </Button>
      </div>

      {error ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Unable to load Source Health</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total sources</CardDescription>
            <CardTitle className="text-3xl" data-testid="source-health-total">{payload ? total : '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Needs attention</CardDescription>
            <CardTitle className="text-3xl text-alerte" data-testid="source-health-attention">{payload ? needsAttention : '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Generated</CardDescription>
            <CardTitle className="text-sm">{payload?.generated_at_utc ? new Date(payload.generated_at_utc).toLocaleString() : '—'}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Sources</CardTitle>
          <CardDescription>Contract: {payload?.contract ?? 'loading'} v{payload?.contract_version ?? '—'}</CardDescription>
        </CardHeader>
        <CardContent>
          {loading && !payload ? <LoadingState compact label="Chargement de Source Health…" /> : null}
          {payload ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Source</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Freshness</TableHead>
                    <TableHead>Auth</TableHead>
                    <TableHead>Last success</TableHead>
                    <TableHead>Message</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {payload.sources.map((source) => (
                    <TableRow key={source.id}>
                      <TableCell className="align-top">
                        <div className="font-mono text-sm font-semibold">{source.id}</div>
                        <div className="text-muted-foreground mt-1 text-xs">{source.kind} · {source.item_count ?? '—'} items</div>
                      </TableCell>
                      <TableCell className="align-top">
                        <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', statusTone(source.status))}>
                          <StatusIcon status={source.status} />
                          {source.status}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-xs align-top">{source.freshness}</TableCell>
                      <TableCell className="text-xs align-top">
                        <div className="font-mono">{source.auth.status}</div>
                        <div className="text-muted-foreground mt-1">{source.auth.secret_names?.slice(0, 3).join(', ') || '—'}</div>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs align-top">{source.last_success_at ?? '—'}</TableCell>
                      <TableCell className="text-muted-foreground max-w-md text-xs align-top">
                        <div>{source.safe_message}</div>
                        {source.warnings.length ? <div className="mt-1 text-alerte">{source.warnings.slice(0, 2).join(' · ')}</div> : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  )
}
