/* Minimal installability service worker: pass-through, no caching.
   The app is server-backed; offline shell may come later. */
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return
  event.respondWith(fetch(event.request).catch(() => new Response('offline', { status: 503 })))
})
