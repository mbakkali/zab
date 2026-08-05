'use strict'

const TOKEN_KEY = 'zab.remote.token'
const POLL_IDLE_MS = 20000
const POLL_BUSY_MS = 4000

const el = (id) => document.getElementById(id)
const app = el('app')
const login = el('login')

let token = null
let timer = null
let sessionSeconds = null
let clock = null
let lastStatus = null

/** Le lien de liaison porte le jeton en fragment : jamais envoyé au serveur, et retiré aussitôt. */
function captureTokenFromUrl() {
  const hash = window.location.hash || ''
  const match = hash.match(/[#&]t=([^&]+)/)
  if (!match) return null
  const value = decodeURIComponent(match[1])
  history.replaceState(null, '', window.location.pathname)
  return value
}

function readToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function storeToken(value) {
  try {
    if (value) window.localStorage.setItem(TOKEN_KEY, value)
    else window.localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* navigation privée : on reste en mémoire pour la session */
  }
  token = value
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
  })
  if (response.status === 401) {
    storeToken(null)
    showLogin('Jeton refusé. Colle un jeton valide.')
    throw new Error('unauthorized')
  }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body && (body.detail || body)
    throw new Error((detail && (detail.error || detail.message)) || `HTTP ${response.status}`)
  }
  return body
}

function showLogin(message) {
  stopPolling()
  app.hidden = true
  login.hidden = false
  const error = el('login-error')
  error.textContent = message || ''
  error.hidden = !message
}

function showApp() {
  login.hidden = true
  app.hidden = false
}

function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')}`
  const s = Math.floor(seconds % 60)
  return `${m} min ${String(s).padStart(2, '0')}`
}

function money(value, currency) {
  if (value == null) return '—'
  try {
    return new Intl.NumberFormat('fr-FR', { style: 'currency', currency: currency || 'EUR' }).format(value)
  } catch {
    return `${value}`
  }
}

function setPill(text, tone) {
  const pill = el('state')
  pill.textContent = text
  pill.className = `pill pill-${tone}`
}

function renderJobBanner(job, busy) {
  const banner = el('banner')
  if (!job) {
    banner.hidden = true
    return
  }
  const labels = {
    start: 'Démarrage de la VM et reprise de la synchronisation',
    'sync-flush': 'Convergence forcée de la synchronisation',
    'sync-resume': 'Reprise des sessions de synchronisation',
    'sync-pause': 'Mise en pause des sessions',
  }
  const label = labels[job.action] || job.action
  // Une réussite ancienne n'apprend plus rien : on la laisse quelques instants
  // pour l'accusé de réception, puis on rend la place. Un échec, lui, reste.
  if (job.state === 'done' && job.finished_at) {
    const age = (Date.now() - Date.parse(job.finished_at)) / 1000
    if (Number.isFinite(age) && age > 120) {
      banner.hidden = true
      return
    }
  }
  banner.hidden = false
  if (busy || job.state === 'running') {
    banner.className = 'banner banner-busy'
    banner.innerHTML = `<span class="spin"></span>${label}… quelques minutes.`
    return
  }
  if (job.state === 'failed') {
    banner.className = 'banner banner-error'
    banner.textContent = `${label} : échec. ${job.error || ''}`.trim()
    return
  }
  banner.className = 'banner'
  banner.textContent = `${label} : terminé.`
}

function renderStatus(data) {
  lastStatus = data
  const vm = data.vm || {}
  const ssh = data.ssh || {}
  const sync = data.sync || {}
  const totals = sync.totals || {}
  const busy = Boolean(data.busy)
  const running = String(vm.status || '').toUpperCase() === 'RUNNING'

  if (busy) setPill('EN COURS', 'busy')
  else if (running) setPill('ALLUMÉE', 'running')
  else if (vm.status) setPill(String(vm.status), vm.found === false ? 'error' : 'idle')
  else setPill('—', 'error')

  sessionSeconds = running ? vm.session_seconds ?? null : null
  renderSubtitle(vm)
  renderJobBanner(data.job, busy)

  const primary = el('primary')
  primary.disabled = busy || running
  primary.textContent = busy ? 'Action en cours…' : running ? 'VM déjà allumée' : 'Démarrer la VM'
  primary.className = 'action'

  el('flush').disabled = busy || !running

  // Un serveur distant ne peut pas voir la sync ni les connexions SSH du Mac :
  // afficher « 0 » se lirait comme « rien ne tourne » au lieu de « je ne sais pas ».
  const connected = totals.watching ?? 0
  const sessions = totals.sessions ?? 0
  if (sync.observable === false) {
    el('sync-value').textContent = 'n/d'
    el('sync-hint').textContent = 'non visible depuis ce serveur'
  } else {
    el('sync-value').textContent = sessions ? `${connected}/${sessions}` : '—'
    el('sync-hint').textContent = sessions
      ? `${(totals.alpha_files ?? 0).toLocaleString('fr-FR')} fichiers · écart ${totals.file_delta ?? 0}${
          totals.conflicts ? ` · ${totals.conflicts} conflit(s)` : ''
        }`
      : sync.error || 'aucune session'
  }

  if (ssh.observable === false) {
    el('ssh-value').textContent = 'n/d'
    el('ssh-hint').textContent = 'non visible depuis ce serveur'
  } else {
    el('ssh-value').textContent = String((ssh.connections || []).length)
    el('ssh-hint').textContent = `${ssh.tunnels ?? 0} tunnel · ${ssh.sync_agents ?? 0} agent(s) sync`
  }

  // Sans mutagen local, forcer un cycle de sync n'a aucun sens.
  el('flush').hidden = sync.observable === false

  el('updated').textContent = `mis à jour ${new Date().toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })}`
}

