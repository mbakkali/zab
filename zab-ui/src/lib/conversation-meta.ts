/** Labels and colors for the Conversations tab (CLI providers). */

export const CONVERSATION_PROVIDER_IDS = [
  'cursor',
  'claude',
  'codex',
  'hermes',
  'gemini',
  'kimi',
] as const

export type ConversationProviderId = (typeof CONVERSATION_PROVIDER_IDS)[number]

export function conversationProviderLabel(id: string): string {
  const m: Record<string, string> = {
    cursor: 'Cursor',
    claude: 'Claude Code',
    codex: 'Codex',
    hermes: 'Hermes',
    gemini: 'Gemini CLI',
    kimi: 'Kimi',
  }
  return m[id] ?? id
}

export function conversationProviderBadgeClass(id: string): string {
  const lower = id.toLowerCase()
  if (lower === 'cursor') return 'bg-sky-50 text-sky-900 ring-sky-200'
  if (lower === 'claude') return 'bg-amber-50 text-amber-900 ring-amber-200'
  if (lower === 'codex') return 'bg-emerald-50 text-emerald-900 ring-emerald-200'
  if (lower === 'hermes') return 'bg-violet-50 text-violet-900 ring-violet-200'
  if (lower === 'gemini') return 'bg-blue-50 text-blue-900 ring-blue-200'
  if (lower === 'kimi') return 'bg-rose-50 text-rose-900 ring-rose-200'
  return 'bg-zinc-100 text-zinc-700 ring-zinc-200'
}

const STATUS_KEYS: Record<string, string> = {
  missing: 'conversations.status.missing',
  detected: 'conversations.status.detected',
  ready: 'conversations.status.ready',
  synced: 'conversations.status.synced',
  unsupported: 'conversations.status.unsupported',
  error: 'conversations.status.error',
}

export function conversationStatusLabel(status: string, t: (key: string) => string): string {
  const key = STATUS_KEYS[status]
  return key ? t(key) : status
}
