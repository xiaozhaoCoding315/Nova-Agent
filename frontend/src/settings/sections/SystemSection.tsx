import { Badge, Spinner } from '../../components/common'
import type { Health } from '../../lib/types'
import { ComponentRow, formatUptime } from '../widgets'

export function SystemSection({
  health,
  loading,
  error,
}: {
  health: Health | null
  loading: boolean
  error: string | null
}) {
  const components = health
    ? Object.entries(health.components).filter(([key]) => key !== 'uptime_s' && key !== 'env')
    : []

  return (
    <section className="rounded-lg border border-edge bg-panel p-4">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="text-sm font-medium">依赖服务</h3>
        {health && (
          <Badge tone={health.status === 'ok' ? 'ok' : 'warn'}>
            {health.status === 'ok' ? '全部正常' : '部分降级'}
          </Badge>
        )}
        {health && (
          <span className="ml-auto text-xs text-dim">
            v{health.version} · 运行 {formatUptime(health.components.uptime_s)}
          </span>
        )}
        {!health && loading && <Spinner />}
      </div>
      {error && <p className="mb-2 text-xs text-err">{error}</p>}
      <div className="divide-y divide-edge/60">
        {components.map(([name, value]) => (
          <ComponentRow key={name} name={name} value={value} />
        ))}
      </div>
      {!health && !loading && !error && (
        <p className="text-sm text-dim">暂无服务状态。</p>
      )}
      <p className="mt-2 text-xs leading-relaxed text-dim">
        PostgreSQL 与 Qdrant 是检索/记忆的底座；LLM 可使用个人或服务端密钥；Embedding 使用服务端密钥；沙箱需要 Docker。
      </p>
    </section>
  )
}
