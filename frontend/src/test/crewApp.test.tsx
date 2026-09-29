/**
 * Приложение бригады: предложение видно с бонусом, «Беру» уходит ответом
 * на сервер; отметки ставятся свайпом и только на смене; «Завершил» ждёт
 * отчёта; адрес старта уходит в профиль со следующего плана.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CrewApp, { crewIdFromHash } from '../CrewApp'
import { DATASET } from '../fixtures/yugo-vostok'
import { buildPlan } from '../fixtures/planner'
import type { CrewDay } from '../types'

const plan = buildPlan(DATASET, { algorithm: 'baseline', id: 'p-test' })
const route = plan.routes.find((item) => item.stops.length >= 2)!
const engineer = DATASET.engineers.find((item) => item.id === route.engineer_id)!
const requests = DATASET.requests.filter((item) => route.stops.some((stop) => stop.request_id === item.id))

const day: CrewDay = {
  plan_id: 'p-test',
  engineer,
  route,
  requests: [...requests, { ...DATASET.requests[0], id: 'n-1', address: 'Домодедово, Речная, 5' }],
  marks: [],
  offers: [
    {
      request_id: 'n-1', address: 'Домодедово, Речная, 5', window: '15:00–18:00', duration_min: 90,
      arrive: '15:20', delta_travel_min: 12, bonus_rub: 1080, text: 'после заявки', expires_in_min: 5,
    },
  ],
  earnings: {
    day_rub: 7000, bonus_planned_rub: 1080, bonus_confirmed_rub: 0, norm_day_min: 480,
    norm_planned_min: 520, norm_confirmed_min: 0, over_norm_min: 40,
  },
  next_request_id: route.stops[0].request_id,
}

let crewDay: CrewDay = day

const calls: { respond: unknown[]; mark: unknown[]; replan: unknown[]; profile: unknown[]; shift: unknown[] } = {
  respond: [], mark: [], replan: [], profile: [], shift: [],
}
let reports: Record<string, unknown> = {}

vi.mock('../crew/crewApi', () => ({
  crewApi: {
    messages: async () => [],
    reports: async () => reports,
    report: async (_r: string, _e: string, report: { request_id: string }) => report,
    shiftEvent: async (_r: string, _e: string, event: unknown) => {
      calls.shift.push(event)
      return [event]
    },
    history: async () => ({ rating: 4.9, reviews_count: 12, days: [], reviews: [] }),
    profile: async () => ({
      engineer_id: engineer.id, since: null, since_plan: null, start_id: 'home',
      addresses: [
        { id: 'home', label: 'Дом', address: 'рядом с офисом', lat: 55.6, lon: 37.6 },
        { id: 'dacha', label: 'Дача', address: 'Видное, Садовая, 3', lat: 55.55, lon: 37.71 },
      ],
    }),
    saveProfile: async (_r: string, _e: string, profile: { start_id: string }) => {
      calls.profile.push(profile)
      return { ...profile, since: '2026-09-19T12:30', since_plan: 'p-test' }
    },
  },
  navLinks: () => ({ yandex: 'https://yandex.ru/maps', dgis: 'https://2gis.ru' }),
}))

vi.mock('../api', () => ({
  api: {
    latestPlan: async () => plan,
    dataset: async () => DATASET,
    crew: async () => crewDay,
    respond: async (_id: string, response: unknown) => {
      calls.respond.push(response)
      return { plan, text: 'Бригада приняла заявку n-1' }
    },
    mark: async (_id: string, mark: unknown) => {
      calls.mark.push(mark)
      return { plan_id: 'p-test', marks: [mark], flags: [] }
    },
    replan: async (_id: string, event: unknown) => {
      calls.replan.push(event)
      return plan
    },
  },
  ApiError: class extends Error {},
}))

function mount() {
  window.location.hash = `#crew/${engineer.id}`
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CrewApp />
    </QueryClientProvider>,
  )
}

test('адрес бригады читается из решётки', () => {
  expect(crewIdFromHash('#crew/lebedev')).toBe('lebedev')
  expect(crewIdFromHash('#crew')).toBeNull()
})

test('предложение видно с бонусом, «Беру» уходит ответом', async () => {
  mount()
  await screen.findByText('Домодедово, Речная, 5')
  expect(screen.getByText(/\+1 080 ₽ сверх нормы/)).toBeInTheDocument()
  expect(screen.getByText('7 000 ₽')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Беру' }))
  await waitFor(() => expect(calls.respond).toHaveLength(1))
  expect(calls.respond[0]).toMatchObject({ request_id: 'n-1', engineer_id: engineer.id, accepted: true })
  await screen.findByText('Бригада приняла заявку n-1')
})

test('отметка — только на смене и только свайпом: касание её не ставит', async () => {
  localStorage.clear()
  calls.mark.length = 0
  mount()
  const depart = await screen.findByRole('button', { name: 'Выехал' })
  expect(depart).toHaveAttribute('aria-disabled', 'true')
  fireEvent.keyDown(screen.getByRole('button', { name: 'Начать смену' }), { key: 'Enter' })
  await waitFor(() => expect(calls.shift).toHaveLength(1))
  expect(screen.getByText('На смене')).toBeInTheDocument()
  // Касание подсказывает, но не отмечает.
  fireEvent.pointerDown(depart, { clientX: 10, pointerId: 1 })
  fireEvent.pointerUp(depart, { clientX: 10, pointerId: 1 })
  expect(screen.getByText('Проведите вправо →')).toBeInTheDocument()
  expect(calls.mark).toHaveLength(0)
  fireEvent.keyDown(depart, { key: 'Enter' })
  await waitFor(() => expect(calls.mark).toHaveLength(1))
  expect(calls.mark[0]).toMatchObject({ kind: 'depart', request_id: route.stops[0].request_id, time: route.stops[0].depart_prev })
  // На перерыве отмечать нельзя.
  fireEvent.click(screen.getByRole('button', { name: 'Перерыв' }))
  expect(screen.getByRole('button', { name: 'Выехал' })).toHaveAttribute('aria-disabled', 'true')
})

test('свайп пальцем до конца ставит отметку', async () => {
  localStorage.clear()
  calls.mark.length = 0
  mount()
  fireEvent.keyDown(await screen.findByRole('button', { name: 'Начать смену' }), { key: 'Enter' })
  const depart = await screen.findByRole('button', { name: 'Выехал' })
  depart.getBoundingClientRect = () => ({ width: 300, height: 56, left: 0, top: 0, right: 300, bottom: 56, x: 0, y: 0, toJSON: () => ({}) })
  fireEvent.pointerDown(depart, { clientX: 0, pointerId: 1 })
  fireEvent.pointerMove(depart, { clientX: 150, pointerId: 1 })
  fireEvent.pointerUp(depart, { clientX: 150, pointerId: 1 })
  expect(calls.mark).toHaveLength(0)
  fireEvent.pointerDown(depart, { clientX: 0, pointerId: 1 })
  fireEvent.pointerMove(depart, { clientX: 290, pointerId: 1 })
  fireEvent.pointerUp(depart, { clientX: 290, pointerId: 1 })
  await waitFor(() => expect(calls.mark).toHaveLength(1))
})

test('«Завершил» ждёт полного отчёта', async () => {
  localStorage.clear()
  const first = route.stops[0].request_id
  const started = { ...day, marks: [{ engineer_id: engineer.id, request_id: first, kind: 'start' as const, time: route.stops[0].start }] }
  crewDay = started
  reports = {}
  mount()
  fireEvent.keyDown(await screen.findByRole('button', { name: 'Начать смену' }), { key: 'Enter' })
  expect(await screen.findByRole('button', { name: 'Завершил — сначала отчёт' })).toHaveAttribute('aria-disabled', 'true')
  expect(screen.getByRole('button', { name: 'Отчёт по заявке' })).toBeInTheDocument()
  crewDay = day
})

test('адрес старта меняется со следующего плана', async () => {
  localStorage.clear()
  mount()
  fireEvent.click(await screen.findByRole('button', { name: /Профиль/ }))
  fireEvent.click(await screen.findByRole('radio', { name: /Дача/ }))
  await waitFor(() => expect(calls.profile).toHaveLength(1))
  expect(calls.profile[0]).toMatchObject({ start_id: 'dacha' })
  expect(await screen.findByText(/Со следующего плана: старт «Дача»/)).toBeInTheDocument()
  expect(screen.getByText(/план p-test идёт как шёл/)).toBeInTheDocument()
})
