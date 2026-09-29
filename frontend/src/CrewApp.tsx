/**
 * Приложение бригады — упрощённый аналог приложения курьера, открывается
 * по адресу `#crew/<бригада>`. Пять вкладок внизу, как у Яндекс Про и Uber
 * Driver: смена, карта, маршрут, BeeGPT, профиль. BeeGPT — та же
 * переписка по смене с диспетчером, поданная как помощник.
 *
 * Смена: начать, перерыв, завершить с итогом дня. Карточка «Сейчас» —
 * статусы свайпом (случайное касание отметку не поставит), звонок клиенту
 * через подменный номер, способ поездки со временем и ценой, навигатор,
 * «проблема на заявке» и отчёт: чек-лист, фото, выданное, подпись клиента.
 *
 * Настоящего телефона у прототипа нет, поэтому отметки времени берутся
 * по плану визита, а геопозиция — по адресу заявки. Два переключателя
 * в профиле нарочно ломают честность: отметка не с адреса и закрытие работы
 * за пять минут — чтобы на экране диспетчера зажглись флаги контроля.
 *
 * Всё сверх отметок и предложений — витрина для показа (`crew/`): входа
 * нет, бригада выбирается на первом экране. План читается «последний»
 * с сервера, ответ на предложение и «клиента нет» меняют план у диспетчера
 * тем же путём, каким он менял бы его сам.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, DropdownMenu, Label, Progress, Select, Switch, ThemeProvider } from '@gravity-ui/uikit'
import { api } from './api'
import { applyTheme, initialTheme, type Theme } from './store'
import { num, plural } from './lib/ui'
import {
  IconBriefcase, IconCall, IconCompass, IconDots, IconMap, IconMoon, IconNavigate, IconRoute, IconSun, IconUser,
  IconUsers, IconWarning,
} from './lib/icons'
import { crewsOf } from './components/CrewSettings'
import BeeMark from './components/settings/BeeMark'
import { NO_SHOW_NOTES } from './components/EventDialog'
import CrewTransit from './crew/CrewTransit'
import CrewMap from './crew/CrewMap'
import SwipeButton from './crew/SwipeButton'
import { CallSheet, CHECKLIST, DelaySheet, ProblemSheet, ReportSheet, Sheet, WaysSheet } from './crew/Sheets'
import { ChatTab, ProfileTab } from './crew/CrewTabs'
import { crewApi, navLinks, type Report, type ShiftEvent, type Way } from './crew/crewApi'
import { useAutoHide } from './crew/useAutoHide'
import './crew/crew.css'
import { hideBoot } from './lib/boot'
import { RouteLoader } from './components/RouteLoader'
import type { CrewDay, CrewOffer, Dataset, Engineer, Mark, MarkKind, NoShowNote, Plan, RequestItem, Stop } from './types'

const DECLINE_REASONS = ['далеко ехать', 'не успею по времени', 'нет инструмента', 'личные обстоятельства']

const STATUS: Record<MarkKind | 'planned', string> = {
  planned: 'в плане',
  depart: 'в пути',
  arrive: 'на месте',
  start: 'в работе',
  done: 'готово',
  no_show: 'клиента нет',
}

const NEXT: Record<MarkKind | 'planned', { kind: MarkKind; label: string } | null> = {
  planned: { kind: 'depart', label: 'Выехал' },
  depart: { kind: 'arrive', label: 'Прибыл' },
  arrive: { kind: 'start', label: 'Начал работу' },
  start: { kind: 'done', label: 'Завершил' },
  done: null,
  no_show: null,
}

/** Подписи устройств; ключи — как в данных заявки. */
const KIT: Record<string, string> = { router: 'роутер', tv_box: 'ТВ-приставка', speaker: 'умная колонка' }

type Tab = 'shift' | 'map' | 'route' | 'chat' | 'profile'
const TABS: { id: Tab; label: string; Icon: (p: { className?: string }) => React.ReactNode }[] = [
  { id: 'shift', label: 'Смена', Icon: IconBriefcase },
  { id: 'map', label: 'Карта', Icon: IconMap },
  { id: 'route', label: 'Маршрут', Icon: IconRoute },
  { id: 'chat', label: 'BeeGPT', Icon: ({ className }) => <BeeMark size={22} className={`b-i-bee${className ? ` ${className}` : ''}`} /> },
  { id: 'profile', label: 'Профиль', Icon: IconUser },
]

