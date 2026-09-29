/**
 * Режим стенда: гость на обезличенном наборе, команда — на данных задания
 * после входа, разработка — без входа вовсе (`access.py` на сервере).
 * Смена режима — перезагрузка страницы: данные отдаёт другой экземпляр сервера.
 */

import { useQuery } from '@tanstack/react-query'
import { API_URL } from '../api'

export type AccessMode = 'guest' | 'real' | 'local'

async function send(path: string, body?: unknown): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    signal: AbortSignal.timeout(8000),
  })
}

export function useAccessMode(): AccessMode | undefined {
  return useQuery({
    queryKey: ['auth-me'],
    queryFn: async () => ((await (await send('/auth/me')).json()) as { mode: AccessMode }).mode,
    staleTime: Infinity,
  }).data
}

/** Вход: `null` — пустил (страница уже перезагружается), иначе текст ошибки. */
export async function login(name: string, password: string): Promise<string | null> {
  try {
    const resp = await send('/auth/login', { login: name, password })
    if (resp.ok) {
      window.location.reload()
      return null
    }
    return resp.status === 401 ? 'Неверный логин или пароль' : 'Сервер не ответил, попробуйте ещё раз'
  } catch {
    return 'Сервер не ответил, попробуйте ещё раз'
  }
}

export async function logout(): Promise<void> {
  try {
    await send('/auth/logout', {})
  } finally {
    window.location.reload()
  }
}
