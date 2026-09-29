/**
 * Меню «…» шапки: загрузка своего файла, версии дня и настройки, соседние
 * приложения, тема. Одно на рабочий экран (`TopBar`) и на экраны показа
 * (`DemoShell`): «Живой день» и «Имитация» закрывают рабочую шапку, и без
 * своего «…» тема и приложения бригады и руководителя оттуда пропадали.
 * На телефоне разделы стоят нижней панелью (`PhoneNav`), пересчёт — в веере
 * «плюса» на карте, поэтому меню одно и то же на всех экранах. После входа
 * на стенде здесь же «Выйти»: плашки режима у вошедшего нет.
 */

import { useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'
import { Button, DropdownMenu } from '@gravity-ui/uikit'
import { api, ApiError } from '../api'
import type { DatasetSummary } from '../types'
import { activePlan, useStore } from '../store'
import { IconBriefcase, IconCalendar, IconDots, IconLogout, IconMap, IconMoon, IconPhone, IconSun, IconUpload } from '../lib/icons'
import { logout, useAccessMode } from '../lib/access'
import { closeOverlays } from './Rail'

/** Набор по умолчанию: вся Москва тремя участками; участок выбирают фильтром в колонке. */
const DEFAULT_SET = 'moskva'

export default function MoreMenu({ phone, size }: {
  phone: boolean
  /** Размер кнопки: в шапке показа кнопки мельче, чем в рабочей. */
  size?: 'm' | 'l'
  /** Прежние пункты телефона — пересчёт и имитация; теперь они в «плюсе» и в нижней панели. */
  onPlan?: () => void
  onSimulate?: () => void
}) {
  const store = useStore()
  const plan = activePlan(store)
  const access = useAccessMode()

  // Свой файл: CSV заказчика или JSON по контракту — пунктом в «…». Разбирает
  // сервер теми же правилами, что наборы; новый набор открывается сам, а назад
  // к Москве ведёт пункт там же. Ход загрузки — до готового плана нового
  // набора — показывает `ImportOverlay` поверх карты.
  const fileRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()
  const onFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || store.importing) return
    const content = await file.text()
    // Строки заявок CSV: без шапки, пустых и строки офиса. У JSON строк нет —
    // для прогноза времени хватает оценки по размеру.
    const csvRows = content.split('\n').filter((line) => /^\uFEFF?\s*[^;,\s]/.test(line) && !/^\uFEFF?\s*(заявка|адрес офиса)/i.test(line))
    const rows = /\.json$/i.test(file.name) ? 0 : csvRows.length
    store.setImporting({ name: file.name, rows, stage: 'upload' })
    try {
      const summary = await api.upload(file.name, content)
      await queryClient.invalidateQueries({ queryKey: ['datasets'] })
      store.setImporting({
        name: file.name,
        rows,
        stage: 'plan',
        datasetId: summary.id,
        facts:
          `заявок ${summary.requests}, бригад ${summary.engineers}` +
          (summary.control ? ', с фактом дня' : ', бригады заведены по числу заявок'),
      })
      store.setDatasetId(summary.id)
    } catch (error) {
      store.setImporting(null)
      store.notify(error instanceof ApiError ? error.message : String(error), 'Файл не принят')
    }
  }

  const fileInput = <input ref={fileRef} type="file" accept=".csv,.json,text/csv,application/json" hidden onChange={onFile} />
  const datasets = queryClient.getQueryData<DatasetSummary[]>(['datasets']) ?? []
  const home = datasets.find((item) => item.id === DEFAULT_SET)?.name ?? 'Вся Москва'
  // Открыт не набор по умолчанию — свой файл: жёлтая точка на «…» говорит, что данные другие.
  const custom = store.datasetId !== DEFAULT_SET
  const current = datasets.find((item) => item.id === store.datasetId)?.name ?? 'свой файл'

  const crewHref = `#crew/${plan?.routes.find((r) => r.stops.length)?.engineer_id ?? ''}`
  const openVersions = () => {
    closeOverlays()
    store.setDemo('versions')
  }

  // «…»: свой файл, версии дня, соседние приложения, тема.
  const moreMenu = (
    <DropdownMenu
      size="l"
      renderSwitcher={(props) => (
        <Button
          {...props}
          view="flat"
          size={size ?? (phone ? 'm' : 'l')}
          className={custom ? 'b-more custom' : 'b-more'}
          title={custom ? `Загружен набор «${current}». Вернуться к «${home}» — здесь же` : 'Ещё: свой файл, версии дня, приложения, тема'}
        >
          <IconDots />
          {custom ? <i className="b-more-dot" aria-hidden="true" /> : null}
          <span className="sr-only">{custom ? `Ещё. Загружен набор «${current}»` : 'Ещё'}</span>
        </Button>
      )}
      items={[
        [
          { text: store.importing ? 'Загружаем файл…' : 'Загрузить CSV или JSON', iconStart: <IconUpload />, action: () => fileRef.current?.click(), disabled: Boolean(store.importing) },
          ...(store.datasetId !== DEFAULT_SET ? [{ text: `Вернуться к набору «${home}»`, iconStart: <IconMap />, action: () => store.setDatasetId(DEFAULT_SET) }] : []),
        ],
        [
          { text: 'Версии дня', iconStart: <IconCalendar />, action: openVersions, disabled: !plan },
        ],
        [
          { text: 'Приложение бригады', iconStart: <IconPhone />, href: crewHref, target: '_blank' },
          { text: 'Экран руководителя', iconStart: <IconBriefcase />, href: '#manager', target: '_blank' },
        ],
        [
          {
            text: store.theme === 'dark' ? 'Светлая тема' : 'Тёмная тема',
            iconStart: store.theme === 'dark' ? <IconSun /> : <IconMoon />,
            action: store.toggleTheme,
          },
        ],
        ...(access === 'real' ? [[{ text: 'Выйти', iconStart: <IconLogout />, action: () => void logout() }]] : []),
      ]}
    />
  )

  return (
    <>
      {fileInput}
      {moreMenu}
    </>
  )
}
