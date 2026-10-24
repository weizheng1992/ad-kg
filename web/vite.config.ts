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
       '/auth', '/creators', '/brands', '/settlements', '/stats', '/admin']
        .map((p) => [p, 'http://127.0.0.1:8000']),
    ),
  },
})
