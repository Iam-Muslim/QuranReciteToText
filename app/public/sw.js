/**
 * Quran Recite2Text - Offline Progressive Web App Service Worker
 * Provides complete offline caching for:
 *  - Static app shell, icons, and Quranic fonts
 *  - Canonical Quran mushaf word files (114 Surah JSONs + surahs metadata)
 */

const CACHE_NAME = 'quran-recite2text-v2';

const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/favicon.png',
  '/logo.png',
  '/fonts/Cairo-arabic.woff2',
  '/fonts/Cairo-latin.woff2',
  '/fonts/JetBrainsMono-400.woff2',
  '/fonts/JetBrainsMono-500.woff2',
  '/fonts/JetBrainsMono-600.woff2',
  '/fonts/Hafs.ttf'
];

const QURAN_MUSHAF_ASSETS = [
  '/quran/surahs.json',
  ...Array.from({ length: 114 }, (_, i) => `/quran/${i + 1}.json`)
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // 1. Cache critical app shell assets
      try {
        await cache.addAll(STATIC_ASSETS);
      } catch (err) {
        console.debug('ServiceWorker app shell precache warning:', err);
      }

      // 2. Pre-cache all 114 Quran Surah word JSONs for 100% offline mushaf operation
      const mushafPromises = QURAN_MUSHAF_ASSETS.map((url) =>
        fetch(url)
          .then((res) => {
            if (res.ok) return cache.put(url, res);
          })
          .catch((err) => {
            console.debug(`Precache failed for ${url}:`, err);
          })
      );
      await Promise.allSettled(mushafPromises);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  // Blob URLs, data URIs, or Tauri IPC bypass the service worker
  if (req.url.startsWith('blob:') || req.url.startsWith('data:') || req.url.includes('tauri:')) {
    return;
  }

  // Cache-first for Quran mushaf JSONs, fonts, and static assets
  const isMushaf = req.url.includes('/quran/');
  const isFontOrAsset = req.destination === 'font' || req.destination === 'image' || req.url.includes('/fonts/');

  if (isMushaf || isFontOrAsset) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Network-first for navigation requests, fallback to cached index.html
  event.respondWith(
    fetch(req).catch(() => caches.match(req).then((cached) => cached || caches.match('/index.html')))
  );
});
