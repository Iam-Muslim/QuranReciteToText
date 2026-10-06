import { defineConfig, type Plugin } from 'vite';
import vue from '@vitejs/plugin-vue';
import { spawn, type ChildProcess } from 'node:child_process';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

function getActivePort(): number {
  const portFile = path.resolve(import.meta.dirname, '.engine_port');
  if (fs.existsSync(portFile)) {
    try {
      const raw = fs.readFileSync(portFile, 'utf-8').trim();
      const p = parseInt(raw, 10);
      if (!isNaN(p) && p > 0) return p;
    } catch {
      // Fallback
    }
  }
  return 8000;
}

function checkEngineHealth(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/api/status`, { timeout: 800 }, (res) => {
      resolve(res.statusCode === 200);
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

function engineAutoLauncherPlugin(): Plugin {
  let engineProcess: ChildProcess | null = null;

  const killEngine = () => {
    if (engineProcess && engineProcess.pid) {
      try {
        if (process.platform === 'win32') {
          spawn('taskkill', ['/pid', String(engineProcess.pid), '/T', '/F']);
        } else {
          engineProcess.kill('SIGTERM');
        }
      } catch {
        // Ignored
      }
      engineProcess = null;
    }
  };

  return {
    name: 'vite-engine-auto-launcher',
    async configureServer(server) {
      let activePort = getActivePort();
      const isAlive = await checkEngineHealth(activePort);

      if (!isAlive) {
        console.log('\n\x1b[36m[*] Auto-Launching Python Alignment Engine...\x1b[0m');
        engineProcess = spawn('python', ['engine/server.py'], {
          cwd: import.meta.dirname,
          stdio: ['ignore', 'pipe', 'inherit'],
          env: { ...process.env, PYTHONUNBUFFERED: '1' },
          windowsHide: true,
        });

        engineProcess.stdout?.on('data', (data) => {
          const str = data.toString();
          if (str.includes('Starting Quran Recite Studio Engine')) {
            process.stdout.write(`\x1b[32m${str.trim()}\x1b[0m\n`);
          }
        });

        engineProcess.on('exit', (code) => {
          if (code !== 0 && code !== null) {
            console.error(`\x1b[31m[!] Python Engine exited with code ${code}\x1b[0m`);
          }
          engineProcess = null;
        });

        // Poll for readiness
        for (let i = 0; i < 30; i++) {
          await new Promise((r) => setTimeout(r, 150));
          activePort = getActivePort();
          if (await checkEngineHealth(activePort)) {
            console.log(`\x1b[32m[✓] Python Alignment Engine connected on http://127.0.0.1:${activePort}\x1b[0m\n`);
            break;
          }
        }
      } else {
        console.log(`\x1b[32m[✓] Python Alignment Engine already active on http://127.0.0.1:${activePort}\x1b[0m\n`);
      }

      // Cleanup on server exit
      process.on('SIGINT', () => {
        killEngine();
        process.exit(0);
      });
      process.on('SIGTERM', () => {
        killEngine();
        process.exit(0);
      });
      process.on('exit', killEngine);
      server.httpServer?.on('close', killEngine);
    },
  };
}

export default defineConfig(() => {
  const initialPort = getActivePort();
  return {
    plugins: [vue(), engineAutoLauncherPlugin()],
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/api': {
          target: `http://127.0.0.1:${initialPort}`,
          changeOrigin: true,
          ws: true,
          configure: (proxy, options) => {
            proxy.on('proxyReq', () => {
              const currentPort = getActivePort();
              options.target = `http://127.0.0.1:${currentPort}`;
            });
            proxy.on('error', (_err, _req, res) => {
              if (res && 'writeHead' in res && !res.headersSent) {
                res.writeHead(503, { 'Content-Type': 'application/json' });
                res.end(
                  JSON.stringify({
                    error: 'Engine Initializing',
                    message: 'The Quran Recite Python engine is starting up. Retrying automatically...',
                  })
                );
              }
            });
          },
        },
      },
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
          '**/__pycache__/**',
          '**/*.pyc',
          '**/.engine_port',
        ],
      },
    },
  };
});
