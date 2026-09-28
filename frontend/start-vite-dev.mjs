import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { createServer } from 'vite'

const root = path.dirname(fileURLToPath(import.meta.url))

function readOption(name, fallback) {
  const index = process.argv.indexOf(`--${name}`)
  if (index === -1 || index + 1 >= process.argv.length) {
    return fallback
  }
  return process.argv[index + 1]
}

const host = readOption('host', process.env.HOST || '127.0.0.1')
const port = Number(readOption('port', process.env.FRONTEND_PORT || 5174))
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'

const server = await createServer({
  configFile: false,
  root,
  plugins: [react()],
  server: {
    host,
    port,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        timeout: 120000,
        proxyTimeout: 120000,
      },
    },
  },
  optimizeDeps: {
    // Avoid scanning inaccessible OneDrive parent directories while still pre-bundling CJS deps.
    noDiscovery: true,
    include: [
      'react',
      'react-dom',
      'react-dom/client',
      'react/jsx-runtime',
      'react/jsx-dev-runtime',
      'react-router-dom',
      'lucide-react',
      'reactflow',
      'recharts',
      'zustand',
      'event-source-polyfill',
    ],
  },
})

await server.listen()
server.printUrls()
