import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import {
  AlertCircle,
  AlertTriangle,
  Archive,
  Bot,
  CheckCircle2,
  ChevronRight,
  Circle,
  ClipboardList,
  ExternalLink,
  Inbox,
  Loader2,
  Mail,
  MessageCircle,
  MessagesSquare,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Tags,
} from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { LoadingState } from '@/components/ui/loading-state'

export type ChannelSyncSummary = {
  unread_count: number
  received_today?: number
  received_this_week?: number
}

export type ChannelItem = {
  id: string
  label: string
  type: 'email' | 'whatsapp' | 'slack' | 'telegram' | string
  connector: string
  org: string
  email_address?: string | null
  address?: string | null
  enabled: boolean
  status?: 'ok' | 'error' | 'pending' | 'degraded' | 'disabled'
  reason?: string | null
  last_synced_at?: string
  sync_summary?: ChannelSyncSummary
  auth?: Record<string, unknown>
  credentials?: Record<string, unknown>
  documentation?: string
}

type ChannelAction = {
  id: string
  channel_id: string
  channel_label: string
  type: string
  sender: string
  subject?: string
  content: string
  date: string
  url?: string
  org: string
  status: 'pending' | 'dismissed' | 'converted' | string
  obsidian_noted?: boolean
}

type ChannelsPayload = {
  generated_at_utc: string
  channels: ChannelItem[]
  action_items?: ChannelAction[]
  total_actions_count: number
}

type HermesDirectoryEntry = {
  id: string
  name: string
  type?: string
  thread_id?: string | null
  guild?: string
}

