import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { LoadingState } from '@/components/ui/loading-state'
import { CostChart, Ring, Sparkline, type CostDay } from '@/components/remote-vm-charts'

type Endpoint = {
  protocol?: string | null
  host?: string | null
  path?: string | null
  connected: boolean
  scanned: boolean
  files: number
  directories: number
  symlinks: number
  total_size: number
  scan_problems: number
  transition_problems: number
  staging?: { path?: string | null; received: number; total: number } | null
}

type SyncSession = {
  name: string
  status?: string | null
  paused: boolean
  mode?: string | null
  last_error?: string | null
  successful_cycles: number
  conflicts: number
  alpha: Endpoint
  beta: Endpoint
  file_delta: number
  problems: number
}

type SyncState = {
  configured: boolean
  engine?: string
  alias?: string
  error?: string | null
  sessions: SyncSession[]
  totals?: {
    sessions: number
    connected: number
    watching: number
    paused: number
    conflicts: number
    problems: number
    alpha_files: number
    beta_files: number
    file_delta: number
    alpha_size: number
    beta_size: number
    staging_total: number
    staging_received: number
  }
}

type SshConnection = { pid: number; kind: string; elapsed_seconds: number | null; command: string }

type SshState = {
  configured: boolean
  alias?: string
  control_master: { state: string; detail?: string | null }
  connections: SshConnection[]
  tunnels: number
  sync_agents: number
  shells: number
  mutagen_daemon: boolean
  active?: boolean
  error?: string
}

type VmState = {
  configured: boolean
  found?: boolean
  status?: string | null
  error?: string | null
  project?: string
  zone?: string
  instance?: string
  machine_type?: string
  vcpus?: number | null
  memory_gb?: number | null
  disks?: { name: string; size_gb: number | null; boot: boolean }[]
  disk_total_gb?: number | null
  internal_ip?: string | null
  external_ip?: string | null
  last_start?: string | null
  last_stop?: string | null
  session_seconds?: number | null
  last_session_seconds?: number | null
  auto_stop_idle_minutes?: number | null
  console_url?: string
  checked_at?: string
}

type Overview = {
  configured: boolean
  config: {
    project: string
    zone: string
    instance: string
    ssh_alias?: string | null
    billing_configured: boolean
    vmctl?: string | null
    auto_stop_idle_minutes?: number | null
  }
  vm: VmState
  ssh: SshState
  sync: SyncState
}

type CostReport = {
  configured?: boolean
  error?: string
  currency?: string
  window_days?: number
  days?: CostDay[]
  by_sku?: { sku: string; category: string; cost: number; units: number; unit?: string }[]
  totals?: {
    window_cost: number
    window_hours: number
    mtd_cost: number
    mtd_hours: number
    last7_cost: number
    last7_hours: number
    today_cost: number
    today_hours: number
    running_days: number
    hourly_rate: number | null
    fixed_daily_cost: number | null
    month_projection: number | null
  }
  freshness?: { last_billed_day?: string | null; billed_through?: string | null; lag_days?: number | null }
  cached?: boolean
  stale?: boolean
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const text = await r.text()
    throw new Error(text || r.statusText)
  }
  return r.json() as Promise<T>
}

