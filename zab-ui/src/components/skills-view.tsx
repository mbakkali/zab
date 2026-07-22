import { useCallback, useEffect, useMemo, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Search01Icon,
  Tag01Icon,
  Building01Icon,
  FolderLibraryIcon,
  Layers01Icon,
  ArrowDown01Icon,
  ArrowRight01Icon,
} from '@hugeicons/core-free-icons'
import { skillIconFor, skillOrgIcon } from '@/lib/connector-meta'
import { shortenHomeInPath, vscodeFileHrefForSkill } from '@/lib/skill-open'
import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n/use-i18n'
import { LoadingState } from '@/components/ui/loading-state'

type Skill = {
  id: string
  path: string
  source?: string
  project?: string
  description?: string | null
  tags?: string[]
  uses_connectors?: string[]
  uses_models?: string[]
  uses_code_tools?: string[]
  registry_key?: string
  registry_status?: string
  key?: string
}
type Org = { org: string; skills: Skill[]; skills_repo_root?: string }
type IndexedSkill = Skill & { key: string; org: string; registry_key?: string; registry_status?: string }

type FilterValue =
  | { type: 'all' }
  | { type: 'org'; value: string }
  | { type: 'project'; value: string }
  | { type: 'category'; value: string }
  | { type: 'source'; value: string }

type RegistryTab = 'adopted' | 'candidate' | 'ignored' | 'conflict' | 'all'

type EnrichedRow = {
  org: string
  skillsRepoRoot?: string
  skill: Skill
  project: string | null
  source: string
  categories: string[]
  registryKey?: string
  registryStatus?: string
}

type GitMeta = {
  is_git_repo?: boolean
  branch?: string | null
  dirty?: boolean | null
  ahead?: number | null
  behind?: number | null
  upstream?: string | null
  remote_url?: string | null
}

type SkillsSyncStatus = {
  global_repo?: { skill_md_count: number; git?: GitMeta; github_synced_hint?: boolean }
  zab_index?: {
    skills_total: number
    global: number
    project: number
    skill_md_paths_configured: number
    registry_counts?: Record<string, number>
  }
  hermes?: {
    config_path: string
    config_exists: boolean
    missing_in_hermes: string[]
    extra_in_hermes: string[]
    configured_dirs_missing_on_disk: string[]
  }
  cursor_global?: { skill_md_count: number; present: boolean; skills_dir: string }
  claude_global?: { skill_md_count: number; present: boolean; skills_dir: string }
  kimi_global?: { skill_md_count: number; present: boolean; skills_dir: string }
  projects?: { projects_indexed: number; workspace_skill_md_count: number }
}

type SkillSyncHint = {
  global_repo?: boolean
  hermes_external_dir?: boolean
  cursor_global_path?: boolean
  claude_global_path?: boolean
  kimi_global_path?: boolean
  cursor_global_slug_parallel?: boolean
  claude_global_slug_parallel?: boolean
  kimi_global_slug_parallel?: boolean
  github?: {
    applicable?: boolean
    tracked?: boolean
    file_clean?: boolean
    pushed_hint?: boolean
    repo_ahead_commits?: number | null
    remote_configured?: boolean
  }
}

function hintForSkillPath(hints: Record<string, SkillSyncHint>, path: string): SkillSyncHint | undefined {
  if (hints[path]) return hints[path]
  const pl = path.toLowerCase()
  for (const [k, v] of Object.entries(hints)) {
    if (k.toLowerCase() === pl) return v
  }
  return undefined
}

