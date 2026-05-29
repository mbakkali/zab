export type Locale = 'en' | 'fr'

export const LOCALE_STORAGE_KEY = 'zab.locale'

export const DEFAULT_LOCALE: Locale = 'en'

export const INTL_LOCALE: Record<Locale, string> = {
  en: 'en-US',
  fr: 'fr-FR',
}

export type TranslationVars = Record<string, string | number>

export type Messages = Record<string, unknown>
