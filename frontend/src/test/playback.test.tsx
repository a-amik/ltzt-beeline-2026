/**
 * Движок воспроизведения дня: бригада к минуте t на месте, счётчики растут
 * монотонно, к концу дня выполнено всё назначенное.
 */

import { DATASET } from '../fixtures/yugo-vostok'
import { buildPlan } from '../fixtures/planner'
import { buildDay, crewAt, statsAt, stopState } from '../lib/playback'
import { DAY_END, DAY_START } from '../lib/time'

const plan = buildPlan(DATASET, { algorithm: 'baseline', id: 'p-test' })
const scene = buildDay(DATASET, plan, ['#111111', '#222222'])

test('сцена собирает все визиты и бригады плана', () => {
  const stops = plan.routes.reduce((n, r) => n + r.stops.length, 0)
  expect(scene.stops.length).toBe(stops)
  expect(scene.tracks.length).toBe(plan.routes.length)
  expect(scene.bounds).not.toBeNull()
})

test('счётчики растут и к концу дня выполнено всё назначенное', () => {
  let prev = statsAt(scene, DAY_START)
  expect(prev.done).toBe(0)
  for (let t = DAY_START + 30; t <= DAY_END; t += 30) {
    const now = statsAt(scene, t)
    expect(now.done).toBeGreaterThanOrEqual(prev.done)
    expect(now.value).toBeGreaterThanOrEqual(prev.value)
    expect(now.km).toBeGreaterThanOrEqual(prev.km - 1e-6)
    prev = now
  }
  expect(prev.done).toBe(scene.stops.length)
})

test('во время работы бригада стоит на адресе заявки и визит «в работе»', () => {
  const stop = scene.stops[0]
  const track = scene.tracks.find((tr) => tr.engineerId === stop.engineerId)!
  const mid = (stop.start + stop.end) / 2
  const at = crewAt(track, mid)
  expect(at.state).toBe('work')
  expect(at.point).toEqual(stop.point)
  expect(stopState(stop, mid)).toBe('working')
  expect(stopState(stop, stop.end + 1)).toMatch(/done|late/)
})
