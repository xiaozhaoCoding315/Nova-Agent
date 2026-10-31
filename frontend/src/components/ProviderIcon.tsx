import { PROVIDER_ICON_PATHS } from '../lib/provider-icons'

export function ProviderIcon({
  id,
  size = 18,
  className = '',
}: {
  id: string
  size?: number
  className?: string
}) {
  const paths = PROVIDER_ICON_PATHS[id]
  if (!paths) {
    return (
      <span
        className={`inline-flex shrink-0 items-center justify-center rounded-md bg-raised font-mono text-[10px] font-semibold uppercase text-dim ${className}`}
        style={{ width: size, height: size }}
        aria-hidden
      >
        {id.slice(0, 1)}
      </span>
    )
  }
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      className={`shrink-0 ${className}`}
      aria-hidden
    >
      {paths.map((path, index) => <path key={index} d={path} />)}
    </svg>
  )
}
