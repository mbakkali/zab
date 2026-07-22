import { useCallback, useEffect, useMemo, useState } from 'react'
import { parse as parseYaml, stringify as stringifyYaml } from 'yaml'
import {
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Code2,
  Copy,
  ExternalLink,
  FileText,
  ListTree,
  Loader2,
  Plus,
  RotateCcw,
  Save,
  Settings2,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'
import { useI18n } from '@/i18n/use-i18n'
import type { TranslationVars } from '@/i18n/types'
import { LoadingState } from '@/components/ui/loading-state'

type TFn = (key: string, vars?: TranslationVars) => string

function configSectionLabel(key: string, t: TFn): string {
  const full = `config.sections.${key}.label`
  const v = t(full)
  return v === full ? key : v
}

function configSectionDescription(key: string, t: TFn): string | undefined {
  const full = `config.sections.${key}.description`
  const v = t(full)
  return v === full ? undefined : v
}

function configGroupLabel(group: SectionGroup, t: TFn): string {
  return t(`config.groups.${group}`)
}

function describeType(value: unknown, t: TFn): string {
  if (value === null || value === undefined) return t('config.types.empty')
  if (Array.isArray(value)) {
    if (value.every((x) => typeof x === 'string')) return t('config.types.stringList')
    if (value.every((x) => x && typeof x === 'object' && !Array.isArray(x))) return t('config.types.objectList')
    return t('config.types.list')
  }
  if (typeof value === 'object') return t('config.types.object')
  const ty = typeof value
  if (ty === 'string') return t('config.types.string')
  if (ty === 'number') return t('config.types.number')
  if (ty === 'boolean') return t('config.types.boolean')
  return ty
}
import { Button, buttonVariants } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { vscodeFileHref } from '@/lib/env-open'
import { cn } from '@/lib/utils'

const USER_CONFIG_KEY = 'user_zab_config'
const USER_CONFIG_PATH = '~/.config/zab/config.yaml'

type ConfigFileSummary = {
  key: string
  title: string
  syntax: string
  exists: boolean
  path_display: string
  hint?: string | null
}

type FileMeta = {
  path_display: string
  exists: boolean
  truncate_note?: string | null
  syntax: string
}

const CONFIG_FILE_ROW_FALLBACK: ConfigFileSummary = {
  key: USER_CONFIG_KEY,
  title: USER_CONFIG_PATH,
  syntax: 'yaml',
  exists: false,
  path_display: USER_CONFIG_PATH,
  hint: 'skills_roots, cli_watchlist, local_tools_path, task_sources, …',
}

type SectionGroup = 'skills' | 'tooling' | 'projects' | 'integrations' | 'system' | 'other'

const SECTION_GROUP: Record<string, SectionGroup> = {
  skills_registry_path: 'skills',
  claude_plugin_paths: 'skills',
  skills_roots: 'skills',
  skills_root: 'skills',
  cli_watchlist: 'tooling',
  tracked_env_extra: 'tooling',
  agentpipe_config_path: 'tooling',
  codexbar_config_path: 'tooling',
  local_tools_path: 'tooling',
  projects_roots: 'projects',
  task_sources: 'projects',
  communication_channels: 'integrations',
  obsidian: 'integrations',
  skills_sync: 'integrations',
  models_discovery: 'system',
  last_scan_at_utc: 'system',
}

const ALWAYS_VISIBLE_SECTION_DEFAULTS: Record<string, unknown> = {
  communication_channels: [],
}

function detectsStaleZabAggregatorBackend(message: string | null): boolean {
  return Boolean(message && message.includes('uv run zab dashboard'))
}

function staleConnectorsMessage(httpStatus: number, rawDetail: string, t: TFn): string {
  return [
    t('config.ui.staleBackend', { status: String(httpStatus) }),
    rawDetail.trim() ? t('config.ui.rawResponse', { detail: rawDetail.trim().slice(0, 280) }) : '',
  ]
    .filter(Boolean)
    .join('\n')
}

function looksLikePathOrUrl(items: unknown[]): boolean {
  if (!items.length) return false
  let pathLike = 0
  for (const x of items) {
    if (typeof x !== 'string') continue
    if (x.length > 40 || x.includes('/') || x.startsWith('~') || x.startsWith('http')) pathLike += 1
  }
  return pathLike >= Math.ceil(items.length / 2)
}

function countItems(value: unknown): number | null {
  if (Array.isArray(value)) return value.length
  if (value && typeof value === 'object') return Object.keys(value as object).length
  return null
}

function safeYamlStringify(value: unknown, t: TFn): string {
  try {
    return stringifyYaml(value, { lineWidth: 0, sortMapEntries: false })
  } catch (err) {
    return t('config.ui.yamlSerializeError', {
      message: err instanceof Error ? err.message : String(err),
    })
  }
}

function hasYamlComments(text: string): boolean {
  return /^\s*#/.test(text) || /\n\s*#/.test(text)
}

function sectionGroupOf(key: string): SectionGroup {
  return SECTION_GROUP[key] ?? 'other'
}

// ────────────────────────────────────────────────────────────────────────────
// Field renderer — récursif, dispatch par type
// ────────────────────────────────────────────────────────────────────────────

type TaskSourceSecretLocation = {
  id: string
  status: 'file' | 'process' | 'missing'
  env_token: string
  key_used?: string | null
  path?: string | null
  path_display?: string | null
  line?: number | null
  suggested_paths?: string[]
}

type ConfigSyncStatus = {
  status?: string | null
  last_synced_at?: string | null
  source?: string | null
  detail?: string | null
}

type ConfigSyncPayload = {
  generated_at_utc?: string
  state_last_sync_at?: string | null
  sections?: Record<string, ConfigSyncStatus>
  items?: Record<string, Record<string, ConfigSyncStatus>>
}

function formatConfigSyncDate(value: string, intlLocale: string, compact = false): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return new Intl.DateTimeFormat(
    intlLocale,
    compact
      ? { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }
      : { dateStyle: 'medium', timeStyle: 'short' },
  ).format(d)
}

