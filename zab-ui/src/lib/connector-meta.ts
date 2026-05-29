import {
  WorkflowCircle03Icon,
  NotionIcon,
  GoogleIcon,
  GoogleDriveIcon,
  Mail02Icon,
  Calendar03Icon,
  GithubIcon,
  GitlabIcon,
  SlackIcon,
  FigmaIcon,
  WhatsappIcon,
  WhatsappBusinessIcon,
  Linkedin02Icon,
  SpotifyIcon,
  CodeFolderIcon,
  Database02Icon,
  CloudServerIcon,
  McpServerIcon,
  Plug02Icon,
  PaintBoardIcon,
  BankIcon,
  Money01Icon,
  ReceiptDollarIcon,
  WorkflowCircle04Icon,
  Mail01Icon,
  Clapperboard,
  Image01Icon,
  GlobeIcon,
  RobotIcon,
  SparklesIcon,
  AiBrain02Icon,
  Microphone,
  Chart01Icon,
  ApiIcon,
  Calendar01Icon,
  Building01Icon,
  ToolsIcon,
  ExternalLink,
} from '@hugeicons/core-free-icons'

const LinearArrow01Icon = WorkflowCircle03Icon
const GmailIcon = Mail02Icon
const HubspotIcon = Linkedin02Icon
const Bank01Icon = BankIcon
const Money03Icon = Money01Icon
const DataflowDownIcon = WorkflowCircle04Icon
const WorkflowSquare03Icon = WorkflowCircle03Icon
const ClapperBoardIcon = Clapperboard
const Sparkles01Icon = SparklesIcon
const Tools01Icon = ToolsIcon
const ExternalLink04Icon = ExternalLink
const Brain02Icon = AiBrain02Icon
const Mic01Icon = Microphone
const ChartIcon = Chart01Icon
const CalendarBlock01Icon = Calendar01Icon
const PaintBucketIcon = PaintBoardIcon

import type { IconSvgElement } from '@hugeicons/react'

export type ConnectorMeta = {
  label: string
  icon: IconSvgElement
  tone: string
  ringTone: string
  description?: string
  href?: string
}

const fallback: ConnectorMeta = {
  label: 'MCP',
  icon: McpServerIcon,
  tone: 'bg-zinc-100 text-zinc-700',
  ringTone: 'ring-zinc-200',
}

