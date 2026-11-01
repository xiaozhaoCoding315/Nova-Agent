import clsx from 'clsx'
import { useMode } from '../stores/mode'

/** 运行模式徽标：本地 / 云端。数据来自 /status/mode。 */
export function ModeBadge() {
  const mode = useMode((state) => state.mode)
  const local = Boolean(mode?.local)
  const label = mode ? (local ? '本地' : '云端') : '连接中'

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 font-mono text-2xs tracking-[0.12em] transition-colors duration-150',
        local ? 'border-accent/30 bg-accentSoft text-accent' : 'border-edge bg-raised text-dim',
      )}
      title={local ? '本地模式：无容器隔离' : '云端模式：容器隔离'}
    >
      <span
        aria-hidden="true"
        className={clsx('h-1 w-1 rounded-full', local ? 'bg-accent' : 'bg-faint')}
      />
      {label}
    </span>
  )
}
