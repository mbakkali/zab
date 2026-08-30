import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Building2,
  CalendarClock,
  Contact,
  ExternalLink,
  Mail,
  MessageCircle,
  MessagesSquare,
  Mic,
  RefreshCw,
  Smartphone,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useMachine } from '@/components/machine-badge'
import { LoadingState } from '@/components/ui/loading-state'

type Channel = {
  channel_id: string
  channel_type?: string
  label?: string
  tool_id?: string
  account?: string
  last_check_status?: string
  last_check_reason?: string
}

type WorkstreamRef = { id: string; label: string; count: number }
type SourceRef = { source: string; count: number }

type Organization = {
  organization_id: string
  organization_label: string
  event_count: number
  sources: SourceRef[]
  workstreams: WorkstreamRef[]
  last_activity?: string | null
}

type TimelineEvent = {
  event_id?: string
  timestamp?: string
  source?: string
  channel_id?: string
  direction?: string
  medium?: string
  source_url?: string
  source_account?: string
  title?: string
  snippet?: string
  body?: string | null
  actor?: { display_name?: string; email?: string | null; role?: string }
  client_workstream_id?: string
}

type InteractionsViewProps = {
  onOpenTool?: (toolId: string) => void
}

type SourceMeta = {
  label: string
  icon: LucideIcon
  /** bubble / badge accent classes */
  badge: string
  dot: string
}

const SOURCE_META: Record<string, SourceMeta> = {
  gmail: {
    label: 'Gmail',
    icon: Mail,
    badge: 'border-danger/35 bg-danger/10 text-danger',
    dot: 'bg-danger/10',
  },
  calendar: {
    label: 'Calendar',
    icon: CalendarClock,
    badge: 'border-info/35 bg-info/10 text-info',
    dot: 'bg-info/10',
  },
  fireflies: {
    label: 'Fireflies',
    icon: Mic,
    badge: 'border-alerte/35 bg-alerte/10 text-alerte',
    dot: 'bg-alerte/10',
  },
  whatsapp: {
    label: 'WhatsApp',
    icon: MessageCircle,
    badge: 'border-succes/35 bg-succes/10 text-succes',
    dot: 'bg-succes/10',
  },
  ios_messages: {
    label: 'iMessage',
    icon: Smartphone,
    badge: 'border-info/35 bg-info/10 text-info',
    dot: 'bg-info/10',
  },
  attio: {
    label: 'Attio',
    icon: Contact,
    badge: 'border-border bg-muted text-foreground',
    dot: 'bg-secondary',
  },
}

const DEFAULT_META: SourceMeta = {
  label: 'Autre',
  icon: MessagesSquare,
  badge: 'border-border bg-muted text-muted-foreground',
  dot: 'bg-secondary',
}

const SNIPPET_LIMIT = 600

function messageContent(event: TimelineEvent): string {
  const body = (event.body || '').trim()
  if (body) return body
  const snippet = (event.snippet || '').trim()
  if (snippet && snippet !== (event.title || '').trim()) return snippet
  return ''
}

function sourceMeta(source?: string, channelType?: string): SourceMeta {
  const s = (source || '').toLowerCase()
  if (SOURCE_META[s]) return SOURCE_META[s]
  const t = (channelType || '').toLowerCase()
  if (SOURCE_META[t]) return SOURCE_META[t]
  if (s.includes('mail')) return SOURCE_META.gmail
  if (s.includes('calendar')) return SOURCE_META.calendar
  if (s.includes('fireflies') || s.includes('meeting')) return SOURCE_META.fireflies
  if (s.includes('whatsapp') || s.includes('evolution')) return SOURCE_META.whatsapp
  if (s.includes('imessage') || s.includes('ios')) return SOURCE_META.ios_messages
  if (s.includes('attio')) return SOURCE_META.attio
  return DEFAULT_META
}

async function apiJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json() as Promise<T>
}

/* Une source qui ne PEUT PAS exister ici n'est pas en panne.
   iMessage lit `~/Library/Messages/chat.db` : sur la VM le canal remonte en
   `error`, et l'écran affichait une pastille rouge sans dire que le geste de
   réparation n'existe pas. `/api/machine` liste ces sources ; on les marque
   « hors machine » et on les sort du décompte des erreurs. */
