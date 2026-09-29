/**
 * Экран руководителя — третья роль прототипа после диспетчера и бригады,
 * открывается по адресу `#manager`. Диспетчер ведёт заявки; руководителю нужен
 * день города разом: идёт ли он к цели, где не хватает людей и во что
 * обходится — пять виджетов сводки (`ManagerDashboard`) за выбранный период,
 * при желании против периода сравнения (`PeriodPicker`).
 *
 * В шапке только знак, период и «…»: правила дня, соседние приложения и тема
 * — в меню, как на экране диспетчера. На телефоне шапка уходит по скроллу.
 *
 * Цели — «визитов вовремя» и «загрузка бригад» — заданы в настройках
 * (группа «Экран руководителя»): регион ниже цели помечен красным. План
 * руководитель не трогает — это дело диспетчера. Зато общие правила дня —
 * порядок целей, приоритеты, тарифы, вес аварии, бригады, правила пересчёта —
 * задаёт только он, пунктом «Правила дня» в «…»: они уходят на сервер (`PUT /rules`)
 * и ложатся под расчёт каждого диспетчера. Входа нет, как и у других ролей
 * прототипа: роль выбирается ссылкой и едет заголовком запроса.
 */

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, DropdownMenu, HelpMark, ThemeProvider } from '@gravity-ui/uikit'
import { applyTheme, initialTheme, type Theme } from '../store'
import { IconDots, IconMap, IconMoon, IconPhone, IconSliders, IconSun } from '../lib/icons'
import { usePhone } from '../lib/media'
import { useAutoHide } from '../crew/useAutoHide'
import { api } from '../api'
import SettingsDrawer from '../components/SettingsDrawer'
import type { Engineer, Settings } from '../types'
import { managerApi } from './managerApi'
import ManagerDashboard from './ManagerDashboard'
import PeriodPicker from './PeriodPicker'
import { dayPeriod, inside, length, parse, rangeLabel, type Period } from './period'
import './manager.css'
import { hideBoot } from '../lib/boot'

