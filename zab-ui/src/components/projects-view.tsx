import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { HugeiconsIcon } from '@hugeicons/react'
import { Folder02Icon } from '@hugeicons/core-free-icons'
import { RefreshCw, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

type OverviewProject = {
  name: string
  path: string
  org: string
  projects_root: string
  /** Dossier parent sous la racine (ex. carrefour) quand le projet est un sous-dossier. */
  workspace_parent?: string | null
  skills: { id: string; path: string; rel_from_home?: string; source?: string }[]
}

type OverviewLike = {
  user_config_path?: string
  projects?: OverviewProject[]
  projects_roots?: string[]
}

function shortenHome(p: string): string {
  return p.replace(/^\/Users\/[^/]+/, '~')
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const t = await r.text()
    throw new Error(t || r.statusText)
  }
  return r.json() as Promise<T>
}

function ProjectCard({
  p,
  shortenHome: sh,
  onOpenSkill,
}: {
  p: OverviewProject
  shortenHome: (path: string) => string
  onOpenSkill: (path: string) => void
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{p.name}</CardTitle>
        <CardDescription>
          <span className="inline-flex flex-wrap items-center gap-2">
            <span
              className={cn(
                'rounded-full px-2 py-0.5 text-[11px] font-medium',
                'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200',
              )}
            >
              {p.org}
            </span>
            <span className="text-muted-foreground">
              {p.skills.length} skill{p.skills.length > 1 ? 's' : ''}
            </span>
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="text-xs"
            onClick={() => {
              void (async () => {
                try {
                  const r = await fetch('/api/system/open-folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: p.path }),
                  })
                  if (!r.ok) {
                    const t = await r.text()
                    throw new Error(t || r.statusText)
                  }
                  toast.success('Dossier ouvert')
                } catch (e) {
                  toast.error(e instanceof Error ? e.message : String(e))
                }
              })()
            }}
          >
            Ouvrir le dossier
          </Button>
        </div>
        <p className="text-muted-foreground font-mono text-[10px] break-all">{sh(p.path)}</p>
        <ul className="space-y-1.5 border-t border-zinc-100 pt-2 text-xs dark:border-zinc-800">
          {p.skills.map((s) => (
            <li key={s.path} className="flex flex-col gap-0.5">
              <button type="button" onClick={() => onOpenSkill(s.path)} className="text-primary w-fit hover:underline">
                <code className="font-mono text-[11px]">{s.id}</code>
              </button>
              <button
                type="button"
                className="text-muted-foreground truncate text-left hover:text-foreground"
                onClick={() => {
                  window.location.href = `vscode://file${s.path}`
                }}
                title={s.path}
              >
                {s.rel_from_home ? sh(s.rel_from_home) : sh(s.path)}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

export function ProjectsView({
  overview,
  onOpenSkill,
  onRefreshOverview,
}: {
  overview: OverviewLike | null
  onOpenSkill: (path: string) => void
  onRefreshOverview: () => Promise<void> | void
}) {
  const [rootsText, setRootsText] = useState('')
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    if (!overview) return
    const pr = overview.projects_roots
    if (pr && pr.length > 0) {
      setRootsText(pr.map((r) => shortenHome(r)).join('\n'))
    } else {
      setRootsText('~/projects')
    }
  }, [overview])

  const detectedRoots = useMemo(() => {
    const s = new Set<string>()
    for (const p of overview?.projects ?? []) {
      if (p.projects_root) s.add(p.projects_root)
    }
    return Array.from(s).sort()
  }, [overview?.projects])

  const projects = overview?.projects ?? []
  const grouped = useMemo(() => {
    const nested = projects.filter((p) => p.workspace_parent)
    const root = projects.filter((p) => !p.workspace_parent)
    const byParent = new Map<string, OverviewProject[]>()
    for (const p of nested) {
      const key = p.workspace_parent ?? ''
      if (!byParent.has(key)) byParent.set(key, [])
      byParent.get(key)!.push(p)
    }
    for (const arr of byParent.values()) {
      arr.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
    }
    const parentKeys = Array.from(byParent.keys()).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
    root.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
    return { byParent, parentKeys, root }
  }, [projects])

  const applyDetectedRoots = () => {
    if (detectedRoots.length === 0) {
      toast.message('Aucune racine déduite', { description: 'Ajoutez des SKILL.md sous ~/projects ou renseignez les chemins ci‑dessous.' })
      return
    }
    setRootsText(detectedRoots.map((r) => shortenHome(r)).join('\n'))
    toast.success(`${detectedRoots.length} racine(s) proposée(s)`)
  }

  const saveRoots = async () => {
    const roots = rootsText
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
    setSaving(true)
    try {
      const r = await apiJson<{ config_path: string; projects_roots: string[] }>('/api/config/projects-roots', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ roots }),
      })
      toast.success('projects_roots enregistré', {
        description: r.projects_roots.join(', ') || '(liste vide — découverte désactivée)',
      })
      await onRefreshOverview()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const refresh = async () => {
    setRefreshing(true)
    try {
      await onRefreshOverview()
      toast.success('Aperçu actualisé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setRefreshing(false)
    }
  }

  if (!overview) return <p className="text-muted-foreground">Chargement…</p>

  const cfgPath = (overview.user_config_path ?? '').replace(/^\/Users\/[^/]+/, '~')

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Projets</h2>
        <p className="text-muted-foreground text-sm">
          Dépôts sous <code className="font-mono text-[11px]">projects_roots</code> : dossiers immédiats et, le cas échéant,{' '}
          <strong className="font-medium text-foreground">un niveau de sous-dossiers</strong> (ex.{' '}
          <code className="font-mono text-[11px]">carrefour/danmdata</code>). Skills : racine du projet,{' '}
          <code className="font-mono text-[11px]">.cursor/**/SKILL.md</code>, <code className="font-mono text-[11px]">.claude/**/SKILL.md</code>.
        </p>
      </header>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800">
              <HugeiconsIcon icon={Folder02Icon} size={20} />
            </div>
            <div>
              <CardTitle className="text-base">Racines dans la config</CardTitle>
              <CardDescription>
                Fichier : <code className="font-mono text-[11px]">{cfgPath || '—'}</code> — clé{' '}
                <code className="font-mono text-[11px]">projects_roots</code>
              </CardDescription>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={refreshing} onClick={() => void refresh()}>
              <RefreshCw className="mr-1.5 size-3.5 opacity-70" />
              Rafraîchir
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={applyDetectedRoots} disabled={detectedRoots.length === 0}>
              Remplir depuis la détection
            </Button>
            <Button type="button" size="sm" disabled={saving} onClick={() => void saveRoots()}>
              <Save className="mr-1.5 size-3.5 opacity-90" />
              Enregistrer dans config.yaml
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <label className="text-muted-foreground text-xs font-medium">Une racine par ligne (ex. ~/projects)</label>
          <Textarea
            value={rootsText}
            onChange={(e) => setRootsText(e.target.value)}
            rows={4}
            className="font-mono text-xs"
            spellCheck={false}
          />
          <p className="text-muted-foreground text-[11px] leading-relaxed">
            Après enregistrement, recharge l’aperçu : projets à la racine de chaque ligne + sous-projets un niveau plus bas
            lorsqu’ils contiennent des SKILL.md. Liste vide = désactive la découverte (<code className="font-mono">projects_roots: []</code>).
          </p>
        </CardContent>
      </Card>

      {projects.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed py-12 text-center text-sm">
          Aucun projet avec SKILL.md pour l’instant. Vérifiez les racines ci‑dessus puis enregistrez et rafraîchissez.
        </p>
      ) : (
        <div className="space-y-8">
          {grouped.parentKeys.map((parent) => (
            <section key={parent} className="space-y-3">
              <h3 className="text-muted-foreground flex flex-wrap items-baseline gap-2 border-b border-zinc-200 pb-2 text-sm font-medium dark:border-zinc-800">
                <span className="text-foreground">{parent}</span>
                <span className="font-normal">· sous-projets</span>
                <span className="font-mono text-[11px] font-normal opacity-80">
                  {(() => {
                    const first = (grouped.byParent.get(parent) ?? [])[0]?.path
                    if (!first) return ''
                    const segs = first.split('/').filter(Boolean)
                    segs.pop()
                    return shortenHome(`/${segs.join('/')}`)
                  })()}
                </span>
              </h3>
              <div className="grid gap-3 md:grid-cols-2">
                {(grouped.byParent.get(parent) ?? []).map((p) => (
                  <ProjectCard key={p.path} p={p} shortenHome={shortenHome} onOpenSkill={onOpenSkill} />
                ))}
              </div>
            </section>
          ))}

          {grouped.root.length > 0 ? (
            <section className="space-y-3">
              <h3 className="text-muted-foreground border-b border-zinc-200 pb-2 text-sm font-medium dark:border-zinc-800">
                À la racine des <code className="font-mono text-[11px]">projects_roots</code>
              </h3>
              <div className="grid gap-3 md:grid-cols-2">
                {grouped.root.map((p) => (
                  <ProjectCard key={p.path} p={p} shortenHome={shortenHome} onOpenSkill={onOpenSkill} />
                ))}
              </div>
            </section>
          ) : null}
        </div>
      )}
    </div>
  )
}
