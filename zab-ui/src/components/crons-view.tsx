import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useI18n } from '@/i18n/use-i18n'
import { LoadingState } from '@/components/ui/loading-state'

interface CronDetail {
  project?: string
  location?: string
  uri?: string
  service_account?: string
  prompt?: string
  skills?: string[]
  script?: string
  deliver?: string
  workdir?: string
  original_id?: string
}

interface Cron {
  id: string
  name: string
  source: 'hermes' | 'gcp' | string
  schedule: string
  enabled: boolean
  status: 'ok' | 'error' | 'active' | 'paused' | 'warning' | string
  last_run?: string
  next_run?: string
  details?: CronDetail
}

interface LogRun {
  timestamp: string
  status: string
  content: string
}

export default function CronsView() {
  const { t } = useI18n()
  const [crons, setCrons] = useState<Cron[]>([])
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [selectedCron, setSelectedCron] = useState<Cron | null>(null)
  const [logs, setLogs] = useState<LogRun[]>([])
  const [loadingLogs, setLoadingLogs] = useState(false)
  const [selectedLog, setSelectedLog] = useState<LogRun | null>(null)
  const [filter, setFilter] = useState<'all' | 'error' | 'hermes' | 'gcp' | 'launchd' | 'active' | 'paused'>('all')
  const [runningCronId, setRunningCronId] = useState<string | null>(null)

  // Charger les crons initialement
  const fetchCrons = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const r = await fetch('/api/crons')
      if (r.ok) {
        const data = await r.json()
        setCrons(data.crons || [])
      } else {
        toast.error(t('crons.toast.loadError'))
      }
    } catch (err) {
      console.error(err)
      toast.error(t('crons.toast.apiError'))
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    fetchCrons()
  }, [])

  // Synchroniser les crons (scan actif)
  const handleSync = async () => {
    setSyncing(true)
    const tid = toast.loading(t('crons.toast.syncing'))
    try {
      const r = await fetch('/api/crons/sync', { method: 'POST' })
      if (r.ok) {
        const data = await r.json()
        setCrons(data.crons || [])
        toast.success(t('crons.toast.syncOk'), { id: tid })
      } else {
        toast.error(t('crons.toast.syncError'), { id: tid })
      }
    } catch (err) {
      console.error(err)
      toast.error(t('crons.toast.syncError'), { id: tid })
    } finally {
      setSyncing(false)
    }
  }

  // Déclencher un cron manuellement
  const handleRunNow = async (cron: Cron) => {
    setRunningCronId(cron.id)
    const tid = toast.loading(`Lancement du cron "${cron.name}"...`)
    try {
      const r = await fetch(`/api/crons/${cron.id}/run`, { method: 'POST' })
      if (r.ok) {
        const data = await r.json()
        if (data.success) {
          toast.success(`Le cron "${cron.name}" a été exécuté avec succès !`, { id: tid })
          fetchCrons(true) // Recharger discrètement
        } else {
          toast.error(`Erreur d'exécution : ${data.error || 'Inconnue'}`, { id: tid })
        }
      } else {
        toast.error('Erreur serveur lors du déclenchement', { id: tid })
      }
    } catch (err) {
      console.error(err)
      toast.error('Erreur réseau lors du déclenchement', { id: tid })
    } finally {
      setRunningCronId(null)
    }
  }

  // Charger les logs d'un cron sélectionné
  const handleSelectCron = async (cron: Cron) => {
    setSelectedCron(cron)
    setSelectedLog(null)
    setLogs([])
    setLoadingLogs(true)
    try {
      const r = await fetch(`/api/crons/${cron.id}/logs`)
      if (r.ok) {
        const data = await r.json()
        setLogs(data.logs || [])
        if (data.logs && data.logs.length > 0) {
          setSelectedLog(data.logs[0]) // Sélectionner le log le plus récent par défaut
        }
      } else {
        toast.error('Impossible de charger les rapports d’exécution')
      }
    } catch (err) {
      console.error(err)
      toast.error('Erreur lors du chargement des logs')
    } finally {
      setLoadingLogs(false)
    }
  }

  // Filtrage des crons
  const errorCount = crons.filter((c) => c.status === 'error').length

  const filteredCrons = crons.filter((c) => {
    // « Erreur » d'abord : une routine morte doit se voir sans faire défiler 28 entrées.
    if (filter === 'error') return c.status === 'error'
    if (filter === 'hermes') return c.source === 'hermes'
    if (filter === 'gcp') return c.source === 'gcp'
    if (filter === 'launchd') return c.source === 'launchd'
    if (filter === 'active') return c.enabled
    if (filter === 'paused') return !c.enabled
    return true
  })

  // Formatage propre du status
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'ok':
      case 'active':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-succes/10 px-2 py-1 text-xs font-semibold text-succes ring-1 ring-succes/35 ring-inset">
            <span className="size-1.5 rounded-full bg-succes/10 animate-pulse" />
            Actif / OK
          </span>
        )
      case 'paused':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-muted px-2 py-1 text-xs font-semibold text-muted-foreground ring-1 ring-ring/40 ring-inset">
            <span className="size-1.5 rounded-full bg-secondary" />
            Suspendu
          </span>
        )
      case 'error':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-danger/10 px-2 py-1 text-xs font-semibold text-danger ring-1 ring-danger/35 ring-inset">
            <span className="size-1.5 rounded-full bg-danger/10 animate-bounce" />
            Erreur
          </span>
        )
      case 'warning':
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-alerte/10 px-2 py-1 text-xs font-semibold text-alerte ring-1 ring-alerte/35 ring-inset">
            <span className="size-1.5 rounded-full bg-alerte/10" />
            Warning
          </span>
        )
      default:
        return (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-info/10 px-2 py-1 text-xs font-semibold text-info ring-1 ring-info/35 ring-inset">
            <span className="size-1.5 rounded-full bg-info/10" />
            {status}
          </span>
        )
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden bg-muted p-6">
      {/* En-tête de page */}
      <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">{t('crons.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('crons.subtitle')}</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => fetchCrons()}
            disabled={loading || syncing}
            className="flex items-center justify-center rounded-lg border border-border bg-card p-2.5 text-foreground shadow-sm transition hover:bg-muted disabled:opacity-50"
            title="Rafraîchir l'affichage"
          >
            <svg className={`size-4 ${loading ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.228 10h-2.12" />
            </svg>
          </button>
          <button
            onClick={handleSync}
            disabled={syncing || loading}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary disabled:opacity-50"
          >
            <svg className={`size-4 ${syncing ? 'animate-spin' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
            </svg>
            {t('crons.syncSources')}
          </button>
        </div>
      </div>

      {loading && crons.length === 0 ? (
        <LoadingState label={t('crons.loading')} />
      ) : null}

      {/* Grid principale : liste de gauche, logs à droite */}
      <div className="flex min-h-0 flex-1 gap-6 overflow-hidden">
        {/* Liste des Crons */}
        <div className="flex w-full flex-col min-w-0 md:w-1/2 lg:w-5/12 bg-card rounded-xl border border-border shadow-sm overflow-hidden">
          {/* Menu de filtrage */}
          <div className="border-b border-border bg-muted/50 p-3 flex gap-1 overflow-x-auto scrollbar-none">
            {(['all', 'error', 'hermes', 'gcp', 'launchd', 'active', 'paused'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`rounded-md px-3 py-1.5 text-xs font-semibold uppercase transition-colors shrink-0 ${
                  filter === f
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-muted'
                }`}
              >
                {f === 'all' && t('crons.filter.all')}
                {f === 'error' && `${t('crons.filter.error')}${errorCount ? ` (${errorCount})` : ''}`}
                {f === 'hermes' && t('crons.filter.hermes')}
                {f === 'gcp' && t('crons.filter.gcp')}
                {f === 'launchd' && t('crons.filter.launchd')}
                {f === 'active' && t('crons.filter.active')}
                {f === 'paused' && t('crons.filter.paused')}
              </button>
            ))}
          </div>

          {/* Liste proprement dite */}
          <div className="flex-1 overflow-y-auto divide-y divide-border">
            {loading ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <svg className="size-8 animate-spin mb-3 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.228 10h-2.12" />
                </svg>
                <p className="text-sm font-medium">{t('crons.loading')}</p>
              </div>
            ) : filteredCrons.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground text-center px-4">
                <svg className="size-12 mb-3 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-sm font-semibold text-foreground">{t('crons.empty.title')}</p>
                <p className="text-xs max-w-xs mt-1">
                  Essayez de cliquer sur "Sync sources" pour lancer une découverte active locale et GCP.
                </p>
              </div>
            ) : (
              filteredCrons.map((cron) => {
                const isSelected = selectedCron?.id === cron.id
                const isRunning = runningCronId === cron.id
                return (
                  <div
                    key={cron.id}
                    onClick={() => handleSelectCron(cron)}
                    className={`flex flex-col p-4 transition cursor-pointer text-left ${
                      isSelected ? 'bg-muted border-l-4 border-border' : 'hover:bg-muted/50'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                            cron.source === 'gcp' ? 'bg-info/10 text-info' : 'bg-info/10 text-hermes-text text-info'
                          }`}>
                            {cron.source}
                          </span>
                          <span className="text-xs text-muted-foreground font-medium">
                            {cron.schedule}
                          </span>
                        </div>
                        <h3 className="font-semibold text-foreground truncate tracking-tight text-sm">
                          {cron.name}
                        </h3>
                      </div>
                      {getStatusBadge(cron.status)}
                    </div>

                    <div className="mt-4 flex items-center justify-between gap-4 text-xs text-muted-foreground">
                      <div className="min-w-0">
                        {cron.last_run && (
                          <p className="truncate">
                            Dernier run : <span className="font-medium text-foreground">{cron.last_run.substring(0, 19).replace('T', ' ')}</span>
                          </p>
                        )}
                      </div>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleRunNow(cron)
                        }}
                        disabled={isRunning || syncing}
                        className={`flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-semibold transition ${
                          cron.source === 'gcp'
                            ? 'bg-info/10 text-info hover:bg-info/10 disabled:bg-muted'
                            : 'bg-info/10 text-info hover:bg-info/10 disabled:bg-muted'
                        }`}
                      >
                        {isRunning ? (
                          <svg className="size-3 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.228 10h-2.12" />
                          </svg>
                        ) : (
                          <svg className="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                          </svg>
                        )}
                        Run
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Détails et Logs d'exécution */}
        <div className="hidden flex-1 flex-col md:flex bg-card rounded-xl border border-border shadow-sm overflow-hidden min-w-0">
          {selectedCron ? (
            <div className="flex h-full flex-col min-h-0">
              {/* Entête du détail */}
              <div className="border-b border-border bg-muted/50 p-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                        selectedCron.source === 'gcp' ? 'bg-info/10 text-info' : 'bg-info/10 text-info'
                      }`}>
                        {selectedCron.source}
                      </span>
                      <span className="text-xs text-muted-foreground font-semibold tracking-wide">
                        {selectedCron.schedule}
                      </span>
                    </div>
                    <h2 className="text-lg font-bold text-foreground truncate tracking-tight">
                      {selectedCron.name}
                    </h2>
                  </div>
                  <div className="text-right">
                    {getStatusBadge(selectedCron.status)}
                  </div>
                </div>

                {/* Métadonnées de configuration */}
                <div className="mt-4 grid grid-cols-1 gap-2 rounded-lg border border-border bg-card p-3 text-xs text-muted-foreground sm:grid-cols-2">
                  {selectedCron.source === 'gcp' ? (
                    <>
                      <div>
                        <span className="font-semibold text-muted-foreground">Projet GCP : </span>
                        <span className="font-medium text-foreground">{selectedCron.details?.project}</span>
                      </div>
                      <div>
                        <span className="font-semibold text-muted-foreground">Région : </span>
                        <span className="font-medium text-foreground">{selectedCron.details?.location}</span>
                      </div>
                      <div className="sm:col-span-2 truncate" title={selectedCron.details?.uri}>
                        <span className="font-semibold text-muted-foreground">Target URI : </span>
                        <code className="text-[11px] font-mono text-foreground bg-muted px-1 py-0.5 rounded">{selectedCron.details?.uri}</code>
                      </div>
                      <div className="sm:col-span-2 truncate" title={selectedCron.details?.service_account}>
                        <span className="font-semibold text-muted-foreground">Service Account : </span>
                        <span className="font-medium text-foreground">{selectedCron.details?.service_account}</span>
                      </div>
                    </>
                  ) : (
                    <>
                      {selectedCron.details?.script && (
                        <div>
                          <span className="font-semibold text-muted-foreground">Script : </span>
                          <code className="font-mono text-foreground">{selectedCron.details?.script}</code>
                        </div>
                      )}
                      {selectedCron.details?.deliver && (
                        <div>
                          <span className="font-semibold text-muted-foreground">Livraison : </span>
                          <span className="font-medium text-foreground">{selectedCron.details?.deliver}</span>
                        </div>
                      )}
                      {selectedCron.details?.workdir && (
                        <div className="sm:col-span-2 truncate" title={selectedCron.details?.workdir}>
                          <span className="font-semibold text-muted-foreground">Workdir : </span>
                          <span className="font-medium text-foreground font-mono text-[11px]">{selectedCron.details?.workdir}</span>
                        </div>
                      )}
                      {selectedCron.details?.skills && selectedCron.details.skills.length > 0 && (
                        <div className="sm:col-span-2 flex flex-wrap gap-1 items-center mt-1">
                          <span className="font-semibold text-muted-foreground mr-1">Skills :</span>
                          {selectedCron.details.skills.map(s => (
                            <span key={s} className="bg-info/10 text-info font-semibold px-2 py-0.5 rounded text-[10px]">
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                      {selectedCron.details?.prompt && (
                        <div className="sm:col-span-2 mt-1 border-t border-border pt-2">
                          <span className="font-semibold text-muted-foreground block mb-1">Prompt de base :</span>
                          <p className="bg-muted/50 p-2 rounded text-[11px] text-muted-foreground max-h-16 overflow-y-auto leading-relaxed whitespace-pre-wrap italic">
                            "{selectedCron.details.prompt}"
                          </p>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* Contenu principal : liste de runs à gauche, contenu à droite */}
              <div className="flex min-h-0 flex-1 overflow-hidden">
                {/* Historique des runs */}
                <div className="flex w-1/3 flex-col border-r border-border shrink-0 min-h-0 bg-muted/20">
                  <div className="border-b border-border bg-muted/50 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    Runs d'exécution ({logs.length})
                  </div>
                  <div className="flex-1 overflow-y-auto divide-y divide-border min-h-0">
                    {loadingLogs ? (
                      <div className="flex flex-col items-center justify-center h-24 text-muted-foreground">
                        <svg className="size-5 animate-spin mb-1 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.228 10h-2.12" />
                        </svg>
                        <span className="text-xs">Chargement...</span>
                      </div>
                    ) : logs.length === 0 ? (
                      <div className="py-8 text-center text-muted-foreground text-xs px-2">
                        Aucun run trouvé pour ce planificateur.
                      </div>
                    ) : (
                      logs.map((run, idx) => {
                        const isSelected = selectedLog?.timestamp === run.timestamp
                        return (
                          <div
                            key={run.timestamp + idx}
                            onClick={() => setSelectedLog(run)}
                            className={`flex flex-col p-3 text-left transition cursor-pointer ${
                              isSelected ? 'bg-muted font-semibold' : 'hover:bg-muted/80'
                            }`}
                          >
                            <span className="text-xs font-mono text-foreground">
                              {run.timestamp.replace('T', ' ').substring(0, 19)}
                            </span>
                            <div className="flex items-center justify-between gap-2 mt-1">
                              <span className={`text-[10px] font-bold uppercase ${
                                run.status === 'ok' ? 'text-succes' : 'text-danger'
                              }`}>
                                {run.status === 'ok' ? 'REUSSITE' : 'ERREUR'}
                              </span>
                              <svg className="size-3 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                              </svg>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                </div>

                {/* Détails du run sélectionné (le log textuel/MD) */}
                <div className="flex flex-1 flex-col overflow-y-auto p-4 min-h-0 bg-primary font-mono text-xs text-muted-foreground">
                  {selectedLog ? (
                    <div className="whitespace-pre-wrap leading-relaxed text-left">
                      {selectedLog.content}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
                      <svg className="size-8 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      Sélectionnez un run pour voir ses logs.
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-center px-4">
              <svg className="size-16 mb-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
              <h3 className="text-base font-semibold text-foreground">Aucun cron sélectionné</h3>
              <p className="text-xs max-w-sm mt-1">
                Sélectionnez un planificateur dans la liste de gauche pour afficher ses détails, ses runs d'exécution et ses journaux de logs.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
