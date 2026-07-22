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
      setItems(payload.items || [])
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
    <div className="space-y-4">
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
                <TableHead>Title</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Org / Workstream</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.workpacket_id} className="cursor-pointer" onClick={() => void openDetail(item)}>
                  <TableCell>{item.display_id || item.workpacket_id}</TableCell>
                  <TableCell>{item.title}</TableCell>
                  <TableCell>{item.state}</TableCell>
                  <TableCell>
                    {item.organization_label} / {item.client_workstream_label}
                  </TableCell>
                </TableRow>
              ))}
              {!items.length && !loading ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
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