function configSyncLabel(
  status: ConfigSyncStatus | undefined,
  intlLocale: string,
  t: TFn,
  compact = false,
): string {
  const when = status?.last_synced_at
  if (!when) return t('config.sync.never')
  return compact
    ? t('config.sync.lastCompact', { date: formatConfigSyncDate(when, intlLocale, true) })
    : t('config.sync.lastFull', { date: formatConfigSyncDate(when, intlLocale, false) })
}

function ConfigSyncBadge({
  status,
  compact = false,
}: {
  status: ConfigSyncStatus | undefined
  compact?: boolean
}) {
  const { t, intlLocale } = useI18n()
  const hasDate = Boolean(status?.last_synced_at)
  const label = configSyncLabel(status, intlLocale, t, compact)
  const title = [
    configSyncLabel(status, intlLocale, t, false),
    status?.source ? t('config.sync.source', { source: status.source }) : '',
    status?.detail ? t('config.sync.detail', { detail: status.detail }) : '',
  ]
    .filter(Boolean)
    .join('\n')

  return (
    <span
      className={cn(
        'inline-flex min-w-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
        hasDate
          ? 'border-sky-200 bg-sky-50 text-sky-800'
          : 'border-zinc-200 bg-muted/60 text-muted-foreground',
        compact ? 'max-w-full px-1.5' : 'shrink-0',
      )}
      title={title}
    >
      <Clock3 size={11} className="shrink-0" />
      <span className="truncate">{label}</span>
    </span>
  )
}

type FieldProps = {
  value: unknown
  onChange: (next: unknown) => void
  readOnly?: boolean
  depth?: number
  fieldKey?: string
  secretHintsById?: Record<string, TaskSourceSecretLocation>
  syncItemsById?: Record<string, ConfigSyncStatus>
}

function FieldRenderer({
  value,
  onChange,
  readOnly,
  depth = 0,
  fieldKey,
  secretHintsById,
  syncItemsById,
}: FieldProps) {
  const { t } = useI18n()
  if (value === null || value === undefined) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground text-xs italic">({t('config.types.empty')})</span>
        {!readOnly && (
          <div className="flex gap-1">
            <Button size="xs" variant="outline" onClick={() => onChange('')}>
              {t('config.ui.initText')}
            </Button>
            <Button size="xs" variant="outline" onClick={() => onChange([])}>
              {t('config.ui.initList')}
            </Button>
            <Button size="xs" variant="outline" onClick={() => onChange({})}>
              {t('config.ui.initObject')}
            </Button>
          </div>
        )}
      </div>
    )
  }
  if (typeof value === 'string') {
    return <StringField value={value} onChange={onChange} readOnly={readOnly} />
  }
  if (typeof value === 'boolean') {
    return <BoolField value={value} onChange={onChange} readOnly={readOnly} />
  }
  if (typeof value === 'number') {
    return <NumberField value={value} onChange={onChange} readOnly={readOnly} />
  }
  if (Array.isArray(value)) {
    if (value.every((x) => typeof x === 'string')) {
      return (
        <StringListField
          value={value as string[]}
          onChange={onChange}
          readOnly={readOnly}
          fieldKey={fieldKey}
        />
      )
    }
    if (
      value.every((x) => x && typeof x === 'object' && !Array.isArray(x)) &&
      value.length > 0
    ) {
      return (
        <ObjectListField
          value={value as Record<string, unknown>[]}
          onChange={onChange}
          readOnly={readOnly}
          depth={depth}
          secretHintsById={secretHintsById}
          syncItemsById={syncItemsById}
        />
      )
    }
    return (
      <MixedListField
        value={value as unknown[]}
        onChange={onChange}
        readOnly={readOnly}
        depth={depth}
      />
    )
  }
  if (typeof value === 'object') {
    return (
      <ObjectField
        value={value as Record<string, unknown>}
        onChange={onChange}
        readOnly={readOnly}
        depth={depth}
        secretHintsById={secretHintsById}
        syncItemsById={syncItemsById}
      />
    )
  }
  return <span className="text-muted-foreground text-xs">{String(value)}</span>
}

function StringField({
  value,
  onChange,
  readOnly,
}: {
  value: string
  onChange: (next: string) => void
  readOnly?: boolean
}) {
  const long = value.length > 80 || value.includes('\n')
  if (long) {
    return (
      <Textarea
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono text-xs leading-relaxed min-h-[6rem]"
      />
    )
  }
  return (
    <input
      type="text"
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
      className="border-input bg-background w-full rounded-lg border px-3 py-2 text-sm font-mono outline-none transition focus:ring-2 focus:ring-zinc-300"
    />
  )
}

function BoolField({
  value,
  onChange,
  readOnly,
}: {
  value: boolean
  onChange: (next: boolean) => void
  readOnly?: boolean
}) {
  return (
    <button
      type="button"
      disabled={readOnly}
      onClick={() => onChange(!value)}
      className={cn(
        'inline-flex h-6 w-11 items-center rounded-full border transition',
        value
          ? 'border-emerald-300 bg-emerald-500 justify-end'
          : 'border-zinc-300 bg-zinc-200 justify-start',
        readOnly && 'opacity-60 cursor-not-allowed',
      )}
      aria-pressed={value}
    >
      <span className="mx-0.5 size-5 rounded-full bg-white shadow" />
    </button>
  )
}

