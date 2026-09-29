import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import '@gravity-ui/uikit/styles/styles.css'
import './index.css'
import App from './App'
import CrewApp from './CrewApp'
import ManagerApp from './manager/ManagerApp'
import AccessBar from './components/AccessBar'
import { hideBoot } from './lib/boot'

const queryClient = new QueryClient({
  defaultOptions: {
    // Сервера может не быть вовсе: повторять запрос трижды незачем,
    // демо-данные ждут за первым же отказом.
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

// Приложение бригады живёт по адресу `#crew/<бригада>` тем же бандлом:
// у прототипа два экрана, а не два продукта.
const crew = window.location.hash.startsWith('#crew')
// Экран руководителя — третья роль: `#manager`.
const manager = window.location.hash.startsWith('#manager')
// Роль меняется ссылкой: другой экран — другая загрузка того же бандла.
window.addEventListener('hashchange', () => {
  const now = window.location.hash
  const kind = now.startsWith('#crew') ? 'crew' : now.startsWith('#manager') ? 'manager' : 'app'
  if (kind !== (crew ? 'crew' : manager ? 'manager' : 'app')) window.location.reload()
})

// Экран запуска снимают сами экраны, когда есть что показать; это — страховка,
// чтобы он не остался поверх ошибки.
window.setTimeout(hideBoot, 20_000)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* Плашка режима стенда стоит над любым из трёх экранов; в разработке её нет. */}
      <div className="b-shell">
        <AccessBar />
        <div className="b-shell-app">{crew ? <CrewApp /> : manager ? <ManagerApp /> : <App />}</div>
      </div>
    </QueryClientProvider>
  </StrictMode>,
)
