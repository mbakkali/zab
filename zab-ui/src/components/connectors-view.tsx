import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  CloudServerIcon,
  CodeFolderIcon,
  Copy01Icon,
  Plug02Icon,
  RefreshIcon,
  Search01Icon,
  Tick02Icon,
} from '@hugeicons/core-free-icons'
import { AlertTriangle, CheckCircle2, Loader2, XCircle } from 'lucide-react'
import { connectorMeta, kindMeta } from '@/lib/connector-meta'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n/use-i18n'
import { LoadingState } from '@/components/ui/loading-state'
import { toast } from 'sonner'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button, buttonVariants } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

const USER_CONFIG_KEY = 'user_zab_config'
const USER_CONFIG_PATH = '~/.config/zab/config.yaml'

type ConnectorSummary = {
  id: string
  display_name: string
  tags: string[]
  form_count: number
  kind_badges: string[]
  transport_badges: string[]
  any_enabled: boolean
  preview_target: string
}

type ConnectorForm = {
  id: string
  kind: string
  transport_kind: string
  enabled: boolean
  target: string
  note?: string | null
  source_label?: string
  config_path?: string | null
  source_ref?: string
  meta?: Record<string, unknown>
}

type ConnectorsApiList = {
  data: ConnectorSummary[]
  pagination: { page: number; limit: number; total: number; total_pages: number }
}

type ConnectorDetailType = {
  id: string
  display_name: string
  tags?: string[]
  forms: ConnectorForm[]
}

type CheckStatus = 'ok' | 'warn' | 'fail' | 'pending' | 'running'

type CheckItem = {
  id: string
  form_id: string
  label: string
  status: CheckStatus
  message: string
  detail?: Record<string, unknown>
}

type CheckDescriptor = {
  id: string
  form_id: string
  label: string
}

type ConnectorCheckPayload = {
  slug: string
  display_name: string
  checks: CheckItem[]
  total: number
  ok: number
  warn: number
  fail: number
}

type GlobalRegistryEntry = {
  slug: string
  display_name: string
  form_count: number
}

type GlobalSummary = {
  connectors_total: number
  total: number
  ok: number
  warn: number
  fail: number
}

type OriginFilter = 'all' | 'local-mcp' | 'composio'

type McpSyncStatusApi = {
  generated_at_utc?: string
  sources?: {
    cursor_user?: { path: string; exists: boolean }
    claude_desktop_user?: { path: string; exists: boolean }
  }
  sources_scanned_counts?: Record<string, number>
  counts?: {
    servers_total?: number
    slugs_unique?: number
    stdio?: number
    http?: number
    conflict_slugs?: number
    orphan_registry?: number
  }
  conflict_slugs?: string[]
  explain_zero_local_mcp?: string
  mcps_packages_hints?: Array<{
    package_count: number
    mcps_dir: string
    skills_repo_root: string
    package_names: string[]
  }>
}