function NumberField({
  value,
  onChange,
  readOnly,
}: {
  value: number
  onChange: (next: number) => void
  readOnly?: boolean
}) {
  return (
    <input
      type="number"
      value={value}
      readOnly={readOnly}
      onChange={(e) => {
        const n = Number(e.target.value)
        onChange(Number.isFinite(n) ? n : 0)
      }}
      className="border-input bg-background w-40 rounded-lg border px-3 py-2 text-sm font-mono outline-none transition focus:ring-2 focus:ring-zinc-300"
    />
  )
}

function StringListField({
  value,
  onChange,
  readOnly,
  fieldKey,
}: {
  value: string[]
  onChange: (next: string[]) => void
  readOnly?: boolean
  fieldKey?: string
}) {
  const { t } = useI18n()
  const [draft, setDraft] = useState('')
  const [bulkMode, setBulkMode] = useState(false)
  const [bulk, setBulk] = useState('')
  const isPathy = looksLikePathOrUrl(value) || /paths?$|roots?$/.test(fieldKey ?? '')

  const add = () => {
    const v = draft.trim()
    if (!v) return
    if (value.includes(v)) {
      setDraft('')
      return
    }
    onChange([...value, v])
    setDraft('')
  }

  const remove = (idx: number) => onChange(value.filter((_, i) => i !== idx))

  const replaceFromBulk = () => {
    const lines = bulk
      .split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean)
    onChange(Array.from(new Set(lines)))
    setBulkMode(false)
  }

  if (bulkMode) {
    return (
      <div className="space-y-2">
        <Textarea
          value={bulk}
          onChange={(e) => setBulk(e.target.value)}
          className="font-mono text-xs leading-relaxed min-h-[8rem]"
          placeholder={t('config.ui.onePerLine')}
        />
        <div className="flex gap-2">
          <Button size="sm" onClick={replaceFromBulk}>
            {t('config.ui.replace')}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setBulkMode(false)
              setBulk('')
            }}
          >
            {t('common.cancel')}
          </Button>
          <p className="text-muted-foreground self-center text-[11px]">
            {t('config.ui.bulkCount', {
              current: String(value.length),
              draft: String(bulk.split(/\r?\n/).filter((x) => x.trim()).length),
            })}
          </p>
        </div>
      </div>
    )
  }

  if (isPathy && value.length) {
    return (
      <div className="space-y-2">
        <ul className="divide-border border-border divide-y rounded-lg border">
          {value.map((item, idx) => (
            <li
              key={`${item}-${idx}`}
              className="hover:bg-muted/40 group flex items-center gap-2 px-2 py-1.5"
            >
              <code className="text-foreground/90 flex-1 truncate font-mono text-[11px]" title={item}>
                {item}
              </code>
              {!readOnly && (
                <button
                  type="button"
                  onClick={() => remove(idx)}
                  className="text-muted-foreground hover:text-destructive rounded p-1 opacity-0 transition group-hover:opacity-100"
                  aria-label={t('config.ui.remove')}
                >
                  <Trash2 size={13} />
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(item)
                    .then(() => toast.success(t('common.copied')))
                    .catch(() => toast.error(t('common.copyFailed')))
                }}
                className="text-muted-foreground hover:text-foreground rounded p-1 opacity-0 transition group-hover:opacity-100"
                aria-label={t('config.ui.copyItem')}
              >
                <Copy size={13} />
              </button>
            </li>
          ))}
        </ul>
        {!readOnly && (
          <div className="flex gap-2">
            <input
              type="text"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  add()
                }
              }}
              placeholder={t('config.ui.addItem')}
              className="border-input bg-background flex-1 rounded-lg border px-3 py-1.5 text-xs font-mono outline-none transition focus:ring-2 focus:ring-zinc-300"
            />
            <Button size="sm" variant="outline" onClick={add}>
              <Plus size={13} />
              {t('config.ui.add')}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setBulkMode(true)}>
              {t('config.ui.bulkEdit')}
            </Button>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {value.length === 0 && (
          <span className="text-muted-foreground text-xs italic">{t('config.ui.emptyList')}</span>
        )}
        {value.map((item, idx) => (
          <span
            key={`${item}-${idx}`}
            className="bg-muted text-foreground inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
          >
            <code className="font-mono">{item}</code>
            {!readOnly && (
              <button
                type="button"
                onClick={() => remove(idx)}
                className="text-muted-foreground hover:text-destructive rounded-full p-0.5"
                aria-label={t('config.ui.remove')}
              >
                <Trash2 size={11} />
              </button>
            )}
          </span>
        ))}
      </div>
      {!readOnly && (
        <div className="flex gap-2">
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                add()
              }
            }}
            placeholder={t('config.ui.addItemEnter')}
            className="border-input bg-background flex-1 rounded-lg border px-3 py-1.5 text-xs outline-none transition focus:ring-2 focus:ring-zinc-300"
          />
          <Button size="sm" variant="outline" onClick={add}>
            <Plus size={13} />
            {t('config.ui.add')}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setBulkMode(true)}>
            {t('config.ui.bulkEdit')}
          </Button>
        </div>
      )}
    </div>
  )
}

