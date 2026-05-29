import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type WorkstationStatus = {
  found: boolean
  project_id?: string
  name?: string
  region?: string
  zone?: string | null
  status?: string | null
  machine_type?: string | null
  internal_ip?: string | null
  external_ip?: string | null
  disk_gb?: number | null
  labels?: Record<string, string>
  bucket?: string
  gcloud_config_expected?: string
  gcloud_config_active?: string | null
  firewall?: {
    rule?: string
    found?: boolean
    source_ranges?: string[]
    target_tags?: string[]
    error?: string
  }
  public_ip_detected?: string | null
  console_url?: string
  host?: string | null
  ssh_command?: string | null
  error?: string
}

type ActionResult = {
  ok?: boolean
  action?: string
  exit_code?: number
  output?: string
  error?: string
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const t = await r.text()
    throw new Error(t || r.statusText)
  }
  return r.json() as Promise<T>
}

function statusClass(status?: string | null) {
  switch ((status || '').toUpperCase()) {
    case 'RUNNING':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-200'
    case 'TERMINATED':
    case 'STOPPED':
      return 'bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200'
    case 'STARTING':
    case 'STOPPING':
    case 'PROVISIONING':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200'
    case 'ERROR':
    case 'NOT_FOUND':
      return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200'
    default:
      return 'bg-muted text-muted-foreground'
  }
}

function short(value?: string | null) {
  return value && value.trim() ? value : '—'
}

