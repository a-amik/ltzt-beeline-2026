/**
 * Клавиши экрана диспетчера и открытие палитры общего поиска
 * (`components/search/CommandPalette`). Вне поля ввода: 1 / 2 / 3 — Заявки,
 * Инженеры, Нагрузка; / — поиск колонки; ↑ ↓ — по строкам списка; Esc — снять
 * выбор или вернуться к заявкам; ? и ⌘K (Ctrl+K) — палитра.
 */

import { useEffect } from 'react'
import { create } from 'zustand'
import { activePlan, useStore } from '../store'
import { closeOverlays } from '../components/Rail'

export const usePalette = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
}))

type Section = 'plan' | 'engineers' | 'deficit'

/** Перейти в раздел колонки — как нажатие в колонке разделов, но без сворачивания. */
export function goSection(key: Section) {
  const s = useStore.getState()
  if (key === 'deficit') {
    if (!activePlan(s)) return
    closeOverlays()
    s.setDemo('deficit')
    return
  }
  closeOverlays()
  s.setPanelOpen(key === 'engineers')
  s.setSideOpen(true)
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const PALETTE_KEY = isMac ? '⌘K' : 'Ctrl K'

const typing = (target: EventTarget | null) => {
  const el = target as HTMLElement | null
  return Boolean(el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable))
}

/** Сдвиг выбора по строкам списка в колонке: заявки, инженеры, районы. */
function stepList(delta: 1 | -1) {
  const box = document.querySelector('.b-col.l .b-cb')
  if (!box) return false
  const rows = [...box.querySelectorAll<HTMLElement>('[role="option"], button.eng')]
  if (!rows.length) return false
  const at = rows.findIndex((row) => row.getAttribute('aria-selected') === 'true' || row.getAttribute('aria-pressed') === 'true')
  const next = rows[at < 0 ? (delta > 0 ? 0 : rows.length - 1) : Math.min(rows.length - 1, Math.max(0, at + delta))]
  if (!next || rows[at] === next) return true
  next.click()
  next.scrollIntoView({ block: 'nearest' })
  return true
}

/** Клавиши экрана диспетчера. Вешается один раз, в `App`. */
export function useHotkeys() {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      const palette = usePalette.getState()
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        palette.setOpen(!palette.open)
        return
      }
      if (palette.open || event.metaKey || event.ctrlKey || event.altKey) return
      const target = event.target as HTMLElement | null
      // Из поля поиска колонки стрелка вниз уводит в список.
      if (event.key === 'ArrowDown' && target?.hasAttribute('data-col-search')) {
        if (stepList(1)) {
          event.preventDefault()
          target.blur()
        }
        return
      }
      if (typing(target)) return
      // Поверх открыто окно раздела (имитация, отчёты, правила) — клавиши его.
      const s = useStore.getState()
      const overlay = Boolean((s.demo && s.demo !== 'deficit') || s.simOpen || s.compareOpen || s.settingsOpen || s.feedOpen || s.dialog)
      if (event.key === '?') {
        event.preventDefault()
        palette.setOpen(true)
        return
      }
      if (overlay) return
      if (event.key === '1' || event.key === '2' || event.key === '3') {
        event.preventDefault()
        goSection(event.key === '1' ? 'plan' : event.key === '2' ? 'engineers' : 'deficit')
      } else if (event.key === '/') {
        const field = document.querySelector<HTMLInputElement>('.b-col.l [data-col-search]')
        if (field) {
          event.preventDefault()
          field.focus()
          field.select()
        }
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (stepList(event.key === 'ArrowDown' ? 1 : -1)) event.preventDefault()
      } else if (event.key === 'Escape') {
        if (s.crewView) s.openCrew(null)
        else if (s.selectedRequestId || s.selectedEngineerId) {
          s.selectRequest(null)
          s.selectEngineer(null)
          s.focusAll()
        } else if (s.demo === 'deficit') goSection('plan')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
