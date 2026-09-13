import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Forward ARIA API calls to the FastAPI backend so the frontend
      // never needs a CORS exception for port 5173.
      // Override with VITE_BACKEND_TARGET=http://host:8000 for Docker/LAN.
      "/api": {
        target: process.env.VITE_BACKEND_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 5173,
  },
})