export function SkillsView({
  orgs,
  fallbackSkillsRoot,
  onEdit,
}: {
  orgs: Org[] | undefined
  fallbackSkillsRoot?: string | null
  onEdit: (path: string) => void
}) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState<FilterValue>({ type: 'all' })
  const [registryTab, setRegistryTab] = useState<RegistryTab>('all')
  const [indexed, setIndexed] = useState<IndexedSkill[]>([])
  const [indexError, setIndexError] = useState<string | null>(null)
  const [syncStatus, setSyncStatus] = useState<SkillsSyncStatus | null>(null)
  const [syncHints, setSyncHints] = useState<Record<string, SkillSyncHint>>({})
  const [syncStatusError, setSyncStatusError] = useState<string | null>(null)
  const [syncBusy, setSyncBusy] = useState<string | null>(null)
  const [scanReport, setScanReport] = useState<string | null>(null)
  const [autoSyncReport, setAutoSyncReport] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)

  const loadIndexed = useCallback(async () => {
    const acc: IndexedSkill[] = []
    const statusQ = registryTab === 'all' ? '' : `&status=${encodeURIComponent(registryTab)}`
    for (let page = 1; page <= 20; page += 1) {
      const r = await fetch(`/api/skills?limit=200&page=${page}${statusQ}`)
      if (!r.ok) throw new Error(await r.text())
      const payload = (await r.json()) as {
        data?: IndexedSkill[]
        pagination?: { total_pages?: number; total?: number }
      }
      const items = Array.isArray(payload.data) ? payload.data : []
      acc.push(...items)
      const totalPages = payload.pagination?.total_pages ?? 1
      if (items.length === 0 || page >= totalPages) break
    }
    setIndexed(acc)
    setIndexError(null)
  }, [registryTab])

  const loadSyncData = useCallback(async () => {
    setSyncStatusError(null)
    try {
      const rSt = await fetch('/api/skills/sync-status')
      if (!rSt.ok) {
        const raw = await rSt.text()
        const is404 = rSt.status === 404 || raw.toLowerCase().includes('not found')
        throw new Error(
          is404
            ? 'le backend zab ne répond pas sur /api/skills/sync-status (404 — process souvent obsolète). Redémarre zab depuis le dépôt à jour.'
            : raw || rSt.statusText,
        )
      }
      setSyncStatus((await rSt.json()) as SkillsSyncStatus)
    } catch (e) {
      setSyncStatus(null)
      setSyncStatusError(e instanceof Error ? e.message : String(e))
    }

    try {
      const rHi = await fetch('/api/skills/sync-hints?limit=500')
      if (!rHi.ok) throw new Error(await rHi.text())
      const hi = (await rHi.json()) as { hints?: Record<string, SkillSyncHint> }
      setSyncHints(typeof hi.hints === 'object' && hi.hints !== null ? hi.hints : {})
    } catch {
      setSyncHints({})
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await loadIndexed()
      } catch (e) {
        if (!cancelled) setIndexError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setInitialLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadIndexed])

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        await loadSyncData()
      } catch (e) {
        if (!cancelled) setSyncStatusError(e instanceof Error ? e.message : String(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadSyncData])

  const flat = useMemo(() => {
    if (indexed.length) {
      return indexed.map((skill) => ({ org: skill.org, skillsRepoRoot: undefined, skill }))
    }
    if (!orgs) return [] as { org: string; skillsRepoRoot?: string; skill: Skill }[]
    return orgs.flatMap((o) => o.skills.map((s) => ({ org: o.org, skillsRepoRoot: o.skills_repo_root, skill: s })))
  }, [indexed, orgs])

  const visibleRows = useMemo<EnrichedRow[]>(() => {
    return flat
      .map((row) => {
        const project = row.skill.project || inferProjectFromPath(row.skill.path)
        const source = inferSourceFromPath(row.skill.path)
        const categories = categoryTags(row.skill.tags, row.org)
        const rk = row.skill.registry_key || row.skill.key || ''
        const rs = row.skill.registry_status
        return { ...row, project, source, categories, registryKey: rk, registryStatus: rs }
      })
  }, [flat])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return visibleRows.filter((e) => {
      const f = activeFilter
      if (f.type === 'org' && e.org !== f.value) return false
      if (f.type === 'project' && (e.project ?? '__none__') !== f.value) return false
      if (f.type === 'category' && !e.categories.includes(String(f.value))) return false
      if (f.type === 'source' && e.source !== f.value) return false
      if (!q) return true
      const inProj = e.project?.toLowerCase().includes(q) ?? false
      const inDesc = e.skill.description?.toLowerCase().includes(q) ?? false
      const inTags = e.skill.tags?.some((t) => t.toLowerCase().includes(q)) ?? false
      const inCats = e.categories.some((t) => t.toLowerCase().includes(q))
      return (
        e.skill.id.toLowerCase().includes(q) ||
        e.org.toLowerCase().includes(q) ||
        e.skill.path.toLowerCase().includes(q) ||
        inProj ||
        inDesc ||
        inTags ||
        inCats
      )
    })
  }, [visibleRows, query, activeFilter])

  const orgCounts = useMemo(() => bucketCounts(visibleRows, (r) => r.org), [visibleRows])
  const projectCounts = useMemo(
    () => bucketCounts(visibleRows, (r) => r.project ?? '__none__'),
    [visibleRows],
  )
  const categoryCounts = useMemo(
    () => bucketCounts(visibleRows.flatMap((r) => r.categories.map((tag) => ({ ...r, _bucket: tag }))), (r) => r._bucket as string),
    [visibleRows],
  )
  const sourceCounts = useMemo(() => bucketCounts(visibleRows, (r) => r.source), [visibleRows])
  const filterLabel = describeFilter(activeFilter)

  const reloadSkills = useCallback(async () => {
    await loadIndexed()
    await loadSyncData()
  }, [loadIndexed, loadSyncData])

  const registryCounts = syncStatus?.zab_index?.registry_counts
  const registrySummary = registryCounts
    ? `Registre — adoptées ${registryCounts.adopted ?? 0} · candidates ${registryCounts.candidate ?? 0} · ignorées ${registryCounts.ignored ?? 0}${
        (registryCounts.conflict ?? 0) > 0 ? ` · conflits ${registryCounts.conflict}` : ''
      }`
    : null

  if (initialLoading && indexed.length === 0 && !indexError) {
    return (
      <div className="space-y-6" data-testid="skills-view">
        <LoadingState label={t('common.loading')} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h2 className="text-2xl font-semibold tracking-tight">{t('skills.title')}</h2>
        <p className="text-muted-foreground text-sm">
          {visibleRows.length} skills affichées
          {registrySummary ? ` · ${registrySummary}` : null}
        </p>
        <p className="text-muted-foreground max-w-3xl text-xs">
          Zab lit le registre local, affiche toutes les skills connues, puis permet d’adopter, ignorer ou synchroniser les entrées utiles.
        </p>
        {indexError ? <p className="text-xs text-amber-700">Index indisponible, fallback overview: {indexError}</p> : null}
        <div className="flex flex-wrap gap-2 pt-1" role="tablist" aria-label="Filtrer par statut registre">
          {(
            [
              ['all', 'Toutes'],
              ['adopted', 'Adoptées seules'],
              ['candidate', 'Candidats'],
              ['ignored', 'Ignorées'],
              ['conflict', 'Conflits'],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              data-testid={`skills-registry-tab-${id}`}
              onClick={() => setRegistryTab(id)}
              className={cn(
                'rounded-full border px-3 py-1 text-xs font-medium transition',
                registryTab === id
                  ? 'border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900'
                  : 'border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <SkillsSyncPanel
        status={syncStatus}
        statusError={syncStatusError}
        busyKey={syncBusy}
        scanReport={scanReport}
        onScanReportClear={() => setScanReport(null)}
        autoSyncReport={autoSyncReport}
        onAutoSyncReportClear={() => setAutoSyncReport(null)}
        onAutoSync={async () => {
          setSyncBusy('auto')
          setAutoSyncReport(null)
          try {
            const r = await fetch('/api/skills/auto-sync', { method: 'POST' })
            const raw = await r.text()
            let j: {
              imported?: { slug?: string; org?: string; project?: string }[]
              skipped?: string[]
              conflicts?: unknown[]
              errors?: string[]
              hermes?: { changed?: boolean; dry_run?: boolean }
              notification?: { sent?: boolean; skipped?: boolean; reason?: string; error?: string }
            } = {}
            try {
              j = JSON.parse(raw) as typeof j
            } catch {
              throw new Error(raw)
            }
            if (!r.ok) throw new Error(raw)
            const imp = j.imported ?? []
            const slugs = imp.map((x) => x.slug).filter(Boolean) as string[]
            const notif = j.notification
            const notifLine =
              notif?.skipped && notif.reason
                ? `notif: ignorée (${notif.reason})`
                : notif?.sent
                  ? 'notif: envoyée'
                  : notif?.error
                    ? `notif: erreur ${notif.error}`
                    : ''
            const hermesLine =
              j.hermes?.dry_run === true
                ? 'Hermes: dry-run (activez auto_hermes_update ou bouton Hermes apply)'
                : j.hermes?.changed === false
                  ? 'Hermes: déjà aligné'
                  : 'Hermes: config écrite'
            const parts = [
              `importées: ${imp.length}${slugs.length ? ` (${slugs.slice(0, 12).join(', ')}${slugs.length > 12 ? '…' : ''})` : ''}`,
              `ignorées: ${j.skipped?.length ?? 0}`,
              `conflits: ${j.conflicts?.length ?? 0}`,
              `erreurs: ${j.errors?.length ?? 0}`,
              hermesLine,
              notifLine,
            ].filter(Boolean)
            setAutoSyncReport(parts.join(' · '))
            await reloadSkills()
          } catch (e) {
            setAutoSyncReport(e instanceof Error ? e.message : String(e))
          } finally {
            setSyncBusy(null)
          }
        }}
        onScan={async () => {
          setSyncBusy('scan')
          setScanReport(null)
          try {
            const r = await fetch('/api/skills/scan-external-dirs', { method: 'POST' })
            const raw = await r.text()
            let j: {
              imported?: unknown[]
              skipped_existing?: unknown[]
              conflicts?: unknown[]
              errors?: string[]
            } = {}
            try {
              j = JSON.parse(raw) as typeof j
            } catch {
              throw new Error(raw)
            }
            if (!r.ok) throw new Error(raw)
            const parts = [
              `importées: ${j.imported?.length ?? 0}`,
              `déjà présentes: ${j.skipped_existing?.length ?? 0}`,
              `conflits: ${j.conflicts?.length ?? 0}`,
              `erreurs: ${j.errors?.length ?? 0}`,
            ]
            setScanReport(parts.join(' · '))
            await reloadSkills()
          } catch (e) {
            setScanReport(e instanceof Error ? e.message : String(e))
          } finally {
            setSyncBusy(null)
          }
        }}
        onHermesUpdate={async () => {
          setSyncBusy('hermes')
          try {
            const r = await fetch('/api/skills/hermes-update', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ apply: true }),
            })
            if (!r.ok) throw new Error(await r.text())
            await loadSyncData()
          } finally {
            setSyncBusy(null)
          }
        }}
        onHermesExport={async () => {
          setSyncBusy('hermes-exp')
          try {
            const r = await fetch('/api/skills/hermes-export', { method: 'POST' })
            if (!r.ok) throw new Error(await r.text())
            const j = (await r.json()) as { yaml?: string }
            const text = j.yaml ?? ''
            if (text && navigator.clipboard?.writeText) {
              await navigator.clipboard.writeText(text)
              setScanReport('Fragment Hermes copié dans le presse-papiers (skills.external_dirs).')
            } else {
              setScanReport(text || '(fragment vide)')
            }
          } catch (e) {
            setScanReport(e instanceof Error ? e.message : String(e))
          } finally {
            setSyncBusy(null)
          }
        }}
        onGithubSync={async () => {
          setSyncBusy('github')
          try {
            const r = await fetch('/api/skills/github-sync', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ message: 'skill: sync dashboard' }),
            })
            const raw = await r.text()
            let j: { error?: string; pushed?: boolean } = {}
            try {
              j = JSON.parse(raw) as { error?: string; pushed?: boolean }
            } catch {
              throw new Error(raw)
            }
            if (!r.ok) throw new Error(j.error || raw)
            await loadSyncData()
            if (j.error) setScanReport(`GitLab: ${j.error}`)
          } catch (e) {
            setScanReport(e instanceof Error ? e.message : String(e))
          } finally {
            setSyncBusy(null)
          }
        }}
        onRefreshIndex={async () => {
          setSyncBusy('index')
          try {
            const r = await fetch('/api/sync', { method: 'POST' })
            if (!r.ok) throw new Error(await r.text())
            await reloadSkills()
          } catch (e) {
            setSyncStatusError(e instanceof Error ? e.message : String(e))
          } finally {
            setSyncBusy(null)
          }
        }}
      />

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
            placeholder="Rechercher une skill, un tag, un projet…"
            className="border-input bg-background w-full rounded-lg border py-2 pr-3 pl-9 text-sm outline-none transition focus:ring-2 focus:ring-zinc-300"
          />
        </div>
        <div className="text-muted-foreground text-xs">
          {filtered.length} / {visibleRows.length} skills affichées · filtre actif : <span className="font-medium text-zinc-700 dark:text-zinc-200">{filterLabel}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[260px_1fr]">
        <SkillsFilterSidebar
          allCount={visibleRows.length}
          activeFilter={activeFilter}
          onChange={setActiveFilter}
          orgCounts={orgCounts}
          projectCounts={projectCounts}
          categoryCounts={categoryCounts}
          sourceCounts={sourceCounts}
        />

        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between rounded-xl border border-zinc-200 bg-zinc-50 px-4 py-2 dark:border-zinc-800 dark:bg-zinc-900/40">
            <div className="flex items-center gap-2">
              <HugeiconsIcon icon={Layers01Icon} size={16} className="text-zinc-500" />
              <span className="text-sm font-semibold tracking-tight">{filterLabel}</span>
            </div>
            <span className="rounded-full border border-zinc-200 bg-white px-2.5 py-0.5 text-[10px] font-semibold tracking-wide text-zinc-700 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-200">
              {filtered.length} skills
            </span>
          </div>

          <div className="divide-y divide-zinc-100 overflow-hidden rounded-xl border border-zinc-200 bg-white dark:divide-zinc-800 dark:border-zinc-800 dark:bg-zinc-950">
            {filtered.map((row, index) => (
              <SkillRow
                key={`${row.org}:${row.skill.id}:${row.skill.path}:${index}`}
                row={row}
                syncHint={hintForSkillPath(syncHints, row.skill.path)}
                fallbackSkillsRoot={fallbackSkillsRoot}
                onEdit={() => onEdit(row.skill.path)}
                onTagClick={(tag) => setActiveFilter({ type: 'category', value: tag })}
                onRegistryChange={reloadSkills}
              />
            ))}
            {filtered.length === 0 && (
              <div className="text-muted-foreground space-y-2 py-16 px-4 text-center text-sm">
                <p>Aucune skill ne correspond au filtre ou à la recherche.</p>
                {visibleRows.length === 0 &&
                syncStatus?.projects &&
                (syncStatus.projects.workspace_skill_md_count ?? 0) > 0 ? (
                  <p className="text-xs leading-relaxed">
                    {syncStatus.projects.workspace_skill_md_count} SKILL.md ont été détectés dans vos projets mais ne sont
                    pas encore dans l’index affiché (souvent déjà copiés dans le miroir). Lancez{' '}
                    <span className="font-medium text-zinc-700 dark:text-zinc-200">Sync auto</span> en haut de page pour
                    les importer, mettre à jour Hermes et rafraîchir l’index.
                  </p>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SkillSyncPills({ hint }: { hint: SkillSyncHint }) {
  const gh = hint.github
  let ghTone = 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
  let ghLabel = 'GH —'
  let ghTitle = 'GitHub : hors dépôt global'
  if (gh?.applicable) {
    if (gh.pushed_hint) {
      ghTone = 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
      ghLabel = 'GH ✓'
      ghTitle = 'GitHub : suivi Git, fichier propre, branche à jour avec le remote'
    } else if (gh.tracked && gh.file_clean === false) {
      ghTone = 'bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200'
      ghLabel = 'GH ~'
      ghTitle = 'GitHub : modifications locales ou index non commit'
    } else if (gh.tracked && (gh.repo_ahead_commits ?? 0) > 0) {
      ghTone = 'bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200'
      ghLabel = 'GH ↑'
      ghTitle = `GitHub : ${gh.repo_ahead_commits} commit(s) en avance sur le remote (non poussés)`
    } else if (gh.tracked) {
      ghTone = 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'
      ghLabel = 'GH ·'
      ghTitle = 'GitHub : suivi Git (état remote incomplet ou non vérifié)'
    } else {
      ghTone = 'bg-rose-50 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200'
      ghLabel = 'GH ?'
      ghTitle = 'GitHub : fichier non suivi dans le dépôt skills'
    }
  }

  const hermesTone = hint.hermes_external_dir
    ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
    : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
  const hermesTitle = hint.hermes_external_dir
    ? 'Hermes : SKILL.md sous un répertoire listé dans external_dirs'
    : 'Hermes : pas sous external_dirs (mettre à jour Hermes ou config)'

  const cursorLinked =
    hint.cursor_global_path || hint.cursor_global_slug_parallel
  const cursorTone = hint.cursor_global_path
    ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
    : hint.cursor_global_slug_parallel
      ? 'bg-sky-50 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200'
      : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
  const cursorTitle = hint.cursor_global_path
    ? 'Cursor global : ce fichier est sous ~/.cursor/skills'
    : hint.cursor_global_slug_parallel
      ? 'Cursor global : un dossier du même nom existe sous ~/.cursor/skills (copie possible)'
      : 'Cursor global : pas de copie détectée'

  const claudeLinked =
    hint.claude_global_path || hint.claude_global_slug_parallel
  const claudeTone = hint.claude_global_path
    ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
    : hint.claude_global_slug_parallel
      ? 'bg-violet-50 text-violet-900 dark:bg-violet-950/40 dark:text-violet-200'
      : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
  const claudeTitle = hint.claude_global_path
    ? 'Claude global : ce fichier est sous ~/.claude/skills'
    : hint.claude_global_slug_parallel
      ? 'Claude global : un dossier du même nom existe sous ~/.claude/skills'
      : 'Claude global : pas de copie détectée'

  const kimiLinked =
    hint.kimi_global_path || hint.kimi_global_slug_parallel
  const kimiTone = hint.kimi_global_path
    ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300'
    : hint.kimi_global_slug_parallel
      ? 'bg-fuchsia-50 text-fuchsia-900 dark:bg-fuchsia-950/40 dark:text-fuchsia-200'
      : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
  const kimiTitle = hint.kimi_global_path
    ? 'Kimi global : ce fichier est sous ~/.kimi/skills'
    : hint.kimi_global_slug_parallel
      ? 'Kimi global : un dossier du même nom existe sous ~/.kimi/skills'
      : 'Kimi global : pas de copie détectée'

  const repoTone = hint.global_repo
    ? 'bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100'
    : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'
  const repoTitle = hint.global_repo
    ? 'Dépôt skills global (skills_sync.repo_root)'
    : 'Hors dépôt global (skill projet ou autre emplacement)'

  return (
    <div
      className="flex flex-wrap gap-1 pt-1"
      data-testid="skill-sync-pills"
      onClick={(e) => e.stopPropagation()}
    >
      <span
        title={repoTitle}
        className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold tracking-wide', repoTone)}
      >
        miroir
      </span>
      <span
        title={hermesTitle}
        className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold tracking-wide', hermesTone)}
      >
        hermes
      </span>
      <span
        title={cursorTitle}
        className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold tracking-wide', cursorTone)}
      >
        cursor{cursorLinked ? (hint.cursor_global_slug_parallel && !hint.cursor_global_path ? '*' : '') : ''}
      </span>
      <span
        title={claudeTitle}
        className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold tracking-wide', claudeTone)}
      >
        claude{claudeLinked ? (hint.claude_global_slug_parallel && !hint.claude_global_path ? '*' : '') : ''}
      </span>
      <span
        title={kimiTitle}
        className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold tracking-wide', kimiTone)}
      >
        kimi{kimiLinked ? (hint.kimi_global_slug_parallel && !hint.kimi_global_path ? '*' : '') : ''}
      </span>
      <span title={ghTitle} className={cn('rounded px-1.5 py-0.5 text-[9px] font-semibold tracking-wide', ghTone)}>
        {ghLabel}
      </span>
    </div>
  )
}

function SkillRow({
  row,
  syncHint,
  fallbackSkillsRoot,
  onEdit,
  onTagClick,
  onRegistryChange,
}: {
  row: EnrichedRow
  syncHint?: SkillSyncHint
  fallbackSkillsRoot?: string | null
  onEdit: () => void
  onTagClick: (tag: string) => void
  onRegistryChange?: () => Promise<void>
}) {
  const { skill, org, skillsRepoRoot, project, source, categories, registryKey, registryStatus } = row
  const meta = skillIconFor(org, skill.id)
  const orgMeta = skillOrgIcon[org]
  const vsc = vscodeFileHrefForSkill(skill.path, skillsRepoRoot, fallbackSkillsRoot)
  const regKey = registryKey || ''
  const st = (registryStatus || '').toLowerCase()
  const hasReg = Boolean(regKey && onRegistryChange)

  const runRegistry = async (path: string, body?: Record<string, unknown>) => {
    if (!onRegistryChange) return
    const r = await fetch(path, {
      method: 'POST',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    if (!r.ok) throw new Error(await r.text())
    await onRegistryChange()
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onEdit}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onEdit()
        }
      }}
      className="group flex cursor-pointer items-start gap-3 px-4 py-3 transition hover:bg-zinc-50 focus-visible:bg-zinc-50 focus-visible:outline-none dark:hover:bg-zinc-900/40 dark:focus-visible:bg-zinc-900/40"
    >
      <div className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg', meta.tone)}>
        <HugeiconsIcon icon={meta.icon} size={22} strokeWidth={1.6} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold tracking-tight">{prettySkill(skill.id)}</h3>
          <span
            className={cn(
              'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide',
              orgMeta?.tone ?? 'bg-zinc-100 text-zinc-600',
            )}
          >
            {org}
          </span>
          {project ? (
            <span className="inline-flex items-center rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200">
              <HugeiconsIcon icon={FolderLibraryIcon} size={10} className="mr-1" /> {project}
            </span>
          ) : null}
          <span className="inline-flex items-center rounded-full bg-zinc-50 px-2 py-0.5 text-[10px] font-medium text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
            {sourceLabel(source)}
          </span>
          {registryStatus ? (
            <span className="inline-flex items-center rounded-full border border-zinc-200 bg-white px-2 py-0.5 text-[10px] font-medium text-zinc-600 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-300">
              {registryStatus}
            </span>
          ) : null}
        </div>
        {skill.description ? (
          <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs">{skill.description}</p>
        ) : null}
        <div className="mt-1.5 flex flex-wrap items-center gap-1">
          {categories.slice(0, 6).map((tag) => (
            <button
              key={`t-${tag}`}
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onTagClick(tag)
              }}
              className="inline-flex items-center rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-medium text-zinc-700 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
            >
              <HugeiconsIcon icon={Tag01Icon} size={9} className="mr-1" />
              {tag}
            </button>
          ))}
          {skill.uses_connectors?.slice(0, 3).map((x) => (
            <span key={`c-${x}`} className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 dark:bg-blue-950/40 dark:text-blue-200">
              {x}
            </span>
          ))}
          {skill.uses_models?.slice(0, 2).map((x) => (
            <span key={`m-${x}`} className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200">
              {x}
            </span>
          ))}
        </div>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {hasReg ? (
          <div
            className="flex max-w-[220px] flex-wrap justify-end gap-1"
            data-testid="skill-registry-actions"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            {st === 'candidate' ? (
              <button
                type="button"
                data-testid="skill-registry-adopt"
                className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200"
                onClick={() => void runRegistry(`/api/skills/registry/adopt?key=${encodeURIComponent(regKey)}`)}
              >
                Adopter
              </button>
            ) : null}
            {['adopted', 'mirrored', 'published'].includes(st) ? (
              <button
                type="button"
                data-testid="skill-registry-unadopt"
                className="rounded border border-zinc-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                onClick={() => void runRegistry(`/api/skills/registry/unadopt?key=${encodeURIComponent(regKey)}`)}
              >
                Désadopter
              </button>
            ) : null}
            {st === 'ignored' ? (
              <button
                type="button"
                className="rounded border border-zinc-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                onClick={() => void runRegistry(`/api/skills/registry/unignore?key=${encodeURIComponent(regKey)}`)}
              >
                Réactiver
              </button>
            ) : null}
            {st !== 'ignored' ? (
              <button
                type="button"
                data-testid="skill-registry-ignore"
                className="rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
                onClick={() => void runRegistry(`/api/skills/registry/ignore?key=${encodeURIComponent(regKey)}`)}
              >
                Ignorer
              </button>
            ) : null}
            {st === 'conflict' ? (
              <button
                type="button"
                data-testid="skill-registry-resolve"
                className="rounded border border-violet-200 bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-950 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-200"
                onClick={() =>
                  void runRegistry(`/api/skills/registry/resolve-conflict?key=${encodeURIComponent(regKey)}`, {
                    keep_path: skill.path,
                  })
                }
              >
                Résoudre (ce fichier)
              </button>
            ) : null}
          </div>
        ) : null}
        {syncHint ? <SkillSyncPills hint={syncHint} /> : null}
        {vsc ? (
          <a
            href={vsc}
            className="text-[11px] font-medium text-zinc-600 underline opacity-0 transition group-hover:opacity-100 dark:text-zinc-300"
            onClick={(e) => e.stopPropagation()}
          >
            IDE →
          </a>
        ) : null}
      </div>
    </div>
  )
}

function SkillsFilterSidebar({
  allCount,
  activeFilter,
  onChange,
  orgCounts,
  projectCounts,
  categoryCounts,
  sourceCounts,
}: {
  allCount: number
  activeFilter: FilterValue
  onChange: (f: FilterValue) => void
  orgCounts: Array<[string, number]>
  projectCounts: Array<[string, number]>
  categoryCounts: Array<[string, number]>
  sourceCounts: Array<[string, number]>
}) {
  return (
    <aside
      data-testid="skills-filter-sidebar"
      className="self-start rounded-xl border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-950"
    >
      <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
        <HugeiconsIcon icon={Layers01Icon} size={12} /> Filtres
      </div>
      <SidebarItem
        active={activeFilter.type === 'all'}
        onClick={() => onChange({ type: 'all' })}
        label="Toutes les skills"
        count={allCount}
        bold
      />
      <SidebarSection icon={Building01Icon} label="Orgs" items={orgCounts}>
        {orgCounts.map(([name, count]) => (
          <SidebarItem
            key={`o-${name}`}
            active={activeFilter.type === 'org' && activeFilter.value === name}
            onClick={() => onChange({ type: 'org', value: name })}
            label={name}
            count={count}
          />
        ))}
      </SidebarSection>
      <SidebarSection icon={FolderLibraryIcon} label="Projets" items={projectCounts}>
        {projectCounts.map(([name, count]) => (
          <SidebarItem
            key={`p-${name}`}
            active={activeFilter.type === 'project' && activeFilter.value === name}
            onClick={() => onChange({ type: 'project', value: name })}
            label={name === '__none__' ? 'Sans projet (global)' : name}
            count={count}
          />
        ))}
      </SidebarSection>
      <SidebarSection icon={Tag01Icon} label="Catégories" items={categoryCounts} initiallyOpen>
        {categoryCounts.map(([name, count]) => (
          <SidebarItem
            key={`c-${name}`}
            active={activeFilter.type === 'category' && activeFilter.value === name}
            onClick={() => onChange({ type: 'category', value: name })}
            label={name}
            count={count}
          />
        ))}
      </SidebarSection>
      <SidebarSection icon={Layers01Icon} label="Sources" items={sourceCounts}>
        {sourceCounts.map(([name, count]) => (
          <SidebarItem
            key={`s-${name}`}
            active={activeFilter.type === 'source' && activeFilter.value === name}
            onClick={() => onChange({ type: 'source', value: name })}
            label={sourceLabel(name)}
            count={count}
          />
        ))}
      </SidebarSection>
    </aside>
  )
}

function SidebarSection({
  icon,
  label,
  items,
  children,
  initiallyOpen,
}: {
  icon: typeof Tag01Icon
  label: string
  items: Array<[string, number]>
  children: React.ReactNode
  initiallyOpen?: boolean
}) {
  const [open, setOpen] = useState<boolean>(initiallyOpen ?? items.length <= 12)
  if (!items.length) return null
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 rounded px-1 py-1 text-[11px] font-semibold tracking-wide text-zinc-500 uppercase hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-900"
      >
        <span className="flex items-center gap-2">
          <HugeiconsIcon icon={icon} size={12} /> {label}
        </span>
        <span className="flex items-center gap-1 text-[10px] font-medium text-zinc-400 normal-case">
          {items.length}
          <HugeiconsIcon icon={open ? ArrowDown01Icon : ArrowRight01Icon} size={12} />
        </span>
      </button>
      {open ? <div className="mt-1 space-y-0.5">{children}</div> : null}
    </div>
  )
}

