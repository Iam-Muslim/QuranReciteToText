import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { initApiRouting, getApiBaseUrl } from './services/api'

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
}

// Start application
bootstrap()
