/**
 * Светлая и тёмная тема — два сегмента со значком. Один вид везде, где
 * тема стоит на виду: в шапке настроек и в шапке отчётов.
 */

import { SegmentedRadioGroup } from '@gravity-ui/uikit'
import { IconMoon, IconSun } from '../lib/icons'
import { useStore } from '../store'

export default function ThemeSwitch() {
  const theme = useStore((s) => s.theme)
  const setTheme = useStore((s) => s.setTheme)
  return (
    <SegmentedRadioGroup
      size="m"
      value={theme}
      onUpdate={(next) => setTheme(next as typeof theme)}
      aria-label="Тема"
      options={[
        { value: 'light', content: <span className="b-st-theme"><IconSun />Светлая</span> },
        { value: 'dark', content: <span className="b-st-theme"><IconMoon />Тёмная</span> },
      ]}
    />
  )
}
