import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react'
import {
  CompassIcon,
  Folder02Icon,
  PuzzleIcon,
  Plug02Icon,
  TestTube01Icon,
  TestTube02Icon,
  LockKeyIcon,
  AiBrain02Icon,
  PencilEdit02Icon,
  PlayCircleIcon,
  Database02Icon,
  CodeFolderIcon,
  GoogleIcon,
  Hammer,
  CloudUploadIcon,
  SparklesIcon,
  Search01Icon,
  HelpSquareIcon,
  CpuIcon,
} from '@hugeicons/core-free-icons'
import { Button, buttonVariants } from '@/components/ui/button'
import { Menu } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { SidebarNav, MobileNavDrawer, type NavId } from '@/components/sidebar-nav'
import { ConnectorsView, ConnectorsConfigFilesPanel } from '@/components/connectors-view'
import { SkillsView } from '@/components/skills-view'
import { ProjectsView } from '@/components/projects-view'
import { TasksInboxView } from '@/components/tasks-inbox-view'
import { shortenHomeInPath, vscodeFileHrefForSkill } from '@/lib/skill-open'
import { cn } from '@/lib/utils'

type McpOverviewBlock = {
  source: string
  servers: { enabled: boolean; name?: string; kind?: string; target?: string }[]
}

type OverviewProject = {
  name: string
  path: string
  org: string
  projects_root: string
  workspace_parent?: string | null
  skills: { id: string; path: string; rel_from_home?: string; source?: string }[]
}

type Overview = {
  skills_root: string | null
  skills_root_configured: boolean
  skills_root_yaml_raw?: string | null
  user_config_path?: string
  zab_version?: string
  dashboard_warning: string | null
  orgs: {
    org: string
    skills: { id: string; path: string; source?: string; project?: string }[]
    skills_repo_root?: string
  }[]
  plugin_bundles: { id: string; path: string; skill_count: number; fs_path?: string }[]
  mcp_configs: Record<string, McpOverviewBlock>
  mcp_registry_relative: string | null
  plugin_config: Record<string, unknown>
  projects?: OverviewProject[]
  projects_roots?: string[]
}

type ScanToolsPayload = {
  cli_commands: { id: string; name: string; kind: string; description: string }[]
  scripts: { id: string; name: string; kind: string; path: string; description: string }[]
}

type EnvRow = {
  name: string
  present: boolean
  in_process: boolean
  in_file: boolean
  masked: string
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const t = await r.text()
    throw new Error(t || r.statusText)
  }
  return r.json() as Promise<T>
}

function useJobRunner() {
  const [lines, setLines] = useState<string[]>([])
  const [jobId, setJobId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)

  const runPreset = useCallback(
    (preset: string, args?: Record<string, unknown>) => {
      setLines([])
      setRunning(true)
      setJobId(null)
      void (async () => {
        try {
          const job = await apiJson<{ id: string }>('/api/jobs/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ preset, args }),
          })
          setJobId(job.id)
          const es = new EventSource(`/api/jobs/${job.id}/stream`)
          es.onmessage = (ev) => {
            try {
              const data = JSON.parse(ev.data) as {
                line?: string
                summary?: { status: string; exit_code: number | null }
              }
              const ln = data.line
              if (typeof ln === 'string') {
                setLines((prev) => [...prev, ln])
              }
              if (data.summary) {
                es.close()
                setRunning(false)
                const st = data.summary.status
                const code = data.summary.exit_code
                if (st === 'done' && code === 0) toast.success('Job terminé')
                else toast.error(`Job terminé : ${st} (code ${code})`)
              }
            } catch {
              const fallback = ev.data != null ? String(ev.data) : ''
              setLines((prev) => [...prev, fallback])
            }
          }
          es.onerror = () => {
            es.close()
            setRunning(false)
            toast.error('Flux SSE interrompu')
          }
        } catch (e) {
          setRunning(false)
          toast.error(e instanceof Error ? e.message : String(e))
        }
      })()
    },
    [],
  )

  return { lines, jobId, running, runPreset }
}

const VALID_TABS: NavId[] = [
  'overview', 'orgs', 'projects', 'tasks_inbox', 'plugins', 'connectors', 'config',
  'tests', 'security', 'exports', 'memory', 'ide', 'models', 'skills',
]

