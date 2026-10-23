import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { initApiRouting, getApiBaseUrl } from './services/api'
import { ensurePersistentStorage } from './services/projectVault'

/**
 * Enterprise Application Bootstrap
 * 
 * 1. Initializes dynamic engine port allocation (Tauri production & dev environments).
 * 2. Installs global error handlers to prevent unhandled UI crashes.
 * 3. Mounts the root App component to the DOM.
 */
async function bootstrap() {
  try {
    // Dynamically discover and bind backend engine port
    await initApiRouting()
    console.info(`[QuranReciteToText] API routing initialized at: ${getApiBaseUrl()}`)
  } catch (err) {
    console.warn('[QuranReciteToText] Running in fallback/dev mode:', err)
  }

  const app = createApp(App)

  // Global Vue runtime error handler
  app.config.errorHandler = (err, _instance, info) => {
    console.error('[QuranReciteToText] Vue Component Error:', err, { info })
  }

  // Global unhandled promise rejection handler
  window.addEventListener('unhandledrejection', (event) => {
    console.warn('[QuranReciteToText] Unhandled Promise Rejection:', event.reason)
  })

  // Mount root application
  app.mount('#app')

  // Register offline Service Worker for browser PWA
  if (typeof window !== 'undefined' && 'serviceWorker' in navigator && !((window as any).__TAURI__ || (window as any).__TAURI_INTERNALS__)) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch((err) => {
        console.debug('[QuranReciteToText] Service worker registration bypassed:', err)
      })
    })
    void ensurePersistentStorage()
  }
}

// Start application
bootstrap()
