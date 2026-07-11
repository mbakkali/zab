import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { useI18n } from '@/i18n/use-i18n'
import { HugeiconsIcon } from '@hugeicons/react'
import { Folder02Icon } from '@hugeicons/core-free-icons'
import { Filter, LayoutGrid, List, RefreshCw, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { ProjectActions, type OverviewProject } from '@/components/project-actions'
import { ProjectsTable } from '@/components/projects-table'
import { cn } from '@/lib/utils'

type OverviewLike = {
  user_config_path?: string
  projects?: OverviewProject[]
  projects_roots?: string[]
}

function shortenHome(p: string): string {
  return p.replace(/^\/Users\/[^/]+/, '~')
}

function activityTime(p: OverviewProject): number {
  const raw = p.last_activity_at_utc
  if (!raw) return 0
  const ts = Date.parse(raw)
  return Number.isNaN(ts) ? 0 : ts
}

function formatActivityDate(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(d)
}

function activitySourceLabel(value?: string | null): string {
  if (value === 'git_commit') return 'git'
  if (value === 'git_metadata') return 'git meta'
  if (value === 'files') return 'fichiers'
  return 'activité'
}

function projectMatchesRoute(p: OverviewProject, routeId: string): boolean {
  const id = routeId.trim().toLowerCase()
  if (!id) return false
  return [p.id, p.name, p.path].some((value) => typeof value === 'string' && value.toLowerCase() === id)
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const respText = await r.text()
    throw new Error(respText || r.statusText)
  }
  return r.json() as Promise<T>
}

