# Маршрут дня — интерфейс

React 19, TypeScript, Vite, карта MapLibre GL, компоненты Gravity UI.
Данные приходят с сервера по [`../CONTRACT.md`](../CONTRACT.md); описание
решения для читателя — в [документации](https://nami.amik.am/app/s/6118d05a96d7cf23ee93528c44bf11aa).

## Команды

```sh
npm install        # зависимости; перед dev и build скрипт кладёт MapLibre в public/
npm run dev        # http://localhost:5173; адрес API — VITE_API_URL, по умолчанию http://127.0.0.1:8000
npm run build      # tsc -b и сборка в dist/
npm test           # Vitest
npm run lint       # oxlint
```

## Экраны

| Экран | Адрес | Где |
|---|---|---|
| Диспетчер: заявки, бригады, карта, настройки | `/` | `App.tsx`, `dispatch/`, `components/` |
| Нагрузка по окнам | `/deficit` | `components/demo/DeficitView.tsx` |
| Живой день с событиями | `/live` | `components/demo/` |
| Имитация: гонка трёх планов | `/sim` | `components/race/` |
| Отчёты | `/reports/…` | `components/reports/` |
| Приложение бригады | `#crew/<бригада>` | `CrewApp.tsx`, `crew/` |
| Экран руководителя | `#manager` | `manager/` |

Маршруты собирает `lib/router.ts`; состояние — `store.ts`; запросы
к серверу — `api.ts`, типы контракта — `types.ts`. Темы (светлая и тёмная)
и цвета заказчика — `theme.css`, общие стили — `index.css`.
