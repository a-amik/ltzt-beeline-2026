/**
 * Отчёты о решении — для руководителя и жюри, по кальке транспортного
 * стенда: слева страницы и главы открытой страницы, справа страница-статья
 * с картинкой, выводом, плитками и рисунками «Рис. N». Страницы идут
 * по вопросам жюри: как устроено решение, как проектировали экраны, как
 * устроены модели, как сравниваем планы, зачем раздел настроек и как
 * сервис держит нагрузку.
 *
 * Экран ничего не пересчитывает: прогоны лежат в `data/` (`GET /reports`,
 * гонка — `GET /race`). Числа вне прогонов — в `reports/facts.ts` с источником.
 * Страница — в адресе: `/about/<страница>` (`lib/router.ts`; старый `/reports/…` тоже открывает).
 */

import { useQuery } from '@tanstack/react-query'
import { Select } from '@gravity-ui/uikit'
import { api } from '../../api'
import ThemeSwitch from '../ThemeSwitch'
import { useStore, type ReportPage } from '../../store'
import DemoShell from './DemoShell'
import { usePhone } from '../../lib/media'
import NavBurger from '../NavBurger'
import { AreaWait } from '../Loading'
import SolutionPage from '../reports/SolutionPage'
import DesignPage from '../reports/DesignPage'
import ModelsPage from '../reports/ModelsPage'
import OpsPage from '../reports/OpsPage'
import MethodPage from '../reports/MethodPage'
import SettingsPage from '../reports/SettingsPage'
import MileagePage from '../reports/MileagePage'
import { closeOverlays } from '../Rail'
import '../reports/reports.css'

const PAGES: { key: ReportPage; title: string; sub: string; chapters: [string, string][] }[] = [
  { key: 'solution', title: 'Как устроено решение', sub: 'данные, результат, назначения, запуск',
    chapters: [['s-chain', 'Цепочка'], ['s-result', 'Контрольный день'], ['s-explain', 'Объяснение'], ['s-replan', 'Перепланирование'], ['s-run', 'Как запустить']] },
  { key: 'design', title: 'Как спроектирован интерфейс', sub: 'диспетчер, бригада и связь между ними',
    chapters: [['i-approach', 'Подход'], ['i-dispatcher', 'Диспетчер'], ['i-crew', 'Приложение бригады'], ['i-flow', 'Как работают вместе'], ['i-why', 'Решения и почему']] },
  { key: 'models', title: 'Как устроены модели', sub: 'цель, расчёт, проверка, сравнение',
    chapters: [['m-goal', 'Цель и ограничения'], ['m-base', 'С чем сравниваем'], ['m-portfolio', 'Три решателя'], ['m-general', 'Новые сценарии'], ['m-race', 'Сравнение планов'], ['m-rules', 'Новая заявка']] },
  { key: 'method', title: 'Живой день и имитация', sub: 'события, сценарии, сравнение',
    chapters: [['me-plans', 'Три плана'], ['me-events', 'События дня'], ['me-days', 'Обычный и тяжёлый'], ['me-start', 'Старт бригад'], ['me-live', 'Живой день'], ['me-race', 'Имитация'], ['me-metrics', 'Как считаем'], ['me-limits', 'Ограничения']] },
  { key: 'settings', title: 'Настройки расчёта', sub: 'зачем, что задаётся, BeeGPT, работа',
    chapters: [['st-why', 'Зачем'], ['st-what', 'Что настраивается'], ['st-rules', 'Кто задаёт'], ['st-helper', 'BeeGPT'], ['st-prod', 'В работе'], ['st-limits', 'Для пилота']] },
  { key: 'ops', title: 'Нагрузка и безопасность', sub: 'масштаб, запросы, защита',
    chapters: [['o-scale', 'Масштаб'], ['o-load', 'Нагрузка'], ['o-abuse', 'Некорректные запросы'], ['o-sec', 'Данные и доступ'], ['o-fraud', 'Проверка отметок'], ['o-next', 'Для пилота']] },
  { key: 'mileage', title: 'Отчёт по исполнителям', sub: 'пробег каждой бригады, три плана',
    chapters: [['mi-sum', 'Сводка'], ['mi-vostok', 'Восток'], ['mi-yugo-vostok', 'Юго-восток'], ['mi-yugocentr', 'Югоцентр']] },
]

const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

export default function ReportsView({ onClose }: { onClose: () => void }) {
  const store = useStore()
  const phone = usePhone()
  const page = store.reportPage
  const data = useQuery({ queryKey: ['reports'], queryFn: () => api.reports(), staleTime: 60_000, retry: false })
  const reports = data.data
  const open = (key: ReportPage) => {
    store.setReportPage(key)
    document.querySelector('.b-an-main')?.scrollTo({ top: 0 })
  }
  const openDemo = (demo: 'compare' | 'race') => store.setDemo(demo)

  return (
    <DemoShell
      title="О проекте"
      info="Как устроен прототип и что показали проверки. Числа взяты из сохранённых прогонов; открытие страницы не запускает новый расчёт."
      onClose={onClose}
      inRail
      // На телефоне тема есть в «…», а переключатель отнимал половину строки шапки.
      extra={phone ? null : <ThemeSwitch />}
      // Телефон: страницы и главы — бургером рядом с «…», а не выпадающим списком над страницей.
      tools={phone ? (
        <NavBurger
          label="Страницы раздела «О проекте»"
          groups={[
            PAGES.map((p, i) => ({ text: `${i + 1}. ${p.title}`, selected: page === p.key, action: () => open(p.key) })),
            (PAGES.find((p) => p.key === page)?.chapters ?? []).map(([id, label]) => ({ text: label, action: () => jump(id) })),
          ]}
        />
      ) : undefined}
    >
      <div className="b-an-wrap">
        <nav className="b-an-side" aria-label="Страницы раздела «О проекте»">
          {PAGES.map((p, i) => (
            <div key={p.key} className={`b-an-page${page === p.key ? ' on' : ''}`}>
              <button type="button" onClick={() => open(p.key)} aria-current={page === p.key ? 'page' : undefined}>
                <span className="n">{i + 1}</span>
                <span><b>{p.title}</b><small>{p.sub}</small></span>
              </button>
              {page === p.key ? (
                <ul>{p.chapters.map(([id, label]) => <li key={id}><button type="button" onClick={() => jump(id)}>{label}</button></li>)}</ul>
              ) : null}
            </div>
          ))}
        </nav>
        <main className="b-an-main">
          <div className="b-an-phone-nav">
            <Select size="l" width="max" value={[page]} onUpdate={([v]) => open(v as ReportPage)}
              options={PAGES.map((p, i) => ({ value: p.key, content: `${i + 1}. ${p.title}` }))} />
          </div>
          {data.isError ? (
            <p className="b-demo-empty">Не удалось загрузить данные отчётов: {String(data.error)}</p>
          ) : !reports ? (
            <AreaWait label="Загружаем раздел «О проекте»" size={64} />
          ) : page === 'design' ? (
            <DesignPage />
          ) : page === 'models' ? (
            <ModelsPage reports={reports} onOpen={openDemo} />
          ) : page === 'method' ? (
            <MethodPage />
          ) : page === 'settings' ? (
            <SettingsPage onOpen={() => { closeOverlays(); store.setSettingsOpen(true) }} />
          ) : page === 'ops' ? (
            <OpsPage reports={reports} />
          ) : page === 'mileage' ? (
            <MileagePage reports={reports} />
          ) : (
            <SolutionPage reports={reports} onOpen={openDemo} />
          )}
        </main>
      </div>
    </DemoShell>
  )
}
