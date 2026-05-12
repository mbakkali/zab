import { useCallback, useEffect, useMemo, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  CloudServerIcon,
  CodeFolderIcon,
  Copy01Icon,
  Plug02Icon,
  Search01Icon,
  Tick02Icon,
} from '@hugeicons/core-free-icons'
import { connectorMeta, kindMeta } from '@/lib/connector-meta'
import { cn } from '@/lib/utils'
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

const EDITABLE_CONFIG_KEYS = new Set(['local_tools_actual', 'user_zab_config'])

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

type ConfigFileSummary = {
  key: string
  title: string
  syntax: string
  exists: boolean
  path_display: string
  hint?: string | null
}

/** Même jeu de clés que `GET /api/config/files`, pour garder une liste même si la route backend est obsolète. */
const CONFIG_FILE_ROWS_FALLBACK: ConfigFileSummary[] = [
  {
    key: 'user_zab_config',
    title: '~/.config/zab/config.yaml',
    syntax: 'yaml',
    exists: false,
    path_display: '~/.config/zab/config.yaml',
    hint: 'skills_root, local_tools_path, cli_watchlist',
  },
  {
    key: 'local_tools_actual',
    title: 'local-tools.yaml',
    syntax: 'yaml',
    exists: false,
    path_display: 'local-tools.yaml',
    hint: 'Défaut ~/.config/zab/local-tools.yaml ou local_tools_path dans config',
  },
]

function fallbackRowMeta(key: string): ConfigFileSummary | undefined {
  return CONFIG_FILE_ROWS_FALLBACK.find((r) => r.key === key)
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
  const [query, setQuery] = useState('')
  const [activeKind, setActiveKind] = useState<string>('all')
  const [list, setList] = useState<ConnectorSummary[]>([])
  const [pagination, setPagination] = useState<ConnectorsApiList['pagination'] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [detailSlug, setDetailSlug] = useState<string | null>(null)
  const [detail, setDetail] = useState<ConnectorDetailType | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const loadList = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const q = encodeURIComponent(query.trim())
      const r = await fetch(`/api/connectors?limit=200&q=${q}`)
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
  }, [query])

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
      if (activeKind === 'all') return true
      return row.kind_badges.some((k) => k.toLowerCase() === activeKind.toLowerCase())
    })
  }, [list, activeKind])

  const stats = useMemo(() => {
    const total = filtered.length
    const enabled = filtered.filter((e) => e.any_enabled).length
    const forms = filtered.reduce((a, x) => a + x.form_count, 0)
    return { total, enabled, forms }
  }, [filtered])

  const backendNeedsRestartForAggregators = detectsStaleZabAggregatorBackend(loadError)

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h2 className="text-2xl font-semibold tracking-tight">Connecteurs</h2>
        <p className="text-muted-foreground text-sm" data-testid="connectors-subtitle">
          {stats.enabled} actifs · {stats.forms} forme(s) · {stats.total} connecteur(s) logique(s)
        </p>
      </header>

      {backendNeedsRestartForAggregators && loadError ? (
        <div
          role="alert"
          data-testid="connectors-stale-backend-notice"
          className="text-destructive space-y-2 rounded-xl border border-red-200 bg-red-50/90 px-4 py-3 text-sm whitespace-pre-wrap"
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
            placeholder="Rechercher un connecteur…"
            aria-label="Rechercher un connecteur"
            className="border-input bg-background w-full rounded-lg border py-2 pr-3 pl-9 text-sm outline-none transition focus:ring-2 focus:ring-zinc-300"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <KindChip active={activeKind === 'all'} onClick={() => setActiveKind('all')}>
            Tous · {list.length}
          </KindChip>
          {kindOptions.map((k) => (
            <KindChip key={k} active={activeKind === k} onClick={() => setActiveKind(k)}>
              {k.toUpperCase()}
            </KindChip>
          ))}
        </div>
      </div>

      {loading && <p className="text-muted-foreground text-sm">Chargement…</p>}
      {loadError && !backendNeedsRestartForAggregators && (
        <div className="text-destructive space-y-2 rounded-xl border border-red-200 bg-red-50/80 px-4 py-3 text-sm whitespace-pre-wrap">
          <p role="alert" data-testid="connectors-load-error">
            {loadError}
          </p>
        </div>
      )}
      {pagination && (
        <p className="text-muted-foreground text-xs">
          Page {pagination.page}/{pagination.total_pages} · {pagination.total} résultat(s)
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
          <p>Aucun connecteur ne correspond.</p>
          {backendNeedsRestartForAggregators ? (
            <p className="text-xs opacity-90">
              Ou le tableau est vide après redémarrage du serveur : attends le chargement complet.
            </p>
          ) : null}
        </div>
      )}

      <ConnectorDetailDialog
        open={Boolean(detailSlug)}
        loading={detailLoading}
        detail={detail}
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
    </div>
  )
}

