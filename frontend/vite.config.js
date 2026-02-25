import { resolve } from 'path'
import { defineConfig } from 'vite'

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        login: resolve(__dirname, 'login.html'),
        configurazioni: resolve(__dirname, 'configurazioni.html'),
        esegui: resolve(__dirname, 'esegui.html'),
        esecuzioni: resolve(__dirname, 'esecuzioni.html'),
        dettaglio: resolve(__dirname, 'dettaglio.html'),
        chatbot: resolve(__dirname, 'chatbot.html'),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        ws: true,
      },
    },
  },
})
