/*
 * Кэш карты: тайлы, шрифты подписей и значки OpenFreeMap живут в браузере.
 * Карта Москвы прогревается заранее (`lib/mapCache.ts`), и после первого
 * захода подложка открывается сразу — даже при плохой или рвущейся связи.
 *
 * Трогает только запросы к `/tiles/` своего сервера — за этим путём nginx
 * стенда держит кэш OpenFreeMap (в разработке путь проксирует Vite); всё
 * остальное — приложение, API — идёт мимо, как без воркера. Тайлы, шрифты
 * и значки — сначала из кэша: у тайлов в адресе версия выгрузки, и под одним
 * адресом они не меняются. Стиль и описание источника — сначала из сети
 * (там адрес свежей выгрузки), из кэша — когда сети нет.
 */

const CACHE = 'bee-map-v2'
const PATH = '/tiles/'

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith('bee-map-') && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

const lasting = (url) =>
  url.pathname.endsWith('.pbf') || url.pathname.includes('/natural_earth/') || url.pathname.includes('/fonts/') || url.pathname.includes('/sprites/')

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || !url.pathname.startsWith(PATH)) return
  event.respondWith(lasting(url) ? fromCache(request) : fromNetwork(request))
})

async function fromCache(request) {
  const cache = await caches.open(CACHE)
  const hit = await cache.match(request, { ignoreVary: true })
  if (hit) return hit
  const response = await fetch(request)
  if (response.ok) cache.put(request, response.clone())
  return response
}

async function fromNetwork(request) {
  const cache = await caches.open(CACHE)
  try {
    const response = await fetch(request)
    if (response.ok) cache.put(request, response.clone())
    return response
  } catch (error) {
    const hit = await cache.match(request, { ignoreVary: true })
    if (hit) return hit
    throw error
  }
}