export function connectorMeta(rawName: string): ConnectorMeta {
  const name = rawName.toLowerCase().replace(/^_todo[-_]/, '').replace(/[-_]+/g, ' ').trim()
  const has = (...words: string[]) => words.some((w) => name.includes(w))

  if (has('linear')) return { label: 'Linear', icon: LinearArrow01Icon, tone: 'bg-violet-100 text-violet-700', ringTone: 'ring-violet-200' }
  if (has('notion')) return { label: 'Notion', icon: NotionIcon, tone: 'bg-zinc-100 text-zinc-900', ringTone: 'ring-zinc-200' }
  if (has('gmail', 'mail')) return { label: 'Gmail', icon: GmailIcon, tone: 'bg-rose-100 text-rose-600', ringTone: 'ring-rose-200' }
  if (has('drive', 'gdrive')) return { label: 'Google Drive', icon: GoogleDriveIcon, tone: 'bg-emerald-100 text-emerald-700', ringTone: 'ring-emerald-200' }
  if (has('calendar', 'gcal')) return { label: 'Google Calendar', icon: Calendar03Icon, tone: 'bg-sky-100 text-sky-700', ringTone: 'ring-sky-200' }
  if (has('google')) return { label: 'Google', icon: GoogleIcon, tone: 'bg-amber-100 text-amber-700', ringTone: 'ring-amber-200' }
  if (has('github')) return { label: 'GitHub', icon: GithubIcon, tone: 'bg-zinc-900 text-white', ringTone: 'ring-zinc-300' }
  if (has('gitlab')) return { label: 'GitLab', icon: GitlabIcon, tone: 'bg-orange-100 text-orange-700', ringTone: 'ring-orange-200' }
  if (has('slack')) return { label: 'Slack', icon: SlackIcon, tone: 'bg-fuchsia-100 text-fuchsia-700', ringTone: 'ring-fuchsia-200' }
  if (has('figma')) return { label: 'Figma', icon: FigmaIcon, tone: 'bg-rose-100 text-rose-600', ringTone: 'ring-rose-200' }
  if (has('whatsapp business')) return { label: 'WhatsApp Business', icon: WhatsappBusinessIcon, tone: 'bg-emerald-100 text-emerald-700', ringTone: 'ring-emerald-200' }
  if (has('whatsapp', 'evolution')) return { label: 'WhatsApp', icon: WhatsappIcon, tone: 'bg-emerald-100 text-emerald-700', ringTone: 'ring-emerald-200' }
  if (has('hubspot')) return { label: 'HubSpot', icon: HubspotIcon, tone: 'bg-orange-100 text-orange-700', ringTone: 'ring-orange-200' }
  if (has('spotify')) return { label: 'Spotify', icon: SpotifyIcon, tone: 'bg-emerald-100 text-emerald-700', ringTone: 'ring-emerald-200' }
  if (has('fireflies', 'transcript')) return { label: 'Fireflies', icon: Mic01Icon, tone: 'bg-amber-100 text-amber-700', ringTone: 'ring-amber-200' }
  if (has('gamma')) return { label: 'Gamma', icon: Sparkles01Icon, tone: 'bg-fuchsia-100 text-fuchsia-700', ringTone: 'ring-fuchsia-200' }
  if (has('apify', 'scrape', 'crawl')) return { label: 'Apify', icon: GlobeIcon, tone: 'bg-emerald-100 text-emerald-700', ringTone: 'ring-emerald-200' }
  if (has('hugeicon', 'icons')) return { label: 'HugeIcons', icon: PaintBucketIcon, tone: 'bg-violet-100 text-violet-700', ringTone: 'ring-violet-200' }
  if (has('qonto', 'banking', 'bank')) return { label: rawName.includes('qonto') ? 'Qonto' : 'Banque', icon: Bank01Icon, tone: 'bg-indigo-100 text-indigo-700', ringTone: 'ring-indigo-200' }
  if (has('pennylane', 'compta', 'invoice', 'facture')) return { label: rawName.includes('pennylane') ? 'Pennylane' : 'Comptabilité', icon: ReceiptDollarIcon, tone: 'bg-amber-100 text-amber-700', ringTone: 'ring-amber-200' }
  if (has('pexels', 'image', 'photo')) return { label: 'Pexels', icon: Image01Icon, tone: 'bg-teal-100 text-teal-700', ringTone: 'ring-teal-200' }
  if (has('supabase', 'database', 'postgres', 'sql')) return { label: rawName.includes('supabase') ? 'Supabase' : 'Database', icon: Database02Icon, tone: 'bg-emerald-100 text-emerald-700', ringTone: 'ring-emerald-200' }
  if (has('flowmetrik', 'gateway')) return { label: 'Flowmetrik', icon: WorkflowSquare03Icon, tone: 'bg-blue-100 text-blue-700', ringTone: 'ring-blue-200' }
  if (has('cowork')) return { label: 'Cowork', icon: Brain02Icon, tone: 'bg-violet-100 text-violet-700', ringTone: 'ring-violet-200' }
  if (has('clay', 'enrich', 'prospect', 'mipim')) return { label: 'Prospection', icon: ChartIcon, tone: 'bg-orange-100 text-orange-700', ringTone: 'ring-orange-200' }
  if (has('memory')) return { label: 'Memory', icon: Brain02Icon, tone: 'bg-fuchsia-100 text-fuchsia-700', ringTone: 'ring-fuchsia-200' }
  if (has('http', 'api', 'webhook')) return { label: 'HTTP/API', icon: ApiIcon, tone: 'bg-sky-100 text-sky-700', ringTone: 'ring-sky-200' }
  return fallback
}

