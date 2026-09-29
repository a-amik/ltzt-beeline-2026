/**
 * Экран запуска из index.html: знак и «Загружаем данные», пока бандл
 * и первый набор ещё не пришли. Снимается один раз, с короткой растушёвкой.
 */
export function hideBoot(): void {
  const boot = document.getElementById('boot')
  if (!boot || boot.classList.contains('is-done')) return
  boot.classList.add('is-done')
  window.setTimeout(() => boot.remove(), 300)
}
