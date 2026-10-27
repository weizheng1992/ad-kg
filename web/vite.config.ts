import path from 'node:path'
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

// dev 代理到本机 AdKG（README §9.7：web → HTTP API 是唯一接入路径）
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      ['/ask', '/graph', '/actions', '/guideline', '/ingest', '/creative', '/agent',
       '/auth', '/creators', '/cases', '/brands', '/settlements', '/stats',
       '/admin', '/menus', '/my-actions']
        .map((p) => [p, {
          target: 'http://127.0.0.1:8000',
          // 页面直开/刷新（accept 含 text/html）回落 SPA 入口不代理 API——与 nginx 同款分流（缺陷备忘⑪）；
          // bypass 返回字符串即改写请求路径，undefined 走代理
          bypass: (req) => (req.headers.accept?.includes('text/html') ? '/index.html' : undefined),
        }]),
    ),
  },
})