export default function ManagerApp() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [rulesOpen, setRulesOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period | null>(null)
  useEffect(() => applyTheme(theme), [theme])
  useEffect(() => hideBoot(), [])
  const phone = usePhone()
  const header = useRef<HTMLElement>(null)
  // Страница прокручивается в #root, а не в окне.
  const root = useRef<HTMLElement | null>(document.getElementById('root'))
  const away = useAutoHide(!phone || rulesOpen, header, root)
  // Сводка по одному плану города: участки — его разбивка, итоги не складываются дважды.
  const dashboard = useQuery({ queryKey: ['manager-dashboard'], queryFn: managerApi.dashboard, refetchInterval: 10000, retry: false })
  const client = useQueryClient()
  const rules = useQuery({ queryKey: ['rules'], queryFn: managerApi.rules, retry: false })
  // Бригады всех регионов — для вкладки «Бригады»: правила общие, а бригада у каждого региона своя.
  const engineers = useQuery({
    queryKey: ['manager-engineers'],
    enabled: rulesOpen,
    staleTime: Infinity,
    queryFn: async (): Promise<Engineer[]> => {
      const list = await api.datasets()
      const sets = await Promise.all(list.map((item) => api.dataset(item.id).catch(() => null)))
      return sets.flatMap((set) => set?.engineers ?? [])
    },
  })
  const save = useMutation({
    mutationFn: (next: Settings) => managerApi.saveRules(next),
    onSuccess: (state) => {
      client.setQueryData(['rules'], state)
      setRulesOpen(false)
      setNotice('Правила дня сохранены: диспетчеры считают по ним со следующего пересчёта')
    },
    onError: (error) => setNotice(`Правила не сохранились: ${error instanceof Error ? error.message : String(error)}`),
  })

  // Дни с данными: пока это день плана города. Период по умолчанию — он сам.
  const anchor = dashboard.data?.date ?? null
  const dataDays = anchor ? [anchor] : []
  const shown = period ?? (anchor ? dayPeriod(anchor) : null)
  const inPeriod = Boolean(anchor && shown && inside(anchor, shown.main))

  return (
    <ThemeProvider theme={theme}>
      <div className="b-mgr">
        <header ref={header} className={`b-mgr-top${away ? ' away' : ''}`}>
          <span className="b-brand">
            <img src="/brand/beeline-logo.svg" alt="" width={24} height={24} />
            <b>билайн бизнес</b>
            <span>Дашборд руководителя</span>
          </span>
          <span className="b-mgr-tools">
            {anchor && shown ? <PeriodPicker value={shown} anchor={anchor} dataDays={dataDays} onChange={setPeriod} /> : null}
            <DropdownMenu
              size="l"
              renderSwitcher={(props) => (
                <Button {...props} view="flat" size="l" className="b-more" title="Ещё: правила дня, приложения, тема">
                  <IconDots />
                  <span className="sr-only">Ещё</span>
                </Button>
              )}
              items={[
                [{ text: 'Правила дня', iconStart: <IconSliders />, action: () => setRulesOpen(true), disabled: !rules.data }],
                [
                  { text: 'Экран диспетчера', iconStart: <IconMap />, href: '#', target: '_blank' },
                  { text: 'Приложение бригады', iconStart: <IconPhone />, href: '#crew', target: '_blank' },
                ],
                [
                  {
                    text: theme === 'dark' ? 'Светлая тема' : 'Тёмная тема',
                    iconStart: theme === 'dark' ? <IconSun /> : <IconMoon />,
                    action: () => setTheme(theme === 'dark' ? 'light' : 'dark'),
                  },
                ],
              ]}
            />
          </span>
        </header>

        {notice ? (
          <p className="b-mgr-notice" role="status">
            {notice}
          </p>
        ) : null}
        {dashboard.isError ? <p className="b-mgr-empty">Сервер планировщика не отвечает.</p> : null}
        {dashboard.isLoading ? <p className="b-mgr-empty">Собираем сводку дня: план города строится один раз, около минуты.</p> : null}
        {dashboard.data && shown ? <PeriodNote period={shown} dataDays={dataDays} /> : null}
        {dashboard.data && inPeriod ? <ManagerDashboard data={dashboard.data} /> : null}
        {dashboard.data && anchor && !inPeriod ? (
          <div className="b-mgr-empty">
            <p>За {shown ? rangeLabel(shown.main, parse(anchor).getFullYear()) : 'период'} данных нет</p>
            <Button view="outlined" size="m" onClick={() => setPeriod(dayPeriod(anchor))}>
              Показать {rangeLabel({ from: anchor, to: anchor })}
            </Button>
          </div>
        ) : null}
      </div>
      {rulesOpen && rules.data ? (
        <SettingsDrawer
          mode="edit"
          initial={rules.data.rules}
          engineers={engineers.data ?? []}
          note="Правила общие на все регионы: диспетчеры видят их только для чтения"
          busy={save.isPending}
          submitLabel={save.isPending ? 'Сохраняем…' : 'Сохранить правила'}
          onClose={() => setRulesOpen(false)}
          onSubmit={(draft) => save.mutate(draft)}
        />
      ) : null}
    </ThemeProvider>
  )
}

/**
 * Строка над сводкой — только когда период шире данных: сколько дней периода
 * с данными и есть ли что сравнивать. Как посчитано — в подсказке.
 */
function PeriodNote({ period, dataDays }: { period: Period; dataDays: string[] }) {
  const n = length(period.main)
  const have = dataDays.filter((day) => inside(day, period.main)).length
  const cmp = period.compare ? dataDays.filter((day) => inside(day, period.compare)).length : null
  if (n === 1 && cmp === null) return null
  if (!have) return null
  const year = parse(period.main.to).getFullYear()
  return (
    <p className="b-mgr-period">
      {n > 1 ? <span>С данными {have} {have === 1 ? 'день' : have < 5 ? 'дня' : 'дней'} из {n}</span> : null}
      {period.compare ? (
        <span className={cmp ? '' : 'none'}>
          {cmp ? `Сравнение с ${rangeLabel(period.compare, year)}` : `За ${rangeLabel(period.compare, year)} данных нет — сравнивать не с чем`}
        </span>
      ) : null}
      <HelpMark aria-label="Откуда данные" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
        <div className="b-dash-help">
          Сводка строится по плану города на день из набора заказчика — {dataDays.map((d) => rangeLabel({ from: d, to: d })).join(', ')}.
          Другие дни появятся, когда планы будут копиться день за днём; тогда период сложит их, а сравнение покажет разницу.
        </div>
      </HelpMark>
    </p>
  )
}
