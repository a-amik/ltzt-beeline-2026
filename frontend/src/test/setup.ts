import '@testing-library/jest-dom/vitest'

// Gravity UI меряет окна и слушает медиазапросы; в jsdom того и другого нет.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) =>
    ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {},
       addListener() {}, removeListener() {}, dispatchEvent: () => false }) as unknown as MediaQueryList) as typeof window.matchMedia
}
if (!window.ResizeObserver) {
  window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
}
