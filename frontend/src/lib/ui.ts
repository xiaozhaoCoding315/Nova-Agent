import type { RepoStatus } from './types'

/** 输入框与下拉框的共用外观；新 Shell、设置、登录与旧面板都引用这里，避免多份漂移。 */
export const inputClass =
  'w-full rounded-md border border-edge bg-raised/60 px-2.5 py-1.5 text-sm text-ink outline-none transition-colors focus:border-accent/50 disabled:opacity-50'

export const selectClass = inputClass + ' cursor-pointer'

/** 统一的字节展示（1024 进制，一处实现）。 */
export function formatBytes(value: number): string {
  if (value >= 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)}MB`
  if (value >= 1024) return `${(value / 1024).toFixed(1)}KB`
  return `${value}B`
}

export type StatusTone = 'ok' | 'warn' | 'err' | 'dim' | 'accent'

/** 项目索引状态：文案与色调的唯一来源（项目头 / 右栏 / 工作区抽屉）。 */
export const REPO_STATUS: Record<RepoStatus, { label: string; tone: StatusTone }> = {
  pending: { label: '排队中', tone: 'dim' },
  indexing: { label: '索引中', tone: 'warn' },
  ready: { label: '就绪', tone: 'ok' },
  failed: { label: '索引失败', tone: 'err' },
  planning: { label: '规划中', tone: 'warn' },
  plan_ready: { label: '待确认方案', tone: 'accent' },
  approved: { label: '已确认方案', tone: 'accent' },
  generating: { label: '生成中', tone: 'warn' },
  review: { label: '待审阅', tone: 'accent' },
}

/** /fix 任务状态：文案与色调的唯一来源（运行面板 / 右栏徽标）。 */
export const RUN_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  queued: { label: '排队中', tone: 'warn' },
  running: { label: '运行中', tone: 'warn' },
  ready: { label: '待确认', tone: 'accent' },
  applied: { label: '已应用', tone: 'ok' },
  rejected: { label: '已拒绝', tone: 'dim' },
  failed: { label: '失败', tone: 'err' },
  canceled: { label: '已取消', tone: 'dim' },
}