function SidebarItem({
  active,
  onClick,
  label,
  count,
  bold,
}: {
  active: boolean
  onClick: () => void
  label: string
  count: number
  bold?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-[12px] transition',
        active
          ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
          : 'text-zinc-700 hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-900',
        bold ? 'font-semibold' : 'font-medium',
      )}
    >
      <span className="truncate">{label}</span>
      <span
        className={cn(
          'shrink-0 rounded-full px-1.5 py-0.5 text-[10px]',
          active ? 'bg-white/20 text-white dark:bg-zinc-900/20 dark:text-zinc-900' : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
        )}
      >
        {count}
      </span>
    </button>
  )
}

function sourceLabel(source: string): string {
  switch (source) {
    case 'cursor':
      return 'Cursor global'
    case 'claude':
      return 'Claude global'
    case 'kimi':
      return 'Kimi global'
    case 'project':
      return 'Projet'
    case 'mirror':
      return 'Miroir skills'
    case 'hermes':
      return 'Hermes ext.'
    default:
      return source || 'autre'
  }
}

function describeFilter(f: FilterValue): string {
  switch (f.type) {
    case 'all':
      return 'Toutes les skills'
    case 'org':
      return `Org · ${f.value}`
    case 'project':
      return `Projet · ${f.value === '__none__' ? 'global' : f.value}`
    case 'category':
      return `Catégorie · ${f.value}`
    case 'source':
      return `Source · ${sourceLabel(f.value)}`
  }
}

