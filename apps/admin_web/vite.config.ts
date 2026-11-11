import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

// 开发服务器固定在 127.0.0.1:5174：后端本地环境只放行 localhost 来源的跨域请求。
export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5174, strictPort: true },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.ts'],
  },
})