function formatDuration(seconds?: number | null) {
  if (seconds == null || seconds < 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`
  return `${s}s`
}

function formatBytes(bytes: number) {
  if (!bytes) return '0 o'
  const units = ['o', 'Ko', 'Mo', 'Go', 'To']
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function statusTone(status?: string | null) {
  switch ((status || '').toUpperCase()) {
    case 'RUNNING':
      return 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300'
    case 'TERMINATED':
    case 'STOPPED':
    case 'SUSPENDED':
      return 'bg-zinc-500/15 text-zinc-700 ring-zinc-500/30 dark:text-zinc-300'
    case 'STAGING':
    case 'PROVISIONING':
    case 'STOPPING':
    case 'SUSPENDING':
      return 'bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300'
    default:
      return 'bg-red-500/15 text-red-700 ring-red-500/30 dark:text-red-300'
  }
}

const SESSION_TONE: Record<string, string> = {
  watching: 'bg-emerald-500',
  'scanning-alpha': 'bg-sky-500',
  'scanning-beta': 'bg-sky-500',
  reconciling: 'bg-sky-500',
  'staging-alpha': 'bg-sky-500',
  'staging-beta': 'bg-sky-500',
  transitioning: 'bg-sky-500',
  saving: 'bg-sky-500',
  'connecting-alpha': 'bg-amber-500',
  'connecting-beta': 'bg-amber-500',
  'waiting-for-rescan': 'bg-amber-500',
  halted: 'bg-red-500',
  paused: 'bg-zinc-400',
}

export function RemoteVmView() {
  const [overview, setOverview] = useState<Overview | null>(null)
  const [cost, setCost] = useState<CostReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [costLoading, setCostLoading] = useState(false)
  const [windowDays, setWindowDays] = useState(30)
  const [busy, setBusy] = useState<string | null>(null)
  // Compteur de session avancé localement entre deux lectures serveur.
  const [liveSession, setLiveSession] = useState<number | null>(null)

  const loadOverview = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const data = await apiJson<Overview>('/api/remote-vm/overview')
      setOverview(data)
      setLiveSession(data.vm?.session_seconds ?? null)
    } catch (e) {
      if (!quiet) toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [])

  const loadCost = useCallback(async (days: number, refresh = false) => {
    setCostLoading(true)
    try {
      const data = await apiJson<CostReport>(`/api/remote-vm/cost?days=${days}&refresh=${refresh}`)
      setCost(data)
      if (refresh && !data.error) toast.success('Facturation rafraîchie')
      if (data.error) toast.error(data.error)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setCostLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  useEffect(() => {
    void loadCost(windowDays)
  }, [loadCost, windowDays])

  useEffect(() => {
    const poll = window.setInterval(() => void loadOverview(true), 30_000)
    const clock = window.setInterval(() => setLiveSession((v) => (v == null ? v : v + 1)), 1000)
    return () => {
      window.clearInterval(poll)
      window.clearInterval(clock)
    }
  }, [loadOverview])

  const runAction = useCallback(
    async (action: 'start' | 'stop') => {
      if (action === 'stop' && !window.confirm('Arrêter la VM ? La sync est vidée puis mise en pause.')) return
      setBusy(action)
      try {
        await apiJson(`/api/remote-vm/${action}`, { method: 'POST' })
        toast.success(action === 'start' ? 'VM démarrée, sync relancée' : 'Sync figée, VM arrêtée')
        await loadOverview()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(null)
      }
    },
    [loadOverview],
  )

  const runSyncAction = useCallback(
    async (action: 'sync-flush' | 'sync-resume' | 'sync-pause') => {
      setBusy(action)
      try {
        await apiJson(`/api/remote-vm/sync-action?action=${action}`, { method: 'POST' })
        toast.success(`${action} terminé`)
        await loadOverview()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      } finally {
        setBusy(null)
      }
    },
    [loadOverview],
  )

  const currency = cost?.currency || 'EUR'
  const money = useMemo(
    () => new Intl.NumberFormat('fr-FR', { style: 'currency', currency, maximumFractionDigits: 2 }),
    [currency],
  )

  if (loading && !overview) {
    return <LoadingState label="Lecture de la VM distante…" />
  }

  if (overview && !overview.configured) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>VM distante non configurée</CardTitle>
          <CardDescription>{overview.vm?.error}</CardDescription>
        </CardHeader>
        <CardContent>
          <pre className="bg-muted overflow-auto rounded-lg p-3 text-xs">{`remote_vm:
  deploy_config: ~/chemin/vers/config.json   # ou project / zone / instance
  gcloud_config: ma-configuration-gcloud
  ssh_alias: mon-alias-ssh
  billing:
    table: projet.dataset.gcp_billing_export_resource_v1_XXXXXX`}</pre>
        </CardContent>
      </Card>
    )
  }

  const vm = overview?.vm
  const ssh = overview?.ssh
  const sync = overview?.sync
  const totals = cost?.totals
  const syncTotals = sync?.totals
  const days = cost?.days ?? []
  const running = (vm?.status || '').toUpperCase() === 'RUNNING'

  const healthySessions = syncTotals ? syncTotals.watching : 0
  const totalSessions = syncTotals?.sessions ?? 0
  const syncTone = totalSessions === 0 ? 'zinc' : healthySessions === totalSessions ? 'emerald' : 'amber'

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Workstation</h1>
            <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${statusTone(vm?.status)}`}>
              {vm?.status ?? '—'}
            </span>
            {running && liveSession != null ? (
              <span className="text-muted-foreground rounded-full bg-emerald-500/10 px-2.5 py-0.5 font-mono text-xs tabular-nums text-emerald-700 dark:text-emerald-300">
                {formatDuration(liveSession)}
              </span>
            ) : null}
          </div>
          <p className="text-muted-foreground text-sm">
            <span className="font-mono">{vm?.instance}</span> · {vm?.machine_type} · {vm?.zone}
            {vm?.auto_stop_idle_minutes ? ` · auto-stop ${vm.auto_stop_idle_minutes} min d’inactivité` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="secondary" disabled={loading} onClick={() => void loadOverview()}>
            {loading ? 'Lecture…' : 'Rafraîchir'}
          </Button>
          <Button type="button" disabled={running || busy != null} onClick={() => void runAction('start')}>
            {busy === 'start' ? 'Démarrage…' : 'Démarrer'}
          </Button>
          <Button type="button" variant="outline" disabled={!running || busy != null} onClick={() => void runAction('stop')}>
            {busy === 'stop' ? 'Arrêt…' : 'Arrêter'}
          </Button>
          {vm?.console_url ? (
            <a href={vm.console_url} target="_blank" rel="noreferrer" className="inline-flex">
              <Button type="button" variant="secondary">
                Console GCP
              </Button>
            </a>
          ) : null}
        </div>
      </header>

      {vm?.error ? (
        <p className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-700 dark:text-red-300">{vm.error}</p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardContent className="space-y-2 pt-6">
            <p className="text-muted-foreground text-xs">Coût mois en cours</p>
            <p className="text-2xl font-semibold tabular-nums">{totals ? money.format(totals.mtd_cost) : '—'}</p>
            <Sparkline values={days.map((d) => d.net_cost)} tone="sky" />
            <p className="text-muted-foreground text-xs">
              projection {totals?.month_projection != null ? money.format(totals.month_projection) : '—'} · socle éteinte{' '}
              {totals?.fixed_daily_cost != null ? `${money.format(totals.fixed_daily_cost)}/j` : '—'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-2 pt-6">
            <p className="text-muted-foreground text-xs">Heures allumée (mois)</p>
            <p className="text-2xl font-semibold tabular-nums">
              {totals ? `${totals.mtd_hours.toFixed(1)} h` : '—'}
            </p>
            <Sparkline values={days.map((d) => d.hours)} tone="amber" />
            <p className="text-muted-foreground text-xs">
              {totals ? `${totals.window_hours.toFixed(1)} h sur ${cost?.window_days} j · ` : ''}
              {totals?.hourly_rate != null ? `${money.format(totals.hourly_rate)}/h` : 'taux inconnu'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-2 pt-6">
            <p className="text-muted-foreground text-xs">Connexions SSH</p>
            <div className="flex items-center gap-2">
              <span
                className={`size-2.5 rounded-full ${ssh?.active ? 'bg-emerald-500 animate-pulse' : 'bg-zinc-400'}`}
                aria-hidden
              />
              <p className="text-2xl font-semibold tabular-nums">{ssh?.connections.length ?? 0}</p>
              <span className="text-muted-foreground text-xs">
                {ssh?.control_master.state === 'up' ? 'multiplexage actif' : 'multiplexage fermé'}
              </span>
            </div>
            <div className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
              <span>{ssh?.tunnels ?? 0} tunnel(s)</span>
              <span>{ssh?.sync_agents ?? 0} agent(s) sync</span>
              <span>{ssh?.shells ?? 0} shell(s)</span>
            </div>
            <p className="text-muted-foreground text-xs">
              démon de sync {ssh?.mutagen_daemon ? 'en marche' : 'arrêté'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-2 pt-6">
            <p className="text-muted-foreground text-xs">Sync</p>
            <Ring value={healthySessions} total={totalSessions} tone={syncTone as 'emerald' | 'amber' | 'zinc'} label="sessions à jour" />
            <p className="text-muted-foreground text-xs">
              {syncTotals ? `${syncTotals.alpha_files.toLocaleString('fr-FR')} fichiers · écart ${syncTotals.file_delta}` : '—'}
              {syncTotals?.conflicts ? ` · ${syncTotals.conflicts} conflit(s)` : ''}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>Coût et heures d’exécution</CardTitle>
            <CardDescription>
              Export de facturation au niveau ressource
              {cost?.freshness?.billed_through ? ` · complet jusqu’au ${cost.freshness.billed_through}` : ''}
              {cost?.stale ? ' · données en cache (requête indisponible)' : ''}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-1">
            {[7, 30, 90].map((d) => (
              <Button
                key={d}
                type="button"
                size="xs"
                variant={windowDays === d ? 'default' : 'outline'}
                onClick={() => setWindowDays(d)}
              >
                {d} j
              </Button>
            ))}
            <Button type="button" size="xs" variant="secondary" disabled={costLoading} onClick={() => void loadCost(windowDays, true)}>
              {costLoading ? '…' : 'Recalculer'}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {cost?.error && days.length === 0 ? (
            <p className="text-muted-foreground text-xs">{cost.error}</p>
          ) : (
            <CostChart days={days} currency={currency} />
          )}

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Metric label="Aujourd’hui (facturé)" value={totals ? money.format(totals.today_cost) : '—'} hint={totals ? `${totals.today_hours.toFixed(2)} h` : undefined} />
            <Metric label="7 derniers jours" value={totals ? money.format(totals.last7_cost) : '—'} hint={totals ? `${totals.last7_hours.toFixed(1)} h` : undefined} />
            <Metric label={`Fenêtre ${cost?.window_days ?? windowDays} j`} value={totals ? money.format(totals.window_cost) : '—'} hint={totals ? `${totals.running_days} jour(s) allumée` : undefined} />
            <Metric
              label="Coût horaire réel"
              value={totals?.hourly_rate != null ? `${money.format(totals.hourly_rate)}/h` : '—'}
              hint={totals?.fixed_daily_cost != null ? `+ ${money.format(totals.fixed_daily_cost)}/j éteinte` : undefined}
            />
          </div>

          {(cost?.by_sku?.length ?? 0) > 0 ? (
            <details className="text-xs">
              <summary className="text-muted-foreground cursor-pointer select-none">Détail par SKU</summary>
              <ul className="mt-2 space-y-1">
                {cost?.by_sku?.map((row) => (
                  <li key={row.sku} className="flex items-center justify-between gap-3">
                    <span className="truncate">{row.sku}</span>
                    <span className="tabular-nums">{money.format(row.cost)}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Machine</CardTitle>
            <CardDescription>Ressources et cycle de vie de l’instance.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm md:grid-cols-2">
            <Info label="Projet" value={vm?.project} mono />
            <Info label="Zone" value={vm?.zone} mono />
            <Info label="Type" value={vm?.machine_type} />
            <Info label="CPU / RAM" value={vm?.vcpus ? `${vm.vcpus} vCPU · ${vm.memory_gb} Go` : undefined} />
            <Info label="Disques" value={vm?.disks?.map((d) => `${d.name} ${d.size_gb} Go`).join(' · ')} />
            <Info label="IP interne" value={vm?.internal_ip} mono />
            <Info label="Dernier démarrage" value={vm?.last_start} mono />
            <Info label="Dernier arrêt" value={vm?.last_stop} mono />
            <Info
              label="Session en cours"
              value={running && liveSession != null ? formatDuration(liveSession) : undefined}
            />
            <Info label="Dernière session" value={formatDuration(vm?.last_session_seconds)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Connexions SSH</CardTitle>
            <CardDescription>
              Alias <span className="font-mono">{ssh?.alias}</span> · multiplexage OpenSSH, tunnels et agents de sync
              observés localement.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span
                className={`rounded-full px-2 py-0.5 ring-1 ring-inset ${
                  ssh?.control_master.state === 'up'
                    ? 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300'
                    : 'bg-zinc-500/15 text-zinc-600 ring-zinc-500/30 dark:text-zinc-300'
                }`}
              >
                control master {ssh?.control_master.state}
              </span>
              {ssh?.control_master.detail ? (
                <span className="text-muted-foreground truncate">{ssh.control_master.detail}</span>
              ) : null}
            </div>

            {(ssh?.connections.length ?? 0) === 0 ? (
              <p className="text-muted-foreground text-xs">
                Aucune connexion SSH locale vers la VM. La sync se reconnecte au prochain démarrage.
              </p>
            ) : (
              <ul className="divide-border divide-y text-xs">
                {ssh?.connections.map((c) => (
                  <li key={c.pid} className="flex items-center justify-between gap-3 py-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span
                        className={`size-2 shrink-0 rounded-full ${
                          c.kind === 'tunnel' ? 'bg-sky-500' : c.kind === 'sync-agent' ? 'bg-violet-500' : 'bg-emerald-500'
                        }`}
                        aria-hidden
                      />
                      <span className="font-medium">{c.kind}</span>
                      <span className="text-muted-foreground truncate font-mono">{c.command}</span>
                    </span>
                    <span className="text-muted-foreground shrink-0 tabular-nums">
                      pid {c.pid} · {formatDuration(c.elapsed_seconds)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle>Synchronisation</CardTitle>
            <CardDescription>
              {syncTotals
                ? `${syncTotals.sessions} session(s) ${sync?.engine} · ${syncTotals.connected} connectée(s) · ${syncTotals.watching} à jour`
                : 'Sessions de synchronisation avec la VM.'}
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-1">
            <Button type="button" size="xs" variant="outline" disabled={busy != null} onClick={() => void runSyncAction('sync-flush')}>
              Forcer un cycle
            </Button>
            <Button type="button" size="xs" variant="outline" disabled={busy != null} onClick={() => void runSyncAction('sync-resume')}>
              Reprendre
            </Button>
            <Button type="button" size="xs" variant="outline" disabled={busy != null} onClick={() => void runSyncAction('sync-pause')}>
              Mettre en pause
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {sync?.error ? <p className="text-muted-foreground text-xs">{sync.error}</p> : null}

          {syncTotals ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                label="Fichiers local → distant"
                value={`${syncTotals.alpha_files.toLocaleString('fr-FR')} → ${syncTotals.beta_files.toLocaleString('fr-FR')}`}
                hint={`${formatBytes(syncTotals.alpha_size)} / ${formatBytes(syncTotals.beta_size)}`}
              />
              <Metric
                label="Écart de fichiers"
                value={String(syncTotals.file_delta)}
                hint={syncTotals.file_delta === 0 ? 'les deux côtés concordent' : 'reste à propager'}
                tone={syncTotals.file_delta === 0 ? 'ok' : 'warn'}
              />
              <Metric
                label="Conflits"
                value={String(syncTotals.conflicts)}
                hint={syncTotals.problems ? `${syncTotals.problems} problème(s)` : 'aucun problème'}
                tone={syncTotals.conflicts === 0 && syncTotals.problems === 0 ? 'ok' : 'warn'}
              />
              <Metric
                label="Transfert en cours"
                value={
                  syncTotals.staging_total > 0
                    ? `${syncTotals.staging_received}/${syncTotals.staging_total}`
                    : 'aucun'
                }
                hint={syncTotals.staging_total > 0 ? 'fichiers en cours de copie' : 'rien en attente'}
              />
            </div>
          ) : null}

          <ul className="divide-border divide-y">
            {(sync?.sessions ?? []).map((session) => {
              const staging = session.beta.staging
              const progress = staging && staging.total > 0 ? staging.received / staging.total : null
              const tone = session.paused ? 'paused' : String(session.status || '')
              return (
                <li key={session.name} className="space-y-1.5 py-2.5">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className={`size-2 shrink-0 rounded-full ${SESSION_TONE[tone] ?? 'bg-zinc-400'}`} aria-hidden />
                      <span className="truncate font-medium">{session.name}</span>
                      <span className="text-muted-foreground text-xs">{session.paused ? 'paused' : session.status}</span>
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                      {session.alpha.files.toLocaleString('fr-FR')} / {session.beta.files.toLocaleString('fr-FR')} fichiers
                      {session.file_delta !== 0 ? (
                        <span className="ml-2 rounded-full bg-amber-500/15 px-1.5 py-0.5 text-amber-700 dark:text-amber-300">
                          Δ {session.file_delta > 0 ? '+' : ''}
                          {session.file_delta}
                        </span>
                      ) : null}
                      {session.conflicts > 0 ? (
                        <span className="ml-2 rounded-full bg-red-500/15 px-1.5 py-0.5 text-red-700 dark:text-red-300">
                          {session.conflicts} conflit(s)
                        </span>
                      ) : null}
                    </span>
                  </div>
                  <div className="bg-muted h-1 w-full overflow-hidden rounded-full">
                    <div
                      className={`h-full rounded-full ${
                        session.status === 'watching' ? 'bg-emerald-500' : session.paused ? 'bg-zinc-400' : 'bg-sky-500'
                      }`}
                      style={{
                        width:
                          progress != null
                            ? `${Math.round(progress * 100)}%`
                            : session.status === 'watching'
                              ? '100%'
                              : session.alpha.connected && session.beta.connected
                                ? '60%'
                                : '12%',
                      }}
                    />
                  </div>
                  {session.last_error ? (
                    <p className="text-muted-foreground truncate text-xs" title={session.last_error}>
                      {session.last_error}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: string
  hint?: string
  tone?: 'ok' | 'warn'
}) {
  const toneClass = tone === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : tone === 'warn' ? 'text-amber-600 dark:text-amber-400' : ''
  return (
    <div className="bg-muted/40 min-w-0 rounded-lg p-3">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className={`truncate text-lg font-semibold tabular-nums ${toneClass}`}>{value}</p>
      {hint ? <p className="text-muted-foreground truncate text-xs">{hint}</p> : null}
    </div>
  )
}

function Info({ label, value, mono = false }: { label: string; value?: string | number | null; mono?: boolean }) {
  const text = value == null || value === '' ? '—' : String(value)
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className={mono ? 'truncate font-mono text-xs' : 'truncate text-sm'}>{text}</p>
    </div>
  )
}
