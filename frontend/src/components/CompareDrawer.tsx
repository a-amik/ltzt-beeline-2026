/**
 * Сравнение с исходными данными заказчика: контрольное распределение,
 * базовый вариант из п. 2.3 и наш план — на одном регионе, одной моделью
 * дороги и с текущими настройками. Считает сервер (`POST /compare`), он же
 * отдаёт подписи показателей: та же таблица стоит в отчёте
 * `data/benchmark/report.md` и в тестах.
 *
 * Таблица — общая с отчётами (`KpiTable`): лучшее жирным, худшее красным.
 * Выполненное вовремя и выполненное с опозданием стоят отдельными строками:
 * план, назначивший всё с тремя десятками опозданий, не лучше плана,
 * назначившего меньше, но вовремя.
 */

import { useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Button } from '@gravity-ui/uikit'
import { runCompare } from '../data'
import { useStore } from '../store'
import KpiTable from './KpiTable'
import { IconClose } from '../lib/icons'
import { RouteLoader } from './RouteLoader'

export default function CompareDrawer() {
  const store = useStore()
  const open = store.compareOpen
  const dataset = store.dataset

  const compare = useMutation({
    mutationFn: () => {
      if (!dataset) throw new Error('Набор ещё не загружен')
      return runCompare(dataset)
    },
    onSuccess: (result) => useStore.getState().setComparison(result),
    onError: (error) => useStore.getState().notify(`Сравнение не посчиталось: ${String(error)}`),
  })

  const run = compare.mutate
  const pending = compare.isPending
  const hasResult = Boolean(store.comparison)
  useEffect(() => {
    if (open && dataset && !hasResult && !pending && !store.offline) run()
  }, [open, dataset, hasResult, pending, store.offline, run])

  if (!open) return null
  const result = store.comparison
  const close = () => store.setCompareOpen(false)

  return (
    <div className="b-drawer fixed inset-0 z-30 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={close} aria-hidden="true" />
      <aside
        role="dialog"
        aria-label="Сравнение с исходными данными"
        className="b-set relative flex w-[560px] max-w-[96vw] flex-col bg-[var(--b-float)]"
        style={{ boxShadow: 'var(--b-shadow-float)' }}
      >
        <div className="b-set-head">
          <div className="min-w-0 flex-1">
            <h2>Сравнение с исходными данными</h2>
            <p>
              Контрольное распределение — как диспетчеры разослали заявки 17 августа. Базовый
              вариант — п. 2.3 задания. Дорога у всех считается одной моделью, опоздание — начало
              работы позже конца окна.
            </p>
          </div>
          <Button view="flat" size="m" onClick={close} title="Закрыть">
            <IconClose />
          </Button>
        </div>

        <div className="b-set-body">
          {store.offline ? (
            <p className="text-[var(--b-text-2)]">Сравнение считает сервер, а он сейчас не отвечает.</p>
          ) : pending || !result ? (
            <div className="flex flex-col gap-1.5">
              <div className="mb-2 flex items-center gap-3">
                <RouteLoader size={32} label="Считаем три плана" />
                <p className="m-0 text-[var(--b-text-2)]">
                  Считаем три плана: решатель ищет столько секунд, сколько задано в настройках.
                </p>
              </div>
              {Array.from({ length: 12 }, (_, i) => (
                <div key={i} className="b-skeleton h-7 w-full" />
              ))}
            </div>
          ) : (
            <KpiTable
              kpis={result.kpis}
              columns={result.rows.map((row) => ({ ...row, ours: row.key === 'solver' }))}
            />
          )}
        </div>

        <div className="b-set-foot">
          <Button view="outlined" size="l" onClick={() => run()} disabled={pending || store.offline}>
            {pending ? 'Считаем…' : 'Пересчитать сравнение'}
          </Button>
          <Button view="flat" size="l" onClick={() => { store.setCompareOpen(false); store.setSettingsOpen(true) }}>
            Правила
          </Button>
        </div>
      </aside>
    </div>
  )
}
