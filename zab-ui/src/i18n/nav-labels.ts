import type { NavId } from '@/components/sidebar-nav'

/** i18n key per nav tab (under `nav.*`). */
export const NAV_I18N_KEY: Record<NavId, string> = {
  overview: 'nav.overview',
  system_check: 'nav.systemCheck',
  orgs: 'nav.orgs',
  projects: 'nav.projects',
  tasks_inbox: 'nav.tasksInbox',
  channels: 'nav.channels',
  conversations: 'nav.conversations',
  plugins: 'nav.plugins',
  connectors: 'nav.connectors',
  config: 'nav.config',
  tests: 'nav.tests',
  security: 'nav.security',
  exports: 'nav.exports',
  memory: 'nav.memory',
  ide: 'nav.ide',
  models: 'nav.models',
  workstation: 'nav.workstation',
  hermes: 'nav.hermes',
  skills: 'nav.skills',
  crons: 'nav.cronsFull',
}
