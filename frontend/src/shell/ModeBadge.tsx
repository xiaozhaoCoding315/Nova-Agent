import clsx from 'clsx'
import { useMode } from '../stores/mode'

const COPY = {
  local: {
    label: 'LOCAL · NO ISOLATION',
    title: '命令直接在项目目录执行，无容器隔离',
  },
  cloud: {
    label: 'CLOUD · SANDBOX',
    title: 'Docker 沙箱执行',
  },
  unknown: {
    label: 'MODE …',
    title: '正在读取运行模式',
  },
} as const

/** 运行模式徽标：本地 / 云端 / 未知。数据来自 /status/mode。 */
export function ModeBadge() {
  const mode = useMode((state) => state.mode)
  const state = mode ? (mode.local ? 'local' : 'cloud') : 'unknown'

  return (
    <span
      className={clsx(
        'inline-flex shrink-0 items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-2xs uppercase tracking-[0.12em]',
        state === 'local' && 'border-warn/40 bg-warn/10 text-warn',
        state === 'cloud' && 'border-edge bg-raised text-dim',
        state === 'unknown' && 'border-edge bg-raised text-faint',
      )}
      title={COPY[state].title}
      aria-label={`运行模式：${COPY[state].label} — ${COPY[state].title}`}
    >
      <span
        aria-hidden="true"
        className={clsx(
          'h-1 w-1 rounded-full',
          state === 'local' && 'bg-warn',
          state === 'cloud' && 'bg-accent',
          state === 'unknown' && 'bg-faint',
        )}
      />
      {COPY[state].label}
    </span>
  )
}
