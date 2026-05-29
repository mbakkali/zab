import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { HugeiconsIcon } from '@hugeicons/react'
import {
  Mail01Icon,
  RefreshIcon,
  Add01Icon,
  MessageMultiple02Icon,
  Settings02Icon,
} from '@hugeicons/core-free-icons'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Loader2, CheckCircle2, AlertCircle, AlertTriangle, PauseCircle } from 'lucide-react'

export type ChannelSyncSummary = {
  unread_count: number
  received_today?: number
  received_this_week?: number
}

export type ChannelItem = {
  id: string
  label: string
  type: 'email' | 'whatsapp' | 'slack' | 'telegram'
  connector: string
  org: string
  email_address?: string
  enabled: boolean
  status?: 'ok' | 'error' | 'pending' | 'degraded' | 'disabled'
  reason?: string | null
  last_synced_at?: string
  sync_summary?: ChannelSyncSummary
}

type ChannelsPayload = {
  generated_at_utc: string
  channels: ChannelItem[]
  total_actions_count: number
}

type OrgItem = {
  org: string
  skills: unknown[]
}

interface ChannelsViewProps {
  orgs?: OrgItem[]
  onRefreshStats?: () => void
  onOpenConnectorsConfig?: (channel: ChannelItem) => void
}

export function ChannelsView({ orgs = [], onRefreshStats, onOpenConnectorsConfig }: ChannelsViewProps) {
  const [data, setData] = useState<ChannelsPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  
  // Modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [type, setType] = useState<'email' | 'whatsapp' | 'slack' | 'telegram'>('email')
  const [connector, setConnector] = useState('gmail')
  const [emailAddress, setEmailAddress] = useState('')
  const [org, setOrg] = useState('personal')
  const [submitting, setSubmitting] = useState(false)

  // Fetch channels data
  const fetchChannels = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await fetch('/api/channels')
      if (!res.ok) throw new Error("Erreur lors de la récupération des canaux")
      const payload = await res.json()
      setData(payload)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(message)
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    void fetchChannels()
  }, [])

  // Sync channels
  const handleSyncAll = async () => {
    setSyncing(true)
    try {
      const res = await fetch('/api/channels/sync', { method: 'POST' })
      if (!res.ok) throw new Error("La synchronisation a échoué")
      const payload = await res.json()
      setData(payload)
      toast.success("Synchronisation effectuée avec succès !")
      if (onRefreshStats) onRefreshStats()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(message)
    } finally {
      setSyncing(false)
    }
  }

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!label.trim()) {
      toast.error("Veuillez saisir un libellé.")
      return
    }
    if (type === 'email' && !emailAddress.trim()) {
      toast.error("Veuillez saisir une adresse e-mail.")
      return
    }

    setSubmitting(true)
    try {
      const res = await fetch('/api/channels/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          label,
          type,
          connector,
          email_address: type === 'email' ? emailAddress : undefined,
          org: org || 'personal'
        }),
      })

      if (!res.ok) {
        const errorText = await res.text()
        throw new Error(errorText || "Impossible d'ajouter le canal")
      }

      const payload = await res.json()
      setData(payload.cache || payload)
      toast.success(`Canal "${label}" ajouté et synchronisé !`)
      
      // Reset form & close
      setLabel('')
      setType('email')
      setConnector('gmail')
      setEmailAddress('')
      setOrg('personal')
      setModalOpen(false)
      
      if (onRefreshStats) onRefreshStats()
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(message)
    } finally {
      setSubmitting(false)
    }
  }

  // Adjust connector based on type selection
  useEffect(() => {
    if (type === 'email') {
      setConnector('gmail')
    } else if (type === 'whatsapp') {
      setConnector('evolution-api')
    } else if (type === 'slack') {
      setConnector('slack')
    } else if (type === 'telegram') {
      setConnector('telegram')
    }
  }, [type])

  const getConnectorBadgeColor = (conn: string) => {
    const c = conn.toLowerCase()
    if (c.includes('gmail')) return 'bg-red-500/10 text-red-500 border-red-500/20'
    if (c.includes('outlook')) return 'bg-blue-500/10 text-blue-500 border-blue-500/20'
    if (c.includes('evolution')) return 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20'
    if (c.includes('slack')) return 'bg-purple-500/10 text-purple-500 border-purple-500/20'
    if (c.includes('telegram')) return 'bg-sky-500/10 text-sky-500 border-sky-500/20'
    return 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20'
  }

  const getChannelGradient = (type: string) => {
    switch (type) {
      case 'email':
        return 'from-blue-600/10 to-indigo-600/5 hover:to-indigo-600/10 border-indigo-500/10 hover:border-indigo-500/30 shadow-indigo-500/5'
      case 'whatsapp':
        return 'from-emerald-600/10 to-teal-600/5 hover:to-teal-600/10 border-emerald-500/10 hover:border-emerald-500/30 shadow-emerald-500/5'
      case 'slack':
        return 'from-purple-600/10 to-pink-600/5 hover:to-pink-600/10 border-purple-500/10 hover:border-purple-500/30 shadow-purple-500/5'
      case 'telegram':
        return 'from-sky-600/10 to-blue-600/5 hover:to-blue-600/10 border-sky-500/10 hover:border-sky-500/30 shadow-sky-500/5'
      default:
        return 'from-zinc-600/10 to-zinc-600/5 hover:to-zinc-600/10 border-zinc-500/10'
    }
  }

  const humanizeReason = (reason?: string | null): string => {
    if (!reason) return ''
    const r = reason.toLowerCase()
    if (r.includes('gog_oauth_missing') || r.includes('credentials missing')) return "OAuth gog non configuré (lancez `gog auth credentials <client.json>`)"
    if (r.includes('gog_cli_not_installed')) return "CLI gog absente (installez `gog`)"
    if (r.includes('evolution_env_incomplete')) return "Variables Evolution manquantes (EVOLUTION_API_URL / API_KEY / INSTANCE)"
    if (r.includes('composio_not_authenticated') || r.includes('401')) return "Composio non authentifié (lancez `composio link <toolkit>`)"
    if (r.includes('composio_cli_not_installed')) return "CLI composio absente"
    if (r.includes('no_fetcher_for_type:slack')) return "Pas encore de connecteur Slack côté zab"
    if (r.startsWith('no_fetcher_for_type:')) return `Aucun connecteur pour ce type (${reason.split(':')[1]})`
    return reason.length > 160 ? reason.slice(0, 160) + '…' : reason
  }

  const renderStatusBadge = (chan: ChannelItem) => {
    const status = chan.status || 'ok'
    if (status === 'ok') {
      return (
        <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold border bg-emerald-50 border-emerald-200 shadow-xs" title="Canal connecté et synchronisé">
          <CheckCircle2 className="h-3 w-3 text-emerald-500" />
          <span className="text-emerald-700">Actif</span>
        </span>
      )
    }
    if (status === 'degraded') {
      const openConfig = () => {
        if (onOpenConnectorsConfig) onOpenConnectorsConfig(chan)
      }
      return (
        <button
          type="button"
          onClick={openConfig}
          className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-semibold shadow-xs transition hover:border-amber-300 hover:bg-amber-100/70"
          title={`${humanizeReason(chan.reason)} — ouvrir Connecteurs`}
          aria-label={`Configurer le canal ${chan.label}`}
        >
          <AlertTriangle className="h-3 w-3 text-amber-500" />
          <span className="text-amber-700">À configurer</span>
        </button>
      )
    }
    if (status === 'disabled') {
      return (
        <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold border bg-zinc-100 border-zinc-200 shadow-xs" title="Canal désactivé">
          <PauseCircle className="h-3 w-3 text-zinc-500" />
          <span className="text-zinc-600">Désactivé</span>
        </span>
      )
    }
    return (
      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold border bg-red-50 border-red-200 shadow-xs" title={humanizeReason(chan.reason)}>
        <AlertCircle className="h-3 w-3 text-red-500 animate-pulse" />
        <span className="text-red-700">Erreur</span>
      </span>
    )
  }

  const formatLastSynced = (dateStr?: string) => {
    if (!dateStr) return 'Jamais'
    try {
      const dt = new Date(dateStr)
      return dt.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
    } catch {
      return dateStr
    }
  }

  return (
    <div className="space-y-6">
      {/* Header Banner with Premium Aesthetics */}
      <div className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-linear-to-r from-zinc-900 via-zinc-800 to-zinc-950 p-6 text-white shadow-xl">
        <div className="absolute -top-24 -right-24 h-48 w-48 rounded-full bg-indigo-500/10 blur-3xl" />
        <div className="absolute -bottom-24 -left-24 h-48 w-48 rounded-full bg-emerald-500/10 blur-3xl" />
        
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-2 w-2 rounded-full bg-indigo-400 animate-pulse" />
              <p className="text-xs font-semibold uppercase tracking-wider text-indigo-300">Canaux de communication</p>
            </div>
            <h1 className="mt-1 text-2xl font-bold tracking-tight md:text-3xl">Gérez votre connectivité</h1>
            <p className="mt-2 max-w-xl text-sm text-zinc-300">
              Centralisez vos comptes e-mails, Slack, WhatsApp et Telegram. Zab agrège les messages clés et vous permet de les transformer en tâches actionnables.
            </p>
          </div>
          
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => setModalOpen(true)}
              className="bg-white text-zinc-950 hover:bg-zinc-100 shadow-lg cursor-pointer flex items-center gap-1.5 rounded-xl font-medium transition"
            >
              <HugeiconsIcon icon={Add01Icon} size={16} strokeWidth={2.5} />
              Nouveau canal
            </Button>
            
            <Button
              onClick={handleSyncAll}
              disabled={syncing}
              variant="outline"
              className="border-zinc-700 bg-zinc-800/50 text-white hover:bg-zinc-800 cursor-pointer flex items-center gap-1.5 rounded-xl font-medium transition"
            >
              {syncing ? (
                <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
              ) : (
                <HugeiconsIcon icon={RefreshIcon} size={16} className="text-indigo-400" />
              )}
              Synchroniser tout
            </Button>
          </div>
        </div>

        {data?.generated_at_utc && (
          <div className="mt-6 flex items-center gap-2 border-t border-zinc-800 pt-4 text-xs text-zinc-400">
            <span>Dernière synchronisation globale :</span>
            <span className="font-semibold text-zinc-300">{new Date(data.generated_at_utc).toLocaleString('fr-FR')}</span>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex h-48 items-center justify-center rounded-xl border border-zinc-100 bg-white/50 backdrop-blur-xs">
          <div className="flex flex-col items-center gap-2">
            <Loader2 className="h-8 w-8 animate-spin text-zinc-800" />
            <p className="text-sm font-medium text-zinc-500">Chargement de vos canaux de communication...</p>
          </div>
        </div>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-2">
          {data?.channels.map((chan) => (
            <Card
              key={chan.id}
              className={`relative overflow-hidden border bg-linear-to-b ${getChannelGradient(chan.type)} transition-all duration-300 hover:-translate-y-1 hover:shadow-lg rounded-xl`}
            >
              <div className="absolute top-0 right-0 p-3">
                {renderStatusBadge(chan)}
              </div>

              <CardHeader className="pb-3 pt-5">
                <div className="flex items-center gap-3">
                  <div className={`flex size-10 items-center justify-center rounded-xl bg-white shadow-md border border-zinc-100`}>
                    {chan.type === 'email' ? (
                      <HugeiconsIcon icon={Mail01Icon} size={20} className="text-indigo-600" />
                    ) : (
                      <HugeiconsIcon icon={MessageMultiple02Icon} size={20} className="text-emerald-600" />
                    )}
                  </div>
                  <div>
                    <CardTitle className="text-base font-bold tracking-tight text-zinc-900">
                      {chan.label}
                    </CardTitle>
                    <CardDescription className="text-xs text-zinc-500 mt-0.5 font-medium flex items-center gap-1.5">
                      <span>Org: </span>
                      <span className="uppercase text-indigo-600 bg-indigo-50 px-1.5 py-0.2 rounded text-[10px] font-bold">
                        {chan.org}
                      </span>
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4 pb-5 pt-0">
                {/* Hint d'état (reason) — caché si le canal est actif */}
                {chan.status && chan.status !== 'ok' && chan.reason && (
                  <div className={`rounded-lg px-3 py-2 text-[11px] font-medium border ${
                    chan.status === 'degraded'
                      ? 'bg-amber-50/70 border-amber-200/60 text-amber-800'
                      : chan.status === 'disabled'
                      ? 'bg-zinc-50 border-zinc-200/60 text-zinc-600'
                      : 'bg-red-50/70 border-red-200/60 text-red-800'
                  }`}>
                    {humanizeReason(chan.reason)}
                  </div>
                )}

                {/* Meta details */}
                <div className="text-xs space-y-1 text-zinc-600 font-medium">
                  {chan.email_address && (
                    <div className="flex justify-between border-b border-zinc-100/50 pb-1">
                      <span className="text-zinc-400">Adresse</span>
                      <span className="text-zinc-800 select-all">{chan.email_address}</span>
                    </div>
                  )}
                  <div className="flex justify-between border-b border-zinc-100/50 pb-1">
                    <span className="text-zinc-400">Connecteur</span>
                    <span className={`rounded px-1.5 py-0.2 border text-[10px] font-bold uppercase ${getConnectorBadgeColor(chan.connector)}`}>
                      {chan.connector}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Dernière synchro</span>
                    <span className="text-zinc-500">{formatLastSynced(chan.last_synced_at)}</span>
                  </div>
                </div>

                {/* Metrics Blocks */}
                {chan.type === 'email' ? (
                  <div className="grid grid-cols-3 gap-2 rounded-xl bg-white/60 p-2.5 shadow-inner border border-zinc-100/80">
                    <div className="text-center">
                      <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Non lus</p>
                      <p className="text-lg font-black text-indigo-600 mt-0.5">
                        {chan.sync_summary?.unread_count ?? 0}
                      </p>
                    </div>
                    <div className="text-center border-x border-zinc-100">
                      <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Aujourd'hui</p>
                      <p className="text-lg font-black text-zinc-800 mt-0.5">
                        {chan.sync_summary?.received_today ?? 0}
                      </p>
                    </div>
                    <div className="text-center">
                      <p className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">7 jours</p>
                      <p className="text-lg font-black text-zinc-800 mt-0.5">
                        {chan.sync_summary?.received_this_week ?? 0}
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-between rounded-xl bg-white/60 px-3 py-2.5 shadow-inner border border-zinc-100/80">
                    <span className="text-xs font-bold text-zinc-500">Messages non lus</span>
                    <span className={`inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-xs font-black ${
                      (chan.sync_summary?.unread_count ?? 0) > 0 ? 'bg-emerald-500 text-white animate-pulse' : 'bg-zinc-200 text-zinc-600'
                    }`}>
                      {chan.sync_summary?.unread_count ?? 0}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Modal / Dialog for Adding Channel */}
      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="sm:max-w-md bg-white border border-zinc-200 rounded-2xl shadow-2xl p-6">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-zinc-950 flex items-center gap-2">
              <HugeiconsIcon icon={Settings02Icon} size={20} className="text-indigo-600" />
              Ajouter un canal de communication
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="mt-4 space-y-4">
            {/* Label input */}
            <div className="space-y-1.5">
              <label htmlFor="chan-label" className="text-xs font-bold uppercase tracking-wider text-zinc-500">
                Nom d'affichage du canal *
              </label>
              <input
                id="chan-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="ex: Gmail Personnel, WhatsApp Client..."
                className="border-zinc-200 bg-zinc-50/50 w-full rounded-xl border px-3.5 py-2.5 text-sm font-medium text-zinc-900 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-4 focus:ring-indigo-500/10"
                required
              />
            </div>

            {/* Type selector */}
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <label htmlFor="chan-type" className="text-xs font-bold uppercase tracking-wider text-zinc-500">
                  Type de canal *
                </label>
                <select
                  id="chan-type"
                  value={type}
                  onChange={(e) => setType(e.target.value as 'email' | 'whatsapp' | 'slack' | 'telegram')}
                  className="border-zinc-200 bg-zinc-50/50 w-full rounded-xl border px-3.5 py-2.5 text-sm font-semibold text-zinc-900 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-4 focus:ring-indigo-500/10"
                >
                  <option value="email">📧 E-mail</option>
                  <option value="whatsapp">💬 WhatsApp</option>
                  <option value="slack">🗣️ Slack</option>
                  <option value="telegram">✈️ Telegram</option>
                </select>
              </div>

              {/* Organization selector */}
              <div className="space-y-1.5">
                <label htmlFor="chan-org" className="text-xs font-bold uppercase tracking-wider text-zinc-500">
                  Organisation associée *
                </label>
                <select
                  id="chan-org"
                  value={org}
                  onChange={(e) => setOrg(e.target.value)}
                  className="border-zinc-200 bg-zinc-50/50 w-full rounded-xl border px-3.5 py-2.5 text-sm font-semibold text-zinc-900 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-4 focus:ring-indigo-500/10"
                >
                  <option value="personal">👤 Personnel</option>
                  {orgs.map((o) => (
                    <option key={o.org} value={o.org}>
                      🏢 {o.org.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Email field (only visible for email type) */}
            {type === 'email' && (
              <div className="space-y-1.5">
                <label htmlFor="chan-email" className="text-xs font-bold uppercase tracking-wider text-zinc-500">
                  Adresse e-mail *
                </label>
                <input
                  id="chan-email"
                  type="email"
                  value={emailAddress}
                  onChange={(e) => setEmailAddress(e.target.value)}
                  placeholder="mehdi@example.com"
                  className="border-zinc-200 bg-zinc-50/50 w-full rounded-xl border px-3.5 py-2.5 text-sm font-medium text-zinc-900 outline-none transition focus:border-indigo-500 focus:bg-white focus:ring-4 focus:ring-indigo-500/10"
                  required
                />
              </div>
            )}

            {/* Connector summary display */}
            <div className="rounded-xl border border-zinc-100 bg-zinc-50 p-3 text-xs text-zinc-500 font-medium">
              <div className="flex justify-between items-center">
                <span>Connecteur qui sera utilisé :</span>
                <span className={`rounded-md px-1.5 py-0.5 border text-[10px] font-bold uppercase ${getConnectorBadgeColor(connector)}`}>
                  {connector}
                </span>
              </div>
              <p className="mt-1.5 text-[11px] text-zinc-400">
                La configuration du jeton d'authentification s'effectue dans l'onglet Connecteurs.
              </p>
            </div>

            {/* Action buttons */}
            <div className="flex justify-end gap-2 pt-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setModalOpen(false)}
                className="border-zinc-200 text-zinc-700 hover:bg-zinc-50 cursor-pointer rounded-xl font-semibold transition"
              >
                Annuler
              </Button>
              <Button
                type="submit"
                disabled={submitting}
                className="bg-zinc-900 text-white hover:bg-zinc-800 cursor-pointer rounded-xl font-semibold transition shadow-md flex items-center gap-1.5"
              >
                {submitting ? (
                  <Loader2 className="h-4 w-4 animate-spin text-white" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Confirmer l'ajout
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
