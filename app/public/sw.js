/**
 * Quran Recite2Text - Offline Progressive Web App Service Worker
 * Provides offline caching for static app shell, icons, and Quranic fonts.
 */

const CACHE_NAME = 'quran-recite2text-v1';

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

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.debug('ServiceWorker cache addAll error:', err);
      });
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

  // Cache-first for offline fonts, images, and static assets
  if (req.destination === 'font' || req.destination === 'image' || req.url.includes('/fonts/')) {
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
