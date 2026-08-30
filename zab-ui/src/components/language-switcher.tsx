import { cn } from '@/lib/utils'
import { useI18n } from '@/i18n/use-i18n'
import type { Locale } from '@/i18n/types'

const LOCALES: { id: Locale; label: string }[] = [
  { id: 'en', label: 'EN' },
  { id: 'fr', label: 'FR' },
]

export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n()

  return (
    <div
      className={cn(
        'inline-flex shrink-0 items-center rounded-md border bg-muted/50 p-0.5 text-xs font-medium',
        className,
      )}
      role="group"
      aria-label={t('language.switchTo', { lang: locale === 'en' ? 'FR' : 'EN' })}
    >
      {LOCALES.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          aria-pressed={locale === id}
          title={t(id === 'en' ? 'language.en' : 'language.fr')}
          onClick={() => setLocale(id)}
          className={cn(
            'rounded px-2 py-1 transition-colors',
            locale === id
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}