function ProjectCard({
  p,
  shortenHome: sh,
  active,
  onOpenOrg,
  onOpenSkill,
  miningProjectPath,
  onMineMemory,
  onRunSecurityScan,
}: {
  p: OverviewProject
  shortenHome: (path: string) => string
  active?: boolean
  onOpenOrg: (org: string) => void
  onOpenSkill: (path: string) => void
  miningProjectPath?: string | null
  onMineMemory?: (path: string, name: string) => void | Promise<void>
  onRunSecurityScan?: (preset: string, path: string) => void
}) {
  const { t } = useI18n()
  const gitRepo = Boolean(p.git_repo)
  const branch = p.git_branch || null
  const remote = (p.remote_host || '') as string

  return (
    <Card className={active ? 'border-zinc-900 ring-1 ring-zinc-900' : undefined}>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{p.name}</CardTitle>
        <CardDescription>
          <span className="inline-flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => onOpenOrg(p.org)}
              className={cn(
                'rounded-full px-2 py-0.5 text-[11px] font-medium',
                'bg-zinc-100 text-zinc-700 transition hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-200',
              )}
            >
              {p.org}
            </button>
            <span className="text-muted-foreground">
              {p.skills.length} skill{p.skills.length > 1 ? 's' : ''}
            </span>
            {gitRepo ? (
              <span
                className={cn(
                  'rounded-full px-2 py-0.5 text-[11px] font-medium',
                  'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100',
                )}
                title={p.origin_https || undefined}
              >
                git{branch ? ` · ${branch}` : ''}
              </span>
            ) : (
              <span className="text-muted-foreground rounded-full px-2 py-0.5 text-[11px]">{t('projects.card.noGit')}</span>
            )}
            {remote ? (
              <span className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-[11px] capitalize">
                {remote}
              </span>
            ) : null}
            {p.workspace_parent ? (
              <span className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-[11px]">
                {p.workspace_parent}
              </span>
            ) : null}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <span title={p.last_activity_at_utc || undefined}>
            MàJ {formatActivityDate(p.last_activity_at_utc)}
          </span>
          {p.last_activity_source ? <span>{activitySourceLabel(p.last_activity_source)}</span> : null}
          {p.last_activity_path ? (
            <span className="max-w-full truncate font-mono" title={p.last_activity_path}>
              {p.last_activity_path}
            </span>
          ) : null}
        </div>
        <ProjectActions
          p={p}
          miningProjectPath={miningProjectPath}
          onMineMemory={onMineMemory}
          onRunSecurityScan={onRunSecurityScan}
        />
        <p className="text-muted-foreground font-mono text-[10px] break-all">{sh(p.path)}</p>
        <details className="rounded-md border border-zinc-200 bg-zinc-50/80 dark:border-zinc-800 dark:bg-zinc-950/40">
          <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-zinc-700 dark:text-zinc-200">
            {t('projects.card.skillsExpand', { count: String(p.skills.length) })}
          </summary>
          <div className="max-h-[min(50vh,28rem)] overflow-y-auto border-t border-zinc-200 px-2 pb-2 pt-1 dark:border-zinc-800">
            <ul className="space-y-1.5 text-xs">
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
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

export function ProjectsView({
  overview,
  activeProjectId,
  onOpenOrg,
  onOpenSkill,
  onRefreshOverview,
  miningProjectPath,
  onMineMemory,
  onRunSecurityScan,
}: {
  overview: OverviewLike | null
  activeProjectId?: string | null
  onOpenOrg: (org: string) => void
  onOpenSkill: (path: string) => void
  onRefreshOverview: () => Promise<void> | void
  miningProjectPath?: string | null
  onMineMemory?: (path: string, name: string) => void | Promise<void>
  onRunSecurityScan?: (preset: string, path: string) => void
}) {
  const { t } = useI18n()
  const [rootsText, setRootsText] = useState('')
  const [saving, setSaving] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [filterQuery, setFilterQuery] = useState('')
  const [filterOrg, setFilterOrg] = useState<string>('all')
  const [filterGit, setFilterGit] = useState<'all' | 'git' | 'nogit'>('all')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>(() => {
    try {
      const v = localStorage.getItem('zab-projects-view')
      return v === 'list' ? 'list' : 'grid'
    } catch {
      return 'grid'
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem('zab-projects-view', viewMode)
    } catch {
      /* ignore */
    }
  }, [viewMode])

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

  const orgOptions = useMemo(() => {
    const s = new Set<string>()
    for (const p of projects) s.add(p.org)
    return Array.from(s).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
  }, [projects])

  const filteredProjects = useMemo(() => {
    const q = filterQuery.trim().toLowerCase()
    let xs = projects
    if (activeProjectId && projects.some((p) => projectMatchesRoute(p, activeProjectId))) {
      xs = xs.filter((p) => projectMatchesRoute(p, activeProjectId))
    }
    if (q) {
      xs = xs.filter((p) => {
        if (p.name.toLowerCase().includes(q)) return true
        if (p.org.toLowerCase().includes(q)) return true
        if (p.path.toLowerCase().includes(q)) return true
        const wp = p.workspace_parent
        if (wp && wp.toLowerCase().includes(q)) return true
        if ((p.git_branch || '').toLowerCase().includes(q)) return true
        if ((p.remote_host || '').toLowerCase().includes(q)) return true
        return p.skills.some((s) => s.id.toLowerCase().includes(q) || s.path.toLowerCase().includes(q))
      })
    }
    if (filterOrg !== 'all') xs = xs.filter((p) => p.org === filterOrg)
    if (filterGit === 'git') xs = xs.filter((p) => p.git_repo)
    if (filterGit === 'nogit') xs = xs.filter((p) => !p.git_repo)
    return [...xs].sort((a, b) => {
      const recent = activityTime(b) - activityTime(a)
      if (recent !== 0) return recent
      return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    })
  }, [projects, activeProjectId, filterQuery, filterOrg, filterGit])

  const applyDetectedRoots = () => {
    if (detectedRoots.length === 0) {
      toast.message(t('projects.toast.noRoots'), { description: t('projects.toast.noRootsDesc') })
      return
    }
    setRootsText(detectedRoots.map((r) => shortenHome(r)).join('\n'))
    toast.success(t('projects.toast.rootsProposed', { count: String(detectedRoots.length) }))
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
      toast.success(t('projects.toast.saved'), {
        description:
          r.projects_roots.join(', ') || t('projects.toast.savedEmpty'),
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
      toast.success(t('projects.toast.refreshed'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setRefreshing(false)
    }
  }

  if (!overview) return <p className="text-muted-foreground">{t('common.loading')}</p>

  const cfgPath = (overview.user_config_path ?? '').replace(/^\/Users\/[^/]+/, '~')

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('projects.title')}</h2>
        <p className="text-muted-foreground text-sm">{t('projects.subtitle')}</p>
      </header>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-800">
              <HugeiconsIcon icon={Folder02Icon} size={20} />
            </div>
            <div>
              <CardTitle className="text-base">{t('projects.roots.title')}</CardTitle>
              <CardDescription>
                {t('projects.roots.fileHint', { path: cfgPath || '—' })}
              </CardDescription>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={refreshing} onClick={() => void refresh()}>
              <RefreshCw className="mr-1.5 size-3.5 opacity-70" />
              {t('projects.roots.refresh')}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={applyDetectedRoots} disabled={detectedRoots.length === 0}>
              {t('projects.roots.fillFromDetection')}
            </Button>
            <Button type="button" size="sm" disabled={saving} onClick={() => void saveRoots()}>
              <Save className="mr-1.5 size-3.5 opacity-90" />
              {t('projects.roots.save')}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          <label className="text-muted-foreground text-xs font-medium">{t('projects.roots.label')}</label>
          <Textarea
            value={rootsText}
            onChange={(e) => setRootsText(e.target.value)}
            rows={4}
            className="font-mono text-xs"
            spellCheck={false}
          />
          <p className="text-muted-foreground text-[11px] leading-relaxed">{t('projects.roots.hint')}</p>
        </CardContent>
      </Card>

      {projects.length === 0 ? (
        <p className="text-muted-foreground rounded-lg border border-dashed py-12 text-center text-sm">
          {t('projects.empty.none')}
        </p>
      ) : (
        <>
          <Card>
            <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3 pb-2">
              <div>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Filter className="text-muted-foreground size-4" />
                  {t('projects.filters.title')}
                </CardTitle>
                <CardDescription>{t('projects.filters.description')}</CardDescription>
              </div>
              <div className="flex gap-1">
                <Button
                  type="button"
                  variant={viewMode === 'grid' ? 'default' : 'ghost'}
                  size="sm"
                  aria-pressed={viewMode === 'grid'}
                  onClick={() => setViewMode('grid')}
                >
                  <LayoutGrid className="mr-1.5 size-3.5" />
                  {t('projects.filters.grid')}
                </Button>
                <Button
                  type="button"
                  variant={viewMode === 'list' ? 'default' : 'ghost'}
                  size="sm"
                  aria-pressed={viewMode === 'list'}
                  onClick={() => setViewMode('list')}
                >
                  <List className="mr-1.5 size-3.5" />
                  {t('projects.filters.list')}
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
              <div className="min-w-[200px] flex-1 space-y-1">
                <label htmlFor="proj-filter-q" className="text-muted-foreground text-xs font-medium">
                  {t('projects.filters.search')}
                </label>
                <input
                  id="proj-filter-q"
                  type="search"
                  value={filterQuery}
                  onChange={(e) => setFilterQuery(e.target.value)}
                  placeholder={t('projects.filters.searchPlaceholder')}
                  className="border-input bg-background ring-offset-background placeholder:text-muted-foreground focus-visible:ring-ring flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-sm transition-colors focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                />
              </div>
              <div className="space-y-1">
                <label htmlFor="proj-filter-org" className="text-muted-foreground text-xs font-medium">
                  {t('projects.filters.org')}
                </label>
                <select
                  id="proj-filter-org"
                  value={filterOrg}
                  onChange={(e) => setFilterOrg(e.target.value)}
                  className="border-input bg-background h-9 rounded-md border px-2 text-sm shadow-sm"
                >
                  <option value="all">{t('projects.filters.allOrgs')}</option>
                  {orgOptions.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label htmlFor="proj-filter-git" className="text-muted-foreground text-xs font-medium">
                  {t('projects.filters.git')}
                </label>
                <select
                  id="proj-filter-git"
                  value={filterGit}
                  onChange={(e) => setFilterGit(e.target.value as 'all' | 'git' | 'nogit')}
                  className="border-input bg-background h-9 rounded-md border px-2 text-sm shadow-sm"
                >
                  <option value="all">{t('projects.filters.allGit')}</option>
                  <option value="git">{t('projects.filters.gitOnly')}</option>
                  <option value="nogit">{t('projects.filters.noGit')}</option>
                </select>
              </div>
              <p className="text-muted-foreground w-full text-[11px] sm:mb-1">
                {t('projects.filters.displayCount', {
                  shown: String(filteredProjects.length),
                  total: String(projects.length),
                })}
                {filteredProjects.length !== projects.length ? t('projects.filters.filterActive') : ''}.
              </p>
            </CardContent>
          </Card>

          {filteredProjects.length === 0 ? (
            <p className="text-muted-foreground rounded-lg border border-dashed py-10 text-center text-sm">
              {t('projects.empty.filtered')}
            </p>
          ) : viewMode === 'list' ? (
            <ProjectsTable
              projects={filteredProjects}
              shortenHome={shortenHome}
              activeProjectId={activeProjectId}
              onOpenOrg={onOpenOrg}
              onOpenSkill={onOpenSkill}
              miningProjectPath={miningProjectPath}
              onMineMemory={onMineMemory}
              onRunSecurityScan={onRunSecurityScan}
            />
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {filteredProjects.map((p) => (
                <ProjectCard
                  key={p.path}
                  p={p}
                  shortenHome={shortenHome}
                  active={activeProjectId ? projectMatchesRoute(p, activeProjectId) : false}
                  onOpenOrg={onOpenOrg}
                  onOpenSkill={onOpenSkill}
                  miningProjectPath={miningProjectPath}
                  onMineMemory={onMineMemory}
                  onRunSecurityScan={onRunSecurityScan}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
