const CACHE_NAME = 'fetch-v3';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/favicon.svg',
  '/static/icon-192.png',
  '/static/icon-512.png',
];

// Install: cache statik dosyaları
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: eski cache'leri temizle
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: Stale-while-revalidate stratejisi
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // API isteklerini her zaman ağdan al (cache'leme)
  if (url.pathname.startsWith('/api/')) return;

  // SSE stream'lerini atlat
  if (url.pathname.startsWith('/api/stream')) return;

  // Statik dosyalar: stale-while-revalidate
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    e.respondWith(
      caches.open(CACHE_NAME).then(cache => {
        return cache.match(e.request).then(cachedResponse => {
          const fetchPromise = fetch(e.request).then(networkResponse => {
            if (networkResponse.ok) {
              cache.put(e.request, networkResponse.clone());
            }
            return networkResponse;
          }).catch(() => cachedResponse);

          // Önce cache'den döndür, arka planda güncelle
          return cachedResponse || fetchPromise;
        });
      })
    );
    return;
  }

  // Diğer istekler: network-first
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});

// Push notification desteği
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : { title: 'FETCH', body: 'İndirme tamamlandı!' };
  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(
    clients.openWindow('/')
  );
});
