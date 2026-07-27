// Taktline offline shell.
//
// Goal: a page reload while the server is down (reboot, free-tier cold start)
// still renders the app, which then shows its cached data + the amber outage
// banner. Strategy:
//   /assets/*, /uploads/*  → cache-first (content-hashed / timestamped names,
//                            so entries are immutable)
//   navigations            → network-first, falling back to the cached shell
// API calls are deliberately untouched — data-level caching lives in the app
// (localStorage snapshots), and mutations must always hit the real server.

const CACHE = 'taktline-shell-v1'

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key !== CACHE) await caches.delete(key)
    }
    await self.clients.claim()
  })())
})

async function cacheFirst(request) {
  const cache = await caches.open(CACHE)
  const hit = await cache.match(request)
  if (hit) return hit
  const res = await fetch(request)
  if (res.ok) cache.put(request, res.clone())
  return res
}

async function navigate(request) {
  const cache = await caches.open(CACHE)
  try {
    const res = await fetch(request)
    if (res.ok) cache.put('/__shell__', res.clone())
    return res
  } catch {
    const shell = await cache.match('/__shell__')
    return shell ?? Response.error()
  }
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/uploads/')) {
    event.respondWith(cacheFirst(request))
  } else if (request.mode === 'navigate') {
    event.respondWith(navigate(request))
  }
})
