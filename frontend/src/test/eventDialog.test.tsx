/**
 * Диалог событий: событие не пересчитывает план, а встаёт в пачку. Новая
 * заявка дня уходит событием `new_request` с правилом назначения, «Сохранить
 * и ещё» кладёт в пачку несколько заявок подряд, «клиента нет» берёт время
 * приезда бригады из плана. Тычок по карте даёт такую же заявку без формы.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { ThemeProvider } from '@gravity-ui/uikit'
import EventDialog from '../components/EventDialog'
import { useStore } from '../store'
import { DATASET } from '../fixtures/yugo-vostok'
import { buildPlan } from '../fixtures/planner'
import { dropEvent, windowAfter } from '../lib/drafts'

function setup(kind: 'new_request' | 'no_show') {
  const plan = buildPlan(DATASET, { algorithm: 'baseline', id: 'p-test' })
  const stop = plan.routes.find((route) => route.stops.length)!.stops[0]
  useStore.setState({
    dataset: DATASET,
    plan,
    previousPlan: null,
    view: 'after',
    dialog: kind,
    drafts: [],
    variants: null,
    pickedPoint: { lat: 55.44, lon: 37.77 },
    selectedRequestId: kind === 'no_show' ? stop.request_id : null,
    picking: false,
  })
  render(
    <ThemeProvider theme="light">
      <EventDialog kind={kind} />
    </ThemeProvider>,
  )
  return { stop }
}

test('новая заявка дня встаёт в пачку с правилом «предложить», план не меняется', () => {
  setup('new_request')
  const before = useStore.getState().plan
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  const { drafts, plan, dialog } = useStore.getState()
  expect(drafts).toHaveLength(1)
  expect(plan).toBe(before)
  expect(dialog).toBeNull()
  const event = drafts[0]
  if (event.type !== 'new_request') throw new Error('тип события')
  expect(event.policy).toBe('offer')
  expect(event.request.priority).toBe('normal')
  expect(event.request.lat).toBeCloseTo(55.44)
})

test('«Сохранить и ещё» оставляет диалог открытым и копит заявки', () => {
  setup('new_request')
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить и ещё' }))
  fireEvent.change(screen.getByLabelText('Широта'), { target: { value: '55.5' } })
  fireEvent.change(screen.getByLabelText('Долгота'), { target: { value: '37.6' } })
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить и ещё' }))
  const drafts = useStore.getState().drafts
  expect(drafts).toHaveLength(2)
  expect(new Set(drafts.map((item) => (item.type === 'new_request' ? item.request.id : '')))).toHaveProperty('size', 2)
  expect(screen.getByText(/Сохранено заявок: 2/)).toBeTruthy()
})

test('«клиента нет» ставит время приезда бригады и причину', () => {
  const { stop } = setup('no_show')
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
  const event = useStore.getState().drafts[0]
  if (event.type !== 'no_show') throw new Error('тип события')
  expect(event.request_id).toBe(stop.request_id)
  expect(event.time).toBe(stop.arrive)
  expect(event.note).toBe('absent')
})

test('тычок по карте — заявка в точке, окно через час после звонка', () => {
  const event = dropEvent({ lat: 55.61234, lon: 37.71234 }, '12:40')
  if (event.type !== 'new_request') throw new Error('тип события')
  expect(event.time).toBe('12:40')
  expect(event.request.lat).toBeCloseTo(55.61234)
  expect(windowAfter('12:40')).toEqual({ start: '14:00', end: '17:00' })
  expect(event.request.window_start).toBe('14:00')
})
