/**
 * Часы показа: рабочий день 10:00—22:00 за выбранное число секунд.
 * Время живёт в минутах дня, кадр считается по метке `requestAnimationFrame`,
 * а не «на кадр»: на экране в 120 Гц день идёт с той же скоростью.
 * При «меньше движения» часы не заводятся сами — только ползунком.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { DAY_END, DAY_START } from '../../lib/time'

export interface Clock {
  time: number
  playing: boolean
  seconds: number
  play: () => void
  pause: () => void
  toggle: () => void
  seek: (minute: number) => void
  restart: () => void
  setSeconds: (seconds: number) => void
}

export function useClock(initialSeconds = 60, autoplay = true): Clock {
  const reduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const [time, setTime] = useState(DAY_START)
  const [playing, setPlaying] = useState(autoplay && !reduced)
  const [seconds, setSeconds] = useState(initialSeconds)
  const timeRef = useRef(DAY_START)
  const last = useRef<number | null>(null)

  useEffect(() => {
    if (!playing) {
      last.current = null
      return
    }
    let frame = 0
    const step = (stamp: number) => {
      if (last.current !== null) {
        const perMs = (DAY_END - DAY_START) / (seconds * 1000)
        const next = Math.min(DAY_END, timeRef.current + (stamp - last.current) * perMs)
        timeRef.current = next
        setTime(next)
        if (next >= DAY_END) {
          setPlaying(false)
          return
        }
      }
      last.current = stamp
      frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [playing, seconds])

  const seek = useCallback((minute: number) => {
    timeRef.current = Math.max(DAY_START, Math.min(DAY_END, minute))
    setTime(timeRef.current)
  }, [])

  return {
    time,
    playing,
    seconds,
    play: () => {
      if (timeRef.current >= DAY_END) seek(DAY_START)
      setPlaying(true)
    },
    pause: () => setPlaying(false),
    toggle: () => {
      if (!playing && timeRef.current >= DAY_END) seek(DAY_START)
      setPlaying(!playing)
    },
    seek,
    restart: () => {
      seek(DAY_START)
      setPlaying(true)
    },
    setSeconds,
  }
}

export function clockText(minute: number): string {
  const m = Math.floor(minute)
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}