function horsMachine(channel: Channel, motifs: string[]): boolean {
  // Les trois identifiants, pas un seul : le canal iMessage porte
  // `channel_type: ios_messages` ET `channel_id: imessage-local`. Ne regarder
  // que `channel_type` le laissait passer pour une panne.
  const cle = `${channel.channel_type ?? ''} ${channel.channel_id ?? ''} ${channel.label ?? ''}`.toLowerCase()
  return motifs.some((m) => cle.includes(m))
}

function statusTone(status?: string): string {
  if (status === 'ok') return 'border-succes/35 bg-succes/10 text-succes'
  if (status === 'degraded') return 'border-alerte/35 bg-alerte/10 text-alerte'
  if (status === 'error') return 'border-danger/35 bg-danger/10 text-danger'
  return 'border-border bg-muted text-muted-foreground'
}

function cleanActor(name?: string): string {
  if (!name) return 'Inconnu'
  const stripped = name.replace(/<[^>]+>/, '').replace(/"/g, '').trim()
  return stripped || name
}

function formatDay(ts?: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatTime(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

function isOutbound(event: TimelineEvent): boolean {
  const dir = (event.direction || '').toLowerCase()
  if (dir === 'outbound') return true
  const who = (event.actor?.email || event.actor?.display_name || '').toLowerCase()
  return who.includes('mehdi@') || who.includes('upfundpro') || who.includes('flowmetrik')
}

function SourceBadge({ source, channelType }: { source?: string; channelType?: string }) {
  const meta = sourceMeta(source, channelType)
  const Icon = meta.icon
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] font-medium',
        meta.badge,
      )}
    >
      <Icon className="h-3 w-3" />
      {meta.label}
    </span>
  )
}

