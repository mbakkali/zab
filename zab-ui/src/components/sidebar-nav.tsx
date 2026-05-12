import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react'
import {
  CompassIcon,
  Briefcase01Icon,
  PuzzleIcon,
  Plug02Icon,
  TestTube01Icon,
  LockKeyIcon,
  Upload03Icon,
  AiBrain02Icon,
  Settings02Icon,
  PencilEdit02Icon,
  SparklesIcon,
  CpuIcon,
  Folder02Icon,
  CheckListIcon,
} from '@hugeicons/core-free-icons'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

export type NavId =
  | 'overview'
  | 'orgs'
  | 'projects'
  | 'tasks_inbox'
  | 'plugins'
  | 'connectors'
  | 'config'
  | 'tests'
  | 'security'
  | 'exports'
  | 'memory'
  | 'ide'
  | 'models'
  | 'skills'

const items: { id: NavId; label: string; icon: unknown; group: 'main' | 'tools' }[] = [
  { id: 'overview', label: 'Vue d’ensemble', icon: CompassIcon, group: 'main' },
  { id: 'orgs', label: 'Organisations', icon: Briefcase01Icon, group: 'main' },
  { id: 'projects', label: 'Projets', icon: Folder02Icon, group: 'main' },
  { id: 'tasks_inbox', label: 'Tâches (multi-outils)', icon: CheckListIcon, group: 'main' },
  { id: 'plugins', label: 'Plugins', icon: PuzzleIcon, group: 'main' },
  { id: 'connectors', label: 'Connecteurs', icon: Plug02Icon, group: 'main' },
  { id: 'config', label: 'Configuration', icon: Settings02Icon, group: 'main' },
  { id: 'skills', label: 'Skills', icon: SparklesIcon, group: 'main' },
  { id: 'models', label: 'Modèles / Cursor', icon: CpuIcon, group: 'main' },
  { id: 'tests', label: 'Tests & jobs', icon: TestTube01Icon, group: 'tools' },
  { id: 'memory', label: 'Mémoire', icon: AiBrain02Icon, group: 'tools' },
  { id: 'security', label: 'Sécurité', icon: LockKeyIcon, group: 'tools' },
  { id: 'exports', label: 'Exports', icon: Upload03Icon, group: 'tools' },
  { id: 'ide', label: 'IDE / outils', icon: Settings02Icon, group: 'tools' },
]

function NavBrand() {
  return (
    <div className="mb-6 flex items-center gap-2 px-2">
      <div className="flex size-8 items-center justify-center rounded-lg bg-zinc-900 text-white">
        <HugeiconsIcon icon={SparklesIcon} size={18} strokeWidth={2} />
      </div>
      <div>
        <p className="text-sm font-semibold tracking-tight">zab</p>
        <p className="text-muted-foreground text-[11px]">skills · MCP · scan</p>
      </div>
    </div>
  )
}

/** Même contenu que la barre latérale, pour asides ou tiroir mobile. */
export function SidebarNavPanel({
  value,
  onChange,
  className,
  showEditSkillLink = false,
}: {
  value: NavId
  onChange: (id: NavId) => void
  className?: string
  /** Sur mobile, raccourci vers l’onglet Skills + éditeur ; masqué sur desktop (FAB). */
  showEditSkillLink?: boolean
}) {
  const main = items.filter((it) => it.group === 'main')
  const tools = items.filter((it) => it.group === 'tools')

  return (
    <div className={cn('flex flex-col', className)}>
      <NavBrand />
      <nav className="flex flex-col gap-1">
        {main.map((it) => (
          <NavButton
            key={it.id}
            active={value === it.id}
            onClick={() => onChange(it.id)}
            icon={it.icon as IconSvgElement}
            label={it.label}
          />
        ))}
      </nav>
      <p className="text-muted-foreground mt-6 mb-2 px-2 text-[11px] font-medium tracking-wider uppercase">Outils</p>
      <nav className="flex flex-col gap-1">
        {tools.map((it) => (
          <NavButton
            key={it.id}
            active={value === it.id}
            onClick={() => onChange(it.id)}
            icon={it.icon as IconSvgElement}
            label={it.label}
          />
        ))}
        {showEditSkillLink ? (
          <NavButton
            active={value === 'skills'}
            onClick={() => onChange('skills' as NavId)}
            icon={PencilEdit02Icon}
            label="Éditer SKILL"
          />
        ) : null}
      </nav>
    </div>
  )
}

export function SidebarNav({ value, onChange }: { value: NavId; onChange: (id: NavId) => void }) {
  return (
    <aside className="bg-sidebar border-sidebar-border sticky top-0 hidden h-screen w-60 shrink-0 border-r px-3 py-5 md:block">
      <SidebarNavPanel value={value} onChange={onChange} />
    </aside>
  )
}

/** Menu mobile : même navigation que la sidebar (visible uniquement lorsque ``open``). */
export function MobileNavDrawer({
  open,
  onOpenChange,
  value,
  onChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  value: NavId
  onChange: (id: NavId) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton
        className={cn(
          'fixed top-0 left-0 z-50 flex h-[100dvh] max-h-[100dvh] w-[min(100vw,18rem)] max-w-none',
          'translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 p-0 sm:max-w-none',
        )}
      >
        <div className="bg-sidebar flex max-h-[100dvh] min-h-0 flex-1 flex-col overflow-y-auto border-r px-3 py-5">
          <DialogHeader className="sr-only">
            <DialogTitle>Navigation zab</DialogTitle>
          </DialogHeader>
          <SidebarNavPanel
            value={value}
            onChange={onChange}
            showEditSkillLink
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function NavButton({
  active,
  onClick,
  icon,
  label,
  hide,
}: {
  active: boolean
  onClick: () => void
  icon: IconSvgElement
  label: string
  hide?: boolean
}) {
  if (hide) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'group flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors',
        active ? 'bg-zinc-900 text-white shadow-sm' : 'text-zinc-700 hover:bg-zinc-100',
      )}
    >
      <HugeiconsIcon icon={icon} size={18} strokeWidth={active ? 2 : 1.6} />
      <span className="font-medium tracking-tight">{label}</span>
    </button>
  )
}
