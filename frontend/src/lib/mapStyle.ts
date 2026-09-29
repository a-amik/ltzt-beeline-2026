/** Стиль подложки и рамка карты: одни на рабочую карту и на карты показа. */

import type { RequestParameters } from 'maplibre-gl'

import type { Coord } from '../types'

/**
 * Подложка — OpenFreeMap, но браузер ходит за ней не к нему, а на свой сервер:
 * `/tiles/` отдаёт nginx стенда из своего кэша (Москва прогрета заранее,
 * к OpenFreeMap он идёт только за тем, чего в кэше нет). В разработке тот же
 * путь проксирует Vite. У карты и приложения один домен: сеть, которая пускает
 * на стенд, пускает и карту, — у тестировщика за корпоративным фильтром
 * подложка не открывалась, пока шла напрямую с tiles.openfreemap.org.
 */
export const TILES_ORIGIN = 'https://tiles.openfreemap.org'
export const TILES_PATH = '/tiles'

/** Адрес OpenFreeMap → тот же путь на своём сервере; чужие адреса не трогаются. */
export function localTiles(url: string): string {
  return url.startsWith(TILES_ORIGIN) ? `${window.location.origin}${TILES_PATH}${url.slice(TILES_ORIGIN.length)}` : url
}

/** Стиль и его описание источника называют OpenFreeMap по полному адресу — сюда его и заворачиваем. */
export function tilesRequest(url: string): RequestParameters | undefined {
  const local = localTiles(url)
  return local === url ? undefined : { url: local }
}

export const STYLE_URL = {
  light: `${TILES_PATH}/styles/liberty`,
  dark: `${TILES_PATH}/styles/dark`,
} as const

/**
 * Москва с областью и запасом. Без границы карту отдаляли до глобуса
 * и вернуться к заявкам можно было только перезагрузкой страницы.
 */
export const MAX_BOUNDS: [Coord, Coord] = [
  [35.5, 54.2],
  [39.5, 56.9],
]

/**
 * Подпись источников карты — свёрнутой в «ⓘ» с самого начала. MapLibre в компактном
 * виде сперва показывает её развёрнутой и сворачивает только от перетаскивания карты;
 * здесь то же сворачивание, но сразу после загрузки. Нажатие на «ⓘ» раскрывает
 * «OpenFreeMap © OpenMapTiles Data from OpenStreetMap».
 */
export function collapseAttribution(map: { getContainer: () => HTMLElement; once: (event: string, fn: () => void) => unknown }): void {
  const run = () => map.getContainer().querySelector('.maplibregl-ctrl-attrib.maplibregl-compact-show')?.classList.remove('maplibregl-compact-show')
  map.once('load', run)
  map.once('idle', run)
}
