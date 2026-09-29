/**
 * Знак BeeGPT — помощника диспетчера (настройки) и бригады (переписка по смене).
 * Облачко реплики в жёлтом билайна с двумя тёмными полосами, как у пчелы
 * и знака бренда, и искрой в углу — примета подсказки; тёмный контур держит
 * знак и на жёлтой подсветке активной вкладки бригады.
 *
 * «Думает» (`busy`) — «Искра + строки», решение команды 29.09.2026 из трёх
 * вариантов движения: полосы пишутся слева направо, как строки ответа;
 * дописана вторая — вспыхивает искра, точкой в конце фразы, от неё расходится
 * свет; строки стираются, и круг заново. Ответ приходит в миг вспышки
 * (`ANSWER_AT`). Движение — функция доли круга, крутится по кадрам; при
 * `prefers-reduced-motion` знак стоит в обычном виде.
 */

import { useEffect, useId, useRef } from 'react'

const BUBBLE =
  'M7 2.5h10a5 5 0 0 1 5 5v5a5 5 0 0 1-5 5h-5.4l-4.7 3.7a.6.6 0 0 1-.97-.47V17.4A5 5 0 0 1 2 12.5v-5a5 5 0 0 1 5-5z'
// Искра вокруг своего центра (17; 5.4) — её вращают и растят на месте.
const SPARK = 'M0 -1.5l.6 .9 .9 .6 -.9 .6 -.6 .9 -.6 -.9 -.9 -.6 .9 -.6z'
const SX = 17
const SY = 5.4
const YELLOW = '#FFC800'
const INK = '#1f2429'

/** Круг движения, мс. */
export const PERIOD = 1600
/** Доля круга, когда вспыхивает искра: обе строки дописаны — тут и приходит ответ. */
const FLASH = 0.52
/** Сколько BeeGPT «думает»: круг и ещё до вспышки — ответ совпадает с ней. */
export const ANSWER_AT = Math.round(PERIOD * (1 + FLASH))

const clamp = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x)
const span = (u: number, a: number, b: number) => clamp((u - a) / (b - a))
const outC = (x: number) => 1 - Math.pow(1 - x, 3)
const inOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)

interface Frame { a: number; b1: number; b2: number; sk: number; sr: number; gr: number; glow: number }
const REST: Frame = { a: 0, b1: 1, b2: 1, sk: 1, sr: 0, gr: 1.5, glow: 0 }

/** Кадр в доле круга u ∈ [0, 1). */
function frame(u: number): Frame {
  const erase = inOut(span(u, 0.8, 0.97))
  const flare = span(u, FLASH - 0.1, FLASH + 0.12)
  const fade = span(u, FLASH + 0.12, FLASH + 0.36)
  const g = span(u, FLASH - 0.06, FLASH + 0.34)
  return {
    b1: u >= 0.97 ? 0 : outC(span(u, 0.02, 0.26)),
    b2: u >= 0.97 ? 0 : outC(span(u, 0.16, 0.42)),
    a: u >= 0.97 ? 0 : erase,
    sk: 1 + 0.7 * outC(flare) - 0.7 * inOut(fade),
    sr: 90 * inOut(span(u, FLASH - 0.1, FLASH + 0.36)),
    gr: 1.5 + 4 * outC(g),
    glow: g > 0 && g < 1 ? 0.55 * (1 - g) : 0,
  }
}

export default function BeeMark({ size = 28, busy = false, className }: { size?: number; busy?: boolean; className?: string }) {
  const clip = `bee-${useId().replace(/:/g, '')}`
  const s1 = useRef<SVGRectElement>(null)
  const s2 = useRef<SVGRectElement>(null)
  const spark = useRef<SVGPathElement>(null)
  const glow = useRef<SVGCircleElement>(null)

  useEffect(() => {
    const paint = (f: Frame) => {
      const bar = (el: SVGRectElement | null, b: number) => {
        el?.setAttribute('x', (2 + 20 * f.a).toFixed(3))
        el?.setAttribute('width', Math.max(0, 20 * (b - f.a)).toFixed(3))
      }
      bar(s1.current, f.b1)
      bar(s2.current, f.b2)
      spark.current?.setAttribute('transform', `rotate(${f.sr.toFixed(2)}) scale(${f.sk.toFixed(3)})`)
      glow.current?.setAttribute('r', f.gr.toFixed(3))
      glow.current?.setAttribute('opacity', f.glow.toFixed(3))
    }
    const still = Boolean(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
    if (!busy || still) {
      paint(REST)
      return
    }
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      paint(frame(((now - start) % PERIOD) / PERIOD))
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      paint(REST)
    }
  }, [busy])

  return (
    <svg className={`b-bee${className ? ` ${className}` : ''}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ overflow: 'visible' }}>
      <defs>
        <clipPath id={clip}>
          <path d={BUBBLE} />
        </clipPath>
      </defs>
      <path d={BUBBLE} fill={YELLOW} />
      <g clipPath={`url(#${clip})`} fill={INK}>
        <rect ref={s1} x="2" y="8.6" width="20" height="1.9" />
        <rect ref={s2} x="2" y="12.3" width="20" height="1.9" />
      </g>
      {/* Тёмный контур: знак читается и на жёлтой подсветке активной вкладки бригады. */}
      <path d={BUBBLE} fill="none" stroke={INK} strokeWidth="1.1" strokeLinejoin="round" />
      <circle ref={glow} cx={SX} cy={SY} r="1.5" fill={YELLOW} opacity="0" />
      <g transform={`translate(${SX} ${SY})`}>
        <path ref={spark} d={SPARK} fill={INK} />
      </g>
    </svg>
  )
}
