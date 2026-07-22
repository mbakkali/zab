import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiOrigin = process.env.ZAB_API_ORIGIN ?? 'http://127.0.0.1:8750'
const uiDevHost = process.env.ZAB_UI_DEV_HOST ?? '127.0.0.1'
const uiDevPort = Number(process.env.ZAB_UI_DEV_PORT ?? '5280')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: uiDevHost,
    port: uiDevPort,
    strictPort: false,
    proxy: {
      '/api': {
        target: apiOrigin,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req) => {
            if (req.url?.includes('/stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
    },
  },
  build: {
    // Fix font preload crossorigin warnings
    rollupOptions: {
      output: {
        // Isole les dépendances stables dans des chunks séparés et cacheables :
        // elles ne sont retéléchargées que lorsqu'elles changent, pas à chaque
        // déploiement du code applicatif.
        // On isole uniquement les libs partagées par le shell + la plupart des
        // vues (react, icônes). Le reste n'est PAS forcé dans un chunk global :
        // rolldown co-localise chaque dépendance avec la vue lazy qui l'utilise,
        // pour qu'elle ne charge qu'au premier affichage de cette page.
        manualChunks: (id) => {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) {
            return 'vendor-react'
          }
          if (id.includes('@hugeicons') || id.includes('lucide-react')) {
            return 'vendor-icons'
          }
          return undefined
        },
        // Ensure fonts get crossorigin attribute in preload links
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && /\.(woff2?|ttf|otf|eot)$/i.test(assetInfo.name)) {
            return 'assets/fonts/[name]-[hash][extname]'
          }
          return 'assets/[name]-[hash][extname]'
        },
      },
    },
  },
})
