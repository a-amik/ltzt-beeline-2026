/**
 * Карта Москвы заранее: воркер `public/map-cache.js` держит тайлы, шрифты
 * и значки OpenFreeMap в браузере, а здесь, после первой отрисовки, фоном
 * выкачивается регион целиком. Дальше подложка открывается из кэша — без
 * ожидания сети и при рвущейся связи; следующий заход ничего не качает.
 *
 * Что прогревается: область от Каширы и Ступина до севера Москвы — зумы
 * 5—11, на которых видны все участки разом; сама Москва — ещё 12—13, на
 * которых диспетчер смотрит маршрут. Около 600 тайлов, по 4 запроса разом,
 * чтобы не отнимать канал у данных плана. При «экономии трафика» не качается.
 */

import { STYLE_URL, localTiles } from './mapStyle'

type Box = { west: number; south: number; east: number; north: number; zooms: [number, number] }

const WARM: Box[] = [
  { west: 37.1, south: 54.75, east: 38.4, north: 56.05, zooms: [5, 11] },
  { west: 37.3, south: 55.55, east: 37.95, north: 55.93, zooms: [12, 13] },
]
const PARALLEL = 4
const DONE_KEY = 'b-map-warm'

function tileRange(box: Box, z: number) {
  const n = 2 ** z
  const x = (lon: number) => Math.floor(((lon + 180) / 360) * n)
  const y = (lat: number) => {
    const r = (lat * Math.PI) / 180
    return Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n)
  }
  return { x0: x(box.west), x1: x(box.east), y0: y(box.north), y1: y(box.south) }
}

/** Адреса тайлов, шрифтов подписей и значков обоих стилей — светлого и тёмного. */
async function assets(): Promise<{ key: string; urls: string[] }> {
  const urls = new Set<string>()
  let template = ''
  for (const styleUrl of Object.values(STYLE_URL)) {
    const style = await (await fetch(styleUrl)).json()
    urls.add(styleUrl)
    const source = Object.values(style.sources ?? {}).find((s: unknown) => (s as { type?: string }).type === 'vector') as
      | { url?: string; tiles?: string[] }
      | undefined
    // Стиль называет OpenFreeMap по полному адресу — прогреваем тот же путь на своём сервере.
    if (!template && source) {
      if (source.tiles?.[0]) template = localTiles(source.tiles[0])
      else if (source.url) {
        urls.add(localTiles(source.url))
        template = localTiles((await (await fetch(localTiles(source.url))).json()).tiles?.[0] ?? '')
      }
    }
    const sprites = Array.isArray(style.sprite) ? style.sprite.map((s: { url: string }) => s.url) : [style.sprite]
    for (const sprite of sprites.filter(Boolean)) {
      for (const suffix of ['.json', '.png', '@2x.json', '@2x.png']) urls.add(localTiles(`${sprite}${suffix}`))
    }
    const fonts = new Set<string>()
    for (const layer of style.layers ?? []) {
      const font = layer.layout?.['text-font']
      if (Array.isArray(font) && font.every((f: unknown) => typeof f === 'string')) fonts.add(font.join(','))
    }
    // Латиница, кириллица и знаки препинания — диапазоны, из которых состоят подписи Москвы.
    for (const stack of fonts) {
      for (const range of ['0-255', '1024-1279', '8192-8447']) {
        urls.add(localTiles(String(style.glyphs).replace('{fontstack}', encodeURIComponent(stack)).replace('{range}', range)))
      }
    }
  }
  if (template) {
    for (const box of WARM) {
      for (let z = box.zooms[0]; z <= box.zooms[1]; z++) {
        const { x0, x1, y0, y1 } = tileRange(box, z)
        for (let x = x0; x <= x1; x++) {
          for (let y = y0; y <= y1; y++) urls.add(template.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(y)))
        }
      }
    }
  }
  return { key: template, urls: [...urls] }
}

async function warm(): Promise<void> {
  const { key, urls } = await assets()
  if (!key) return
  try {
    if (localStorage.getItem(DONE_KEY) === key) return
  } catch {
    // хранилище недоступно — прогреем ещё раз, кэш всё равно отдаст готовое
  }
  let next = 0
  const worker = async () => {
    while (next < urls.length) {
      const url = urls[next++]
      try {
        await fetch(url)
      } catch {
        // сеть мигнула — тайл докачается, когда карта его попросит
      }
    }
  }
  await Promise.all(Array.from({ length: PARALLEL }, worker))
  try {
    localStorage.setItem(DONE_KEY, key)
  } catch {
    // не запомнили — в следующий раз прогрев пройдёт по кэшу быстро
  }
}

/** Завести воркер кэша карты и прогреть Москву фоном. Без поддержки воркеров — ничего не делает. */
export function startMapCache(): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  const saveData = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData
  navigator.serviceWorker
    .register('/map-cache.js')
    .then(() => navigator.serviceWorker.ready)
    .then(
      () =>
        new Promise<void>((resolve) => {
          // Прогрев — через воркер: пока он не взял страницу под себя, запросы мимо кэша.
          if (navigator.serviceWorker.controller) resolve()
          else navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), { once: true })
        }),
    )
    .then(() => (saveData ? undefined : new Promise((r) => window.setTimeout(r, 3000)).then(warm)))
    .catch(() => undefined)
}
