import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { LoadingState } from '@/components/ui/loading-state'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

type WorkPacket = {
  workpacket_id: string
  display_id?: string
  title?: string
  state?: string
  priority?: string
  organization_label?: string
  client_workstream_label?: string
  confidence?: number
  updated_at?: string
  actions?: string[]
  metadata?: { ledger_facts?: { next_event_at?: string | null; awaiting_reply_from_us?: boolean; days_since_last_event?: number | null } }
}

/** Une échéance passe avant une réponse due, qui passe avant un simple suivi. */
function urgencyRank(item: WorkPacket): number {
  const facts = item.metadata?.ledger_facts
  if (facts?.next_event_at) return 0
  if (facts?.awaiting_reply_from_us) return 1
  if (item.state === 'active') return 2
  if (item.state === 'candidate') return 3
  return 4
}

async function apiJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json() as Promise<T>
}

export function WorkpacketsView() {
  const [items, setItems] = useState<WorkPacket[]>([])
  const [selected, setSelected] = useState<WorkPacket | null>(null)
  const [detailMd, setDetailMd] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const payload = await apiJson<{ items: WorkPacket[] }>('/api/workpackets')
      const rows = [...(payload.items || [])].sort(
        (a, b) => urgencyRank(a) - urgencyRank(b) || (a.display_id || '').localeCompare(b.display_id || ''),
      )
      setItems(rows)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openDetail = async (item: WorkPacket) => {
    setSelected(item)
    setDetailMd('')
    try {
      const packet = await apiJson<WorkPacket & { subject_lock?: Record<string, string> }>(
        `/api/workpackets/${encodeURIComponent(item.workpacket_id)}`,
      )
      const lock = packet.subject_lock || {}
      setDetailMd(
        [
          `# ${packet.title || item.title}`,
          '',
          `- State: ${packet.state}`,
          `- Priority: ${packet.priority}`,
          `- Organization: ${packet.organization_label}`,
          `- Workstream: ${packet.client_workstream_label}`,
          '',
          '## Subject Lock',
          `- Client: ${lock.client || '—'}`,
          `- Project / workstream: ${lock.project_or_workstream || '—'}`,
          `- Subject: ${lock.subject || '—'}`,
          `- Canonical source: ${lock.canonical_source || '—'}`,
        ].join('\n'),
      )
    } catch (e) {
      setDetailMd(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-4" data-testid="workpackets-view">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2">
          <div>
            <CardTitle>WorkPackets</CardTitle>
            <CardDescription>Canonical Zab WorkPackets with Subject Lock and projections.</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Refresh
          </Button>
        </CardHeader>
        <CardContent>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {loading && items.length === 0 ? (
            <LoadingState compact label="Chargement des WorkPackets…" />
          ) : null}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Tâche et prochaine action</TableHead>
                <TableHead>État</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.workpacket_id} className="cursor-pointer" onClick={() => void openDetail(item)}>
                  <TableCell className="align-top">{item.display_id || item.workpacket_id}</TableCell>
                  <TableCell>
                    <div className="font-medium">{item.title}</div>
                    {item.actions?.length ? (
                      <div className="mt-1 text-sm text-muted-foreground">→ {item.actions[0]}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="align-top">{item.state}</TableCell>
                </TableRow>
              ))}
              {!items.length && !loading ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-muted-foreground">
                    No WorkPackets yet. Run sync + reconstruct from CLI.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {selected ? (
        <Card>
          <CardHeader>
            <CardTitle>{selected.display_id || selected.workpacket_id}</CardTitle>
            <CardDescription>Subject Lock and canonical detail</CardDescription>
          </CardHeader>
          <CardContent>
            <pre className="whitespace-pre-wrap text-sm">{detailMd}</pre>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
