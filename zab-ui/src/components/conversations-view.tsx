import { useCallback, useEffect, useMemo, useState, type ChangeEvent } from 'react'
import { toast } from 'sonner'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  RefreshIcon,
  Search01Icon,
  PlayCircleIcon,
  MessageDone01Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  Copy01Icon,
  CheckListIcon,
  AiSettingIcon,
} from '@hugeicons/core-free-icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n/use-i18n'
import {
  conversationProviderBadgeClass,
  conversationProviderLabel,
  conversationStatusLabel,
} from '@/lib/conversation-meta'

type ProviderRow = {
  id: string
  label: string
  status: string
  postgres_documents: number
  local: Record<string, unknown>
}

type ProvidersPayload = {
  generated_at_utc: string
  providers: ProviderRow[]
  compact_index: { path: string; last_batch?: string; updated_at_utc?: string }
}

type HealthPayload = {
  severity: string
  postgres: Record<string, unknown>
  integrity: Record<string, unknown> | null
  recommendations: { id: string; message: string }[]
  generated_at_utc: string
}

type SearchRow = {
  document_id: string
  conversation_id?: string | null
  index_document_id?: string | null
  source: string
  wing: string | null
  room: string | null
  synced_at: string | null
  path?: string | null
  match_chunks: number
  content_excerpt: string
}

type BrowseRow = Omit<SearchRow, 'match_chunks'> & {
  match_chunks?: number
  chunk_count: number
  message_count: number
  title?: string | null
  conversation_id?: string | null
}

type BrowsePayload = {
  items: BrowseRow[]
  total: number
  /** archive : table Postgres zab_conversations ; index_fallback : anciennes lignes mehdi_memory_* seules */
  conversation_storage?: 'archive' | 'index_fallback' | 'error' | 'unavailable'
}

type ConversationMessage = {
  role: string
  label: string
  content: string
  timestamp?: string | null
  tool_name?: string | null
  line?: number | null
}

type ConversationDetail = {
  id?: string
  source?: string
  wing?: string | null
  path?: string | null
  messages?: ConversationMessage[]
  raw_events?: unknown[]
  chunks?: Record<string, unknown>[]
}

async function apiJson<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) {
    const t = await r.text()
    throw new Error(t || r.statusText)
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
    const t = await r.text()
    throw new Error(t || r.statusText)
  }
  return r.json() as Promise<T>
}

function severityBanner(sev: string): string {
  if (sev === 'fail') return 'border-red-300 bg-red-50 text-red-900'
  if (sev === 'warn') return 'border-amber-300 bg-amber-50 text-amber-950'
  return 'border-emerald-200 bg-emerald-50 text-emerald-950'
}

function sourceToProviderSlug(source: string, wing?: string | null): string {
  const w = (wing ?? '').toLowerCase()
  if (source === 'cursor_agent_transcript' || (source === 'agent_context_artifact' && w.startsWith('cursor')))
    return 'cursor'
  if (source === 'claude_code_transcript') return 'claude'
  if (source === 'codex_transcript' || (source === 'agent_context_artifact' && w.startsWith('codex')))
    return 'codex'
  if (source === 'kimi_transcript' || (source === 'agent_context_artifact' && w.startsWith('kimi')))
    return 'kimi'
  if (source === 'hermes_transcript') return 'hermes'
  if (source === 'gemini_cli_transcript') return 'gemini'
  return source
}

function conversationMessageClass(role: string): string {
  const r = role.toLowerCase()
  if (r === 'user') return 'border-sky-200 bg-sky-50'
  if (r === 'assistant') return 'border-zinc-200 bg-white'
  if (r === 'tool') return 'border-violet-200 bg-violet-50'
  if (r === 'system') return 'border-amber-200 bg-amber-50'
  return 'border-zinc-200 bg-muted/50'
}

