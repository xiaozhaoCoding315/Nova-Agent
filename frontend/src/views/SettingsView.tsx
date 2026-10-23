import { LogOut, RefreshCw, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Button, Spinner, StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Health, Usage } from '../lib/types'
import { useAuth } from '../stores/auth'

function formatUptime(seconds: unknown): string {
  const s = Number(seconds) || 0
  if (s < 3600) return `${Math.floor(s / 60)} 分钟`
  if (s < 86400) return `${(s / 3600).toFixed(1)} 小时`
  return `${(s / 86400).toFixed(1)} 天`
}

function ComponentRow({ name, value }: { name: string; value: unknown }) {
  if (typeof value === 'object' && value !== null) {
    const obj = value as Record<string, unknown>
    const available = Boolean(obj.available)
    return (
      <div className="flex items-start gap-2.5 py-1.5">
        <StatusDot state={available ? 'ok' : 'warn'} />
        <div className="min-w-0">
          <p className="text-[13px]">{name}</p>
          <p className="break-all font-mono text-[11.5px] text-dim">
            {String(obj.image ?? obj.reason ?? (available ? 'ok' : 'unavailable'))}
          </p>
        </div>
      </div>
    )
  }
  const text = String(value)
  const state = text.startsWith('ok') ? 'ok' : text.startsWith('failed') ? 'err' : 'warn'
  return (
    <div className="flex items-start gap-2.5 py-1.5">
      <StatusDot state={state} />
      <div className="min-w-0">
        <p className="text-[13px]">{name}</p>
        <p className="break-all font-mono text-[11.5px] text-dim">{text}</p>
      </div>
    </div>
  )
}

function QuotaBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const unlimited = limit <= 0
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100))
  return (
    <div className="py-1.5">
      <div className="mb-1 flex items-center justify-between text-[12.5px]">
        <span className="text-dim">{label}</span>
        <span className="font-mono text-[11.5px]">
          {used.toLocaleString()} {unlimited ? '/ 不限' : `/ ${limit.toLocaleString()}`}
        </span>
      </div>
      {!unlimited && (
        <div className="h-1.5 overflow-hidden rounded-full bg-raised">
          <div
            className={`h-full rounded-full ${pct >= 90 ? 'bg-err' : pct >= 70 ? 'bg-warn' : 'bg-accent'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      )}
    </div>
  )
}

export function SettingsView() {
  const user = useAuth((s) => s.user)
  const logout = useAuth((s) => s.logout)
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [h, u] = await Promise.all([api.status.health(), api.status.usage()])
      setHealth(h)
      setUsage(u)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const components = health
    ? Object.entries(health.components).filter(([key]) => key !== 'uptime_s' && key !== 'env')
    : []

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-3xl space-y-5">
        <div className="flex items-center justify-between">
          <h2 className="text-[16px] font-semibold">系统状态</h2>
          <Button size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? <Spinner /> : <RefreshCw size={12} />} 刷新
          </Button>
        </div>

        {error && <p className="text-[13px] text-err">{error}</p>}

        <section className="rounded-xl border border-edge bg-panel p-4">
          <div className="mb-1 flex items-center gap-2">
            <h3 className="text-[13.5px] font-medium">依赖服务</h3>
            {health && (
              <Badge tone={health.status === 'ok' ? 'ok' : 'warn'}>
                {health.status === 'ok' ? '全部正常' : '部分降级'}
              </Badge>
            )}
            {health && (
              <span className="ml-auto text-[11.5px] text-dim">
                v{health.version} · 运行 {formatUptime(health.components.uptime_s)}
              </span>
            )}
          </div>
          <div className="divide-y divide-edge/60">
            {components.map(([name, value]) => (
              <ComponentRow key={name} name={name} value={value} />
            ))}
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed text-dim">
            PostgreSQL 与 Qdrant 是检索/记忆的底座；LLM 与 Embedding 需要 API Key；沙箱需要 Docker 且构建
            nova-sandbox 镜像，不可用时 run_code 工具会如实标记而不是降级执行。
          </p>
        </section>

        <section className="rounded-xl border border-edge bg-panel p-4">
          <h3 className="mb-2 text-[13.5px] font-medium">今日用量与配额</h3>
          {usage ? (
            <div className="space-y-1">
              <QuotaBar label="Token 用量" used={usage.today_tokens} limit={usage.daily_token_budget} />
              <QuotaBar label="本小时消息数" used={usage.messages_last_hour} limit={usage.hourly_message_limit} />
              <QuotaBar label="沙箱执行次数" used={usage.sandbox_runs_today} limit={usage.sandbox_daily_limit} />
            </div>
          ) : (
            <p className="flex items-center gap-2 text-[12.5px] text-dim">
              {loading && <Spinner />} 加载中…
            </p>
          )}
        </section>

        <section className="rounded-xl border border-edge bg-panel p-4">
          <h3 className="mb-2 text-[13.5px] font-medium">账号</h3>
          <div className="flex items-center gap-2.5">
            <ShieldCheck size={16} className="text-accent" />
            <div>
              <p className="text-[13px]">
                {user?.username} <Badge tone={user?.role === 'admin' ? 'accent' : 'dim'}>{user?.role}</Badge>
              </p>
              <p className="text-[11.5px] text-dim">账号与密码在服务端 .env 中维护（ADMIN_PASSWORD / DEMO_PASSWORD）</p>
            </div>
            <Button size="sm" variant="danger" className="ml-auto" onClick={() => void logout()}>
              <LogOut size={12} /> 退出登录
            </Button>
          </div>
        </section>
      </div>
    </div>
  )
}