/** Выборки из плана: кто где, что не назначено, что изменилось и что заморожено. */

import type { Dataset, Deferred, Plan, RequestItem, Route, Stop, Unassigned } from '../types'

export interface Assignment {
  engineerId: string
  route: Route
  stop: Stop
}

export function assignmentIndex(plan: Plan | null): Map<string, Assignment> {
  const out = new Map<string, Assignment>()
  if (!plan) return out
  for (const route of plan.routes) {
    for (const stop of route.stops) {
      out.set(stop.request_id, { engineerId: route.engineer_id, route, stop })
    }
  }
  return out
}

export function unassignedIndex(plan: Plan | null): Map<string, Unassigned> {
  return new Map((plan?.unassigned ?? []).map((item) => [item.request_id, item]))
}

/** Заявки, которых событие коснулось. */
export function changedIds(plan: Plan | null): Set<string> {
  return new Set((plan?.diff?.changed_requests ?? []).map((item) => item.request_id))
}

/** Визиты, начатые до события: их не трогали. */
export function frozenIds(plan: Plan | null): Set<string> {
  return new Set(plan?.diff?.frozen_requests ?? [])
}

export function changedRoutes(plan: Plan | null): Set<string> {
  return new Set(plan?.diff?.changed_routes ?? [])
}

/** Заявки, которыми план живёт: набор плюс пришедшие событиями дня. */
export function knownRequests(dataset: Dataset | null, plan: Plan | null): RequestItem[] {
  const list = [...(dataset?.requests ?? [])]
  const known = new Set(list.map((item) => item.id))
  const events = [...(plan?.history ?? []), ...(plan?.diff ? [plan.diff.event] : [])]
  for (const event of events) {
    if ((event.type === 'urgent' || event.type === 'new_request') && !known.has(event.request.id)) {
      known.add(event.request.id)
      list.unshift(event.request)
    }
  }
  return list
}

/** Заявки, явно перенесённые на завтра. */
export function deferredIndex(plan: Plan | null): Map<string, Deferred> {
  return new Map((plan?.deferred ?? []).map((item) => [item.request_id, item]))
}