function EnvTokenSourceHint({
  hint,
  envToken,
}: {
  hint: TaskSourceSecretLocation | undefined
  envToken: string
}) {
  const openInEditor = async (path: string, line?: number | null, key?: string) => {
    try {
      const r = await fetch('/api/system/open-editor-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, line: line ?? undefined, key: key ?? undefined }),
      })
      const t = await r.text()
      if (!r.ok) throw new Error(t || r.statusText)
      const j = JSON.parse(t) as { opened_with?: string; line?: number | null }
      toast.success(`Ouvert (${j.opened_with ?? 'éditeur'})${j.line ? ` — ligne ${j.line}` : ''}`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  if (!hint) {
    return (
      <p className="text-muted-foreground text-[10px] leading-snug">
        Secret : variable <code className="font-mono">{envToken || '—'}</code> — analyse en cours…
      </p>
    )
  }

  const keyLabel =
    hint.key_used && hint.key_used !== hint.env_token
      ? `${hint.env_token} → ${hint.key_used}`
      : hint.env_token || envToken

  if (hint.status === 'file' && hint.path && hint.path_display) {
    return (
      <div className="mt-1 space-y-1.5 rounded-md border border-emerald-200/80 bg-emerald-50/50 px-2.5 py-2 text-[10px] leading-snug text-emerald-900">
        <p>
          <span className="font-medium">Secret trouvé</span> dans{' '}
          <code className="font-mono">{hint.path_display}</code>
          {hint.line ? ` (ligne ${hint.line})` : ''} — clé <code className="font-mono">{keyLabel}</code>
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="xs"
            variant="outline"
            className="h-6 border-emerald-300 text-emerald-900 hover:bg-emerald-100"
            onClick={() => void openInEditor(hint.path!, hint.line, hint.key_used ?? hint.env_token)}
          >
            Ouvrir le .env
          </Button>
          <a
            href={vscodeFileHref(hint.path, hint.line)}
            className={cn(buttonVariants({ variant: 'ghost', size: 'xs' }), 'h-6 text-emerald-800')}
          >
            <ExternalLink size={11} className="mr-1 inline" />
            Cursor / VS Code
          </a>
        </div>
      </div>
    )
  }

  if (hint.status === 'process') {
    return (
      <p className="mt-1 rounded-md border border-amber-200/80 bg-amber-50/60 px-2.5 py-2 text-[10px] leading-snug text-amber-900">
        Variable <code className="font-mono">{keyLabel}</code> présente dans le processus du dashboard, mais
        introuvable dans les fichiers <code className="font-mono">.env</code> scannés. Pour la versionner,
        ajoutez-la dans <code className="font-mono">~/.config/zab/.env</code>.
      </p>
    )
  }

  return (
    <div className="mt-1 space-y-1 rounded-md border border-rose-200/80 bg-rose-50/50 px-2.5 py-2 text-[10px] leading-snug text-rose-900">
      <p>
        <span className="font-medium">Secret absent</span> — aucune valeur pour <code className="font-mono">{keyLabel}</code>{' '}
        dans les .env parcourus.
      </p>
      {hint.suggested_paths && hint.suggested_paths.length > 0 ? (
        <p className="text-rose-800/90">
          Fichiers à renseigner :{' '}
          {hint.suggested_paths.map((p, i) => (
            <span key={p}>
              {i > 0 ? ', ' : ''}
              <code className="font-mono">{p}</code>
            </span>
          ))}
        </p>
      ) : null}
    </div>
  )
}

function summarizeObject(obj: Record<string, unknown>): string {
  const ident =
    (typeof obj.id === 'string' && obj.id) ||
    (typeof obj.label === 'string' && obj.label) ||
    (typeof obj.name === 'string' && obj.name) ||
    (typeof obj.key === 'string' && obj.key) ||
    null
  if (ident) return ident
  const keys = Object.keys(obj).slice(0, 3).join(', ')
  return keys || '(objet)'
}

function ObjectListField({
  value,
  onChange,
  readOnly,
  depth = 0,
  secretHintsById,
  syncItemsById,
}: {
  value: Record<string, unknown>[]
  onChange: (next: Record<string, unknown>[]) => void
  readOnly?: boolean
  depth?: number
  secretHintsById?: Record<string, TaskSourceSecretLocation>
  syncItemsById?: Record<string, ConfigSyncStatus>
}) {
  const { t } = useI18n()
  const [openIdx, setOpenIdx] = useState<number | null>(null)

  const updateItem = (idx: number, next: Record<string, unknown>) => {
    const arr = value.slice()
    arr[idx] = next
    onChange(arr)
  }
  const removeItem = (idx: number) => {
    onChange(value.filter((_, i) => i !== idx))
    if (openIdx === idx) setOpenIdx(null)
  }
  const addItem = () => {
    const template = value[0] ? Object.fromEntries(Object.keys(value[0]).map((k) => [k, ''])) : {}
    onChange([...value, template])
    setOpenIdx(value.length)
  }

  return (
    <div className="space-y-2">
      <ul className="space-y-1.5">
        {value.map((item, idx) => {
          const open = openIdx === idx
          const itemSyncKey =
            (typeof item.id === 'string' && item.id) ||
            (typeof item.key === 'string' && item.key) ||
            (typeof item.name === 'string' && item.name) ||
            ''
          const itemSync = itemSyncKey ? syncItemsById?.[itemSyncKey] : undefined
          return (
            <li key={idx} className="border-border rounded-lg border">
              <div className="flex items-center gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => setOpenIdx(open ? null : idx)}
                  className="text-muted-foreground hover:text-foreground"
                  aria-label={open ? t('config.ui.collapse') : t('config.ui.expand')}
                >
                  {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <span className="text-foreground/80 text-xs font-medium">
                  {idx + 1}. {summarizeObject(item)}
                </span>
                <span className="text-muted-foreground text-[10px]">
                  {t('config.ui.fieldsCount', { count: String(Object.keys(item).length) })}
                </span>
                {itemSync ? <ConfigSyncBadge status={itemSync} compact /> : null}
                <div className="ml-auto flex gap-1">
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => removeItem(idx)}
                      className="text-muted-foreground hover:text-destructive rounded p-1"
                      aria-label={t('config.ui.remove')}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              </div>
              {open && (
                <div className="border-border bg-muted/30 border-t p-3">
                  <ObjectField
                    value={item}
                    onChange={(next) => updateItem(idx, next as Record<string, unknown>)}
                    readOnly={readOnly}
                    depth={depth + 1}
                    secretHintsById={secretHintsById}
                    syncItemsById={syncItemsById}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {!readOnly && (
        <Button size="sm" variant="outline" onClick={addItem}>
          <Plus size={13} />
          {t('config.ui.addEntry')}
        </Button>
      )}
    </div>
  )
}

function MixedListField({
  value,
  onChange,
  readOnly,
  depth = 0,
}: {
  value: unknown[]
  onChange: (next: unknown[]) => void
  readOnly?: boolean
  depth?: number
}) {
  return (
    <div className="space-y-1.5">
      {value.map((item, idx) => (
        <div key={idx} className="border-border bg-muted/30 rounded-lg border p-3">
          <div className="text-muted-foreground mb-1 flex items-center justify-between text-[11px]">
            <span>Élément {idx + 1}</span>
            {!readOnly && (
              <button
                type="button"
                onClick={() => onChange(value.filter((_, i) => i !== idx))}
                className="hover:text-destructive rounded p-1"
                aria-label="Supprimer"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
          <FieldRenderer
            value={item}
            onChange={(next) => {
              const arr = value.slice()
              arr[idx] = next
              onChange(arr)
            }}
            readOnly={readOnly}
            depth={depth + 1}
          />
        </div>
      ))}
    </div>
  )
}

function ObjectField({
  value,
  onChange,
  readOnly,
  depth = 0,
  secretHintsById,
  syncItemsById,
}: {
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
  readOnly?: boolean
  depth?: number
  secretHintsById?: Record<string, TaskSourceSecretLocation>
  syncItemsById?: Record<string, ConfigSyncStatus>
}) {
  const { t } = useI18n()
  const entries = Object.entries(value)
  const updateKey = (k: string, v: unknown) => onChange({ ...value, [k]: v })

  return (
    <div className={cn('grid gap-4', depth === 0 && 'grid-cols-1')}>
      {entries.map(([k, v]) => (
        <div key={k} className="grid grid-cols-1 gap-1.5 sm:grid-cols-[180px_1fr] sm:items-start">
          <div className="flex flex-col">
            <code className="text-foreground/90 font-mono text-[11px] font-semibold">{k}</code>
            <span className="text-muted-foreground text-[10px]">{describeType(v, t)}</span>
          </div>
          <div className="min-w-0 space-y-0">
            <FieldRenderer
              value={v}
              onChange={(next) => updateKey(k, next)}
              readOnly={readOnly}
              depth={depth + 1}
              fieldKey={k}
              syncItemsById={syncItemsById}
            />
            {k === 'env_token' && typeof value.id === 'string' ? (
              <EnvTokenSourceHint
                hint={secretHintsById?.[String(value.id)]}
                envToken={typeof v === 'string' ? v : ''}
              />
            ) : null}
          </div>
        </div>
      ))}
      {entries.length === 0 && (
        <span className="text-muted-foreground text-xs italic">{t('config.ui.emptyObject')}</span>
      )}
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// View principal
// ────────────────────────────────────────────────────────────────────────────

export function ConfigView() {
  const { t, intlLocale } = useI18n()
  const [rows, setRows] = useState<ConfigFileSummary[]>([])
  const [chosen] = useState<string>(USER_CONFIG_KEY)
  const [rawText, setRawText] = useState<string>('')
  const [originalText, setOriginalText] = useState<string>('')
  const [meta, setMeta] = useState<FileMeta | null>(null)
  const [banner, setBanner] = useState<string | null>(null)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [autoSaving, setAutoSaving] = useState(false)
  const [reloadNonce, setReloadNonce] = useState(0)
  const [viewMode, setViewMode] = useState<'form' | 'yaml'>('form')
  const [activeSection, setActiveSection] = useState<string | null>(null)
  const [secretHintsById, setSecretHintsById] = useState<Record<string, TaskSourceSecretLocation>>({})
  const [syncStatusBySection, setSyncStatusBySection] = useState<Record<string, ConfigSyncStatus>>({})
  const [syncItemsBySection, setSyncItemsBySection] = useState<
    Record<string, Record<string, ConfigSyncStatus>>
  >({})
  const aggregatorStale = false

  const editable = chosen === USER_CONFIG_KEY
  const dirty = rawText !== originalText

  useEffect(() => {
    void (async () => {
      setBusy(true)
      setBanner(null)
      try {
        const r = await fetch('/api/config/files')
        const respText = await r.text()
        if (!r.ok) {
          if (r.status === 404) setBanner(staleConnectorsMessage(404, respText, t))
          else setBanner(t('config.ui.listFilesError', { status: String(r.status) }))
          setRows([CONFIG_FILE_ROW_FALLBACK])
        } else {
          const list = JSON.parse(respText) as ConfigFileSummary[]
          const row =
            list.find((x) => x.key === USER_CONFIG_KEY) ?? list[0] ?? CONFIG_FILE_ROW_FALLBACK
          setRows([row])
        }
      } catch {
        setBanner(t('config.ui.networkError'))
        setRows([CONFIG_FILE_ROW_FALLBACK])
      } finally {
        setBusy(false)
      }
    })()
  }, [t])

  useEffect(() => {
    if (!chosen) return
    void (async () => {
      setBanner(null)
      try {
        const r = await fetch(`/api/config/file?key=${encodeURIComponent(chosen)}`)
        const respText = await r.text()
        if (!r.ok) {
          setRawText('')
          setOriginalText('')
          setMeta(null)
          if (r.status === 404) setBanner(staleConnectorsMessage(404, respText, t))
          else setBanner(t('config.ui.readError', { status: String(r.status) }))
          return
        }
        const j = JSON.parse(respText) as {
          exists: boolean
          path_display: string
          content: string
          truncate_note?: string | null
          syntax: string
          error?: string | null
        }
        setMeta({
          exists: j.exists,
          path_display: j.path_display,
          truncate_note: j.truncate_note,
          syntax: j.syntax,
        })
        const initial = !j.exists
          ? t('config.ui.missingFileHeader', { path: j.path_display })
          : j.content || (j.error ? `# ${j.error}\n` : '')
        setRawText(initial)
        setOriginalText(initial)
      } catch {
        setRawText('')
        setOriginalText('')
      }
    })()
  }, [chosen, reloadNonce, t])

  useEffect(() => {
    if (chosen !== 'user_zab_config') return
    void (async () => {
      try {
        const r = await fetch('/api/tasks/secret-locations')
        if (!r.ok) return
        const j = (await r.json()) as { sources?: TaskSourceSecretLocation[] }
        const map: Record<string, TaskSourceSecretLocation> = {}
        for (const row of j.sources ?? []) {
          if (row?.id) map[row.id] = row
        }
        setSecretHintsById(map)
      } catch {
        setSecretHintsById({})
      }
    })()
  }, [chosen, reloadNonce])

  useEffect(() => {
    if (chosen !== USER_CONFIG_KEY) return
    void (async () => {
      try {
        const r = await fetch('/api/config/sync-status')
        if (!r.ok) return
        const j = (await r.json()) as ConfigSyncPayload
        setSyncStatusBySection(j.sections ?? {})
        setSyncItemsBySection(j.items ?? {})
      } catch {
        setSyncStatusBySection({})
        setSyncItemsBySection({})
      }
    })()
  }, [chosen, reloadNonce])

  const parsed = useMemo(() => {
    if (!rawText.trim()) return { ok: true as const, value: {} as Record<string, unknown> }
    try {
      const doc = parseYaml(rawText)
      if (doc && typeof doc === 'object' && !Array.isArray(doc)) {
        return { ok: true as const, value: doc as Record<string, unknown> }
      }
      return { ok: true as const, value: {} as Record<string, unknown> }
    } catch (err) {
      return { ok: false as const, error: err instanceof Error ? err.message : String(err) }
    }
  }, [rawText])

  const sectionKeys = useMemo(() => {
    if (!parsed.ok) return []
    const merged = new Set<string>(Object.keys(parsed.value))
    for (const key of Object.keys(ALWAYS_VISIBLE_SECTION_DEFAULTS)) {
      merged.add(key)
    }
    return Array.from(merged)
  }, [parsed])

  useEffect(() => {
    if (sectionKeys.length === 0) {
      if (activeSection !== null) setActiveSection(null)
      return
    }
    if (!activeSection || !sectionKeys.includes(activeSection)) {
      setActiveSection(sectionKeys[0])
    }
  }, [sectionKeys, activeSection])

  const updateSection = useCallback(
    (sectionKey: string, next: unknown) => {
      if (!parsed.ok) return
      const draftObj: Record<string, unknown> = { ...parsed.value, [sectionKey]: next }
      try {
        const serialized = safeYamlStringify(draftObj, t)
        setRawText(serialized)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : String(err))
      }
    },
    [parsed, t],
  )

  const saveYaml = async () => {
    setSaving(true)
    try {
      const r = await fetch(`/api/config/file?key=${encodeURIComponent(chosen)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: rawText }),
      })
      const errText = await r.text()
      if (!r.ok) throw new Error(errText || r.statusText)
      toast.success(t('config.toast.saved'))
      setOriginalText(rawText)
      setReloadNonce((n) => n + 1)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    if (!editable || aggregatorStale) return
    if (viewMode !== 'form') return
    if (!dirty) return
    if (!parsed.ok) return

    const timer = window.setTimeout(() => {
      void (async () => {
        setAutoSaving(true)
        try {
          const r = await fetch(`/api/config/file?key=${encodeURIComponent(chosen)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: rawText }),
          })
          const errText = await r.text()
          if (!r.ok) throw new Error(errText || r.statusText)
          setOriginalText(rawText)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : String(e))
        } finally {
          setAutoSaving(false)
        }
      })()
    }, 450)

    return () => window.clearTimeout(timer)
  }, [editable, aggregatorStale, viewMode, dirty, parsed, chosen, rawText])

  const reload = () => {
    if (dirty && !window.confirm(t('config.confirm.discardChanges'))) return
    setRawText(originalText)
    setReloadNonce((n) => n + 1)
  }

  const groupedSections = useMemo(() => {
    const groups = new Map<SectionGroup, string[]>()
    for (const key of sectionKeys) {
      const g = sectionGroupOf(key)
      const list = groups.get(g) ?? []
      list.push(key)
      groups.set(g, list)
    }
    const order: SectionGroup[] = ['skills', 'tooling', 'projects', 'integrations', 'system', 'other']
    return order
      .map((g) => ({ group: g, keys: groups.get(g) ?? [] }))
      .filter((x) => x.keys.length > 0)
  }, [sectionKeys])

  const sectionValueByKey = useMemo(() => {
    if (!parsed.ok) return {}
    const out: Record<string, unknown> = { ...parsed.value }
    for (const [key, defaultValue] of Object.entries(ALWAYS_VISIBLE_SECTION_DEFAULTS)) {
      if (!(key in out)) out[key] = defaultValue
    }
    return out
  }, [parsed])

  const backendNeedsRestart = detectsStaleZabAggregatorBackend(banner)
  const yamlHasComments = hasYamlComments(rawText)

  if (busy && !meta) {
    return (
      <div className="space-y-4" data-testid="connectors-config-panel">
        <LoadingState label={t('common.loading')} />
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="connectors-config-panel">
      <header className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <Settings2 size={22} className="text-muted-foreground" />
          {t('config.title')}
        </h2>
        <p className="text-muted-foreground text-sm">{t('config.subtitle')}</p>
      </header>

      {banner && (
        <div
          role="alert"
          className={cn(
            'rounded-xl border px-4 py-3 text-sm whitespace-pre-wrap',
            backendNeedsRestart
              ? 'text-destructive border-red-200 bg-red-50/90'
              : 'text-amber-900 border-amber-200 bg-amber-50',
          )}
        >
          {banner}
        </div>
      )}

      <div className="ring-foreground/10 bg-card overflow-hidden rounded-xl ring-1">
        {/* Header avec sélecteur de fichier + actions */}
        <div className="border-border flex flex-col gap-3 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 overflow-hidden">
            <FileText size={16} className="text-muted-foreground shrink-0" />
            <div className="flex flex-wrap items-center gap-1.5">
              {(() => {
                const row = (busy ? CONFIG_FILE_ROW_FALLBACK : rows[0]) ?? CONFIG_FILE_ROW_FALLBACK
                return (
                  <span className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-900 bg-zinc-900 px-2.5 py-1 text-xs font-medium text-white">
                    <span>config.yaml</span>
                    {!row.exists && (
                      <span className="rounded-full bg-amber-200/60 px-1.5 py-0.5 text-[9px] font-semibold text-amber-900">
                        {t('config.file.absent')}
                      </span>
                    )}
                  </span>
                )
              })()}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="border-border inline-flex rounded-lg border p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('form')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition',
                  viewMode === 'form'
                    ? 'bg-zinc-900 text-white shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <ListTree size={12} />
                {t('config.viewMode.form')}
              </button>
              <button
                type="button"
                onClick={() => setViewMode('yaml')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition',
                  viewMode === 'yaml'
                    ? 'bg-zinc-900 text-white shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Code2 size={12} />
                {t('config.viewMode.yaml')}
              </button>
            </div>
            <Button
              size="sm"
              variant="ghost"
              disabled={saving}
              onClick={reload}
              title={t('config.ui.reloadTitle')}
            >
              <RotateCcw size={13} />
              {t('config.ui.reload')}
            </Button>
            {editable && (
              <Button size="sm" disabled={saving || autoSaving || !dirty} onClick={() => void saveYaml()}>
                <Save size={13} />
                {saving ? t('config.ui.saving') : dirty ? t('config.ui.save') : t('config.ui.upToDate')}
              </Button>
            )}
          </div>
        </div>

        {/* Path + metadata bar */}
        {meta && (
          <div className="border-border bg-muted/20 flex flex-wrap items-center gap-2 border-b px-4 py-2 text-[11px]">
            <code className="bg-background border-border break-all rounded border px-2 py-0.5 font-mono">
              {meta.path_display}
            </code>
            {!meta.exists && (
              <span className="text-amber-900">{t('config.file.missingHint')}</span>
            )}
            <a
              href={`vscode://file/${meta.path_display}`}
              className={buttonVariants({ variant: 'ghost', size: 'xs' })}
              title={t('config.ui.editorTitle')}
            >
              <ExternalLink size={11} />
              {t('config.ui.editor')}
            </a>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded px-2 py-0.5 hover:bg-background"
              onClick={() => {
                void navigator.clipboard
                  .writeText(meta.path_display)
                  .then(() => toast.success(t('common.pathCopied')))
                  .catch(() => toast.error(t('common.copyFailed')))
              }}
            >
              <Copy size={11} />
              {t('config.ui.copyPath')}
            </button>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 rounded px-2 py-0.5 hover:bg-background"
              onClick={() => {
                void navigator.clipboard
                  .writeText(rawText)
                  .then(() => toast.success(t('common.contentCopied')))
                  .catch(() => toast.error(t('common.copyFailed')))
              }}
            >
              <Copy size={11} />
              {t('config.ui.copyContent')}
            </button>
            <span className="ml-auto inline-flex items-center gap-1">
              {autoSaving ? (
                <span className="text-zinc-600 inline-flex items-center gap-1">
                  <Loader2 size={12} className="animate-spin" />
                  {t('config.ui.autosave')}
                </span>
              ) : dirty ? (
                <span className="text-amber-700">{t('config.ui.unsaved')}</span>
              ) : (
                <span className="text-emerald-700 inline-flex items-center gap-1">
                  <Check size={12} />
                  {t('config.ui.upToDate')}
                </span>
              )}
            </span>
          </div>
        )}

        {meta?.truncate_note && (
          <p className="border-border bg-amber-50 border-b px-4 py-1.5 text-[11px] text-amber-800">
            {t('config.ui.truncated', { note: meta.truncate_note })}
          </p>
        )}

        {viewMode === 'form' && !parsed.ok && (
          <div className="text-destructive border-border bg-red-50 border-b px-4 py-2 text-xs">
            {t('config.ui.invalidYaml', { error: parsed.error })}
          </div>
        )}

        {viewMode === 'form' && parsed.ok && yamlHasComments && dirty && (
          <p className="border-border bg-amber-50 border-b px-4 py-1.5 text-[11px] text-amber-800">
            {t('config.ui.commentsWarning')}
          </p>
        )}

        {/* Corps : sidebar + contenu */}
        {viewMode === 'form' && parsed.ok ? (
          <div className="grid gap-0 lg:grid-cols-[240px_1fr]">
            <aside className="border-border bg-muted/10 lg:border-r p-2">
              {groupedSections.length === 0 ? (
                <p className="text-muted-foreground p-3 text-xs">{t('config.ui.emptyFile')}</p>
              ) : (
                <nav className="space-y-3">
                  {groupedSections.map(({ group, keys }) => (
                    <div key={group}>
                      <p className="text-muted-foreground px-2 py-1 text-[10px] font-semibold uppercase tracking-wider">
                        {configGroupLabel(group, t)}
                      </p>
                      <ul className="space-y-0.5">
                        {keys.map((key) => {
                          const active = key === activeSection
                          const count = countItems(sectionValueByKey[key])
                          const syncStatus = syncStatusBySection[key]
                          return (
                            <li key={key}>
                              <button
                                type="button"
                                onClick={() => setActiveSection(key)}
                                className={cn(
                                  'flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-xs transition',
                                  active
                                    ? 'bg-zinc-900 text-white'
                                    : 'text-foreground hover:bg-muted',
                                )}
                              >
                                <span className="min-w-0 flex-1">
                                  <span className="block truncate">{configSectionLabel(key, t)}</span>
                                  {syncStatus ? (
                                    <span
                                      className={cn(
                                        'block truncate text-[10px]',
                                        active ? 'text-white/65' : 'text-muted-foreground',
                                      )}
                                    >
                                      {configSyncLabel(syncStatus, intlLocale, t, true)}
                                    </span>
                                  ) : null}
                                </span>
                                {count !== null && (
                                  <span
                                    className={cn(
                                      'ml-2 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold',
                                      active ? 'bg-white/15 text-white' : 'bg-muted text-muted-foreground',
                                    )}
                                  >
                                    {count}
                                  </span>
                                )}
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    </div>
                  ))}
                </nav>
              )}
            </aside>

            <section className="min-h-[40vh] p-4">
              {!activeSection || !(activeSection in sectionValueByKey) ? (
                <p className="text-muted-foreground text-sm italic">{t('config.ui.selectSection')}</p>
              ) : (
                <SectionPanel
                  sectionKey={activeSection}
                  value={sectionValueByKey[activeSection]}
                  onChange={(next) => updateSection(activeSection, next)}
                  readOnly={!editable || aggregatorStale}
                  secretHintsById={activeSection === 'task_sources' ? secretHintsById : undefined}
                  syncStatus={syncStatusBySection[activeSection]}
                  syncItemsById={syncItemsBySection[activeSection]}
                />
              )}
            </section>
          </div>
        ) : (
          <div className="p-4">
            <YamlEditor value={rawText} onChange={setRawText} readOnly={!editable} />
          </div>
        )}
      </div>
    </div>
  )
}

function SectionPanel({
  sectionKey,
  value,
  onChange,
  readOnly,
  secretHintsById,
  syncStatus,
  syncItemsById,
}: {
  sectionKey: string
  value: unknown
  onChange: (next: unknown) => void
  readOnly?: boolean
  secretHintsById?: Record<string, TaskSourceSecretLocation>
  syncStatus?: ConfigSyncStatus
  syncItemsById?: Record<string, ConfigSyncStatus>
}) {
  const { t } = useI18n()
  const description = configSectionDescription(sectionKey, t)
  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="text-lg font-semibold">{configSectionLabel(sectionKey, t)}</h3>
            <code className="text-muted-foreground font-mono text-[11px]">{sectionKey}</code>
            <span className="text-muted-foreground text-[11px]">{describeType(value, t)}</span>
          </div>
          {description ? (
            <p className="text-muted-foreground text-xs">{description}</p>
          ) : null}
        </div>
        {syncStatus ? <ConfigSyncBadge status={syncStatus} /> : null}
      </div>

      <div className="rounded-lg border border-border p-4">
        <FieldRenderer
          value={value}
          onChange={onChange}
          readOnly={readOnly}
          fieldKey={sectionKey}
          secretHintsById={secretHintsById}
          syncItemsById={syncItemsById}
        />
      </div>
    </div>
  )
}

function YamlEditor({
  value,
  onChange,
  readOnly,
}: {
  value: string
  onChange: (next: string) => void
  readOnly?: boolean
}) {
  const lines = value.split('\n').length
  const numbers = useMemo(
    () => Array.from({ length: Math.max(lines, 12) }, (_, i) => i + 1).join('\n'),
    [lines],
  )
  return (
    <div className="border-border flex max-h-[min(640px,70vh)] overflow-hidden rounded-lg border font-mono text-[11px] leading-relaxed">
      <pre
        aria-hidden
        className="bg-muted text-muted-foreground select-none whitespace-pre px-3 py-3 text-right"
      >
        {numbers}
      </pre>
      <Textarea
        data-testid="connectors-config-pre"
        spellCheck={false}
        readOnly={readOnly}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 rounded-none border-0 bg-background px-3 py-3 font-mono text-[11px] leading-relaxed focus-visible:ring-0"
      />
    </div>
  )
}
