import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { useI18n } from '@/i18n/use-i18n'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { LoadingState } from '@/components/ui/loading-state'
import { cn } from '@/lib/utils'

type SecretsHubProjectRow = {
  org: string
  project: string
  env_file_count: number
  detected_count: number
  skipped_count: number
  versioned: boolean
}

type SecretsHubOverviewPayload = {
  counts: { referenced: number; plain: number; process: number; missing: number }
  scanned_files: number
  projects: SecretsHubProjectRow[]
  totals: { projects: number; detected: number; skipped: number; versioned: number }
}

async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init)
  if (!r.ok) {
    const respText = await r.text()
    throw new Error(respText || r.statusText)
  }
  return r.json() as Promise<T>
}

// Cet écran est en lecture seule par construction : il ne fait jamais suivre
// --apply ni aucune écriture. La route qu'il appelle n'expose que des noms,
// des chemins et des compteurs — jamais une valeur de secret.
export function SecretsHubProjectsView() {
  const { t } = useI18n()
  const [payload, setPayload] = useState<SecretsHubOverviewPayload | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiJson<SecretsHubOverviewPayload>('/api/security/secrets-hub/overview')
      setPayload(data)
    } catch (e) {
      setPayload(null)
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const counts = payload?.counts
  const totals = payload?.totals
  const rows = payload?.projects ?? []

  return (
    <div className="space-y-4" data-testid="secrets-hub-projects-view">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle>{t('security.secretsHub.title')}</CardTitle>
            <CardDescription>{t('security.secretsHub.subtitle')}</CardDescription>
          </div>
          <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void load()}>
            {t('common.refresh')}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading && !payload ? (
            <LoadingState compact label={t('common.loading')} />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                  <p className="text-muted-foreground text-[11px] uppercase">{t('security.secretsHub.counts.referenced')}</p>
                  <p className="text-xl font-semibold tracking-tight">{counts?.referenced ?? '—'}</p>
                </div>
                <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                  <p className="text-muted-foreground text-[11px] uppercase">{t('security.secretsHub.counts.plain')}</p>
                  <p className="text-xl font-semibold tracking-tight">{counts?.plain ?? '—'}</p>
                </div>
                <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                  <p className="text-muted-foreground text-[11px] uppercase">{t('security.secretsHub.counts.process')}</p>
                  <p className="text-xl font-semibold tracking-tight">{counts?.process ?? '—'}</p>
                </div>
                <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                  <p className="text-muted-foreground text-[11px] uppercase">{t('security.secretsHub.counts.missing')}</p>
                  <p className="text-xl font-semibold tracking-tight">{counts?.missing ?? '—'}</p>
                </div>
              </div>
              <p className="text-muted-foreground text-xs">
                {t('security.secretsHub.totalsLine', {
                  projects: totals?.projects ?? 0,
                  detected: totals?.detected ?? 0,
                  skipped: totals?.skipped ?? 0,
                  versioned: totals?.versioned ?? 0,
                  scannedFiles: payload?.scanned_files ?? 0,
                })}
              </p>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('security.secretsHub.tableTitle')}</CardTitle>
          <CardDescription>{t('security.secretsHub.tableSubtitle')}</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('security.secretsHub.columns.org')}</TableHead>
                <TableHead>{t('security.secretsHub.columns.project')}</TableHead>
                <TableHead>{t('security.secretsHub.columns.envFiles')}</TableHead>
                <TableHead>{t('security.secretsHub.columns.detected')}</TableHead>
                <TableHead>{t('security.secretsHub.columns.skipped')}</TableHead>
                <TableHead>{t('security.secretsHub.columns.status')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground text-sm">
                    {t('common.loading')}
                  </TableCell>
                </TableRow>
              ) : rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground text-sm">
                    {t('security.secretsHub.empty')}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow key={`${row.org}:${row.project}`}>
                    <TableCell className="font-mono text-xs">{row.org || '—'}</TableCell>
                    <TableCell className="font-mono text-xs">{row.project || '—'}</TableCell>
                    <TableCell className="text-xs">{row.env_file_count}</TableCell>
                    <TableCell className="text-xs">{row.detected_count}</TableCell>
                    <TableCell className="text-xs">{row.skipped_count}</TableCell>
                    <TableCell>
                      {row.versioned ? (
                        <span className="inline-flex rounded-full bg-sky-50 px-2 py-0.5 text-[11px] text-sky-800 ring-1 ring-sky-200">
                          {t('security.secretsHub.statusVersioned')}
                        </span>
                      ) : (
                        <span
                          className={cn(
                            'inline-flex rounded-full px-2 py-0.5 text-[11px] ring-1',
                            row.detected_count > 0
                              ? 'bg-amber-50 text-amber-900 ring-amber-200'
                              : 'bg-zinc-100 text-zinc-600 ring-zinc-200',
                          )}
                        >
                          {t('security.secretsHub.statusNotMirrored')}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
