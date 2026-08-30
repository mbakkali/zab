/* Pastilles de connecteurs — NEUTRES, et c'est une décision.
 *
 * Chaque service portait ici la couleur de sa marque : Linear violet, Drive
 * vert, Gmail rose, GitHub noir. Cinquante-quatre teintes sur un écran font un
 * arc-en-ciel, là où la charte Flowmetrik est noir et blanc et plafonne
 * l'accent à ~5 % de la surface.
 *
 * L'icône identifie déjà le service : la couleur ne faisait que le répéter.
 * Les rétablir suppose de les traiter comme des marques tierces — un hex de
 * marque, pas une classe de palette Tailwind — et de décider que l'exception
 * vaut la dérogation. Ce n'était pas le cas ici.
 */

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
  ringTone: 'ring-border',
}

export function connectorMeta(rawName: string): ConnectorMeta {
  const name = rawName.toLowerCase().replace(/^_todo[-_]/, '').replace(/[-_]+/g, ' ').trim()
  const has = (...words: string[]) => words.some((w) => name.includes(w))

  if (has('linear')) return { label: 'Linear', icon: LinearArrow01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('notion')) return { label: 'Notion', icon: NotionIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('gmail', 'mail')) return { label: 'Gmail', icon: GmailIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('drive', 'gdrive')) return { label: 'Google Drive', icon: GoogleDriveIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('calendar', 'gcal')) return { label: 'Google Calendar', icon: Calendar03Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('google')) return { label: 'Google', icon: GoogleIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('github')) return { label: 'GitHub', icon: GithubIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('gitlab')) return { label: 'GitLab', icon: GitlabIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('slack')) return { label: 'Slack', icon: SlackIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('figma')) return { label: 'Figma', icon: FigmaIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('whatsapp business')) return { label: 'WhatsApp Business', icon: WhatsappBusinessIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('whatsapp', 'evolution')) return { label: 'WhatsApp', icon: WhatsappIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('hubspot')) return { label: 'HubSpot', icon: HubspotIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('spotify')) return { label: 'Spotify', icon: SpotifyIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('fireflies', 'transcript')) return { label: 'Fireflies', icon: Mic01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('gamma')) return { label: 'Gamma', icon: Sparkles01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('apify', 'scrape', 'crawl')) return { label: 'Apify', icon: GlobeIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('hugeicon', 'icons')) return { label: 'HugeIcons', icon: PaintBucketIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('qonto', 'banking', 'bank')) return { label: rawName.includes('qonto') ? 'Qonto' : 'Banque', icon: Bank01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('pennylane', 'compta', 'invoice', 'facture')) return { label: rawName.includes('pennylane') ? 'Pennylane' : 'Comptabilité', icon: ReceiptDollarIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('pexels', 'image', 'photo')) return { label: 'Pexels', icon: Image01Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('supabase', 'database', 'postgres', 'sql')) return { label: rawName.includes('supabase') ? 'Supabase' : 'Database', icon: Database02Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('flowmetrik', 'gateway')) return { label: 'Flowmetrik', icon: WorkflowSquare03Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('cowork')) return { label: 'Cowork', icon: Brain02Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('clay', 'enrich', 'prospect', 'mipim')) return { label: 'Prospection', icon: ChartIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('memory')) return { label: 'Memory', icon: Brain02Icon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  if (has('http', 'api', 'webhook')) return { label: 'HTTP/API', icon: ApiIcon, tone: 'bg-muted text-foreground', ringTone: 'ring-border' }
  return fallback
}

export function kindMeta(kind: string): { icon: IconSvgElement; tone: string; label: string } {
  switch (kind) {
    case 'stdio':
      return { icon: CodeFolderIcon, tone: 'bg-muted text-foreground', label: 'stdio' }
    case 'http':
      return { icon: CloudServerIcon, tone: 'bg-muted text-foreground', label: 'http' }
    case 'sse':
      return { icon: DataflowDownIcon, tone: 'bg-muted text-foreground', label: 'sse' }
    case 'composio':
      return { icon: Plug02Icon, tone: 'bg-muted text-foreground', label: 'composio' }
    default:
      return { icon: Plug02Icon, tone: 'bg-muted text-foreground', label: kind || '—' }
  }
}

export const skillOrgIcon: Record<string, { icon: IconSvgElement; tone: string }> = {
  flowmetrik: { icon: WorkflowSquare03Icon, tone: 'bg-muted text-foreground' },
  carrefour: { icon: Building01Icon, tone: 'bg-muted text-foreground' },
  upfund: { icon: CodeFolderIcon, tone: 'bg-muted text-foreground' },
  'hors-org': { icon: GlobeIcon, tone: 'bg-muted text-foreground' },
  celeste: { icon: Sparkles01Icon, tone: 'bg-muted text-foreground' },
  'arp-astrance': { icon: Building01Icon, tone: 'bg-muted text-foreground' },
  tara: { icon: Sparkles01Icon, tone: 'bg-muted text-foreground' },
  'mehdi-hub': { icon: Brain02Icon, tone: 'bg-muted text-foreground' },
  perso: { icon: Brain02Icon, tone: 'bg-muted text-foreground' },
}

export function skillIconFor(orgName: string, skillId: string): { icon: IconSvgElement; tone: string } {
  const id = skillId.toLowerCase()
  if (id.includes('whatsapp')) return { icon: WhatsappIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('calendar') || id.includes('vcard')) return { icon: CalendarBlock01Icon, tone: 'bg-muted text-foreground' }
  if (id.includes('mail') || id.includes('email')) return { icon: Mail01Icon, tone: 'bg-muted text-foreground' }
  if (id.includes('bank') || id.includes('qonto')) return { icon: Bank01Icon, tone: 'bg-muted text-foreground' }
  if (id.includes('compta') || id.includes('pennylane') || id.includes('facture')) return { icon: ReceiptDollarIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('outils') || id.includes('tools')) return { icon: Tools01Icon, tone: 'bg-muted text-foreground' }
  if (id.includes('plaquette') || id.includes('docx') || id.includes('pptx')) return { icon: ClapperBoardIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('prospect') || id.includes('mipim') || id.includes('outreach')) return { icon: ChartIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('cockpit') || id.includes('router')) return { icon: WorkflowSquare03Icon, tone: 'bg-muted text-foreground' }
  if (id.includes('branding')) return { icon: PaintBucketIcon, tone: 'bg-muted text-foreground' }
  if (id.includes('context') || id.endsWith('-base')) return { icon: Brain02Icon, tone: 'bg-muted text-foreground' }
  return skillOrgIcon[orgName] ?? { icon: Sparkles01Icon, tone: 'bg-muted text-foreground' }
}

export const ExternalIcon = ExternalLink04Icon
export const RobotFallbackIcon = RobotIcon
export const Money = Money03Icon
