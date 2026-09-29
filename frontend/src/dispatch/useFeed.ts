import { useQuery } from '@tanstack/react-query'
import { crewApi } from '../crew/crewApi'
import { useStore } from '../store'

/** Лента от бригад региона: одна на экран, опрос раз в пять секунд. */
export function useFeed() {
  const region = useStore((s) => s.datasetId)
  const offline = useStore((s) => s.offline)
  return useQuery({
    queryKey: ['feed', region],
    queryFn: () => crewApi.feed(region),
    enabled: Boolean(region) && !offline,
    refetchInterval: 5000,
    retry: false,
  })
}

export const KIND_RU: Record<string, string> = {
  sos: 'SOS',
  problem: 'Проблема',
  delay: 'Задерживается',
  call: 'Звонок клиенту',
  text: 'Сообщение',
  report: 'Отчёт',
  flag: 'Контроль',
}