type HermesSnapshot = {
  home: string
  config_path: string
  config_present: boolean
  config_error?: string | null
  enabled: boolean
  default_org?: string | null
  channels: ChannelItem[]
  platform_toolsets: Record<string, string[]>
  platforms: Record<string, unknown>
  directory_path: string
  directory_present: boolean
  directory_error?: string | null
  directory_updated_at?: string | null
  directory_counts: Record<string, number>
  directory_platforms: Record<string, HermesDirectoryEntry[]>
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

const CHANNEL_TYPES = ['email', 'whatsapp', 'slack', 'telegram'] as const

function channelIcon(type: string) {
  if (type === 'email') return Mail
  if (type === 'slack') return MessagesSquare
  if (type === 'telegram') return MessagesSquare
  if (type === 'whatsapp') return MessageCircle
  return Inbox
}

function channelTone(type: string) {
  if (type === 'email') return 'bg-info/10 text-info border-info/35'
  if (type === 'whatsapp') return 'bg-succes/10 text-succes border-succes/35'
  if (type === 'slack') return 'bg-muted text-foreground border-border'
  if (type === 'telegram') return 'bg-info/10 text-info border-info/35'
  return 'bg-muted text-foreground border-border'
}

function connectorForType(type: string) {
  if (type === 'email') return 'gmail'
  if (type === 'whatsapp') return 'evolution-api'
  if (type === 'slack') return 'slack'
  if (type === 'telegram') return 'telegram'
  return type
}

function statusMeta(status?: ChannelItem['status']) {
  if (status === 'ok') return { label: 'Actif', icon: CheckCircle2, cls: 'bg-succes/10 text-succes border-succes/35' }
  if (status === 'degraded') return { label: 'À configurer', icon: AlertTriangle, cls: 'bg-alerte/10 text-alerte border-alerte/35' }
  if (status === 'disabled') return { label: 'Désactivé', icon: Circle, cls: 'bg-muted text-muted-foreground border-border' }
  return { label: 'Erreur', icon: AlertCircle, cls: 'bg-danger/10 text-danger border-danger/35' }
}

function formatDate(value?: string | null) {
  if (!value) return 'Jamais'
  try {
    return new Date(value).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return value
  }
}

function humanizeReason(reason?: string | null): string {
  if (!reason) return ''
  const r = reason.toLowerCase()
  if (r.includes('gog_oauth_missing') || r.includes('credentials missing')) return 'OAuth gog non configuré'
  if (r.includes('gog_cli_not_installed')) return 'CLI gog absente'
  if (r.includes('evolution_env_incomplete')) return 'Variables Evolution manquantes'
  if (r.includes('composio_not_authenticated') || r.includes('401')) return 'Composio non authentifié'
  if (r.includes('composio_cli_not_installed')) return 'CLI composio absente'
  if (r.includes('no_fetcher_for_type:slack')) return 'Fetcher Slack non branché côté Zab'
  if (r.startsWith('no_fetcher_for_type:')) return `Aucun fetcher pour ${reason.split(':')[1]}`
  return reason.length > 180 ? `${reason.slice(0, 180)}…` : reason
}

function channelAddress(channel: ChannelItem) {
  return channel.email_address || channel.address || '—'
}

function envKeys(channel: ChannelItem) {
  const source = channel.auth || channel.credentials || {}
  return Object.entries(source)
    .map(([key, value]) => (key.endsWith('_env') || key === 'token_env' || key === 'credentials_env' ? String(value) : null))
    .filter(Boolean) as string[]
}

function authEntries(channel: ChannelItem) {
  const source = channel.auth || channel.credentials || {}
  return Object.entries(source).filter(([, value]) => value !== undefined && value !== null && String(value).trim() !== '')
}

export function ChannelsView({ orgs = [], onRefreshStats, onOpenConnectorsConfig }: ChannelsViewProps) {
  const [data, setData] = useState<ChannelsPayload | null>(null)
  const [hermes, setHermes] = useState<HermesSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [type, setType] = useState<(typeof CHANNEL_TYPES)[number]>('email')
  const [connector, setConnector] = useState('gmail')
  const [emailAddress, setEmailAddress] = useState('')
  const [org, setOrg] = useState('personal')
  const [submitting, setSubmitting] = useState(false)
  const [actionBusyId, setActionBusyId] = useState<string | null>(null)

  const fetchChannels = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [channelsRes, hermesRes] = await Promise.all([
        fetch('/api/channels'),
        fetch('/api/channels/hermes'),
      ])
      if (!channelsRes.ok) throw new Error('Erreur lors de la récupération des canaux')
      const payload = (await channelsRes.json()) as ChannelsPayload
      setData(payload)
      if (!selectedId && payload.channels.length > 0) setSelectedId(payload.channels[0].id)
      if (hermesRes.ok) setHermes((await hermesRes.json()) as HermesSnapshot)
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => {
    void fetchChannels()
  }, [])

  useEffect(() => {
    setConnector(connectorForType(type))
  }, [type])

  const channels = data?.channels ?? []
  const actions = data?.action_items ?? []
  const pendingActions = actions.filter((action) => action.status === 'pending')
  const selected = channels.find((channel) => channel.id === selectedId) ?? channels[0]

  const summary = useMemo(() => {
    const active = channels.filter((channel) => channel.status === 'ok').length
    const degraded = channels.filter((channel) => channel.status === 'degraded').length
    const unread = channels.reduce((sum, channel) => sum + (channel.sync_summary?.unread_count ?? 0), 0)
    const platforms = Array.from(new Set(channels.map((channel) => channel.type))).length
    return { active, degraded, unread, platforms }
  }, [channels])

  const hermesDirectoryRows = useMemo(() => {
    if (!hermes?.directory_platforms) return []
    return Object.entries(hermes.directory_platforms).flatMap(([platform, entries]) =>
      (Array.isArray(entries) ? entries.slice(0, 8) : []).map((entry) => ({ platform, ...entry })),
    )
  }, [hermes])

  const handleSyncAll = async () => {
    setSyncing(true)
    try {
      const res = await fetch('/api/channels/sync', { method: 'POST' })
      if (!res.ok) throw new Error('La synchronisation a échoué')
      setData((await res.json()) as ChannelsPayload)
      toast.success('Synchronisation effectuée')
      if (onRefreshStats) onRefreshStats()
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setSyncing(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!label.trim()) {
      toast.error('Veuillez saisir un libellé.')
      return
    }
    if (type === 'email' && !emailAddress.trim()) {
      toast.error('Veuillez saisir une adresse e-mail.')
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
          org: org || 'personal',
        }),
      })
      if (!res.ok) throw new Error(await res.text())
      const payload = await res.json()
      setData((payload.cache || payload) as ChannelsPayload)
      toast.success(`Canal "${label}" ajouté`)
      setLabel('')
      setType('email')
      setEmailAddress('')
      setOrg('personal')
      setModalOpen(false)
      if (onRefreshStats) onRefreshStats()
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  const updateAction = async (action: ChannelAction, mode: 'dismiss' | 'obsidian-convert') => {
    setActionBusyId(action.id)
    try {
      const res = await fetch(`/api/channels/actions/${encodeURIComponent(action.id)}/${mode}`, { method: 'POST' })
      if (!res.ok) throw new Error(await res.text())
      setData((await res.json()) as ChannelsPayload)
      toast.success(mode === 'dismiss' ? 'Action archivée' : 'Action convertie en tâche')
      if (onRefreshStats) onRefreshStats()
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setActionBusyId(null)
    }
  }

  const StatusIcon = statusMeta(selected?.status).icon

  return (
    <section className="space-y-5" data-testid="channels-view">
      {loading && !data ? <LoadingState label="Chargement des canaux…" /> : null}
      <header className="flex flex-col gap-3 border-b pb-4 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-muted-foreground text-sm font-medium uppercase">Communication</p>
          <h2 className="text-3xl font-semibold tracking-tight">Canaux</h2>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
            Configuration Zab, état de synchro et annuaire Hermes des plateformes joignables.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => void fetchChannels()} disabled={loading || syncing}>
            <RefreshCw className={cn('mr-2 size-4', loading ? 'animate-spin' : '')} />
            Recharger
          </Button>
          <Button type="button" variant="outline" onClick={() => setModalOpen(true)}>
            <Plus className="mr-2 size-4" />
            Nouveau canal
          </Button>
          <Button type="button" onClick={() => void handleSyncAll()} disabled={syncing}>
            {syncing ? <Loader2 className="mr-2 size-4 animate-spin" /> : <RefreshCw className="mr-2 size-4" />}
            Synchroniser
          </Button>
        </div>
      </header>

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Canaux" value={channels.length} />
        <Metric label="Actifs" value={summary.active} tone="text-succes" />
        <Metric label="À configurer" value={summary.degraded} tone="text-alerte" />
        <Metric label="Actions" value={data?.total_actions_count ?? pendingActions.length} tone="text-info" />
      </div>

      {loading ? (
        <div className="flex h-48 items-center justify-center rounded-lg border">
          <Loader2 className="mr-2 size-5 animate-spin" />
          <span className="text-muted-foreground text-sm">Chargement des canaux...</span>
        </div>
      ) : (
        <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.4fr)]">
          <Card className="overflow-hidden">
            <CardHeader className="border-b pb-3">
              <CardTitle className="text-base">Canaux Zab</CardTitle>
              <CardDescription>{summary.platforms} plateforme(s) · {summary.unread} non lu(s)</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {channels.length === 0 ? (
                <div className="p-4 text-sm text-muted-foreground">Aucun canal configuré.</div>
              ) : (
                <div className="divide-y">
                  {channels.map((channel) => (
                    <ChannelRow
                      key={channel.id}
                      channel={channel}
                      active={selected?.id === channel.id}
                      onClick={() => setSelectedId(channel.id)}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <div className="space-y-5">
            {selected ? (
              <Card>
                <CardHeader className="border-b">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={cn('inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium', channelTone(selected.type))}>
                          {selected.type}
                        </span>
                        <span className={cn('inline-flex items-center rounded-md border px-2 py-1 text-xs font-medium', statusMeta(selected.status).cls)}>
                          <StatusIcon className="mr-1 size-3.5" />
                          {statusMeta(selected.status).label}
                        </span>
                      </div>
                      <CardTitle className="mt-3 truncate text-xl">{selected.label}</CardTitle>
                      <CardDescription className="mt-1 font-mono text-xs">{selected.id}</CardDescription>
                    </div>
                    <div className="flex gap-2">
                      <Button type="button" variant="outline" size="sm" onClick={() => onOpenConnectorsConfig?.(selected)}>
                        <Settings className="mr-2 size-4" />
                        Connecteur
                      </Button>
                      {selected.documentation ? (
                        <a href={selected.documentation} target="_blank" rel="noreferrer">
                          <Button type="button" variant="outline" size="sm">
                            <ExternalLink className="mr-2 size-4" />
                            Docs
                          </Button>
                        </a>
                      ) : null}
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-5 pt-5">
                  {selected.status && selected.status !== 'ok' && selected.reason ? (
                    <div className="rounded-lg border border-alerte/35 bg-alerte/10 px-3 py-2 text-sm text-alerte">
                      {humanizeReason(selected.reason)}
                    </div>
                  ) : null}

                  <div className="grid gap-3 md:grid-cols-3">
                    <InfoBlock label="Connecteur" value={selected.connector} />
                    <InfoBlock label="Organisation" value={selected.org} />
                    <InfoBlock label="Adresse" value={channelAddress(selected)} />
                    <InfoBlock label="Dernière synchro" value={formatDate(selected.last_synced_at)} />
                    <InfoBlock label="Non lus" value={String(selected.sync_summary?.unread_count ?? 0)} />
                    <InfoBlock label="Cette semaine" value={String(selected.sync_summary?.received_this_week ?? 0)} />
                  </div>

                  <div className="grid gap-4 lg:grid-cols-2">
                    <section className="rounded-lg border p-3">
                      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                        <ShieldCheck className="size-4 text-muted-foreground" />
                        Auth et variables
                      </div>
                      {authEntries(selected).length > 0 ? (
                        <div className="space-y-2">
                          {authEntries(selected).map(([key, value]) => (
                            <div key={key} className="flex items-center justify-between gap-3 text-xs">
                              <span className="text-muted-foreground">{key}</span>
                              <code className="max-w-52 truncate rounded bg-muted px-1.5 py-0.5">{String(value)}</code>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">Aucun bloc auth détaillé dans la config Zab.</p>
                      )}
                      {envKeys(selected).length > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-1">
                          {envKeys(selected).map((key) => <Badge key={key}>{key}</Badge>)}
                        </div>
                      ) : null}
                    </section>

                    <section className="rounded-lg border p-3">
                      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                        <ClipboardList className="size-4 text-muted-foreground" />
                        Actions de ce canal
                      </div>
                      <div className="space-y-2">
                        {pendingActions.filter((action) => action.channel_id === selected.id).slice(0, 4).map((action) => (
                          <ActionRow key={action.id} action={action} busy={actionBusyId === action.id} onUpdate={updateAction} />
                        ))}
                        {pendingActions.filter((action) => action.channel_id === selected.id).length === 0 ? (
                          <p className="text-sm text-muted-foreground">Aucune action en attente.</p>
                        ) : null}
                      </div>
                    </section>
                  </div>
                </CardContent>
              </Card>
            ) : null}

            <Card>
              <CardHeader className="border-b">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">Hermes channels</CardTitle>
                    <CardDescription>
                      {hermes?.config_present ? hermes.config_path : 'Config Hermes introuvable'}
                    </CardDescription>
                  </div>
                  <span className={cn('rounded-md border px-2 py-1 text-xs font-medium', hermes?.enabled ? 'border-succes/35 bg-succes/10 text-succes' : 'border-border bg-muted text-muted-foreground')}>
                    {hermes?.enabled ? 'enabled' : 'disabled'}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="grid gap-4 pt-5 lg:grid-cols-[1fr_1.2fr]">
                <section>
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                    <Bot className="size-4 text-muted-foreground" />
                    Plateformes déclarées
                  </div>
                  <div className="space-y-2">
                    {(hermes?.channels ?? []).map((channel) => (
                      <HermesChannel key={channel.id} channel={channel} toolsets={hermes?.platform_toolsets?.[channel.type] ?? []} count={hermes?.directory_counts?.[channel.type] ?? 0} />
                    ))}
                    {(hermes?.channels ?? []).length === 0 ? (
                      <p className="text-sm text-muted-foreground">Aucun canal Hermes déclaré.</p>
                    ) : null}
                  </div>
                </section>

                <section>
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                    <Tags className="size-4 text-muted-foreground" />
                    Annuaire joignable
                  </div>
                  <div className="max-h-72 overflow-auto rounded-lg border">
                    {hermesDirectoryRows.length > 0 ? hermesDirectoryRows.map((entry) => (
                      <div key={`${entry.platform}:${entry.id}`} className="flex items-center justify-between gap-3 border-b px-3 py-2 text-sm last:border-b-0">
                        <div className="min-w-0">
                          <div className="truncate font-medium">{entry.name}</div>
                          <div className="text-muted-foreground truncate font-mono text-xs">{entry.id}</div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          <Badge>{entry.platform}</Badge>
                          {entry.thread_id ? <Badge>topic {entry.thread_id}</Badge> : null}
                        </div>
                      </div>
                    )) : (
                      <div className="p-3 text-sm text-muted-foreground">Aucune entrée dans `channel_directory.json`.</div>
                    )}
                  </div>
                  {hermes?.directory_updated_at ? (
                    <p className="text-muted-foreground mt-2 text-xs">Mis à jour : {formatDate(hermes.directory_updated_at)}</p>
                  ) : null}
                </section>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {pendingActions.length > 0 ? (
        <Card>
          <CardHeader className="border-b">
            <CardTitle className="text-base">Actions multi-canaux</CardTitle>
            <CardDescription>{pendingActions.length} message(s) à traiter</CardDescription>
          </CardHeader>
          <CardContent className="divide-y p-0">
            {pendingActions.slice(0, 8).map((action) => (
              <ActionRow key={action.id} action={action} busy={actionBusyId === action.id} onUpdate={updateAction} wide />
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Ajouter un canal</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Nom d’affichage">
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Gmail Personnel"
                className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                required
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Type">
                <select
                  value={type}
                  onChange={(e) => setType(e.target.value as (typeof CHANNEL_TYPES)[number])}
                  className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                >
                  {CHANNEL_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </Field>
              <Field label="Organisation">
                <select
                  value={org}
                  onChange={(e) => setOrg(e.target.value)}
                  className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                >
                  <option value="personal">personal</option>
                  {orgs.map((item) => <option key={item.org} value={item.org}>{item.org}</option>)}
                </select>
              </Field>
            </div>
            {type === 'email' ? (
              <Field label="Adresse e-mail">
                <input
                  type="email"
                  value={emailAddress}
                  onChange={(e) => setEmailAddress(e.target.value)}
                  placeholder="mehdi@example.com"
                  className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
                  required
                />
              </Field>
            ) : null}
            <div className="rounded-lg border bg-muted/40 p-3 text-sm">
              Connecteur: <code className="font-mono">{connector}</code>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setModalOpen(false)}>Annuler</Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Plus className="mr-2 size-4" />}
                Ajouter
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  )
}

function Metric({ label, value, tone = '' }: { label: string; value: number | string; tone?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className={cn('text-3xl', tone)}>{value}</CardTitle>
      </CardHeader>
    </Card>
  )
}

function InfoBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div className="mt-1 truncate text-sm font-medium">{value}</div>
    </div>
  )
}

function Badge({ children }: { children: ReactNode }) {
  return <span className="rounded border bg-muted px-1.5 py-0.5 text-[11px] font-medium">{children}</span>
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-muted-foreground text-xs font-medium uppercase">{label}</span>
      {children}
    </label>
  )
}

function ChannelRow({ channel, active, onClick }: { channel: ChannelItem; active: boolean; onClick: () => void }) {
  const Icon = channelIcon(channel.type)
  const meta = statusMeta(channel.status)
  const StatusIcon = meta.icon
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn('flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-muted/50', active && 'bg-muted')}
    >
      <span className={cn('flex size-9 items-center justify-center rounded-lg border', channelTone(channel.type))}>
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">{channel.label}</span>
        <span className="text-muted-foreground mt-0.5 block truncate text-xs">{channel.connector} · {channel.org}</span>
      </span>
      <span className={cn('inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px]', meta.cls)}>
        <StatusIcon className="mr-1 size-3" />
        {channel.sync_summary?.unread_count ?? 0}
      </span>
      <ChevronRight className="text-muted-foreground size-4" />
    </button>
  )
}

function HermesChannel({ channel, toolsets, count }: { channel: ChannelItem; toolsets: string[]; count: number }) {
  const Icon = channelIcon(channel.type)
  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-start gap-3">
        <span className={cn('flex size-8 items-center justify-center rounded-lg border', channelTone(channel.type))}>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <div className="truncate text-sm font-medium">{channel.label}</div>
            <span className={cn('rounded-md border px-1.5 py-0.5 text-[11px]', channel.enabled ? 'bg-succes/10 text-succes border-succes/35' : 'bg-muted text-muted-foreground border-border')}>
              {channel.enabled ? 'on' : 'off'}
            </span>
          </div>
          <div className="text-muted-foreground mt-0.5 truncate font-mono text-xs">{channel.id} · {channel.connector}</div>
          <div className="mt-2 flex flex-wrap gap-1">
            <Badge>{count} route(s)</Badge>
            {toolsets.map((toolset) => <Badge key={toolset}>{toolset}</Badge>)}
          </div>
        </div>
      </div>
    </div>
  )
}

function ActionRow({ action, busy, onUpdate, wide = false }: { action: ChannelAction; busy: boolean; onUpdate: (action: ChannelAction, mode: 'dismiss' | 'obsidian-convert') => Promise<void>; wide?: boolean }) {
  return (
    <div className={cn('space-y-2', wide ? 'p-4' : 'rounded-lg border p-3')}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{action.subject || 'Action sans titre'}</div>
          <div className="text-muted-foreground mt-0.5 truncate text-xs">{action.sender} · {action.channel_label} · {formatDate(action.date)}</div>
        </div>
        <Badge>{action.type}</Badge>
      </div>
      <p className="text-muted-foreground line-clamp-2 text-sm">{action.content}</p>
      <div className="flex flex-wrap gap-2">
        {action.url ? (
          <a href={action.url} target="_blank" rel="noreferrer">
            <Button type="button" variant="outline" size="sm">
              <ExternalLink className="mr-2 size-4" />
              Ouvrir
            </Button>
          </a>
        ) : null}
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void onUpdate(action, 'obsidian-convert')}>
          {busy ? <Loader2 className="mr-2 size-4 animate-spin" /> : <ClipboardList className="mr-2 size-4" />}
          Tâche
        </Button>
        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void onUpdate(action, 'dismiss')}>
          <Archive className="mr-2 size-4" />
          Archiver
        </Button>
      </div>
    </div>
  )
}
