// Service worker minimal : il met en cache la coquille de l'application pour que
// l'écran s'affiche instantanément et hors connexion. Les réponses de l'API ne
// sont jamais mises en cache — un état de VM périmé serait pire que pas d'état.

const CACHE = 'vm-shell-v3'
const SHELL = ['/', '/app.css', '/app.js', '/manifest.webmanifest', '/icons/icon-192.png']

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)
  if (request.method !== 'GET' || url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/') || url.pathname === '/ping') return

  // Réseau d'abord pour la coquille : une mise à jour déployée doit arriver
  // dès la première ouverture en ligne, le cache ne sert qu'en repli.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(CACHE).then((cache) => cache.put(request, copy))
        }
        return response
      })
      .catch(() => caches.match(request).then((hit) => hit || caches.match('/'))),
  )
})
