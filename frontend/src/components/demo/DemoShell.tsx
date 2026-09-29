/**
 * Общая рамка экранов показа: шапка с названием и часами, пульт времени
 * (пуск, скорость, ползунок дня), закрытие по Esc. Экран показа закрывает
 * рабочий целиком: жюри смотрит на один сюжет, а не на диспетчерскую.
 */

import { useEffect, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api'
import type { Settings } from '../../types'
import { Button, HelpMark, SegmentedRadioGroup } from '@gravity-ui/uikit'
import { DAY_END, DAY_START } from '../../lib/time'
import { IconClose, IconPlay } from '../../lib/icons'
import { clockText, type Clock } from './useClock'
import { RouteLoader } from '../RouteLoader'
import MoreMenu from '../MoreMenu'
import { usePhone } from '../../lib/media'

interface Props {
  title: string
  subtitle?: string
  /** Пояснение к экрану — в подсказке ⓘ у заголовка, а не строкой под ним. */
  info?: ReactNode
  clock?: Clock
  marks?: { t: number; tone: 'bad' | 'event' | 'hot' }[]
  onClose: () => void
  /** Раздел колонки: на компьютере из него уходят колонкой, крестик — только на телефоне, где колонки нет. */
  inRail?: boolean
  children: ReactNode
  /** Пульт экрана: сценарий, длительность, пуск. На узком экране — своей строкой под именем. */
  extra?: ReactNode
  /** Мелкий инструмент у правого края первой строки, перед «…» и крестиком, — день, например. */
  tools?: ReactNode
  /** Своя кнопка «Пуск» (имитация). Без неё и с часами «Пуск» рисует рамка. На узком экране «Пуск» —
      в первой строке рядом с часами, одной с ними высоты; пульт — второй строкой. */
  play?: ReactNode
  /** Идёт расчёт: часы стоят на начале дня, пуск и ползунок недоступны. */
  busy?: boolean
  /** Меню «…» рабочей шапки — на экранах, которые её закрывают целиком. */
  menu?: boolean
}

export default function DemoShell({ title, subtitle, info, inRail, clock, marks = [], onClose, children, extra, tools, play, busy, menu }: Props) {
  const phone = usePhone()
  // Шапка с пультом на узком экране идёт в две строки: имя, часы и крестик — первой, пульт — второй.
  const pult = Boolean(clock || extra)
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
      if (event.key === ' ' && clock && !busy && (event.target as HTMLElement)?.tagName !== 'INPUT') {
        event.preventDefault()
        clock.toggle()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, clock, busy])

  return (
    <div className="b-demo" role="dialog" aria-label={title}>
      <header className={pult ? 'b-demo-top pult' : 'b-demo-top'}>
        <div className="b-demo-title">
          <b className="b-demo-name">
            {title}
            {info ? (
              <HelpMark aria-label="Об этом экране" popoverProps={{ placement: ['bottom-start', 'bottom'] }}>
                <div className="b-demo-info">{info}</div>
              </HelpMark>
            ) : null}
          </b>
          {subtitle ? <span>{subtitle}</span> : null}
        </div>
        {clock ? (
          <div className="b-demo-clock" aria-live="off">
            {clockText(clock.time)}
          </div>
        ) : null}
        {pult ? (
          <div className="b-demo-acts">
            {extra}
            {clock ? (
              <>
                <SegmentedRadioGroup
                  size="m"
                  value={String(clock.seconds)}
                  onUpdate={(value) => clock.setSeconds(Number(value))}
                  options={[
                    { value: '30', content: '30 с' },
                    { value: '60', content: '1 мин' },
                    { value: '120', content: '2 мин' },
                  ]}
                />
              </>
            ) : null}
          </div>
        ) : null}
        {play || clock ? (
          <span className="b-demo-play">
            {play ?? (clock ? (
              <Button view="action" size="m" onClick={clock.toggle} disabled={busy} title="Пуск и пауза — пробел">
                <span className="flex items-center gap-1.5">
                  {clock.playing ? <span className="b-demo-pause" aria-hidden="true" /> : <IconPlay />}
                  {clock.playing ? 'Пауза' : clock.time >= DAY_END ? 'Ещё раз' : 'Пуск'}
                </span>
              </Button>
            ) : null)}
          </span>
        ) : null}
        {/* Инструменты, «…» и крестик — концом первой строки, вне пульта: на узком экране
            пульт уходит второй строкой, а крестик остаётся у правого края рядом с именем. */}
        <span className="b-demo-end">
          {tools}
          {menu || phone ? <MoreMenu phone={phone} size="m" /> : null}
          <Button view="flat" size="m" onClick={onClose} title="Закрыть — Esc" className={inRail ? 'b-demo-close phone' : 'b-demo-close'}>
            <IconClose />
          </Button>
        </span>
      </header>
      <div className="b-demo-body">{children}</div>
      {clock ? (
        <div className="b-demo-scrub">
          <input
            type="range"
            min={DAY_START}
            max={DAY_END}
            step={1}
            value={Math.floor(clock.time)}
            disabled={busy}
            aria-label="Время дня"
            onChange={(event) => {
              clock.pause()
              clock.seek(Number(event.target.value))
            }}
          />
          <div className="b-demo-marks" aria-hidden="true">
            {marks.map((mark, i) => (
              <i
                key={i}
                className={mark.tone}
                style={{ left: `${((mark.t - DAY_START) / (DAY_END - DAY_START)) * 100}%` }}
              />
            ))}
          </div>
          <div className="b-demo-hours" aria-hidden="true">
            {Array.from({ length: 7 }, (_, i) => DAY_START + i * 120).map((t) => (
              <span key={t}>{clockText(t)}</span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Ожидание расчёта сценария: знак-лоадер и что именно считается. Стоит
 * поверх экрана показа вместо счётчиков — пока дня нет, показывать нечего.
 */
export function DemoBusy({ title, detail, first }: { title: string; detail?: string; first?: boolean }) {
  return (
    <div className="b-demo-busy" role="status" aria-live="polite">
      <RouteLoader size={64} label={title} />
      <b>{title}</b>
      {detail ? <span>{detail}</span> : null}
      {first ? <small>{FIRST_RUN_NOTE}</small> : null}
    </div>
  )
}

/**
 * Подпись первого расчёта: утро плана на участке и старте считается один раз
 * и дальше берётся готовым (`mornings.py`), поэтому первый сценарий идёт
 * заметно дольше следующих. Показывается, только когда утра правда ещё нет.
 */
export const FIRST_RUN_NOTE = 'Первый расчёт на участке дольше: утро плана считается один раз, дальше — быстрее'

/** Готово ли утро сценария на сервере — чтобы честно сказать, что первый расчёт дольше. */
export function useFirstRun(datasetId: string | undefined, start: string, settings: Settings | null, enabled: boolean): boolean {
  const ready = useQuery({
    queryKey: ['race-morning', datasetId, start, settings],
    queryFn: () => api.raceMorning({ dataset_id: datasetId!, start, settings }),
    staleTime: 0,
    retry: false,
    enabled: enabled && !!datasetId,
  })
  return ready.data?.ready === false
}
