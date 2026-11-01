import type { DeliveryReport as Report } from '../lib/types'
import { RunSummary } from '../timeline/RunSummary'

/**
 * 旧入口保留给遗留对话视图；视觉与信息结构已由 `timeline/RunSummary` 取代。
 * Task 7 删除旧视图时一并清理。
 */
export function DeliveryReport({ report }: { report: Report | null | undefined }) {
  return <RunSummary report={report} />
}