function addMin(clock: string, minutes: number): string {
  const [h, m] = clock.split(':').map(Number)
  const total = h * 60 + m + minutes
  return `${String(Math.floor(total / 60) % 24).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

function statusOf(marks: Mark[], requestId: string): MarkKind | 'planned' {
  const order: MarkKind[] = ['depart', 'arrive', 'start', 'done', 'no_show']
  let best: MarkKind | 'planned' = 'planned'
  for (const mark of marks) {
    if (mark.request_id !== requestId) continue
    if (best === 'planned' || order.indexOf(mark.kind) > order.indexOf(best as MarkKind)) best = mark.kind
  }
  return best
}

const nowClock = () => new Date().toTimeString().slice(0, 5)

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // приватное окно: выбор живёт до перезагрузки
  }
}

export function crewIdFromHash(hash: string): string | null {
  const match = /^#crew\/?([^/?]*)/.exec(hash)
  return match ? match[1] || null : null
}

export default function CrewApp() {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const [engineerId, setEngineerId] = useState<string | null>(() => crewIdFromHash(window.location.hash))
  const [tab, setTab] = useState<Tab>('shift')
  const [sheetOpen, setSheetOpen] = useState(false)
  const header = useRef<HTMLElement>(null)
  const hidden = useAutoHide(sheetOpen, header)
  useEffect(() => applyTheme(theme), [theme])
  // У бригады свой экран загрузки смены — общий снимается сразу.
  useEffect(() => hideBoot(), [])
  useEffect(() => {
    const onHash = () => setEngineerId(crewIdFromHash(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const latest = useQuery({ queryKey: ['latest'], queryFn: () => api.latestPlan(), refetchInterval: 5000, retry: false })
  const dataset = useQuery({
    queryKey: ['dataset', latest.data?.dataset_id],
    queryFn: () => api.dataset(latest.data!.dataset_id),
    enabled: Boolean(latest.data),
    staleTime: Infinity,
  })
  const region = latest.data?.dataset_id ?? ''
  const unread = useQuery({
    queryKey: ['crew-chat', region, engineerId],
    queryFn: () => crewApi.messages(region, engineerId!),
    enabled: Boolean(region && engineerId),
    refetchInterval: 6000,
    retry: false,
  })
  const badge = (unread.data ?? []).filter((m) => m.author === 'dispatcher' && !m.read).length

  return (
    <ThemeProvider theme={theme}>
      <div className={`b-crew${engineerId ? ' with-tabs' : ''}`}>
        <header ref={header} className={`b-crew-top${hidden ? ' away' : ''}`}>
          <span className="b-brand">
            <img src="/brand/beeline-logo.svg" alt="" width={24} height={24} />
            <b>билайн бизнес</b>
            <span>Моя смена</span>
          </span>
          {/* «…» как у диспетчера и руководителя: другая бригада, соседние экраны, тема.
              Экраны открываются в этой же вкладке — main.tsx перезагрузит приложение под адрес. */}
          <DropdownMenu
            size="l"
            renderSwitcher={(props) => (
              <Button {...props} view="flat" size="m" className="b-more" title="Ещё: бригада, экраны, тема" aria-label="Ещё">
                <IconDots />
              </Button>
            )}
            items={[
              ...(engineerId ? [[{ text: 'Другая бригада', iconStart: <IconUsers />, href: '#crew' }]] : []),
              [
                { text: 'Экран диспетчера', iconStart: <IconMap />, href: '#' },
                { text: 'Экран руководителя', iconStart: <IconBriefcase />, href: '#manager' },
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
        </header>
        {latest.isError ? (
          <p className="b-crew-empty">
            {(latest.error as { status?: number } | null)?.status === 404
              ? 'План на сегодня ещё не построен. Диспетчер строит его на своём экране — смена появится здесь сама.'
              : 'Сервер планировщика не отвечает. Приложение бригады работает только с ним.'}
          </p>
        ) : !engineerId ? (
          <Picker engineers={dataset.data?.engineers ?? []} plan={latest.data ?? null} />
        ) : (
          <Day
            engineerId={engineerId}
            region={region}
            plan={latest.data ?? null}
            dataset={dataset.data ?? null}
            tab={tab}
            theme={theme}
            onTab={setTab}
            onSheet={setSheetOpen}
          />
        )}
        {engineerId ? (
          <nav className="b-crew-tabs" aria-label="Разделы">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={tab === t.id ? 'on' : ''}
                aria-current={tab === t.id ? 'page' : undefined}
                onClick={() => {
                  setTab(t.id)
                  window.scrollTo({ top: 0 })
                }}
              >
                <t.Icon />
                <span>{t.label}</span>
                {t.id === 'chat' && badge ? <b className="b-badge" aria-label={`${badge} новых`}>{badge}</b> : null}
              </button>
            ))}
          </nav>
        ) : null}
      </div>
    </ThemeProvider>
  )
}

function Picker({ engineers, plan }: { engineers: Engineer[]; plan: Plan | null }) {
  // Дом из правил дня (руководитель или сама бригада) главнее дома из набора.
  const crews = plan?.settings ? crewsOf(plan.settings) : {}
  return (
    <div className="b-crew-body">
      <h2>Кто вы?</h2>
      <p className="b-crew-muted">В настоящем приложении вход был бы по учётной записи. Здесь — выбором.</p>
      <ul className="b-crew-list">
        {engineers.map((engineer) => (
          <li key={engineer.id}>
            <a href={`#crew/${engineer.id}`}>
              <b>{engineer.name}</b>
              <span>
                смена {engineer.shift_start}–{engineer.shift_end} · {engineer.skills.length}{' '}
                {plural(engineer.skills.length, 'навык', 'навыка', 'навыков')}
              </span>
              {crews[engineer.id]?.home?.address ?? engineer.home?.address ? (
                <em>{crews[engineer.id]?.home?.address ?? engineer.home?.address}</em>
              ) : null}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

type SheetKind = 'ways' | 'call' | 'report' | 'problem' | 'summary' | 'delay' | null

function Day({ engineerId, region, plan, dataset, tab, theme, onTab, onSheet }: {
  engineerId: string
  region: string
  plan: Plan | null
  dataset: Dataset | null
  tab: Tab
  theme: Theme
  onTab: (tab: Tab) => void
  onSheet: (open: boolean) => void
}) {
  const client = useQueryClient()
  const [spoofGeo, setSpoofGeo] = useState(false)
  const [fastClose, setFastClose] = useState(false)
  const [note, setNote] = useState<NoShowNote>('absent')
  const [toast, setToast] = useState<string | null>(null)
  const [sheet, setSheetState] = useState<SheetKind>(null)
  const setSheet = (kind: SheetKind) => {
    setSheetState(kind)
    onSheet(kind !== null)
  }
  const shiftKey = `b-crew-shift:${region}:${engineerId}`
  const [shift, setShift] = useState<ShiftEvent[]>(() => readJson(shiftKey, []))
  const waysKey = `b-crew-ways:${engineerId}`
  const [chosen, setChosen] = useState<Record<string, Way['kind']>>(() => readJson(waysKey, {}))

  const day = useQuery({
    queryKey: ['crew', engineerId],
    queryFn: () => api.crew('latest', engineerId),
    refetchInterval: 4000,
    retry: false,
  })
  const reports = useQuery({
    queryKey: ['crew-reports', region, engineerId],
    queryFn: () => crewApi.reports(region, engineerId),
    enabled: Boolean(region),
    retry: false,
  })

  const refresh = () => {
    void client.invalidateQueries({ queryKey: ['crew', engineerId] })
    void client.invalidateQueries({ queryKey: ['latest'] })
  }
  const say = (text: string) => {
    setToast(text)
    window.setTimeout(() => setToast(null), 4000)
  }
  const shiftState = shift.length ? shift[shift.length - 1].kind : null
  const onShift = shiftState === 'start' || shiftState === 'resume'
  const pushShift = (kind: ShiftEvent['kind']) => {
    const event = { kind, time: nowClock() }
    const next = kind === 'start' ? [event] : [...shift, event]
    setShift(next)
    writeJson(shiftKey, next)
    // Смена живёт в телефоне; сервер узнаёт о ней, когда доступен.
    if (region) {
      crewApi.shiftEvent(region, engineerId, event).catch(() => {
        // Сервер перезапустился и смены не помнит: восстанавливаем её начало
        // и повторяем событие — телефон тут источник правды.
        const begun = next.find((e) => e.kind === 'start') ?? event
        if (kind === 'start') return
        crewApi
          .shiftEvent(region, engineerId, { kind: 'start', time: begun.time })
          .then(() => crewApi.shiftEvent(region, engineerId, event))
          .catch(() => undefined)
      })
    }
  }

  const mark = useMutation({
    mutationFn: async ({ stop, request, kind }: { stop: Stop; request: RequestItem; kind: MarkKind }) => {
      const planId = day.data!.plan_id
      const time =
        kind === 'depart' ? stop.depart_prev
        : kind === 'arrive' ? stop.arrive
        : kind === 'start' ? stop.start
        : kind === 'done' ? (fastClose ? addMin(stop.start, 5) : stop.end)
        : stop.arrive
      const shiftGeo = spoofGeo ? 0.02 : 0
      const result = await api.mark(planId, {
        engineer_id: engineerId, request_id: request.id, kind, time,
        lat: request.lat + shiftGeo, lon: request.lon + shiftGeo,
      })
      if (kind === 'no_show') {
        await api.replan(planId, { id: `crew-${Date.now()}`, type: 'no_show', time, request_id: request.id, note })
      }
      return result
    },
    onSuccess: (result, vars) => {
      refresh()
      const mine = result.flags.filter((flag) => flag.engineer_id === engineerId)
      say(
        vars.kind === 'no_show'
          ? 'Отмечено: клиента нет. Заявка ушла диспетчеру на перенос'
          : mine.length
            ? `Отметка принята. У диспетчера ${mine.length} ${plural(mine.length, 'вопрос', 'вопроса', 'вопросов')} к отметкам`
            : 'Отметка принята',
      )
    },
    onError: (error) => say(`Не отметилось: ${String(error)}`),
  })

  const respond = useMutation({
    mutationFn: ({ offer, accepted, reason }: { offer: CrewOffer; accepted: boolean; reason?: string }) =>
      api.respond(day.data!.plan_id, {
        request_id: offer.request_id, engineer_id: engineerId, accepted, reason: reason ?? null, time: offer.arrive,
      }),
    onSuccess: (result) => {
      refresh()
      say(result.text)
    },
    onError: (error) => say(`Ответ не дошёл: ${String(error)}`),
  })

  const saveReport = useMutation({
    mutationFn: (report: Report) => crewApi.report(region, engineerId, report),
    onSuccess: (report) => {
      client.setQueryData(['crew-reports', region, engineerId], { ...(reports.data ?? {}), [report.request_id]: report })
      setSheet(null)
      say('Отчёт сохранён')
    },
    onError: (error) => say(`Отчёт не сохранился: ${String(error)}`),
  })

  const data: CrewDay | undefined = day.data
  const requests = useMemo(() => new Map((data?.requests ?? []).map((item) => [item.id, item])), [data])
  if (day.isError) return <p className="b-crew-empty">Смены на сегодня для этой бригады нет.</p>
  if (!data)
    return (
      <div className="b-crew-empty b-crew-loading">
        <RouteLoader size={56} label="Загружаем смену" />
        <p aria-hidden="true">Загружаем смену</p>
      </div>
    )

  const stops = data.route.stops
  const next = stops.find((stop) => stop.request_id === data.next_request_id) ?? null
  const nextRequest = next ? requests.get(next.request_id) ?? null : null
  const nextStatus = next ? statusOf(data.marks, next.request_id) : 'planned'
  const nextAction = NEXT[nextStatus]
  const earn = data.earnings
  const total = earn.day_rub + earn.bonus_confirmed_rub
  const planned = earn.day_rub + earn.bonus_planned_rub
  const report = next ? reports.data?.[next.request_id] ?? null : null
  const reportItems = nextRequest ? (CHECKLIST[nextRequest.type_bk] ?? ['', '']).length : 0
  const reportDone = Boolean(report && report.checklist.length >= reportItems && report.photos_after > 0 && report.signed)
  const way = next ? chosen[next.request_id] ?? null : null
  const engineerHome = data.engineer.home ? ([data.engineer.home.lat, data.engineer.home.lon] as [number, number]) : null
  const office = dataset ? ([dataset.office.lat, dataset.office.lon] as [number, number]) : null
  const start = plan?.start === 'home' && engineerHome ? engineerHome : office
  const origin = (() => {
    const index = next ? stops.indexOf(next) : -1
    if (index > 0) {
      const prev = requests.get(stops[index - 1].request_id)
      return prev ? ([prev.lat, prev.lon] as [number, number]) : start
    }
    return start
  })()
  const choose = (kind: Way['kind']) => {
    if (!next) return
    const updated = { ...chosen, [next.request_id]: kind }
    setChosen(updated)
    writeJson(waysKey, updated)
  }
  const doneStops = stops.filter((s) => statusOf(data.marks, s.request_id) === 'done')
  const planOptions = ((plan?.settings as { options?: Record<string, unknown> } | undefined)?.options ?? {}) as Record<string, unknown>
  const waits = (plan?.standby ?? []).filter((s) => s.engineer_id === engineerId)

  const shiftCard = (
    <section className={`b-crew-card shift ${shiftState ?? 'off'}`}>
      {!shiftState || shiftState === 'end' ? (
        <>
          <h3>{shiftState === 'end' ? 'Смена завершена' : 'Смена не начата'}</h3>
          <p className="b-crew-muted">
            План на сегодня: {stops.length} {plural(stops.length, 'визит', 'визита', 'визитов')}, первый в {stops[0]?.arrive ?? '—'}. Начните смену, чтобы отмечать
            визиты и получать предложения.
          </p>
          <SwipeButton label="Начать смену" onConfirm={() => pushShift('start')} />
        </>
      ) : (
        <>
          <div className="b-shift-row">
            <span className={`b-dot ${onShift ? 'on' : 'pause'}`} aria-hidden="true" />
            <b>{onShift ? 'На смене' : 'Перерыв'}</b>
            <span className="b-crew-muted">с {shift.find((e) => e.kind === 'start')?.time}</span>
          </div>
          <div className="b-shift-acts">
            {onShift ? (
              <Button view="normal" size="l" onClick={() => pushShift('pause')}>
                Перерыв
              </Button>
            ) : (
              <Button view="action" size="l" onClick={() => pushShift('resume')}>
                Вернуться к работе
              </Button>
            )}
            <Button view="outlined" size="l" onClick={() => setSheet('summary')}>
              Завершить смену
            </Button>
          </div>
          {data.route.break_start ? (
            <p className="b-crew-muted">
              Обед по плану {data.route.break_start}–{data.route.break_end}
            </p>
          ) : null}
        </>
      )}
    </section>
  )

  const shiftTab = (
    <div className="b-crew-body">
      {shiftCard}
      <section className="b-crew-card money">
        <small>Заработок сегодня</small>
        <b>{num(total)} ₽</b>
        <span>
          оклад {num(earn.day_rub)} ₽{earn.bonus_confirmed_rub ? ` + бонус ${num(earn.bonus_confirmed_rub)} ₽` : ''}
          {planned > total ? ` · по плану до ${num(planned)} ₽` : ''}
        </span>
        <div className="b-crew-norm">
          <Progress
            size="s"
            theme={earn.norm_confirmed_min >= earn.norm_day_min ? 'success' : 'info'}
            value={Math.min(100, (100 * earn.norm_confirmed_min) / Math.max(earn.norm_day_min, 1))}
          />
          <span>
            норма {earn.norm_confirmed_min} из {earn.norm_day_min} нормо-мин
            {earn.over_norm_min ? ` · в плане сверх нормы ${earn.over_norm_min}` : ''}
          </span>
        </div>
      </section>

      {(data.kit && Object.keys(data.kit).length) || Object.values(data.stock ?? {}).some((n) => n > 0) ? (
        <section className="b-crew-card money">
          <small>Взять утром</small>
          <b>
            {Object.entries(data.stock && Object.keys(data.stock).length ? data.stock : data.kit ?? {})
              .filter(([, count]) => count > 0)
              .map(([item, count]) => `${KIT[item] ?? item} × ${count}`)
              .join(' · ')}
          </b>
          <span>по заявкам дня и запас сверх них; устройства выдаёт склад</span>
          {data.stock_left && Object.keys(data.stock_left).length ? (
            <span>
              запас под заявки дня:{' '}
              {Object.entries(data.stock_left).some(([, n]) => n > 0)
                ? Object.entries(data.stock_left)
                    .filter(([, n]) => n > 0)
                    .map(([item, n]) => `${KIT[item] ?? item} × ${n}`)
                    .join(' · ')
                : 'кончился — заявки с устройством уйдут другим бригадам'}
            </span>
          ) : null}
        </section>
      ) : null}

      {data.offers.length ? (
        <section className="b-crew-card offers">
          <h3>Предложение{data.offers.length > 1 ? 'я' : ''} · ответить за {data.offers[0].expires_in_min} мин</h3>
          {data.offers.map((offer) => (
            <OfferCard
              key={offer.request_id}
              offer={offer}
              busy={respond.isPending}
              onAccept={() => respond.mutate({ offer, accepted: true })}
              onDecline={(reason) => respond.mutate({ offer, accepted: false, reason })}
            />
          ))}
        </section>
      ) : null}

      <section className="b-crew-card now">
        <h3>{next ? 'Сейчас' : 'Маршрут на сегодня закрыт'}</h3>
        {next && nextRequest ? (
          <>
            <div className="b-crew-visit">
              <b>{nextRequest.type_bk}</b>
              <span>{nextRequest.address}</span>
              <span className="b-crew-muted">
                окно {nextRequest.window_start}–{nextRequest.window_end} · приезд {next.arrive} · работа{' '}
                {nextRequest.duration_min} мин
              </span>
              <Label size="s" theme={nextStatus === 'start' ? 'info' : 'normal'}>
                {STATUS[nextStatus]}
              </Label>
            </div>
            <div className="b-quick" role="group" aria-label="Действия с заявкой">
              <button type="button" onClick={() => setSheet('call')}>
                <IconCall />Позвонить
              </button>
              <button type="button" onClick={() => setSheet('ways')}>
                <IconCompass />
                {way ? 'Поеду иначе' : 'Как поеду'}
              </button>
              {origin ? (
                <a href={navLinks(origin, [nextRequest.lat, nextRequest.lon], way ?? (next.mode === 'car' ? 'car' : 'transit')).yandex} target="_blank" rel="noreferrer">
                  <IconNavigate />Навигатор
                </a>
              ) : null}
              <button type="button" onClick={() => setSheet('problem')}>
                <IconWarning />Проблема
              </button>
            </div>
            <div className="b-crew-acts">
              {onShift && (nextStatus === 'planned' || nextStatus === 'depart') ? (
                <Button view="outlined" size="l" width="max" onClick={() => setSheet('delay')}>
                  Задерживаюсь
                </Button>
              ) : null}
              {!onShift ? (
                <p className="b-crew-muted">
                  {shiftState === 'pause' ? 'Вы на перерыве: вернитесь к работе, чтобы отмечать визиты.' : 'Начните смену, чтобы отмечать визиты.'}
                </p>
              ) : null}
              {nextStatus === 'start' ? (
                <Button view={reportDone ? 'flat' : 'normal'} size="l" width="max" onClick={() => setSheet('report')}>
                  {reportDone ? 'Отчёт готов · изменить' : report ? 'Отчёт не закончен' : 'Отчёт по заявке'}
                </Button>
              ) : null}
              {nextAction ? (
                <SwipeButton
                  label={nextAction.kind === 'done' && !reportDone ? 'Завершил — сначала отчёт' : nextAction.label}
                  disabled={!onShift || mark.isPending || (nextAction.kind === 'done' && !reportDone)}
                  onConfirm={() => mark.mutate({ stop: next, request: nextRequest, kind: nextAction.kind })}
                />
              ) : null}
              {nextStatus === 'arrive' ? (
                <div className="b-crew-noshow">
                  <Select
                    size="l"
                    width="max"
                    value={[note]}
                    onUpdate={([value]) => setNote(value as NoShowNote)}
                    options={NO_SHOW_NOTES}
                  />
                  <Button
                    view="outlined-danger"
                    size="l"
                    disabled={!onShift || mark.isPending}
                    onClick={() => mark.mutate({ stop: next, request: nextRequest, kind: 'no_show' })}
                  >
                    Клиента нет
                  </Button>
                </div>
              ) : null}
              {(way === 'transit' || (!way && next.mode === 'transit')) && (nextStatus === 'planned' || nextStatus === 'depart') ? (
                <CrewTransit key={next.request_id} planId={data.plan_id} engineerId={engineerId} requestId={next.request_id} />
              ) : null}
            </div>
          </>
        ) : (
          <p className="b-crew-muted">Все визиты отмечены. Новые заявки придут предложением.</p>
        )}
      </section>
    </div>
  )

  const routeTab = (
    <div className="b-crew-body">
      <section className="b-crew-card route">
        <h3>
          Маршрут дня · {stops.length} {plural(stops.length, 'визит', 'визита', 'визитов')}
        </h3>
        <ol className="b-crew-route">
          {stops.map((stop) => {
            const request = requests.get(stop.request_id)
            const status = stop.status === 'no_show' ? 'no_show' : statusOf(data.marks, stop.request_id)
            return (
              <li key={stop.request_id} className={`${status}${stop.request_id === next?.request_id ? ' next' : ''}`}>
                <time>{stop.arrive}</time>
                <span>
                  <b>{request?.type_bk ?? stop.request_id}</b>
                  <em>{request?.address ?? ''}</em>
                  <em>
                    окно {request?.window_start}–{request?.window_end} · дорога {stop.travel_min} мин
                  </em>
                </span>
                <Label size="xs" theme={status === 'done' ? 'success' : status === 'no_show' ? 'danger' : 'normal'}>
                  {STATUS[status]}
                </Label>
              </li>
            )
          })}
        </ol>
        {data.route.break_start ? (
          <p className="b-crew-muted">Обед {data.route.break_start}–{data.route.break_end}</p>
        ) : null}
        {waits.length ? (
          <div className="b-waits">
            <h4>Где ждать между визитами</h4>
            {waits.map((w) => (
              <p key={`${w.after_request_id}-${w.start}`}>
                <time>
                  {w.start}–{w.end}
                </time>
                {w.text}
              </p>
            ))}
          </div>
        ) : null}
        <Button view="normal" size="l" width="max" onClick={() => onTab('map')}>
          Показать на карте
        </Button>
      </section>
    </div>
  )

  return (
    <>
      {tab === 'shift' ? shiftTab : null}
      {tab === 'map' ? (
        <CrewMap
          day={data}
          start={start}
          statusOf={(id) => statusOf(data.marks, id)}
          nextId={next?.request_id ?? null}
          way={way}
          theme={theme}
        />
      ) : null}
      {tab === 'route' ? routeTab : null}
      {tab === 'chat' ? <ChatTab region={region} engineerId={engineerId} requestId={next?.request_id ?? null} /> : null}
      {tab === 'profile' ? (
        <ProfileTab region={region} engineerId={engineerId} name={data.engineer.name}>
          <section className="b-crew-card demo">
            <h3>Для показа контроля</h3>
            <Switch size="m" checked={spoofGeo} onUpdate={setSpoofGeo} content="Отмечаться в двух километрах от адреса" />
            <Switch size="m" checked={fastClose} onUpdate={setFastClose} content="Закрывать работу через 5 минут" />
            <p className="b-crew-muted">
              Оба переключателя зажигают флаги у диспетчера: бонус за такой визит не начисляется до подтверждения.
            </p>
          </section>
        </ProfileTab>
      ) : null}

      {sheet === 'ways' && next ? (
        <WaysSheet
          planId={data.plan_id}
          engineerId={engineerId}
          requestId={next.request_id}
          chosen={way}
          onChoose={(kind) => {
            choose(kind)
            say('Способ выбран: карта и навигатор покажут его')
          }}
          onClose={() => setSheet(null)}
        />
      ) : null}
      {sheet === 'call' && nextRequest ? (
        <CallSheet planId={data.plan_id} engineerId={engineerId} request={nextRequest} onClose={() => setSheet(null)} />
      ) : null}
      {sheet === 'report' && nextRequest ? (
        <ReportSheet request={nextRequest} initial={report} onSave={(r) => saveReport.mutate(r)} onClose={() => setSheet(null)} />
      ) : null}
      {sheet === 'delay' && next ? (
        <DelaySheet
          step={Number(planOptions.delay_step_min ?? 15)}
          autoFrom={planOptions.delay_auto_replan === false ? null : Number(planOptions.delay_auto_min ?? 15)}
          onClose={() => setSheet(null)}
          onSend={(minutes) => {
            setSheet(null)
            crewApi.delay(data.plan_id, engineerId, minutes, next.depart_prev, next.request_id).then(
              (got) => {
                refresh()
                say(got.text)
              },
              (e) => say(`Сигнал не ушёл: ${String(e)}`),
            )
          }}
        />
      ) : null}
      {sheet === 'problem' ? (
        <ProblemSheet
          onClose={() => setSheet(null)}
          onSend={(text, sos) => {
            crewApi
              .say(region, engineerId, { text, kind: sos ? 'sos' : 'problem', request_id: next?.request_id ?? null })
              .then(
                () => say(sos ? 'SOS отправлен диспетчеру' : 'Диспетчер получил сообщение о проблеме'),
                (e) => say(`Не отправилось: ${String(e)}`),
              )
            setSheet(null)
          }}
        />
      ) : null}
      {sheet === 'summary' ? (
        <Sheet title="Итоги смены" onClose={() => setSheet(null)}>
          <dl className="b-summary">
            <div>
              <dt>Визитов</dt>
              <dd>
                {doneStops.length} из {stops.length}
              </dd>
            </div>
            <div>
              <dt>Вовремя</dt>
              <dd>{doneStops.filter((s) => s.late_min === 0).length}</dd>
            </div>
            <div>
              <dt>Дорога</dt>
              <dd>
                {doneStops.reduce((s, x) => s + x.travel_min, 0)} мин · {num(doneStops.reduce((s, x) => s + x.travel_km, 0), 1)} км
              </dd>
            </div>
            <div>
              <dt>Норма</dt>
              <dd>
                {earn.norm_confirmed_min} из {earn.norm_day_min} нормо-мин
              </dd>
            </div>
            <div>
              <dt>Заработано</dt>
              <dd>{num(total)} ₽</dd>
            </div>
          </dl>
          {doneStops.length < stops.length ? (
            <p className="b-crew-muted">
              Не отмечено {stops.length - doneStops.length} {plural(stops.length - doneStops.length, 'визит', 'визита', 'визитов')}: после завершения смены они уйдут диспетчеру.
            </p>
          ) : null}
          <SwipeButton
            label="Завершить смену"
            tone="danger"
            onConfirm={() => {
              pushShift('end')
              setSheet(null)
              say('Смена завершена')
            }}
          />
        </Sheet>
      ) : null}

      {toast ? (
        <div className="b-crew-toast" role="status">
          {toast}
        </div>
      ) : null}
    </>
  )
}

function OfferCard({
  offer,
  busy,
  onAccept,
  onDecline,
}: {
  offer: CrewOffer
  busy: boolean
  onAccept: () => void
  onDecline: (reason: string) => void
}) {
  const [reason, setReason] = useState(DECLINE_REASONS[0])
  return (
    <div className="b-crew-offer">
      <div className="b-crew-visit">
        <b>{offer.address}</b>
        <span className="b-crew-muted">
          окно {offer.window} · работа {offer.duration_min} мин · приезд {offer.arrive} ·{' '}
          {offer.delta_travel_min > 0
            ? `+${offer.delta_travel_min} мин дороги`
            : offer.delta_travel_min < 0
              ? `дорога короче на ${-offer.delta_travel_min} мин`
              : 'без лишней дороги'}
        </span>
        <b className="bonus">{offer.bonus_rub ? `+${num(offer.bonus_rub)} ₽ сверх нормы` : 'в пределах нормы дня'}</b>
      </div>
      <div className="b-crew-acts">
        <Button view="action" size="l" width="max" disabled={busy} onClick={onAccept}>
          Беру
        </Button>
        <div className="b-crew-noshow">
          <Select
            size="l"
            width="max"
            value={[reason]}
            onUpdate={([value]) => setReason(value ?? DECLINE_REASONS[0])}
            options={DECLINE_REASONS.map((value) => ({ value, content: value }))}
          />
          <Button view="outlined" size="l" disabled={busy} onClick={() => onDecline(reason)}>
            Отказаться
          </Button>
        </div>
      </div>
    </div>
  )
}
