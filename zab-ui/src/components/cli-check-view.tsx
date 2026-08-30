import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, CircleDot, ExternalLink, LogIn, Pencil, PlayCircle, Plus, RefreshCw, Terminal, Trash2, XCircle } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { useI18n } from '@/i18n/use-i18n'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

type CliCheckStatus = 'ok' | 'warn' | 'fail' | 'skipped' | 'idle'

type CliCheckRow = {
  id: string
  label: string
  category: string
  status: CliCheckStatus
  message: string
  url?: string | null
  raw?: Record<string, unknown>
  detail?: {
    command?: string[]
    login_command?: string[]
    binary_path?: string | null
    exit_code?: number
    missing_env?: string[]
    missing_env_any?: string[]
    reasons?: string[]
    stdout_tail?: string
    stderr_tail?: string
  }
}

type CliCheckPayload = {
  contract: 'cli-auth-checks'
  contract_version: string
  generated_at_utc: string
  config_path: string
  total: number
  percentage: number
  score: number
  ok: number
  warn: number
  fail: number
  skipped: number
  checks: CliCheckRow[]
}

type CliCheckConfigPayload = {
  path: string
  config: {
    checks?: unknown[]
  }
}

function statusTone(status: CliCheckStatus): string {
  if (status === 'ok') return 'border-succes/35 bg-succes/10 text-succes'
  if (status === 'warn') return 'border-alerte/35 bg-alerte/10 text-alerte'
  if (status === 'fail') return 'border-danger/35 bg-danger/10 text-danger'
  return 'border-border bg-muted text-muted-foreground'
}

function StatusIcon({ status }: { status: CliCheckStatus }) {
  if (status === 'ok') return <CheckCircle2 className="size-4" />
  if (status === 'warn') return <AlertTriangle className="size-4" />
  if (status === 'fail') return <XCircle className="size-4" />
  return <CircleDot className="size-4" />
}

function commandFromRaw(raw: Record<string, unknown>): string[] {
  const command = raw.command
  if (typeof command === 'string' && command.trim()) return [command.trim()]
  if (Array.isArray(command)) return command.map((item) => String(item)).filter((item) => item.trim())
  return []
}

function loginCommandFromRaw(raw: Record<string, unknown>): string[] {
  const command = raw.login_command
  if (typeof command === 'string' && command.trim()) return [command.trim()]
  if (Array.isArray(command)) return command.map((item) => String(item)).filter((item) => item.trim())
  return []
}

function commandText(row: CliCheckRow): string {
  const cmd = row.detail?.command
  return Array.isArray(cmd) && cmd.length > 0 ? cmd.join(' ') : '—'
}

function loginCommandText(row: CliCheckRow): string {
  const cmd = row.detail?.login_command
  return Array.isArray(cmd) && cmd.length > 0 ? cmd.join(' ') : '—'
}

function detailText(row: CliCheckRow): string {
  const parts: string[] = []
  if (typeof row.detail?.exit_code === 'number') parts.push(`exit ${row.detail.exit_code}`)
  if (row.detail?.missing_env?.length) parts.push(`env: ${row.detail.missing_env.join(', ')}`)
  if (row.detail?.missing_env_any?.length) parts.push(`env any: ${row.detail.missing_env_any.join(', ')}`)
  if (row.detail?.reasons?.length) parts.push(row.detail.reasons.slice(0, 2).join(' · '))
  return parts.join(' · ')
}

function parseCheckJson(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON must be an object')
  }
  return parsed as Record<string, unknown>
}

function scoreRows(rows: CliCheckRow[]) {
  const checked = rows.filter((row) => row.status !== 'idle')
  const weights: Record<string, number> = { ok: 1, warn: 0.5, fail: 0, skipped: 0 }
  const score = checked.reduce((sum, row) => sum + (weights[row.status] ?? 0), 0)
  return {
    checked: checked.length,
    total: rows.length,
    score,
    percentage: checked.length ? Math.round((score / checked.length) * 100) : 0,
    ok: checked.filter((row) => row.status === 'ok').length,
    warn: checked.filter((row) => row.status === 'warn').length,
    fail: checked.filter((row) => row.status === 'fail').length,
  }
}