function McpSyncPanel({
  onScanComplete,
  onOpenGlobalCheck,
  disableGlobalCheck,
}: {
  onScanComplete: () => void | Promise<void>
  onOpenGlobalCheck: () => void
  disableGlobalCheck: boolean
}) {
  const { t } = useI18n()
  const [status, setStatus] = useState<McpSyncStatusApi | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setError(null)
    try {
      const r = await fetch('/api/mcps/sync-status')
      if (!r.ok) throw new Error(await r.text())
      setStatus((await r.json()) as McpSyncStatusApi)
    } catch (e) {
      setStatus(null)
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const scan = async () => {
    setBusy(true)
    try {
      const r = await fetch('/api/mcps/scan', { method: 'POST' })
      const raw = await r.text()
      if (!r.ok) throw new Error(raw.slice(0, 400))
      await load()
      await onScanComplete()
      toast.success(t('connectors.mcpSync.toastScan'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const refreshIndex = async () => {
    setBusy(true)
    try {
      const r = await fetch('/api/sync', { method: 'POST' })
      if (!r.ok) throw new Error(await r.text())
      toast.success(t('connectors.mcpSync.toastIndex'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const c = status?.counts
  const cur = status?.sources?.cursor_user
  const cl = status?.sources?.claude_desktop_user

  return (
    <Card data-testid="mcp-sync-panel">
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t('connectors.mcpSync.title')}</CardTitle>
        <CardDescription>{t('connectors.mcpSync.description')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {error ? (
          <p className="text-destructive text-xs whitespace-pre-wrap" role="alert">
            {error}
          </p>
        ) : null}
        {status ? (
          <div className="text-muted-foreground grid gap-2 sm:grid-cols-2">
            <div>
              <span className="font-medium text-foreground">{t('connectors.mcpSync.sources')}</span>
              <ul className="mt-1 list-inside list-disc text-xs">
                <li>
                  Cursor user : {cur?.exists ? t('connectors.mcpSync.present') : t('connectors.mcpSync.absent')}
                  {cur?.path ? ` — ${cur.path}` : ''}
                </li>
                <li>
                  Claude Desktop : {cl?.exists ? t('connectors.mcpSync.present') : t('connectors.mcpSync.absent')}
                  {cl?.path ? ` — ${cl.path}` : ''}
                </li>
              </ul>
            </div>
            <div>
              <span className="font-medium text-foreground">{t('connectors.mcpSync.counters')}</span>
              <ul className="mt-1 list-inside list-disc text-xs">
                <li>
                  {t('connectors.mcpSync.serversDetected')} : {c?.servers_total ?? 0}
                </li>
                <li>
                  {t('connectors.mcpSync.uniqueSlugs')} : {c?.slugs_unique ?? 0}
                </li>
                <li>
                  stdio / http : {c?.stdio ?? 0} / {c?.http ?? 0}
                </li>
                <li>
                  {t('connectors.mcpSync.conflicts')} : {c?.conflict_slugs ?? 0}
                </li>
              </ul>
            </div>
            {status.sources_scanned_counts && Object.keys(status.sources_scanned_counts).length > 0 ? (
              <div className="sm:col-span-2">
                <span className="font-medium text-foreground">{t('connectors.mcpSync.byOrigin')}</span>
                <p className="text-xs">
                  {Object.entries(status.sources_scanned_counts)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(' · ')}
                </p>
              </div>
            ) : null}
            {status.conflict_slugs && status.conflict_slugs.length > 0 ? (
              <div className="sm:col-span-2 rounded-md border border-alerte/35 bg-alerte/10 px-3 py-2 text-xs text-alerte">
                {t('connectors.mcpSync.conflictsList')} : {status.conflict_slugs.join(', ')}
              </div>
            ) : null}
            {status.explain_zero_local_mcp ? (
              <div className="text-muted-foreground sm:col-span-2 text-xs">{status.explain_zero_local_mcp}</div>
            ) : null}
          </div>
        ) : !error ? (
          <p className="text-muted-foreground text-xs">{t('connectors.mcpSync.loadingStatus')}</p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => void load()}>
            <HugeiconsIcon icon={RefreshIcon} size={16} className="mr-1.5" />
            {t('connectors.mcpSync.refreshStatus')}
          </Button>
          <Button type="button" size="sm" variant="default" disabled={busy} onClick={() => void scan()}>
            {busy ? (
              <>
                <Loader2 className="mr-1.5 size-4 animate-spin" />
                {t('connectors.mcpSync.scanning')}
              </>
            ) : (
              t('connectors.mcpSync.scan')
            )}
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void refreshIndex()}>
            {t('connectors.mcpSync.refreshIndex')}
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={busy || disableGlobalCheck} onClick={onOpenGlobalCheck}>
            {t('connectors.checkAll')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

type ConfigFileSummary = {
  key: string
  title: string
  syntax: string
  exists: boolean
  path_display: string
  hint?: string | null
}

const CONFIG_FILE_ROW_FALLBACK: ConfigFileSummary = {
  key: USER_CONFIG_KEY,
  title: USER_CONFIG_PATH,
  syntax: 'yaml',
  exists: false,
  path_display: USER_CONFIG_PATH,
  hint: 'skills_roots, cli_watchlist, local_tools_path, …',
}

function fallbackRowMeta(key: string): ConfigFileSummary | undefined {
  return key === USER_CONFIG_KEY ? CONFIG_FILE_ROW_FALLBACK : undefined
}

function isComposioConnector(row: ConnectorSummary): boolean {
  return row.tags.includes('composio') || row.kind_badges.includes('composio')
}

function isLocalMcpConnector(row: ConnectorSummary): boolean {
  return (
    row.kind_badges.includes('mcp') &&
    row.transport_badges.includes('stdio') &&
    !isComposioConnector(row)
  )
}

function connectorOriginLabel(row: ConnectorSummary): { label: string; tone: string } | null {
  if (isComposioConnector(row)) {
    return {
      label: 'Composio',
      tone: 'bg-muted text-foreground ring-1 ring-ring/40',
    }
  }
  if (isLocalMcpConnector(row)) {
    return {
      label: 'MCP local',
      tone: 'bg-alerte/10 text-alerte ring-1 ring-alerte/35',
    }
  }
  if (row.kind_badges.includes('mcp') && row.transport_badges.some((t) => t === 'http' || t === 'sse')) {
    return {
      label: 'MCP distant',
      tone: 'bg-info/10 text-info ring-1 ring-info/35',
    }
  }
  return null
}

function CheckStatusIcon({ status }: { status: CheckStatus }) {
  if (status === 'ok') return <CheckCircle2 className="size-4 shrink-0 text-succes" />
  if (status === 'warn') return <AlertTriangle className="size-4 shrink-0 text-alerte" />
  if (status === 'fail') return <XCircle className="size-4 shrink-0 text-danger" />
  if (status === 'running') return <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
  return <span className="inline-block size-4 shrink-0 rounded-full border border-border" />
}

function checkStatusLabel(status: CheckStatus): string {
  if (status === 'ok') return 'OK'
  if (status === 'warn') return 'À surveiller'
  if (status === 'fail') return 'KO'
  if (status === 'running') return 'En cours…'
  return 'En attente'
}

/** Détecte l’erreur « backend sans routes agrégateur / config». */
export function detectsStaleZabAggregatorBackend(message: string | null): boolean {
  return Boolean(message && message.includes('uv run zab dashboard'))
}

/** Message lisible lorsque uvicorn tourne encore sur une ancienne version du backend. */
function staleConnectorsMessage(httpStatus: number, rawDetail: string): string {
  return [
    `L’agrégateur de connecteurs n’est pas disponible sur ce serveur (HTTP ${httpStatus}).`,
    'Arrête ce processus avec Ctrl+C, puis depuis la racine du dépôt zab exécute :',
    '`uv run zab dashboard --no-open --port 8742`',
    "(ou le port qui t’arrange ; en dev Vite doit proxy vers ce même backend).",
    rawDetail.trim() ? `Réponse brute : ${rawDetail.trim().slice(0, 280)}` : '',
  ]
    .filter(Boolean)
    .join('\n')
}

export function ConnectorsView() {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [activeKind, setActiveKind] = useState<string>('all')
  const [activeTag, setActiveTag] = useState<string | null>(null)
  const [activeOrigin, setActiveOrigin] = useState<OriginFilter>('all')
  const [list, setList] = useState<ConnectorSummary[]>([])
  const [pagination, setPagination] = useState<ConnectorsApiList['pagination'] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [detailSlug, setDetailSlug] = useState<string | null>(null)
  const [detail, setDetail] = useState<ConnectorDetailType | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [globalCheckOpen, setGlobalCheckOpen] = useState(false)

  const loadList = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const q = encodeURIComponent(query.trim())
      const tagParam = activeTag ? `&tag=${encodeURIComponent(activeTag)}` : ''
      const r = await fetch(`/api/connectors?limit=200&q=${q}${tagParam}`)
      const text = await r.text()
      if (!r.ok) {
        setPagination(null)
        setList([])
        if (r.status === 404) {
          setLoadError(staleConnectorsMessage(404, text))
        } else {
          let detail = text
          try {
            const parsed = JSON.parse(text) as { detail?: unknown }
            if (typeof parsed.detail === 'string') detail = parsed.detail
          } catch {
            /* raw */
          }
          setLoadError(`Erreur API connecteurs (${r.status}) : ${detail.slice(0, 400)}`)
        }
        return
      }
      const data = JSON.parse(text) as ConnectorsApiList
      setList(data.data)
      setPagination(data.pagination)
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e))
      setPagination(null)
      setList([])
    } finally {
      setLoading(false)
    }
  }, [query, activeTag])

  useEffect(() => {
    const t = window.setTimeout(() => void loadList(), 280)
    return () => window.clearTimeout(t)
  }, [loadList])

  useEffect(() => {
    if (!detailSlug) {
      setDetail(null)
      return
    }
    setDetailLoading(true)
    void (async () => {
      try {
        const r = await fetch(`/api/connectors/${encodeURIComponent(detailSlug)}`)
        const text = await r.text()
        if (!r.ok) {
          toast.error(
            r.status === 404
              ? staleConnectorsMessage(404, text)
              : `Détail indisponible (${r.status})`,
          )
          setDetailSlug(null)
          setDetail(null)
          return
        }
        setDetail(JSON.parse(text) as ConnectorDetailType)
      } catch {
        toast.error(`Détail indisponible pour ${detailSlug}`)
        setDetailSlug(null)
        setDetail(null)
      } finally {
        setDetailLoading(false)
      }
    })()
  }, [detailSlug])

  const kindOptions = useMemo(() => {
    const s = new Set<string>()
    for (const row of list) {
      for (const k of row.kind_badges) s.add(k)
    }
    return Array.from(s).sort()
  }, [list])

  const filtered = useMemo(() => {
    return list.filter((row) => {
      if (activeKind !== 'all' && !row.kind_badges.some((k) => k.toLowerCase() === activeKind.toLowerCase())) {
        return false
      }
      if (activeOrigin === 'local-mcp' && !isLocalMcpConnector(row)) return false
      if (activeOrigin === 'composio' && !isComposioConnector(row)) return false
      return true
    })
  }, [list, activeKind, activeOrigin])

  const originStats = useMemo(() => {
    const localMcp = list.filter(isLocalMcpConnector).length
    const composio = list.filter(isComposioConnector).length
    return { localMcp, composio }
  }, [list])

  const stats = useMemo(() => {
    const total = filtered.length
    const enabled = filtered.filter((e) => e.any_enabled).length
    const forms = filtered.reduce((a, x) => a + x.form_count, 0)
    return { total, enabled, forms }
  }, [filtered])

  const backendNeedsRestartForAggregators = detectsStaleZabAggregatorBackend(loadError)

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-semibold tracking-tight">{t('connectors.title')}</h2>
          <p className="text-muted-foreground text-sm" data-testid="connectors-subtitle">
            {t('connectors.subtitleActive', {
              active: String(stats.enabled),
              forms: String(stats.forms),
              total: String(stats.total),
              mcp: String(originStats.localMcp),
            })}
          </p>
        </div>
        <Button
          type="button"
          variant="default"
          size="sm"
          data-testid="connectors-check-all-btn"
          onClick={() => setGlobalCheckOpen(true)}
          disabled={loading || list.length === 0}
        >
          <HugeiconsIcon icon={RefreshIcon} size={16} className="mr-1.5" />
          {t('connectors.checkAll')}
        </Button>
      </header>

      <McpSyncPanel
        onScanComplete={async () => {
          await loadList()
        }}
        onOpenGlobalCheck={() => setGlobalCheckOpen(true)}
        disableGlobalCheck={loading || list.length === 0}
      />

      {backendNeedsRestartForAggregators && loadError ? (
        <div
          role="alert"
          data-testid="connectors-stale-backend-notice"
          className="text-destructive space-y-2 rounded-xl border border-danger/35 bg-danger/10 px-4 py-3 text-sm whitespace-pre-wrap"
        >
          {loadError}
        </div>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full max-w-sm">
          <HugeiconsIcon
            icon={Search01Icon}
            size={16}
            className="text-muted-foreground absolute top-1/2 left-3 -translate-y-1/2"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('connectors.searchPlaceholder')}
            aria-label={t('connectors.searchAria')}
            className="border-input bg-background w-full rounded-lg border py-2 pr-3 pl-9 text-sm outline-none transition focus:ring-2 focus:ring-ring/40"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <KindChip active={activeKind === 'all'} onClick={() => setActiveKind('all')}>
            {t('connectors.filter.all')} · {list.length}
          </KindChip>
          {kindOptions.map((k) => (
            <KindChip key={k} active={activeKind === k} onClick={() => setActiveKind(k)}>
              {k.toUpperCase()}
            </KindChip>
          ))}
          <KindChip
            active={activeOrigin === 'local-mcp'}
            onClick={() => {
              const enable = activeOrigin !== 'local-mcp'
              setActiveOrigin(enable ? 'local-mcp' : 'all')
              if (enable) setActiveTag(null)
            }}
          >
            {t('connectors.filter.mcpLocal')} · {originStats.localMcp}
          </KindChip>
          <KindChip
            active={activeOrigin === 'composio'}
            onClick={() => {
              const enable = activeOrigin !== 'composio'
              setActiveOrigin(enable ? 'composio' : 'all')
              setActiveTag(enable ? 'composio' : null)
            }}
          >
            Composio · {originStats.composio}
          </KindChip>
        </div>
      </div>

      {loading && list.length === 0 ? <LoadingState compact label={t('common.loading')} /> : null}
      {loadError && !backendNeedsRestartForAggregators && (
        <div className="text-destructive space-y-2 rounded-xl border border-danger/35 bg-danger/10 px-4 py-3 text-sm whitespace-pre-wrap">
          <p role="alert" data-testid="connectors-load-error">
            {loadError}
          </p>
        </div>
      )}
      {pagination && (
        <p className="text-muted-foreground text-xs">
          {t('common.pageOf', { page: String(pagination.page), total: String(pagination.total_pages) })} ·{' '}
          {t('common.results', { count: String(pagination.total) })}
        </p>
      )}

      <div
        data-testid="connectors-grid"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      >
        {filtered.map((row) => (
          <ConnectorCard key={row.id} row={row} onDetail={() => setDetailSlug(row.id)} />
        ))}
      </div>

      {filtered.length === 0 && !loading && (
        <div className="text-muted-foreground rounded-xl border border-dashed py-16 text-center text-sm space-y-1">
          <p>{t('connectors.empty')}</p>
          {backendNeedsRestartForAggregators ? (
            <p className="text-xs opacity-90">
              {t('connectors.emptyRestartHint')}
            </p>
          ) : null}
        </div>
      )}

      <ConnectorDetailDialog
        open={Boolean(detailSlug)}
        loading={detailLoading}
        detail={detail}
        slug={detailSlug}
        onOpenChange={(o) => {
          if (!o) setDetailSlug(null)
        }}
        onTest={async (formId) => {
          const slug = formId.replace('api-', '')
          if (!['litellm', 'openrouter'].includes(slug)) {
            toast.error('Test non disponible pour ce connecteur')
            return
          }
          try {
            const r = await fetch(`/api/tools/probe?kind=${slug}`)
            const data = (await r.json()) as { ok?: boolean; status_code?: number; error?: string }
            if (data.ok) toast.success(`Connecteur ${slug} OK (${data.status_code})`)
            else toast.error(`Connecteur ${slug} : ${data.error || 'échec'}`)
          } catch (e) {
            toast.error(e instanceof Error ? e.message : String(e))
          }
        }}
      />

      <ConnectorsGlobalCheckDialog
        open={globalCheckOpen}
        onOpenChange={setGlobalCheckOpen}
      />
    </div>
  )
}

export function ConnectorsConfigFilesPanel({ aggregatorStale }: { aggregatorStale?: boolean }) {
  const [rows, setRows] = useState<ConfigFileSummary[]>([])
  const [chosen] = useState<string>(USER_CONFIG_KEY)
  const [content, setContent] = useState<string>('')
  const [draft, setDraft] = useState('')
  const [meta, setMeta] = useState<{
    path_display: string
    exists: boolean
    truncate_note?: string | null
    syntax: string
  } | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [reloadNonce, setReloadNonce] = useState(0)

  useEffect(() => {
    setDraft(content)
  }, [content])

  useEffect(() => {
    void (async () => {
      setBusy(true)
      setBanner(null)
      try {
        const r = await fetch('/api/config/files')
        const t = await r.text()
        if (!r.ok) {
          if (r.status === 404) {
            if (!aggregatorStale) setBanner(staleConnectorsMessage(404, t))
          } else {
            setBanner(`Impossible de lister les configs (${r.status}).`)
          }
          setRows([CONFIG_FILE_ROW_FALLBACK])
        } else {
          const list = JSON.parse(t) as ConfigFileSummary[]
          const row =
            list.find((x) => x.key === USER_CONFIG_KEY) ?? list[0] ?? CONFIG_FILE_ROW_FALLBACK
          setRows([row])
        }
      } catch {
        setBanner('Erreur réseau lors du chargement des chemins config.')
        setRows([CONFIG_FILE_ROW_FALLBACK])
      } finally {
        setBusy(false)
      }
    })()
  }, [aggregatorStale])

  useEffect(() => {
    if (!chosen) return
    void (async () => {
      if (!aggregatorStale) setBanner(null)
      try {
        const r = await fetch(`/api/config/file?key=${encodeURIComponent(chosen)}`)
        const t = await r.text()
        if (!r.ok) {
          setContent('')
          setMeta(null)
          if (r.status === 404) {
            if (aggregatorStale) {
              const fb = fallbackRowMeta(chosen)
              setMeta(
                fb
                  ? {
                      path_display: fb.path_display,
                      exists: fb.exists,
                      syntax: fb.syntax === 'json' ? 'json' : 'yaml',
                      truncate_note: null,
                    }
                  : null,
              )
              setContent(
                [
                  '# Aperçu non disponible (backend à jour nécessaire)',
                  '',
                  'La route `/api/config/file` n’existe pas sur ce serveur : redémarrage requis comme ci‑dessus.',
                  '',
                  fb ? `Référence attendue dans le repo : \`${fb.path_display}\`.` : '',
                ].join('\n'),
              )
            } else setBanner(staleConnectorsMessage(404, t))
          } else {
            setBanner(`Erreur lecture fichier (${r.status}).`)
          }
          return
        }
        const j = JSON.parse(t) as {
          exists: boolean
          path_display: string
          content: string
          truncate_note?: string | null
          syntax: string
          error?: string | null
        }
        setMeta({
          exists: j.exists,
          path_display: j.path_display,
          truncate_note: j.truncate_note,
          syntax: j.syntax,
        })
        setContent(
          !j.exists
            ? `# Fichier absent sur ce poste :\n${j.path_display}\n\nCréez-le avec « zab config --open » ou depuis le dashboard Configuration.`
            : j.content || (j.error ? `# ${j.error}` : ''),
        )
      } catch {
        setContent('')
      }
    })()
  }, [chosen, aggregatorStale, reloadNonce])

  const editable = chosen === USER_CONFIG_KEY

  const saveYaml = async () => {
    setSaving(true)
    try {
      const r = await fetch(`/api/config/file?key=${encodeURIComponent(chosen)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft }),
      })
      const errText = await r.text()
      if (!r.ok) throw new Error(errText || r.statusText)
      toast.success('Fichier enregistré')
      setReloadNonce((n) => n + 1)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card data-testid="connectors-config-panel" size="sm" className="border-border">
      <CardHeader className="border-b border-border pb-4">
        <CardTitle>Configuration zab</CardTitle>
        <CardDescription>
          Édition de <code className="text-xs">{USER_CONFIG_PATH}</code>. Ajoutez des binaires dans{' '}
          <code className="text-xs">cli_watchlist</code> pour le scan <code className="text-xs">which</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-4">
        {busy ? (
          <p className="text-muted-foreground text-xs">Chargement des chemins…</p>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <span className="text-muted-foreground text-xs font-medium whitespace-nowrap">Fichier</span>
            <code className="border-input bg-background break-all rounded-lg border px-3 py-2 font-mono text-xs sm:flex-1">
              {(rows[0] ?? CONFIG_FILE_ROW_FALLBACK).path_display}
              {!(rows[0] ?? CONFIG_FILE_ROW_FALLBACK).exists ? ' (absent)' : ''}
            </code>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(editable ? draft : content).then(
                  () => toast.success('Contenu copié'),
                  () => toast.error('Copie impossible'),
                )
              }}
            >
              Copier
            </Button>
            {editable ? (
              <>
                <Button type="button" variant="secondary" size="sm" disabled={saving} onClick={() => setReloadNonce((n) => n + 1)}>
                  Recharger
                </Button>
                <Button type="button" size="sm" disabled={saving} onClick={() => void saveYaml()}>
                  {saving ? '…' : 'Enregistrer'}
                </Button>
              </>
            ) : null}
          </div>
        )}
        {banner && (
          <p className="text-destructive whitespace-pre-wrap text-xs" role="status">
            {banner}
          </p>
        )}
        {meta && (
          <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <code className="bg-muted rounded px-1.5 py-0.5 break-all">{meta.path_display}</code>
            {!meta.exists && <span>(fichier manquant ou non résolu depuis l’IDE)</span>}
            <a
              href={`vscode://file/${meta.path_display}`}
              className={buttonVariants({ variant: 'outline', size: 'sm' })}
              title="Ouvrir dans VS Code / Cursor"
            >
              Ouvrir dans l’éditeur
            </a>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground text-[11px] underline"
              onClick={() => {
                void navigator.clipboard
                  .writeText(meta.path_display)
                  .then(() => toast.success('Chemin copié'))
                  .catch(() => toast.error('Impossible de copier'))
              }}
            >
              Copier chemin
            </button>
          </div>
        )}
        {meta?.truncate_note && (
          <p className="text-alerte text-[11px]">Aperçu tronqué : {meta.truncate_note}</p>
        )}
        {editable ? (
          <Textarea
            data-testid="connectors-config-pre"
            className="border-border bg-background font-mono text-[11px] leading-relaxed min-h-[min(340px,50vh)]"
            spellCheck={false}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        ) : (
          <pre
            data-testid="connectors-config-pre"
            className="border-border bg-muted/40 max-h-[min(340px,50vh)] overflow-auto rounded-lg border p-3 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words"
          >
            {content || '—'}
          </pre>
        )}
      </CardContent>
    </Card>
  )
}

function KindChip({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      type="button"
      className={cn(
        'rounded-full border px-3 py-1 text-xs font-medium transition',
        active
          ? 'border-border bg-primary text-primary-foreground'
          : 'border-border bg-card text-muted-foreground hover:border-border',
      )}
    >
      {children}
    </button>
  )
}

function ConnectorCard({ row, onDetail }: { row: ConnectorSummary; onDetail: () => void }) {
  const { t } = useI18n()
  const meta = connectorMeta(row.display_name || row.id)
  const primaryTransport = row.transport_badges[0] || row.kind_badges[0] || ''
  const k = kindMeta(primaryTransport || 'stdio')
  const origin = connectorOriginLabel(row)

  return (
    <div className="group bg-card hover:border-border hover:shadow-sm relative flex flex-col gap-4 rounded-xl border border-border p-5 transition">
      <div className="flex items-start justify-between gap-3">
        <div
          className={cn(
            'flex size-14 items-center justify-center rounded-2xl ring-1',
            meta.tone,
            meta.ringTone,
          )}
        >
          <HugeiconsIcon icon={meta.icon} size={32} strokeWidth={1.6} />
        </div>
        <SummaryStatus enabled={row.any_enabled} />
      </div>

      <div className="space-y-1">
        <h3 className="text-base font-semibold tracking-tight">{row.display_name}</h3>
        <p className="text-muted-foreground text-xs font-mono">{row.id}</p>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {origin ? (
          <span className={cn('inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold', origin.tone)}>
            {origin.label}
          </span>
        ) : null}
        {row.kind_badges.map((kb) => (
          <span
            key={kb}
            className="bg-primary/10 text-primary inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize"
          >
            {kb}
          </span>
        ))}
        <span
          className={cn(
            'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
            k.tone,
          )}
        >
          <HugeiconsIcon icon={k.icon} size={12} strokeWidth={2} />
          {primaryTransport || '—'}
        </span>
        {row.form_count > 1 && (
          <span className="inline-flex rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground ring-1 ring-ring/40">
            {row.form_count} {row.kind_badges.includes('composio') && row.kind_badges.length === 1 ? 'comptes' : 'formes'}
          </span>
        )}
        {(row.tags ?? []).map((t) => (
          <span
            key={t}
            className="inline-flex rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground ring-1 ring-ring/40 capitalize"
          >
            {t}
          </span>
        ))}
      </div>

      {row.preview_target && (
        <div className="bg-muted/60 group-hover:bg-muted relative rounded-lg px-3 py-2 transition">
          <code className="text-muted-foreground line-clamp-2 block pr-7 font-mono text-[11px] break-all">
            {row.preview_target}
          </code>
          <button
            type="button"
            aria-label="Copier la cible"
            onClick={() => {
              void navigator.clipboard
                .writeText(row.preview_target)
                .then(() => toast.success('Cible copiée'))
                .catch(() => toast.error('Impossible de copier'))
            }}
            className="absolute top-1.5 right-1.5 rounded-md p-1 text-muted-foreground opacity-0 transition hover:bg-muted hover:text-foreground group-hover:opacity-100"
          >
            <HugeiconsIcon icon={Copy01Icon} size={14} />
          </button>
        </div>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-full"
        data-testid="connector-view-btn"
        onClick={onDetail}
      >
        {t('common.view')}
      </Button>
    </div>
  )
}

function SummaryStatus({ enabled }: { enabled: boolean }) {
  const { t } = useI18n()
  if (enabled) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-succes/10 px-2 py-1 text-[11px] font-medium text-succes ring-1 ring-succes/35">
        <HugeiconsIcon icon={Tick02Icon} size={12} strokeWidth={2} />
        {t('connectors.status.active')}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground ring-1 ring-ring/40">
      {t('connectors.status.disabled')}
    </span>
  )
}

function ConnectorDetailDialog({
  open,
  loading,
  detail,
  slug,
  onOpenChange,
  onTest,
}: {
  open: boolean
  loading: boolean
  detail: ConnectorDetailType | null
  slug: string | null
  onOpenChange: (open: boolean) => void
  onTest?: (formId: string) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[min(90vh,720px)] w-full max-w-lg overflow-y-auto sm:max-w-lg"
        data-testid="connector-detail-dialog"
      >
        {loading ? (
          <p className="text-muted-foreground text-sm">Chargement du détail…</p>
        ) : detail ? (
          <>
            <DialogHeader>
              <DialogTitle>{detail.display_name}</DialogTitle>
              <DialogDescription className="font-mono text-xs">{detail.id}</DialogDescription>
            </DialogHeader>
            {slug && open ? <ConnectorCheckPanel slug={slug} /> : null}
            <div className="space-y-4 pt-2" data-testid="connector-forms-list">
              {detail.forms.map((f) => (
                <div key={f.id} className="space-y-2 rounded-lg border border-border bg-muted/80 p-3">
                  <div className="flex flex-wrap gap-2 text-[11px] font-medium capitalize">
                    <span className="bg-background rounded-full px-2 py-0.5 ring-1">{f.kind}</span>
                    <span className="bg-background rounded-full px-2 py-0.5 ring-1">{f.transport_kind}</span>
                    <span className={f.enabled ? 'text-succes' : 'text-muted-foreground'}>{f.enabled ? 'activé' : 'désactivé'}</span>
                    {f.kind === 'composio' ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-foreground ring-1 ring-ring/40">
                        Composio
                      </span>
                    ) : (
                      <span
                        className={cn(
                          'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
                          f.transport_kind === 'stdio'
                            ? 'bg-alerte/10 text-alerte ring-1 ring-alerte/35'
                            : 'bg-info/10 text-info ring-1 ring-info/35',
                        )}
                      >
                        {f.transport_kind === 'stdio' ? 'MCP local' : 'MCP distant'}
                      </span>
                    )}
                  </div>
                  <div>
                    <p className="text-muted-foreground text-[11px] font-medium uppercase">Cible</p>
                    <code className="mt-1 block whitespace-pre-wrap break-all text-xs">{f.target}</code>
                  </div>
                  {f.kind === 'mcp' &&
                    (() => {
                      const cmd = f.meta?.command
                      if (typeof cmd !== 'string' || !cmd.trim()) return null
                      const rawArgs = f.meta?.args
                      const args = Array.isArray(rawArgs)
                        ? rawArgs.filter((x): x is string => typeof x === 'string')
                        : []
                      return (
                        <div>
                          <p className="text-muted-foreground text-[11px] font-medium uppercase">Commande</p>
                          <code className="mt-1 block whitespace-pre-wrap break-all text-xs">
                            {cmd}
                            {args.length > 0 ? ` ${args.join(' ')}` : ''}
                          </code>
                        </div>
                      )
                    })()}
                  {f.source_label && (
                    <div data-testid="connector-form-source">
                      <p className="text-muted-foreground text-[11px] font-medium uppercase">Source</p>
                      <p className="text-xs">{f.source_label}</p>
                      {f.source_ref && <p className="font-mono text-[11px] text-muted-foreground">{f.source_ref}</p>}
                    </div>
                  )}
                  <SourceOpenRow path={f.config_path ?? undefined} />
                  {f.kind === 'mcp' && Array.isArray(f.meta?.env_vars) && (f.meta?.env_vars as string[]).length > 0 && (
                    <div>
                      <p className="text-muted-foreground text-[11px] font-medium uppercase">Variables</p>
                      <ul className="mt-1 list-inside list-disc text-xs">
                        {(f.meta?.env_vars as string[]).map((v) => (
                          <li key={v} className="font-mono">
                            {v}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {f.kind === 'composio' && f.meta && (
                    <div className="space-y-1 text-xs" data-testid="connector-composio-meta">
                      <p>
                        <span className="text-muted-foreground">Toolkit : </span>
                        <span className="font-mono">{String(f.meta.toolkit_slug ?? '—')}</span>
                      </p>
                      {(f.meta.account_email || f.meta.account_label) ? (
                        <p>
                          <span className="text-muted-foreground">Compte : </span>
                          <span className="font-mono">{String(f.meta.account_email ?? f.meta.account_label)}</span>
                        </p>
                      ) : null}
                      {f.meta.user_id ? (
                        <p>
                          <span className="text-muted-foreground">User ID : </span>
                          <span className="font-mono">{String(f.meta.user_id)}</span>
                        </p>
                      ) : null}
                      <p>
                        <span className="text-muted-foreground">Auth : </span>
                        <span className="font-mono">{String(f.meta.auth_scheme ?? '—')}</span>
                      </p>
                      <p>
                        <span className="text-muted-foreground">Account ID : </span>
                        <span className="font-mono">{String(f.meta.connected_account_id ?? '—')}</span>
                      </p>
                      <p>
                        <span className="text-muted-foreground">Statut : </span>
                        <span className="font-mono">{String(f.meta.status ?? '—')}</span>
                      </p>
                      {f.meta.mcp_url ? (
                        <p>
                          <span className="text-muted-foreground">MCP : </span>
                          <span className="font-mono break-all">{String(f.meta.mcp_url)}</span>
                        </p>
                      ) : null}
                    </div>
                  )}
                  {f.kind === 'api' && f.meta && (
                    <div className="space-y-2 text-xs">
                      {(f.meta.base_url != null || f.meta.api_key_env != null) && (
                        <p data-testid="connector-api-meta">
                          {String(f.meta.base_url ?? '')}{' '}
                          <span className="font-mono">· env: {String(f.meta.api_key_env ?? '—')}</span>
                        </p>
                      )}
                      {onTest && (
                        <Button variant="outline" size="sm" onClick={() => onTest(f.id)}>
                          Tester la connexion
                        </Button>
                      )}
                    </div>
                  )}
                  {f.note && <p className="text-muted-foreground text-[11px]">{f.note}</p>}
                </div>
              ))}
            </div>
          </>
        ) : (
          <p className="text-muted-foreground text-sm">—</p>
        )}
      </DialogContent>
    </Dialog>
  )
}

function SourceOpenRow({ path }: { path?: string }) {
  if (!path) return null
  const vscodeHref = path.startsWith('http') ? path : `vscode://file${path}`
  return (
    <div className="flex flex-wrap items-center gap-2">
      <a href={vscodeHref} className={buttonVariants({ variant: 'outline', size: 'sm' })}>
        Ouvrir dans l&apos;éditeur
      </a>
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground text-[11px] underline"
        onClick={() => {
          void navigator.clipboard
            .writeText(path)
            .then(() => toast.success('Chemin copié'))
            .catch(() => toast.error('Impossible de copier'))
        }}
      >
        Copier chemin absolu
      </button>
    </div>
  )
}

function ConnectorsGlobalCheckDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [registry, setRegistry] = useState<GlobalRegistryEntry[]>([])
  const [results, setResults] = useState<Record<string, ConnectorCheckPayload>>({})
  const [summary, setSummary] = useState<GlobalSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const doneRef = useRef(false)
  const esRef = useRef<EventSource | null>(null)

  const stopStream = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
  }, [])

  const runCheck = useCallback(() => {
    stopStream()
    setLoading(true)
    setError(null)
    setSummary(null)
    setRegistry([])
    setResults({})
    doneRef.current = false

    const es = new EventSource('/api/connectors-check/stream')
    esRef.current = es

    es.addEventListener('registry', (ev) => {
      try {
        setRegistry(JSON.parse(ev.data) as GlobalRegistryEntry[])
      } catch {
        /* ignore */
      }
    })

    es.addEventListener('connector', (ev) => {
      try {
        const payload = JSON.parse(ev.data) as ConnectorCheckPayload
        setResults((prev) => ({ ...prev, [payload.slug]: payload }))
      } catch {
        /* ignore */
      }
    })

    const finish = (s?: GlobalSummary) => {
      if (doneRef.current) return
      doneRef.current = true
      stopStream()
      setLoading(false)
      if (s) {
        setSummary(s)
        toast.success(`Vérification terminée : ${s.ok} OK · ${s.warn} à surveiller · ${s.fail} KO`)
      }
    }

    es.addEventListener('done', (ev) => {
      try {
        finish(JSON.parse(ev.data) as GlobalSummary)
      } catch {
        finish()
      }
    })

    es.onerror = () => {
      if (!doneRef.current) {
        setError('Flux de vérification interrompu')
        finish()
      }
    }
  }, [stopStream])

  useEffect(() => {
    if (open) runCheck()
    else stopStream()
    return () => stopStream()
  }, [open, runCheck, stopStream])

  const doneCount = Object.keys(results).length
  const totalCount = registry.length

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[min(90vh,720px)] w-full max-w-2xl overflow-y-auto" data-testid="connectors-global-check-dialog">
        <DialogHeader>
          <DialogTitle>Vérification globale</DialogTitle>
          <DialogDescription>
            Checks read-only sur MCP locaux, proxies API et comptes Composio.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-muted-foreground text-xs">
            {loading
              ? `${doneCount}/${totalCount || '…'} connecteur(s) vérifié(s)`
              : summary
                ? `${summary.connectors_total} connecteur(s) · ${summary.ok} OK · ${summary.warn} à surveiller · ${summary.fail} KO`
                : 'Prêt'}
          </p>
          <Button type="button" size="sm" variant="outline" disabled={loading} onClick={runCheck} data-testid="connectors-global-check-rerun">
            {loading ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : <HugeiconsIcon icon={RefreshIcon} size={14} className="mr-1.5" />}
            Relancer
          </Button>
        </div>

        {error ? <p className="text-destructive text-xs">{error}</p> : null}

        <div className="space-y-2">
          {(registry.length > 0 ? registry : Object.values(results).map((r) => ({
            slug: r.slug,
            display_name: r.display_name,
            form_count: r.checks.length,
          }))).map((entry) => {
            const payload = results[entry.slug]
            const pending = loading && !payload
            const fail = payload?.fail ?? 0
            const warn = payload?.warn ?? 0
            const ok = payload?.ok ?? 0
            const status: CheckStatus = pending ? 'running' : fail > 0 ? 'fail' : warn > 0 ? 'warn' : payload ? 'ok' : 'pending'
            return (
              <div
                key={entry.slug}
                className="rounded-lg border border-border bg-muted/80 px-3 py-2"
                data-testid={`connector-global-check-${entry.slug}`}
              >
                <div className="flex items-start gap-2">
                  <CheckStatusIcon status={status} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <p className="text-sm font-medium">{entry.display_name}</p>
                      <span className="font-mono text-[11px] text-muted-foreground">{entry.slug}</span>
                      {payload ? (
                        <span className="text-[11px] text-muted-foreground">
                          {ok} OK · {warn} à surveiller · {fail} KO
                        </span>
                      ) : pending ? (
                        <span className="text-[11px] text-muted-foreground">Vérification…</span>
                      ) : null}
                    </div>
                    {payload && payload.checks.length > 0 ? (
                      <ul className="mt-2 space-y-1">
                        {payload.checks.map((chk) => (
                          <li key={chk.id} className="flex items-start gap-2 text-[11px]">
                            <CheckStatusIcon status={chk.status} />
                            <span className="min-w-0 flex-1">
                              <span className="font-medium">{chk.label}</span>
                              {chk.message ? <span className="text-muted-foreground"> — {chk.message}</span> : null}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ConnectorCheckPanel({ slug }: { slug: string }) {
  const [checks, setChecks] = useState<Record<string, CheckItem>>({})
  const [summary, setSummary] = useState<Omit<ConnectorCheckPayload, 'checks'> | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const doneRef = useRef(false)
  const esRef = useRef<EventSource | null>(null)

  const stopStream = useCallback(() => {
    esRef.current?.close()
    esRef.current = null
  }, [])

  const runCheck = useCallback(() => {
    stopStream()
    setLoading(true)
    setError(null)
    setSummary(null)
    setChecks({})
    doneRef.current = false

    const es = new EventSource(`/api/connectors/${encodeURIComponent(slug)}/check/stream`)
    esRef.current = es

    es.addEventListener('registry', (ev) => {
      try {
        const data = JSON.parse(ev.data) as { checks?: CheckDescriptor[] }
        const init: Record<string, CheckItem> = {}
        for (const d of data.checks ?? []) {
          init[d.id] = { ...d, status: 'pending', message: '' }
        }
        setChecks(init)
      } catch {
        /* ignore */
      }
    })

    es.addEventListener('check', (ev) => {
      try {
        const chk = JSON.parse(ev.data) as CheckItem
        setChecks((prev) => {
          const next = { ...prev }
          for (const id of Object.keys(next)) {
            if (next[id].status === 'pending') {
              next[id] = { ...next[id], status: 'running' }
              break
            }
          }
          next[chk.id] = { ...chk }
          return next
        })
      } catch {
        /* ignore */
      }
    })

    es.addEventListener('error', (ev) => {
      try {
        const data = JSON.parse((ev as MessageEvent).data) as { error?: string }
        if (data.error) setError(`Connecteur inconnu : ${slug}`)
      } catch {
        /* ignore */
      }
    })

    const finish = (s?: Omit<ConnectorCheckPayload, 'checks'>) => {
      if (doneRef.current) return
      doneRef.current = true
      stopStream()
      setLoading(false)
      if (s) setSummary(s)
    }

    es.addEventListener('done', (ev) => {
      try {
        finish(JSON.parse(ev.data) as Omit<ConnectorCheckPayload, 'checks'>)
      } catch {
        finish()
      }
    })

    es.onerror = () => {
      if (!doneRef.current) {
        setError('Flux de vérification interrompu')
        finish()
      }
    }
  }, [slug, stopStream])

  useEffect(() => {
    runCheck()
    return () => stopStream()
  }, [runCheck, stopStream])

  const checkList = useMemo(() => Object.values(checks), [checks])

  return (
    <div
      className="space-y-3 rounded-lg border border-border bg-card p-3"
      data-testid="connector-check-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium">Vérification</p>
          <p className="text-muted-foreground text-[11px]">
            {summary
              ? `${summary.ok} OK · ${summary.warn} à surveiller · ${summary.fail} KO`
              : loading
                ? 'Checks en cours…'
                : 'Aucun check'}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={loading}
          onClick={runCheck}
          data-testid="connector-check-rerun"
        >
          {loading ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : <HugeiconsIcon icon={RefreshIcon} size={14} className="mr-1.5" />}
          Relancer
        </Button>
      </div>

      {error ? <p className="text-destructive text-xs">{error}</p> : null}

      {checkList.length > 0 ? (
        <ul className="space-y-2">
          {checkList.map((chk) => (
            <li key={chk.id} className="flex items-start gap-2 rounded-md bg-muted px-2 py-1.5 text-xs">
              <CheckStatusIcon status={chk.status} />
              <div className="min-w-0 flex-1">
                <p className="font-medium">{chk.label}</p>
                <p className="text-muted-foreground">
                  {checkStatusLabel(chk.status)}
                  {chk.message ? ` — ${chk.message}` : ''}
                </p>
              </div>
            </li>
          ))}
        </ul>
      ) : loading ? (
        <p className="text-muted-foreground flex items-center gap-2 text-xs">
          <Loader2 className="size-3.5 animate-spin" />
          Préparation des checks…
        </p>
      ) : null}
    </div>
  )
}

/** @deprecated Rétrocompat — l’overview expose encore blocks ; cette vue utilise /api/connectors. */
export type ServerEntry = {
  name: string
  kind: string
  enabled: boolean
  target: string
  note?: string
}

export type Block = { source: string; servers: ServerEntry[] }

export const _iconsDeprecated = { CloudServerIcon, CodeFolderIcon, Plug02Icon }
