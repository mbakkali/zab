import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Loader de chargement partagé pour les écrans du dashboard.
 *
 * À afficher tant que la donnée principale d'une vue est en cours de
 * récupération (initial fetch), pour éviter les écrans vides ou les
 * contenus placeholder « — » pendant le chargement.
 */
export function LoadingState({
  label = 'Chargement…',
  className,
  compact = false,
}: {
  label?: string
  className?: string
  compact?: boolean
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="loading-state"
      className={cn(
        'flex w-full flex-col items-center justify-center gap-3 text-muted-foreground',
        compact ? 'py-8' : 'min-h-[40vh]',
        className,
      )}
    >
      <Loader2 className="size-6 animate-spin" />
      {label ? <p className="text-sm">{label}</p> : null}
      <span className="sr-only">{label || 'Chargement'}</span>
    </div>
  )
}

export default LoadingState
