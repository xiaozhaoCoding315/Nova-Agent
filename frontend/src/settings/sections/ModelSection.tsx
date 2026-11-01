import { ModelSettings } from '../../components/ModelSettings'
import type { LlmSettings } from '../../lib/types'

export function ModelSection({
  settings,
  loading,
  onReload,
}: {
  settings: LlmSettings | null
  loading: boolean
  onReload: () => void
}) {
  return <ModelSettings settings={settings} loading={loading} onReload={onReload} />
}
