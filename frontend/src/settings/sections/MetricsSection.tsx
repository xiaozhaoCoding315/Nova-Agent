import { TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type { Metrics } from '../../lib/types'
import { MetricTile } from '../widgets'

const pct = (value: number) => `${Math.round(value * 100)}%`

export function MetricsSection({
  refreshToken,
  days,
  onDaysChange,
}: {
  refreshToken: number
  days: number
  onDaysChange: (days: number) => void
}) {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.status.metrics(days)
      .then((next) => {
        if (!alive) return
        setMetrics(next)
        setError(null)
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : '加载失败')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [refreshToken, days])

  return (
    <section className="rounded-lg border border-edge bg-panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <TrendingUp size={14} className="text-accent" />
        <h3 className="text-sm font-medium">交付指标</h3>
        <div className="ml-auto flex gap-1">
          {[7, 30].map((option) => (
            <button
              key={option}
              onClick={() => onDaysChange(option)}
              aria-pressed={days === option}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${
                days === option ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink'
              }`}
            >
              {option} 天
            </button>
          ))}
        </div>
      </div>
      {error && <p className="mb-2 text-xs text-err">{error}</p>}
      {metrics ? (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <MetricTile label="首次 Gate 通过率" value={pct(metrics.first_gate_pass_rate)} hint="无需修复即通过" />
            <MetricTile label="返工率" value={pct(metrics.rework_rate)} hint="需要修复的任务占比" />
            <MetricTile
              label="审批耗时"
              value={metrics.approval_minutes_avg == null ? '—' : `${metrics.approval_minutes_avg} 分`}
              hint="提案创建到应用"
            />
            <MetricTile label="Token 用量" value={metrics.tokens_total.toLocaleString()} hint="窗口内累计" />
            <MetricTile
              label="任务 p95 时长"
              value={metrics.p95_job_seconds == null ? '—' : `${metrics.p95_job_seconds}s`}
              hint="后台 Job 完成耗时"
            />
          </div>
          {metrics.tool_metrics && metrics.tool_metrics.length > 0 && (
            <div className="mt-4">
              <p className="mb-1.5 text-xs uppercase tracking-wide text-dim">工具健康</p>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-2xs uppercase tracking-wide text-dim/70">
                    <tr>
                      <th className="py-1 pr-3 font-medium">工具</th>
                      <th className="py-1 pr-3 font-medium">调用</th>
                      <th className="py-1 pr-3 font-medium">成功率</th>
                      <th className="py-1 pr-3 font-medium">p95</th>
                      <th className="py-1 pr-3 font-medium">策略拒绝</th>
                      <th className="py-1 font-medium">基建错误</th>
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.tool_metrics.map((tool) => (
                      <tr key={tool.name} className="border-t border-edge/60">
                        <td className="py-1.5 pr-3 font-mono text-ink">{tool.name}</td>
                        <td className="py-1.5 pr-3 text-dim">{tool.calls}</td>
                        <td className="py-1.5 pr-3 text-dim">{pct(tool.ok_rate)}</td>
                        <td className="py-1.5 pr-3 text-dim">
                          {tool.p95_ms == null ? '—' : `${tool.p95_ms}ms`}
                        </td>
                        <td className="py-1.5 pr-3 text-dim">{tool.policy_denials}</td>
                        <td className="py-1.5 text-dim">{tool.infra_errors}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      ) : !error && (
        <p className="flex items-center gap-2 text-sm text-dim">
          {loading ? <Spinner /> : null} {loading ? '加载指标…' : '暂无指标数据'}
        </p>
      )}
    </section>
  )
}
