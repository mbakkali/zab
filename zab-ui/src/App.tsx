import { Fragment, Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
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
  MessageMultiple02Icon,
} from '@hugeicons/core-free-icons'
import { Button, buttonVariants } from '@/components/ui/button'
import { LoadingState } from '@/components/ui/loading-state'
import { ChevronDown, ChevronRight, Menu, CheckCircle2, XCircle, AlertTriangle, Loader2, Download, Copy, LogIn, RefreshCw, ShieldCheck, ExternalLink } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import { SidebarNav, MobileNavDrawer, type NavId } from '@/components/sidebar-nav'
import type { ChannelItem } from '@/components/channels-view'

// Chaque vue est chargée à la demande (code-splitting) : le bundle initial ne
// contient que le shell + la vue « overview », les autres pages téléchargent
// leur chunk au premier affichage. Cf. <Suspense> plus bas.
const ConnectorsView = lazy(() =>
  import('@/components/connectors-view').then((m) => ({ default: m.ConnectorsView })),
)
const CliCheckView = lazy(() =>
  import('@/components/cli-check-view').then((m) => ({ default: m.CliCheckView })),
)
const ConfigView = lazy(() =>
  import('@/components/config-view').then((m) => ({ default: m.ConfigView })),
)
const SkillsView = lazy(() =>
  import('@/components/skills-view').then((m) => ({ default: m.SkillsView })),
)
const ProjectsView = lazy(() =>
  import('@/components/projects-view').then((m) => ({ default: m.ProjectsView })),
)
const TasksInboxView = lazy(() =>
  import('@/components/tasks-inbox-view').then((m) => ({ default: m.TasksInboxView })),
)
const ConversationsView = lazy(() =>
  import('@/components/conversations-view').then((m) => ({ default: m.ConversationsView })),
)
const InteractionsView = lazy(() =>
  import('@/components/interactions-view').then((m) => ({ default: m.InteractionsView })),
)
const WorkpacketsView = lazy(() =>
  import('@/components/workpackets-view').then((m) => ({ default: m.WorkpacketsView })),
)
const WorkstationView = lazy(() =>
  import('@/components/workstation-view').then((m) => ({ default: m.WorkstationView })),
)
const CapabilitiesView = lazy(() =>
  import('@/components/capabilities-view').then((m) => ({ default: m.CapabilitiesView })),
)
const SourceHealthView = lazy(() =>
  import('@/components/source-health-view').then((m) => ({ default: m.SourceHealthView })),
)
const LogsView = lazy(() =>
  import('@/components/logs-view').then((m) => ({ default: m.LogsView })),
)
const ToolsCatalogView = lazy(() =>
  import('@/components/tools-catalog-view').then((m) => ({ default: m.ToolsCatalogView })),
)
const CronsView = lazy(() => import('@/components/crons-view'))
const ChannelsView = lazy(() =>
  import('@/components/channels-view').then((m) => ({ default: m.ChannelsView })),
)
import { vscodeFileHref } from '@/lib/env-open'
import { shortenHomeInPath, vscodeFileHrefForSkill } from '@/lib/skill-open'
import {
  buildSystemCheckReport,
  consumeSystemCheckStream,
  downloadSystemCheckReport,
  type SystemCheckItem,
  type SystemCheckReport,
  type SystemCheckStatus,
  type SystemCheckSummary,
} from '@/lib/system-check-stream'
import { startJobAndCollectLines } from '@/lib/job-stream'
import { cn } from '@/lib/utils'
import { LanguageSwitcher } from '@/components/language-switcher'
import { useI18n } from '@/i18n/use-i18n'
import { NAV_I18N_KEY } from '@/i18n/nav-labels'
import { useFormatDate } from '@/i18n/format'

type McpOverviewBlock = {
  source: string
  servers: { enabled: boolean; name?: string; kind?: string; target?: string }[]
}

type OverviewProject = {
  id?: string
  name: string
  path: string
  org: string
  projects_root: string
  workspace_parent?: string | null
  skills: { id: string; path: string; rel_from_home?: string; source?: string }[]
  git_repo?: boolean
  git_branch?: string | null
  remote_host?: string | null
  origin_url?: string | null
  origin_https?: string | null
  last_activity_at_utc?: string | null
  last_activity_source?: string | null
  last_activity_path?: string | null
}

type Overview = {
  skills_root: string | null
  skills_roots?: string[]
  skills_root_configured: boolean
  skills_root_yaml_raw?: string | null
  skills_roots_yaml?: string[]
  user_config_path?: string
  zab_version?: string
  dashboard_warning: string | null
  orgs: {
    org: string
    skills: { id: string; path: string; source?: string; project?: string }[]
    projects?: {
      id?: string
      name?: string
      path?: string
      workspace_parent?: string | null
      skills_count?: number
      org?: string
      git_repo?: boolean
      git_branch?: string | null
      remote_host?: string | null
      last_activity_at_utc?: string | null
      last_activity_source?: string | null
      last_activity_path?: string | null
    }[]
    projects_count?: number
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

type StateSummary = {
  version?: string
  last_sync_at?: string
  path?: string
  counts: Record<string, number>
}

/** Agrégation connecteurs de `/api/connectors`, partagée avec l'onglet Connectors. */
type ConnectorsSummaryPayload = {
  data: { id: string; any_enabled?: boolean }[]
  pagination: { total: number }
}

type CodeToolRow = {
  key: string
  id: string
  display_name?: string
  provider?: string
  kind?: string
  binary?: string | null
  installed?: boolean
}

type SecurityReportRow = {
  key: string
  path: string
  updated_at_utc: string
  bytes: number
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
  const { t } = useI18n()
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
                if (st === 'done' && code === 0) toast.success(t('common.jobDone'))
                else toast.error(t('common.jobDoneWithCode', { status: st, code: String(code) }))
              }
            } catch {
              const fallback = ev.data != null ? String(ev.data) : ''
              setLines((prev) => [...prev, fallback])
            }
          }
          es.onerror = () => {
            es.close()
            setRunning(false)
            toast.error(t('common.sseInterrupted'))
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
  'overview', 'system_check', 'cli_check', 'capabilities', 'source_health', 'logs', 'orgs', 'projects', 'tasks_inbox', 'channels', 'conversations', 'interactions', 'workpackets', 'plugins', 'connectors', 'config',
  'tests', 'security', 'memory', 'ide', 'models', 'workstation', 'skills', 'catalog', 'crons',
]

type HashRoute = {
  tab: NavId | null
  id: string | null
}

function encodeRouteId(id?: string | null): string {
  if (!id) return ''
  return id.split('/').map((part) => encodeURIComponent(part)).join('/')
}

