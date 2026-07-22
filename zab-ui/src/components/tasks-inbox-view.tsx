import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useI18n } from '@/i18n/use-i18n'
import { useFormatDate } from '@/i18n/format'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  CheckListIcon,
  LinkSquare02Icon,
  RefreshIcon,
  Add01Icon,
  LockKeyIcon,
  Settings02Icon,
  TestTube02Icon,
} from '@hugeicons/core-free-icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { NavId } from '@/components/sidebar-nav'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

type TaskItem = {
  identifier: string
  display_identifier?: string
  title: string
  url: string
  state: string
  updated_at: string
  source_label: string
}

type TaskSourceBlock = {
  id: string
  label: string
  backend: string
  status: string
  reason: string | null
  routing_doc?: string | null
  routing_doc_abs?: string | null
  mcp_hint?: string | null
  local_project_path?: string | null
  local_project_path_abs?: string | null
  url?: string | null
  env_token: string
  items: TaskItem[]
}

type TasksInboxPayload = {
  generated_at_utc: string
  parse_errors: string[]
  env_hints: Record<string, boolean>
  sources: TaskSourceBlock[]
  all_tasks: TaskItem[]
  total_count: number
}

type PmEnvSyncPayload = {
  path: string
  scanned_env_files: number
  keys_updated: string[]
  keys_skipped_already_present: string[]
  keys_found_by_scan: string[]
  keys_missing_after_scan: string[]
}

type SourceCheckResult = TaskSourceBlock & {
  checked_at_utc: string
  token_present: boolean
}

async function apiJson<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) {
    const respText = await r.text()
    throw new Error(respText || r.statusText)
  }
  return r.json() as Promise<T>
}

async function apiPostJson<T>(path: string, body: Record<string, unknown>): Promise<T> {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    const respText = await r.text()
    throw new Error(respText || r.statusText)
  }
  return r.json() as Promise<T>
}

function sourceBadgeColor(label: string): string {
  const lower = label.toLowerCase()
  if (lower.includes('gitlab')) return 'bg-orange-50 text-orange-800 ring-orange-200'
  if (lower.includes('linear')) return 'bg-purple-50 text-purple-800 ring-purple-200'
  if (lower.includes('notion')) return 'bg-gray-100 text-gray-700 ring-gray-200'
  if (lower.includes('github')) return 'bg-slate-100 text-slate-700 ring-slate-200'
  return 'bg-zinc-100 text-zinc-700 ring-zinc-200'
}

function formatTaskDate(iso: string, locale: string): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleDateString(locale, {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso.slice(0, 16).replace('T', ' ')
  }
}

