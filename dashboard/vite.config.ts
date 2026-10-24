/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dashboard talks to the engine through /api, and to the markets service
// through /api/markets. In development Vite proxies both, so the browser sees
// one origin and neither needs CORS.
const engineUrl = process.env.ENGINE_URL ?? 'http://localhost:8000'
const marketsUrl = process.env.MARKETS_URL ?? 'http://localhost:8090'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // The more specific path first: Vite matches them in order.
    proxy: { '/api/markets': marketsUrl, '/api': engineUrl },
  },
  // Libraries go in their own chunks: they change less often than the app,
  // so browsers keep them cached across deploys. React is split from the rest
  // (Recharts and its d3/redux dependencies) so each stays under Vite's 500 KB
  // warning. Groups are matched in order.
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            { name: 'vendor', test: /node_modules/ },
          ],
        },
      },
    },
  },
  test: {
    projects: [
      {
        extends: true,
        test: { name: 'contract', include: ['test/**/*.test.ts'], environment: 'node' },
      },
      {
        extends: true,
        test: {
          name: 'ui',
          include: ['src/**/*.test.{ts,tsx}'],
          environment: 'jsdom',
          setupFiles: ['src/test/setup.ts'],
        },
      },
    ],
  },
})