export default function App() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [envRows, setEnvRows] = useState<EnvRow[]>([])
  const [toolsLocal, setToolsLocal] = useState<Record<string, unknown> | null>(null)
  const [exportHints, setExportHints] = useState<Record<string, unknown> | null>(null)
  const { lines, jobId, running, runPreset } = useJobRunner()

  const [skillPath, setSkillPath] = useState('orgs/flowmetrik/skills/flowmetrik-context/SKILL.md')
  const [skillContent, setSkillContent] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)

  const [tab, setTab] = useState<NavId>(() => {
    const hash = window.location.hash.replace('#', '') as NavId
    return VALID_TABS.includes(hash) ? hash : 'overview'
  })
  const [scanTools, setScanTools] = useState<ScanToolsPayload | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const hydratedFromHashRef = useRef(false)

  const navigateTab = useCallback((id: NavId) => {
    setTab(id)
    window.location.hash = id
    setMobileNavOpen(false)
  }, [])

  useEffect(() => {
    if (hydratedFromHashRef.current) return
    hydratedFromHashRef.current = true
    const hash = window.location.hash.replace('#', '') as NavId
    if (VALID_TABS.includes(hash)) {
      setTab(hash)
    }
  }, [])

  useEffect(() => {
    const handler = () => {
      const hash = window.location.hash.replace('#', '') as NavId
      if (VALID_TABS.includes(hash)) setTab(hash)
    }
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const [ov, sec, tl, ex, sc] = await Promise.all([
          apiJson<Overview>('/api/overview'),
          apiJson<{ variables: EnvRow[] }>('/api/security/env'),
          apiJson<Record<string, unknown>>('/api/tools/local'),
          apiJson<Record<string, unknown>>('/api/exports/hints'),
          apiJson<ScanToolsPayload>('/api/tools/scan'),
        ])
        setOverview(ov)
        setEnvRows(sec.variables)
        setToolsLocal(tl)
        setExportHints(ex)
        setScanTools(sc)
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      }
    })()
  }, [])

  const totalSkills = useMemo(
    () => overview?.orgs.reduce((acc, o) => acc + o.skills.length, 0) ?? 0,
    [overview],
  )
  const totalConnectors = useMemo(
    () =>
      overview
        ? Object.values(overview.mcp_configs).reduce((acc, b) => acc + b.servers.length, 0)
        : 0,
    [overview],
  )
  const enabledConnectors = useMemo(
    () =>
      overview
        ? Object.values(overview.mcp_configs).reduce(
            (acc, b) => acc + b.servers.filter((s) => s.enabled).length,
            0,
          )
        : 0,
    [overview],
  )

  const loadSkill = useCallback(async (path?: string) => {
    const target = path ?? skillPath
    if (path) setSkillPath(path)
    try {
      const r = await apiJson<{ content: string }>(`/api/skills/file?path=${encodeURIComponent(target)}`)
      setSkillContent(r.content)
      toast.success('SKILL chargé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [skillPath])

  const saveSkill = async () => {
    try {
      await apiJson(`/api/skills/file?path=${encodeURIComponent(skillPath)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: skillContent }),
      })
      toast.success('SKILL enregistré (backup .zab-backup-*)')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const refreshOverview = useCallback(async () => {
    const ov = await apiJson<Overview>('/api/overview')
    setOverview(ov)
  }, [])

  const refreshScanTools = useCallback(async () => {
    try {
      const sc = await apiJson<ScanToolsPayload>('/api/tools/scan')
      setScanTools(sc)
      toast.success(`Scan terminé — ${sc.cli_commands.length} commandes zab, ${sc.scripts.length} scripts`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const probe = async (kind: 'litellm' | 'openrouter') => {
    try {
      const r = await apiJson<Record<string, unknown>>(`/api/tools/probe?kind=${kind}`)
      toast.message(`Probe ${kind}`, { description: JSON.stringify(r, null, 2).slice(0, 400) })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const titles: Record<NavId, string> = {
    overview: 'Vue d’ensemble',
    orgs: 'Organisations',
    projects: 'Projets',
    tasks_inbox: 'Tâches (multi-outils)',
    plugins: 'Plugins',
    connectors: 'Connecteurs',
    config: 'Configuration',
    tests: 'Tests & jobs',
    security: 'Sécurité',
    exports: 'Exports',
    memory: 'Mémoire',
    ide: 'IDE & outils',
    models: 'Modèles / Cursor',
    skills: 'Skills',
  }

  return (
    <div className="bg-muted/40 text-foreground min-h-screen">
      <div className="flex">
        <SidebarNav value={tab} onChange={navigateTab} />
        <MobileNavDrawer open={mobileNavOpen} onOpenChange={setMobileNavOpen} value={tab} onChange={navigateTab} />
        <main className="min-w-0 flex-1">
          <div className="bg-background/80 sticky top-0 z-10 flex h-14 items-center justify-between gap-2 border-b px-3 backdrop-blur sm:px-6">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 md:hidden"
                aria-label="Ouvrir le menu de navigation"
                onClick={() => setMobileNavOpen(true)}
              >
                <Menu className="size-5" />
              </Button>
              <div className="flex min-w-0 items-center gap-2 text-sm">
                <span className="text-muted-foreground shrink-0">zab</span>
                <span className="text-muted-foreground shrink-0">/</span>
                <span className="truncate font-medium tracking-tight">{titles[tab]}</span>
              </div>
            </div>
            <div className="text-muted-foreground flex min-w-0 max-w-[42%] flex-shrink-0 items-center justify-end sm:max-w-[48%] md:max-w-[55%] lg:max-w-md">
              {overview ? (
                overview.skills_root ? (
                  <code className="bg-muted truncate rounded-md px-2 py-1 text-left font-mono text-[10px] sm:text-xs">
                    {overview.skills_root.replace(/^\/Users\/[^/]+/, '~')}
                  </code>
                ) : (
                  <span className="text-amber-700 dark:text-amber-400 line-clamp-2 text-right text-[10px] sm:text-xs">
                    Config skills manquante
                  </span>
                )
              ) : null}
            </div>
          </div>

          <div className="mx-auto w-full max-w-7xl px-6 py-8">
            {tab === 'overview' && (
              <OverviewSection
                overview={overview}
                totalSkills={totalSkills}
                totalConnectors={totalConnectors}
                enabledConnectors={enabledConnectors}
                onJump={navigateTab}
                refreshScanTools={refreshScanTools}
              />
            )}
            {tab === 'orgs' && (
              <OrgsSection
                overview={overview}
                onJump={navigateTab}
                onOpenSkill={(path) => {
                  navigateTab('skills')
                  void loadSkill(path)
                  setEditorOpen(true)
                }}
              />
            )}
            {tab === 'projects' && (
              <ProjectsView
                overview={overview}
                onOpenSkill={(path) => {
                  navigateTab('skills')
                  void loadSkill(path)
                  setEditorOpen(true)
                }}
                onRefreshOverview={refreshOverview}
              />
            )}
            {tab === 'tasks_inbox' && <TasksInboxView onJump={navigateTab} />}
            {tab === 'plugins' && <PluginsSection overview={overview} onJump={navigateTab} />}
            {tab === 'connectors' && <ConnectorsView />}
            {tab === 'config' && <ConnectorsConfigFilesPanel />}
            {tab === 'skills' && (
              <SkillsView
                orgs={overview?.orgs}
                fallbackSkillsRoot={overview?.skills_root}
                onEdit={(path) => {
                  void loadSkill(path)
                  setEditorOpen(true)
                }}
              />
            )}
            {tab === 'tests' && (
              <TestsSection running={running} runPreset={runPreset} jobId={jobId} lines={lines} />
            )}
            {tab === 'security' && (
              <SecuritySection
                envRows={envRows}
                refreshEnvRows={async () => {
                  const sec = await apiJson<{ variables: EnvRow[] }>('/api/security/env')
                  setEnvRows(sec.variables)
                }}
              />
            )}
            {tab === 'exports' && (
              <ExportsSection running={running} runPreset={runPreset} hints={exportHints} />
            )}
            {tab === 'memory' && (
              <MemorySection running={running} runPreset={runPreset} jobLines={lines} jobId={jobId} />
            )}
            {tab === 'ide' && <IdeSection toolsLocal={toolsLocal} scanTools={scanTools} probe={probe} />}
            {tab === 'models' && <ModelsCodySection />}
          </div>
        </main>
      </div>

      <SkillEditorPanel
        path={skillPath}
        content={skillContent}
        onPathChange={setSkillPath}
        onContentChange={setSkillContent}
        onLoad={() => void loadSkill()}
        onSave={() => void saveSkill()}
        open={editorOpen}
        onOpenChange={setEditorOpen}
      />
    </div>
  )
}

function OverviewSection({
  overview,
  totalSkills,
  totalConnectors,
  enabledConnectors,
  onJump,
  refreshScanTools,
}: {
  overview: Overview | null
  totalSkills: number
  totalConnectors: number
  enabledConnectors: number
  onJump: (id: NavId) => void
  refreshScanTools: () => Promise<void>
}) {
  const [scanRefreshing, setScanRefreshing] = useState(false)
  const [cliOpen, setCliOpen] = useState(false)
  const [cliText, setCliText] = useState('')
  const [cliLoading, setCliLoading] = useState(false)

  const openCliHelp = () => {
    setCliOpen(true)
    setCliLoading(true)
    setCliText('')
    void (async () => {
      try {
        const r = await apiJson<{ text: string }>('/api/cli/help')
        setCliText(r.text)
      } catch (e) {
        setCliText(e instanceof Error ? e.message : String(e))
      } finally {
        setCliLoading(false)
      }
    })()
  }

  if (!overview) return <p className="text-muted-foreground">Chargement…</p>

  const stats = [
    {
      label: 'Organisations',
      value: overview.orgs.length,
      icon: Folder02Icon,
      tone: 'bg-amber-100 text-amber-700',
      target: 'orgs' as NavId,
    },
    {
      label: 'Skills',
      value: totalSkills,
      icon: SparklesIcon,
      tone: 'bg-violet-100 text-violet-700',
      target: 'skills' as NavId,
    },
    {
      label: 'Connecteurs',
      value: `${enabledConnectors}/${totalConnectors}`,
      icon: Plug02Icon,
      tone: 'bg-blue-100 text-blue-700',
      target: 'connectors' as NavId,
    },
    {
      label: 'Plugins',
      value: overview.plugin_bundles.length,
      icon: PuzzleIcon,
      tone: 'bg-emerald-100 text-emerald-700',
      target: 'plugins' as NavId,
    },
  ]

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Vue d’ensemble</h2>
        <p className="text-muted-foreground text-sm">
          État du dépôt skills, MCP et plugins (chemins lus depuis ~/.config/zab/config.yaml).
        </p>
      </header>

      {overview.dashboard_warning ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-100">
          {overview.dashboard_warning}
        </div>
      ) : null}

      <p className="text-muted-foreground text-xs leading-relaxed">
        Serveur zab {overview.zab_version ?? '—'} · Fichier lu :{' '}
        <code className="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">
          {(overview.user_config_path ?? '').replace(/^\/Users\/[^/]+/, '~') || '—'}
        </code>
        · Clé <code className="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">skills_root</code> dans ce fichier :{' '}
        {overview.skills_root_yaml_raw ? (
          <code className="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">{overview.skills_root_yaml_raw}</code>
        ) : (
          <span className="text-amber-800 dark:text-amber-300">absente (le dashboard ne doit pas charger le dépôt)</span>
        )}
      </p>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s) => (
          <button
            key={s.label}
            onClick={() => onJump(s.target)}
            className="group bg-card hover:border-zinc-300 hover:shadow-sm flex items-center gap-4 rounded-xl border border-zinc-200 p-5 text-left transition"
          >
            <div className={cn('flex size-12 items-center justify-center rounded-xl', s.tone)}>
              <HugeiconsIcon icon={s.icon} size={24} strokeWidth={1.7} />
            </div>
            <div>
              <p className="text-2xl font-semibold tracking-tight">{s.value}</p>
              <p className="text-muted-foreground text-xs">{s.label}</p>
            </div>
          </button>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-zinc-100 text-zinc-700">
              <HugeiconsIcon icon={CodeFolderIcon} size={20} />
            </div>
            <div>
              <CardTitle>Racine du dépôt</CardTitle>
              <CardDescription>skills_root dans ~/.config/zab/config.yaml</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <code className="bg-muted block rounded-md px-3 py-2 font-mono text-xs break-all">
              {overview.skills_root ?? '— (non configuré)'}
            </code>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
              <HugeiconsIcon icon={Database02Icon} size={20} />
            </div>
            <div>
              <CardTitle>MCP registry</CardTitle>
              <CardDescription>Skill source de référence</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <code className="bg-muted block rounded-md px-3 py-2 font-mono text-xs break-all">
              {overview.mcp_registry_relative ?? '—'}
            </code>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-zinc-100 text-zinc-700">
            <HugeiconsIcon icon={CompassIcon} size={20} />
          </div>
          <div>
            <CardTitle>Démarrage rapide</CardTitle>
            <CardDescription>Quelques actions courantes</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <QuickJump label="Projets locaux & config" icon={Folder02Icon} onClick={() => onJump('projects')} />
          <QuickJump label="Configurer les connecteurs" icon={Plug02Icon} onClick={() => onJump('connectors')} />
          <QuickJump label="Parcourir les skills" icon={SparklesIcon} onClick={() => onJump('skills')} />
          <QuickJump label="Lancer un job de test" icon={TestTube02Icon} onClick={() => onJump('tests')} />
          <QuickJump label="Vérifier la sécurité" icon={LockKeyIcon} onClick={() => onJump('security')} />
          <QuickJump
            label="Relancer le scan outils"
            icon={Search01Icon}
            disabled={scanRefreshing}
            onClick={async () => {
              setScanRefreshing(true)
              try {
                await refreshScanTools()
              } finally {
                setScanRefreshing(false)
              }
            }}
          />
          <QuickJump label="Options CLI zab (--help)" icon={HelpSquareIcon} onClick={openCliHelp} />
        </CardContent>
      </Card>

      <Dialog open={cliOpen} onOpenChange={setCliOpen}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-hidden sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>Options du CLI zab</DialogTitle>
            <DialogDescription>Sortie de la commande équivalente à `zab --help`.</DialogDescription>
          </DialogHeader>
          <pre className="bg-muted max-h-[min(60vh,520px)] overflow-auto rounded-lg p-3 font-mono text-xs whitespace-pre-wrap">
            {cliLoading ? 'Chargement…' : cliText}
          </pre>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function QuickJump({
  label,
  icon,
  onClick,
  disabled,
}: {
  label: string
  icon: IconSvgElement
  onClick: () => void | Promise<void>
  disabled?: boolean
}) {
  return (
    <button
      onClick={() => void onClick()}
      disabled={disabled}
      type="button"
      className="hover:bg-muted/60 flex items-center justify-between rounded-lg border border-zinc-200 px-3 py-3 text-sm transition disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span className="flex items-center gap-2.5 font-medium">
        <HugeiconsIcon icon={icon} size={18} className="text-zinc-500" />
        {label}
      </span>
      <span className="text-muted-foreground text-xs">→</span>
    </button>
  )
}

function OrgsSection({
  overview,
  onOpenSkill,
  onJump,
}: {
  overview: Overview | null
  onOpenSkill: (path: string) => void
  onJump: (id: NavId) => void
}) {
  if (!overview) return <p className="text-muted-foreground">Chargement…</p>
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Organisations</h2>
        <p className="text-muted-foreground text-sm">{overview.orgs.length} organisations (dépôt + projets locaux fusionnés)</p>
      </header>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {overview.orgs.map((o) => (
          <Card key={o.org}>
            <CardHeader className="flex flex-row items-center gap-3">
              <div className="flex size-12 items-center justify-center rounded-xl bg-zinc-900 text-white">
                <HugeiconsIcon icon={Folder02Icon} size={22} />
              </div>
              <div>
                <CardTitle className="text-lg">{o.org}</CardTitle>
                <CardDescription>{o.skills.length} skills</CardDescription>
              </div>
            </CardHeader>
            <CardContent>
              <ul className="list-none space-y-0.5 pl-0 text-xs">
                {o.skills.map((s) => {
                  const vsc = vscodeFileHrefForSkill(s.path, o.skills_repo_root, overview.skills_root)
                  return (
                    <li key={s.path} className="min-w-0 list-none">
                      <div className="flex min-w-0 items-stretch gap-0 rounded-md border border-transparent transition hover:border-zinc-200/80 hover:bg-muted/50">
                        <button
                          type="button"
                          className="min-w-0 flex-1 px-2 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-zinc-400"
                          onClick={() => onOpenSkill(s.path)}
                        >
                          <span className="text-primary block font-mono text-[11px] font-medium">{s.id}</span>
                          <span className="text-muted-foreground mt-0.5 block truncate font-mono text-[10px]">
                            {shortenHomeInPath(s.path)}
                          </span>
                        </button>
                        <div className="flex shrink-0 flex-col items-end justify-center gap-0.5 pr-1">
                          {s.source === 'workspace' ? (
                            <span className="bg-muted text-muted-foreground rounded px-1 py-0.5 text-[9px]">
                              {s.project ? s.project : 'projet'}
                            </span>
                          ) : null}
                          {vsc ? (
                            <a
                              href={vsc}
                              className="text-primary px-1 py-0.5 text-[10px] underline"
                              onClick={(e) => e.stopPropagation()}
                            >
                              IDE
                            </a>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </CardContent>
          </Card>
        ))}
      </div>

      <p className="text-muted-foreground text-sm">
        Liste des dépôts sous{' '}
        <code className="bg-muted rounded px-1 py-0.5 font-mono text-[11px]">projects_roots</code> et enregistrement dans{' '}
        <code className="font-mono text-[11px]">~/.config/zab/config.yaml</code> : onglet{' '}
        <button type="button" className="text-primary font-medium underline" onClick={() => onJump('projects')}>
          Projets
        </button>
        .
      </p>
    </div>
  )
}

function PluginsSection({
  overview,
  onJump,
}: {
  overview: Overview | null
  onJump: (id: NavId) => void
}) {
  if (!overview) return <p className="text-muted-foreground">Chargement…</p>
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Plugins</h2>
        <p className="text-muted-foreground text-sm">{overview.plugin_bundles.length} bundles</p>
      </header>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {overview.plugin_bundles.map((b) => (
          <div
            key={b.id}
            className="bg-card flex flex-col gap-2 rounded-xl border border-zinc-200 p-4 transition hover:border-zinc-300 hover:shadow-sm"
          >
            <div className="flex items-center gap-3">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700">
                <HugeiconsIcon icon={PuzzleIcon} size={24} strokeWidth={1.7} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{b.id}</p>
                <p className="text-muted-foreground text-xs">{b.skill_count} skills</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="text-xs"
                disabled={!overview.skills_root && !overview.plugin_bundles.some((b) => b.fs_path)}
                onClick={() => {
                  const fs = b.fs_path?.replace(/\/$/, '')
                  const root = overview.skills_root?.replace(/\/$/, '')
                  let href: string | null = null
                  if (fs) {
                    href = `vscode://file${fs}`
                  } else if (root) {
                    const rel = b.path.replace(/^\//, '')
                    href = `vscode://file/${root}/${rel}`
                  }
                  if (!href) return
                  window.location.href = href
                }}
              >
                Ouvrir dossier
              </Button>
              <Button type="button" variant="secondary" size="sm" className="text-xs" onClick={() => onJump('skills')}>
                Liste skills
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function TestsSection({
  running,
  runPreset,
  jobId,
  lines,
}: {
  running: boolean
  runPreset: (p: string, a?: Record<string, unknown>) => void
  jobId: string | null
  lines: string[]
}) {
  const presets = [
    { id: 'smoke_mcps', label: 'Smoke MCP', icon: TestTube02Icon, tone: 'bg-emerald-100 text-emerald-700' },
    { id: 'gateway_pytest', label: 'Pytest gateway', icon: TestTube01Icon, tone: 'bg-blue-100 text-blue-700' },
    { id: 'sync_mcps_litellm', label: 'Sync → Litellm', icon: CloudUploadIcon, tone: 'bg-violet-100 text-violet-700' },
    { id: 'build_plugins', label: 'build-plugins.sh', icon: Hammer, tone: 'bg-amber-100 text-amber-700' },
    { id: 'google_oauth_mehdi_context', label: 'OAuth Google', icon: GoogleIcon, tone: 'bg-rose-100 text-rose-700' },
  ]
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Tests & jobs</h2>
        <p className="text-muted-foreground text-sm">Lancement de scripts du dépôt avec sortie en direct.</p>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {presets.map((p) => (
          <button
            key={p.id}
            type="button"
            disabled={running}
            onClick={() => runPreset(p.id)}
            className="group bg-card hover:border-zinc-300 hover:shadow-sm flex flex-col items-start gap-3 rounded-xl border border-zinc-200 p-4 text-left transition disabled:opacity-50"
          >
            <div className={cn('flex size-11 items-center justify-center rounded-xl', p.tone)}>
              <HugeiconsIcon icon={p.icon} size={22} strokeWidth={1.7} />
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight">{p.label}</p>
              <p className="text-muted-foreground inline-flex items-center gap-1 text-[11px]">
                <HugeiconsIcon icon={PlayCircleIcon} size={12} />
                preset
              </p>
            </div>
          </button>
        ))}
      </div>

      {jobId && <p className="text-muted-foreground text-xs">Job : <code>{jobId}</code></p>}

      <Card>
        <CardHeader>
          <CardTitle>Logs</CardTitle>
          <CardDescription>Flux SSE en direct</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="max-h-[420px] overflow-auto rounded-lg bg-zinc-950 p-4 text-[11px] leading-5 whitespace-pre-wrap text-emerald-200">
            {lines.join('\n') || (running ? 'En attente de sortie…' : '— aucun log —')}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}

function SecuritySection({
  envRows,
  refreshEnvRows,
}: {
  envRows: EnvRow[]
  refreshEnvRows: () => Promise<void>
}) {
  const [envPathDisplay, setEnvPathDisplay] = useState<string | null>(null)
  const [envDraft, setEnvDraft] = useState('')
  const [envLoading, setEnvLoading] = useState(true)
  const [envSaving, setEnvSaving] = useState(false)

  const loadEnvFile = useCallback(async () => {
    setEnvLoading(true)
    try {
      const data = await apiJson<{
        path_display: string
        content: string
      }>('/api/security/env-file')
      setEnvPathDisplay(data.path_display)
      setEnvDraft(data.content)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setEnvLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadEnvFile()
  }, [loadEnvFile])

  const saveEnvFile = async () => {
    setEnvSaving(true)
    try {
      const res = await apiJson<{ backup: string | null }>('/api/security/env-file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: envDraft }),
      })
      toast.success(res.backup ? `Enregistré (copie : ${res.backup})` : 'Enregistré')
      await refreshEnvRows()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setEnvSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Sécurité</h2>
        <p className="text-muted-foreground text-sm">
          Variables suivies (processus zab et fichier <code className="bg-muted rounded px-1">.env</code> à la racine
          skills). Valeurs sensibles : affichage intégral uniquement dans l’éditeur ci‑dessous.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Fichier .env</CardTitle>
          <CardDescription>
            {envPathDisplay ? (
              <>
                Chemin : <code className="font-mono text-xs">{envPathDisplay}</code>
              </>
            ) : (
              'Chargement du chemin…'
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-muted-foreground text-xs">
            Le contenu est lu et écrit tel quel sur le disque. Une copie horodatée est créée avant remplacement si le
            fichier existait déjà.
          </p>
          {envLoading ? (
            <p className="text-muted-foreground text-sm">Chargement…</p>
          ) : (
            <Textarea
              className="font-mono text-xs leading-relaxed min-h-[220px]"
              spellCheck={false}
              value={envDraft}
              onChange={(e) => setEnvDraft(e.target.value)}
            />
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" disabled={envLoading || envSaving} onClick={() => void loadEnvFile()}>
              Recharger depuis le disque
            </Button>
            <Button type="button" disabled={envLoading || envSaving} onClick={() => void saveEnvFile()}>
              Enregistrer .env
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nom</TableHead>
                <TableHead>Processus</TableHead>
                <TableHead>Fichier .env</TableHead>
                <TableHead>Aperçu masqué</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {envRows.map((row) => (
                <TableRow key={row.name}>
                  <TableCell className="font-mono text-xs">{row.name}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1',
                        row.in_process
                          ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                          : 'bg-zinc-100 text-zinc-600 ring-zinc-200',
                      )}
                    >
                      {row.in_process ? 'oui' : 'non'}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        'inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium ring-1',
                        row.in_file
                          ? 'bg-sky-50 text-sky-800 ring-sky-200'
                          : 'bg-zinc-100 text-zinc-600 ring-zinc-200',
                      )}
                    >
                      {row.in_file ? 'oui' : 'non'}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{row.masked || '—'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function ExportsSection({
  running,
  runPreset,
  hints,
}: {
  running: boolean
  runPreset: (p: string, a?: Record<string, unknown>) => void
  hints: Record<string, unknown> | null
}) {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Exports</h2>
        <p className="text-muted-foreground text-sm">Synchronisation des MCP et build des plugins.</p>
      </header>
      <div className="flex flex-wrap gap-2">
        <Button disabled={running} onClick={() => runPreset('sync_mcps_litellm')}>
          <HugeiconsIcon icon={CloudUploadIcon} size={16} className="mr-1.5" />
          Sync Litellm
        </Button>
        <Button disabled={running} variant="secondary" onClick={() => runPreset('build_plugins')}>
          <HugeiconsIcon icon={Hammer} size={16} className="mr-1.5" />
          build-plugins
        </Button>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Indices</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="bg-muted overflow-auto rounded-lg p-3 text-xs">
            {JSON.stringify(hints, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}

type MemoryStatusPayload = {
  configured: boolean
  connected: boolean
  psycopg_available: boolean
  document_count: number | null
  chunk_count: number | null
  error: string | null
}

type MemoryDocRow = {
  id: string
  source: string
  export_batch_id: string
  wing: string | null
  room: string | null
  synced_at: string | null
  metadata: unknown
}

type MemoryChunkRow = {
  id: string
  document_id: string
  content_excerpt: string
  chunk_index: number
  created_at: string | null
}

function MemorySection({
  running,
  runPreset,
  jobLines,
  jobId,
}: {
  running: boolean
  runPreset: (p: string, a?: Record<string, unknown>) => void
  jobLines: string[]
  jobId: string | null
}) {
  const [jsonlPath, setJsonlPath] = useState('')
  const [status, setStatus] = useState<MemoryStatusPayload | null>(null)
  const [docOffset, setDocOffset] = useState(0)
  const [docs, setDocs] = useState<MemoryDocRow[]>([])
  const [docsErr, setDocsErr] = useState<string | null>(null)
  const [chunksByDoc, setChunksByDoc] = useState<Record<string, MemoryChunkRow[]>>({})
  const [chunksLoading, setChunksLoading] = useState<string | null>(null)
  const pageSize = 20

  const loadStatus = useCallback(async () => {
    try {
      const s = await apiJson<MemoryStatusPayload>('/api/memory/status')
      setStatus(s)
    } catch {
      setStatus(null)
    }
  }, [])

  const loadDocuments = useCallback(async () => {
    setDocsErr(null)
    try {
      const r = await fetch(`/api/memory/documents?limit=${pageSize}&offset=${docOffset}`)
      if (!r.ok) {
        const t = await r.text()
        setDocs([])
        setDocsErr(t || r.statusText)
        return
      }
      const j = (await r.json()) as { documents: MemoryDocRow[] }
      setDocs(j.documents ?? [])
    } catch (e) {
      setDocs([])
      setDocsErr(e instanceof Error ? e.message : String(e))
    }
  }, [docOffset])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  useEffect(() => {
    void loadDocuments()
  }, [loadDocuments])

  const openChunks = async (documentId: string) => {
    if (chunksByDoc[documentId]) {
      const next = { ...chunksByDoc }
      delete next[documentId]
      setChunksByDoc(next)
      return
    }
    setChunksLoading(documentId)
    try {
      const j = await apiJson<{ chunks: MemoryChunkRow[] }>(
        `/api/memory/chunks?document_id=${encodeURIComponent(documentId)}&limit=50`,
      )
      setChunksByDoc((prev) => ({ ...prev, [documentId]: j.chunks ?? [] }))
    } catch {
      toast.error('Impossible de charger les chunks')
    } finally {
      setChunksLoading(null)
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Mémoire</h2>
        <p className="text-muted-foreground text-sm">
          MemPalace (local) produit du JSONL ; zab importe dans Postgres via{' '}
          <code className="bg-muted rounded px-1 text-xs">MEHDI_MEMORY_DATABASE_URL</code>. Sources officielles :{' '}
          <a
            className="text-primary underline"
            href="https://github.com/MemPalace/mempalace"
            target="_blank"
            rel="noreferrer"
          >
            GitHub MemPalace
          </a>
          ,{' '}
          <a className="text-primary underline" href="https://pypi.org/project/mempalace/" target="_blank" rel="noreferrer">
            PyPI mempalace
          </a>
          .
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>MemPalace CLI</CardTitle>
          <CardDescription>
            Installation isolée recommandée (<code className="text-xs">uv tool install</code>). N’utilisez que les
            sources officielles listées ci-dessus.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button type="button" disabled={running} onClick={() => runPreset('mempalace_install')}>
              Installer MemPalace (uv tool)
            </Button>
          </div>
          {jobId && jobLines.length > 0 ? (
            <pre className="bg-muted max-h-40 overflow-auto rounded-lg p-3 text-[11px]">{jobLines.join('\n')}</pre>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>État Postgres</CardTitle>
            <CardDescription>Lecture seule des tables mehdi_memory_* (même DSN que le gateway).</CardDescription>
          </div>
          <Button type="button" variant="secondary" size="sm" onClick={() => void loadStatus().then(() => loadDocuments())}>
            Rafraîchir
          </Button>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {!status ? (
            <p className="text-muted-foreground">Chargement…</p>
          ) : (
            <ul className="text-muted-foreground space-y-1 text-xs">
              <li>
                DSN configuré :{' '}
                <span className="text-foreground font-medium">{status.configured ? 'oui' : 'non'}</span>
              </li>
              <li>
                Driver psycopg :{' '}
                <span className="text-foreground font-medium">{status.psycopg_available ? 'oui' : 'non'}</span>
                {!status.psycopg_available ? (
                  <span className="ml-1">— installez avec : uv sync --extra memory</span>
                ) : null}
              </li>
              <li>
                Connexion :{' '}
                <span className="text-foreground font-medium">{status.connected ? 'ok' : 'non'}</span>
              </li>
              {status.document_count != null ? (
                <li>
                  Documents : {status.document_count} — chunks : {status.chunk_count ?? '—'}
                </li>
              ) : null}
              {status.error ? (
                <li className="text-amber-800 dark:text-amber-200">{status.error}</li>
              ) : null}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Importer JSONL</CardTitle>
          <CardDescription>Chemin sous le repo skills ou $HOME ; exécuté dans le dépôt skills configuré.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <input
            className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm"
            placeholder="chemin/vers/export.jsonl"
            value={jsonlPath}
            onChange={(e) => setJsonlPath(e.target.value)}
          />
          <Button
            disabled={running || !jsonlPath.trim()}
            onClick={() => runPreset('memory_import', { jsonl_path: jsonlPath.trim() })}
          >
            <HugeiconsIcon icon={AiBrain02Icon} size={16} className="mr-1.5" />
            Importer
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Documents en base</CardTitle>
          <CardDescription>Aperçu paginé (tri par synced_at décroissant).</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {docsErr ? <p className="text-destructive text-xs">{docsErr}</p> : null}
          {!docsErr && docs.length === 0 ? (
            <p className="text-muted-foreground text-xs">Aucun document (ou connexion indisponible).</p>
          ) : null}
          {docs.length > 0 ? (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-24">Voir</TableHead>
                    <TableHead>export_batch_id</TableHead>
                    <TableHead>wing</TableHead>
                    <TableHead>room</TableHead>
                    <TableHead>synced_at</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {docs.map((d) => (
                    <Fragment key={d.id}>
                      <TableRow>
                        <TableCell>
                          <Button
                            type="button"
                            variant="outline"
                            size="xs"
                            disabled={chunksLoading === d.id}
                            onClick={() => void openChunks(d.id)}
                          >
                            {chunksByDoc[d.id] ? 'Masquer' : 'Chunks'}
                          </Button>
                        </TableCell>
                        <TableCell className="max-w-[180px] truncate font-mono text-xs">{d.export_batch_id}</TableCell>
                        <TableCell className="text-xs">{d.wing ?? '—'}</TableCell>
                        <TableCell className="text-xs">{d.room ?? '—'}</TableCell>
                        <TableCell className="text-xs">{d.synced_at ?? '—'}</TableCell>
                      </TableRow>
                      {chunksByDoc[d.id] ? (
                        <TableRow key={`${d.id}-chunks`}>
                          <TableCell colSpan={5} className="bg-muted/40 align-top">
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px]">
                              {chunksByDoc[d.id]
                                .map((c) => `[#${c.chunk_index}] ${c.content_excerpt}`)
                                .join('\n\n—\n\n')}
                            </pre>
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={docOffset === 0}
                  onClick={() => setDocOffset((o) => Math.max(0, o - pageSize))}
                >
                  Précédent
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={docs.length < pageSize}
                  onClick={() => setDocOffset((o) => o + pageSize)}
                >
                  Suivant
                </Button>
              </div>
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

function IdeSection({
  toolsLocal,
  scanTools,
  probe,
}: {
  toolsLocal: Record<string, unknown> | null
  scanTools: ScanToolsPayload | null
  probe: (kind: 'litellm' | 'openrouter') => void
}) {
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">IDE & outils</h2>
        <p className="text-muted-foreground text-sm">Configuration locale et tests d’endpoints LLM.</p>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>local-tools.yaml</CardTitle>
            <CardDescription>Copie zab/local-tools.example.yaml → zab/local-tools.yaml</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <pre className="bg-muted max-h-64 overflow-auto rounded-lg p-3 text-xs">
              {JSON.stringify(toolsLocal, null, 2)}
            </pre>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => probe('litellm')}>
                Tester LiteLLM /models
              </Button>
              <Button variant="outline" onClick={() => probe('openrouter')}>
                Tester OpenRouter /models
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Outils CLI</CardTitle>
            <CardDescription>Commandes zab et scripts du dépôt</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!scanTools ? (
              <p className="text-muted-foreground text-sm">Chargement…</p>
            ) : (
              <div className="space-y-4">
                <div>
                  <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Commandes zab</p>
                  <ul className="space-y-1">
                    {scanTools.cli_commands.map((c) => (
                      <li key={c.id} className="flex items-center gap-2 text-xs">
                        <code className="bg-muted rounded px-1.5 py-0.5 font-mono">{c.name}</code>
                        <span className="text-muted-foreground">{c.description}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Scripts ({scanTools.scripts.length})</p>
                  <ul className="space-y-1 max-h-64 overflow-auto">
                    {scanTools.scripts.map((s) => (
                      <li key={s.id} className="flex items-start gap-2 text-xs">
                        <code className="bg-muted rounded px-1.5 py-0.5 font-mono shrink-0">{s.name}</code>
                        <span className="text-muted-foreground line-clamp-2">{s.description}</span>
                        <a
                          href={`vscode://file/${s.path}`}
                          className={buttonVariants({ variant: 'ghost', size: 'xs' })}
                          title="Ouvrir dans l'éditeur"
                        >
                          →
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function ModelsCodySection() {
  const [scan, setScan] = useState<Record<string, unknown> | null>(null)
  const [last, setLast] = useState<Record<string, unknown> | null>(null)
  const [discoveryMeta, setDiscoveryMeta] = useState<{
    user_config_path?: string
    models_discovery?: Record<string, unknown>
    agentpipe_config_path_override?: string
    codexbar_config_path_override?: string
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [persist, setPersist] = useState(true)

  const reloadDiscovery = async () => {
    try {
      const d = await apiJson<{
        user_config_path?: string
        models_discovery?: Record<string, unknown>
        agentpipe_config_path_override?: string
        codexbar_config_path_override?: string
      }>('/api/config/models-discovery')
      setDiscoveryMeta(d)
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        const j = await apiJson<Record<string, unknown>>('/api/scan/last')
        if (j.present === true) setLast(j)
      } catch {
        /* ignore */
      }
      await reloadDiscovery()
    })()
  }, [])

  const runScan = async () => {
    setLoading(true)
    try {
      const q = persist ? '?persist=1' : ''
      const j = await apiJson<Record<string, unknown>>(`/api/scan${q}`)
      setScan(j)
      toast.success(persist ? 'Scan terminé — scan-last.yaml + models_discovery dans config.yaml' : 'Scan terminé')
      await reloadDiscovery()
      try {
        const again = await apiJson<Record<string, unknown>>('/api/scan/last')
        if (again.present === true) setLast(again)
      } catch {
        /* ignore */
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const displayPayload =
    scan ??
    (last?.present === true && typeof last.scan === 'object' && last.scan !== null
      ? (last.scan as Record<string, unknown>)
      : null)

  const ap = (displayPayload?.agentpipe as Record<string, unknown> | undefined) || {}
  const cb = (displayPayload?.codexbar as Record<string, unknown> | undefined) || {}
  const cc = (displayPayload?.cursor_cody as Record<string, unknown> | undefined) || {}
  const clisBlock = displayPayload?.clis as Record<string, unknown> | undefined
  const wl = (clisBlock?.watchlist as { name: string; on_path: boolean; which_path?: string | null }[]) || []
  const ms = (displayPayload?.memory_stack as Record<string, unknown> | undefined) || {}
  const msMp = (ms.mempalace as Record<string, unknown> | undefined) || {}
  const msProbe = (ms.postgres_probe as Record<string, unknown> | undefined) || {}
  const msScripts = (ms.skills_scripts as Record<string, unknown> | undefined) || {}

  const agents = Array.isArray(ap.agents) ? (ap.agents as Record<string, unknown>[]) : []
  const codingFlat = Array.isArray(ap.coding_models_flat) ? (ap.coding_models_flat as string[]) : []
  const probe = (cb.cli_probe as Record<string, unknown> | undefined) || {}

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">Modèles & Cursor (agentpipe · CodexBar)</h2>
        <p className="text-muted-foreground text-sm">
          Lecture du fichier agentpipe (coding models par agent), du JSON CodexBar et test CLI{' '}
          <code className="bg-muted rounded px-1 text-xs">codexbar --version</code> +{' '}
          <code className="bg-muted rounded px-1 text-xs">codexbar config validate</code>. Définissez des chemins
          absolus avec <code className="bg-muted rounded px-1 text-xs">agentpipe_config_path</code> /{' '}
          <code className="bg-muted rounded px-1 text-xs">codexbar_config_path</code> dans{' '}
          <code className="bg-muted rounded px-1 text-xs">~/.config/zab/config.yaml</code>. Pour Cursor/Cody et la liste{' '}
          <code className="bg-muted rounded px-1 text-xs">cli_watchlist</code>, voir aussi local-tools.yaml.
        </p>
      </header>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-sky-100 text-sky-800">
            <HugeiconsIcon icon={CpuIcon} size={20} />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" disabled={loading} onClick={() => void runScan()}>
              {loading ? 'Scan…' : 'Lancer le scan'}
            </Button>
            <label className="text-muted-foreground flex cursor-pointer items-center gap-2 text-xs">
              <input type="checkbox" checked={persist} onChange={(e) => setPersist(e.target.checked)} />
              Enregistrer après scan (<code className="bg-muted rounded px-1">scan-last.yaml</code>,{' '}
              <code className="bg-muted rounded px-1">last_scan_at_utc</code> et bloc{' '}
              <code className="bg-muted rounded px-1">models_discovery</code>)
            </label>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          {!displayPayload ? (
            <p className="text-muted-foreground text-sm">
              Aucun jeu de données — lance un scan ou recharge : le dernier{' '}
              <code className="bg-muted rounded px-1 text-xs">scan-last.yaml</code> sera utilisé s&apos;il existe.
            </p>
          ) : (
            <>
              <div className="space-y-3">
                <p className="text-muted-foreground text-[11px] font-medium uppercase">Agentpipe — coding models</p>
                <p className="text-muted-foreground font-mono text-xs break-all">
                  Config résolu : {(ap.path as string) || '—'}
                </p>
                {discoveryMeta?.agentpipe_config_path_override ? (
                  <p className="text-muted-foreground text-xs">
                    Override YAML :{' '}
                    <code className="bg-muted rounded px-1">{String(discoveryMeta.agentpipe_config_path_override)}</code>
                  </p>
                ) : null}
                <div className="flex flex-wrap gap-1.5">
                  {codingFlat.length === 0 ? (
                    <span className="text-muted-foreground text-xs">Aucun modèle détecté dans les blocs agents (clés model / models / …).</span>
                  ) : (
                    codingFlat.map((m) => (
                      <span key={m} className="bg-muted rounded-full px-2 py-0.5 font-mono text-[11px]">
                        {m}
                      </span>
                    ))
                  )}
                </div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Agent</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Modèles</TableHead>
                      <TableHead>CLI</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {agents.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={4} className="text-muted-foreground text-xs">
                          Fichier absent ou aucun agent — vérifiez le chemin agentpipe.
                        </TableCell>
                      </TableRow>
                    ) : (
                      agents.map((row) => {
                        const cms = Array.isArray(row.coding_models) ? (row.coding_models as string[]) : []
                        return (
                          <TableRow key={String(row.id)}>
                            <TableCell className="font-mono text-xs">{String(row.id ?? '—')}</TableCell>
                            <TableCell className="font-mono text-xs">{String(row.type ?? '—')}</TableCell>
                            <TableCell className="text-xs">{cms.length ? cms.join(', ') : '—'}</TableCell>
                            <TableCell className="font-mono text-xs">
                              {row.on_path ? String(row.which_path ?? row.probe_binary ?? 'oui') : 'hors PATH'}
                            </TableCell>
                          </TableRow>
                        )
                      })
                    )}
                  </TableBody>
                </Table>
              </div>

              <div className="space-y-3">
                <p className="text-muted-foreground text-[11px] font-medium uppercase">CodexBar — config &amp; CLI</p>
                <p className="text-muted-foreground font-mono text-xs break-all">
                  Config résolu : {(cb.path as string) || '—'}
                </p>
                {discoveryMeta?.codexbar_config_path_override ? (
                  <p className="text-muted-foreground text-xs">
                    Override YAML :{' '}
                    <code className="bg-muted rounded px-1">{String(discoveryMeta.codexbar_config_path_override)}</code>
                  </p>
                ) : null}
                <p className="text-muted-foreground text-xs">
                  Clés JSON :{' '}
                  {Array.isArray(cb.top_level_keys) && (cb.top_level_keys as string[]).length
                    ? (cb.top_level_keys as string[]).join(', ')
                    : '—'}
                </p>
                <pre className="bg-muted max-h-72 overflow-auto rounded-lg p-3 text-xs">{JSON.stringify(probe, null, 2)}</pre>
              </div>

              <div>
                <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Cursor / Cody</p>
                <pre className="bg-muted max-h-64 overflow-auto rounded-lg p-3 text-xs">{JSON.stringify(cc, null, 2)}</pre>
              </div>
              <div>
                <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">CLI watchlist (which)</p>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Binaire</TableHead>
                      <TableHead>PATH</TableHead>
                      <TableHead>Chemin</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {wl.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={3} className="text-muted-foreground text-xs">
                          Liste vide — ajoute <code className="bg-muted rounded px-1">cli_watchlist</code> dans le YAML.
                        </TableCell>
                      </TableRow>
                    ) : (
                      wl.map((row) => (
                        <TableRow key={row.name}>
                          <TableCell className="font-mono text-xs">{row.name}</TableCell>
                          <TableCell>{row.on_path ? 'oui' : 'non'}</TableCell>
                          <TableCell className="font-mono text-xs break-all">{row.which_path ?? '—'}</TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>

              <div className="space-y-3">
                <p className="text-muted-foreground text-[11px] font-medium uppercase">
                  Mémoire MCP (MemPalace → Postgres)
                </p>
                <div className="text-muted-foreground grid gap-2 text-xs md:grid-cols-2">
                  <p>
                    CLI MemPalace :{' '}
                    <span className="font-medium text-foreground">
                      {msMp.on_path === true ? 'sur le PATH' : 'absent'}
                    </span>
                    {typeof msMp.version === 'string' && msMp.version ? (
                      <span className="ml-1 font-mono text-[11px]">({msMp.version})</span>
                    ) : null}
                  </p>
                  <p>
                    DSN <code className="bg-muted rounded px-1">MEHDI_MEMORY_DATABASE_URL</code> :{' '}
                    <span className="font-medium text-foreground">
                      {ms.MEHDI_MEMORY_DATABASE_URL_configured === true ? 'configuré' : 'absent'}
                    </span>
                  </p>
                  <p>
                    Script import :{' '}
                    {msScripts.import_memory_jsonl_exists === true ? (
                      <span className="text-foreground">présent</span>
                    ) : (
                      <span className="text-amber-700">manquant (repo skills)</span>
                    )}
                  </p>
                  <p>
                    Sonde Postgres :{' '}
                    <span className="font-mono text-[11px]">
                      {typeof msProbe.document_count === 'number' && typeof msProbe.chunk_count === 'number'
                        ? `connecté — docs ${msProbe.document_count}, chunks ${msProbe.chunk_count}`
                        : msProbe.skipped_reason != null && msProbe.skipped_reason !== ''
                          ? String(msProbe.skipped_reason)
                          : '—'}
                    </span>
                  </p>
                </div>
              </div>
            </>
          )}
          {discoveryMeta?.models_discovery ? (
            <div>
              <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">
                Copie dans{' '}
                <code className="bg-muted rounded px-1">{discoveryMeta.user_config_path ?? '~/.config/zab/config.yaml'}</code>{' '}
                → models_discovery
              </p>
              <pre className="bg-muted/60 max-h-56 overflow-auto rounded-lg p-3 text-[11px]">
                {JSON.stringify(discoveryMeta.models_discovery, null, 2)}
              </pre>
            </div>
          ) : null}
          {last && last.present === true ? (
            <div>
              <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Dernier scan persisté</p>
              <pre className="bg-muted/60 max-h-48 overflow-auto rounded-lg p-3 text-[11px]">
                {JSON.stringify(last.saved_at_utc ? { saved_at_utc: last.saved_at_utc } : last, null, 2)}
              </pre>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

function SkillEditorPanel({
  path,
  content,
  onPathChange,
  onContentChange,
  onLoad,
  onSave,
  open,
  onOpenChange,
}: {
  path: string
  content: string
  onPathChange: (v: string) => void
  onContentChange: (v: string) => void
  onLoad: () => void
  onSave: () => void
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  if (!open) {
    return (
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        className="pointer-events-auto fixed right-6 bottom-6 z-40 flex items-center gap-2 rounded-full bg-zinc-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg transition hover:bg-zinc-800"
      >
        <HugeiconsIcon icon={PencilEdit02Icon} size={16} />
        Éditer SKILL
      </button>
    )
  }

  return (
    <div className="fixed inset-0 z-30 flex items-stretch justify-end bg-black/30">
      <button className="flex-1" type="button" aria-label="Fermer" onClick={() => onOpenChange(false)} />
      <div className="bg-background flex h-full w-full max-w-3xl flex-col border-l shadow-2xl">
        <div className="flex items-center justify-between border-b px-5 py-3">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-md bg-zinc-100">
              <HugeiconsIcon icon={PencilEdit02Icon} size={16} />
            </div>
            <div>
              <p className="text-sm font-semibold">Éditeur SKILL</p>
              <p className="text-muted-foreground text-[11px]">orgs/… ou claude-plugins/…</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-muted-foreground hover:text-foreground rounded-md px-2 py-1 text-sm"
          >
            Fermer
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b px-5 py-3">
          <input
            className="border-input bg-background min-w-[240px] flex-1 rounded-lg border px-3 py-2 text-sm"
            value={path}
            onChange={(e) => onPathChange(e.target.value)}
          />
          <Button type="button" variant="secondary" onClick={onLoad}>
            Charger
          </Button>
          <Button type="button" onClick={onSave}>
            Enregistrer
          </Button>
        </div>
        <Textarea
          className="flex-1 rounded-none border-0 font-mono text-xs"
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
        />
      </div>
    </div>
  )
}
