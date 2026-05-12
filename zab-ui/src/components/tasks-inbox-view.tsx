import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { HugeiconsIcon } from '@hugeicons/react'
import { CheckListIcon, LinkSquare02Icon, RefreshIcon } from '@hugeicons/core-free-icons'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { NavId } from '@/components/sidebar-nav'
import { cn } from '@/lib/utils'

type TaskItem = {
  identifier: string
  title: string
  url: string
  state: string
  updated_at: string
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
  env_token: string
  items: TaskItem[]
}

type TasksInboxPayload = {
  generated_at_utc: string
  parse_errors: string[]
  env_hints: Record<string, boolean>
  sources: TaskSourceBlock[]
}

type PmEnvSyncPayload = {
  path: string
  scanned_env_files: number
  keys_updated: string[]
  keys_skipped_already_present: string[]
  keys_found_by_scan: string[]
  keys_missing_after_scan: string[]
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

function routingHref(abs: string | null | undefined, raw: string | null | undefined): string | null {
  const t = (raw || '').trim()
  if (t.startsWith('http://') || t.startsWith('https://')) return t
  if (abs && abs.trim()) return `vscode://file${abs.trim()}`
  return null
}

export function TasksInboxView({ onJump }: { onJump: (id: NavId) => void }) {
  const [data, setData] = useState<TasksInboxPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncingPm, setSyncingPm] = useState(false)

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

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Tâches (multi-outils)</h2>
          <p className="text-muted-foreground text-sm">
            Agrégation légère des issues / cartes selon <code className="font-mono text-[11px]">task_sources</code> dans{' '}
            <code className="font-mono text-[11px]">~/.config/zab/config.yaml</code>. Jetons PM :{' '}
            <code className="font-mono text-[11px]">~/.config/zab/.env</code> (fusion depuis vos projets ci‑dessous), puis{' '}
            <code className="font-mono text-[11px]">$ZAB_SKILLS_ROOT/.env</code> — voir aussi Sécurité.
          </p>
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
                  toast.success('Jetons PM fusionnés dans ~/.config/zab/.env', {
                    description: `${s.scanned_env_files} fichier(s) .env parcouru(s) · écrits : ${s.keys_updated.join(', ') || 'aucun'}`,
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
            Importer depuis les .env des projets
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void load()}>
            <HugeiconsIcon icon={RefreshIcon} size={16} className="mr-1.5 opacity-70" />
            Rafraîchir
          </Button>
          <Button type="button" variant="secondary" size="sm" onClick={() => onJump('config')}>
            Configuration
          </Button>
        </div>
      </header>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-sky-100 text-sky-800">
            <HugeiconsIcon icon={CheckListIcon} size={20} />
          </div>
          <div>
            <CardTitle className="text-base">Variables d’accès</CardTitle>
            <CardDescription>
              Présence dans le processus ou dans <code className="font-mono text-[11px]">~/.config/zab/.env</code> — aucun secret affiché.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          {data ? (
            <ul className="flex flex-wrap gap-3 text-xs">
              {Object.entries(data.env_hints).map(([k, ok]) => (
                <li
                  key={k}
                  className={cn(
                    'rounded-full px-2.5 py-1 font-mono ring-1',
                    ok ? 'bg-emerald-50 text-emerald-800 ring-emerald-200' : 'bg-zinc-100 text-zinc-600 ring-zinc-200',
                  )}
                >
                  {k} : {ok ? 'oui' : 'non'}
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

      <p className="text-muted-foreground text-xs">
        SKILL de routage (copiable vers votre dépôt skills) :{' '}
        <code className="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">examples/skills/zab-project-management-routing/SKILL.md</code>{' '}
        à la racine du clone zab.
      </p>

      {!data ? (
        <p className="text-muted-foreground text-sm">Chargement…</p>
      ) : data.sources.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed py-12 text-center text-sm">
          Aucune source configurée. Ajoutez une liste <code className="font-mono text-[11px]">task_sources</code> dans votre{' '}
          <code className="font-mono text-[11px]">config.yaml</code>.
        </p>
      ) : (
        <div className="space-y-8">
          {data.sources.map((src) => (
            <section key={src.id} className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-2">
                <div>
                  <h3 className="text-lg font-semibold tracking-tight">{src.label}</h3>
                  <p className="text-muted-foreground text-xs">
                    <span className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono dark:bg-zinc-800">{src.backend}</span>
                    <span className="mx-2">·</span>
                    <span className="font-mono text-[11px]">{src.id}</span>
                    <span className="mx-2">·</span>
                    <span
                      className={cn(
                        'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1',
                        src.status === 'ok'
                          ? 'bg-emerald-50 text-emerald-800 ring-emerald-200'
                          : src.status === 'skipped'
                            ? 'bg-zinc-100 text-zinc-700 ring-zinc-200'
                            : 'bg-rose-50 text-rose-800 ring-rose-200',
                      )}
                    >
                      {src.status}
                    </span>
                    {src.reason ? <span className="text-muted-foreground ml-2">— {src.reason}</span> : null}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {src.mcp_hint ? (
                    <span className="text-muted-foreground max-w-md text-[11px]" title={src.mcp_hint}>
                      MCP : {src.mcp_hint}
                    </span>
                  ) : null}
                  {routingHref(src.routing_doc_abs, src.routing_doc) ? (
                    <a
                      href={routingHref(src.routing_doc_abs, src.routing_doc)!}
                      className="text-primary inline-flex items-center gap-1 text-xs font-medium hover:underline"
                    >
                      <HugeiconsIcon icon={LinkSquare02Icon} size={14} />
                      Règle / doc
                    </a>
                  ) : null}
                  {src.local_project_path_abs ? (
                    <a
                      href={`vscode://file${src.local_project_path_abs}`}
                      className="text-primary inline-flex items-center gap-1 text-xs font-medium hover:underline"
                    >
                      Dossier local
                    </a>
                  ) : null}
                </div>
              </div>

              {src.items.length === 0 && src.status === 'ok' ? (
                <p className="text-muted-foreground text-sm">Aucun élément renvoyé pour cette source.</p>
              ) : src.items.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-24">Id</TableHead>
                      <TableHead>Titre</TableHead>
                      <TableHead className="w-32">État</TableHead>
                      <TableHead className="w-44">MàJ</TableHead>
                      <TableHead className="w-20" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {src.items.map((row, idx) => (
                      <TableRow key={`${src.id}-${row.identifier}-${idx}`}>
                        <TableCell className="font-mono text-xs">{row.identifier}</TableCell>
                        <TableCell className="max-w-md truncate text-sm">{row.title}</TableCell>
                        <TableCell className="text-muted-foreground text-xs">{row.state || '—'}</TableCell>
                        <TableCell className="text-muted-foreground font-mono text-[11px]">
                          {row.updated_at ? row.updated_at.slice(0, 19).replace('T', ' ') : '—'}
                        </TableCell>
                        <TableCell>
                          {row.url ? (
                            <a
                              href={row.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-primary text-xs font-medium hover:underline"
                            >
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
              ) : null}
            </section>
          ))}
        </div>
      )}

      {data ? (
        <p className="text-muted-foreground text-[11px]">
          Généré : <code className="font-mono">{data.generated_at_utc}</code>
        </p>
      ) : null}
    </div>
  )
}
