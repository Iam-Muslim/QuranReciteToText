import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  // Prevent vite from obscuring rust errors
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    watch: {
      ignored: [
        '**/.cache/**',
        '**/userData/**',
        '**/output/**',
        '**/dist/**',
        '**/*.qproj',
        '**/*.mp3',
        '**/*.wav',
        '**/.git/**',
        '**/node_modules/**',
        '**/src-tauri/**',
      ],
    },
  },
  build: {
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('wavesurfer.js')) {
            return 'vendor-wavesurfer';
          }
          if (id.includes('jszip')) {
            return 'vendor-jszip';
          }
        },
      },
    },
  },
});