function formatCheckedAt(iso: string | undefined, locale: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

export function TasksInboxView({ onJump }: { onJump?: (id: NavId) => void } = {}) {
  const { t } = useI18n()
  const { intlLocale } = useFormatDate()
  const [data, setData] = useState<TasksInboxPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncingPm, setSyncingPm] = useState(false)
  const [viewMode, setViewMode] = useState<'unified' | 'by-source'>('unified')
  const [filterSource, setFilterSource] = useState<string | null>(null)
  const [newSourceUrl, setNewSourceUrl] = useState('')
  const [addingSource, setAddingSource] = useState(false)
  const [checking, setChecking] = useState<Record<string, boolean>>({})
  const [checkedAt, setCheckedAt] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const j = await apiJson<TasksInboxPayload>('/api/tasks/inbox')
      setData(j)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const forceSync = useCallback(async () => {
    setLoading(true)
    try {
      const j = await apiPostJson<TasksInboxPayload>('/api/tasks/inbox/sync', {})
      setData(j)
      toast.success(t('tasks.toast.synced'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [t])

  const checkSource = useCallback(async (sourceId: string) => {
    setChecking((s) => ({ ...s, [sourceId]: true }))
    try {
      const result = await apiPostJson<SourceCheckResult>(
        `/api/tasks/sources/${encodeURIComponent(sourceId)}/check`,
        {},
      )
      setData((prev) => {
        if (!prev) return prev
        const sources = prev.sources.map((s) =>
          s.id === sourceId ? { ...s, ...result, items: result.items || s.items } : s,
        )
        return { ...prev, sources }
      })
      setCheckedAt((m) => ({ ...m, [sourceId]: result.checked_at_utc }))
      if (result.status === 'ok') {
        toast.success(
          t('tasks.toast.sourceFetched', {
            label: result.label,
            count: String(result.items?.length ?? 0),
          }),
        )
      } else if (result.status === 'skipped') {
        toast.warning(`${result.label} : ${result.reason || 'token absent'}`)
      } else {
        toast.error(`${result.label} : ${result.reason || 'erreur'}`)
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setChecking((s) => ({ ...s, [sourceId]: false }))
    }
  }, [t])

  useEffect(() => {
    void load()
  }, [load])

  const displayedTasks = (() => {
    if (!data) return []
    if (viewMode === 'by-source') {
      if (!filterSource) return []
      const src = data.sources.find((s) => s.id === filterSource)
      return src?.items || []
    }
    let tasks = data.all_tasks || []
    if (filterSource) {
      const src = data.sources.find((s) => s.id === filterSource)
      const ids = new Set(src?.items.map((i) => i.url) || [])
      tasks = tasks.filter((t) => ids.has(t.url))
    }
    return tasks
  })()

  const handleAddSource = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!newSourceUrl.trim()) return
    setAddingSource(true)
    try {
      await apiPostJson('/api/tasks/sources/add', { url: newSourceUrl })
      toast.success(t('tasks.toast.sourceAdded'))
      setNewSourceUrl('')
      await forceSync()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setAddingSource(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="space-y-6" data-testid="tasks-inbox-view">
        <LoadingState label="Chargement de l'inbox des tâches…" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">{t('tasks.title')}</h2>
          <p className="text-muted-foreground text-sm">{t('tasks.subtitle')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={loading || syncingPm}
            onClick={() => {
              setSyncingPm(true)
              void (async () => {
                try {
                  const s = await apiPostJson<PmEnvSyncPayload>('/api/tasks/pm-env/sync', { force: false })
                  toast.success(t('tasks.toast.pmEnvMerged'), {
                    description: t('tasks.toast.pmEnvDesc', {
                      files: String(s.scanned_env_files),
                      keys: s.keys_updated.join(', ') || t('tasks.toast.pmEnvNone'),
                    }),
                  })
                  await load()
                } catch (e) {
                  toast.error(e instanceof Error ? e.message : String(e))
                } finally {
                  setSyncingPm(false)
                }
              })()
            }}
          >
            {t('tasks.importEnv')}
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void forceSync()}>
            <HugeiconsIcon icon={RefreshIcon} size={16} className="mr-1.5 opacity-70" />
            {t('tasks.refresh')}
          </Button>
        </div>
      </header>

      {filterSource && (
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-xs">{t('tasks.filterLabel')}</span>
          <span className="bg-primary text-primary-foreground inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs">
            {data?.sources.find((s) => s.id === filterSource)?.label}
            <button onClick={() => setFilterSource(null)} className="ml-1 hover:opacity-70" aria-label={t('tasks.removeFilter')}>
              ×
            </button>
          </span>
        </div>
      )}

      <Card>
        <CardHeader className="py-4 flex flex-row items-start justify-between">
          <div>
            <CardTitle className="text-base">{t('tasks.sources.title')}</CardTitle>
            <CardDescription>{t('tasks.sources.description')}</CardDescription>
          </div>
          <form onSubmit={handleAddSource} className="flex items-center gap-2 max-w-sm w-full">
            <input
              type="url"
              placeholder={t('tasks.sources.placeholder')}
              value={newSourceUrl}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewSourceUrl(e.target.value)}
              className="flex h-8 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 text-xs"
              required
            />
            <Button type="submit" size="sm" disabled={addingSource || !newSourceUrl.trim()} className="shrink-0 h-8">
              <HugeiconsIcon icon={Add01Icon} size={14} className="mr-1" />
              {t('tasks.sources.add')}
            </Button>
          </form>
        </CardHeader>
        <CardContent className="pt-0">
          {!data ? (
            <p className="text-muted-foreground text-sm">{t('common.loading')}</p>
          ) : data.sources.length === 0 ? (
            <p className="text-muted-foreground py-2 text-sm">{t('tasks.sources.none')}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tasks.table.label')}</TableHead>
                  <TableHead className="w-24">{t('tasks.table.backend')}</TableHead>
                  <TableHead>{t('tasks.table.directory')}</TableHead>
                  <TableHead className="w-36">{t('tasks.table.status')}</TableHead>
                  <TableHead className="w-16 text-right">{t('tasks.table.tasks')}</TableHead>
                  <TableHead className="w-64 text-right">{t('tasks.table.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.sources.map((src) => {
                  const isFiltered = filterSource === src.id
                  const isChecking = !!checking[src.id]
                  const lastChecked = checkedAt[src.id]
                  const tokenAbsent = !!src.reason?.toLowerCase().includes('absente')
                  const isError = src.status === 'error' || src.status === 'skipped'
                  return (
                    <TableRow
                      key={src.id}
                      className={cn('cursor-pointer', isFiltered && 'bg-primary/5')}
                      onClick={() => setFilterSource(isFiltered ? null : src.id)}
                    >
                      <TableCell className="font-medium">{src.label}</TableCell>
                      <TableCell>
                        <span className="text-muted-foreground bg-muted inline-flex rounded-md px-1.5 py-0.5 text-xs">
                          {src.backend}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-0.5">
                          {src.local_project_path ? (
                            <span className="font-mono text-xs" title={src.local_project_path_abs || ''}>
                              {src.local_project_path}
                            </span>
                          ) : null}
                          {src.url ? (
                            <a
                              href={src.url}
                              target="_blank"
                              rel="noreferrer"
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 px-2 py-1 bg-secondary hover:bg-secondary/80 text-secondary-foreground rounded text-[10px] font-medium transition-colors w-fit mt-1"
                            >
                              <HugeiconsIcon icon={LinkSquare02Icon} size={12} />
                              {t('tasks.openProject')}
                            </a>
                          ) : null}
                          <span className="text-muted-foreground text-[10px]">
                            {t('tasks.table.token')} : <code>{src.env_token}</code>
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <span
                            className={cn(
                              'inline-flex w-fit rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                              src.status === 'ok'
                                ? 'bg-emerald-50 text-emerald-800 ring-emerald-200'
                                : src.status === 'skipped'
                                  ? 'bg-zinc-100 text-zinc-700 ring-zinc-200'
                                  : 'bg-rose-50 text-rose-800 ring-rose-200',
                            )}
                          >
                            {src.status}
                          </span>
                          {src.reason && (
                            <span className="text-[10px] text-red-600 truncate max-w-[180px]" title={src.reason}>
                              {src.reason}
                            </span>
                          )}
                          {lastChecked && (
                            <span className="text-muted-foreground text-[10px]">
                              {t('tasks.testedAt')} {formatCheckedAt(lastChecked, intlLocale)}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-medium">
                        {src.status === 'ok' ? src.items.length : '—'}
                      </TableCell>
                      <TableCell className="text-right">
                        <div
                          className="flex flex-wrap items-center justify-end gap-1.5"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isChecking}
                            onClick={() => void checkSource(src.id)}
                            className="h-7"
                            title={t('tasks.testTitle')}
                          >
                            <HugeiconsIcon
                              icon={isChecking ? RefreshIcon : TestTube02Icon}
                              size={13}
                              className={cn('mr-1', isChecking && 'animate-spin')}
                            />
                            {isChecking ? t('tasks.testing') : t('tasks.test')}
                          </Button>
                          {isError && onJump && (
                            <>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                onClick={() => onJump('security')}
                                className="h-7 text-amber-700 hover:bg-amber-50 hover:text-amber-900"
                                title={
                                  tokenAbsent
                                    ? t('tasks.setTokenTitle', { token: src.env_token })
                                    : t('tasks.verifyTokenTitle', { token: src.env_token })
                                }
                              >
                                <HugeiconsIcon icon={LockKeyIcon} size={13} className="mr-1" />
                                {tokenAbsent ? t('tasks.setToken') : t('tasks.verifyToken')}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                onClick={() => onJump('config')}
                                className="h-7"
                                title={t('tasks.editConfigTitle')}
                              >
                                <HugeiconsIcon icon={Settings02Icon} size={13} className="mr-1" />
                                {t('tasks.configBtn')}
                              </Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-800">
            <HugeiconsIcon icon={CheckListIcon} size={20} />
          </div>
          <div className="flex-1">
            <CardTitle className="text-base">
              {viewMode === 'unified'
                ? t('tasks.allTasks', { count: String(data?.total_count || 0) })
                : t('tasks.bySource')}
            </CardTitle>
            <CardDescription>
              {viewMode === 'unified' ? t('tasks.unifiedDesc') : t('tasks.bySourceDesc')}
            </CardDescription>
          </div>
          <div className="flex gap-1">
            <Button
              type="button"
              variant={viewMode === 'unified' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setViewMode('unified')}
            >
              {t('tasks.unified')}
            </Button>
            <Button
              type="button"
              variant={viewMode === 'by-source' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setViewMode('by-source')}
            >
              {t('tasks.bySourceMode')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!data ? (
            <p className="text-muted-foreground text-sm">{t('common.loading')}</p>
          ) : displayedTasks.length === 0 ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {filterSource
                ? t('tasks.empty.source')
                : viewMode === 'by-source'
                  ? t('tasks.empty.pickSource')
                  : t('tasks.empty.none')}
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-28">{t('tasks.table.source')}</TableHead>
                  <TableHead className="w-20">{t('tasks.table.id')}</TableHead>
                  <TableHead>{t('tasks.table.titleCol')}</TableHead>
                  <TableHead className="w-28">{t('tasks.table.status')}</TableHead>
                  <TableHead className="w-32">{t('tasks.table.updated')}</TableHead>
                  <TableHead className="w-16" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayedTasks.map((row, idx) => (
                  <TableRow key={`${row.source_label}-${row.identifier}-${idx}`}>
                    <TableCell>
                      <span
                        className={cn(
                          'inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                          sourceBadgeColor(row.source_label),
                        )}
                      >
                        {row.source_label}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-xs" title={row.identifier}>
                      {row.display_identifier || row.identifier}
                    </TableCell>
                    <TableCell className="max-w-md truncate text-sm font-medium">{row.title}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{row.state || '—'}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">{formatTaskDate(row.updated_at, intlLocale)}</TableCell>
                    <TableCell>
                      {row.url ? (
                        <a
                          href={row.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-primary inline-flex items-center gap-1 text-xs font-medium hover:underline"
                        >
                          <HugeiconsIcon icon={LinkSquare02Icon} size={14} />
                          Ouvrir
                        </a>
                      ) : (
                        '—'
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3 py-3">
          <div>
            <CardTitle className="text-sm">Variables d'accès</CardTitle>
            <CardDescription className="text-[11px]">
              Présence dans le processus — aucun secret affiché.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {data ? (
            <ul className="flex flex-wrap gap-2 text-xs">
              {Object.entries(data.env_hints).map(([k, ok]) => (
                <li
                  key={k}
                  className={cn(
                    'rounded-full px-2 py-0.5 font-mono text-[10px] ring-1',
                    ok ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-zinc-100 text-zinc-600 ring-zinc-200',
                  )}
                >
                  {k}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground text-sm">Chargement…</p>
          )}
        </CardContent>
      </Card>

      {data && data.parse_errors.length > 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          <p className="font-medium">Entrées task_sources ignorées</p>
          <ul className="mt-2 list-inside list-disc space-y-0.5">
            {data.parse_errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {data ? (
        <p className="text-muted-foreground text-[10px]">
          Généré : <code className="font-mono">{data.generated_at_utc}</code>
        </p>
      ) : null}
    </div>
  )
}
