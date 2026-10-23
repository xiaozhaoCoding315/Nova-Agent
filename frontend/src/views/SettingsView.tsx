import { Brain, Clock, Coins, LogOut, RefreshCw, ShieldCheck, Trash2, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Button, Spinner, StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Health, Memory, Metrics, Usage } from '../lib/types'
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

function MetricTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-edge bg-base/50 px-3 py-2.5">
      <p className="text-[10.5px] uppercase tracking-wide text-dim">{label}</p>
      <p className="mt-1 text-[18px] font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-[10.5px] text-dim/70">{hint}</p>}
    </div>
  )
}

export function SettingsView() {
  const user = useAuth((s) => s.user)
  const logout = useAuth((s) => s.logout)
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [memory, setMemory] = useState<Memory | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [metricsDays, setMetricsDays] = useState(7)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [h, u, m, mt] = await Promise.all([
        api.status.health(),
        api.status.usage(),
        api.memory.get(),
        api.status.metrics(metricsDays),
      ])
      setHealth(h)
      setUsage(u)
      setMemory(m)
      setMetrics(mt)
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
  }, [metricsDays])

  const removeFact = async (id: number) => {
    try {
      await api.memory.removeFact(id)
      setMemory((current) => current ? { ...current, facts: current.facts.filter((f) => f.id !== id) } : current)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const removeDaily = async (day: string) => {
    try {
      await api.memory.removeDaily(day)
      setMemory((current) => current ? { ...current, daily: current.daily.filter((d) => d.day !== day) } : current)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const components = health
    ? Object.entries(health.components).filter(([key]) => key !== 'uptime_s' && key !== 'env')
    : []

  const pct = (value: number) => `${Math.round(value * 100)}%`

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
          <div className="mb-2 flex items-center gap-2">
            <TrendingUp size={14} className="text-accent" />
            <h3 className="text-[13.5px] font-medium">交付指标</h3>
            <div className="ml-auto flex gap-1">
              {[7, 30].map((days) => (
                <button
                  key={days}
                  onClick={() => setMetricsDays(days)}
                  className={`rounded px-2 py-0.5 text-[11px] ${metricsDays === days ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink'}`}
                >
                  {days} 天
                </button>
              ))}
            </div>
          </div>
          {metrics ? (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <MetricTile label="接受变更" value={String(metrics.accepted_changes)} hint={`共 ${metrics.changes_total} 个变更`} />
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
          ) : (
            <p className="flex items-center gap-2 text-[12.5px] text-dim"><Spinner /> 加载指标…</p>
          )}
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
          <div className="mb-2 flex items-center gap-2">
            <Brain size={14} className="text-accent" />
            <h3 className="text-[13.5px] font-medium">记忆</h3>
            <span className="text-[11px] text-dim">
              {memory ? `${memory.facts.length} 条事实 · ${memory.daily.length} 份日摘要` : '加载中…'}
            </span>
          </div>

          {memory && memory.facts.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[10.5px] uppercase tracking-wide text-dim">长期事实</p>
              {memory.facts.map((fact) => (
                <div key={fact.id} className="flex items-start gap-2 rounded-lg border border-edge bg-base/40 px-2.5 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[12px] leading-relaxed">{fact.content}</p>
                    <p className="mt-0.5 flex items-center gap-2 text-[10.5px] text-dim">
                      <span className="flex items-center gap-1"><Coins size={10} /> 重要性 {fact.importance.toFixed(1)}</span>
                      {fact.promoted_at && <Badge tone="ok">已晋升</Badge>}
                      {fact.last_used_at && <span>最近使用 {new Date(fact.last_used_at).toLocaleDateString()}</span>}
                    </p>
                  </div>
                  <button
                    className="mt-0.5 text-dim/60 hover:text-err"
                    onClick={() => void removeFact(fact.id)}
                    aria-label="删除事实"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          )}

          {memory && memory.daily.length > 0 && (
            <div className="mt-3 space-y-1.5">
              <p className="text-[10.5px] uppercase tracking-wide text-dim">日摘要</p>
              {memory.daily.map((item) => (
                <div key={item.day} className="rounded-lg border border-edge bg-base/40 px-2.5 py-2">
                  <div className="flex items-center gap-2">
                    <Clock size={11} className="text-dim" />
                    <span className="font-mono text-[11px] text-dim">{item.day}</span>
                    <span className="text-[10.5px] text-dim/70">{item.message_count} 条消息</span>
                    <button
                      className="ml-auto text-dim/60 hover:text-err"
                      onClick={() => void removeDaily(item.day)}
                      aria-label="删除日摘要"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-[11.5px] leading-relaxed text-dim">
                    {item.summary}
                  </p>
                </div>
              ))}
            </div>
          )}

          {memory && memory.facts.length === 0 && memory.daily.length === 0 && (
            <p className="text-[12px] leading-relaxed text-dim">
              还没有长期记忆。对话中抽取的偏好、日摘要与晋升事实会出现在这里；你可以随时删除。
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
