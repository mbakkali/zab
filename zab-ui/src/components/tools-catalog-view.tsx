import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleDot, Copy, Pencil, RefreshCw, Save, X, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

type ToolStatus = 'ok' | 'warn' | 'fail' | 'skipped'

type ToolIssue = {
  tool_id: string
  severity: 'error' | 'warn'
  code: string
  message: string
}

type ToolSkillRef = {
  id: string
  found: boolean
  path?: string | null
  org?: string | null
  project?: string | null
}

type ToolImplementation = {
  id?: string
  kind?: string
  provider?: string
  role?: string
  priority?: number
  coverage?: string
  command?: string
  fallback_when?: string[]
}

type ToolsCatalogTool = {
  id: string
  label: string
  kind: string
  coverage?: string
  status: ToolStatus
  safety?: string
  notes?: string | null
  keywords?: string[]
  examples?: string[]
  commands?: string[]
  providers?: string[]
  origin?: string
  origin_refs?: { section?: string; key?: string }[]
  skill_refs?: string[]
  linked_skills?: ToolSkillRef[]
  implementations?: ToolImplementation[]
  primary?: string
  fallback?: string
  has_fallback?: boolean
  availability_tag?: string
  status_reason?: string
  last_checked_at_utc?: string
  primary_implementation_id?: string | null
  fallback_implementation_ids?: string[]
  validation_issues?: ToolIssue[]
}

type ToolsCatalogPayload = {
  contract: 'tools-catalog'
  contract_version: string
  generated_at_utc: string
  annotations_path: string
  duplicate_ids: string[]
  summary: {
    total: number
    ok: number
    warn: number
    fail: number
    skipped: number
    kinds: Record<string, number>
    providers: Record<string, number>
    with_skill_refs: number
    with_fallback: number
  }
  tools: ToolsCatalogTool[]
}

type ToolsValidationPayload = {
  contract: string
  contract_version: string
  generated_at_utc: string
  strict: boolean
  summary: {
    total_tools: number
    errors: number
    warnings: number
    broken_skill_refs: number
    invalid_ids: number
    unsafe_commands: number
  }
  issues: ToolIssue[]
}

type ToolCheckEntry = {
  id: string
  status: ToolStatus
  message: string
  detail?: Record<string, unknown>
}

type ToolCheckResult = {
  tool_id: string
  label?: string
  status: ToolStatus
  availability_tag?: string
  status_reason?: string
  checks: ToolCheckEntry[]
  refreshed?: boolean
  last_checked_at_utc?: string
}

type ToolEditForm = {
  label: string
  kind: string
  coverage: string
  safety: string
  notes: string
  keywords: string
  examples: string
  skill_refs: string
  commands: string
}

