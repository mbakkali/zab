import type { Messages, TranslationVars } from './types'

function getNested(obj: Messages, path: string): unknown {
  const parts = path.split('.')
  let cur: unknown = obj
  for (const p of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[p]
  }
  return cur
}

function interpolate(template: string, vars?: TranslationVars): string {
  if (!vars) return template
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) => {
    const v = vars[key]
    return v === undefined ? `{{${key}}}` : String(v)
  })
}

export function resolveMessage(
  messages: Messages,
  key: string,
  vars?: TranslationVars,
): string {
  const raw = getNested(messages, key)
  if (typeof raw !== 'string') {
    if (import.meta.env.DEV) {
      console.warn(`[i18n] missing key: ${key}`)
    }
    return key
  }
  return interpolate(raw, vars)
}

/** Flatten nested keys for parity checks between locale files. */
export function flattenKeys(obj: Messages, prefix = ''): string[] {
  const keys: string[] = []
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      keys.push(...flattenKeys(v as Messages, path))
    } else {
      keys.push(path)
    }
  }
  return keys.sort()
}
