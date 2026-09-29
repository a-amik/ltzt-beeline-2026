/**
 * Значок ⓘ с пояснением по нажатию: на экране бригады стоит только то,
 * что нужно для действия, а легенда и оговорки живут здесь. Касание
 * мимо или Escape закрывают подсказку.
 */

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { IconInfo } from '../lib/icons'

export default function InfoTip({ label, className, children }: { label: string; className?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const away = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false)
    }
    const key = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', key)
    }
  }, [open])
  return (
    <div ref={root} className={`b-tip${open ? ' open' : ''}${className ? ` ${className}` : ''}`}>
      <button type="button" className="b-tip-btn" aria-label={label} aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconInfo />
      </button>
      {open ? (
        <div className="b-tip-pop" role="note">
          {children}
        </div>
      ) : null}
    </div>
  )
}
