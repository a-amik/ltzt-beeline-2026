/**
 * Мост между сервером и демо-данными. Правило одно: сначала спрашиваем
 * сервер, и только если он не ответил — считаем на месте и поднимаем
 * признак `offline`, чтобы в углу зажёгся бейдж «демо-данные».
 */

import { api, ApiError } from './api'
import { DATASET } from './fixtures/yugo-vostok'
import { buildPlan, localReplan } from './fixtures/planner'
import { useStore } from './store'
import type {
  Comparison,
  Dataset,
  DatasetSummary,
  Plan,
  PlanEvent,
  ScenarioSpec,
  Settings,
  SettingsForm,
  SimulationResult,
} from './types'

function goOffline(): void {
  if (!useStore.getState().offline) useStore.getState().setOffline(true)
}

const demoSummary: DatasetSummary[] = [
  {
    id: DATASET.id,
    name: DATASET.name,
    date: DATASET.date,
    requests_count: DATASET.requests.length,
    engineers_count: DATASET.engineers.length,
  },
]

export async function loadDatasets(): Promise<DatasetSummary[]> {
  try {
    const list = await api.datasets()
    if (list.length > 0) return list
  } catch {
    goOffline()
  }
  goOffline()
  return demoSummary
}

export async function loadDataset(id: string): Promise<Dataset> {
  try {
    return await api.dataset(id)
  } catch {
    goOffline()
    return DATASET
  }
}

export async function runPlan(
  dataset: Dataset,
  algorithm: 'solver' | 'baseline' = 'solver',
  settings: Settings = useStore.getState().settings,
  rememberLatest = true,
): Promise<Plan> {
  try {
    return await api.plan(dataset.id, algorithm, settings, rememberLatest)
  } catch (error) {
    if (error instanceof ApiError) throw error
    goOffline()
    return buildPlan(dataset, { algorithm, id: `local-${algorithm}` })
  }
}

/** Форма настроек приходит с сервера; без сервера настраивать нечего. */
export async function loadSettingsForm(): Promise<SettingsForm | null> {
  try {
    return await api.settings()
  } catch {
    return null
  }
}

/** Ручная замена или принятое предложение. Отказ приходит словами — его и показываем. */
export async function runAssign(
  plan: Plan,
  requestId: string,
  engineerId: string,
  insertAfter: string | null,
): Promise<Plan> {
  return api.assign(plan.id, requestId, engineerId, insertAfter)
}

export async function runCompare(dataset: Dataset): Promise<Comparison> {
  return api.compare(dataset.id, useStore.getState().settings)
}

export async function runReplan(
  dataset: Dataset,
  plan: Plan,
  event: PlanEvent,
): Promise<Plan> {
  try {
    return await api.replan(plan.id, event)
  } catch (error) {
    if (error instanceof ApiError) throw error
    // Без сервера на месте считаются только три события первой версии.
    if (event.type !== 'urgent' && event.type !== 'cancel' && event.type !== 'engineer_off') throw error
    goOffline()
    return localReplan(dataset, plan, event)
  }
}

export async function runSimulation(spec: ScenarioSpec): Promise<SimulationResult> {
  return api.simulate(spec)
}