export function CliCheckView() {
  const { t } = useI18n()
  const [rows, setRows] = useState<CliCheckRow[]>([])
  const [configPath, setConfigPath] = useState('~/.config/zab/cli-checks.json')
  const [lastRunAt, setLastRunAt] = useState<string | null>(null)
  const [configLoading, setConfigLoading] = useState(false)
  const [checkingAll, setCheckingAll] = useState(false)
  const [checkingId, setCheckingId] = useState<string | null>(null)
  const [openingId, setOpeningId] = useState<string | null>(null)
  const [connectingId, setConnectingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editorText, setEditorText] = useState('')

  const rowsFromConfig = useCallback((payload: CliCheckConfigPayload): CliCheckRow[] => {
    const checks = Array.isArray(payload.config?.checks) ? payload.config.checks : []
    return checks.map((entry, index) => {
      const raw = entry && typeof entry === 'object' && !Array.isArray(entry) ? entry as Record<string, unknown> : {}
      const id = String(raw.id || raw.label || `check-${index + 1}`).trim()
      return {
        id,
        label: String(raw.label || id).trim(),
        category: String(raw.category || 'cli').trim(),
        status: 'idle',
        message: t('cliCheck.notChecked'),
        url: typeof raw.url === 'string' && raw.url.trim() ? raw.url.trim() : null,
        raw,
        detail: { command: commandFromRaw(raw), login_command: loginCommandFromRaw(raw) },
      }
    })
  }, [t])

  const applyConfig = useCallback((payload: CliCheckConfigPayload) => {
    setConfigPath(payload.path)
    setRows(rowsFromConfig(payload))
    setLastRunAt(null)
  }, [rowsFromConfig])

  const loadConfig = useCallback(async () => {
    setConfigLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/cli-check/config')
      if (!response.ok) throw new Error(await response.text())
      applyConfig((await response.json()) as CliCheckConfigPayload)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      toast.error(message)
    } finally {
      setConfigLoading(false)
    }
  }, [applyConfig])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  const runAll = useCallback(async () => {
    setCheckingAll(true)
    setError(null)
    try {
      const response = await fetch('/api/cli-check')
      if (!response.ok) throw new Error(await response.text())
      const payload = (await response.json()) as CliCheckPayload
      setRows(payload.checks)
      setConfigPath(payload.config_path)
      setLastRunAt(payload.generated_at_utc)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      toast.error(message)
    } finally {
      setCheckingAll(false)
    }
  }, [])

  const runOne = useCallback(async (row: CliCheckRow) => {
    setCheckingId(row.id)
    setError(null)
    try {
      const response = await fetch(`/api/cli-check?only=${encodeURIComponent(row.id)}`)
      if (!response.ok) throw new Error(await response.text())
      const payload = (await response.json()) as CliCheckPayload
      const checked = payload.checks[0]
      if (!checked) throw new Error(t('cliCheck.noResult'))
      setRows((current) => current.map((item) => (item.id === row.id || item.id === checked.id ? checked : item)))
      setLastRunAt(payload.generated_at_utc)
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      toast.error(message)
    } finally {
      setCheckingId(null)
    }
  }, [t])

  const openTerminal = useCallback(async (row: CliCheckRow) => {
    setOpeningId(row.id)
    try {
      const response = await fetch(`/api/cli-check/${encodeURIComponent(row.id)}/open-terminal`, {
        method: 'POST',
      })
      if (!response.ok) throw new Error(await response.text())
      toast.success(t('cliCheck.terminalOpened', { label: row.label }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setOpeningId(null)
    }
  }, [t])

  const openLoginTerminal = useCallback(async (row: CliCheckRow) => {
    setConnectingId(row.id)
    try {
      const response = await fetch(`/api/cli-check/${encodeURIComponent(row.id)}/open-login-terminal`, {
        method: 'POST',
      })
      if (!response.ok) throw new Error(await response.text())
      toast.success(t('cliCheck.loginTerminalOpened', { label: row.label }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setConnectingId(null)
    }
  }, [t])

  const openAddEditor = useCallback(() => {
    setEditingId(null)
    setEditorText(JSON.stringify({
      id: 'new-cli-auth',
      label: 'New CLI auth',
      category: 'cli',
      command: ['cli', 'auth', 'status'],
      login_command: ['cli', 'login'],
      timeout_seconds: 8,
      success: { exit_codes: [0] },
    }, null, 2))
    setEditorOpen(true)
  }, [])

  const openEditEditor = useCallback((row: CliCheckRow) => {
    setEditingId(row.id)
    setEditorText(JSON.stringify(row.raw ?? {
      id: row.id,
      label: row.label,
      category: row.category,
      command: row.detail?.command ?? [],
      url: row.url,
    }, null, 2))
    setEditorOpen(true)
  }, [])

  const saveEditor = useCallback(async () => {
    setSaving(true)
    try {
      const check = parseCheckJson(editorText)
      const response = await fetch(
        editingId ? `/api/cli-check/config/checks/${encodeURIComponent(editingId)}` : '/api/cli-check/config/checks',
        {
          method: editingId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(check),
        },
      )
      if (!response.ok) throw new Error(await response.text())
      applyConfig((await response.json()) as CliCheckConfigPayload)
      setEditorOpen(false)
      toast.success(t('cliCheck.saved'))
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }, [applyConfig, editingId, editorText, t])

  const deleteCheck = useCallback(async (row: CliCheckRow) => {
    if (!window.confirm(t('cliCheck.deleteConfirm', { label: row.label }))) return
    setSaving(true)
    try {
      const response = await fetch(`/api/cli-check/config/checks/${encodeURIComponent(row.id)}`, { method: 'DELETE' })
      if (!response.ok) throw new Error(await response.text())
      applyConfig((await response.json()) as CliCheckConfigPayload)
      toast.success(t('cliCheck.deleted'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }, [applyConfig, t])

  const routeUrl = useMemo(() => `${window.location.origin}/#cli_check`, [])
  const summary = useMemo(() => scoreRows(rows), [rows])
  const generatedAt = lastRunAt ? new Date(lastRunAt).toLocaleString() : t('cliCheck.neverRun')

  if (configLoading && rows.length === 0) {
    return (
      <section className="space-y-6" data-testid="cli-check-view">
        <LoadingState label={t('common.loading')} />
      </section>
    )
  }

  return (
    <section className="space-y-6" data-testid="cli-check-view">
      <header className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div className="min-w-0">
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">{t('cliCheck.kicker')}</p>
          <h2 className="text-3xl font-semibold tracking-tight">{t('cliCheck.title')}</h2>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">{t('cliCheck.subtitle')}</p>
          <div className="mt-3 flex max-w-full flex-wrap gap-2 text-xs">
            <code className="bg-muted max-w-full truncate rounded-md px-2 py-1 font-mono">{routeUrl}</code>
            <code className="bg-muted max-w-full truncate rounded-md px-2 py-1 font-mono">{configPath}</code>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => void loadConfig()} disabled={configLoading || checkingAll}>
            <RefreshCw className={cn('mr-2 size-4', configLoading ? 'animate-spin' : '')} />
            {t('cliCheck.reloadConfig')}
          </Button>
          <Button type="button" variant="outline" onClick={openAddEditor} disabled={saving}>
            <Plus className="mr-2 size-4" />
            {t('cliCheck.add')}
          </Button>
          <Button type="button" onClick={() => void runAll()} disabled={checkingAll || configLoading || rows.length === 0}>
            <PlayCircle className={cn('mr-2 size-4', checkingAll ? 'animate-spin' : '')} />
            {checkingAll ? t('cliCheck.refreshing') : t('cliCheck.refresh')}
          </Button>
        </div>
      </header>

      {error ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>{t('cliCheck.loadError')}</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('cliCheck.score')}</CardDescription>
            <CardTitle className="text-3xl">{summary.checked ? `${summary.percentage}%` : '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('common.ok')}</CardDescription>
            <CardTitle className="text-3xl text-succes">{summary.checked ? summary.ok : '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('common.warn')}</CardDescription>
            <CardTitle className="text-3xl text-alerte">{summary.checked ? summary.warn : '—'}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{t('common.fail')}</CardDescription>
            <CardTitle className="text-3xl text-danger">{summary.checked ? summary.fail : '—'}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t('cliCheck.tableTitle')}</CardTitle>
          <CardDescription>
            {summary.total} {t('cliCheck.checks')} · {summary.checked} {t('cliCheck.checked')} · {generatedAt}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {configLoading ? <p className="text-muted-foreground text-sm">{t('common.loading')}</p> : null}
          {!configLoading ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('cliCheck.table.status')}</TableHead>
                    <TableHead>{t('cliCheck.table.check')}</TableHead>
                    <TableHead>{t('cliCheck.table.command')}</TableHead>
                    <TableHead>{t('cliCheck.table.url')}</TableHead>
                    <TableHead>{t('cliCheck.table.detail')}</TableHead>
                    <TableHead>{t('cliCheck.table.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="align-top">
                        <span className={cn('inline-flex items-center gap-1 rounded-full border px-2 py-1 text-xs font-medium', statusTone(row.status))}>
                          <StatusIcon status={row.status} />
                          {row.status === 'idle' ? t('cliCheck.notCheckedShort') : row.status}
                        </span>
                      </TableCell>
                      <TableCell className="min-w-56 align-top">
                        <div className="font-medium">{row.label}</div>
                        <div className="text-muted-foreground mt-1 font-mono text-xs">{row.id} · {row.category}</div>
                        <div className="text-muted-foreground mt-2 text-xs">{row.message}</div>
                      </TableCell>
                      <TableCell className="min-w-72 align-top">
                        <div className="space-y-2">
                          <div className="flex items-start gap-2">
                            <Terminal className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                            <div className="min-w-0">
                              <div className="text-muted-foreground text-[0.7rem] uppercase">{t('cliCheck.checkCommand')}</div>
                              <code className="text-muted-foreground break-all font-mono text-xs">{commandText(row)}</code>
                            </div>
                          </div>
                          <div className="flex items-start gap-2">
                            <LogIn className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                            <div className="min-w-0">
                              <div className="text-muted-foreground text-[0.7rem] uppercase">{t('cliCheck.loginCommand')}</div>
                              <code className="text-muted-foreground break-all font-mono text-xs">{loginCommandText(row)}</code>
                            </div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="min-w-44 align-top">
                        {row.url ? (
                          <a
                            className="text-primary inline-flex max-w-56 items-center gap-1 truncate text-sm hover:underline"
                            href={row.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <ExternalLink className="size-4 shrink-0" />
                            <span className="truncate">{row.url.replace(/^https?:\/\//, '')}</span>
                          </a>
                        ) : (
                          <span className="text-muted-foreground text-sm">—</span>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground max-w-sm align-top text-xs">
                        {detailText(row) || '—'}
                      </TableCell>
                      <TableCell className="min-w-64 align-top">
                        <div className="flex flex-wrap gap-2">
                          <Button type="button" variant="outline" size="sm" disabled={checkingAll || checkingId === row.id} onClick={() => void runOne(row)}>
                            <PlayCircle className={cn('mr-2 size-4', checkingId === row.id ? 'animate-spin' : '')} />
                            {checkingId === row.id ? t('cliCheck.checking') : t('cliCheck.runCheck')}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={!row.detail?.command?.length || openingId === row.id}
                            onClick={() => void openTerminal(row)}
                            title={!row.detail?.command?.length ? t('cliCheck.noCommand') : t('cliCheck.openTerminal')}
                          >
                            <Terminal className="mr-2 size-4" />
                            {openingId === row.id ? t('cliCheck.openingTerminal') : t('cliCheck.openTerminal')}
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={!row.detail?.login_command?.length || connectingId === row.id}
                            onClick={() => void openLoginTerminal(row)}
                            title={!row.detail?.login_command?.length ? t('cliCheck.noLoginCommand') : t('cliCheck.connect')}
                          >
                            <LogIn className="mr-2 size-4" />
                            {connectingId === row.id ? t('cliCheck.connecting') : t('cliCheck.connect')}
                          </Button>
                          <Button type="button" variant="outline" size="icon-sm" disabled={saving} onClick={() => openEditEditor(row)} title={t('cliCheck.edit')}>
                            <Pencil className="size-4" />
                          </Button>
                          <Button type="button" variant="destructive" size="icon-sm" disabled={saving} onClick={() => void deleteCheck(row)} title={t('cliCheck.delete')}>
                            <Trash2 className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{editingId ? t('cliCheck.edit') : t('cliCheck.add')}</DialogTitle>
            <DialogDescription>{t('cliCheck.jsonHelp')}</DialogDescription>
          </DialogHeader>
          <Textarea
            className="min-h-96 font-mono text-xs"
            value={editorText}
            spellCheck={false}
            onChange={(event) => setEditorText(event.target.value)}
          />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditorOpen(false)} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button type="button" onClick={() => void saveEditor()} disabled={saving}>
              {saving ? t('common.saving') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}
