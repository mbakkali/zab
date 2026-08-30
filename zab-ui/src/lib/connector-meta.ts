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
  tone: 'bg-muted text-foreground',
  ringTone: 'ring-ring/40',
}

export function connectorMeta(rawName: string): ConnectorMeta {
  const name = rawName.toLowerCase().replace(/^_todo[-_]/, '').replace(/[-_]+/g, ' ').trim()
  const has = (...words: string[]) => words.some((w) => name.includes(w))

  if (has('linear')) return { label: 'Linear', icon: LinearArrow01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('notion')) return { label: 'Notion', icon: NotionIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('gmail', 'mail')) return { label: 'Gmail', icon: GmailIcon, tone: 'bg-danger/10 text-danger', ringTone: 'ring-danger/35' }
  if (has('drive', 'gdrive')) return { label: 'Google Drive', icon: GoogleDriveIcon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('calendar', 'gcal')) return { label: 'Google Calendar', icon: Calendar03Icon, tone: 'bg-info/10 text-info', ringTone: 'ring-info/35' }
  if (has('google')) return { label: 'Google', icon: GoogleIcon, tone: 'bg-alerte/10 text-alerte', ringTone: 'ring-alerte/35' }
  if (has('github')) return { label: 'GitHub', icon: GithubIcon, tone: 'bg-primary text-primary-foreground', ringTone: 'ring-ring/40' }
  if (has('gitlab')) return { label: 'GitLab', icon: GitlabIcon, tone: 'bg-alerte/10 text-alerte', ringTone: 'ring-alerte/35' }
  if (has('slack')) return { label: 'Slack', icon: SlackIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('figma')) return { label: 'Figma', icon: FigmaIcon, tone: 'bg-danger/10 text-danger', ringTone: 'ring-danger/35' }
  if (has('whatsapp business')) return { label: 'WhatsApp Business', icon: WhatsappBusinessIcon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('whatsapp', 'evolution')) return { label: 'WhatsApp', icon: WhatsappIcon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('hubspot')) return { label: 'HubSpot', icon: HubspotIcon, tone: 'bg-alerte/10 text-alerte', ringTone: 'ring-alerte/35' }
  if (has('spotify')) return { label: 'Spotify', icon: SpotifyIcon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('fireflies', 'transcript')) return { label: 'Fireflies', icon: Mic01Icon, tone: 'bg-alerte/10 text-alerte', ringTone: 'ring-alerte/35' }
  if (has('gamma')) return { label: 'Gamma', icon: Sparkles01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('apify', 'scrape', 'crawl')) return { label: 'Apify', icon: GlobeIcon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('hugeicon', 'icons')) return { label: 'HugeIcons', icon: PaintBucketIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('qonto', 'banking', 'bank')) return { label: rawName.includes('qonto') ? 'Qonto' : 'Banque', icon: Bank01Icon, tone: 'bg-info/10 text-info', ringTone: 'ring-info/35' }
  if (has('pennylane', 'compta', 'invoice', 'facture')) return { label: rawName.includes('pennylane') ? 'Pennylane' : 'Comptabilité', icon: ReceiptDollarIcon, tone: 'bg-alerte/10 text-alerte', ringTone: 'ring-alerte/35' }
  if (has('pexels', 'image', 'photo')) return { label: 'Pexels', icon: Image01Icon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('supabase', 'database', 'postgres', 'sql')) return { label: rawName.includes('supabase') ? 'Supabase' : 'Database', icon: Database02Icon, tone: 'bg-succes/10 text-succes', ringTone: 'ring-succes/35' }
  if (has('flowmetrik', 'gateway')) return { label: 'Flowmetrik', icon: WorkflowSquare03Icon, tone: 'bg-info/10 text-info', ringTone: 'ring-info/35' }
  if (has('cowork')) return { label: 'Cowork', icon: Brain02Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('clay', 'enrich', 'prospect', 'mipim')) return { label: 'Prospection', icon: ChartIcon, tone: 'bg-alerte/10 text-alerte', ringTone: 'ring-alerte/35' }
  if (has('memory')) return { label: 'Memory', icon: Brain02Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-ring/40' }
  if (has('http', 'api', 'webhook')) return { label: 'HTTP/API', icon: ApiIcon, tone: 'bg-info/10 text-info', ringTone: 'ring-info/35' }
  return fallback
}

export function kindMeta(kind: string): { icon: IconSvgElement; tone: string; label: string } {
  switch (kind) {
    case 'stdio':
      return { icon: CodeFolderIcon, tone: 'bg-muted text-foreground', label: 'stdio' }
    case 'http':
      return { icon: CloudServerIcon, tone: 'bg-info/10 text-info', label: 'http' }
    case 'sse':
      return { icon: DataflowDownIcon, tone: 'bg-muted text-foreground', label: 'sse' }
    case 'composio':
      return { icon: Plug02Icon, tone: 'bg-muted text-foreground', label: 'composio' }
    default:
      return { icon: Plug02Icon, tone: 'bg-muted text-muted-foreground', label: kind || '—' }
  }
}

export const skillOrgIcon: Record<string, { icon: IconSvgElement; tone: string }> = {
  flowmetrik: { icon: WorkflowSquare03Icon, tone: 'bg-info/10 text-info' },
  carrefour: { icon: Building01Icon, tone: 'bg-danger/10 text-danger' },
  upfund: { icon: CodeFolderIcon, tone: 'bg-alerte/10 text-alerte' },
  'hors-org': { icon: GlobeIcon, tone: 'bg-muted text-muted-foreground' },
  celeste: { icon: Sparkles01Icon, tone: 'bg-muted text-foreground' },
  'arp-astrance': { icon: Building01Icon, tone: 'bg-alerte/10 text-alerte' },
  tara: { icon: Sparkles01Icon, tone: 'bg-muted text-foreground' },
  'mehdi-hub': { icon: Brain02Icon, tone: 'bg-muted text-foreground' },
  perso: { icon: Brain02Icon, tone: 'bg-succes/10 text-succes' },
}

export function skillIconFor(orgName: string, skillId: string): { icon: IconSvgElement; tone: string } {
  const id = skillId.toLowerCase()
  if (id.includes('whatsapp')) return { icon: WhatsappIcon, tone: 'bg-succes/10 text-succes' }
  if (id.includes('calendar') || id.includes('vcard')) return { icon: CalendarBlock01Icon, tone: 'bg-info/10 text-info' }
  if (id.includes('mail') || id.includes('email')) return { icon: Mail01Icon, tone: 'bg-danger/10 text-danger' }
  if (id.includes('bank') || id.includes('qonto')) return { icon: Bank01Icon, tone: 'bg-info/10 text-info' }
  if (id.includes('compta') || id.includes('pennylane') || id.includes('facture')) return { icon: ReceiptDollarIcon, tone: 'bg-alerte/10 text-alerte' }
  if (id.includes('outils') || id.includes('tools')) return { icon: Tools01Icon, tone: 'bg-muted text-foreground' }
  if (id.includes('plaquette') || id.includes('docx') || id.includes('pptx')) return { icon: ClapperBoardIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('prospect') || id.includes('mipim') || id.includes('outreach')) return { icon: ChartIcon, tone: 'bg-alerte/10 text-alerte' }
  if (id.includes('cockpit') || id.includes('router')) return { icon: WorkflowSquare03Icon, tone: 'bg-info/10 text-info' }
  if (id.includes('branding')) return { icon: PaintBucketIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('context') || id.endsWith('-base')) return { icon: Brain02Icon, tone: 'bg-muted text-foreground' }
  return skillOrgIcon[orgName] ?? { icon: Sparkles01Icon, tone: 'bg-muted text-foreground' }
}

export const ExternalIcon = ExternalLink04Icon
export const RobotFallbackIcon = RobotIcon
export const Money = Money03Icon