function bucketCounts<T extends Record<string, unknown>>(rows: T[], key: (r: T) => string): Array<[string, number]> {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const k = key(row)
    if (!k) continue
    counts.set(k, (counts.get(k) ?? 0) + 1)
  }
  return Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1]
    return a[0].localeCompare(b[0])
  })
}

function inferProjectFromPath(path: string): string | null {
  const p = (path || '').replace(/\\/g, '/')
  if (!p) return null
  if (/\/\.(claude|cursor|kimi)\/skills\//.test(p)) return null
  if (/\/projects\/skills\//.test(p)) return null
  const m = p.match(/\/projects\/([^/]+)(?:\/([^/]+))?\//)
  if (!m) return null
  const a = m[1]
  const b = m[2]
  if (b && !['skills', '.cursor', '.claude', '.kimi'].includes(b)) return b
  if (a && !['skills'].includes(a)) return a
  return null
}

function inferSourceFromPath(path: string): string {
  const p = (path || '').replace(/\\/g, '/')
  if (/\/\.claude\/skills\//.test(p)) return 'claude'
  if (/\/\.cursor\/skills\//.test(p)) return 'cursor'
  if (/\/\.kimi\/skills\//.test(p)) return 'kimi'
  if (/\/projects\/skills\//.test(p)) return 'mirror'
  if (/\/projects\//.test(p)) return 'project'
  return 'autre'
}

function categoryTags(tags: string[] | undefined, org: string): string[] {
  if (!tags?.length) return []
  const o = org.toLowerCase()
  const out: string[] = []
  for (const raw of tags) {
    const t = String(raw).trim()
    if (!t) continue
    if (t.toLowerCase() === o) continue
    if (!out.includes(t)) out.push(t)
  }
  return out
}

function SkillsSyncPanel({
  status,
  statusError,
  busyKey,
  scanReport,
  onScanReportClear,
  autoSyncReport,
  onAutoSyncReportClear,
  onAutoSync,
  onScan,
  onHermesUpdate,
  onHermesExport,
  onGithubSync,
  onRefreshIndex,
}: {
  status: SkillsSyncStatus | null
  statusError: string | null
  busyKey: string | null
  scanReport: string | null
  onScanReportClear: () => void
  autoSyncReport: string | null
  onAutoSyncReportClear: () => void
  onAutoSync: () => Promise<void>
  onScan: () => Promise<void>
  onHermesUpdate: () => Promise<void>
  onHermesExport: () => Promise<void>
  onGithubSync: () => Promise<void>
  onRefreshIndex: () => Promise<void>
}) {
  const { t } = useI18n()
  const gr = status?.global_repo
  const git = gr?.git
  const zi = status?.zab_index
  const he = status?.hermes
  const cu = status?.cursor_global
  const cl = status?.claude_global
  const ki = status?.kimi_global
  const pr = status?.projects

  return (
    <section
      data-testid="skills-sync-panel"
      className="space-y-4 rounded-xl border border-zinc-200 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-900/40"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold tracking-tight">Actions</h3>
          <p className="text-muted-foreground text-xs">
            Scanne, importe et rafraîchit la liste. Les détails techniques sont repliés plus bas.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <SyncActionButton
            testId="skills-sync-auto"
            label="Sync auto"
            busy={busyKey === 'auto'}
            onClick={onAutoSync}
          />
          <SyncActionButton
            testId="skills-sync-scan"
            label="Scanner & copier externes"
            busy={busyKey === 'scan'}
            onClick={onScan}
          />
          <SyncActionButton
            testId="skills-sync-hermes"
            label="Mettre à jour Hermes"
            busy={busyKey === 'hermes'}
            onClick={onHermesUpdate}
          />
          <SyncActionButton
            testId="skills-sync-hermes-export"
            label="Copier fragment Hermes"
            busy={busyKey === 'hermes-exp'}
            variant="secondary"
            onClick={onHermesExport}
          />
          <SyncActionButton
            testId="skills-sync-refresh-index"
            label="Rafraîchir index"
            busy={busyKey === 'index'}
            variant="secondary"
            onClick={onRefreshIndex}
          />
          <SyncActionButton
            testId="skills-sync-github"
            label="Sync GitLab"
            busy={busyKey === 'github'}
            variant="secondary"
            onClick={onGithubSync}
          />
        </div>
      </div>

      {statusError ? (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          <span className="font-medium">Statut sync indisponible.</span> {statusError}
        </p>
      ) : null}
      {autoSyncReport ? (
        <div
          data-testid="skills-auto-sync-report"
          className="flex items-start justify-between gap-2 rounded-lg border border-emerald-200 bg-emerald-50/80 px-3 py-2 text-xs dark:border-emerald-900 dark:bg-emerald-950/40"
        >
          <span className="font-mono text-[11px] break-all">{autoSyncReport}</span>
          <button type="button" className="shrink-0 text-zinc-500 underline" onClick={onAutoSyncReportClear}>
            Fermer
          </button>
        </div>
      ) : null}
      {scanReport ? (
        <div className="flex items-start justify-between gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-2 text-xs dark:border-zinc-700 dark:bg-zinc-950">
          <span className="font-mono text-[11px] break-all">{scanReport}</span>
          <button type="button" className="shrink-0 text-zinc-500 underline" onClick={onScanReportClear}>
            Fermer
          </button>
        </div>
      ) : null}

      <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <span>
          {zi
            ? t('skills.sync.indexedCount', { count: String(zi.skills_total) })
            : t('skills.sync.indexNotLoaded')}
        </span>
        <span>{pr ? `${pr.workspace_skill_md_count} fichiers SKILL.md détectés` : null}</span>
        <span>{gr ? `${gr.skill_md_count} dans le miroir` : null}</span>
      </div>

      <details className="rounded-lg border border-zinc-200 bg-white p-3 text-xs dark:border-zinc-800 dark:bg-zinc-950">
        <summary className="cursor-pointer font-medium text-zinc-700 dark:text-zinc-200">{t('skills.sync.details')}</summary>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <SyncCard
            title={t('skills.sync.mirrorTitle')}
            badges={['miroir', gr?.github_synced_hint ? 'gitlab-synced' : 'gitlab']}
            lines={[
              gr ? `${gr.skill_md_count} SKILL.md copiés` : '—',
              git?.is_git_repo
                ? `git ${git.branch ?? '?'}${git.dirty ? ' · modifs' : ' · propre'}`
                : 'pas de dépôt git',
              git?.ahead != null && git?.behind != null ? `ahead ${git.ahead} / behind ${git.behind}` : null,
            ]}
          />
          <SyncCard
            title="Index zab"
            badges={['scan', 'cache']}
            lines={[
              zi ? `${zi.skills_total} skills indexées (miroir ${zi.global} · sources ${zi.project})` : '—',
              zi ? `${zi.skill_md_paths_configured} entrées adoptées / exposées (registre)` : null,
              zi?.registry_counts
                ? `registre: candidats ${zi.registry_counts.candidate ?? 0} · ignorées ${zi.registry_counts.ignored ?? 0} · conflits ${zi.registry_counts.conflict ?? 0}`
                : null,
            ]}
          />
          <SyncCard
            title="Hermes"
            badges={['hermes']}
            lines={[
              he?.config_exists ? shortenHomeInPath(he.config_path) : 'config absente',
              he
                ? `manquants cfg: ${he.missing_in_hermes?.length ?? 0} · extra: ${he.extra_in_hermes?.length ?? 0}`
                : null,
              he && (he.configured_dirs_missing_on_disk?.length ?? 0) > 0
                ? `dossiers absents: ${he.configured_dirs_missing_on_disk?.length}`
                : null,
            ]}
          />
          <SyncCard title="Cursor global" badges={['cursor-global']} lines={[cu?.present ? `${cu.skill_md_count} skills` : 'dossier absent', cu ? shortenHomeInPath(cu.skills_dir) : null]} />
          <SyncCard title="Claude global" badges={['claude-global']} lines={[cl?.present ? `${cl.skill_md_count} skills` : 'dossier absent', cl ? shortenHomeInPath(cl.skills_dir) : null]} />
          <SyncCard title="Kimi global" badges={['kimi-global']} lines={[ki?.present ? `${ki.skill_md_count} skills` : 'dossier absent', ki ? shortenHomeInPath(ki.skills_dir) : null]} />
          <SyncCard
            title="Sources externes découvertes"
            badges={['source']}
            lines={[pr ? `${pr.projects_indexed} projets · ${pr.workspace_skill_md_count} SKILL.md détectés` : '—']}
          />
        </div>
      </details>
    </section>
  )
}

function SyncCard({
  title,
  badges,
  lines,
  className,
}: {
  title: string
  badges: string[]
  lines: (string | null | undefined)[]
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex flex-col gap-2 rounded-lg border border-zinc-200 bg-white p-3 shadow-sm dark:border-zinc-800 dark:bg-zinc-950',
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-semibold">{title}</span>
        {badges.map((b) => (
          <span
            key={b}
            className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
          >
            {b}
          </span>
        ))}
      </div>
      <ul className="text-muted-foreground space-y-0.5 text-[11px] leading-snug">
        {lines
          .map((line, i) => ({ line, i }))
          .filter((x) => x.line)
          .map(({ line, i }) => (
            <li key={i} className="font-mono break-all">
              {line}
            </li>
          ))}
      </ul>
    </div>
  )
}

function SyncActionButton({
  label,
  busy,
  onClick,
  variant = 'default',
  testId,
}: {
  label: string
  busy: boolean
  onClick: () => void | Promise<void>
  variant?: 'default' | 'secondary'
  testId?: string
}) {
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={busy}
      onClick={() => void onClick()}
      className={cn(
        'rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50',
        variant === 'secondary'
          ? 'border border-zinc-200 bg-white text-zinc-800 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100'
          : 'bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white',
      )}
    >
      {busy ? '…' : label}
    </button>
  )
}

function prettySkill(id: string): string {
  return id.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
