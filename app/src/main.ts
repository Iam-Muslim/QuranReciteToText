import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { initApiRouting } from './services/api'

// Initialize dynamic port API routing for Tauri production, then mount app
initApiRouting().finally(() => {
  createApp(App).mount('#app')
})
