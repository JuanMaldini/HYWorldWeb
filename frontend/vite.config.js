import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/project': 'http://localhost:5000',
      '/api': 'http://localhost:5000',
      '/projects': 'http://localhost:5000',
      '/static': 'http://localhost:5000',
    }
  }
})