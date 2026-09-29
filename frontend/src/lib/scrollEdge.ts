/**
 * Строка с прокруткой вбок и скрытой полосой сама не говорит, что за краем
 * что-то есть. Хук ставит на контейнер `data-more="left|right|both"`, пока
 * есть куда листать, — а стиль по этому признаку затухает край к фону.
 */

import { useEffect, type RefObject } from 'react'

export function useScrollEdge(ref: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const mark = () => {
      const left = node.scrollLeft > 1
      const right = node.scrollLeft + node.clientWidth < node.scrollWidth - 1
      const more = left && right ? 'both' : left ? 'left' : right ? 'right' : ''
      if (more) node.dataset.more = more
      else delete node.dataset.more
    }
    mark()
    const observer = new ResizeObserver(mark)
    observer.observe(node)
    for (const child of Array.from(node.children)) observer.observe(child)
    node.addEventListener('scroll', mark, { passive: true })
    return () => {
      observer.disconnect()
      node.removeEventListener('scroll', mark)
    }
  }, [ref])
}