/** Accepte `#projects/clients/acme`, `#/orgs/clients`, `#conversations?…`. */
function parseLocationHashToRoute(): HashRoute {
  let raw = window.location.hash.replace(/^#/, '').trim()
  if (!raw) return { tab: null, id: null }
  if (raw.startsWith('/')) raw = raw.slice(1)
  const beforeQuery = raw.split(/[?]/)[0] ?? ''
  const [segment, ...rest] = beforeQuery.split('/')
  if (!segment) return { tab: null, id: null }
  const id = segment as NavId
  if (!VALID_TABS.includes(id)) return { tab: null, id: null }
  const rawRouteId = rest.join('/').trim()
  let routeId: string | null = null
  if (rawRouteId) {
    try {
      routeId = decodeURIComponent(rawRouteId)
    } catch {
      routeId = rawRouteId
    }
  }
  return { tab: id, id: routeId }
}

export default function App() {
  const { t } = useI18n()
  const [overview, setOverview] = useState<Overview | null>(null)
  const [toolsLocal, setToolsLocal] = useState<Record<string, unknown> | null>(null)
  const [stateSummary, setStateSummary] = useState<StateSummary | null>(null)
  const [connectorsSummary, setConnectorsSummary] = useState<ConnectorsSummaryPayload | null>(null)
  const { lines, jobId, running, runPreset } = useJobRunner()
  const {
    lines: securityLines,
    jobId: securityJobId,
    running: securityRunning,
    runPreset: runSecurityPreset,
  } = useJobRunner()
  const [miningProjectPath, setMiningProjectPath] = useState<string | null>(null)

  const handleMineProjectMemory = useCallback(async (projectPath: string, projectName: string) => {
    setMiningProjectPath(projectPath)
    try {
      const r = await startJobAndCollectLines('mempalace_mine', {
        project_path: projectPath,
        wing: projectName,
        mode: 'projects',
      })
      if (r.status === 'done' && r.exit_code === 0) {
        toast.success(t('memory.toast.mempalaceDone', { name: projectName }))
      } else {
        toast.error(
          t('memory.toast.mempalaceFail', {
            name: projectName,
            status: r.status,
            code: String(r.exit_code),
          }),
        )
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setMiningProjectPath(null)
    }
  }, [t])

  const [skillPath, setSkillPath] = useState('orgs/flowmetrik/skills/flowmetrik-context/SKILL.md')
  const [skillContent, setSkillContent] = useState('')
  const [editorOpen, setEditorOpen] = useState(false)

  const initialRoute = useMemo(() => parseLocationHashToRoute(), [])
  const [tab, setTab] = useState<NavId>(() => initialRoute.tab ?? 'overview')
  const [routeId, setRouteId] = useState<string | null>(() => initialRoute.id)
  const [scanTools, setScanTools] = useState<ScanToolsPayload | null>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const navigateRoute = useCallback((id: NavId, entityId?: string | null) => {
    setTab(id)
    setRouteId(entityId || null)
    window.location.hash = entityId ? `${id}/${encodeRouteId(entityId)}` : id
    setMobileNavOpen(false)
  }, [])

  const navigateTab = useCallback((id: NavId) => {
    navigateRoute(id, null)
  }, [navigateRoute])

  useEffect(() => {
    const handler = () => {
      const route = parseLocationHashToRoute()
      if (route.tab) {
        setTab(route.tab)
        setRouteId(route.id)
      } else if (window.location.hash) {
        setTab('overview')
        setRouteId(null)
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}#overview`)
      }
    }
    handler()
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])

  useEffect(() => {
    // Les appels sont volontairement découplés : l'overview ne doit dépendre que
    // des endpoints rapides (/api/overview, /api/state). Le scan des outils
    // (/api/tools/scan) est lent à froid (plusieurs secondes) et ne sert qu'à
    // l'onglet IDE + aux stats de « rescan » ; on le charge en arrière-plan
    // sans bloquer le rendu initial du tableau de bord.
    void (async () => {
      try {
        const ov = await apiJson<Overview>('/api/overview')
        setOverview(ov)
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      }
    })()
    void apiJson<StateSummary>('/api/state')
      .then(setStateSummary)
      .catch(() => {})
    // Source de vérité des connecteurs : la même agrégation que l'onglet Connectors.
    // `overview.mcp_configs` ne couvre que deux fichiers de config historiques et
    // affichait « 0/0 » sur un poste qui expose pourtant des serveurs MCP.
    void apiJson<ConnectorsSummaryPayload>('/api/connectors?limit=200')
      .then(setConnectorsSummary)
      .catch(() => {})
    void apiJson<Record<string, unknown>>('/api/tools/local')
      .then(setToolsLocal)
      .catch(() => {})
    void apiJson<ScanToolsPayload>('/api/tools/scan')
      .then(setScanTools)
      .catch(() => {})
  }, [])

  const totalSkills = useMemo(
    () => overview?.orgs.reduce((acc, o) => acc + o.skills.length, 0) ?? 0,
    [overview],
  )
  const totalConnectors = useMemo(() => {
    if (connectorsSummary) return connectorsSummary.pagination.total
    return overview
      ? Object.values(overview.mcp_configs).reduce((acc, b) => acc + b.servers.length, 0)
      : 0
  }, [connectorsSummary, overview])
  const enabledConnectors = useMemo(() => {
    if (connectorsSummary) return connectorsSummary.data.filter((c) => c.any_enabled).length
    return overview
      ? Object.values(overview.mcp_configs).reduce(
          (acc, b) => acc + b.servers.filter((s) => s.enabled).length,
          0,
        )
      : 0
  }, [connectorsSummary, overview])

  const loadSkill = useCallback(async (path?: string) => {
    const target = path ?? skillPath
    if (path) setSkillPath(path)
    try {
      const r = await apiJson<{ content: string }>(`/api/skills/file?path=${encodeURIComponent(target)}`)
      setSkillContent(r.content)
      toast.success(t('skillEditor.toastLoaded'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [skillPath, t])

  const saveSkill = async () => {
    try {
      await apiJson(`/api/skills/file?path=${encodeURIComponent(skillPath)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: skillContent }),
      })
      toast.success(t('skillEditor.toastSaved'))
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
      toast.success(
        t('overview.toast.scanDone', {
          cli: String(sc.cli_commands.length),
          scripts: String(sc.scripts.length),
        }),
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [t])

  const syncState = useCallback(async () => {
    try {
      const st = await apiJson<StateSummary>('/api/sync', { method: 'POST' })
      setStateSummary(st)
      toast.success(t('overview.toast.indexSynced'))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [t])

  const probe = async (kind: 'litellm' | 'openrouter') => {
    try {
      const r = await apiJson<Record<string, unknown>>(`/api/tools/probe?kind=${kind}`)
      toast.message(`Probe ${kind}`, { description: JSON.stringify(r, null, 2).slice(0, 400) })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const tabTitle = useMemo(() => t(NAV_I18N_KEY[tab]), [t, tab])

  useEffect(() => {
    document.title =
      tab === 'overview' ? t('app.docTitle') : t('app.docTitleTab', { title: tabTitle })
  }, [tab, tabTitle, t])

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
                aria-label={t('nav.openMenu')}
                onClick={() => setMobileNavOpen(true)}
              >
                <Menu className="size-5" />
              </Button>
              <div className="flex min-w-0 items-center gap-2 text-sm">
                <span className="text-muted-foreground shrink-0">zab</span>
                <span className="text-muted-foreground shrink-0">/</span>
                <span className="truncate font-medium tracking-tight">{tabTitle}</span>
                {routeId ? (
                  <>
                    <span className="text-muted-foreground shrink-0">/</span>
                    <span className="text-muted-foreground truncate font-mono text-xs">{routeId}</span>
                  </>
                ) : null}
              </div>
            </div>
            <div className="text-muted-foreground flex min-w-0 max-w-[42%] flex-shrink-0 items-center justify-end gap-2 sm:max-w-[48%] md:max-w-[55%] lg:max-w-md">
              <LanguageSwitcher />
              {overview ? (
                overview.skills_root ? (
                  <code className="bg-muted hidden truncate rounded-md px-2 py-1 text-left font-mono text-[10px] sm:inline sm:text-xs">
                    {overview.skills_root.replace(/^\/Users\/[^/]+/, '~')}
                  </code>
                ) : (
                  <span className="text-alerte line-clamp-2 hidden text-right text-[10px] sm:inline sm:text-xs">
                    {t('app.skillsConfigMissing')}
                  </span>
                )
              ) : null}
            </div>
          </div>

          <div className="mx-auto w-full max-w-7xl px-6 py-8">
            <Suspense fallback={<ViewFallback />}>
            {tab === 'overview' && (
              <OverviewSection
                overview={overview}
                totalSkills={totalSkills}
                totalConnectors={totalConnectors}
                enabledConnectors={enabledConnectors}
                stateSummary={stateSummary}
                onJump={navigateTab}
                refreshScanTools={refreshScanTools}
                syncState={syncState}
              />
            )}
            {tab === 'system_check' && <SystemCheckSection />}
            {tab === 'cli_check' && <CliCheckView />}
            {tab === 'capabilities' && <CapabilitiesView />}
            {tab === 'source_health' && <SourceHealthView />}
            {tab === 'logs' && <LogsView />}
            {tab === 'catalog' && <ToolsCatalogView initialToolId={routeId} />}
            {tab === 'channels' && (
              <ChannelsView
                orgs={overview?.orgs}
                onRefreshStats={refreshOverview}
                onOpenConnectorsConfig={(_channel: ChannelItem) => navigateTab('connectors')}
              />
            )}
            {tab === 'orgs' && (
              <OrgsSection
                overview={overview}
                activeOrgId={routeId}
                onOpenProject={(projectId) => navigateRoute('projects', projectId)}
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
                activeProjectId={routeId}
                onOpenOrg={(org) => navigateRoute('orgs', org)}
                miningProjectPath={miningProjectPath}
                onMineMemory={handleMineProjectMemory}
                onRunSecurityScan={(preset, projectPath) => {
                  navigateTab('security')
                  runSecurityPreset(preset, { project_path: projectPath })
                }}
                onOpenSkill={(path) => {
                  navigateTab('skills')
                  void loadSkill(path)
                  setEditorOpen(true)
                }}
                onRefreshOverview={refreshOverview}
              />
            )}
            {tab === 'tasks_inbox' && <TasksInboxView onJump={navigateTab} />}
            {tab === 'conversations' && <ConversationsView />}
            {tab === 'interactions' && (
              <InteractionsView onOpenTool={(toolId) => navigateRoute('catalog', toolId)} />
            )}
            {tab === 'workpackets' && <WorkpacketsView />}
            {tab === 'plugins' && <PluginsSection overview={overview} onJump={navigateTab} />}
            {tab === 'connectors' && <ConnectorsView />}
            {tab === 'config' && <ConfigView />}
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
                running={securityRunning}
                runPreset={runSecurityPreset}
                jobId={securityJobId}
                jobLines={securityLines}
              />
            )}
            {tab === 'memory' && (
              <MemorySection
                projects={overview?.projects ?? []}
                miningProjectPath={miningProjectPath}
                running={running}
                runPreset={runPreset}
                jobLines={lines}
                jobId={jobId}
              />
            )}
            {tab === 'ide' && <IdeSection toolsLocal={toolsLocal} scanTools={scanTools} probe={probe} />}
            {tab === 'models' && <ModelsCodySection />}
            {tab === 'workstation' && <WorkstationView />}
            {tab === 'crons' && <CronsView />}
            </Suspense>
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

function ViewFallback() {
  return (
    <div
      data-testid="view-fallback"
      className="flex min-h-[40vh] items-center justify-center"
    >
      <Loader2 className="text-muted-foreground size-6 animate-spin" />
    </div>
  )
}

function StatusIcon({ status }: { status: SystemCheckStatus }) {
  if (status === 'ok') return <CheckCircle2 className="size-5 text-succes" />
  if (status === 'warn') return <AlertTriangle className="size-5 text-alerte" />
  if (status === 'fail') return <XCircle className="size-5 text-danger" />
  if (status === 'running') return <Loader2 className="size-5 animate-spin text-info" />
  // pending — grisé
  return <div className="size-5 rounded-full border-2 border-border bg-muted" />
}

function statusLabel(status: SystemCheckStatus, t: (key: string) => string) {
  if (status === 'ok') return t('common.ok')
  if (status === 'warn') return t('common.warn')
  if (status === 'fail') return t('common.fail')
  if (status === 'running') return t('systemCheck.running')
  return t('common.pending')
}

function applySystemCheckReport(
  report: SystemCheckReport,
  setters: {
    setChecks: (v: Record<string, SystemCheckItem>) => void
    setSummary: (v: SystemCheckSummary) => void
    setReport: (v: SystemCheckReport) => void
    checksRef: { current: Record<string, SystemCheckItem> }
  },
) {
  const map: Record<string, SystemCheckItem> = {}
  for (const chk of report.checks) {
    map[chk.id] = chk
  }
  setters.checksRef.current = map
  setters.setChecks(map)
  setters.setSummary({
    generated_at_utc: report.generated_at_utc,
    percentage: report.percentage,
    score: report.score,
    total: report.total,
    ok: report.ok,
    warn: report.warn,
    fail: report.fail,
  })
  setters.setReport(report)
}

function SystemCheckSection() {
  const { t } = useI18n()
  const { formatDateTime } = useFormatDate()
  const [checks, setChecks] = useState<Record<string, SystemCheckItem>>({})
  const [summary, setSummary] = useState<SystemCheckSummary | null>(null)
  const [report, setReport] = useState<SystemCheckReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const streamAbortRef = useRef<AbortController | null>(null)
  const checksRef = useRef<Record<string, SystemCheckItem>>({})

  const runCheck = useCallback(() => {
    streamAbortRef.current?.abort()
    const controller = new AbortController()
    streamAbortRef.current = controller
    checksRef.current = {}

    setLoading(true)
    setError(null)
    setSummary(null)
    setReport(null)
    setChecks({})

    void (async () => {
      try {
        const out: { report: SystemCheckReport | null } = { report: null }
        await consumeSystemCheckStream(
          {
            onRegistry: (descriptors) => {
              const init: Record<string, SystemCheckItem> = {}
              for (const d of descriptors) {
                init[d.id] = { ...d, status: 'pending', message: '' }
              }
              checksRef.current = init
              setChecks(init)
            },
            onCheck: (chk) => {
              checksRef.current = { ...checksRef.current, [chk.id]: chk }
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
            },
            onDone: (s) => {
              out.report = buildSystemCheckReport(s, checksRef.current)
              applySystemCheckReport(out.report, { setChecks, setSummary, setReport, checksRef })
            },
          },
          controller.signal,
        )
        if (out.report) {
          await apiJson<{ saved: boolean; path: string }>('/api/system/check/last', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ report: out.report }),
          })
          toast.success(t('systemCheck.toast.done', { pct: String(out.report.percentage) }))
        }
      } catch (e) {
        if (controller.signal.aborted) return
        const message = e instanceof Error ? e.message : String(e)
        setError(message)
        toast.error(message)
      } finally {
        setLoading(false)
      }
    })()
  }, [t])

  useEffect(() => {
    void (async () => {
      try {
        const payload = await apiJson<{
          present: boolean
          report?: SystemCheckReport
        }>('/api/system/check/last')
        if (payload.present && payload.report) {
          applySystemCheckReport(payload.report, { setChecks, setSummary, setReport, checksRef })
        }
      } catch {
        /* pas de rapport persisté */
      }
    })()
    return () => {
      streamAbortRef.current?.abort()
    }
  }, [])

  const handleDownloadReport = useCallback(() => {
    if (report) {
      downloadSystemCheckReport(report)
      toast.success(t('systemCheck.toast.reportDownloaded'))
      return
    }
    if (summary) {
      const built = buildSystemCheckReport(summary, checks)
      downloadSystemCheckReport(built)
      toast.success(t('systemCheck.toast.reportDownloaded'))
      return
    }
    toast.error(t('systemCheck.runFirst'))
  }, [report, summary, checks, t])

  const checkList = useMemo(() => Object.values(checks), [checks])

  const grouped = useMemo(() => {
    return checkList.reduce<Record<string, SystemCheckItem[]>>((acc, row) => {
      const key = row.category || 'autres'
      acc[key] = [...(acc[key] ?? []), row]
      return acc
    }, {})
  }, [checkList])

  // Live progressive computation from checks state
  const totalChecks = checkList.length
  const doneChecks = checkList.filter((c) => c.status === 'ok' || c.status === 'warn' || c.status === 'fail')
  const okCount = doneChecks.filter((c) => c.status === 'ok').length
  const warnCount = doneChecks.filter((c) => c.status === 'warn').length
  const failCount = doneChecks.filter((c) => c.status === 'fail').length
  const weights: Record<string, number> = { ok: 1, warn: 0.5, fail: 0 }
  const liveScore = doneChecks.reduce((sum, c) => sum + (weights[c.status] ?? 0), 0)
  const percentage = totalChecks > 0 ? Math.round((liveScore / totalChecks) * 100) : 0

  const meterClass = percentage >= 80 ? 'bg-succes/10' : percentage >= 50 ? 'bg-alerte/10' : 'bg-danger/10'

  return (
    <div className="space-y-6">
      <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">{t('systemCheck.dashboard')}</p>
          <h1 className="text-3xl font-semibold tracking-tight">{t('systemCheck.title')}</h1>
          <p className="text-muted-foreground mt-2 max-w-2xl text-sm">{t('systemCheck.subtitleFull')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={runCheck} disabled={loading}>
            {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : <HugeiconsIcon icon={PlayCircleIcon} className="mr-2 size-4" />}
            {t('systemCheck.run')}
          </Button>
          <Button
            variant="outline"
            onClick={handleDownloadReport}
            disabled={loading || (!report && !summary)}
          >
            <Download className="mr-2 size-4" />
            {t('systemCheck.downloadReport')}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-6">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-5xl font-semibold tracking-tight">{totalChecks > 0 ? `${percentage}%` : '—'}</div>
              <p className="text-muted-foreground mt-1 text-sm">
                {totalChecks > 0
                  ? t('systemCheck.summaryCounts', {
                      ok: String(okCount),
                      warn: String(warnCount),
                      fail: String(failCount),
                      total: String(totalChecks),
                    })
                  : t('systemCheck.noChecksYet')}
              </p>
            </div>
            <div className="w-full md:max-w-xl">
              <div className="bg-muted h-4 overflow-hidden rounded-full">
                <div className={cn('h-full rounded-full transition-all duration-500', meterClass)} style={{ width: `${percentage}%` }} />
              </div>
              <p className="text-muted-foreground mt-2 text-xs">
                {t('overview.lastCheck')}{' '}
                {summary?.generated_at_utc ? formatDateTime(summary.generated_at_utc) : t('common.dash')}
              </p>
            </div>
          </div>
          {error ? <p className="mt-4 text-sm text-danger">{error}</p> : null}
        </CardContent>
      </Card>

      {Object.entries(grouped).map(([category, rows]) => (
        <Card key={category}>
          <CardHeader>
            <CardTitle className="capitalize">{category}</CardTitle>
            <CardDescription>{t('systemCheck.checksCount', { count: rows.length })}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">{t('systemCheck.table.status')}</TableHead>
                  <TableHead>{t('systemCheck.table.service')}</TableHead>
                  <TableHead>{t('systemCheck.table.message')}</TableHead>
                  <TableHead className="hidden lg:table-cell">{t('systemCheck.table.details')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => {
                  const isPending = row.status === 'pending'
                  const isRunning = row.status === 'running'
                  return (
                    <TableRow
                      key={row.id}
                      className={cn(
                        'transition-opacity duration-300',
                        isPending && 'opacity-40',
                        isRunning && 'opacity-80',
                      )}
                    >
                      <TableCell><StatusIcon status={row.status} /></TableCell>
                      <TableCell>
                        <div className="font-medium">{row.label}</div>
                        <div className="text-muted-foreground text-xs">{statusLabel(row.status, t)}</div>
                      </TableCell>
                      <TableCell className="text-sm">
                        {isRunning ? t('systemCheck.running') : row.message || t('common.dash')}
                      </TableCell>
                      <TableCell className="text-muted-foreground hidden max-w-md truncate font-mono text-xs lg:table-cell">
                        {row.detail ? JSON.stringify(row.detail).slice(0, 220) : t('common.dash')}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function OverviewSection({
  overview,
  totalSkills,
  totalConnectors,
  enabledConnectors,
  stateSummary,
  onJump,
  refreshScanTools,
  syncState,
}: {
  overview: Overview | null
  totalSkills: number
  totalConnectors: number
  enabledConnectors: number
  stateSummary: StateSummary | null
  onJump: (id: NavId) => void
  refreshScanTools: () => Promise<void>
  syncState: () => Promise<void>
}) {
  const { t } = useI18n()
  const [scanRefreshing, setScanRefreshing] = useState(false)
  const [syncing, setSyncing] = useState(false)
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

  if (!overview) return <LoadingState label={t('common.loading')} />

  const stats = [
    {
      label: t('overview.stats.orgs'),
      value: overview.orgs.length,
      icon: Folder02Icon,
      tone: 'bg-alerte/10 text-alerte',
      target: 'orgs' as NavId,
    },
    {
      label: t('overview.stats.skills'),
      value: totalSkills,
      icon: SparklesIcon,
      tone: 'bg-muted text-foreground',
      target: 'skills' as NavId,
    },
    {
      label: t('overview.stats.connectors'),
      value: `${enabledConnectors}/${totalConnectors}`,
      icon: Plug02Icon,
      tone: 'bg-info/10 text-info',
      target: 'connectors' as NavId,
    },
    {
      label: t('overview.stats.plugins'),
      value: overview.plugin_bundles.length,
      icon: PuzzleIcon,
      tone: 'bg-succes/10 text-succes',
      target: 'plugins' as NavId,
    },
  ]

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('overview.title')}</h2>
        <p className="text-muted-foreground text-sm">{t('overview.subtitle')}</p>
      </header>

      {overview.dashboard_warning ? (
        <div className="rounded-lg border border-alerte/35 bg-alerte/10 p-4 text-sm text-alerte">
          {overview.dashboard_warning}
        </div>
      ) : null}

      <p className="text-muted-foreground text-xs leading-relaxed">
        {t('overview.serverStatus', {
          version: overview.zab_version ?? '—',
          configPath:
            (overview.user_config_path ?? '').replace(/^\/Users\/[^/]+/, '~') || '—',
          skillsPaths:
            overview.skills_roots_yaml && overview.skills_roots_yaml.length > 0
              ? overview.skills_roots_yaml.map((r: string) => r.replace(/^\/Users\/[^/]+/, '~')).join(', ')
              : overview.skills_root_yaml_raw
                ? overview.skills_root_yaml_raw
                : t('overview.skillsNotConfigured'),
        })}
      </p>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {stats.map((s) => (
          <button
            key={s.label}
            onClick={() => onJump(s.target)}
            className="group bg-card hover:border-border hover:shadow-sm flex items-center gap-4 rounded-xl border border-border p-5 text-left transition"
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
            <div className="flex size-10 items-center justify-center rounded-xl bg-muted text-foreground">
              <HugeiconsIcon icon={CodeFolderIcon} size={20} />
            </div>
            <div>
              <CardTitle>{t('overview.skillsRoot.title')}</CardTitle>
              <CardDescription>skills_root · ~/.config/zab/config.yaml</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <code className="bg-muted block rounded-md px-3 py-2 font-mono text-xs break-all">
              {overview.skills_root ?? t('overview.skillsRoot.notConfigured')}
            </code>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl bg-muted text-foreground">
              <HugeiconsIcon icon={Database02Icon} size={20} />
            </div>
            <div>
              <CardTitle>{t('overview.mcpRegistry')}</CardTitle>
              <CardDescription>{t('overview.skillRefSource')}</CardDescription>
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
          <div className="flex size-10 items-center justify-center rounded-xl bg-succes/10 text-succes">
            <HugeiconsIcon icon={Database02Icon} size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <CardTitle>{t('overview.stateIndex.title')}</CardTitle>
            <CardDescription>
              <code className="bg-muted rounded px-1">~/.local/share/zab/state.yaml</code>
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="secondary"
            disabled={syncing}
            onClick={async () => {
              setSyncing(true)
              try {
                await syncState()
              } finally {
                setSyncing(false)
              }
            }}
          >
            {syncing ? `${t('common.refresh')}…` : 'Sync'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            {['skills', 'mcp_servers', 'connectors', 'code_tools', 'tools', 'memory_sources'].map((key) => (
              <div key={key} className="rounded-lg border border-border px-3 py-2">
                <p className="text-lg font-semibold">{stateSummary?.counts?.[key] ?? '—'}</p>
                <p className="text-muted-foreground text-[11px]">{key}</p>
              </div>
            ))}
          </div>
          <p className="text-muted-foreground font-mono text-[11px] break-all">
            {stateSummary?.path ?? t('overview.stateIndex.notLoaded')} ·{' '}
            {stateSummary?.last_sync_at ?? t('overview.stateIndex.neverSynced')}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-muted text-foreground">
            <HugeiconsIcon icon={CompassIcon} size={20} />
          </div>
          <div>
            <CardTitle>{t('overview.quickStart.title')}</CardTitle>
            <CardDescription>{t('overview.quickStart.subtitle')}</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <QuickJump
            label={t('overview.quickStart.conversations')}
            icon={MessageMultiple02Icon}
            onClick={() => onJump('conversations')}
          />
          <QuickJump label={t('overview.quickStart.projects')} icon={Folder02Icon} onClick={() => onJump('projects')} />
          <QuickJump label={t('overview.quickStart.connectors')} icon={Plug02Icon} onClick={() => onJump('connectors')} />
          <QuickJump label={t('overview.quickStart.skills')} icon={SparklesIcon} onClick={() => onJump('skills')} />
          <QuickJump label={t('overview.quickStart.tests')} icon={TestTube02Icon} onClick={() => onJump('tests')} />
          <QuickJump label={t('overview.quickStart.security')} icon={LockKeyIcon} onClick={() => onJump('security')} />
          <QuickJump
            label={t('overview.quickStart.rescanTools')}
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
          <QuickJump label={t('overview.quickStart.cliHelp')} icon={HelpSquareIcon} onClick={openCliHelp} />
        </CardContent>
      </Card>

      <Dialog open={cliOpen} onOpenChange={setCliOpen}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-hidden sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{t('overview.cliHelp.title')}</DialogTitle>
            <DialogDescription>`zab --help`</DialogDescription>
          </DialogHeader>
          <pre className="bg-muted max-h-[min(60vh,520px)] overflow-auto rounded-lg p-3 font-mono text-xs whitespace-pre-wrap">
            {cliLoading ? t('common.loading') : cliText}
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
      className="hover:bg-muted/60 flex items-center justify-between rounded-lg border border-border px-3 py-3 text-sm transition disabled:cursor-not-allowed disabled:opacity-50"
    >
      <span className="flex items-center gap-2.5 font-medium">
        <HugeiconsIcon icon={icon} size={18} className="text-muted-foreground" />
        {label}
      </span>
      <span className="text-muted-foreground text-xs">→</span>
    </button>
  )
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

function OrgSkillsCard({
  org,
  skills,
  projects,
  active,
  skillsRepoRoot,
  skillsRoot,
  onOpenSkill,
  onOpenProject,
}: {
  org: string
  skills: Overview['orgs'][number]['skills']
  projects?: NonNullable<Overview['orgs'][number]['projects']>
  active?: boolean
  skillsRepoRoot?: string
  skillsRoot: string | null
  onOpenSkill: (path: string) => void
  onOpenProject: (id: string) => void
}) {
  const { t } = useI18n()
  const projectRows = [...(projects ?? [])].sort((a, b) => {
    const bt = b.last_activity_at_utc ? Date.parse(b.last_activity_at_utc) : 0
    const at = a.last_activity_at_utc ? Date.parse(a.last_activity_at_utc) : 0
    if (bt !== at) return bt - at
    return String(a.name || '').localeCompare(String(b.name || ''), undefined, { sensitivity: 'base' })
  })
  const [expanded, setExpanded] = useState(() => projectRows.length <= 6 && skills.length <= 5)
  useEffect(() => {
    if (active) setExpanded(true)
  }, [active])
  const toggle = useCallback(() => setExpanded((e) => !e), [])
  return (
    <Card className={active ? 'border-border ring-1 ring-ring/40' : undefined}>
      <CardHeader className="flex flex-row items-center gap-3 pb-2">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground">
          <HugeiconsIcon icon={Folder02Icon} size={22} />
        </div>
        <div className="min-w-0 flex-1">
          <CardTitle className="text-lg">{org}</CardTitle>
          <CardDescription>
            {projectRows.length} projet{projectRows.length > 1 ? 's' : ''} · {skills.length} skills
          </CardDescription>
        </div>
        <button
          type="button"
          onClick={toggle}
          className="text-muted-foreground hover:bg-muted/80 flex shrink-0 items-center gap-1 rounded-lg border border-border/80 px-2 py-1.5 text-xs font-medium transition outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
          aria-expanded={expanded}
          aria-label={expanded ? t('orgs.collapseAria') : t('orgs.expandAria')}
        >
          {expanded ? (
            <>
              <span className="hidden sm:inline">{t('orgs.collapse')}</span>
              <ChevronDown className="size-4" aria-hidden />
            </>
          ) : (
            <>
              <span className="hidden sm:inline">{t('orgs.expand')}</span>
              <ChevronRight className="size-4" aria-hidden />
            </>
          )}
        </button>
      </CardHeader>
      {expanded ? (
        <CardContent className="space-y-3 pt-0">
          <div>
            <p className="text-muted-foreground mb-1.5 text-[10px] font-semibold uppercase">Projets</p>
            {projectRows.length > 0 ? (
              <ul className="list-none space-y-1 pl-0 text-xs">
                {projectRows.slice(0, 12).map((p) => (
                  <li key={p.path || p.name} className="min-w-0 rounded-md border border-border/70">
                    <button
                      type="button"
                      className="block w-full px-2 py-1.5 text-left transition hover:bg-muted/60"
                      onClick={() => {
                        const projectId = p.id || p.name || p.path
                        if (projectId) onOpenProject(projectId)
                      }}
                    >
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-xs font-medium">{p.name || 'Projet'}</p>
                        <p className="text-muted-foreground truncate font-mono text-[10px]">
                          {p.path ? shortenHomeInPath(p.path) : p.workspace_parent || ''}
                        </p>
                      </div>
                      <span className="text-muted-foreground shrink-0 text-[10px]" title={p.last_activity_at_utc || undefined}>
                        {formatActivityDate(p.last_activity_at_utc)}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                      {p.org && p.org !== org ? <span className="rounded bg-muted px-1 py-0.5">{p.org}</span> : null}
                      {p.git_repo ? (
                        <span className="rounded bg-succes/10 px-1 py-0.5 text-succes">
                          git{p.git_branch ? ` · ${p.git_branch}` : ''}
                        </span>
                      ) : (
                        <span>{t('projects.card.noGit')}</span>
                      )}
                      <span>{p.skills_count ?? 0} skill{(p.skills_count ?? 0) !== 1 ? 's' : ''}</span>
                      {p.last_activity_source ? <span>{activitySourceLabel(p.last_activity_source)}</span> : null}
                    </div>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground text-xs">Aucun projet rattaché.</p>
            )}
            {projectRows.length > 12 ? (
              <p className="text-muted-foreground mt-1 text-[10px]">+{projectRows.length - 12} autres projets</p>
            ) : null}
          </div>
          <div>
            <p className="text-muted-foreground mb-1.5 text-[10px] font-semibold uppercase">Skills</p>
          <ul className="list-none space-y-0.5 pl-0 text-xs">
            {skills.map((s) => {
              const vsc = vscodeFileHrefForSkill(s.path, skillsRepoRoot, skillsRoot)
              return (
                <li key={s.path} className="min-w-0 list-none">
                  <div className="flex min-w-0 items-stretch gap-0 rounded-md border border-transparent transition hover:border-border/80 hover:bg-muted/50">
                    <button
                      type="button"
                      className="min-w-0 flex-1 px-2 py-1.5 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
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
                          {s.project ? s.project : t('orgs.projectTag')}
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
          </div>
        </CardContent>
      ) : null}
    </Card>
  )
}

function OrgsSection({
  overview,
  onOpenSkill,
  activeOrgId,
  onOpenProject,
  onJump,
}: {
  overview: Overview | null
  onOpenSkill: (path: string) => void
  activeOrgId?: string | null
  onOpenProject: (id: string) => void
  onJump: (id: NavId) => void
}) {
  const { t } = useI18n()
  if (!overview) return <LoadingState label={t('common.loading')} />
  const selectedOrg = activeOrgId ? overview.orgs.find((o) => o.org === activeOrgId) : undefined
  const visibleOrgs = selectedOrg ? [selectedOrg] : overview.orgs
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('orgs.title')}</h2>
        <p className="text-muted-foreground text-sm">
          {t('orgs.subtitleCount', { count: String(visibleOrgs.length) })}
        </p>
      </header>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {visibleOrgs.map((o) => (
          <OrgSkillsCard
            key={o.org}
            org={o.org}
            skills={o.skills}
            projects={o.projects}
            active={activeOrgId === o.org}
            skillsRepoRoot={o.skills_repo_root}
            skillsRoot={overview.skills_root}
            onOpenSkill={onOpenSkill}
            onOpenProject={onOpenProject}
          />
        ))}
      </div>

      <p className="text-muted-foreground text-sm">
        {t('orgs.footer')}{' '}
        <button type="button" className="text-primary font-medium underline" onClick={() => onJump('projects')}>
          {t('nav.projects')}
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
  const { t } = useI18n()
  if (!overview) return <LoadingState label={t('common.loading')} />
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('plugins.title')}</h2>
        <p className="text-muted-foreground text-sm">{overview.plugin_bundles.length} bundles</p>
      </header>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {overview.plugin_bundles.map((b) => (
          <div
            key={b.id}
            className="bg-card flex flex-col gap-2 rounded-xl border border-border p-4 transition hover:border-border hover:shadow-sm"
          >
            <div className="flex items-center gap-3">
              <div className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-succes/10 text-succes">
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
  const { t } = useI18n()
  const presets = [
    { id: 'smoke_mcps', label: 'Smoke MCP', icon: TestTube02Icon, tone: 'bg-succes/10 text-succes' },
    { id: 'gateway_pytest', label: 'Pytest gateway', icon: TestTube01Icon, tone: 'bg-info/10 text-info' },
    { id: 'sync_mcps_litellm', label: 'Sync → Litellm', icon: CloudUploadIcon, tone: 'bg-muted text-foreground' },
    { id: 'build_plugins', label: 'build-plugins.sh', icon: Hammer, tone: 'bg-alerte/10 text-alerte' },
    { id: 'google_oauth_mehdi_context', label: 'OAuth Google', icon: GoogleIcon, tone: 'bg-danger/10 text-danger' },
  ]
  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('tests.title')}</h2>
        <p className="text-muted-foreground text-sm">{t('tests.subtitle')}</p>
      </header>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
        {presets.map((p) => (
          <button
            key={p.id}
            type="button"
            disabled={running}
            onClick={() => runPreset(p.id)}
            className="group bg-card hover:border-border hover:shadow-sm flex flex-col items-start gap-3 rounded-xl border border-border p-4 text-left transition disabled:opacity-50"
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
          <pre className="max-h-[420px] overflow-auto rounded-lg bg-primary p-4 text-[11px] leading-5 whitespace-pre-wrap text-succes">
            {lines.join('\n') || (running ? 'En attente de sortie…' : '— aucun log —')}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}

type SecurityEnvFileRow = {
  path: string
  path_display: string
  exists: boolean
  configured: boolean
  keys: string[]
}

type SecurityEnvFileSource = {
  kind: 'file'
  path: string
  path_display: string
  key: string
  line: number | null
}

type SecurityEnvProcessSource = {
  kind: 'process'
  keys: string[]
}

type SecurityDashlaneMatch = {
  id: string
  title: string
  reference: string
  web_url?: string
  match: 'exact' | 'fuzzy' | string
  score: number
}

type SecurityEnvSyncRow = {
  name: string
  status: 'synced' | 'pending' | 'missing' | string
  provider: string | null
  recommended_provider: string | null
  dashlane_title: string
  dashlane_reference_value: string
  dashlane_reference_template: string
  dashlane_web_url?: string
  dashlane_match_status: 'matched' | 'not_found' | string
  dashlane_matches: SecurityDashlaneMatch[]
  reference_hint: string
  note_template: string
  source_count: number
}

type SecurityEnvVarRow = {
  name: string
  present: boolean
  in_process: boolean
  in_file: boolean
  masked: string
  sources: (SecurityEnvFileSource | SecurityEnvProcessSource)[]
  sync?: SecurityEnvSyncRow | null
}

type SecuritySecretSyncPayload = {
  provider: string
  status: string
  generated_at_utc: string
  write_supported: boolean
  counts: {
    synced: number
    pending: number
    missing: number
    total: number
  }
  dashlane_inventory?: {
    available: boolean
    status: string
    count: number
    status_detail?: string | null
    items?: {
      id: string
      title: string
      reference: string
      web_url?: string
    }[]
  }
  variables: SecurityEnvSyncRow[]
  manual_steps?: string[]
  message?: string
}

type SecuritySecretProvider = {
  id: string
  label: string
  available: boolean
  implemented: boolean
  enabled: boolean
  cli?: string
  cli_path?: string | null
  status: string
  status_label: string
  status_detail?: string | null
  login_command?: string
  check_command?: string
  capabilities?: string[]
  limitations?: string[]
  write_supported?: boolean
  local_reference_write_supported?: boolean
}

type SecurityDashlaneApplyResult = {
  name: string
  status: 'synced' | 'skipped' | 'error' | 'create_required' | string
  provider?: string
  reason?: string
  reference_hint?: string
  dashlane_title?: string
  dashlane_reference_value?: string
  dashlane_web_url?: string
  dashlane_secret_status?: string
  hint?: string
  changed_files?: {
    path: string
    path_display: string
    keys: string[]
    storage?: string
  }[]
}

type SecurityDashlaneApplyResponse = {
  provider: 'dashlane'
  result: SecurityDashlaneApplyResult
  secret_sync?: SecuritySecretSyncPayload
}

type SecurityDashlaneCopyValueResponse = {
  copied: boolean
  name: string
  dashlane_title: string
}

type SecurityEnvOverviewPayload = {
  files: SecurityEnvFileRow[]
  variables: SecurityEnvVarRow[]
  secret_sync?: SecuritySecretSyncPayload
}

type SecuritySubmenuId = 'env_files' | 'local_scans' | 'sync_secrets'

function DashlaneLogo({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'relative inline-flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-sm bg-[#0b6670] text-[9px] font-bold text-foreground',
        className,
      )}
    >
      D
      <img
        src="https://play-lh.googleusercontent.com/82k9b2kIf3AGhg7Owb4JwM07V4dxazgqubplyo2vDuLJOOBtzjD4XQ5rGLMUye93kw"
        alt=""
        className="absolute inset-0 size-full rounded-sm object-cover"
      />
    </span>
  )
}

function SecuritySyncPill({ sync }: { sync?: SecurityEnvSyncRow | null }) {
  if (!sync || sync.status === 'missing') {
    return <span className="text-muted-foreground text-xs">—</span>
  }
  if (sync.status === 'synced') {
    return (
      <span className="inline-flex max-w-[180px] items-center gap-1.5 rounded-full bg-succes/10 px-2 py-1 text-[11px] font-medium text-succes ring-1 ring-succes/35">
        <DashlaneLogo />
        <span>Dashlane</span>
        {sync.reference_hint ? <span className="truncate font-mono opacity-70">{sync.reference_hint}</span> : null}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-alerte/10 px-2 py-1 text-[11px] font-medium text-alerte ring-1 ring-alerte/35">
      <DashlaneLogo />
      <span>À créer</span>
    </span>
  )
}

function SecuritySection({
  running,
  runPreset,
  jobId,
  jobLines,
}: {
  running: boolean
  runPreset: (p: string, a?: Record<string, unknown>) => void
  jobId: string | null
  jobLines: string[]
}) {
  const { t } = useI18n()
  const [overviewLoading, setOverviewLoading] = useState(true)
  const [envFiles, setEnvFiles] = useState<SecurityEnvFileRow[]>([])
  const [envVars, setEnvVars] = useState<SecurityEnvVarRow[]>([])
  const [secretProviders, setSecretProviders] = useState<SecuritySecretProvider[]>([])
  const [secretSync, setSecretSync] = useState<SecuritySecretSyncPayload | null>(null)
  const [providersLoading, setProvidersLoading] = useState(true)
  const [syncChecking, setSyncChecking] = useState(false)
  const [securitySubmenu, setSecuritySubmenu] = useState<SecuritySubmenuId>('env_files')
  const [openingKey, setOpeningKey] = useState<string | null>(null)
  const [reports, setReports] = useState<SecurityReportRow[]>([])
  const [dashlaneModalOpen, setDashlaneModalOpen] = useState(false)
  const [dashlaneSelectedNames, setDashlaneSelectedNames] = useState<Set<string>>(() => new Set())
  const [dashlaneConfirmAll, setDashlaneConfirmAll] = useState(false)
  const [dashlaneSyncRunning, setDashlaneSyncRunning] = useState(false)
  const [dashlaneActiveName, setDashlaneActiveName] = useState<string | null>(null)
  const [dashlaneCopyingName, setDashlaneCopyingName] = useState<string | null>(null)
  const [dashlaneReferenceByName, setDashlaneReferenceByName] = useState<Record<string, string>>({})
  const [dashlaneResults, setDashlaneResults] = useState<Record<string, SecurityDashlaneApplyResult>>({})

  const loadReports = useCallback(async () => {
    try {
      const data = await apiJson<{ reports: SecurityReportRow[] }>('/api/security/reports')
      setReports(data.reports)
    } catch {
      setReports([])
    }
  }, [])

  const loadOverview = useCallback(async () => {
    setOverviewLoading(true)
    try {
      const data = await apiJson<SecurityEnvOverviewPayload>('/api/security/env-overview')
      setEnvFiles(data.files ?? [])
      setEnvVars(data.variables ?? [])
      setSecretSync(data.secret_sync ?? null)
    } catch (e) {
      setEnvFiles([])
      setEnvVars([])
      setSecretSync(null)
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setOverviewLoading(false)
    }
  }, [])

  const loadProviders = useCallback(async () => {
    setProvidersLoading(true)
    try {
      const data = await apiJson<{ providers: SecuritySecretProvider[] }>('/api/security/secret-providers')
      setSecretProviders(data.providers ?? [])
    } catch {
      setSecretProviders([])
    } finally {
      setProvidersLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadOverview()
    void loadProviders()
    void loadReports()
  }, [loadOverview, loadProviders, loadReports])

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(label)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const applySecretSyncPayload = (data: SecuritySecretSyncPayload & { providers?: SecuritySecretProvider[] }) => {
    setSecretSync(data)
    if (data.providers) setSecretProviders(data.providers)
    const syncByName = new Map((data.variables ?? []).map((row) => [row.name, row]))
    setEnvVars((current) =>
      current.map((row) => ({
        ...row,
        sync: syncByName.get(row.name) ?? row.sync,
      })),
    )
  }

  const runDashlaneCheck = async () => {
    setSyncChecking(true)
    try {
      const data = await apiJson<SecuritySecretSyncPayload & { providers?: SecuritySecretProvider[] }>(
        '/api/security/secret-sync/check',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: 'dashlane', apply: false }),
        },
      )
      applySecretSyncPayload(data)
      toast.success(data.message ?? 'Check Dashlane terminé')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSyncChecking(false)
    }
  }

  const openEnvInEditor = async (path: string, opts?: { line?: number | null; key?: string }) => {
    const token = `${path}:${opts?.key ?? ''}:${opts?.line ?? ''}`
    setOpeningKey(token)
    try {
      const res = await apiJson<{ opened_with: string; line?: number | null }>('/api/system/open-editor-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path,
          line: opts?.line ?? undefined,
          key: opts?.key ?? undefined,
        }),
      })
      const where = res.line ? `ligne ${res.line}` : 'fichier'
      toast.success(`Ouvert (${res.opened_with}) — ${where}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setOpeningKey(null)
    }
  }

  const configuredFiles = envFiles.filter((f) => f.configured)
  const providersForDisplay =
    secretProviders.length > 0
      ? secretProviders
      : [
          {
            id: 'dashlane',
            label: 'Dashlane',
            available: false,
            implemented: true,
            enabled: true,
            status: providersLoading ? 'loading' : 'missing_cli',
            status_label: providersLoading ? 'Chargement' : 'dcli absent',
            login_command: 'dcli sync',
            check_command: 'dcli status',
            write_supported: false,
          },
          {
            id: 'dotenvx',
            label: 'dotenvx',
            available: false,
            implemented: false,
            enabled: false,
            status: 'planned',
            status_label: 'Prévu',
            write_supported: false,
          },
          {
            id: 'op',
            label: '1Password',
            available: false,
            implemented: false,
            enabled: false,
            status: 'planned',
            status_label: 'Prévu',
            write_supported: false,
          },
          {
            id: 'sops',
            label: 'SOPS',
            available: false,
            implemented: false,
            enabled: false,
            status: 'planned',
            status_label: 'Prévu',
            write_supported: false,
          },
        ]
  const dashlaneProvider = providersForDisplay.find((p) => p.id === 'dashlane') ?? null
  const pendingDashlaneRows = (secretSync?.variables ?? []).filter((row) => row.status === 'pending')
  const fileBackedNames = new Set(envVars.filter((row) => row.sources.some((source) => source.kind === 'file')).map((row) => row.name))
  const selectableDashlaneRows = pendingDashlaneRows.filter((row) => fileBackedNames.has(row.name))
  const selectedDashlaneRows = selectableDashlaneRows.filter((row) => dashlaneSelectedNames.has(row.name))
  const dashlaneAllSelected =
    selectableDashlaneRows.length > 0 && selectedDashlaneRows.length === selectableDashlaneRows.length

  const defaultDashlaneReferenceForRow = (row: SecurityEnvSyncRow) =>
    row.dashlane_match_status === 'matched' ? row.dashlane_reference_value : ''

  const openDashlaneModal = (mode: 'first' | 'all' = 'first') => {
    const next = new Set<string>()
    const nextRefs: Record<string, string> = {}
    if (mode === 'all') {
      selectableDashlaneRows.forEach((row) => {
        next.add(row.name)
        nextRefs[row.name] = defaultDashlaneReferenceForRow(row)
      })
    } else if (selectableDashlaneRows[0]) {
      next.add(selectableDashlaneRows[0].name)
      nextRefs[selectableDashlaneRows[0].name] = defaultDashlaneReferenceForRow(selectableDashlaneRows[0])
    }
    setDashlaneSelectedNames(next)
    setDashlaneReferenceByName(nextRefs)
    setDashlaneConfirmAll(false)
    setDashlaneResults({})
    setDashlaneActiveName(null)
    setDashlaneModalOpen(true)
  }

  const toggleDashlaneSelection = (name: string, checked: boolean) => {
    const row = selectableDashlaneRows.find((item) => item.name === name)
    setDashlaneSelectedNames((current) => {
      const next = new Set(current)
      if (checked) next.add(name)
      else next.delete(name)
      return next
    })
    if (checked && row) {
      setDashlaneReferenceByName((current) => ({
        ...current,
        [name]: current[name] || defaultDashlaneReferenceForRow(row),
      }))
    }
    setDashlaneConfirmAll(false)
  }

  const setDashlaneSelectionAll = (checked: boolean) => {
    setDashlaneSelectedNames(checked ? new Set(selectableDashlaneRows.map((row) => row.name)) : new Set())
    setDashlaneReferenceByName(
      checked
        ? Object.fromEntries(selectableDashlaneRows.map((row) => [row.name, dashlaneReferenceByName[row.name] || defaultDashlaneReferenceForRow(row)]))
        : {},
    )
    setDashlaneConfirmAll(false)
  }

  const runDashlaneModalSync = async () => {
    if (selectedDashlaneRows.length === 0) {
      toast.warning('Sélection vide')
      return
    }
    if (dashlaneAllSelected && !dashlaneConfirmAll) {
      toast.warning('Confirme la sélection totale avant de lancer la sync.')
      return
    }
    setDashlaneSyncRunning(true)
    setDashlaneResults({})
    try {
      for (const row of selectedDashlaneRows) {
        setDashlaneActiveName(row.name)
        const data = await apiJson<SecurityDashlaneApplyResponse>('/api/security/secret-sync/dashlane/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider: 'dashlane',
            name: row.name,
            reference: dashlaneReferenceByName[row.name],
            selected_count: selectedDashlaneRows.length,
            total_selectable: selectableDashlaneRows.length,
            confirm_all: dashlaneConfirmAll,
          }),
        })
        setDashlaneResults((current) => ({ ...current, [row.name]: data.result }))
        if (data.secret_sync) applySecretSyncPayload(data.secret_sync)
        if (data.result.status === 'error') break
      }
      await loadOverview()
      await loadProviders()
      toast.success('Sync Dashlane terminée')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setDashlaneActiveName(null)
      setDashlaneSyncRunning(false)
    }
  }

  const copyDashlaneValue = async (row: SecurityEnvSyncRow) => {
    setDashlaneCopyingName(row.name)
    try {
      const data = await apiJson<SecurityDashlaneCopyValueResponse>('/api/security/secret-sync/dashlane/copy-value', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: row.name, confirm_clipboard: true }),
      })
      toast.success(`Valeur copiée pour ${data.dashlane_title}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setDashlaneCopyingName(null)
    }
  }

  const securityScanPresets = [
    {
      id: 'security_osv_zab',
      label: t('security.osvZab'),
      hint: t('security.osvZabHint'),
      icon: Search01Icon,
      tone: 'bg-info/10 text-info',
    },
    {
      id: 'security_npm_audit_zab_ui',
      label: t('security.npmAudit'),
      hint: t('security.npmAuditHint'),
      icon: CodeFolderIcon,
      tone: 'bg-succes/10 text-succes',
    },
    {
      id: 'security_gitleaks_zab',
      label: 'Gitleaks — zab',
      hint: 'Secrets dans l’historique Git du clone zab (binaire gitleaks sur le PATH)',
      icon: LockKeyIcon,
      tone: 'bg-danger/10 text-danger',
    },
    {
      id: 'security_osv_skills',
      label: t('security.osvSkills'),
      hint: t('security.osvSkillsHint'),
      icon: Search01Icon,
      tone: 'bg-muted text-foreground',
    },
    {
      id: 'security_pip_audit_zab',
      label: 'pip-audit — zab',
      hint: 'Audit PyPI de l’environnement projet via uv run --with pip-audit pip-audit',
      icon: CpuIcon,
      tone: 'bg-alerte/10 text-alerte',
    },
  ] as const

  const securitySubmenus: { id: SecuritySubmenuId; label: string; hint: string }[] = [
    {
      id: 'env_files',
      label: 'Fichiers .env',
      hint: overviewLoading ? 'Chargement' : `${configuredFiles.length} chemin(s)`,
    },
    {
      id: 'local_scans',
      label: 'Scans locaux',
      hint: `${securityScanPresets.length} job(s) CLI`,
    },
    {
      id: 'sync_secrets',
      label: 'Sync & secrets',
      hint: secretSync
        ? `${secretSync.counts.pending} à créer · ${secretSync.counts.synced} sync`
        : `${envVars.length} variable(s)`,
    },
  ]

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('security.title')}</h2>
        <p className="text-muted-foreground text-sm">{t('security.subtitle')}</p>
      </header>

      <div className="grid gap-2 sm:grid-cols-3" role="tablist" aria-label="Sous-menus sécurité">
        {securitySubmenus.map((item) => {
          const selected = securitySubmenu === item.id
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => setSecuritySubmenu(item.id)}
              className={cn(
                'rounded-lg border px-3 py-2 text-left transition',
                selected
                  ? 'border-border bg-primary text-primary-foreground shadow-sm'
                  : 'border-border bg-card text-foreground hover:border-border hover:bg-muted',
              )}
            >
              <span className="block text-sm font-semibold">{item.label}</span>
              <span className={cn('mt-0.5 block text-[11px]', selected ? 'text-muted-foreground' : 'text-muted-foreground')}>
                {item.hint}
              </span>
            </button>
          )
        })}
      </div>

      {securitySubmenu === 'env_files' ? (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle>Fichiers .env</CardTitle>
            <CardDescription>
              Chemins déclarés dans <code className="bg-muted rounded px-1">security_env_paths</code> (
              <code className="bg-muted rounded px-1">~/.config/zab/config.yaml</code>).
            </CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" disabled={overviewLoading} onClick={() => void loadOverview()}>
            Rafraîchir
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {overviewLoading ? (
            <LoadingState compact label="Chargement…" />
          ) : configuredFiles.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Aucun fichier — ajoutez{' '}
              <code className="bg-muted rounded px-1">security_env_paths</code> (ex.{' '}
              <code className="bg-muted rounded px-1">~/projects/skills/.env</code>,{' '}
              <code className="bg-muted rounded px-1">~/.hermes/.env</code>).
            </p>
          ) : (
            <ul className="space-y-3">
              {configuredFiles.map((f) => (
                <li
                  key={f.path}
                  className="rounded-lg border border-border p-3"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="font-mono text-xs font-medium">{f.path_display}</p>
                      <p className="text-muted-foreground mt-0.5 flex flex-wrap gap-2 text-[11px]">
                        <span
                          className={cn(
                            'inline-flex rounded-full px-2 py-0.5 ring-1',
                            f.exists
                              ? 'bg-succes/10 text-succes ring-succes/35'
                              : 'bg-muted text-muted-foreground ring-ring/40',
                          )}
                        >
                          {f.exists ? 'présent' : 'absent'}
                        </span>
                        {f.configured ? (
                          <span className="inline-flex rounded-full bg-info/10 px-2 py-0.5 text-info ring-1 ring-info/35">
                            configuré
                          </span>
                        ) : null}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={!f.exists || openingKey === f.path}
                        onClick={() => void openEnvInEditor(f.path)}
                      >
                        Ouvrir le fichier
                      </Button>
                      <a
                        href={vscodeFileHref(f.path)}
                        className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), !f.exists && 'pointer-events-none opacity-50')}
                        onClick={(e) => !f.exists && e.preventDefault()}
                      >
                        VS Code / Cursor
                      </a>
                    </div>
                  </div>
                  {f.keys.length > 0 ? (
                    <p className="text-muted-foreground mt-2 text-[11px]">
                      Clés suivies :{' '}
                      <span className="font-mono text-foreground">{f.keys.slice(0, 12).join(', ')}</span>
                      {f.keys.length > 12 ? ` (+${f.keys.length - 12})` : ''}
                    </p>
                  ) : (
                    <p className="text-muted-foreground mt-2 text-[11px]">Aucune clé suivie dans ce fichier.</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      ) : null}

      {securitySubmenu === 'local_scans' ? (
      <Card>
        <CardHeader className="flex flex-row items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-muted text-foreground">
            <HugeiconsIcon icon={TestTube02Icon} size={20} />
          </div>
          <div className="min-w-0 flex-1">
            <CardTitle>Scans locaux (CLI)</CardTitle>
            <CardDescription>
              Les commandes s’exécutent sur votre machine avec le même PATH que le processus{' '}
              <code className="bg-muted rounded px-1 text-xs">zab dashboard</code>. Installez les outils manquants
              (brew, etc.). Les logs de cet onglet utilisent un runner dédié.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {securityScanPresets.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={running}
                onClick={() => runPreset(p.id)}
                className="group bg-card hover:border-border hover:shadow-sm flex flex-col items-start gap-2 rounded-xl border border-border p-4 text-left transition disabled:opacity-50"
              >
                <div className={cn('flex size-10 items-center justify-center rounded-xl', p.tone)}>
                  <HugeiconsIcon icon={p.icon} size={20} strokeWidth={1.7} />
                </div>
                <div>
                  <p className="text-sm font-semibold tracking-tight">{p.label}</p>
                  <p className="text-muted-foreground mt-0.5 text-[11px] leading-snug">{p.hint}</p>
                </div>
                <p className="text-muted-foreground inline-flex items-center gap-1 text-[11px]">
                  <HugeiconsIcon icon={PlayCircleIcon} size={12} />
                  Lancer le job
                </p>
              </button>
            ))}
          </div>
          {jobId ? (
            <p className="text-muted-foreground text-xs">
              Job : <code className="bg-muted rounded px-1 font-mono">{jobId}</code>
            </p>
          ) : null}
          <div>
            <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Sortie</p>
            <pre className="max-h-[min(420px,50vh)] overflow-auto rounded-lg bg-primary p-4 text-[11px] leading-5 whitespace-pre-wrap text-succes">
              {jobLines.join('\n') || (running ? 'En attente de sortie…' : '— lancez un scan ci-dessus —')}
            </pre>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-muted-foreground text-[11px] font-medium uppercase">Derniers rapports persistés</p>
              <Button type="button" variant="outline" size="sm" onClick={() => void loadReports()}>
                Rafraîchir
              </Button>
            </div>
            {reports.length === 0 ? (
              <p className="text-muted-foreground text-xs">Aucun rapport sécurité persisté.</p>
            ) : (
              <ul className="grid gap-2 sm:grid-cols-2">
                {reports.slice(0, 6).map((r) => (
                  <li key={r.key} className="rounded-md border border-border p-2 text-xs">
                    <p className="font-mono">{r.key}</p>
                    <p className="text-muted-foreground">{new Date(r.updated_at_utc).toLocaleString()}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </CardContent>
      </Card>
      ) : null}

      {securitySubmenu === 'sync_secrets' ? (
      <>
      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>Synchronisation secrets</CardTitle>
            <CardDescription>
              Providers de coffre local pour remplacer progressivement les valeurs .env par des références de secrets.
            </CardDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={overviewLoading || providersLoading}
            onClick={() => {
              void loadOverview()
              void loadProviders()
            }}
          >
            <RefreshCw className="mr-1.5 size-3.5" />
            Rafraîchir
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {providersForDisplay.map((provider) => {
              const isDashlane = provider.id === 'dashlane'
              const active = provider.enabled && provider.implemented
              const providerTone =
                !active
                  ? 'border-border bg-muted opacity-60'
                  : provider.status === 'ready'
                    ? 'border-succes/35 bg-succes/10'
                    : provider.status === 'login_required'
                      ? 'border-alerte/35 bg-alerte/10'
                      : 'border-border bg-card'
              return (
                <div
                  key={provider.id}
                  className={cn('rounded-lg border p-3', providerTone)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      {isDashlane ? (
                        <DashlaneLogo className="size-6 rounded-md" />
                      ) : (
                        <span className="flex size-6 items-center justify-center rounded-md bg-muted text-[10px] font-semibold text-muted-foreground">
                          {provider.label.slice(0, 2).toUpperCase()}
                        </span>
                      )}
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{provider.label}</p>
                        <p className="text-muted-foreground truncate text-[11px]">{provider.cli ?? provider.id}</p>
                      </div>
                    </div>
                    <span
                      className={cn(
                        'shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                        provider.status === 'ready'
                          ? 'bg-succes/10 text-succes ring-succes/35'
                          : provider.status === 'login_required'
                            ? 'bg-alerte/10 text-alerte ring-alerte/35'
                            : 'bg-muted text-muted-foreground ring-ring/40',
                      )}
                    >
                      {provider.status_label}
                    </span>
                  </div>
                  {provider.status_detail ? (
                    <p className="text-muted-foreground mt-2 text-[11px]">{provider.status_detail}</p>
                  ) : null}
                  {!provider.implemented ? (
                    <p className="text-muted-foreground mt-2 text-[11px]">Provider grisé pour une intégration future.</p>
                  ) : null}
                </div>
              )
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={!dashlaneProvider?.login_command}
              onClick={() => void copyText(dashlaneProvider?.login_command ?? 'dcli sync', 'Commande Dashlane copiée')}
            >
              <LogIn className="mr-1.5 size-3.5" />
              Login Dashlane
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={syncChecking}
              onClick={() => void runDashlaneCheck()}
            >
              {syncChecking ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : <ShieldCheck className="mr-1.5 size-3.5" />}
              Check sync Dashlane
            </Button>
            <Button
              type="button"
              variant="default"
              size="sm"
              disabled={dashlaneSyncRunning || selectableDashlaneRows.length === 0}
              onClick={() => openDashlaneModal('first')}
            >
              <DashlaneLogo className="mr-1.5 size-3.5" />
              Sync sélection
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={dashlaneSyncRunning || selectableDashlaneRows.length === 0}
              title={
                selectableDashlaneRows.length === 0
                  ? 'Aucun secret fichier à synchroniser.'
                  : 'Ouvre la modale avec tous les secrets éligibles sélectionnés.'
              }
              onClick={() => openDashlaneModal('all')}
            >
              {dashlaneSyncRunning ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 size-3.5" />}
              Sync all
            </Button>
            {secretSync ? (
              <p className="text-muted-foreground text-xs">
                {secretSync.counts.synced} sync · {secretSync.counts.pending} à créer · {secretSync.counts.missing} absents
                {secretSync.dashlane_inventory ? ` · ${secretSync.dashlane_inventory.count} secret(s) Dashlane lus` : ''}
              </p>
            ) : null}
          </div>

          {pendingDashlaneRows.length > 0 ? (
            <div className="rounded-lg border border-alerte/35 bg-alerte/10 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-alerte">Références Dashlane à poser</p>
                <span className="text-[11px] text-alerte/80">
                  {pendingDashlaneRows.length} variable(s)
                </span>
              </div>
              <ul className="space-y-2">
                {pendingDashlaneRows.slice(0, 6).map((row) => (
                  <li key={row.name} className="rounded-md border border-alerte/35 bg-white/70 p-2">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="font-mono text-xs font-semibold">{row.name}</p>
                        <p className="text-muted-foreground mt-0.5 font-mono text-[11px]">{row.dashlane_title}</p>
                        <p className="text-muted-foreground mt-0.5 font-mono text-[11px]">{row.dashlane_reference_template}</p>
                        <p
                          className={cn(
                            'mt-1 inline-flex rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                            row.dashlane_match_status === 'matched'
                              ? 'bg-succes/10 text-succes ring-succes/35'
                              : 'bg-alerte/10 text-alerte ring-alerte/35',
                          )}
                        >
                          {row.dashlane_match_status === 'matched'
                            ? 'Z_KEY existe dans Dashlane'
                            : dashlaneProvider?.write_supported
                              ? 'Z_KEY sera créé dans Dashlane'
                              : 'Writer Dashlane requis'}
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 text-[11px]"
                        onClick={() => void copyText(row.note_template, `Note ${row.name} copiée`)}
                      >
                        <Copy className="mr-1.5 size-3" />
                        Note
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
              {pendingDashlaneRows.length > 6 ? (
                <p className="text-muted-foreground mt-2 text-[11px]">+{pendingDashlaneRows.length - 6} autre(s) variable(s).</p>
              ) : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog
        open={dashlaneModalOpen}
        onOpenChange={(open) => {
          if (!dashlaneSyncRunning) setDashlaneModalOpen(open)
        }}
      >
        <DialogContent className="max-h-[92vh] max-w-3xl overflow-hidden">
          <DialogHeader>
            <DialogTitle>Sync Zab → Dashlane</DialogTitle>
            <DialogDescription>
              Zab cherche <code className="bg-muted rounded px-1">Z_&lt;KEY&gt;</code> dans Dashlane, crée le Secret manquant si le writer est disponible, puis remplace la valeur locale par la référence <code className="bg-muted rounded px-1">dl://</code>.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-3">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input
                  type="checkbox"
                  className="size-4 rounded border-border"
                  checked={dashlaneAllSelected}
                  disabled={dashlaneSyncRunning || selectableDashlaneRows.length === 0}
                  onChange={(event) => setDashlaneSelectionAll(event.currentTarget.checked)}
                />
                Tout sélectionner
              </label>
              <span className="text-muted-foreground text-xs">
                {selectedDashlaneRows.length}/{selectableDashlaneRows.length} sélectionné(s)
              </span>
            </div>

            {dashlaneAllSelected ? (
              <div className="rounded-lg border border-alerte/35 bg-alerte/10 p-3 text-alerte">
                <div className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                  <div className="space-y-2">
                    <p className="text-sm font-semibold">Toutes les variables éligibles sont sélectionnées.</p>
                    <label className="flex items-center gap-2 text-xs font-medium">
                      <input
                        type="checkbox"
                        className="size-4 rounded border-alerte/35"
                        checked={dashlaneConfirmAll}
                        disabled={dashlaneSyncRunning}
                        onChange={(event) => setDashlaneConfirmAll(event.currentTarget.checked)}
                      />
                      Confirmer la synchronisation complète
                    </label>
                  </div>
                </div>
              </div>
            ) : null}

            <div className="max-h-[48vh] overflow-auto rounded-lg border border-border">
              {selectableDashlaneRows.length === 0 ? (
                <p className="text-muted-foreground p-4 text-sm">
                  Aucune variable fichier en attente.
                </p>
              ) : (
                <ul className="divide-y divide-border">
                  {selectableDashlaneRows.map((row) => {
                    const checked = dashlaneSelectedNames.has(row.name)
                    const result = dashlaneResults[row.name]
                    const active = dashlaneActiveName === row.name
                    const synced = result?.status === 'synced'
                    const created = synced && result?.dashlane_secret_status === 'created'
                    const failed = result?.status === 'error'
                    const createRequired = result?.status === 'create_required'
                    const resultReason =
                      result?.reason === 'dashlane_secret_write_unavailable'
                        ? 'Writer Dashlane non configuré pour créer le Secret.'
                        : result?.reason
                    return (
                      <li key={row.name} className="p-3">
                        <div className="flex items-start gap-3">
                          <input
                            type="checkbox"
                            className="mt-1 size-4 rounded border-border"
                            checked={checked}
                            disabled={dashlaneSyncRunning}
                            onChange={(event) => toggleDashlaneSelection(row.name, event.currentTarget.checked)}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="font-mono text-xs font-semibold">{row.name}</p>
                              {active ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-info/10 px-2 py-0.5 text-[10px] font-medium text-info ring-1 ring-info/35">
                                  <Loader2 className="size-3 animate-spin" />
                                  en cours
                                </span>
                              ) : synced ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-succes/10 px-2 py-0.5 text-[10px] font-medium text-succes ring-1 ring-succes/35">
                                  <CheckCircle2 className="size-3" />
                                  {created ? 'créé + sync' : 'sync'}
                                </span>
                              ) : failed ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 px-2 py-0.5 text-[10px] font-medium text-danger ring-1 ring-danger/35">
                                  <XCircle className="size-3" />
                                  erreur
                                </span>
                              ) : createRequired ? (
                                <span className="inline-flex items-center gap-1 rounded-full bg-alerte/10 px-2 py-0.5 text-[10px] font-medium text-alerte ring-1 ring-alerte/35">
                                  <AlertTriangle className="size-3" />
                                  à créer
                                </span>
                              ) : null}
                            </div>
                            <p className="text-muted-foreground mt-1 font-mono text-[11px]">{row.dashlane_title}</p>
                            <p className="text-muted-foreground mt-0.5 break-all font-mono text-[11px]">
                              {dashlaneReferenceByName[row.name]
                                ? `${row.name}=${dashlaneReferenceByName[row.name]}`
                                : `${row.name}=dl://…`}
                            </p>
                            {row.dashlane_match_status === 'matched' ? (
                              <p className="mt-2 text-[11px] text-succes">
                                Secret existant : <span className="font-mono">{row.dashlane_title}</span>
                              </p>
                            ) : (
                              <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-alerte/35 bg-alerte/10 p-2">
                                <p className="min-w-0 flex-1 text-[11px] text-alerte">
                                  {dashlaneProvider?.write_supported ? 'Sera créé dans Dashlane' : 'Création automatique à configurer'} :{' '}
                                  <span className="font-mono">{row.dashlane_title}</span>
                                </p>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="h-7 text-[11px]"
                                  disabled={dashlaneCopyingName === row.name}
                                  onClick={() => void copyDashlaneValue(row)}
                                >
                                  {dashlaneCopyingName === row.name ? (
                                    <Loader2 className="mr-1.5 size-3 animate-spin" />
                                  ) : (
                                    <Copy className="mr-1.5 size-3" />
                                  )}
                                  Copier valeur
                                </Button>
                              </div>
                            )}
                            {resultReason ? (
                              <p className="mt-1 text-[11px] text-alerte">
                                {resultReason}
                                {result?.hint ? <span className="ml-1">{result.hint}</span> : null}
                              </p>
                            ) : null}
                            {result?.changed_files?.length ? (
                              <p className="mt-1 text-[11px] text-succes">
                                {result.changed_files.length} fichier(s) mis à jour
                              </p>
                            ) : null}
                          </div>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 shrink-0 text-[11px]"
                            disabled={!row.note_template}
                            onClick={() => void copyText(row.note_template, `Note ${row.name} copiée`)}
                          >
                            <Copy className="mr-1.5 size-3" />
                            Note
                          </Button>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" disabled={dashlaneSyncRunning} onClick={() => setDashlaneModalOpen(false)}>
              Fermer
            </Button>
            <Button
              type="button"
              disabled={
                dashlaneSyncRunning ||
                selectedDashlaneRows.length === 0 ||
                (dashlaneAllSelected && !dashlaneConfirmAll)
              }
              onClick={() => void runDashlaneModalSync()}
            >
              {dashlaneSyncRunning ? <Loader2 className="mr-1.5 size-3.5 animate-spin" /> : <RefreshCw className="mr-1.5 size-3.5" />}
              Lancer un par un
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Card>
        <CardHeader>
          <CardTitle>Variables suivies — provenance</CardTitle>
          <CardDescription>
            D’où vient chaque clé (processus du dashboard ou fichier .env). Le bouton Ouvrir place le curseur sur la
            ligne de la clé dans l’éditeur.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Variable</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Aperçu</TableHead>
                <TableHead>Synced</TableHead>
                <TableHead className="w-[100px]"> </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {overviewLoading ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground text-sm">
                    Chargement…
                  </TableCell>
                </TableRow>
              ) : envVars.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground text-sm">
                    Aucune variable suivie.
                  </TableCell>
                </TableRow>
              ) : (
                envVars.map((row) => {
                  const fileSources = row.sources.filter((s): s is SecurityEnvFileSource => s.kind === 'file')
                  const proc = row.sources.find((s): s is SecurityEnvProcessSource => s.kind === 'process')
                  const primaryFile = fileSources[0]
                  const openToken = primaryFile ? `${primaryFile.path}:${primaryFile.key}:${primaryFile.line ?? ''}` : ''
                  const dashlaneWebUrl = row.sync?.status === 'synced' ? row.sync.dashlane_web_url : ''
                  return (
                    <TableRow key={row.name}>
                      <TableCell className="font-mono text-xs">{row.name}</TableCell>
                      <TableCell className="text-xs">
                        <ul className="space-y-1.5">
                          {proc ? (
                            <li>
                              <span className="text-muted-foreground">Processus</span>
                              {proc.keys.length > 0 && proc.keys[0] !== row.name ? (
                                <span className="font-mono text-[11px]"> ({proc.keys.join(', ')})</span>
                              ) : null}
                            </li>
                          ) : null}
                          {fileSources.length === 0 && !proc ? (
                            <li className="text-muted-foreground">—</li>
                          ) : null}
                          {fileSources.map((src) => (
                            <li key={`${src.path}:${src.key}`} className="font-mono text-[11px] leading-snug">
                              {src.path_display}
                              <span className="text-muted-foreground font-sans"> → </span>
                              {src.key}
                              {src.line ? (
                                <span className="text-muted-foreground font-sans"> (l.{src.line})</span>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{row.masked || (row.present ? '••••' : '—')}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <SecuritySyncPill sync={row.sync} />
                          {dashlaneWebUrl ? (
                            <a
                              href={dashlaneWebUrl}
                              target="_blank"
                              rel="noreferrer"
                              title="Voir dans Dashlane"
                              aria-label={`Voir ${row.name} dans Dashlane`}
                              className={cn(buttonVariants({ variant: 'outline', size: 'xs' }), 'h-6 text-[11px]')}
                            >
                              <ExternalLink className="size-3" />
                              Voir
                            </a>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        {primaryFile ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-7 text-[11px]"
                            disabled={openingKey === openToken}
                            onClick={() =>
                              void openEnvInEditor(primaryFile.path, {
                                line: primaryFile.line,
                                key: primaryFile.key,
                              })
                            }
                          >
                            Ouvrir
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      </>
      ) : null}
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

type MemorySearchRow = {
  document_id: string
  chunk_id: string
  source: string
  export_batch_id: string
  wing: string | null
  room: string | null
  path?: string | null
  chunk_index: number
  content_excerpt: string
  created_at: string | null
}

type MemoryConfigHistoryRow = {
  key: string
  title: string
  kind: string
  exists: boolean
  path_display: string
  updated_at_unix: number | null
  bytes: number | null
}

function MemorySection({
  projects,
  miningProjectPath,
  running,
  runPreset,
  jobLines,
  jobId,
}: {
  projects: OverviewProject[]
  miningProjectPath: string | null
  running: boolean
  runPreset: (p: string, a?: Record<string, unknown>) => void
  jobLines: string[]
  jobId: string | null
}) {
  const { t } = useI18n()
  const [jsonlPath, setJsonlPath] = useState('')
  const [status, setStatus] = useState<MemoryStatusPayload | null>(null)
  const [docOffset, setDocOffset] = useState(0)
  const [docs, setDocs] = useState<MemoryDocRow[]>([])
  const [docsErr, setDocsErr] = useState<string | null>(null)
  const [chunksByDoc, setChunksByDoc] = useState<Record<string, MemoryChunkRow[]>>({})
  const [chunksLoading, setChunksLoading] = useState<string | null>(null)
  const [memoryQuery, setMemoryQuery] = useState('')
  const [memoryWingFilter, setMemoryWingFilter] = useState('')
  const [memorySourceFilter, setMemorySourceFilter] = useState('')
  const [memorySearchLoading, setMemorySearchLoading] = useState(false)
  const [memorySearchResults, setMemorySearchResults] = useState<MemorySearchRow[]>([])
  const [projectScanPath, setProjectScanPath] = useState('')
  const [projectScanPersist, setProjectScanPersist] = useState(true)
  const [projectScan, setProjectScan] = useState<Record<string, unknown> | null>(null)
  const [projectScanLoading, setProjectScanLoading] = useState(false)
  const [configHistory, setConfigHistory] = useState<MemoryConfigHistoryRow[]>([])
  const [configHistoryLoading, setConfigHistoryLoading] = useState(false)
  const [modelsDiscovery, setModelsDiscovery] = useState<Record<string, unknown> | null>(null)
  const [lastScanMeta, setLastScanMeta] = useState<Record<string, unknown> | null>(null)
  const pageSize = 20

  const sortedProjects = useMemo(
    () =>
      [...projects].sort((a, b) =>
        `${a.org}/${a.name}`.localeCompare(`${b.org}/${b.name}`, undefined, { sensitivity: 'base' }),
      ),
    [projects],
  )

  const [selectedMinePaths, setSelectedMinePaths] = useState<Set<string>>(() => new Set())
  const [mineScanMode, setMineScanMode] = useState<'projects' | 'convos'>('projects')
  const [batchMining, setBatchMining] = useState(false)
  const [batchProgress, setBatchProgress] = useState<{ current: number; total: number; label: string } | null>(
    null,
  )
  const [batchLogLines, setBatchLogLines] = useState<string[]>([])

  const memoryBusy = running || batchMining || miningProjectPath != null

  useEffect(() => {
    if (!projectScanPath && sortedProjects[0]?.path) {
      setProjectScanPath(sortedProjects[0].path)
    }
  }, [projectScanPath, sortedProjects])

  const toggleMinePath = (path: string) => {
    setSelectedMinePaths((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  const selectAllMine = () => {
    setSelectedMinePaths(new Set(sortedProjects.map((p) => p.path)))
  }

  const clearMineSelection = () => {
    setSelectedMinePaths(new Set())
  }

  const runBatchMine = async () => {
    const paths = sortedProjects.filter((p) => selectedMinePaths.has(p.path)).map((p) => p.path)
    if (paths.length === 0) {
      toast.message('Aucun projet coché')
      return
    }
    setBatchMining(true)
    setBatchLogLines([])
    const accumulated: string[] = []
    let stoppedEarly = false
    for (let i = 0; i < paths.length; i++) {
      const projectPath = paths[i]
      const proj = sortedProjects.find((p) => p.path === projectPath)
      const name = proj?.name ?? projectPath
      setBatchProgress({ current: i + 1, total: paths.length, label: name })
      try {
        const r = await startJobAndCollectLines('mempalace_mine', {
          project_path: projectPath,
          wing: name,
          mode: mineScanMode,
        })
        accumulated.push(`\n=== ${name} (${projectPath}) ===\n`, ...r.lines)
        setBatchLogLines([...accumulated])
        if (!(r.status === 'done' && r.exit_code === 0)) {
          toast.error(`MemPalace : échec sur « ${name} » (code ${String(r.exit_code)})`)
          stoppedEarly = true
          break
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
        stoppedEarly = true
        break
      }
    }
    setBatchMining(false)
    setBatchProgress(null)
    if (!stoppedEarly) {
      toast.success(`MemPalace : ${paths.length} projet(s) indexé(s)`)
    }
  }

  const loadStatus = useCallback(async () => {
    try {
      const s = await apiJson<MemoryStatusPayload>('/api/memory/status')
      setStatus(s)
    } catch {
      setStatus(null)
    }
  }, [])

  const loadConfigRecovery = useCallback(async () => {
    setConfigHistoryLoading(true)
    try {
      const [hist, discovery, last] = await Promise.all([
        apiJson<MemoryConfigHistoryRow[]>('/api/config/history'),
        apiJson<Record<string, unknown>>('/api/config/models-discovery'),
        apiJson<Record<string, unknown>>('/api/scan/last'),
      ])
      setConfigHistory(hist)
      setModelsDiscovery(discovery)
      setLastScanMeta(last)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setConfigHistoryLoading(false)
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

  useEffect(() => {
    void loadConfigRecovery()
  }, [loadConfigRecovery])

  const runProjectScan = async () => {
    if (!projectScanPath.trim()) {
      toast.message('Choisissez un projet à scanner')
      return
    }
    setProjectScanLoading(true)
    try {
      const q = new URLSearchParams()
      q.set('root', projectScanPath.trim())
      if (projectScanPersist) q.set('persist', '1')
      const j = await apiJson<Record<string, unknown>>(`/api/scan?${q.toString()}`)
      setProjectScan(j)
      toast.success(projectScanPersist ? 'Scan projet terminé et persisté' : 'Scan projet terminé')
      await loadConfigRecovery()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setProjectScanLoading(false)
    }
  }

  const runMemorySearch = async (queryOverride?: string) => {
    const qText = (queryOverride ?? memoryQuery).trim()
    if (!qText) {
      toast.message('Saisissez une requête mémoire')
      return
    }
    setMemorySearchLoading(true)
    try {
      const q = new URLSearchParams()
      q.set('q', qText)
      q.set('limit', '12')
      if (memoryWingFilter.trim()) q.set('wing', memoryWingFilter.trim())
      if (memorySourceFilter.trim()) q.set('source', memorySourceFilter.trim())
      const payload = await apiJson<{ results: MemorySearchRow[] }>(`/api/memory/search?${q.toString()}`)
      setMemorySearchResults(payload.results ?? [])
      toast.success(`${payload.results?.length ?? 0} résultat(s) mémoire`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setMemorySearchLoading(false)
    }
  }

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
        <h2 className="text-2xl font-semibold tracking-tight">{t('memory.title')}</h2>
        <p className="text-muted-foreground text-sm">
          {t('memory.subtitle')}{' '}
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
          <CardTitle>Recherche mémoire</CardTitle>
          <CardDescription>
            Recherche dans Postgres : conversations Cursor / Claude / Codex / Kimi, plans, règles et skills synchronisés par{' '}
            <code className="text-xs">zab memory sync-agents</code>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_190px_220px_auto]">
            <input
              className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm"
              placeholder="Rechercher une conversation, ex. extension chrome danmdata"
              value={memoryQuery}
              onChange={(e) => setMemoryQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void runMemorySearch()
              }}
            />
            <select
              className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm"
              value={memorySourceFilter}
              onChange={(e) => setMemorySourceFilter(e.target.value)}
            >
              <option value="">Toutes sources</option>
              <option value="cursor_agent_transcript">Cursor</option>
              <option value="claude_code_transcript">Claude Code</option>
              <option value="codex_transcript">Codex</option>
              <option value="kimi_transcript">Kimi</option>
              <option value="agent_context_artifact">Plans / règles / skills</option>
            </select>
            <input
              className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm"
              placeholder="wing optionnel (danmdata, zab…)"
              value={memoryWingFilter}
              onChange={(e) => setMemoryWingFilter(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void runMemorySearch()
              }}
            />
            <Button type="button" disabled={memorySearchLoading || !memoryQuery.trim()} onClick={() => void runMemorySearch()}>
              <HugeiconsIcon icon={Search01Icon} size={16} className="mr-1.5" />
              {memorySearchLoading ? 'Recherche…' : 'Chercher'}
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            {['extension chrome danmdata', 'composio flowmetrik-wa', 'mempalace postgres', 'gmail', 'codex', 'kimi'].map((q) => (
              <Button
                key={q}
                type="button"
                variant="outline"
                size="sm"
                className="text-xs"
                onClick={() => {
                  setMemoryQuery(q)
                  void runMemorySearch(q)
                }}
              >
                {q}
              </Button>
            ))}
          </div>
          {memorySearchResults.length > 0 ? (
            <div className="space-y-3">
              <p className="text-muted-foreground text-xs">{memorySearchResults.length} résultat(s). Cliquez sur “Voir la conversation” pour ouvrir les chunks du document.</p>
              {memorySearchResults.map((r, index) => (
                <article key={`${r.document_id}:${r.chunk_id}:${r.chunk_index}:${index}`} className="rounded-xl border border-border p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-muted px-2 py-0.5 font-medium text-foreground">
                      {r.source}
                    </span>
                    <span className="text-muted-foreground">{r.wing ?? '—'} / {r.room ?? '—'}</span>
                    <span className="text-muted-foreground">chunk {r.chunk_index}</span>
                  </div>
                  {r.path ? <p className="text-muted-foreground mt-1 break-all font-mono text-[10px]">{shortenHomeInPath(r.path)}</p> : null}
                  <pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-[11px] leading-relaxed">
                    {r.content_excerpt}
                  </pre>
                  <button
                    type="button"
                    className="text-primary mt-2 text-[11px] font-medium hover:underline"
                    onClick={() => void openChunks(r.document_id)}
                  >
                    {chunksByDoc[r.document_id] ? 'Masquer la conversation' : 'Voir la conversation'}
                  </button>
                  {chunksByDoc[r.document_id] ? (
                    <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/70 p-3 text-[11px] leading-relaxed">
                      {chunksByDoc[r.document_id].map((c) => `[#${c.chunk_index}] ${c.content_excerpt}`).join('\n\n—\n\n')}
                    </pre>
                  ) : null}
                </article>
              ))}
            </div>
          ) : memoryQuery.trim() && !memorySearchLoading ? (
            <p className="text-muted-foreground text-xs">Aucun résultat pour cette requête.</p>
          ) : null}
        </CardContent>
      </Card>

      <details className="rounded-xl border border-border bg-card" data-testid="memory-tools-details">
        <summary className="cursor-pointer select-none px-5 py-4 text-sm font-medium">
          Outils techniques mémoire
          <span className="text-muted-foreground ml-2 font-normal">
            scan projet, config, MemPalace, état Postgres, import JSONL
          </span>
        </summary>
        <div className="space-y-4 border-t border-border p-5">
          <Card data-testid="memory-project-scan">
            <CardHeader>
              <CardTitle>Scan projet & contexte mémoire</CardTitle>
              <CardDescription>
                Lance <code className="text-xs">/api/scan</code> sur un projet précis pour vérifier SKILL.md, outils locaux,
                Cursor/Cody, MemPalace et la sonde Postgres avant indexation.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
                <select
                  className="border-input bg-background min-w-0 rounded-lg border px-3 py-2 text-sm"
                  value={projectScanPath}
                  onChange={(e) => setProjectScanPath(e.target.value)}
                >
                  {sortedProjects.length === 0 ? <option value="">Aucun projet détecté</option> : null}
                  {sortedProjects.map((p, index) => (
                    <option key={`${p.org}:${p.name}:${p.path}:${index}`} value={p.path}>
                      {p.org}/{p.name} — {shortenHomeInPath(p.path)}
                    </option>
                  ))}
                </select>
                <Button type="button" disabled={projectScanLoading || !projectScanPath.trim()} onClick={() => void runProjectScan()}>
                  <HugeiconsIcon icon={Search01Icon} size={16} className="mr-1.5" />
                  {projectScanLoading ? 'Scan…' : 'Scanner'}
                </Button>
              </div>
              <label className="text-muted-foreground flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={projectScanPersist}
                  onChange={(e) => setProjectScanPersist(e.target.checked)}
                />
                Persister le résultat dans <code className="bg-muted rounded px-1">scan-last.yaml</code> et mettre à jour
                <code className="bg-muted rounded px-1">last_scan_at_utc</code> /{' '}
                <code className="bg-muted rounded px-1">models_discovery</code>
              </label>
              {projectScan ? <MemoryProjectScanSummary scan={projectScan} /> : null}
            </CardContent>
          </Card>

          <Card data-testid="memory-config-recovery">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle>Récupération configuration</CardTitle>
                <CardDescription>Dernier scan persisté, fichiers config courants et découverte modèles enregistrée.</CardDescription>
              </div>
              <Button type="button" variant="secondary" size="sm" disabled={configHistoryLoading} onClick={() => void loadConfigRecovery()}>
                Rafraîchir
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Entrée</TableHead>
                    <TableHead>État</TableHead>
                    <TableHead>Modifié</TableHead>
                    <TableHead>Chemin</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {configHistory.map((row) => (
                    <TableRow key={row.key}>
                      <TableCell className="text-xs">
                        <span className="font-medium">{row.title}</span>
                        <span className="text-muted-foreground ml-1">({row.kind})</span>
                      </TableCell>
                      <TableCell className="text-xs">{row.exists ? `${row.bytes ?? 0} o` : 'absent'}</TableCell>
                      <TableCell className="text-xs">
                        {row.updated_at_unix ? new Date(row.updated_at_unix * 1000).toLocaleString() : '—'}
                      </TableCell>
                      <TableCell className="max-w-[360px] truncate font-mono text-[11px]">
                        {shortenHomeInPath(row.path_display)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {configHistory.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-muted-foreground text-xs">
                        {configHistoryLoading ? 'Chargement…' : 'Aucun historique récupérable.'}
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
              <div className="grid gap-3 lg:grid-cols-2">
                <details className="text-xs">
                  <summary className="text-muted-foreground cursor-pointer select-none py-1">Dernier scan persisté</summary>
                  <pre className="bg-muted mt-2 max-h-56 overflow-auto rounded-lg p-3">
                    {JSON.stringify(lastScanMeta ?? { present: false }, null, 2)}
                  </pre>
                </details>
                <details className="text-xs">
                  <summary className="text-muted-foreground cursor-pointer select-none py-1">models_discovery config.yaml</summary>
                  <pre className="bg-muted mt-2 max-h-56 overflow-auto rounded-lg p-3">
                    {JSON.stringify(modelsDiscovery ?? {}, null, 2)}
                  </pre>
                </details>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Indexer dans MemPalace (local)</CardTitle>
              <CardDescription>
                Cochez les dépôts puis lancez l’indexation. En mode <strong className="font-medium">Code &amp; docs</strong>, seuls
                les fichiers <code className="text-xs">.md</code>, <code className="text-xs">.pdf</code> et{' '}
                <code className="text-xs">.txt</code> sont ingérés en texte ; les <code className="text-xs">.csv</code> ne donnent
                qu’un descriptif (en-têtes + volume) ; le reste est ignoré. Cela alimente le palace local (SQLite / Chroma) — pas
                l’import Postgres.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground font-medium">Mode :</span>
            <Button
              type="button"
              size="sm"
              variant={mineScanMode === 'projects' ? 'default' : 'outline'}
              disabled={memoryBusy}
              onClick={() => setMineScanMode('projects')}
            >
              Code & docs
            </Button>
            <Button
              type="button"
              size="sm"
              variant={mineScanMode === 'convos' ? 'default' : 'outline'}
              disabled={memoryBusy}
              onClick={() => setMineScanMode('convos')}
            >
              Conversations
            </Button>
          </div>
          {sortedProjects.length === 0 ? (
            <p className="text-muted-foreground text-xs">
              Aucun projet détecté. Configurez <code className="font-mono">projects_roots</code> dans l’onglet Projets.
            </p>
          ) : (
            <ul className="max-h-56 space-y-2 overflow-y-auto rounded-lg border border-border p-3">
              {sortedProjects.map((p, index) => (
                <li key={`${p.org}:${p.name}:${p.path}:${index}`} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1 size-4 shrink-0 rounded border-border"
                    checked={selectedMinePaths.has(p.path)}
                    disabled={memoryBusy}
                    onChange={() => toggleMinePath(p.path)}
                  />
                  <label className="flex min-w-0 flex-1 cursor-pointer flex-col gap-0.5 leading-snug">
                    <button
                      type="button"
                      className="text-left font-medium hover:underline"
                      disabled={memoryBusy}
                      onClick={() => toggleMinePath(p.path)}
                    >
                      {p.name}{' '}
                      <span className="text-muted-foreground font-normal">({p.org})</span>
                    </button>
                    <span className="text-muted-foreground font-mono text-[10px] break-all">
                      {shortenHomeInPath(p.path)}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={memoryBusy} onClick={selectAllMine}>
              Tout cocher
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={memoryBusy} onClick={clearMineSelection}>
              Tout décocher
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={memoryBusy || selectedMinePaths.size === 0}
              onClick={() => void runBatchMine()}
            >
              <HugeiconsIcon icon={PlayCircleIcon} size={16} className="mr-1.5" />
              Lancer l&apos;indexation ({selectedMinePaths.size})
            </Button>
          </div>
          {batchProgress ? (
            <div className="space-y-1">
              <div className="text-muted-foreground flex justify-between text-[11px]">
                <span>
                  {batchProgress.label} — {batchProgress.current} / {batchProgress.total}
                </span>
                <span>{Math.round((100 * batchProgress.current) / batchProgress.total)} %</span>
              </div>
              <div className="bg-muted h-2 overflow-hidden rounded-full">
                <div
                  className="bg-primary h-2 rounded-full transition-[width] duration-300"
                  style={{ width: `${(100 * batchProgress.current) / batchProgress.total}%` }}
                />
              </div>
            </div>
          ) : null}
          {batchLogLines.length > 0 ? (
            <pre className="bg-muted max-h-48 overflow-auto rounded-lg p-3 text-[11px]">{batchLogLines.join('\n')}</pre>
          ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>MemPalace CLI</CardTitle>
              <CardDescription>Installation isolée recommandée (<code className="text-xs">uv tool install</code>).</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Button type="button" disabled={memoryBusy} onClick={() => runPreset('mempalace_install')}>
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
            <LoadingState compact label="Chargement…" />
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
                <li className="text-alerte">{status.error}</li>
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
            disabled={memoryBusy || !jsonlPath.trim()}
            onClick={() => runPreset('memory_import', { jsonl_path: jsonlPath.trim() })}
          >
            <HugeiconsIcon icon={AiBrain02Icon} size={16} className="mr-1.5" />
            Importer
          </Button>
            </CardContent>
          </Card>
        </div>
      </details>

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

function MemoryProjectScanSummary({ scan }: { scan: Record<string, unknown> }) {
  const memoryStack = (scan.memory_stack as Record<string, unknown> | undefined) || {}
  const mempalace = (memoryStack.mempalace as Record<string, unknown> | undefined) || {}
  const postgres = (memoryStack.postgres_probe as Record<string, unknown> | undefined) || {}
  const scripts = (memoryStack.skills_scripts as Record<string, unknown> | undefined) || {}
  const warnings = Array.isArray(scan.warnings) ? (scan.warnings as string[]) : []
  const workspaceProjects = Array.isArray(scan.workspace_projects) ? scan.workspace_projects.length : 0
  const skillCount = typeof scan.skill_md_count === 'number' ? scan.skill_md_count : 0

  return (
    <div className="rounded-lg border border-border p-3 text-xs">
      <div className="grid gap-2 md:grid-cols-2">
        <p className="text-muted-foreground">
          Racine scannée :{' '}
          <span className="font-mono text-foreground break-all">{shortenHomeInPath(String(scan.scan_root_resolved ?? '—'))}</span>
        </p>
        <p>
          SKILL.md : <span className="font-medium">{skillCount}</span> · projets détectés :{' '}
          <span className="font-medium">{workspaceProjects}</span>
        </p>
        <p>
          MemPalace :{' '}
          <span className="font-medium">{mempalace.on_path === true ? 'présent' : 'absent'}</span>
          {typeof mempalace.version === 'string' && mempalace.version ? (
            <span className="text-muted-foreground ml-1 font-mono">{mempalace.version}</span>
          ) : null}
        </p>
        <p>
          DSN mémoire :{' '}
          <span className="font-medium">
            {memoryStack.MEHDI_MEMORY_DATABASE_URL_configured === true ? 'configuré' : 'absent'}
          </span>
        </p>
        <p>
          Import JSONL :{' '}
          <span className="font-medium">{scripts.import_memory_jsonl_exists === true ? 'script présent' : 'script absent'}</span>
        </p>
        <p>
          Postgres :{' '}
          <span className="font-mono">
            {typeof postgres.document_count === 'number' && typeof postgres.chunk_count === 'number'
              ? `docs ${postgres.document_count}, chunks ${postgres.chunk_count}`
              : String(postgres.skipped_reason ?? '—')}
          </span>
        </p>
      </div>
      {warnings.length > 0 ? (
        <ul className="mt-3 space-y-1 text-alerte">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
      <details className="mt-3">
        <summary className="text-muted-foreground cursor-pointer select-none py-1">JSON scan complet</summary>
        <pre className="bg-muted mt-2 max-h-72 overflow-auto rounded-lg p-3">{JSON.stringify(scan, null, 2)}</pre>
      </details>
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
  const { t } = useI18n()
  const [codeTools, setCodeTools] = useState<CodeToolRow[]>([])
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const payload = await apiJson<{ data: CodeToolRow[] }>('/api/code-tools?limit=50')
        if (!cancelled) setCodeTools(payload.data ?? [])
      } catch {
        if (!cancelled) setCodeTools([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('ide.title')}</h2>
        <p className="text-muted-foreground text-sm">{t('ide.subtitle')}</p>
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
            <CardTitle>{t('ide.codeTools')}</CardTitle>
            <CardDescription>Agents et IDE détectés par l’index local</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('ide.columns.tool')}</TableHead>
                  <TableHead>{t('ide.columns.provider')}</TableHead>
                  <TableHead>{t('ide.columns.state')}</TableHead>
                  <TableHead>{t('ide.columns.binary')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {codeTools.map((tool, index) => (
                  <TableRow key={`${tool.key}:${tool.id}:${tool.binary ?? ''}:${index}`}>
                    <TableCell className="font-medium text-xs">{tool.display_name ?? tool.id}</TableCell>
                    <TableCell className="font-mono text-xs">{tool.provider ?? '—'}</TableCell>
                    <TableCell className="text-xs">{tool.installed ? t('memory.installed') : t('memory.absent')}</TableCell>
                    <TableCell className="font-mono text-[11px] break-all">{tool.binary ?? '—'}</TableCell>
                  </TableRow>
                ))}
                {codeTools.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-muted-foreground text-xs">
                      Aucun outil indexé. Lancez un sync depuis la vue d’ensemble.
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
            {!scanTools ? (
              <p className="text-muted-foreground text-sm">Chargement…</p>
            ) : (
              <div className="space-y-4">
                <div>
                  <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Commandes zab</p>
                  <ul className="space-y-1">
                    {scanTools.cli_commands.map((c, index) => (
                      <li key={`${c.id}:${c.name}:${index}`} className="flex items-center gap-2 text-xs">
                        <code className="bg-muted rounded px-1.5 py-0.5 font-mono">{c.name}</code>
                        <span className="text-muted-foreground">{c.description}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="text-muted-foreground mb-2 text-[11px] font-medium uppercase">Scripts ({scanTools.scripts.length})</p>
                  <ul className="space-y-1 max-h-64 overflow-auto">
                    {scanTools.scripts.map((s, index) => (
                      <li key={`${s.id}:${s.path}:${index}`} className="flex items-start gap-2 text-xs">
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

type AgentDiscoveryRow = {
  id: string
  codexbar_usage_id: string | null
  cli_path: string | null
  on_path: boolean
  cli_source?: string | null
  sources: string[]
  agentpipe_type?: string | null
  coding_models_preview?: string[] | null
}

type AgentsDiscoveryPayload = {
  codexbar_config_path?: string
  codexbar_present?: boolean
  codexbar_error?: string
  agentpipe_path?: string
  agentpipe_present?: boolean
  agentpipe_error?: string
  rows: AgentDiscoveryRow[]
}

type CodexAgentsApiPayload = {
  config_path: string
  present?: boolean
  agents: Array<{
    id: string
    enabled?: boolean
    cli_path: string | null
    on_path: boolean
    cli_source?: string
  }>
  error?: string
}

function isApiNotFoundMessage(msg: string): boolean {
  const m = msg.toLowerCase()
  return (
    m.includes('not found') ||
    (m.includes('"detail"') && m.includes('not found')) ||
    m.includes('404')
  )
}

function codexAgentsToDiscoveryPayload(legacy: CodexAgentsApiPayload): AgentsDiscoveryPayload {
  return {
    codexbar_config_path: legacy.config_path,
    codexbar_present: legacy.present,
    codexbar_error: legacy.error,
    rows: legacy.agents.map((a) => ({
      id: a.id,
      codexbar_usage_id: a.id,
      cli_path: a.cli_path,
      on_path: a.on_path,
      cli_source: a.cli_source ?? 'codexbar',
      sources: ['codexbar'],
      agentpipe_type: null,
      coding_models_preview: null,
    })),
  }
}

function pickFirstUsageEntry(apiData: unknown): Record<string, unknown> | null {
  if (apiData == null) return null
  if (Array.isArray(apiData)) {
    for (const item of apiData) {
      if (item && typeof item === 'object' && 'usage' in item) {
        return item as Record<string, unknown>
      }
    }
    return null
  }
  if (typeof apiData === 'object' && apiData !== null && 'usage' in apiData) {
    return apiData as Record<string, unknown>
  }
  return null
}

function UsageBand({
  title,
  window,
}: {
  title: string
  window: Record<string, unknown> | null | undefined
}) {
  if (!window || typeof window !== 'object') return null
  const up = window.usedPercent
  const pct = typeof up === 'number' ? Math.min(100, Math.max(0, up)) : null
  const wm = window.windowMinutes
  const rd = window.resetDescription
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-muted-foreground text-[11px] font-medium">{title}</span>
        {pct != null ? (
          <span className="font-mono text-[11px]">{pct}%</span>
        ) : (
          <span className="text-muted-foreground text-[11px]">—</span>
        )}
      </div>
      {pct != null ? (
        <div className="bg-muted h-2 w-full overflow-hidden rounded-full">
          <div className="bg-primary h-full rounded-full transition-all" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
      <p className="text-muted-foreground text-[10px]">
        {[typeof wm === 'number' ? `fenêtre ${wm} min` : null, typeof rd === 'string' ? rd : null].filter(Boolean).join(' · ') ||
          '—'}
      </p>
    </div>
  )
}

function ProviderUsageCard({
  agentId,
  payload,
  noCodexbar,
  loading,
}: {
  agentId: string
  payload: Record<string, unknown> | undefined
  noCodexbar?: boolean
  loading?: boolean
}) {
  if (noCodexbar) {
    return (
      <p className="text-muted-foreground text-xs">
        Agent listé via agentpipe uniquement — pas de provider CodexBar correspondant : pas de quota{' '}
        <code className="bg-muted rounded px-1">codexbar usage</code>.
      </p>
    )
  }
  if (!payload && loading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <Loader2 className="size-3.5 animate-spin" />
        Chargement en cours…
      </div>
    )
  }
  if (!payload) {
    return <p className="text-muted-foreground text-xs">Pas encore chargé — clique sur « Rafraîchir la conso ».</p>
  }
  if (payload.ok === false) {
    return (
      <div className="text-danger text-xs">
        {String(payload.error ?? payload.stderr_preview ?? 'erreur')}
        {typeof payload.exit_code === 'number' ? ` (exit ${payload.exit_code})` : ''}
      </div>
    )
  }
  const raw = payload.data
  const entry = pickFirstUsageEntry(raw)
  const usage =
    entry && typeof entry.usage === 'object' && entry.usage !== null ? (entry.usage as Record<string, unknown>) : null
  if (!usage) {
    return <p className="text-muted-foreground text-xs">Données usage vides ou format inattendu.</p>
  }
  const email = typeof usage.accountEmail === 'string' ? usage.accountEmail : null
  const login = typeof usage.loginMethod === 'string' ? usage.loginMethod : null
  const prim = usage.primary as Record<string, unknown> | undefined
  const sec = usage.secondary as Record<string, unknown> | undefined
  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-sm font-medium">{agentId}</p>
          {email ? <p className="text-muted-foreground text-[11px]">{email}</p> : null}
          {login ? <p className="text-muted-foreground text-[11px]">{login}</p> : null}
        </div>
        {loading ? (
          <span className="text-muted-foreground inline-flex shrink-0 items-center gap-1 text-[10px]">
            <Loader2 className="size-3 animate-spin" />
            live
          </span>
        ) : null}
      </div>
      <UsageBand title="Fenêtre principale" window={prim} />
      <UsageBand title="Fenêtre secondaire" window={sec} />
    </div>
  )
}

function ModelsCodySection() {
  const { t } = useI18n()
  const [discoveryPayload, setDiscoveryPayload] = useState<AgentsDiscoveryPayload | null>(null)
  const [agentsLoading, setAgentsLoading] = useState(true)
  const [agentsErr, setAgentsErr] = useState<string | null>(null)
  const [discoveryNotice, setDiscoveryNotice] = useState<string | null>(null)
  const [discoveryScanning, setDiscoveryScanning] = useState(false)
  const [usageByProvider, setUsageByProvider] = useState<Record<string, Record<string, unknown>>>({})
  const [usageLoading, setUsageLoading] = useState(false)
  const [usageLoadingByProvider, setUsageLoadingByProvider] = useState<Record<string, boolean>>({})

  const loadAgentsDiscovery = useCallback(async () => {
    setAgentsLoading(true)
    setAgentsErr(null)
    setDiscoveryNotice(null)
    try {
      const j = await apiJson<AgentsDiscoveryPayload>('/api/agents/discovery')
      setDiscoveryPayload(j)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (isApiNotFoundMessage(msg)) {
        try {
          const legacy = await apiJson<CodexAgentsApiPayload>('/api/agents')
          setDiscoveryPayload(codexAgentsToDiscoveryPayload(legacy))
          setDiscoveryNotice(
            'L’API « /api/agents/discovery » est absente (zab à redémarrer ou à mettre à jour). Affichage limité aux agents CodexBar.',
          )
          return
        } catch (e2) {
          setDiscoveryPayload(null)
          setAgentsErr(e2 instanceof Error ? e2.message : String(e2))
          return
        }
      }
      setDiscoveryPayload(null)
      setAgentsErr(msg)
    } finally {
      setAgentsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadAgentsDiscovery()
  }, [loadAgentsDiscovery])

  const runWorkspaceDiscovery = async () => {
    setDiscoveryScanning(true)
    try {
      await apiJson<Record<string, unknown>>('/api/scan?persist=true')
      toast.success('Découverte enregistrée (agentpipe + codexbar dans models_discovery, dernier scan).')
      await loadAgentsDiscovery()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setDiscoveryScanning(false)
    }
  }

  const refreshUsage = async () => {
    const rows = discoveryPayload?.rows ?? []
    const targets = [
      ...new Set(rows.filter((r) => r.codexbar_usage_id).map((r) => r.codexbar_usage_id as string)),
    ]
    if (!targets.length) {
      toast.message('Aucun provider CodexBar dans la liste — rien à interroger pour la conso.')
      return
    }
    setUsageLoading(true)
    setUsageLoadingByProvider((prev) => {
      const next = { ...prev }
      for (const providerId of targets) next[providerId] = true
      return next
    })
    try {
      await Promise.allSettled(
        targets.map(async (providerId) => {
          try {
            const j = await apiJson<Record<string, unknown>>(
              `/api/codexbar/usage?provider=${encodeURIComponent(providerId)}`,
            )
            setUsageByProvider((prev) => ({ ...prev, [providerId]: j }))
          } catch (e) {
            setUsageByProvider((prev) => ({
              ...prev,
              [providerId]: { ok: false, error: e instanceof Error ? e.message : String(e), provider: providerId },
            }))
          } finally {
            setUsageLoadingByProvider((prev) => ({ ...prev, [providerId]: false }))
          }
        }),
      )
    } finally {
      setUsageLoading(false)
    }
  }

  const rows = discoveryPayload?.rows ?? []
  const codexbarPath = discoveryPayload?.codexbar_config_path
  const agentpipePath = discoveryPayload?.agentpipe_path

  return (
    <div className="space-y-6">
      <header>
        <h2 className="text-2xl font-semibold tracking-tight">{t('models.title')}</h2>
        <p className="text-muted-foreground text-sm">{t('models.subtitle')}</p>
      </header>

      <Card>
        <CardHeader className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 space-y-1">
            <CardTitle>Agents &amp; consommation</CardTitle>
            <CardDescription className="space-y-1">
              <span className="font-mono text-[11px] break-words">
                CodexBar : {codexbarPath ? shortenHomeInPath(codexbarPath) : '—'}
              </span>
              <span className="font-mono text-[11px] break-words block">
                Agentpipe : {agentpipePath ? shortenHomeInPath(agentpipePath) : '—'}
              </span>
            </CardDescription>
          </div>
          <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
            <Button
              type="button"
              variant="default"
              size="sm"
              className="max-sm:flex-1"
              disabled={discoveryScanning}
              onClick={() => void runWorkspaceDiscovery()}
            >
              {discoveryScanning ? 'Découverte…' : 'Découvrir & enregistrer'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="max-sm:flex-1"
              disabled={agentsLoading}
              onClick={() => void loadAgentsDiscovery()}
            >
              {agentsLoading ? 'Chargement…' : 'Recharger la liste'}
            </Button>
            <Button
              type="button"
              size="sm"
              className="max-sm:flex-1"
              disabled={usageLoading || !rows.some((r) => r.codexbar_usage_id)}
              onClick={() => void refreshUsage()}
            >
              {usageLoading ? 'Rafraîchissement…' : 'Rafraîchir la conso'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-8">
          <div className="space-y-4">
            {agentsErr ? <p className="text-destructive text-sm">{agentsErr}</p> : null}
            {discoveryNotice ? (
              <p className="text-alerte text-sm">{discoveryNotice}</p>
            ) : null}
            {discoveryPayload?.codexbar_error && discoveryPayload.codexbar_error !== 'codexbar_config_missing' ? (
              <p className="text-alerte text-sm">CodexBar : {discoveryPayload.codexbar_error}</p>
            ) : null}
            {discoveryPayload?.agentpipe_error ? (
              <p className="text-alerte text-sm">Agentpipe : {discoveryPayload.agentpipe_error}</p>
            ) : null}
            {!agentsLoading && discoveryPayload?.codexbar_error === 'codexbar_config_missing' ? (
              <p className="text-muted-foreground text-sm">
                Fichier CodexBar introuvable. Indique <code className="bg-muted rounded px-1">codexbar_config_path</code> dans la
                config zab si besoin.
              </p>
            ) : null}
            <div className="w-full overflow-x-auto">
              <Table className="min-w-[720px]">
                <TableHeader>
                  <TableRow>
                    <TableHead>Agent</TableHead>
                    <TableHead>CLI</TableHead>
                    <TableHead>Statut</TableHead>
                    <TableHead>Origines</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={4} className="text-muted-foreground text-xs">
                        {agentsLoading
                          ? 'Chargement…'
                          : 'Aucun agent — lance « Découvrir & enregistrer » ou vérifie agentpipe / CodexBar.'}
                      </TableCell>
                    </TableRow>
                  ) : (
                    rows.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="max-w-[200px]">
                          <div className="font-mono text-xs">{r.id}</div>
                          {r.agentpipe_type ? (
                            <div className="text-muted-foreground mt-0.5 text-[10px]">type agentpipe : {r.agentpipe_type}</div>
                          ) : null}
                          {r.coding_models_preview && r.coding_models_preview.length > 0 ? (
                            <div
                              className="text-muted-foreground mt-0.5 line-clamp-2 text-[10px]"
                              title={r.coding_models_preview.join(', ')}
                            >
                              modèles : {r.coding_models_preview.join(', ')}
                            </div>
                          ) : null}
                        </TableCell>
                        <TableCell className="font-mono text-xs break-all">
                          {r.cli_path ? shortenHomeInPath(r.cli_path) : '—'}
                        </TableCell>
                        <TableCell className="text-xs">{r.on_path ? 'sur le PATH' : 'hors PATH'}</TableCell>
                        <TableCell className="text-muted-foreground text-xs">
                          {r.sources.length ? r.sources.join(' + ') : '—'}
                          {r.cli_source ? (
                            <span className="text-muted-foreground block text-[10px] opacity-80">CLI : {r.cli_source}</span>
                          ) : null}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </div>
          </div>
          <div className="space-y-3 border-t border-border pt-6">
            <p className="text-muted-foreground text-xs">
              Consommation : uniquement les agents qui ont aussi une entrée CodexBar activée (même identifiant fusionné par
              nom).
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              {rows.map((r) => (
                <ProviderUsageCard
                  key={r.id}
                  agentId={r.id}
                  noCodexbar={!r.codexbar_usage_id}
                  loading={r.codexbar_usage_id ? Boolean(usageLoadingByProvider[r.codexbar_usage_id]) : false}
                  payload={r.codexbar_usage_id ? usageByProvider[r.codexbar_usage_id] : undefined}
                />
              ))}
            </div>
          </div>
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
  const { t } = useI18n()
  if (!open) return null

  return (
    <div className="fixed inset-0 z-30 flex items-stretch justify-end bg-black/30">
      <button className="flex-1" type="button" aria-label={t('skillEditor.closeAria')} onClick={() => onOpenChange(false)} />
      <div className="bg-background flex h-full w-full max-w-3xl flex-col border-l shadow-2xl">
        <div className="flex items-center justify-between border-b px-5 py-3">
          <div className="flex items-center gap-2">
            <div className="flex size-8 items-center justify-center rounded-md bg-muted">
              <HugeiconsIcon icon={PencilEdit02Icon} size={16} />
            </div>
            <div>
              <p className="text-sm font-semibold">{t('skillEditor.title')}</p>
              <p className="text-muted-foreground text-[11px]">{t('skillEditor.pathHint')}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="text-muted-foreground hover:text-foreground rounded-md px-2 py-1 text-sm"
          >
            {t('skillEditor.close')}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b px-5 py-3">
          <input
            className="border-input bg-background min-w-[240px] flex-1 rounded-lg border px-3 py-2 text-sm"
            value={path}
            onChange={(e) => onPathChange(e.target.value)}
          />
          <Button type="button" variant="secondary" onClick={onLoad}>
            {t('skillEditor.load')}
          </Button>
          <Button type="button" onClick={onSave}>
            {t('skillEditor.save')}
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
