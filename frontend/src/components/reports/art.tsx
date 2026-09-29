/** Иллюстрации к страницам отчётов в двух темах. */

import { useStore } from '../../store'
import solution from '../../assets/reports/solution.webp'
import solutionLight from '../../assets/reports/solution-light.webp'
import design from '../../assets/reports/design.webp'
import designLight from '../../assets/reports/design-light.webp'
import models from '../../assets/reports/models.webp'
import modelsLight from '../../assets/reports/models-light.webp'
import method from '../../assets/reports/method.webp'
import methodLight from '../../assets/reports/method-light.webp'
import settings from '../../assets/reports/settings.webp'
import settingsLight from '../../assets/reports/settings-light.webp'
import ops from '../../assets/reports/ops.webp'
import opsLight from '../../assets/reports/ops-light.webp'

function ReportArt({ dark, light }: { dark: string; light: string }) {
  const theme = useStore((state) => state.theme)
  return <img src={theme === 'dark' ? dark : light} alt="" decoding="async" />
}

export const ArtSolution = () => <ReportArt dark={solution} light={solutionLight} />
export const ArtDesign = () => <ReportArt dark={design} light={designLight} />
export const ArtModels = () => <ReportArt dark={models} light={modelsLight} />
export const ArtMethod = () => <ReportArt dark={method} light={methodLight} />
export const ArtSettings = () => <ReportArt dark={settings} light={settingsLight} />
export const ArtOps = () => <ReportArt dark={ops} light={opsLight} />
