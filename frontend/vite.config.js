import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { readFileSync } from 'node:fs'

const frontendPackage = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))
const frontendVersion = frontendPackage.version || '0.0.0+unknown'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', '')
  const appPort = Number(env.APP_PORT || 3000)
  const rosWebSocketUrl = env.ROS_WS_URL ?? '/ws/ros2'
  const backendPort = '8000'
  const backendProxy = {
    '/ros1/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    '/ros2/api': { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true },
    '/api': {
      target: `http://127.0.0.1:${backendPort}`,
      changeOrigin: true,
      xfwd: true
    },
    '/ws': {
      target: `ws://127.0.0.1:${backendPort}`,
      ws: true,
      xfwd: true
    }
  }

  return {
  envDir: '..',
  define: {
    'import.meta.env.VITE_FRONTEND_VERSION': JSON.stringify(frontendVersion),
    'import.meta.env.ROS_WS_URL': JSON.stringify(rosWebSocketUrl)
  },
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia']
    }),
    Components({
      resolvers: [ElementPlusResolver()]
    })
  ],
  server: {
    port: appPort,
    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
      interval: Number(process.env.CHOKIDAR_INTERVAL || 500)
    },
    proxy: backendProxy
  },
  preview: {
    port: appPort,
    proxy: backendProxy
  },
  build: {
    outDir: 'dist',
    sourcemap: env.VITE_BUILD_SOURCEMAP === 'true',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/three/')) return 'three'
          if (id.includes('/element-plus/') || id.includes('/@element-plus/')) return 'element'
          if (
            id.includes('/vue/') ||
            id.includes('/vue-router/') ||
            id.includes('/pinia/') ||
            id.includes('/@vue/')
          ) {
            return 'vue'
          }
          return undefined
        }
      }
    }
  }
  }
})
