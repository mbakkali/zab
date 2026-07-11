import { useState, type FormEvent } from 'react'
import { ClipboardCopy, Play, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

type ResearchPayload = {
  contract: 'research-packet'
  contract_version: string
  generated_at_utc: string
  query: string
  mode: string
  project: { id: string | null; path: string | null; confidence: string }
  freshness: Record<string, { status?: string; last_checked_at?: string; last_success_at?: string }>
  source_status: { source: string; kind: string; status: string; freshness: string; items_considered: number | null }[]
  context_packet_markdown: string
  citations: { id: string; kind: string; label: string; reason: string; path?: string }[]
  conflicts: { topic: string; reason: string; confidence?: string }[]
  recommended_next_actions: string[]
  warnings: string[]
}

const MODES = ['plan', 'debug', 'review', 'briefing', 'handoff']

export function ResearchView() {
  const [query, setQuery] = useState('comment rendre Zab dynamique ?')
  const [project, setProject] = useState('zab')
  const [mode, setMode] = useState('plan')
  const [refresh, setRefresh] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [payload, setPayload] = useState<ResearchPayload | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          project: project.trim() || null,
          mode,
          refresh,
          max_tokens: 6000,
        }),
      })
      if (!response.ok) throw new Error(await response.text())
      const data = (await response.json()) as ResearchPayload
      setPayload(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function copyPacket() {
    if (!payload?.context_packet_markdown) return
    await navigator.clipboard.writeText(payload.context_packet_markdown)
    toast.success('Research packet copied')
  }

  return (
    <section className="space-y-6" data-testid="research-view">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <p className="text-muted-foreground text-sm font-medium tracking-wide uppercase">Agent Center</p>
          <h1 className="text-3xl font-semibold tracking-tight">Research</h1>
          <p className="text-muted-foreground mt-2 max-w-3xl text-sm">
            Build a deterministic, cited and freshness-aware packet before planning, coding or reviewing.
          </p>
        </div>
        <Button type="button" variant="outline" onClick={() => void copyPacket()} disabled={!payload?.context_packet_markdown}>
          <ClipboardCopy className="mr-2 size-4" />
          Copy packet
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Packet request</CardTitle>
          <CardDescription>Cache is used by default; refresh explicitly reads supported external sources.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="grid gap-4" onSubmit={(event) => void submit(event)}>
            <label className="grid gap-2 text-sm font-medium">
              Query
              <Textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={3} />
            </label>
            <div className="grid gap-4 md:grid-cols-[1fr_180px_160px]">
              <label className="grid gap-2 text-sm font-medium">
                Project
                <input
                  className="border-input bg-background ring-offset-background placeholder:text-muted-foreground focus-visible:ring-ring h-10 rounded-md border px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                  value={project}
                  onChange={(event) => setProject(event.target.value)}
                />
              </label>
              <label className="grid gap-2 text-sm font-medium">
                Mode
                <select
                  className="border-input bg-background ring-offset-background focus-visible:ring-ring h-10 rounded-md border px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
                  value={mode}
                  onChange={(event) => setMode(event.target.value)}
                >
                  {MODES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label className="flex items-end gap-2 pb-2 text-sm font-medium">
                <input type="checkbox" checked={refresh} onChange={(event) => setRefresh(event.target.checked)} />
                Refresh sources
              </label>
            </div>
            <div>
              <Button type="submit" disabled={loading || !query.trim()}>
                {loading ? <RefreshCw className="mr-2 size-4 animate-spin" /> : <Play className="mr-2 size-4" />}
                Run research
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {error ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>Unable to build research packet</CardTitle>
            <CardDescription>{error}</CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      {payload ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <Card>
            <CardHeader>
              <CardTitle>Context packet</CardTitle>
              <CardDescription>
                {payload.contract} v{payload.contract_version} · {new Date(payload.generated_at_utc).toLocaleString()}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="bg-muted text-foreground max-h-[720px] overflow-auto rounded-md p-4 text-sm whitespace-pre-wrap" data-testid="research-packet">
                {payload.context_packet_markdown}
              </pre>
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader>
                <CardTitle>Source status</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {payload.source_status.slice(0, 10).map((row) => (
                  <div key={row.source} className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs">{row.source}</span>
                    <span className={cn('rounded-full border px-2 py-1 text-xs', row.status === 'ok' || row.status === 'local_ok' ? 'text-emerald-700' : 'text-amber-700')}>
                      {row.status}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Citations</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {payload.citations.map((citation) => (
                  <div key={citation.id}>
                    <div className="font-mono text-xs font-semibold">{citation.label}</div>
                    <div className="text-muted-foreground text-xs">{citation.reason}</div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Next actions</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="text-muted-foreground list-disc space-y-2 pl-5 text-sm">
                  {payload.recommended_next_actions.map((action) => <li key={action}>{action}</li>)}
                </ul>
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </section>
  )
}
