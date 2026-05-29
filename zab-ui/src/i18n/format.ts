import { useCallback } from 'react'
import { useI18n } from './use-i18n'

export function useFormatDate() {
  const { intlLocale } = useI18n()

  const formatDateTime = useCallback(
    (value: Date | string | number, options?: Intl.DateTimeFormatOptions) => {
      const d = value instanceof Date ? value : new Date(value)
      return d.toLocaleString(intlLocale, options)
    },
    [intlLocale],
  )

  const formatDate = useCallback(
    (value: Date | string | number, options?: Intl.DateTimeFormatOptions) => {
      const d = value instanceof Date ? value : new Date(value)
      return d.toLocaleDateString(intlLocale, options)
    },
    [intlLocale],
  )

  const formatTime = useCallback(
    (value: Date | string | number, options?: Intl.DateTimeFormatOptions) => {
      const d = value instanceof Date ? value : new Date(value)
      return d.toLocaleTimeString(intlLocale, options)
    },
    [intlLocale],
  )

  return { formatDateTime, formatDate, formatTime, intlLocale }
}
