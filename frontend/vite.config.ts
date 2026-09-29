import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // MapLibre 6 состоит из трёх ES-модулей, и его воркер живёт отдельным файлом.
  // Предсборка зависимостей Vite переупаковывает воркер в свой чанк, тот
  // поднимается, но на сообщения не отвечает — тайлы не качаются вовсе.
  // Исключение из предсборки отдаёт браузеру исходные модули пакета.
  optimizeDeps: { exclude: ['maplibre-gl'] },
  // Подложка карты идёт через свой путь `/tiles/` (на стенде — кэш nginx, см. lib/mapStyle.ts);
  // в разработке тот же путь проксирует Vite.
  server: {
    proxy: {
      '/tiles': { target: 'https://tiles.openfreemap.org', changeOrigin: true, rewrite: (path) => path.replace(/^\/tiles/, '') },
      // Схема стенда в разработке: интерфейс ходит в /api, как на стенде (VITE_API_URL=/api),
      // а BEE_API_PROXY указывает, кто за этим путём — маршрутизатор гостевого режима и входа.
      ...(process.env.BEE_API_PROXY ? { '/api': { target: process.env.BEE_API_PROXY } } : {}),
    },
  },
  // Тесты интерфейса: jsdom, Testing Library; карта в них не рисуется.
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.tsx'],
    css: false,
    // Gravity UI подключает свои .css из ESM: без прогона через Vite Node их не прочитает.
    server: { deps: { inline: ['@gravity-ui/uikit'] } },
  },
})