function renderSubtitle(vm) {
  const parts = []
  if (vm.instance) parts.push(vm.instance)
  if (vm.machine_type) parts.push(vm.machine_type)
  const base = parts.join(' · ') || 'VM'
  el('subtitle').textContent =
    sessionSeconds != null ? `${base} · allumée depuis ${formatDuration(sessionSeconds)}` : base
}

function renderCost(data) {
  const totals = data.totals || {}
  const currency = data.currency || 'EUR'
  el('cost-value').textContent = money(totals.mtd_cost, currency)
  el('cost-hint').textContent =
    totals.month_projection != null
      ? `projection ${money(totals.month_projection, currency)}`
      : data.error || '—'
  el('hours-value').textContent = totals.mtd_hours != null ? `${totals.mtd_hours.toFixed(1)} h` : '—'
  el('hours-hint').textContent =
    totals.hourly_rate != null ? `${money(totals.hourly_rate, currency)}/h allumée` : '—'
}

function offline(message) {
  const banner = el('banner')
  banner.hidden = false
  banner.className = 'banner banner-error'
  banner.textContent = message
}

async function refresh() {
  try {
    const data = await api('/api/status')
    renderStatus(data)
    schedule(data.busy ? POLL_BUSY_MS : POLL_IDLE_MS)
  } catch (error) {
    if (error.message === 'unauthorized') return
    offline('Serveur injoignable. Le Mac qui héberge le tunnel est peut-être éteint.')
    schedule(POLL_IDLE_MS)
  }
}

async function refreshCost() {
  try {
    renderCost(await api('/api/cost'))
  } catch {
    /* le coût est secondaire : on garde l'affichage précédent */
  }
}

function schedule(delay) {
  window.clearTimeout(timer)
  timer = window.setTimeout(refresh, delay)
}

function stopPolling() {
  window.clearTimeout(timer)
  window.clearInterval(clock)
}

async function act(path, confirmMessage) {
  if (confirmMessage && !window.confirm(confirmMessage)) return
  el('primary').disabled = true
  try {
    const body = await api(path, { method: 'POST' })
    renderJobBanner(body.job, true)
    schedule(1500)
  } catch (error) {
    if (error.message !== 'unauthorized') offline(error.message)
    el('primary').disabled = false
  }
}

function showView(name) {
  el('view-vm').hidden = name !== 'vm'
  for (const section of document.querySelectorAll('#views-apps > section')) {
    section.hidden = section.dataset.view !== name
  }
  for (const tab of document.querySelectorAll('#tabs .tab')) {
    tab.classList.toggle('tab-on', tab.dataset.view === name)
  }
}

async function loadAppTabs() {
  // Les onglets n'apparaissent que si des applications sont effectivement
  // configurées côté serveur : sur un déploiement qui n'en a pas, la barre
  // reste invisible plutôt que d'offrir un bouton qui mène à une erreur.
  try {
    const info = await api('/api/apps')
    const apps = (info && info.apps) || []
    if (!apps.length) return
    const tabs = el('tabs')
    const views = el('views-apps')
    for (const entry of apps) {
      const tab = document.createElement('button')
      tab.className = 'tab'
      tab.type = 'button'
      tab.dataset.view = entry.slug
      tab.textContent = entry.label
      tab.addEventListener('click', () => showView(entry.slug))
      tabs.append(tab)

      const section = document.createElement('section')
      section.dataset.view = entry.slug
      section.hidden = true
      const note = document.createElement('p')
      note.className = 'muted'
      note.textContent =
        'Cette application tourne sur la VM. Elle n’est joignable que lorsqu’elle ' +
        'est allumée : démarre-la depuis l’onglet VM si la page reste vide.'
      const link = document.createElement('a')
      link.className = 'action'
      link.href = entry.path
      link.textContent = `Ouvrir ${entry.label}`
      section.append(note, link)
      views.append(section)
    }
    tabs.hidden = false
  } catch (error) {
    if (error.message === 'unauthorized') throw error
  }
}

function wire() {
  el('tab-vm').addEventListener('click', () => showView('vm'))
  el('primary').addEventListener('click', () => act('/api/start'))
  el('flush').addEventListener('click', () => act('/api/sync-action?action=sync-flush'))
  el('refresh').addEventListener('click', () => refresh())
  el('forget').addEventListener('click', () => {
    storeToken(null)
    showLogin('Jeton oublié sur cet appareil.')
  })

  login.addEventListener('submit', (event) => {
    event.preventDefault()
    const value = el('token').value.trim()
    if (!value) return
    storeToken(value)
    el('token').value = ''
    start()
  })

  // Revenir sur l'app depuis l'écran d'accueil doit montrer un état frais, pas celui d'hier.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && token) refresh()
  })
}

function start() {
  if (!token) {
    showLogin()
    return
  }
  showApp()
  stopPolling()
  clock = window.setInterval(() => {
    if (sessionSeconds != null) {
      sessionSeconds += 1
      renderSubtitle((lastStatus && lastStatus.vm) || {})
    }
  }, 1000)
  refresh()
  refreshCost()
  loadAppTabs().catch(() => {})
  window.setInterval(refreshCost, 5 * 60 * 1000)
}

const linked = captureTokenFromUrl()
if (linked) storeToken(linked)
else token = readToken()
wire()
start()

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}))
}
