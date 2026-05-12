import { useMemo, useState } from 'react'
import { HugeiconsIcon } from '@hugeicons/react'
import { Search01Icon } from '@hugeicons/core-free-icons'
import { skillIconFor, skillOrgIcon } from '@/lib/connector-meta'
import { shortenHomeInPath, vscodeFileHrefForSkill } from '@/lib/skill-open'
import { cn } from '@/lib/utils'

type Skill = { id: string; path: string; source?: string; project?: string }
type Org = { org: string; skills: Skill[]; skills_repo_root?: string }

export function SkillsView({
  orgs,
  fallbackSkillsRoot,
  onEdit,
}: {
  orgs: Org[] | undefined
  fallbackSkillsRoot?: string | null
  onEdit: (path: string) => void
}) {
  const [query, setQuery] = useState('')
  const [activeOrg, setActiveOrg] = useState<string>('all')

  const flat = useMemo(() => {
    if (!orgs) return [] as { org: string; skillsRepoRoot?: string; skill: Skill }[]
    return orgs.flatMap((o) => o.skills.map((s) => ({ org: o.org, skillsRepoRoot: o.skills_repo_root, skill: s })))
  }, [orgs])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return flat.filter((e) => {
      if (activeOrg !== 'all' && e.org !== activeOrg) return false
      if (!q) return true
      const inProj = e.skill.project?.toLowerCase().includes(q) ?? false
      return (
        e.skill.id.toLowerCase().includes(q) ||
        e.org.toLowerCase().includes(q) ||
        e.skill.path.toLowerCase().includes(q) ||
        inProj
      )
    })
  }, [flat, query, activeOrg])

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-1">
        <h2 className="text-2xl font-semibold tracking-tight">Skills</h2>
        <p className="text-muted-foreground text-sm">
          {flat.length} skills réparties sur {orgs?.length ?? 0} organisations
        </p>
      </header>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full max-w-sm">
          <HugeiconsIcon
            icon={Search01Icon}
            size={16}
            className="text-muted-foreground absolute top-1/2 left-3 -translate-y-1/2"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Rechercher une skill…"
            className="border-input bg-background w-full rounded-lg border py-2 pr-3 pl-9 text-sm outline-none transition focus:ring-2 focus:ring-zinc-300"
          />
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Chip active={activeOrg === 'all'} onClick={() => setActiveOrg('all')}>
            Tous · {flat.length}
          </Chip>
          {orgs?.map((o) => (
            <Chip key={o.org} active={activeOrg === o.org} onClick={() => setActiveOrg(o.org)}>
              {o.org} · {o.skills.length}
            </Chip>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filtered.map(({ org, skillsRepoRoot, skill }) => (
          <SkillCard
            key={skill.path}
            org={org}
            skill={skill}
            skillsRepoRoot={skillsRepoRoot}
            fallbackSkillsRoot={fallbackSkillsRoot}
            onEdit={() => onEdit(skill.path)}
          />
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="text-muted-foreground rounded-xl border border-dashed py-16 text-center text-sm">
          Aucune skill ne correspond.
        </div>
      )}
    </div>
  )
}

function SkillCard({
  org,
  skill,
  skillsRepoRoot,
  fallbackSkillsRoot,
  onEdit,
}: {
  org: string
  skill: Skill
  skillsRepoRoot?: string
  fallbackSkillsRoot?: string | null
  onEdit: () => void
}) {
  const meta = skillIconFor(org, skill.id)
  const orgMeta = skillOrgIcon[org]
  const vsc = vscodeFileHrefForSkill(skill.path, skillsRepoRoot, fallbackSkillsRoot)
  return (
    <div className="group bg-card hover:border-zinc-300 flex flex-col gap-2 rounded-xl border border-zinc-200 transition hover:shadow-sm">
      <button
        type="button"
        onClick={onEdit}
        className="text-left outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 cursor-pointer flex flex-col gap-2 rounded-t-xl p-4 pb-2"
      >
        <div className="flex items-start gap-3">
          <div className={cn('flex size-12 shrink-0 items-center justify-center rounded-xl', meta.tone)}>
            <HugeiconsIcon icon={meta.icon} size={26} strokeWidth={1.6} />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold tracking-tight">{prettySkill(skill.id)}</h3>
            <span
              className={cn(
                'mt-1 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide',
                orgMeta?.tone ?? 'bg-zinc-100 text-zinc-600',
              )}
            >
              {org}
              {skill.source === 'workspace' && skill.project ? ` · ${skill.project}` : ''}
            </span>
          </div>
        </div>
        <span className="text-muted-foreground line-clamp-2 font-mono text-[10px] break-all">
          {shortenHomeInPath(skill.path)}
        </span>
      </button>
      {vsc ? (
        <div className="flex justify-end border-t border-zinc-100 px-3 py-2 dark:border-zinc-800">
          <a href={vsc} className="text-primary text-[11px] font-medium underline" onClick={(e) => e.stopPropagation()}>
            Ouvrir dans l’IDE
          </a>
        </div>
      ) : null}
    </div>
  )
}

function Chip({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      type="button"
      className={cn(
        'rounded-full border px-3 py-1 text-xs font-medium transition',
        active
          ? 'border-zinc-900 bg-zinc-900 text-white'
          : 'border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300',
      )}
    >
      {children}
    </button>
  )
}

function prettySkill(id: string): string {
  return id.replace(/[-_]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
