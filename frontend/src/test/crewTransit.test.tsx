/**
 * «Как доехать»: путь строится только по нажатию и показывает линии,
 * ожидание, пересадку и ближайшие отправления; отказ 2ГИС — словами.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CrewTransit from '../crew/CrewTransit'
import type { TransitTrip } from '../crew/transitTypes'

const trip: TransitTrip = {
  request_id: 'r1', depart: '10:00', plan_arrive: '10:13', date: '2026-09-21', origin: 'офис', target: 'Домодедово', note: null,
  options: [{
    total_min: 46, arrive: '10:46', transfers: 1, walk: 'пешком 12 мин', departures: ['10:21', '10:36'],
    legs: [
      { kind: 'walk', minutes: 4, wait_min: 0, place: '', vehicle: '', lines: [] },
      { kind: 'ride', minutes: 5, wait_min: 2, place: 'Мебельная фабрика', vehicle: 'автобус', lines: ['891'] },
      { kind: 'transfer', minutes: 6, wait_min: 0, place: 'Бирюлёво-Тов.', vehicle: '', lines: [] },
      { kind: 'ride', minutes: 23, wait_min: 1, place: 'Бирюлёво-Тов.', vehicle: 'электричка', lines: ['Павелецкий вокзал — Домодедово'] },
    ],
  }],
}

const asked: string[] = []
let answer: TransitTrip = trip

vi.mock('../api', () => ({
  api: {
    crewTransit: (_plan: string, _eng: string, request: string) => {
      asked.push(request)
      return Promise.resolve(answer)
    },
  },
}))

function show() {
  const client = new QueryClient()
  render(
    <QueryClientProvider client={client}>
      <CrewTransit planId="p" engineerId="e1" requestId="r1" />
    </QueryClientProvider>,
  )
}

test('путь спрашивается по нажатию и читается по участкам', async () => {
  asked.length = 0
  answer = trip
  show()
  expect(asked).toEqual([])
  fireEvent.click(screen.getByText('Как доехать на транспорте'))
  await waitFor(() => expect(screen.getByText('Автобус 891')).toBeTruthy())
  expect(asked).toEqual(['r1'])
  expect(screen.getByText(/ждать 2 мин/)).toBeTruthy()
  expect(screen.getByText('Электричка Павелецкий вокзал — Домодедово')).toBeTruthy()
  expect(screen.getByText('Пересадка, 6 мин')).toBeTruthy()
  expect(screen.getByText('10:21')).toBeTruthy()
  expect(screen.getByText(/1 пересадка/)).toBeTruthy()
  expect(screen.getByText(/выезд 10:00, из офиса/)).toBeTruthy()
  expect(screen.getByText(/понедельник/)).toBeTruthy()
  expect(screen.getByText(/позже на 33 мин/)).toBeTruthy()
})

test('отказ 2ГИС показывается словами', async () => {
  answer = { ...trip, options: [], note: 'Точки дальше 50 км: демо-ключ 2ГИС такой путь не строит' }
  show()
  fireEvent.click(screen.getByText('Как доехать на транспорте'))
  await waitFor(() => expect(screen.getByText(/дальше 50 км/)).toBeTruthy())
})
