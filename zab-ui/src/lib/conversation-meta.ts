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
  if (lower === 'cursor') return 'bg-info/10 text-info ring-info/35'
  if (lower === 'claude') return 'bg-alerte/10 text-alerte ring-alerte/35'
  if (lower === 'codex') return 'bg-succes/10 text-succes ring-succes/35'
  if (lower === 'hermes') return 'bg-muted text-foreground ring-ring/40'
  if (lower === 'gemini') return 'bg-info/10 text-info ring-info/35'
  if (lower === 'kimi') return 'bg-danger/10 text-danger ring-danger/35'
  return 'bg-muted text-foreground ring-ring/40'
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
