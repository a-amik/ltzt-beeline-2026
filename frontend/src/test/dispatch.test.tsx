/**
 * Экран диспетчера: детали бригады сужают список до её маршрута, лента
 * от бригад открывает детали нужной бригады, ручной приоритет уходит
 * в настройки плана.
 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from '@gravity-ui/uikit'
import RequestList from '../components/RequestList'
import FeedPanel, { FeedButton } from '../dispatch/FeedPanel'
import CrewCard from '../dispatch/CrewCard'
import { DATASET } from '../fixtures/yugo-vostok'
import { buildPlan } from '../fixtures/planner'
import { useStore } from '../store'

const plan = buildPlan(DATASET, { algorithm: 'solver', id: 'p-d' })
const route = plan.routes.find((r) => r.stops.length >= 2)!
const other = plan.routes.find((r) => r.engineer_id !== route.engineer_id && r.stops.length)!
const read: string[] = []

vi.mock('../crew/crewApi', () => ({
  crewApi: {
    feed: async () => ({
      unread: 2,
      urgent: 1,
      items: [
        { id: 'm1', kind: 'problem', author: 'crew', engineer_id: other.engineer_id, engineer: 'Другая', time: '12:10', text: 'Не пускает охрана', request_id: null, unread: true },
        { id: 'm2', kind: 'text', author: 'crew', engineer_id: route.engineer_id, engineer: 'Эта', time: '12:00', text: 'Буду через 10 минут', request_id: null, unread: true },
      ],
    }),
    read: async (_r: string, eng: string) => {
      read.push(eng)
      return { ok: true }
    },
    messages: async () => [],
    say: async () => ({}),
  },
}))

const wrap = (node: React.ReactNode) =>
  render(
    <ThemeProvider theme="light">
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider>
    </ThemeProvider>,
  )

beforeEach(() => {
  act(() => {
    useStore.setState({ dataset: DATASET, datasetId: DATASET.id, plan, offline: false, crewView: null, feedOpen: false, search: '' })
  })
})

test('детали бригады сужают список до её маршрута по порядку визитов', async () => {
  wrap(<RequestList />)
  const all = screen.getAllByRole('option').length
  act(() => useStore.getState().openCrew(route.engineer_id))
  // В поле поиска стоит тег бригады: список ищется по её маршруту.
  const tag = screen.getByRole('button', { name: /убрать из поиска/ })
  expect(tag).toBeInTheDocument()
  const ids = screen.getAllByRole('option').map((o) => o.querySelector('s')?.textContent)
  expect(ids).toEqual(route.stops.map((s) => s.request_id))
  expect(ids.length).toBeLessThan(all)
  // Текст рядом с тегом уточняет поиск внутри маршрута.
  fireEvent.change(screen.getByPlaceholderText('в маршруте бригады'), { target: { value: route.stops[1].request_id } })
  expect(screen.getAllByRole('option').map((o) => o.querySelector('s')?.textContent)).toEqual([route.stops[1].request_id])
  fireEvent.change(screen.getByPlaceholderText('в маршруте бригады'), { target: { value: '' } })
  fireEvent.click(tag)
  expect(screen.getAllByRole('option').length).toBe(all)
})

test('детали бригады — карточка с перепиской и действиями', async () => {
  wrap(<CrewCard engineerId={route.engineer_id} embedded />)
  expect(await screen.findByText('Буду через 10 минут')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Написать' })).toBeInTheDocument()
  expect(screen.getByText('Визитов').nextSibling?.textContent).toBe(String(route.stops.length))
})

test('карточка бригады показывает маршрут адресами по порядку визитов', () => {
  wrap(<CrewCard engineerId={route.engineer_id} embedded />)
  const list = screen.getByRole('list', { name: 'Маршрут по адресам' })
  const addresses = Array.from(list.querySelectorAll('.a')).map((node) => node.textContent)
  const byId = new Map(DATASET.requests.map((r) => [r.id, r.address]))
  expect(addresses).toEqual(route.stops.map((s) => byId.get(s.request_id)))
  // Строка маршрута выбирает заявку — её подсветят карта и список.
  fireEvent.click(list.querySelectorAll('button')[1])
  expect(useStore.getState().selectedRequestId).toBe(route.stops[1].request_id)
})

test('лента открывает бригаду и помечает её сообщения прочитанными', async () => {
  wrap(
    <>
      <FeedButton />
      <FeedPanel />
    </>,
  )
  const bell = await screen.findByRole('button', { name: 'Лента от бригад, новых 2' })
  fireEvent.click(bell)
  fireEvent.click(await screen.findByRole('tab', { name: 'Требует ответа' }))
  expect(screen.queryByText('Буду через 10 минут')).toBeNull()
  fireEvent.click(screen.getByText('Не пускает охрана'))
  expect(useStore.getState().crewView).toBe(other.engineer_id)
  expect(useStore.getState().feedOpen).toBe(false)
  await waitFor(() => expect(read).toEqual([other.engineer_id]))
})

test('ручной приоритет хранится в настройках плана', () => {
  const id = DATASET.requests[0].id
  act(() => useStore.getState().setRequestPriority(id, 'urgent'))
  expect(useStore.getState().settings.requests).toEqual({ [id]: { priority: 'urgent' } })
  act(() => useStore.getState().setRequestPriority(id, null))
  expect(useStore.getState().settings.requests).toEqual({})
})
