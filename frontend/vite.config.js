import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El frontend habla directo con PocketBase (VITE_PB_URL), no hay backend local.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    historyApiFallback: true,
  },
})