export function ConnectorsConfigFilesPanel({ aggregatorStale }: { aggregatorStale?: boolean }) {
  const [rows, setRows] = useState<ConfigFileSummary[]>([])
  const [chosen, setChosen] = useState<string>('user_zab_config')
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
          setRows(CONFIG_FILE_ROWS_FALLBACK.slice())
          setChosen(CONFIG_FILE_ROWS_FALLBACK[0]?.key ?? 'user_zab_config')
        } else {
          const list = JSON.parse(t) as ConfigFileSummary[]
          setRows(list)
          const first = list.find((x) => x.exists) ?? list[0]
          setChosen(first?.key ?? 'user_zab_config')
        }
      } catch {
        setBanner('Erreur réseau lors du chargement des chemins config.')
        setRows(CONFIG_FILE_ROWS_FALLBACK.slice())
        setChosen('user_zab_config')
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
            ? `# Fichier absent sur ce poste :\n${j.path_display}\n\nTu peux copier depuis zab/local-tools.example.yaml puis adapter.`
            : j.content || (j.error ? `# ${j.error}` : ''),
        )
      } catch {
        setContent('')
      }
    })()
  }, [chosen, aggregatorStale, reloadNonce])

  const editable = EDITABLE_CONFIG_KEYS.has(chosen)

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
    <Card data-testid="connectors-config-panel" size="sm" className="border-zinc-200">
      <CardHeader className="border-b border-zinc-100 pb-4">
        <CardTitle>Configuration zab</CardTitle>
        <CardDescription>
          <code className="text-xs">config.yaml</code> et <code className="text-xs">local-tools.yaml</code> sont éditables
          ici ; le modèle <code className="text-xs">local-tools.example.yaml</code> reste lecture seule. Ajoutez des binaires dans{' '}
          <code className="text-xs">cli_watchlist</code> pour le scan <code className="text-xs">which</code>.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-4">
        {busy ? (
          <p className="text-muted-foreground text-xs">Chargement des chemins…</p>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <label className="text-muted-foreground text-xs font-medium whitespace-nowrap" htmlFor="config-file-select">
              Fichier
            </label>
            <select
              id="config-file-select"
              value={chosen}
              onChange={(e) => setChosen(e.target.value)}
              className="border-input bg-background w-full max-w-md rounded-lg border px-3 py-2 text-xs sm:flex-1"
            >
              {rows.map((row) => (
                <option key={row.key} value={row.key}>
                  {row.title}
                  {!row.exists ? ' (absent)' : ''}
                </option>
              ))}
            </select>
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
          <p className="text-amber-800 text-[11px]">Aperçu tronqué : {meta.truncate_note}</p>
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
          ? 'border-zinc-900 bg-zinc-900 text-white'
          : 'border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300',
      )}
    >
      {children}
    </button>
  )
}

function ConnectorCard({ row, onDetail }: { row: ConnectorSummary; onDetail: () => void }) {
  const meta = connectorMeta(row.display_name || row.id)
  const primaryTransport = row.transport_badges[0] || row.kind_badges[0] || ''
  const k = kindMeta(primaryTransport || 'stdio')

  return (
    <div className="group bg-card hover:border-zinc-300 hover:shadow-sm relative flex flex-col gap-4 rounded-xl border border-zinc-200 p-5 transition">
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
          <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700 ring-1 ring-slate-200">
            {row.form_count} formes
          </span>
        )}
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
            className="absolute top-1.5 right-1.5 rounded-md p-1 text-zinc-500 opacity-0 transition hover:bg-white hover:text-zinc-900 group-hover:opacity-100"
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
        Voir
      </Button>
    </div>
  )
}

function SummaryStatus({ enabled }: { enabled: boolean }) {
  if (enabled) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200">
        <HugeiconsIcon icon={Tick02Icon} size={12} strokeWidth={2} />
        actif
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2 py-1 text-[11px] font-medium text-zinc-600 ring-1 ring-zinc-200">
      désactivé
    </span>
  )
}

function ConnectorDetailDialog({
  open,
  loading,
  detail,
  onOpenChange,
  onTest,
}: {
  open: boolean
  loading: boolean
  detail: ConnectorDetailType | null
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
            <div className="space-y-4 pt-2" data-testid="connector-forms-list">
              {detail.forms.map((f) => (
                <div key={f.id} className="space-y-2 rounded-lg border border-zinc-100 bg-zinc-50/80 p-3">
                  <div className="flex flex-wrap gap-2 text-[11px] font-medium capitalize">
                    <span className="bg-background rounded-full px-2 py-0.5 ring-1">{f.kind}</span>
                    <span className="bg-background rounded-full px-2 py-0.5 ring-1">{f.transport_kind}</span>
                    <span className={f.enabled ? 'text-emerald-700' : 'text-zinc-500'}>{f.enabled ? 'activé' : 'désactivé'}</span>
                    <span className={cn(
                      'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
                      f.transport_kind === 'stdio'
                        ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'
                        : 'bg-blue-50 text-blue-700 ring-1 ring-blue-200'
                    )}>
                      {f.transport_kind === 'stdio' ? 'Local' : 'Remote'}
                    </span>
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
                      {f.source_ref && <p className="font-mono text-[11px] text-zinc-500">{f.source_ref}</p>}
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
