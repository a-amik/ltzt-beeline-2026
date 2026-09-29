/**
 * Граница ошибок вокруг карты. MapLibre требует WebGL2 и бросает исключение,
 * если браузер его не даёт: отключённое ускорение, удалённый рабочий стол,
 * фоновая вкладка. Без границы падал бы весь экран; с ней пропадает одна
 * карта, а заявки, ленты бригад, метрики и настройки работают.
 */

import { Component, type ReactNode } from 'react'

interface State {
  failed: boolean
  message: string
}

export default class MapBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false, message: '' }

  static getDerivedStateFromError(error: unknown): State {
    const text = error instanceof Error ? error.message : String(error)
    return { failed: true, message: text }
  }

  render() {
    if (!this.state.failed) return this.props.children
    const webgl = /webgl/i.test(this.state.message)
    return (
      <div className="b-map-fail">
        <b>Карта не отображается</b>
        <span>
          {webgl
            ? 'Браузеру нужна поддержка WebGL2: включите аппаратное ускорение или откройте в другом браузере. План, заявки и ленты бригад работают и без карты.'
            : 'Карта не загрузилась. План, заявки и ленты бригад работают и без неё.'}
        </span>
      </div>
    )
  }
}
