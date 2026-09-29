/**
 * <route-loader> — знак «Маршрута дня» в круге: линия проезжает букву «М»
 * от старта к финишу и обратно, точки в углах загораются по ходу.
 *
 * Один элемент на все случаи: экран запуска (index.html, до загрузки бандла),
 * смена бригады и пересчёт плана в React. Размер — шириной и высотой
 * элемента, по умолчанию 24 px; подпись для экранного диктора — aria-label.
 * Фон круга — переменная --route-loader-bg: в тёмной теме он светлее,
 * чтобы круг не тонул в графитовом фоне. При prefers-reduced-motion знак
 * стоит целым, без движения.
 */
;(() => {
  if (!('customElements' in window) || customElements.get('route-loader')) return

  const Y = '#ffc800'
  const INK = '#13171b'
  // Маршрут буквы: старт внизу слева, два верхних угла, финиш внизу справа.
  const P = [[24, 72], [24, 30], [50, 56], [76, 30], [76, 72]]
  const SEG = P.slice(1).map((p, i) => Math.hypot(p[0] - P[i][0], p[1] - P[i][1]))
  const CUM = SEG.reduce((acc, len) => (acc.push(acc[acc.length - 1] + len), acc), [0])
  const L = CUM[CUM.length - 1]
  const D = 'M' + P.map((p) => p.join(' ')).join('L')
  // Точки маршрута — четыре угла буквы; нижняя вершина — просто поворот.
  const NODES = [0, 1, 3, 4]
  // Один проезд в одну сторону; полный цикл — туда и обратно.
  const LEG = 1800

  const clamp = (x) => Math.max(0, Math.min(1, x))
  const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)
  const still = window.matchMedia('(prefers-reduced-motion: reduce)')

  const nodes = NODES.map(
    (i) =>
      `<g class="n" data-i="${i}"><circle cx="${P[i][0]}" cy="${P[i][1]}" r="11" fill="${Y}"/>` +
      `<circle cx="${P[i][0]}" cy="${P[i][1]}" r="4.6" fill="${INK}"/></g>`,
  ).join('')
  const line = `fill="none" stroke="${Y}" stroke-width="9" stroke-linejoin="round" stroke-linecap="round"`
  const TEMPLATE =
    '<style>:host{display:inline-block;width:24px;height:24px;flex:none;vertical-align:middle}' +
    'svg{display:block;width:100%;height:100%}</style>' +
    `<svg viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="50" fill="var(--route-loader-bg, ${INK})"/>` +
    // Круг теснее квадрата иконки: знак ужат, чтобы кольца не касались края.
    '<g transform="translate(50 51) scale(.86) translate(-50 -51)">' +
    `<path d="${D}" ${line} stroke-opacity=".2"/><path class="run" d="${D}" ${line}/>${nodes}</g></svg>`

  class RouteLoader extends HTMLElement {
    connectedCallback() {
      if (!this.shadowRoot) {
        this.attachShadow({ mode: 'open' }).innerHTML = TEMPLATE
        this.run = this.shadowRoot.querySelector('.run')
        this.nodes = [...this.shadowRoot.querySelectorAll('.n')]
      }
      if (!this.hasAttribute('role')) this.setAttribute('role', 'status')
      if (!this.hasAttribute('aria-label')) this.setAttribute('aria-label', 'Загрузка')
      this.start = performance.now()
      this.tick = (now) => {
        this.frame(((now - this.start) % (2 * LEG)) / (2 * LEG))
        this.raf = requestAnimationFrame(this.tick)
      }
      if (still.matches) this.frame(-1)
      else this.raf = requestAnimationFrame(this.tick)
    }

    disconnectedCallback() {
      cancelAnimationFrame(this.raf)
    }

    /** Кадр цикла: p от 0 до 1; первая половина — туда, вторая — обратно; p < 0 — знак целиком. */
    frame(p) {
      let from = 0
      let to = L
      let front = L
      let back = false
      if (p >= 0) {
        back = p >= 0.5
        const q = (p % 0.5) * 2
        const head = ease(clamp(q / 0.62)) * L
        const tail = ease(clamp((q - 0.42) / 0.58)) * L
        ;[from, to, front] = back ? [L - head, L - tail, L - head] : [tail, head, head]
      }
      const len = Math.max(0, to - from)
      this.run.setAttribute('stroke-dasharray', `${len} ${L + 20}`)
      this.run.setAttribute('stroke-dashoffset', String(-from))
      this.run.setAttribute('opacity', len > 0.01 ? '1' : '0')
      for (const n of this.nodes) {
        const i = Number(n.dataset.i)
        const d = CUM[i]
        const lit = d >= from - 0.5 && d <= to + 0.5 ? 1 : 0
        // Точка вспыхивает, когда до неё доходит голова линии.
        const passed = clamp((back ? d - front : front - d) / 18)
        const s = p < 0 ? 1 : 1 + 0.22 * Math.sin(Math.PI * passed) * lit
        n.setAttribute('opacity', String(p < 0 ? 1 : 0.25 + 0.75 * lit))
        n.setAttribute('transform', `translate(${P[i][0]} ${P[i][1]}) scale(${s}) translate(${-P[i][0]} ${-P[i][1]})`)
      }
    }
  }

  customElements.define('route-loader', RouteLoader)
})()