function linesToList(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

function statusTone(status: ToolStatus): string {
  if (status === 'ok') return 'border-succes/35 bg-succes/10 text-succes'
  if (status === 'warn') return 'border-alerte/35 bg-alerte/10 text-alerte'
  if (status === 'fail') return 'border-danger/35 bg-danger/10 text-danger'
  return 'border-border bg-muted text-muted-foreground'
}

function StatusIcon({ status }: { status: ToolStatus }) {
  if (status === 'ok') return <CheckCircle2 className="size-4" />
  if (status === 'warn') return <AlertTriangle className="size-4" />
  if (status === 'fail') return <XCircle className="size-4" />
  return <CircleDot className="size-4" />
}

function countLabel(value: number | undefined | null): string {
  return typeof value === 'number' ? String(value) : '—'
}

const IMPL_KIND_LABELS: Record<string, string> = {
  mcp: 'MCP',
  api: 'API call',
  'api+skill': 'API + skill',
  cli: 'CLI',
  composio: 'Composio',
  channel: 'Channel',
  memory: 'Memory',
}

function implKindLabel(kind?: string | null): string {
  const key = (kind ?? '').trim().toLowerCase()
  if (!key) return '—'
  return IMPL_KIND_LABELS[key] ?? key
}

function implKindTone(kind?: string | null): string {
  const key = (kind ?? '').trim().toLowerCase()
  if (key === 'mcp') return 'border-border bg-muted text-foreground'
  if (key === 'api' || key === 'api+skill') return 'border-info/35 bg-info/10 text-info'
  if (key === 'cli') return 'border-border bg-muted text-foreground'
  if (key === 'composio') return 'border-alerte/35 bg-alerte/10 text-alerte'
  if (key === 'channel') return 'border-succes/35 bg-succes/10 text-succes'
  if (key === 'memory') return 'border-info/35 bg-info/10 text-info'
  return 'border-border bg-muted text-muted-foreground'
}

function primaryImplementation(tool: ToolsCatalogTool): ToolImplementation | undefined {
  const impls = tool.implementations ?? []
  if (!impls.length) return undefined
  if (tool.primary_implementation_id) {
    const match = impls.find((impl) => impl.id === tool.primary_implementation_id)
    if (match) return match
  }
  const nonFallback = impls.filter((impl) => (impl.role ?? 'primary') !== 'fallback')
  const pool = nonFallback.length ? nonFallback : impls
  return [...pool].sort((a, b) => (a.priority ?? 50) - (b.priority ?? 50))[0]
}

function fallbackKinds(tool: ToolsCatalogTool, primaryKind?: string | null): string[] {
  const primary = (primaryKind ?? '').trim().toLowerCase()
  const seen = new Set<string>()
  const out: string[] = []
  for (const impl of tool.implementations ?? []) {
    const key = (impl.kind ?? '').trim().toLowerCase()
    if (!key || key === primary || seen.has(key)) continue
    seen.add(key)
    out.push(key)
  }
  return out
}

type ToolsCatalogViewProps = {
  initialToolId?: string | null
}

export function ToolsCatalogView({ initialToolId }: ToolsCatalogViewProps = {}) {
  const [catalog, setCatalog] = useState<ToolsCatalogPayload | null>(null)
  const [validation, setValidation] = useState<ToolsValidationPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | ToolStatus>('all')
  const [selectedToolId, setSelectedToolId] = useState<string | null>(initialToolId ?? null)
  const [checkResult, setCheckResult] = useState<ToolCheckResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editForm, setEditForm] = useState<ToolEditForm | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [catalogResp, validationResp] = await Promise.all([
        fetch('/api/tools/catalog'),
        fetch('/api/tools/validate'),
      ])
      if (!catalogResp.ok) throw new Error(await catalogResp.text())
      const catalogPayload = (await catalogResp.json()) as ToolsCatalogPayload
      if (!Array.isArray(catalogPayload.tools)) throw new Error('Invalid tools catalog payload')
      setCatalog(catalogPayload)

      if (validationResp.ok) {
        const validationPayload = (await validationResp.json()) as ToolsValidationPayload
        setValidation(validationPayload)
      } else {
        setValidation(null)
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      toast.error(message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (initialToolId) setSelectedToolId(initialToolId)
  }, [initialToolId])

  const filtered = useMemo(() => {
    const rows = catalog?.tools ?? []
    const q = query.trim().toLowerCase()
    return rows.filter((tool) => {
      if (statusFilter !== 'all' && tool.status !== statusFilter) return false
      if (!q) return true
      const hay = [
        tool.id,
        tool.label,
        tool.kind,
        tool.coverage,
        tool.safety,
        tool.status,
        tool.status_reason,
        ...(tool.keywords ?? []),
        ...(tool.examples ?? []),
        ...(tool.commands ?? []),
        ...(tool.skill_refs ?? []),
        ...(tool.providers ?? []),
        ...(tool.origin ? [tool.origin] : []),
        ...(tool.implementations ?? []).map((impl) => impl.kind ?? ''),
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return q.split(/\s+/).filter(Boolean).every((term) => hay.includes(term))
    })
  }, [catalog, query, statusFilter])

  const selectedTool = useMemo(
    () => filtered.find((tool) => tool.id === selectedToolId) ?? catalog?.tools.find((tool) => tool.id === selectedToolId) ?? null,
    [catalog, filtered, selectedToolId],
  )
  const selectedValidationIssues = useMemo(
    () => (selectedTool ? (validation?.issues ?? []).filter((issue) => issue.tool_id === selectedTool.id) : []),
    [selectedTool, validation],
  )

  useEffect(() => {
    setCheckResult(null)
    setEditing(false)
    setEditForm(null)
  }, [selectedToolId])

  const patchCatalogTool = useCallback((toolId: string, patch: Partial<ToolsCatalogTool>) => {
    setCatalog((prev) => (prev ? { ...prev, tools: prev.tools.map((t) => (t.id === toolId ? { ...t, ...patch } : t)) } : prev))
  }, [])

  const replaceCatalogTool = useCallback((tool: ToolsCatalogTool) => {
    setCatalog((prev) => (prev ? { ...prev, tools: prev.tools.map((t) => (t.id === tool.id ? tool : t)) } : prev))
  }, [])

  const recheckTool = useCallback(
    async (toolId: string) => {
      setChecking(true)
      try {
        const resp = await fetch(`/api/tools/check?tool_id=${encodeURIComponent(toolId)}&refresh=true`)
        if (!resp.ok) throw new Error(await resp.text())
        const data = (await resp.json()) as ToolCheckResult
        setCheckResult(data)
        patchCatalogTool(toolId, {
          status: data.status,
          status_reason: data.status_reason,
          availability_tag: data.availability_tag,
          last_checked_at_utc: data.last_checked_at_utc,
        })
        toast.success(`Recheck ${toolId} : ${data.status}`)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err))
      } finally {
        setChecking(false)
      }
    },
    [patchCatalogTool],
  )

  const startEdit = useCallback((tool: ToolsCatalogTool) => {
    setEditForm({
      label: tool.label ?? '',
      kind: tool.kind ?? '',
      coverage: tool.coverage ?? '',
      safety: tool.safety ?? '',
      notes: tool.notes ?? '',
      keywords: (tool.keywords ?? []).join('\n'),
      examples: (tool.examples ?? []).join('\n'),
      skill_refs: (tool.skill_refs ?? []).join('\n'),
      commands: (tool.commands ?? []).join('\n'),
    })
    setCheckResult(null)
    setEditing(true)
  }, [])

  const saveEdit = useCallback(
    async (toolId: string, form: ToolEditForm) => {
      setSaving(true)
      try {
        const body = {
          label: form.label.trim(),
          kind: form.kind.trim(),
          coverage: form.coverage.trim(),
          safety: form.safety.trim(),
          notes: form.notes,
          keywords: linesToList(form.keywords),
          examples: linesToList(form.examples),
          skill_refs: linesToList(form.skill_refs),
          commands: linesToList(form.commands),
        }
        const resp = await fetch(`/api/tools/${encodeURIComponent(toolId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (!resp.ok) throw new Error(await resp.text())
        const data = (await resp.json()) as { tool: ToolsCatalogTool }
        if (data.tool) replaceCatalogTool(data.tool)
        setEditing(false)
        toast.success('Tool mis à jour')
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err))
      } finally {
        setSaving(false)
      }
    },
    [replaceCatalogTool],
  )

  const duplicateIds = catalog?.duplicate_ids ?? []
  const summary = catalog?.summary
  const validationSummary = validation?.summary
  const visibleKinds = useMemo(() => {
    const counts = catalog?.summary?.kinds ?? {}
    return Object.entries(counts)
      .filter(([, value]) => typeof value === 'number' && value > 0)
      .sort(([a], [b]) => a.localeCompare(b))
  }, [catalog])

  if (loading && !catalog) {
    return (
      <section className="space-y-6" data-testid="tools-catalog-view">
        <LoadingState label="Chargement du Tools Catalog…" />
      </section>
    )
  }

  return (
    <section className="space-y-6" data-testid="tools-catalog-view">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Agent Center</p>
          <h1 className="text-3xl font-semibold tracking-tight">Tools Catalog</h1>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
            Actionable capabilities Zab can search, inspect and validate from any workspace.
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
            <CardTitle>Unable to load tools catalog</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Total tools</CardDescription>
            <CardTitle className="text-3xl" data-testid="tools-total">{countLabel(summary?.total)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Healthy</CardDescription>
            <CardTitle className="text-3xl text-succes" data-testid="tools-ok">{countLabel(summary?.ok)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Warnings</CardDescription>
            <CardTitle className="text-3xl text-alerte" data-testid="tools-warn">{countLabel(summary?.warn)}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Failures</CardDescription>
            <CardTitle className="text-3xl text-danger" data-testid="tools-fail">{countLabel(summary?.fail)}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader className="space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <CardTitle>Catalog summary</CardTitle>
              <CardDescription>
                Contract: {catalog?.contract ?? 'loading'} v{catalog?.contract_version ?? '—'} · generated{' '}
                {catalog?.generated_at_utc ? new Date(catalog.generated_at_utc).toLocaleString() : '—'}
              </CardDescription>
            </div>
            <div className="text-muted-foreground text-xs">
              <div>Annotations: <code className="font-mono">{catalog?.annotations_path ?? '—'}</code></div>
              <div>Linked skills: {countLabel(summary?.with_skill_refs)} · fallbacks: {countLabel(summary?.with_fallback)}</div>
              {visibleKinds.length ? (
                <div>Kinds: {visibleKinds.map(([kind, count]) => `${kind}=${count}`).join(' · ')}</div>
              ) : null}
            </div>
          </div>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by tool, skill, command, provider…"
              className="border-input bg-background min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm outline-none transition focus:ring-2 focus:ring-ring/40"
            />
            <div className="flex flex-wrap gap-2">
              {(['all', 'ok', 'warn', 'fail', 'skipped'] as const).map((status) => (
                <Button
                  key={status}
                  type="button"
                  size="sm"
                  variant={statusFilter === status ? 'default' : 'outline'}
                  onClick={() => setStatusFilter(status)}
                >
                  {status.toUpperCase()}
                </Button>
              ))}
            </div>
          </div>
          {duplicateIds.length > 0 ? (
            <div className="rounded-md border border-alerte/35 bg-alerte/10 px-3 py-2 text-xs text-alerte">
              Duplicate ids: {duplicateIds.join(', ')}
            </div>
          ) : null}
          {validationSummary ? (
            <div className="rounded-md border border-border bg-muted px-3 py-2 text-xs text-foreground">
              Validation: {validationSummary.errors} errors · {validationSummary.warnings} warnings ·{' '}
              {validationSummary.unsafe_commands} unsafe command(s)
            </div>
          ) : null}
        </CardHeader>
        <CardContent>
          {loading && !catalog ? <p className="text-muted-foreground text-sm">Loading tools catalog…</p> : null}
          {catalog ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tool</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Primary</TableHead>
                    <TableHead>Skills</TableHead>
                    <TableHead>Origin</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((tool) => {
                    const primaryImpl = primaryImplementation(tool)
                    const primaryKind = primaryImpl?.kind
                    const otherKinds = fallbackKinds(tool, primaryKind)
                    return (
                    <TableRow
                      key={tool.id}
                      className="cursor-pointer"
                      onClick={() => setSelectedToolId(tool.id)}
                    >
                      <TableCell className="align-top">
                        <div className="font-mono text-sm font-semibold">{tool.label}</div>
                        <div className="text-muted-foreground mt-1 text-xs">{tool.id} · {tool.kind}</div>
                      </TableCell>
                      <TableCell className="align-top text-xs">
                        <span className={cn('inline-flex items-center rounded-full border px-2 py-1 font-medium', implKindTone(primaryKind))}>
                          {implKindLabel(primaryKind)}
                        </span>
                        {otherKinds.length ? (
                          <div className="text-muted-foreground mt-1 flex flex-wrap gap-1">
                            {otherKinds.map((kind) => (
                              <span key={kind} className="bg-muted rounded-full px-2 py-0.5 text-[10px]">
                                {implKindLabel(kind)}
                              </span>
                            ))}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="align-top">
                        <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', statusTone(tool.status))}>
                          <StatusIcon status={tool.status} />
                          {tool.status}
                        </span>
                        <div className="text-muted-foreground mt-1 text-[11px]">{tool.availability_tag ?? '—'}</div>
                      </TableCell>
                      <TableCell className="align-top text-xs">
                        <div className="font-mono">{tool.primary ?? '—'}</div>
                        <div className="text-muted-foreground mt-1">{tool.fallback ?? '—'}</div>
                      </TableCell>
                      <TableCell className="align-top text-xs">
                        <div className="flex flex-wrap gap-1">
                          {(tool.skill_refs ?? []).slice(0, 4).map((ref) => (
                            <span key={ref} className="bg-muted rounded-full px-2 py-0.5 font-mono text-[10px]">
                              {ref}
                            </span>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="align-top text-xs">
                        <div>{tool.origin ?? 'local'}</div>
                        {tool.providers?.length ? (
                          <div className="text-muted-foreground mt-1">{tool.providers.join(', ')}</div>
                        ) : null}
                      </TableCell>
                    </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
              {!filtered.length ? (
                <p className="text-muted-foreground mt-4 text-sm">No tools matched the current filters.</p>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={Boolean(selectedTool)} onOpenChange={(open) => !open && setSelectedToolId(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-4xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <span>{selectedTool?.label ?? 'Tool detail'}</span>
              {selectedTool ? (
                <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', statusTone(selectedTool.status))}>
                  <StatusIcon status={selectedTool.status} />
                  {selectedTool.status}
                </span>
              ) : null}
            </DialogTitle>
            <DialogDescription>
              {selectedTool?.id ?? '—'} · {selectedTool?.kind ?? '—'} · {selectedTool?.coverage ?? '—'}
            </DialogDescription>
          </DialogHeader>

          {selectedTool ? (
            <div className="space-y-4 text-sm">
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="default"
                  onClick={() => void recheckTool(selectedTool.id)}
                  disabled={checking}
                >
                  <RefreshCw className={cn('mr-1.5 size-4', checking ? 'animate-spin' : '')} />
                  Re-vérifier
                </Button>
                {editing ? (
                  <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                    <X className="mr-1.5 size-4" />
                    Annuler
                  </Button>
                ) : (
                  <Button type="button" size="sm" variant="outline" onClick={() => startEdit(selectedTool)}>
                    <Pencil className="mr-1.5 size-4" />
                    Éditer
                  </Button>
                )}
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void navigator.clipboard
                      .writeText(selectedTool.id)
                      .then(() => toast.success('Tool id copied'))
                      .catch(() => toast.error('Copy failed'))
                  }}
                >
                  <Copy className="mr-1.5 size-4" />
                  Copy id
                </Button>
                {selectedTool.commands?.[0] ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(selectedTool.commands?.join('\n') ?? '')
                        .then(() => toast.success('Commands copied'))
                        .catch(() => toast.error('Copy failed'))
                    }}
                  >
                    <Copy className="mr-1.5 size-4" />
                    Copy commands
                  </Button>
                ) : null}
              </div>

              {checkResult ? (
                <Card className="border-info/35">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base flex items-center gap-2">
                      <span>Recheck</span>
                      <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', statusTone(checkResult.status))}>
                        <StatusIcon status={checkResult.status} />
                        {checkResult.status}
                      </span>
                    </CardTitle>
                    <CardDescription>
                      {checkResult.status_reason ?? '—'}
                      {checkResult.last_checked_at_utc ? ` · ${new Date(checkResult.last_checked_at_utc).toLocaleTimeString()}` : ''}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-1 text-xs">
                    {(checkResult.checks ?? []).map((entry) => (
                      <div key={entry.id} className="flex items-start gap-2">
                        <span className={statusTone(entry.status).split(' ').find((c) => c.startsWith('text-')) ?? ''}>
                          <StatusIcon status={entry.status} />
                        </span>
                        <span>
                          <code className="font-mono">{entry.id}</code>
                          <span className="text-muted-foreground"> — {entry.message}</span>
                        </span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              ) : null}

              {editing && editForm ? (
                <Card className="border-alerte/35">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Éditer le tool</CardTitle>
                    <CardDescription>
                      Enregistré dans <code className="font-mono">~/.config/zab/tools.yaml</code>. Les listes (mots-clés,
                      exemples, skills, commandes) sont <strong>ajoutées</strong> aux valeurs par défaut du tool.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3 text-xs">
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="space-y-1">
                        <span className="text-muted-foreground">Label</span>
                        <input
                          className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                          value={editForm.label}
                          onChange={(e) => setEditForm({ ...editForm, label: e.target.value })}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-muted-foreground">Kind</span>
                        <input
                          className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                          value={editForm.kind}
                          onChange={(e) => setEditForm({ ...editForm, kind: e.target.value })}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-muted-foreground">Coverage</span>
                        <input
                          className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                          value={editForm.coverage}
                          onChange={(e) => setEditForm({ ...editForm, coverage: e.target.value })}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-muted-foreground">Safety</span>
                        <input
                          className="border-input bg-background w-full rounded-md border px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                          value={editForm.safety}
                          onChange={(e) => setEditForm({ ...editForm, safety: e.target.value })}
                        />
                      </label>
                    </div>
                    <label className="space-y-1 block">
                      <span className="text-muted-foreground">Notes</span>
                      <Textarea
                        value={editForm.notes}
                        onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                        className="text-xs min-h-16"
                      />
                    </label>
                    <div className="grid gap-3 md:grid-cols-2">
                      <label className="space-y-1 block">
                        <span className="text-muted-foreground">Mots-clés (1 par ligne)</span>
                        <Textarea
                          value={editForm.keywords}
                          onChange={(e) => setEditForm({ ...editForm, keywords: e.target.value })}
                          className="font-mono text-xs min-h-24"
                        />
                      </label>
                      <label className="space-y-1 block">
                        <span className="text-muted-foreground">Skills liés (1 par ligne)</span>
                        <Textarea
                          value={editForm.skill_refs}
                          onChange={(e) => setEditForm({ ...editForm, skill_refs: e.target.value })}
                          className="font-mono text-xs min-h-24"
                        />
                      </label>
                      <label className="space-y-1 block">
                        <span className="text-muted-foreground">Exemples (1 par ligne)</span>
                        <Textarea
                          value={editForm.examples}
                          onChange={(e) => setEditForm({ ...editForm, examples: e.target.value })}
                          className="text-xs min-h-24"
                        />
                      </label>
                      <label className="space-y-1 block">
                        <span className="text-muted-foreground">Commandes (1 par ligne)</span>
                        <Textarea
                          value={editForm.commands}
                          onChange={(e) => setEditForm({ ...editForm, commands: e.target.value })}
                          className="font-mono text-xs min-h-24"
                        />
                      </label>
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button type="button" size="sm" variant="outline" onClick={() => setEditing(false)} disabled={saving}>
                        Annuler
                      </Button>
                      <Button type="button" size="sm" onClick={() => void saveEdit(selectedTool.id, editForm)} disabled={saving}>
                        <Save className={cn('mr-1.5 size-4', saving ? 'animate-pulse' : '')} />
                        Enregistrer
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ) : null}

              {selectedTool.status_reason ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Status reason</CardTitle>
                  </CardHeader>
                  <CardContent className="text-muted-foreground text-sm">
                    {selectedTool.status_reason}
                  </CardContent>
                </Card>
              ) : null}

              <div className="grid gap-3 md:grid-cols-2">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Primary</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 text-xs">
                    <p><span className="text-muted-foreground">Primary:</span> <code className="font-mono">{selectedTool.primary ?? '—'}</code></p>
                    <p><span className="text-muted-foreground">Fallback:</span> <code className="font-mono">{selectedTool.fallback ?? '—'}</code></p>
                    <p><span className="text-muted-foreground">Safety:</span> {selectedTool.safety ?? '—'}</p>
                    <p><span className="text-muted-foreground">Providers:</span> {selectedTool.providers?.join(', ') || '—'}</p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Linked skills</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-xs">
                    {(selectedTool.linked_skills ?? []).length ? (
                      <ul className="space-y-1">
                        {selectedTool.linked_skills?.map((skill) => (
                          <li key={skill.id} className="flex items-start gap-2">
                            <span className={skill.found ? 'text-succes' : 'text-alerte'}>{skill.found ? '✓' : '!'}</span>
                            <span>
                              <code className="font-mono">{skill.id}</code>
                              {skill.path ? <span className="text-muted-foreground"> · {skill.path}</span> : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-muted-foreground">No linked skills.</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Examples</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-xs">
                    {selectedTool.examples?.length ? (
                      <ul className="list-disc space-y-1 pl-5">
                        {selectedTool.examples.map((example) => (
                          <li key={example}>{example}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-muted-foreground">No examples.</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Commands</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-2 text-xs">
                    {selectedTool.commands?.length ? (
                      <Textarea readOnly value={selectedTool.commands.join('\n')} className="font-mono text-xs min-h-32" />
                    ) : (
                      <p className="text-muted-foreground">No commands declared.</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Implementations</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-xs">
                  {selectedTool.implementations?.length ? (
                    <div className="space-y-2">
                      {selectedTool.implementations.map((impl) => (
                        <div key={impl.id ?? `${impl.provider}-${impl.kind}`} className="rounded-md border px-3 py-2">
                          <div className="font-mono font-semibold">{impl.id ?? 'implementation'}</div>
                          <div className="text-muted-foreground mt-1">
                            {impl.kind ?? '—'} · {impl.provider ?? '—'} · {impl.role ?? '—'} · {impl.coverage ?? '—'}
                          </div>
                          {impl.command ? <div className="mt-1 font-mono text-[11px]">{impl.command}</div> : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-muted-foreground">No implementations declared.</p>
                  )}
                </CardContent>
              </Card>

              {selectedValidationIssues.length > 0 ? (
                <Card className="border-alerte/35">
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Validation issues</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 text-xs">
                    {selectedValidationIssues.map((issue) => (
                      <p key={`${issue.code}-${issue.tool_id}-${issue.message}`}>
                        <span className={issue.severity === 'error' ? 'text-danger' : 'text-alerte'}>{issue.severity}</span>
                        {' · '}
                        {issue.code} — {issue.message}
                      </p>
                    ))}
                  </CardContent>
                </Card>
              ) : null}

              {selectedTool.origin_refs?.length ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Origin refs</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-1 text-xs">
                    {selectedTool.origin_refs.map((ref, index) => (
                      <p key={`${ref.section}-${ref.key}-${index}`}>
                        <code className="font-mono">{ref.section}</code>
                        {ref.key ? <span className="text-muted-foreground"> · {ref.key}</span> : null}
                      </p>
                    ))}
                  </CardContent>
                </Card>
              ) : null}

              {selectedTool.notes ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Notes</CardTitle>
                  </CardHeader>
                  <CardContent className="text-muted-foreground text-sm">
                    {selectedTool.notes}
                  </CardContent>
                </Card>
              ) : null}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  )
}
