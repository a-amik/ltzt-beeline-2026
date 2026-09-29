import type { CSSProperties } from 'react'

/**
 * Лоадер «Маршрута дня»: знак в круге, линия проезжает букву «М» туда
 * и обратно. Сам элемент — `<route-loader>` из `public/route-loader.js`:
 * он же стоит на экране запуска, пока бандл ещё грузится.
 */
export function RouteLoader({ size = 24, label = 'Загрузка', style }: { size?: number; label?: string; style?: CSSProperties }) {
  return <route-loader aria-label={label} style={{ width: size, height: size, ...style }} />
}

declare module 'react' {
  namespace JSX {
    interface IntrinsicElements {
      'route-loader': DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement>
    }
  }
}