export function InteractionsView({ onOpenTool }: InteractionsViewProps) {
  const machine = useMachine()
  const sourcesAbsentes = useMemo(
    () => (machine?.sources_indisponibles ?? []).flatMap((s) => s.motifs ?? [s.source]),
    [machine],
  )
  const [channels, setChannels] = useState<Channel[]>([])
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [selectedOrg, setSelectedOrg] = useState<string | null>(null)
  const [events, setEvents] = useState<TimelineEvent[]>([])
  const [wsFilter, setWsFilter] = useState<string | null>(null)
  const [mediumFilter, setMediumFilter] = useState<string | null>(null)
  const [orgQuery, setOrgQuery] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(false)
  const [threadLoading, setThreadLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (liveChannelCheck = false) => {
    setLoading(true)
    setError(null)
    try {
      const [channelResult, orgResult] = await Promise.allSettled([
        apiJson<{ channels: Channel[] }>(`/api/channels/check?live=${liveChannelCheck ? 'true' : 'false'}`),
        apiJson<{ organizations: Organization[] }>('/api/interactions/organizations'),
      ])
      const errors: string[] = []
      if (channelResult.status === 'fulfilled') {
        setChannels(channelResult.value.channels || [])
      } else {
        setChannels([])
        errors.push(channelResult.reason instanceof Error ? channelResult.reason.message : String(channelResult.reason))
      }
      if (orgResult.status === 'fulfilled') {
        const orgs = orgResult.value.organizations || []
        setOrganizations(orgs)
        setSelectedOrg((prev) => prev ?? orgs[0]?.organization_id ?? null)
      } else {
        setOrganizations([])
        setSelectedOrg(null)
        errors.push(orgResult.reason instanceof Error ? orgResult.reason.message : String(orgResult.reason))
      }
      setError(errors.length ? errors.join(' · ') : null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(false)
  }, [load])

  useEffect(() => {
    if (!selectedOrg) {
      setEvents([])
      return
    }
    let cancelled = false
    setThreadLoading(true)
    setWsFilter(null)
    setMediumFilter(null)
    setExpanded(new Set())
    apiJson<{ events: TimelineEvent[]; enrichment?: { fetched?: number; skipped?: number } }>(
      `/api/interactions/timeline?organization=${encodeURIComponent(selectedOrg)}&limit=300&enrich=true`,
    )
      .then((payload) => {
        if (cancelled) return
        const sorted = [...(payload.events || [])].sort((a, b) =>
          String(a.timestamp || '').localeCompare(String(b.timestamp || '')),
        )
        setEvents(sorted)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setThreadLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedOrg])

  const filteredOrgs = useMemo(() => {
    const q = orgQuery.trim().toLowerCase()
    if (!q) return organizations
    return organizations.filter((o) => o.organization_label.toLowerCase().includes(q))
  }, [organizations, orgQuery])

  const activeOrg = useMemo(
    () => organizations.find((o) => o.organization_id === selectedOrg) ?? null,
    [organizations, selectedOrg],
  )

  const mediumOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const e of events) {
      const src = (e.source || 'unknown').toLowerCase()
      counts.set(src, (counts.get(src) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1])
  }, [events])

  const visibleEvents = useMemo(() => {
    return events.filter((e) => {
      if (wsFilter && e.client_workstream_id !== wsFilter) return false
      if (mediumFilter && (e.source || '').toLowerCase() !== mediumFilter) return false
      return true
    })
  }, [events, wsFilter, mediumFilter])

  const groupedByDay = useMemo(() => {
    const groups: { day: string; items: TimelineEvent[] }[] = []
    for (const event of visibleEvents) {
      const day = formatDay(event.timestamp)
      const last = groups[groups.length - 1]
      if (last && last.day === day) last.items.push(event)
      else groups.push({ day, items: [event] })
    }
    return groups
  }, [visibleEvents])

  const toggleExpanded = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  return (
    <section className="space-y-6" data-testid="interactions-view">
      {loading && organizations.length === 0 && events.length === 0 ? (
        <LoadingState label="Chargement des interactions…" />
      ) : null}
      <div>
        <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Conversation Ledger</p>
        <h1 className="text-3xl font-semibold tracking-tight">Interactions</h1>
        <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
          Regroupe les échanges d'un client dans un fil unique, toutes sources confondues (Gmail, Calendar,
          Fireflies, WhatsApp, iMessage, Attio…). Cliquez sur un channel pour ouvrir sa fiche dans le Tools Catalog.
        </p>
      </div>

      {error ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Erreur de chargement</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <div>
            <CardTitle>Channels connectés</CardTitle>
            <CardDescription>Bindings Tool Catalog et dernier statut de vérification.</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => void load(true)} disabled={loading}>
            <RefreshCw className={cn('mr-2 h-4 w-4', loading ? 'animate-spin' : '')} />
            Rafraîchir
          </Button>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="channels-grid">
            {channels.map((channel) => {
              const meta = sourceMeta(channel.channel_type, channel.channel_type)
              const Icon = meta.icon
              const absente = horsMachine(channel, sourcesAbsentes)
              return (
                <button
                  key={channel.channel_id}
                  type="button"
                  onClick={() => channel.tool_id && onOpenTool?.(channel.tool_id)}
                  disabled={!channel.tool_id}
                  className="group hover:border-primary/50 hover:bg-accent/40 flex flex-col gap-2 rounded-lg border p-3 text-left transition disabled:cursor-default"
                  data-testid="channel-card"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={cn('flex h-6 w-6 items-center justify-center rounded-md', meta.badge)}>
                        <Icon className="h-3.5 w-3.5" />
                      </span>
                      <span className="text-sm font-medium">{channel.label || channel.channel_id}</span>
                    </div>
                    <span
                      title={
                        absente
                          ? machine?.sources_indisponibles.find((s) =>
                              horsMachine(channel, s.motifs ?? [s.source]),
                            )?.raison
                          : channel.last_check_reason
                      }
                      className={cn(
                        'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium',
                        absente
                          ? 'border-border bg-muted text-muted-foreground'
                          : statusTone(channel.last_check_status),
                      )}
                    >
                      {absente
                        ? `hors ${machine?.libelle ?? 'machine'}`
                        : channel.last_check_status || 'unknown'}
                    </span>
                  </div>
                  <div className="text-muted-foreground text-xs">{channel.account || '—'}</div>
                  {channel.tool_id ? (
                    <div className="text-muted-foreground flex items-center gap-1 text-[11px] group-hover:text-primary">
                      <ExternalLink className="h-3 w-3" />
                      <code className="font-mono">{channel.tool_id}</code>
                    </div>
                  ) : null}
                </button>
              )
            })}
            {!channels.length && !loading ? (
              <p className="text-muted-foreground text-sm">Aucun channel configuré.</p>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Inbox par entreprise</CardTitle>
          <CardDescription>
            Sélectionnez un client pour voir son fil d'échanges cross-plateformes, ordonné dans le temps.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
            {/* Company list */}
            <div className="flex flex-col gap-2" data-testid="org-list">
              <input
                type="search"
                value={orgQuery}
                onChange={(e) => setOrgQuery(e.target.value)}
                placeholder="Rechercher une entreprise…"
                className="border-input bg-background rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring/40"
              />
              <div className="max-h-[560px] space-y-1 overflow-y-auto pr-1">
                {filteredOrgs.map((org) => {
                  const active = org.organization_id === selectedOrg
                  return (
                    <button
                      key={org.organization_id}
                      type="button"
                      onClick={() => setSelectedOrg(org.organization_id)}
                      className={cn(
                        'flex w-full flex-col gap-1 rounded-lg border px-3 py-2 text-left transition',
                        active ? 'border-primary bg-accent' : 'hover:bg-accent/50',
                      )}
                      data-testid="org-item"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-sm font-medium">
                          <Building2 className="text-muted-foreground h-4 w-4" />
                          {org.organization_label}
                        </span>
                        <span className="text-muted-foreground text-xs">{org.event_count}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-1">
                        {org.sources.map((s) => {
                          const meta = sourceMeta(s.source)
                          const Icon = meta.icon
                          return (
                            <span
                              key={s.source}
                              className={cn(
                                'inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px]',
                                meta.badge,
                              )}
                              title={`${s.source}: ${s.count}`}
                            >
                              <Icon className="h-3 w-3" />
                              {s.count}
                            </span>
                          )
                        })}
                      </div>
                      <div className="text-muted-foreground text-[10px]">
                        Dernier échange : {formatDay(org.last_activity)}
                      </div>
                    </button>
                  )
                })}
                {!filteredOrgs.length ? (
                  <p className="text-muted-foreground px-2 py-4 text-sm">Aucune entreprise indexée.</p>
                ) : null}
              </div>
            </div>

            {/* Chat thread */}
            <div className="flex min-h-[400px] flex-col rounded-lg border" data-testid="org-thread">
              {activeOrg ? (
                <>
                  <div className="space-y-2 border-b px-4 py-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-semibold">{activeOrg.organization_label}</div>
                        <div className="text-muted-foreground text-xs">
                          {visibleEvents.length} / {events.length} échange(s)
                        </div>
                      </div>
                      {activeOrg.workstreams.length ? (
                        <div className="flex flex-wrap gap-1">
                          <button
                            type="button"
                            onClick={() => setWsFilter(null)}
                            className={cn(
                              'rounded-full border px-2 py-0.5 text-[11px]',
                              wsFilter === null ? 'border-primary bg-accent' : 'hover:bg-accent/50',
                            )}
                          >
                            Tous sujets
                          </button>
                          {activeOrg.workstreams.map((ws) => (
                            <button
                              key={ws.id}
                              type="button"
                              onClick={() => setWsFilter((prev) => (prev === ws.id ? null : ws.id))}
                              className={cn(
                                'rounded-full border px-2 py-0.5 text-[11px]',
                                wsFilter === ws.id ? 'border-primary bg-accent' : 'hover:bg-accent/50',
                              )}
                            >
                              {ws.label} · {ws.count}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>

                    {/* Medium filter */}
                    <div className="flex flex-wrap items-center gap-1" data-testid="medium-filter">
                      <span className="text-muted-foreground mr-1 text-[11px]">Medium :</span>
                      <button
                        type="button"
                        onClick={() => setMediumFilter(null)}
                        className={cn(
                          'rounded-full border px-2 py-0.5 text-[11px]',
                          mediumFilter === null ? 'border-primary bg-accent' : 'hover:bg-accent/50',
                        )}
                      >
                        Tous
                      </button>
                      {mediumOptions.map(([src, count]) => {
                        const meta = sourceMeta(src)
                        const Icon = meta.icon
                        const active = mediumFilter === src
                        return (
                          <button
                            key={src}
                            type="button"
                            onClick={() => setMediumFilter((prev) => (prev === src ? null : src))}
                            className={cn(
                              'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]',
                              active ? meta.badge : 'hover:bg-accent/50',
                            )}
                          >
                            <span className={cn('h-2 w-2 rounded-full', meta.dot)} />
                            <Icon className="h-3 w-3" />
                            {meta.label} · {count}
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4" style={{ maxHeight: 560 }}>
                    {threadLoading ? (
                      <p className="text-muted-foreground text-sm">Chargement du fil et des contenus Gmail…</p>
                    ) : null}
                    {!threadLoading && !visibleEvents.length ? (
                      <p className="text-muted-foreground text-sm">Aucun échange pour ce filtre.</p>
                    ) : null}
                    {groupedByDay.map((group) => (
                      <div key={group.day} className="space-y-3">
                        <div className="flex items-center justify-center">
                          <span className="text-muted-foreground bg-muted rounded-full px-2 py-0.5 text-[10px]">
                            {group.day}
                          </span>
                        </div>
                        {group.items.map((event, idx) => {
                          const out = isOutbound(event)
                          const meta = sourceMeta(event.source)
                          const id = event.event_id || `${event.timestamp}-${idx}`
                          const content = messageContent(event)
                          const isLong = content.length > SNIPPET_LIMIT
                          const isOpen = expanded.has(id)
                          const shownContent = isLong && !isOpen ? `${content.slice(0, SNIPPET_LIMIT)}…` : content
                          const hasSubject = Boolean(event.title && event.title !== content.slice(0, 120))
                          return (
                            <div
                              key={id}
                              className={cn('flex', out ? 'justify-end' : 'justify-start')}
                              data-testid="thread-message"
                            >
                              <div
                                className={cn(
                                  'max-w-[80%] rounded-2xl border px-3 py-2 text-sm',
                                  out
                                    ? 'bg-primary/10 border-primary/20 rounded-br-sm'
                                    : 'bg-muted/60 rounded-bl-sm',
                                )}
                              >
                                <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                                  <SourceBadge source={event.source} />
                                  <span className="font-medium">{cleanActor(event.actor?.display_name)}</span>
                                  <span className="text-muted-foreground">· {formatTime(event.timestamp)}</span>
                                </div>
                                {out && event.source_account ? (
                                  <div className="text-muted-foreground mb-1 text-[10px]">
                                    Répondu depuis <span className="font-medium">{event.source_account}</span>
                                  </div>
                                ) : null}
                                {hasSubject ? (
                                  <div className="font-medium">{event.title}</div>
                                ) : null}
                                {shownContent ? (
                                  <div
                                    className={cn(
                                      'mt-1 text-xs whitespace-pre-wrap',
                                      hasSubject ? 'text-muted-foreground' : 'text-foreground',
                                    )}
                                  >
                                    {shownContent}
                                  </div>
                                ) : !hasSubject ? (
                                  <div className="text-muted-foreground font-medium">(sans contenu)</div>
                                ) : null}
                                <div className="mt-2 flex items-center gap-3">
                                  {isLong ? (
                                    <button
                                      type="button"
                                      onClick={() => toggleExpanded(id)}
                                      className="text-primary text-[11px] font-medium hover:underline"
                                    >
                                      {isOpen ? 'Voir moins' : 'Voir plus'}
                                    </button>
                                  ) : null}
                                  {event.source_url ? (
                                    <a
                                      href={event.source_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-primary inline-flex items-center gap-1 text-[11px] font-medium hover:underline"
                                    >
                                      <ExternalLink className="h-3 w-3" />
                                      Ouvrir dans {meta.label}
                                    </a>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="flex flex-1 items-center justify-center">
                  <p className="text-muted-foreground text-sm">Sélectionnez une entreprise.</p>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </section>
  )
}