export function WorkstationView() {
  const [status, setStatus] = useState<WorkstationStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [busyAction, setBusyAction] = useState<'start' | 'stop' | 'sync_dry' | 'sync_run' | null>(null)
  const [lastAction, setLastAction] = useState<ActionResult | null>(null)
  const [syncPreview, setSyncPreview] = useState<string[] | null>(null)

  const loadStatus = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiJson<WorkstationStatus>('/api/workstation/status')
      setStatus(data)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  const runAction = useCallback(
    async (action: 'start' | 'stop') => {
      if (action === 'stop' && !window.confirm('Arrêter la workstation ? Les processus distants seront interrompus.')) {
        return
      }
      setBusyAction(action)
      try {
        const result = await apiJson<ActionResult>(`/api/workstation/${action}`, { method: 'POST' })
        setLastAction(result)
        if (result.ok) toast.success(action === 'start' ? 'Démarrage lancé' : 'Arrêt lancé')
        else toast.error(result.error || 'Action échouée')
        await loadStatus()
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      } finally {
        setBusyAction(null)
      }
    },
    [loadStatus],
  )

  const runSync = useCallback(
    async (dryRun: boolean) => {
      setBusyAction(dryRun ? 'sync_dry' : 'sync_run')
      try {
        const result = await apiJson<ActionResult & { files_affected?: string[] }>(`/api/workstation/sync?dry_run=${dryRun}`, { method: 'POST' })
        setLastAction(result)
        if (dryRun && result.files_affected) {
          setSyncPreview(result.files_affected)
          toast.success(`Prévisualisation: ${result.files_affected.length} fichiers à synchroniser`)
        } else if (!dryRun && result.ok) {
          setSyncPreview(null)
          toast.success('Synchronisation terminée')
        } else if (!result.ok) {
          toast.error(result.error || 'Erreur de synchronisation')
        }
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      } finally {
        setBusyAction(null)
      }
    },
    [],
  )

  const copy = useCallback(async (text?: string | null, label = 'Copié') => {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      toast.success(label)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [])

  const syncToBucketCommand = useMemo(() => {
    if (!status?.bucket) return null
    return `gcloud storage rsync ~/projects ${status.bucket}/projects --recursive --ignore-symlinks --exclude='(^|/)(node_modules|\\.venv|venv|__pycache__|\\.next|dist|build)(/|$)'`
  }, [status?.bucket])

  const publicIpAllowed = useMemo(() => {
    const ip = status?.public_ip_detected
    const ranges = status?.firewall?.source_ranges ?? []
    if (!ip || ranges.length === 0) return null
    return ranges.some((r) => r === `${ip}/32` || r === ip)
  }, [status?.firewall?.source_ranges, status?.public_ip_detected])

  const state = (status?.status || 'unknown').toUpperCase()
  const canStart = status?.found && !['RUNNING', 'STARTING', 'PROVISIONING'].includes(state)
  const canStop = status?.found && !['TERMINATED', 'STOPPED', 'STOPPING'].includes(state)

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Workstation</h1>
          <p className="text-muted-foreground text-sm">
            Pilotage local de la VM remote dev Flowmetrik : état, démarrage, arrêt, SSH et garde-fous réseau.
          </p>
        </div>
        <Button type="button" variant="secondary" disabled={loading} onClick={() => void loadStatus()}>
          {loading ? 'Rafraîchissement…' : 'Rafraîchir'}
        </Button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              État
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusClass(status?.status)}`}>
                {short(status?.status)}
              </span>
            </CardTitle>
            <CardDescription>
              {status?.found === false ? 'Instance introuvable ou inaccessible par gcloud.' : 'Instance Compute Engine configurée.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            {status?.error ? <p className="text-destructive text-xs">{status.error}</p> : null}
            <div className="grid gap-3 md:grid-cols-2">
              <Info label="Projet" value={status?.project_id} mono />
              <Info label="Instance" value={status?.name} mono />
              <Info label="Zone" value={status?.zone} mono />
              <Info label="Région" value={status?.region} mono />
              <Info label="Machine" value={status?.machine_type} />
              <Info label="Disque" value={status?.disk_gb != null ? `${status.disk_gb} Go` : undefined} />
              <Info label="IP interne" value={status?.internal_ip} mono />
              <Info label="IP externe" value={status?.external_ip} mono />
            </div>
            <div className="flex flex-wrap gap-2">
              <Button type="button" disabled={!canStart || busyAction != null} onClick={() => void runAction('start')}>
                {busyAction === 'start' ? 'Démarrage…' : 'Démarrer'}
              </Button>
              <Button type="button" variant="outline" disabled={!canStop || busyAction != null} onClick={() => void runAction('stop')}>
                {busyAction === 'stop' ? 'Arrêt…' : 'Arrêter'}
              </Button>
              <Button type="button" variant="secondary" disabled={!status?.ssh_command} onClick={() => void copy(status?.ssh_command, 'Commande SSH copiée')}>
                Copier SSH
              </Button>
              {status?.host ? (
                <a className="inline-flex" href={`https://80-${status.host}/?authuser=1`} target="_blank" rel="noreferrer">
                  <Button type="button" variant="default">Ouvrir IDE</Button>
                </a>
              ) : null}
              {status?.console_url ? (
                <a className="inline-flex" href={status.console_url} target="_blank" rel="noreferrer">
                  <Button type="button" variant="secondary">Console GCP</Button>
                </a>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Sécurité réseau</CardTitle>
            <CardDescription>Vérification de la règle firewall et de l’IP publique courante.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <Info label="Config gcloud attendue" value={status?.gcloud_config_expected} mono />
            <Info label="Config active" value={status?.gcloud_config_active} mono />
            <Info label="Règle firewall" value={status?.firewall?.rule} mono />
            <Info label="IP publique détectée" value={status?.public_ip_detected} mono />
            <div>
              <p className="text-muted-foreground text-xs">Sources autorisées</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {(status?.firewall?.source_ranges ?? []).length > 0 ? (
                  status?.firewall?.source_ranges?.map((r) => (
                    <span key={r} className="rounded-md bg-muted px-2 py-1 font-mono text-xs">{r}</span>
                  ))
                ) : (
                  <span className="text-muted-foreground text-xs">—</span>
                )}
              </div>
            </div>
            {publicIpAllowed === false ? (
              <p className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
                L’IP publique détectée ne correspond pas aux ranges autorisés. L’accès SSH peut échouer.
              </p>
            ) : null}
            {status?.firewall?.error ? <p className="text-destructive text-xs">{status.firewall.error}</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Sync projets (Mac → Workstation)</CardTitle>
          <CardDescription>
            Synchronise le dossier local `~/projects` vers le bucket GCS de transit (qui est ensuite monté sur la workstation).
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          <Info label="Bucket" value={status?.bucket} mono />
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" disabled={busyAction != null} onClick={() => void runSync(true)}>
              {busyAction === 'sync_dry' ? 'Calcul...' : 'Prévisualiser (Dry Run)'}
            </Button>
            <Button type="button" variant="default" disabled={busyAction != null} onClick={() => void runSync(false)}>
              {busyAction === 'sync_run' ? 'Synchronisation...' : 'Synchroniser'}
            </Button>
          </div>

          {syncPreview != null && (
            <div className="mt-4">
              <p className="text-muted-foreground mb-2 text-xs font-medium">Fichiers modifiés / ajoutés ({syncPreview.length}) :</p>
              <div className="bg-muted max-h-60 overflow-auto rounded-lg p-3 text-xs">
                {syncPreview.length > 0 ? (
                  <ul className="list-inside list-disc pl-2">
                    {syncPreview.map((f, i) => (
                      <li key={i} className="font-mono text-xs">{f}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="text-muted-foreground">Aucun fichier à synchroniser.</span>
                )}
              </div>
            </div>
          )}

          {syncToBucketCommand ? (
            <div className="mt-4">
              <CommandBlock label="Commande de secours" command={syncToBucketCommand} onCopy={copy} />
            </div>
          ) : null}
        </CardContent>
      </Card>

      {lastAction ? (
        <Card>
          <CardHeader>
            <CardTitle>Dernière action</CardTitle>
            <CardDescription>{lastAction.action ?? 'action'} — code {lastAction.exit_code ?? '—'}</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="bg-muted max-h-52 overflow-auto rounded-lg p-3 text-xs">
              {JSON.stringify(lastAction, null, 2)}
            </pre>
          </CardContent>
        </Card>
      ) : null}

      <details className="rounded-xl border border-zinc-200 bg-card p-4 text-xs dark:border-zinc-800">
        <summary className="cursor-pointer select-none font-medium">Payload brut</summary>
        <pre className="bg-muted mt-3 max-h-80 overflow-auto rounded-lg p-3">{JSON.stringify(status ?? {}, null, 2)}</pre>
      </details>
    </div>
  )
}

function Info({ label, value, mono = false }: { label: string; value?: string | number | null; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className={mono ? 'truncate font-mono text-xs' : 'truncate text-sm'}>{short(value == null ? null : String(value))}</p>
    </div>
  )
}

function CommandBlock({ label, command, onCopy }: { label: string; command: string; onCopy: (text: string, label?: string) => Promise<void> }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-muted-foreground text-xs">{label}</p>
        <Button type="button" variant="outline" size="xs" onClick={() => void onCopy(command, 'Commande copiée')}>
          Copier
        </Button>
      </div>
      <pre className="bg-muted overflow-auto rounded-lg p-3 text-xs"><code>{command}</code></pre>
    </div>
  )
}