export function kindMeta(kind: string): { icon: IconSvgElement; tone: string; label: string } {
  switch (kind) {
    case 'stdio':
      return { icon: CodeFolderIcon, tone: 'bg-zinc-100 text-zinc-700', label: 'stdio' }
    case 'http':
      return { icon: CloudServerIcon, tone: 'bg-sky-100 text-sky-700', label: 'http' }
    case 'sse':
      return { icon: DataflowDownIcon, tone: 'bg-violet-100 text-violet-700', label: 'sse' }
    case 'composio':
      return { icon: Plug02Icon, tone: 'bg-fuchsia-100 text-fuchsia-700', label: 'composio' }
    default:
      return { icon: Plug02Icon, tone: 'bg-zinc-100 text-zinc-500', label: kind || '—' }
  }
}

export const skillOrgIcon: Record<string, { icon: IconSvgElement; tone: string }> = {
  flowmetrik: { icon: WorkflowSquare03Icon, tone: 'bg-blue-100 text-blue-700' },
  carrefour: { icon: Building01Icon, tone: 'bg-rose-100 text-rose-700' },
  upfund: { icon: CodeFolderIcon, tone: 'bg-amber-100 text-amber-800' },
  'hors-org': { icon: GlobeIcon, tone: 'bg-zinc-100 text-zinc-600' },
  celeste: { icon: Sparkles01Icon, tone: 'bg-fuchsia-100 text-fuchsia-700' },
  'arp-astrance': { icon: Building01Icon, tone: 'bg-amber-100 text-amber-700' },
  tara: { icon: Sparkles01Icon, tone: 'bg-pink-100 text-pink-700' },
  'mehdi-hub': { icon: Brain02Icon, tone: 'bg-violet-100 text-violet-700' },
  perso: { icon: Brain02Icon, tone: 'bg-emerald-100 text-emerald-700' },
}

export function skillIconFor(orgName: string, skillId: string): { icon: IconSvgElement; tone: string } {
  const id = skillId.toLowerCase()
  if (id.includes('whatsapp')) return { icon: WhatsappIcon, tone: 'bg-emerald-100 text-emerald-700' }
  if (id.includes('calendar') || id.includes('vcard')) return { icon: CalendarBlock01Icon, tone: 'bg-sky-100 text-sky-700' }
  if (id.includes('mail') || id.includes('email')) return { icon: Mail01Icon, tone: 'bg-rose-100 text-rose-700' }
  if (id.includes('bank') || id.includes('qonto')) return { icon: Bank01Icon, tone: 'bg-indigo-100 text-indigo-700' }
  if (id.includes('compta') || id.includes('pennylane') || id.includes('facture')) return { icon: ReceiptDollarIcon, tone: 'bg-amber-100 text-amber-700' }
  if (id.includes('outils') || id.includes('tools')) return { icon: Tools01Icon, tone: 'bg-zinc-100 text-zinc-700' }
  if (id.includes('plaquette') || id.includes('docx') || id.includes('pptx')) return { icon: ClapperBoardIcon, tone: 'bg-fuchsia-100 text-fuchsia-700' }
  if (id.includes('prospect') || id.includes('mipim') || id.includes('outreach')) return { icon: ChartIcon, tone: 'bg-orange-100 text-orange-700' }
  if (id.includes('cockpit') || id.includes('router')) return { icon: WorkflowSquare03Icon, tone: 'bg-blue-100 text-blue-700' }
  if (id.includes('branding')) return { icon: PaintBucketIcon, tone: 'bg-pink-100 text-pink-700' }
  if (id.includes('context') || id.endsWith('-base')) return { icon: Brain02Icon, tone: 'bg-violet-100 text-violet-700' }
  return skillOrgIcon[orgName] ?? { icon: Sparkles01Icon, tone: 'bg-zinc-100 text-zinc-700' }
}

export const ExternalIcon = ExternalLink04Icon
export const RobotFallbackIcon = RobotIcon
export const Money = Money03Icon
