import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, AlertTriangle, CircleDot, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

type CapabilityStatus = 'complete' | 'partial' | 'deferred' | 'missing'

type CapabilityRisk = 'read' | 'local_write' | 'external_read' | 'external_write' | 'destructive'

type Capability = {
  id: string
  domain: string
  summary: string
  risk: CapabilityRisk
  core: string | null
  cli: string | null
  mcp: string | null
  api: string | null
  ui: string | null
  status: CapabilityStatus
  parity_notes?: string
}

type CapabilityManifest = {
  contract: 'capability-manifest'
  contract_version: string
  name: string
  description: string
  generated_at_utc: string
  contracts: Record<string, boolean>
  surfaces: string[]
  capabilities: Capability[]
  summary: Record<'total' | 'complete' | 'partial' | 'deferred' | 'missing', number>
  total?: number
  complete?: number
  partial?: number
  deferred?: number
  missing?: number
}

const SURFACE_LABELS: { key: keyof Pick<Capability, 'core' | 'cli' | 'mcp' | 'api' | 'ui'>; label: string }[] = [
  { key: 'core', label: 'Core' },
  { key: 'cli', label: 'CLI' },
  { key: 'mcp', label: 'MCP' },
  { key: 'api', label: 'API' },
  { key: 'ui', label: 'UI' },
]

function statusTone(status: CapabilityStatus): string {
  if (status === 'complete') return 'border-succes/35 bg-succes/10 text-succes'
  if (status === 'partial') return 'border-alerte/35 bg-alerte/10 text-alerte'
  return 'border-border bg-muted text-muted-foreground'
}

function StatusIcon({ status }: { status: CapabilityStatus }) {
  if (status === 'complete') return <CheckCircle2 className="size-4" />
  if (status === 'partial') return <AlertTriangle className="size-4" />
  return <CircleDot className="size-4" />
}

function SurfacePill({ label, value }: { label: string; value: string | null }) {
  return (
    <div
      className={cn(
        'rounded-lg border px-2 py-1 text-xs',
        value
          ? 'border-border bg-background text-foreground'
          : 'border-dashed border-muted-foreground/30 text-muted-foreground',
      )}
      title={value ?? 'missing'}
    >
      <span className="font-medium">{label}</span>
      <span className="text-muted-foreground ml-1">{value ? '✓' : '—'}</span>
    </div>
  )
}

function countFor(manifest: CapabilityManifest | null, key: 'total' | 'complete' | 'partial' | 'deferred' | 'missing') {
  if (!manifest) return '—'
  return manifest.summary?.[key] ?? manifest[key] ?? '—'
}

export function CapabilitiesView() {
  const [manifest, setManifest] = useState<CapabilityManifest | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/capabilities')
      if (!response.ok) throw new Error(await response.text())
      const payload = (await response.json()) as CapabilityManifest
      if (!Array.isArray(payload.capabilities)) {
        throw new Error('Invalid capabilities manifest: capabilities must be an array')
      }
      setManifest(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [load])

  const domains = useMemo(() => {
    if (!manifest) return []
    return Array.from(new Set(manifest.capabilities.map((capability) => capability.domain))).sort()
  }, [manifest])

  return (
    <section className="space-y-6" data-testid="capabilities-view">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Agent Center</p>
          <h1 className="text-3xl font-semibold tracking-tight">Capabilities</h1>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
            AI-native manifest showing which Zab capabilities are exposed across Core, CLI, MCP, API and UI.
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className={cn('mr-2 size-4', loading ? 'animate-spin' : '')} />
          Refresh
        </Button>
      </div>

      {error ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Unable to load capabilities</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total</CardDescription>
            <CardTitle className="text-3xl" data-testid="capabilities-total">
              {countFor(manifest, 'total')}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Complete</CardDescription>
            <CardTitle className="text-3xl text-succes" data-testid="capabilities-complete">
              {countFor(manifest, 'complete')}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Partial</CardDescription>
            <CardTitle className="text-3xl text-alerte" data-testid="capabilities-partial">
              {countFor(manifest, 'partial')}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Domains</CardDescription>
            <CardTitle className="text-3xl">{domains.length || '—'}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Surface parity matrix</CardTitle>
          <CardDescription>
            Contract: {manifest?.contract ?? 'loading'} v{manifest?.contract_version ?? '—'} · generated{' '}
            {manifest?.generated_at_utc ? new Date(manifest.generated_at_utc).toLocaleString() : '—'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading && !manifest ? <LoadingState compact label="Chargement des capabilities…" /> : null}
          {manifest ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Capability</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Risk</TableHead>
                    <TableHead>Surfaces</TableHead>
                    <TableHead>Notes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {manifest.capabilities.map((capability) => (
                    <TableRow key={capability.id}>
                      <TableCell className="min-w-72 align-top">
                        <div className="font-mono text-sm font-semibold">{capability.id}</div>
                        <div className="text-muted-foreground mt-1 text-xs">{capability.domain} · {capability.summary}</div>
                      </TableCell>
                      <TableCell className="align-top">
                        <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', statusTone(capability.status))}>
                          <StatusIcon status={capability.status} />
                          {capability.status}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono text-xs align-top">{capability.risk}</TableCell>
                      <TableCell className="align-top">
                        <div className="grid min-w-80 grid-cols-5 gap-1">
                          {SURFACE_LABELS.map((surface) => (
                            <SurfacePill key={surface.key} label={surface.label} value={capability[surface.key]} />
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground max-w-xs text-xs align-top">
                        {capability.parity_notes ?? 'All declared surfaces available.'}
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