function formatMessageTime(value?: string | null): string | null {
  if (!value) return null
  const numeric = Number(value)
  const d = Number.isFinite(numeric) ? new Date(numeric < 10_000_000_000 ? numeric * 1000 : numeric) : new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** UUID à passer à l’API détail : id archive préféré, sinon document index. */
function conversationDetailApiId(row: SearchRow | BrowseRow): string {
  const c = row.conversation_id?.trim()
  if (c) return c
  return row.document_id
}

/** Titre lisible dans le dialogue (extrait du chemin métier). */
function shortPathLabel(path: string | undefined | null, wing: string | null | undefined): string {
  const p = path?.trim()
  if (p) {
    const parts = p.split(/[/\\]/).filter(Boolean)
    const base = parts.pop()
    if (base) return base.length > 64 ? `${base.slice(0, 61)}…` : base
  }
  const w = wing?.trim()
  if (w) return w.length > 72 ? `${w.slice(0, 69)}…` : w
  return ''
}

export function ConversationsView() {
  const { t } = useI18n()
  const [providers, setProviders] = useState<ProvidersPayload | null>(null)
  const [health, setHealth] = useState<HealthPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [q, setQ] = useState('')
  const [debouncedQ, setDebouncedQ] = useState('')
  const [providerFilters, setProviderFilters] = useState<string[]>([])
  const [searchRows, setSearchRows] = useState<SearchRow[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [browseRows, setBrowseRows] = useState<BrowseRow[]>([])
  const [browseTotal, setBrowseTotal] = useState(0)
  const [browseOffset, setBrowseOffset] = useState(0)
  const [browseLoading, setBrowseLoading] = useState(false)
  const [browseStorage, setBrowseStorage] = useState<BrowsePayload['conversation_storage'] | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detailDoc, setDetailDoc] = useState<ConversationDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [jobRunning, setJobRunning] = useState(false)
  const [jobLines, setJobLines] = useState<string[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [p, h] = await Promise.all([
        apiJson<ProvidersPayload>('/api/conversations/providers'),
        apiJson<HealthPayload>('/api/conversations/health'),
      ])
      setProviders(p)
      setHealth(h)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(q.trim()), 320)
    return () => window.clearTimeout(t)
  }, [q])

  const runSearch = useCallback(async () => {
    if (!debouncedQ) {
      setSearchRows([])
      return
    }
    if (health?.postgres && health.postgres.configured === false) {
      toast.message(t('conversationsView.toast.postgresMissing'), {
        description: t('conversationsView.toast.postgresMissingDesc'),
      })
      return
    }
    setSearchLoading(true)
    try {
      const params = new URLSearchParams({
        q: debouncedQ,
        limit: '20',
        offset: '0',
      })
      if (providerFilters.length > 0) params.set('providers', providerFilters.join(','))
      const j = await apiJson<{ results: SearchRow[] }>(`/api/conversations/search?${params.toString()}`)
      setSearchRows(j.results ?? [])
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      setSearchRows([])
    } finally {
      setSearchLoading(false)
    }
  }, [debouncedQ, providerFilters, health])

  useEffect(() => {
    void runSearch()
  }, [runSearch])

  const browsePageSize = 25

  const loadBrowse = useCallback(async () => {
    if (health?.postgres && health.postgres.configured === false) {
      setBrowseRows([])
      setBrowseTotal(0)
      setBrowseStorage(null)
      return
    }
    setBrowseLoading(true)
    try {
      const params = new URLSearchParams({
        limit: String(browsePageSize),
        offset: String(browseOffset),
      })
      if (providerFilters.length > 0) params.set('providers', providerFilters.join(','))
      const j = await apiJson<BrowsePayload>(`/api/conversations/documents?${params.toString()}`)
      setBrowseRows(j.items ?? [])
      setBrowseTotal(j.total ?? 0)
      setBrowseStorage(j.conversation_storage ?? null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      setBrowseRows([])
      setBrowseTotal(0)
      setBrowseStorage(null)
    } finally {
      setBrowseLoading(false)
    }
  }, [browseOffset, providerFilters, health])

  useEffect(() => {
    void loadBrowse()
  }, [loadBrowse])

  useEffect(() => {
    setBrowseOffset(0)
  }, [providerFilters])

  const startSyncJob = useCallback(
    async (dryRun: boolean) => {
      setJobRunning(true)
      setJobLines([])
      try {
        const job = await apiPostJson<{ id: string }>('/api/conversations/sync', {
          dry_run: dryRun,
          append: false,
          with_mempalace: false,
          workspace_storage_cursor: false,
          providers: null,
          batch_id: null,
        })
        const es = new EventSource(`/api/jobs/${job.id}/stream`)
        await new Promise<void>((resolve, reject) => {
          es.onmessage = (ev) => {
            try {
              const data = JSON.parse(ev.data) as {
                line?: string
                summary?: { status: string; exit_code: number | null }
              }
              if (typeof data.line === 'string') {
                setJobLines((prev) => [...prev, data.line as string])
              }
              if (data.summary) {
                es.close()
                const ok = data.summary.status === 'done' && data.summary.exit_code === 0
                if (ok) toast.success(dryRun ? t('conversationsView.toast.dryRunDone') : t('conversationsView.toast.syncDone'))
                else toast.error(`Job ${data.summary.status} (code ${String(data.summary.exit_code)})`)
                resolve()
              }
            } catch (err) {
              es.close()
              reject(err instanceof Error ? err : new Error(String(err)))
            }
          }
          es.onerror = () => {
            es.close()
            reject(new Error('Flux SSE interrompu'))
          }
        })
        await load()
        void runSearch()
        void loadBrowse()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      } finally {
        setJobRunning(false)
      }
    },
    [load, runSearch, loadBrowse],
  )

  const openDetail = useCallback(async (id: string) => {
    if (!id) return
    setDetailId(id)
    setDetailDoc(null)
    setDetailLoading(true)
    try {
      const j = await apiJson<{ document: ConversationDetail }>(`/api/conversations/document/${encodeURIComponent(id)}?chunk_limit=120`)
      setDetailDoc(j.document)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      setDetailDoc(null)
    } finally {
      setDetailLoading(false)
    }
  }, [])

  const sev = health?.severity ?? 'ok'
  const recs = useMemo(() => health?.recommendations ?? [], [health])
  const showingSearch = debouncedQ.length > 0
  const visibleRows: Array<SearchRow | BrowseRow> = showingSearch ? searchRows : browseRows
  const providerRows = providers?.providers ?? []
  const providerIds = useMemo(() => providerRows.map((p) => p.id), [providerRows])
  const effectiveProviderFilters = providerFilters.length > 0 ? providerFilters : providerIds
  const activeProviderSet = useMemo(() => new Set(effectiveProviderFilters), [effectiveProviderFilters])
  const allSourcesLabel = t('conversationsView.filters.allSources')
  const providerFilterSummary =
    providerFilters.length > 0 ? `${providerFilters.length}/${providerIds.length || providerFilters.length} sources` : allSourcesLabel

  const setProviderFilterChecked = useCallback(
    (id: string, checked: boolean) => {
      setProviderFilters((current) => {
        const base = current.length > 0 ? current : providerIds
        const next = checked
          ? Array.from(new Set([...base, id]))
          : base.filter((x) => x !== id)
        if (next.length === 0 || next.length === providerIds.length) return []
        return next
      })
    },
    [providerIds],
  )

  const openAiProviderConfig = useCallback(() => {
    window.location.hash = 'config'
  }, [])

  const detailIndex = useMemo(() => {
    if (!detailId) return -1
    return visibleRows.findIndex((r) => conversationDetailApiId(r) === detailId)
  }, [detailId, visibleRows])

  const goPrev = useCallback(() => {
    if (detailIndex <= 0) return
    const prev = visibleRows[detailIndex - 1]
    if (prev) void openDetail(conversationDetailApiId(prev))
  }, [detailIndex, visibleRows, openDetail])

  const goNext = useCallback(() => {
    if (detailIndex < 0 || detailIndex >= visibleRows.length - 1) return
    const next = visibleRows[detailIndex + 1]
    if (next) void openDetail(conversationDetailApiId(next))
  }, [detailIndex, visibleRows, openDetail])

  const detailRow = detailIndex >= 0 ? visibleRows[detailIndex] : null
  const detailProviderSlug = detailRow
    ? sourceToProviderSlug(detailRow.source, detailRow.wing)
    : detailDoc
      ? sourceToProviderSlug(String(detailDoc.source ?? ''), detailDoc.wing)
      : null

  const copyDetailPath = useCallback(async () => {
    const p = detailDoc?.path
    if (!p) return
    try {
      await navigator.clipboard.writeText(String(p))
      toast.success(t('conversationsView.toast.pathCopied'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Impossible de copier')
    }
  }, [detailDoc])

  useEffect(() => {
    if (detailId == null) return
    const onKey = (ev: KeyboardEvent) => {
      const target = ev.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
      if (ev.altKey || ev.ctrlKey || ev.metaKey) return
      if (ev.key === 'ArrowLeft' || ev.key === 'k' || ev.key === 'K') {
        ev.preventDefault()
        ev.stopPropagation()
        goPrev()
      } else if (ev.key === 'ArrowRight' || ev.key === 'j' || ev.key === 'J') {
        ev.preventDefault()
        ev.stopPropagation()
        goNext()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => document.removeEventListener('keydown', onKey, true)
  }, [detailId, goPrev, goNext])

  // Reference variables to satisfy tsc unused variable checks
  const _unusedRef = [
    detailLoading,
    goPrev,
    goNext,
    detailProviderSlug,
    copyDetailPath,
    ArrowLeft01Icon,
    ArrowRight01Icon,
    Copy01Icon
  ]
  if (_unusedRef.length < 0) console.log(_unusedRef)

  return (
    <div className="space-y-8" data-testid="conversations-view">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">{t('conversationsView.title')}</h2>
        <p className="text-muted-foreground mt-1 text-sm">{t('conversationsView.subtitle')}</p>
      </div>

      <Card
        data-testid="conversations-health-banner"
        className={cn('border', severityBanner(sev))}
      >
        <CardHeader className="pb-2">
          <CardTitle className="text-base">État des données</CardTitle>
          <CardDescription>
            Sévérité : <strong>{sev}</strong>
            {health?.postgres && typeof health.postgres.document_count === 'number' ? (
              <>
                {' '}
                — documents Postgres : {String(health.postgres.document_count)}
              </>
            ) : null}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {recs.length ? (
            <ul className="list-inside list-disc text-sm">
              {recs.map((r) => (
                <li key={r.id}>{r.message}</li>
              ))}
            </ul>
          ) : (
            <p className="text-sm">Aucune alerte.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={loading || jobRunning}
              onClick={() => void load()}
              data-testid="conversations-refresh-health"
            >
              <HugeiconsIcon icon={RefreshIcon} size={16} strokeWidth={2} className="mr-1.5" />
              {t('conversationsView.actions.refreshChecks')}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={jobRunning}
              onClick={() => void startSyncJob(true)}
              data-testid="conversations-dry-run"
            >
              <HugeiconsIcon icon={MessageDone01Icon} size={16} strokeWidth={2} className="mr-1.5" />
              {t('conversationsView.actions.dryRun')}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={jobRunning}
              onClick={() => void startSyncJob(false)}
              data-testid="conversations-sync"
            >
              <HugeiconsIcon icon={PlayCircleIcon} size={16} strokeWidth={2} className="mr-1.5" />
              {t('conversationsView.actions.sync')}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={openAiProviderConfig}
              data-testid="conversations-add-ai-provider"
            >
              <HugeiconsIcon icon={AiSettingIcon} size={16} strokeWidth={2} className="mr-1.5" />
              {t('conversationsView.actions.addAiProvider')}
            </Button>
          </div>
          {jobLines.length > 0 ? (
            <pre className="bg-muted max-h-40 overflow-auto rounded-md p-2 text-[11px] leading-snug whitespace-pre-wrap">
              {jobLines.slice(-80).join('\n')}
            </pre>
          ) : null}
        </CardContent>
      </Card>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-muted-foreground text-xs" data-testid="conversations-provider-filter-summary">
            {providerFilterSummary}
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={providerFilters.length === 0}
            onClick={() => setProviderFilters([])}
            data-testid="conversations-provider-filter-all"
          >
            <HugeiconsIcon icon={CheckListIcon} size={14} strokeWidth={2} className="mr-1" />
            {t('conversationsView.filters.allSources')}
          </Button>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" data-testid="conversations-provider-cards">
          {providerRows.map((p) => {
            const checked = activeProviderSet.has(p.id)
            return (
              <Card
                key={p.id}
                className={cn(
                  'transition',
                  checked ? 'bg-primary/5 ring-primary/50' : 'opacity-75',
                )}
                data-testid={`conversation-provider-${p.id}`}
              >
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between gap-2">
                    <label className="flex min-w-0 cursor-pointer items-center gap-2">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(ev) => setProviderFilterChecked(p.id, ev.currentTarget.checked)}
                        aria-label={`Filtrer ${p.label}`}
                        data-testid={`conversations-provider-filter-${p.id}`}
                        className="border-input text-primary size-4 rounded"
                      />
                      <CardTitle className="truncate text-sm font-medium">{p.label}</CardTitle>
                    </label>
                    <span
                      className={cn(
                        'rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                        conversationProviderBadgeClass(p.id),
                      )}
                    >
                      {conversationStatusLabel(p.status, t)}
                    </span>
                  </div>
                  <CardDescription className="text-xs">
                    Docs Postgres : <strong>{p.postgres_documents}</strong>{' '}
                    <span className="text-muted-foreground">(import sync)</span>
                  </CardDescription>
                </CardHeader>
              </Card>
            )
          })}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('conversationsView.history.title')}</CardTitle>
          <CardDescription>
            Explorez les conversations les plus récentes, ou tapez une recherche pour filtrer en plein texte.{' '}
            <span className="text-foreground font-medium">Cliquez sur une ligne</span> (ou sur Détail) pour ouvrir le
            fil de messages.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {browseStorage === 'index_fallback' ? (
            <div
              className="border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-50 rounded-lg border px-3 py-2 text-sm"
              role="status"
              data-testid="conversations-index-fallback-notice"
            >
              <p className="font-medium">Historique depuis l&apos;index Postgres (mémoire MCP)</p>
              <p className="text-muted-foreground mt-1 text-xs dark:text-amber-100/85">
                L&apos;archive <code className="font-mono">zab_conversations</code> est encore vide — les données viennent
                des anciennes lignes <code className="font-mono">mehdi_memory_*</code>. Lancez{' '}
                <strong>Synchroniser</strong> (pas le dry-run) pour remplir l&apos;archive et stabiliser les compteurs.
              </p>
            </div>
          ) : null}
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <div className="relative min-w-0 flex-1">
              <HugeiconsIcon
                icon={Search01Icon}
                className="text-muted-foreground pointer-events-none absolute top-2.5 left-2.5"
                size={18}
                strokeWidth={2}
              />
              <input
                className="border-input bg-background w-full rounded-lg border py-2 pr-3 pl-9 text-sm outline-none transition focus:ring-2 focus:ring-zinc-300"
                placeholder="Rechercher dans les conversations…"
                value={q}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setQ(e.target.value)}
                data-testid="conversations-search"
              />
            </div>
            <div
              className="border-input bg-muted/30 text-muted-foreground flex h-9 shrink-0 items-center rounded-md border px-3 text-xs"
              data-testid="conversations-provider-filter"
            >
              {providerFilterSummary}
            </div>
          </div>
          {showingSearch ? null : (
            <div className="text-muted-foreground flex flex-wrap items-center justify-between gap-2 text-xs">
              <span>
                {browseLoading
                  ? 'Chargement de l’historique…'
                  : browseTotal > 0
                    ? `${browseTotal} conversation(s) — ${browseOffset + 1}-${Math.min(browseOffset + browsePageSize, browseTotal)}`
                    : '0 conversation'}
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={browseLoading || browseOffset === 0}
                  onClick={() => setBrowseOffset((v) => Math.max(0, v - browsePageSize))}
                  data-testid="conversations-browse-prev"
                >
                  Précédent
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={browseLoading || browseOffset + browsePageSize >= browseTotal}
                  onClick={() => setBrowseOffset((v) => v + browsePageSize)}
                  data-testid="conversations-browse-next"
                >
                  Suivant
                </Button>
              </div>
            </div>
          )}
          {searchLoading || browseLoading ? (
            <p className="text-muted-foreground text-sm" data-testid="conversations-search-loading">
              {showingSearch ? 'Recherche…' : 'Chargement…'}
            </p>
          ) : debouncedQ && searchRows.length === 0 ? (
            <p className="text-muted-foreground text-sm" data-testid="conversations-empty-results">
              Aucun résultat. Vérifiez la sync ou élargissez la requête.
            </p>
          ) : null}
          {!showingSearch && !browseLoading && browseRows.length === 0 ? (
            <p className="text-muted-foreground text-sm" data-testid="conversations-empty-history">
              {browseStorage === 'error'
                ? 'Impossible de lire Postgres (historique ou archive). Revérifiez ZAB_MEMORY_DATABASE_URL puis les migrations.'
                : browseStorage === 'index_fallback'
                  ? 'Aucun document conversationnel dans Postgres. Les providers ci-dessus sont « prêts » sur le poste mais rien n’a encore été importé : exécutez Synchroniser (sync réelle).'
                  : browseStorage === 'archive'
                    ? 'Aucune conversation dans l’archive. Lancez une synchronisation pour importer depuis vos JSONL locaux.'
                    : 'Aucune conversation historique à afficher. Configurez Postgres ou lancez une synchronisation.'}
            </p>
          ) : null}
          {visibleRows.length > 0 ? (
            <Table data-testid="conversations-results-table" className="table-fixed">
              <colgroup>
                <col className="w-[140px]" />
                <col className="w-[220px]" />
                <col />
                <col className="w-[120px]" />
                <col className="w-[110px]" />
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead>Provider</TableHead>
                  <TableHead>Wing</TableHead>
                  <TableHead>{showingSearch ? 'Extraits' : 'Aperçu'}</TableHead>
                  <TableHead className="text-right">Volume</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRows.map((row) => {
                  const apiId = conversationDetailApiId(row)
                  const rowLabel =
                    shortPathLabel(row.path, row.wing) || row.document_id.slice(0, 8)
                  const matchN = Number(row.match_chunks ?? 0)
                  const browseRow = row as BrowseRow
                  return (
                    <TableRow
                      key={`${row.document_id}-${apiId}`}
                      data-testid="conversation-result-row"
                      tabIndex={0}
                      role="button"
                      className={cn(
                        'hover:bg-muted/70 cursor-pointer border-l-4 border-transparent',
                        detailId === apiId ? 'border-l-primary bg-muted/40' : 'focus-visible:ring-ring focus-visible:ring-2',
                      )}
                      aria-label={`Ouvrir la conversation ${rowLabel}`}
                      onClick={() => void openDetail(apiId)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault()
                          void openDetail(apiId)
                        }
                      }}
                    >
                      <TableCell className="align-top text-xs">
                        <span
                          className={cn(
                            'inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                            conversationProviderBadgeClass(sourceToProviderSlug(row.source, row.wing)),
                          )}
                        >
                          {conversationProviderLabel(sourceToProviderSlug(row.source, row.wing))}
                        </span>
                        <div className="text-muted-foreground mt-0.5 truncate font-mono text-[10px]">{row.source}</div>
                      </TableCell>
                      <TableCell className="truncate align-top text-xs" title={row.wing ?? ''}>
                        <div className="truncate">{row.wing ?? '—'}</div>
                        <div className="text-muted-foreground truncate font-mono text-[10px]" title={rowLabel}>
                          {rowLabel}
                        </div>
                      </TableCell>
                      <TableCell className="align-top text-xs whitespace-normal">
                        <p className="text-foreground line-clamp-2 leading-snug">
                          {(row.content_excerpt ?? '').replace(/\s+/g, ' ').slice(0, 320) || (
                            <span className="text-muted-foreground italic">(pas d&apos;extrait)</span>
                          )}
                        </p>
                      </TableCell>
                      <TableCell className="text-muted-foreground align-top text-right text-[11px] tabular-nums">
                        {showingSearch ? (
                          <span>{matchN} extrait{matchN > 1 ? 's' : ''}</span>
                        ) : (
                          <div className="flex flex-col items-end leading-tight">
                            <span>
                              <strong className="text-foreground">{browseRow.message_count}</strong> msg
                            </span>
                            <span className="text-[10px]">{browseRow.chunk_count} chunks</span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="align-top text-right">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          data-testid={`conversation-open-detail-${row.document_id}`}
                          onClick={(ev) => {
                            ev.stopPropagation()
                            void openDetail(apiId)
                          }}
                        >
                          Détail
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          ) : null}
        </CardContent>
      </Card>

      <Dialog
        open={detailId != null}
        onOpenChange={(o) => {
          if (!o) {
            setDetailId(null)
            setDetailDoc(null)
            setDetailLoading(false)
          }
        }}
      >
        <DialogContent
          className="flex h-[92vh] max-h-[92vh] w-[96vw] max-w-[1400px] flex-col gap-0 overflow-hidden p-0"
          data-testid="conversation-detail-dialog"
        >
          <DialogHeader className="bg-background/95 supports-backdrop-filter:backdrop-blur sticky top-0 z-10 flex flex-col gap-2 border-b px-5 py-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 flex-1 space-y-1 pr-12">
              <div className="flex flex-wrap items-center gap-2">
                {detailProviderSlug ? (
                  <span
                    className={cn(
                      'inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                      conversationProviderBadgeClass(detailProviderSlug),
                    )}
                  >
                    {conversationProviderLabel(detailProviderSlug)}
                  </span>
                ) : null}
                <DialogTitle className="truncate text-left leading-snug">
                  {detailDoc
                    ? shortPathLabel(detailDoc.path, detailDoc.wing) || 'Conversation'
                    : detailLoading
                      ? 'Chargement…'
                      : 'Conversation'}
                </DialogTitle>
              </div>
              {detailDoc ? (
                <DialogDescription className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-left text-xs">
                  <span className="font-mono">{String(detailDoc.source ?? '—')}</span>
                  {detailDoc.wing ? <span>· {detailDoc.wing}</span> : null}
                  {Array.isArray(detailDoc.messages) ? (
                    <span>· {detailDoc.messages.length} message{detailDoc.messages.length > 1 ? 's' : ''}</span>
                  ) : null}
                  {Array.isArray(detailDoc.chunks) ? (
                    <span>· {detailDoc.chunks.length} chunk{detailDoc.chunks.length > 1 ? 's' : ''}</span>
                  ) : null}
                </DialogDescription>
              ) : null}
              {detailDoc?.path ? (
                <div className="flex items-center gap-1.5">
                  <code className="text-muted-foreground bg-muted/60 max-w-full truncate rounded px-1.5 py-0.5 font-mono text-[11px]">
                    {String(detailDoc.path)}
                  </code>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    onClick={() => void copyDetailPath()}
                    aria-label="Copier le chemin"
                    title="Copier le chemin"
                  >
                    <HugeiconsIcon icon={Copy01Icon} size={14} strokeWidth={2} />
                  </Button>
                </div>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={goPrev}
                disabled={detailIndex <= 0}
                aria-label="Conversation précédente"
                data-testid="conversation-detail-prev"
              >
                <HugeiconsIcon icon={ArrowLeft01Icon} size={14} strokeWidth={2} className="mr-1" />
                Préc.
              </Button>
              <span className="text-muted-foreground hidden text-[11px] tabular-nums sm:inline">
                {detailIndex >= 0 ? `${detailIndex + 1}/${visibleRows.length}` : ''}
              </span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={goNext}
                disabled={detailIndex < 0 || detailIndex >= visibleRows.length - 1}
                aria-label="Conversation suivante"
                data-testid="conversation-detail-next"
              >
                Suiv.
                <HugeiconsIcon icon={ArrowRight01Icon} size={14} strokeWidth={2} className="ml-1" />
              </Button>
            </div>
          </DialogHeader>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {detailDoc ? (
              <div className="space-y-3 text-sm">
                {(detailDoc.messages ?? []).length > 0 ? (
                  <div className="space-y-3" data-testid="conversation-message-timeline">
                    {(detailDoc.messages ?? []).map((m, idx) => {
                      const time = formatMessageTime(m.timestamp)
                      return (
                        <article
                          key={`${String(m.line ?? idx)}-${m.role}-${idx}`}
                          className={cn('rounded-xl border p-3 text-sm shadow-xs', conversationMessageClass(m.role))}
                          data-testid="conversation-message"
                        >
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <span className="font-semibold">{m.label || m.role}</span>
                            {m.tool_name ? (
                              <span className="rounded-full bg-white/70 px-2 py-0.5 font-mono text-[11px] ring-1 ring-black/5">
                                {m.tool_name}
                              </span>
                            ) : null}
                            {time ? <span className="text-muted-foreground text-xs">{time}</span> : null}
                          </div>
                          <pre className="font-sans break-words whitespace-pre-wrap">{m.content}</pre>
                        </article>
                      )
                    })}
                  </div>
                ) : Array.isArray(detailDoc.chunks) && detailDoc.chunks.length > 0 ? (
                  <div
                    className="border-amber-300 bg-amber-50/90 text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-50 space-y-2 rounded-xl border p-3 text-xs"
                    data-testid="conversation-chunks-fallback"
                  >
                    <p className="font-medium">Pas de messages structurés en archive</p>
                    <p className="text-muted-foreground dark:text-amber-100/85">
                      Contenu affiché depuis l&apos;index de recherche (chunks). Une sync complète peut remplir la
                      colonne messages si le JSONL source est disponible.
                    </p>
                    <div className="space-y-2">
                      {detailDoc.chunks.map((c: Record<string, unknown>) => (
                        <div key={String(c.id)} className="bg-background/80 dark:bg-background/20 rounded-md p-2">
                          <div className="text-muted-foreground mb-1 font-mono">chunk {String(c.chunk_index)}</div>
                          <pre className="font-sans break-words whitespace-pre-wrap text-[13px] leading-relaxed">
                            {String(c.content ?? '')}
                          </pre>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : detailLoading ? (
                  <div className="space-y-2" aria-hidden>
                    <div className="bg-muted h-4 w-2/3 animate-pulse rounded" />
                    <div className="bg-muted h-24 w-full animate-pulse rounded" />
                    <div className="bg-muted h-24 w-full animate-pulse rounded" />
                  </div>
                ) : (
                  <p className="text-muted-foreground text-sm">
                    Conversation vide : ni messages archive ni chunks. Relancez une synchronisation depuis la machine où
                    se trouvent les JSONL agents.
                  </p>
                )}
                {(detailDoc.messages ?? []).length > 0 && Array.isArray(detailDoc.chunks) && detailDoc.chunks.length > 0 ? (
                  <details className="bg-muted/30 rounded-lg border p-3 text-xs">
                    <summary className="cursor-pointer font-medium select-none">
                      Voir chunks bruts (index recherche Postgres)
                    </summary>
                    <div className="mt-3 space-y-2">
                      {detailDoc.chunks.map((c: Record<string, unknown>) => (
                        <div key={String(c.id)} className="bg-muted/60 rounded-md p-2">
                          <div className="text-muted-foreground mb-1">chunk {String(c.chunk_index)}</div>
                          <pre className="font-sans break-words whitespace-pre-wrap">{String(c.content ?? '')}</pre>
                        </div>
                      ))}
                    </div>
                  </details>
                ) : null}
              </div>
            ) : (
              <div className="space-y-2" aria-hidden>
                <div className="bg-muted h-4 w-2/3 animate-pulse rounded" />
                <div className="bg-muted h-24 w-full animate-pulse rounded" />
                <div className="bg-muted h-24 w-full animate-pulse rounded" />
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
