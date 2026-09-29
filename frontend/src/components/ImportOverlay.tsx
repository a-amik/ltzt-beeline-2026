/**
 * Ход загрузки своего файла — одной карточкой поверх карты, от разбора
 * до готового плана. Загрузка идёт в два шага: сервер разбирает файл
 * (адреса, дороги между ними, бригады), затем экран сам строит первый план
 * нового набора. Порознь эти шаги читались чередой уведомлений и подменой
 * старого плана посреди работы; здесь они стоят одним списком, текущий —
 * с полосой `Crunch`, а старый план под карточкой притушен.
 *
 * Готово — карточка говорит итог (заявки, бригады, не назначено) и уходит
 * сама через пару секунд или по щелчку. План не построился — карточка
 * уходит сразу, причину говорит уведомление расчёта.
 */

import { useEffect, useRef, useState } from 'react'
import { useStore } from '../store'
import Crunch, { type Phase } from './Crunch'
import { RouteLoader } from './RouteLoader'
import { IconCheck } from '../lib/icons'

const UPLOAD_PHASES: Phase[] = [
  { at: 0, text: 'Читаем файл' },
  { at: 0.12, text: 'Ищем адреса на карте' },
  { at: 0.45, text: 'Считаем дороги между адресами: машина, пешком, велосипед, транспорт' },
  { at: 0.85, text: 'Собираем набор: бригады, дома, факт дня' },
]

const PLAN_PHASES: Phase[] = [
  { at: 0, text: 'Раскладываем заявки по бригадам' },
  { at: 0.35, text: 'Решатель ищет план короче и выгоднее' },
  { at: 0.8, text: 'Сверяем окна, навыки и запас оборудования' },
]

/** Сколько карточка держит итог, прежде чем уйти. */
const DONE_MS = 2600

export default function ImportOverlay() {
  const importing = useStore((s) => s.importing)
  const plan = useStore((s) => s.plan)
  const planning = useStore((s) => s.planning)
  const datasetId = useStore((s) => s.datasetId)
  const budget = useStore((s) => Number((s.settings.options as Record<string, unknown> | undefined)?.time_limit_s) || 4)
  const [done, setDone] = useState<{ facts: string; left: number } | null>(null)
  const sawPlanning = useRef(false)

  const target = importing?.stage === 'plan' ? importing.datasetId : undefined
  const ready = Boolean(target && plan?.dataset_id === target && !planning)

  useEffect(() => {
    if (!importing) {
      sawPlanning.current = false
      setDone(null)
      return
    }
    if (planning) sawPlanning.current = true
    // Диспетчер ушёл к другому набору — загрузка ему больше не нужна.
    if (target && datasetId !== target) useStore.getState().setImporting(null)
    else if (ready) {
      setDone({ facts: importing.facts ?? '', left: plan?.unassigned.length ?? 0 })
    } else if (target && sawPlanning.current && !planning && !plan) useStore.getState().setImporting(null)
  }, [importing, planning, plan, datasetId, target, ready])

  useEffect(() => {
    if (!done) return
    const timer = window.setTimeout(() => useStore.getState().setImporting(null), DONE_MS)
    return () => window.clearTimeout(timer)
  }, [done])

  if (!importing) return null
  const rows = importing.rows
  const uploadMs = 1500 + (rows || 200) * 30
  const planMs = budget * 1000 + 3000
  const close = done ? () => useStore.getState().setImporting(null) : undefined

  return (
    <div className="b-import" data-done={done ? '' : undefined} onClick={close}>
      <div className="b-import-card" role="status" aria-live="polite">
        <div className="b-import-h">
          {done ? (
            <span className="b-import-ok">
              <IconCheck />
            </span>
          ) : (
            <RouteLoader size={40} label="Загружаем файл" />
          )}
          <span>
            <b>{done ? 'Набор загружен, план готов' : `Загружаем «${importing.name}»`}</b>
            {done ? (
              <>
                <small>{done.facts}</small>
                <small>
                  {done.left ? (
                    <>
                      не назначено <em className="b-list-g-bad">{done.left}</em> — наверху списка заявок
                    </>
                  ) : (
                    'назначены все заявки'
                  )}
                </small>
              </>
            ) : rows ? (
              <small>{`${rows} ${plural(rows, 'заявка', 'заявки', 'заявок')} в файле`}</small>
            ) : null}
          </span>
        </div>
        {done ? null : (
          <ol className="b-import-steps">
            <li data-state={importing.stage === 'upload' ? 'now' : 'done'}>
              {importing.stage === 'upload' ? (
                <Crunch key="upload" title="Разбираем файл" estimateMs={uploadMs} phases={UPLOAD_PHASES} />
              ) : (
                <>
                  <IconCheck />
                  <span>Файл разобран: {importing.facts}</span>
                </>
              )}
            </li>
            {/* Шаг плана встаёт, когда до него дошло: заранее его строка висела пустым обещанием. */}
            {importing.stage === 'plan' ? (
              <li data-state="now">
                <Crunch key="plan" title="Строим план дня" estimateMs={planMs} phases={PLAN_PHASES} />
              </li>
            ) : null}
          </ol>
        )}
      </div>
    </div>
  )
}

function plural(n: number, one: string, few: string, many: string): string {
  const d = n % 10
  const h = n % 100
  if (d === 1 && h !== 11) return one
  if (d >= 2 && d <= 4 && (h < 12 || h > 14)) return few
  return many
}
