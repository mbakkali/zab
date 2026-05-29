import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import en from './locales/en.json'
import fr from './locales/fr.json'
import { resolveMessage } from './resolve'
import {
  DEFAULT_LOCALE,
  INTL_LOCALE,
  LOCALE_STORAGE_KEY,
  type Locale,
  type Messages,
  type TranslationVars,
} from './types'

const CATALOG: Record<Locale, Messages> = { en: en as Messages, fr: fr as Messages }

function readStoredLocale(): Locale {
  if (typeof window === 'undefined') return DEFAULT_LOCALE
  const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
  if (stored === 'en' || stored === 'fr') return stored
  return DEFAULT_LOCALE
}

type I18nContextValue = {
  locale: Locale
  intlLocale: string
  setLocale: (locale: Locale) => void
  t: (key: string, vars?: TranslationVars) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale)

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    localStorage.setItem(LOCALE_STORAGE_KEY, next)
  }, [])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const messages = CATALOG[locale]

  const t = useCallback(
    (key: string, vars?: TranslationVars) => resolveMessage(messages, key, vars),
    [messages],
  )

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      intlLocale: INTL_LOCALE[locale],
      setLocale,
      t,
    }),
    [locale, setLocale, t],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18nContext(): I18nContextValue {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useI18n must be used within I18nProvider')
  return ctx
}
