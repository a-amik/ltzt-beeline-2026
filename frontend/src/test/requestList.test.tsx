/**
 * Список заявок: перенесённая на завтра заявка стоит в своей группе
 * с причиной, а не среди «не назначены».
 */

import { render, screen } from '@testing-library/react'
import { ThemeProvider } from '@gravity-ui/uikit'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RequestList from '../components/RequestList'
import { useStore } from '../store'
import { DATASET } from '../fixtures/yugo-vostok'
import { buildPlan } from '../fixtures/planner'

test('заявка на завтра стоит в группе «На следующий день» с причиной', () => {
  const plan = buildPlan(DATASET, { algorithm: 'baseline', id: 'p-test' })
  const fresh = { ...DATASET.requests[0], id: 'n-777', address: 'Каширское шоссе, 1' }
  plan.history = [{ id: 'e1', type: 'new_request', time: '12:00', request: fresh, policy: 'offer' }]
  plan.deferred = [{ request_id: 'n-777', reason: 'Сегодня взять некому: заявка переносится на следующий день', since: '12:00' }]
  useStore.setState({ dataset: DATASET, plan, previousPlan: null, view: 'after', search: '', planning: false })
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ThemeProvider theme="light">
        <RequestList />
      </ThemeProvider>
    </QueryClientProvider>,
  )
  expect(screen.getByText('На следующий день')).toBeInTheDocument()
  expect(screen.getByText(/заявка переносится на следующий день/)).toBeInTheDocument()
  expect(screen.getByText('Каширское шоссе, 1')).toBeInTheDocument()
})
