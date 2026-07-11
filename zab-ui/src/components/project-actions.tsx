import { toast } from 'sonner'
import { Button } from '@/components/ui/button'

export type OverviewProject = {
  id?: string
  name: string
  path: string
  org: string
  projects_root: string
  workspace_parent?: string | null
  skills: { id: string; path: string; rel_from_home?: string; source?: string }[]
  git_repo?: boolean
  git_branch?: string | null
  remote_host?: string | null
  origin_url?: string | null
  origin_https?: string | null
  last_activity_at_utc?: string | null
  last_activity_source?: string | null
  last_activity_path?: string | null
}

async function postProjectAction(url: string, body: Record<string, string>): Promise<void> {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) {
    let msg = r.statusText
    try {
      const j = (await r.json()) as { detail?: unknown }
      if (typeof j.detail === 'string') msg = j.detail
      else if (j.detail && typeof j.detail === 'object' && 'output' in j.detail) {
        const d = j.detail as { output?: string; error?: string }
        msg = [d.error, d.output].filter(Boolean).join('\n') || msg
      }
    } catch {
      msg = await r.text()
    }
    throw new Error(msg || r.statusText)
  }
}

export function ProjectActions({
  p,
  compact = false,
  miningProjectPath,
  onMineMemory,
  onRunSecurityScan,
}: {
  p: OverviewProject
  compact?: boolean
  miningProjectPath?: string | null
  onMineMemory?: (path: string, name: string) => void | Promise<void>
  onRunSecurityScan?: (preset: string, path: string) => void
}) {
  const gitRepo = Boolean(p.git_repo)
  const originHttps = typeof p.origin_https === 'string' ? p.origin_https : ''

  const runPm = async (tool: 'gh' | 'glab') => {
    try {
      await postProjectAction('/api/system/project-pm-cli', { path: p.path, tool })
      toast.success(tool === 'gh' ? 'GitHub CLI' : 'GitLab CLI', {
        description: 'Commande exécutée (souvent ouverture du navigateur).',
      })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const openOrigin = async () => {
    try {
      await postProjectAction('/api/system/open-git-remote', { path: p.path })
      toast.success('Remote origin ouvert dans le navigateur')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const openFolder = async () => {
    try {
      const r = await fetch('/api/system/open-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: p.path }),
      })
      if (!r.ok) {
        const t = await r.text()
        throw new Error(t || r.statusText)
      }
      toast.success('Dossier ouvert')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const btnClass = compact ? 'h-7 px-2 text-[10px]' : 'text-xs'

  return (
    <div className="flex flex-wrap gap-1">
      {onMineMemory ? (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className={btnClass}
          disabled={miningProjectPath != null}
          title="MemPalace : .md/.pdf/.txt + descriptif CSV uniquement ; palace local (hors Postgres)"
          onClick={() => void onMineMemory(p.path, p.name)}
        >
          {miningProjectPath === p.path ? 'Index…' : compact ? 'Mémoire' : 'Indexer mémoire'}
        </Button>
      ) : null}
      <Button type="button" variant="outline" size="sm" className={btnClass} onClick={() => void openFolder()}>
        {compact ? 'Dossier' : 'Ouvrir le dossier'}
      </Button>
      {gitRepo && originHttps ? (
        <Button type="button" variant="secondary" size="sm" className={btnClass} onClick={() => void openOrigin()}>
          Origin
        </Button>
      ) : null}
      {gitRepo ? (
        <>
          <Button type="button" variant="outline" size="sm" className={btnClass} onClick={() => void runPm('gh')}>
            gh
          </Button>
          <Button type="button" variant="outline" size="sm" className={btnClass} onClick={() => void runPm('glab')}>
            glab
          </Button>
        </>
      ) : null}
      {onRunSecurityScan ? (
        <>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={btnClass}
            title="OSV-Scanner récursif sur ce projet"
            onClick={() => onRunSecurityScan('security_osv_project', p.path)}
          >
            OSV
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={btnClass}
            title="npm audit dans ce projet (si package.json)"
            onClick={() => onRunSecurityScan('security_npm_audit_project', p.path)}
          >
            npm audit
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={btnClass}
            title="Gitleaks sur ce projet"
            onClick={() => onRunSecurityScan('security_gitleaks_project', p.path)}
          >
            Gitleaks
          </Button>
        </>
      ) : null}
    </div>
  )
}
