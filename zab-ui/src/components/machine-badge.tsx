import { useEffect, useState } from 'react'
import { CloudServerIcon, ComputerIcon, LaptopIcon } from '@hugeicons/core-free-icons'
import { HugeiconsIcon } from '@hugeicons/react'
import { cn } from '@/lib/utils'

/**
 * Sur quelle machine ce zab tourne.
 *
 * Zab tourne sur le Mac de travail ET sur la VM cowork, avec le même code et
 * la même configuration. Deux onglets ouverts côte à côte étaient jusqu'ici
 * indiscernables — et on répare alors la mauvaise machine.
 *
 * Le badge porte aussi les sources qui ne PEUVENT pas fonctionner ici :
 * iMessage remonte en `error` sur la VM parce que `chat.db` n'existe que sur
 * macOS. Ce n'est pas une panne, et rien ne le disait.
 */

export type Machine = {
  genre: 'mac' | 'vm' | 'autre'
  libelle: string
  hote: string
  systeme: string
  architecture: string
  home: string
  tailscale: string | null
  sources_indisponibles: { source: string; motifs: string[]; raison: string }[]
}

const ICONES = { mac: LaptopIcon, vm: CloudServerIcon, autre: ComputerIcon }

export function useMachine() {
  const [machine, setMachine] = useState<Machine | null>(null)
  useEffect(() => {
    let vivant = true
    fetch('/api/machine')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (vivant && d) setMachine(d as Machine) })
      .catch(() => {})
    return () => { vivant = false }
  }, [])
  return machine
}

export function MachineBadge({ machine, className }: { machine: Machine | null; className?: string }) {
  if (!machine) return null
  const indispo = machine.sources_indisponibles ?? []
  return (
    <span
      // `title` et non une infobulle : le badge vit dans une barre déjà dense,
      // et l'information est un rappel, pas une action.
      title={[
        `${machine.libelle} — ${machine.hote}`,
        `${machine.systeme} ${machine.architecture} · ${machine.home}`,
        machine.tailscale ? `tailnet : ${machine.tailscale}` : null,
        ...indispo.map((s) => `${s.source} indisponible ici : ${s.raison}`),
      ].filter(Boolean).join('\n')}
      className={cn(
        'inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-1',
        'font-mono text-[10px] font-bold tracking-[0.06em] uppercase sm:text-[11px]',
        // La machine n'est pas un état : ni succès, ni alerte. Un badge
        // neutre — la teinte serait un signal qui ne veut rien dire.
        'border-border bg-muted text-foreground',
        className,
      )}
    >
      <HugeiconsIcon icon={ICONES[machine.genre] ?? ICONES.autre} className="size-3.5 shrink-0" />
      <span className="truncate">{machine.libelle}</span>
    </span>
  )
}
