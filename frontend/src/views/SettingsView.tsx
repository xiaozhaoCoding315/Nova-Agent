import {
  Activity, Brain, Clock, Coins, Cpu, FolderOpen,
  KeyRound, RefreshCw, Server, Trash2, TrendingUp, Users,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { AccountPanel } from '../components/AccountPanel'
import { AdminUsersPanel } from '../components/AdminUsersPanel'
import { FilesPanel } from '../components/FilesPanel'
import { ModelSettings } from '../components/ModelSettings'
import { Badge, Button, Spinner, StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Health, Memory, Metrics, SelfQuota, Usage } from '../lib/types'
import { useAuth } from '../stores/auth'
import { useLlm } from '../stores/llm'

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
      <div className="flex items-start gap-2.5 py-2">
        <StatusDot state={available ? 'ok' : 'warn'} />
        <div className="min-w-0">
          <p className="text-[12.5px]">{name}</p>
          <p className="break-all font-mono text-[11px] text-dim">
            {String(obj.image ?? obj.reason ?? (available ? 'ok' : 'unavailable'))}
          </p>
        </div>
      </div>
    )
  }
  const text = String(value)
  const state = text.startsWith('ok') ? 'ok' : text.startsWith('failed') ? 'err' : 'warn'
  return (
    <div className="flex items-start gap-2.5 py-2">
      <StatusDot state={state} />
      <div className="min-w-0">
        <p className="text-[12.5px]">{name}</p>
        <p className="break-all font-mono text-[11px] text-dim">{text}</p>
      </div>
    </div>
  )
}

function QuotaBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const unlimited = limit <= 0
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100))
  return (
    <div className="py-2">
      <div className="mb-1 flex items-center justify-between text-[12px]">
        <span className="text-dim">{label}</span>
        <span className="font-mono text-[11px]">
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
    <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-dim">{label}</p>
      <p className="mt-1 text-[18px] font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-[10px] text-dim/70">{hint}</p>}
    </div>
  )
}

const BUDGET_FIELDS = [
  { key: 'self_daily_tokens', label: '每日 token 预算', hint: '如 50000' },
  { key: 'self_hourly_messages', label: '每小时消息数', hint: '如 20' },
  { key: 'self_sandbox_daily', label: '每日沙箱执行', hint: '如 10' },
] as const

function SelfBudgetEditor({ quota, onSaved }: { quota: SelfQuota; onSaved: (q: SelfQuota) => void }) {
  const [form, setForm] = useState<Record<string, string>>(() => Object.fromEntries(
    BUDGET_FIELDS.map(({ key }) => [key, quota[key] == null ? '' : String(quota[key])]),
  ))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    const values: Record<string, number | null> = {}
    for (const { key } of BUDGET_FIELDS) {
      const raw = (form[key] ?? '').trim()
      if (raw === '') {
        values[key] = null
        continue
      }
      const value = Number(raw)
      if (!Number.isInteger(value) || value < 0) {
        setError('预算需为非负整数（留空表示不额外限制）')
        setBusy(false)
        return
      }
      values[key] = value
    }
    try {
      const updated = await api.quota.update(values)
      onSaved(updated)
      setNotice('个人预算已更新')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-edge/70 bg-base/30 p-3">
      <p className="text-[12px] text-ink">个人预算（自我约束）</p>
      <p className="mt-0.5 text-[10.5px] leading-relaxed text-dim/80">
        只会在管理员给你的上限之内进一步收紧，用于自我控制用量；留空表示不额外限制。
      </p>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {BUDGET_FIELDS.map(({ key, label, hint }) => (
          <label key={key} className="space-y-1">
            <span className="text-[11px] text-dim">{label}</span>
            <input
              value={form[key] ?? ''}
              onChange={(event) => setForm({ ...form, [key]: event.target.value })}
              placeholder={hint}
              inputMode="numeric"
              className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none transition-colors focus:border-accent/60"
            />
          </label>
        ))}
      </div>
      {error && <p className="mt-2 text-[11.5px] text-err">{error}</p>}
      {notice && <p className="mt-2 text-[11.5px] text-ok">{notice}</p>}
      <div className="mt-3 flex justify-end">
        <Button size="sm" variant="primary" onClick={() => void save()} disabled={busy}>
          {busy && <Spinner />} 保存预算
        </Button>
      </div>
    </div>
  )
}

type SectionKey = 'model' | 'usage' | 'metrics' | 'files' | 'memory' | 'system' | 'account' | 'admin'

const SECTIONS: { key: SectionKey; label: string; icon: typeof Cpu }[] = [
  { key: 'model', label: '模型与密钥', icon: Cpu },
  { key: 'usage', label: '用量与配额', icon: Activity },
  { key: 'metrics', label: '交付指标', icon: TrendingUp },
  { key: 'files', label: '文件与存储', icon: FolderOpen },
  { key: 'memory', label: '长期记忆', icon: Brain },
  { key: 'system', label: '系统状态', icon: Server },
  { key: 'account', label: '账号与安全', icon: KeyRound },
  { key: 'admin', label: '用户管理', icon: Users },
]

export function SettingsView() {
  const user = useAuth((s) => s.user)
  const {
    settings: llmSettings, loading: llmLoading, load: loadLlm,
  } = useLlm()

  const [section, setSection] = useState<SectionKey>('model')
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [selfQuota, setSelfQuota] = useState<SelfQuota | null>(null)
  const [memory, setMemory] = useState<Memory | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [metricsDays, setMetricsDays] = useState(7)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [h, u, sq, m, mt] = await Promise.all([
        api.status.health(),
        api.status.usage(),
        api.quota.get(),
        api.memory.get(),
        api.status.metrics(metricsDays),
      ])
      setHealth(h)
      setUsage(u)
      setSelfQuota(sq)
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
    void loadLlm()
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
  const sections = SECTIONS.filter((item) => item.key !== 'admin' || user?.role === 'admin')
  const sectionTitle = sections.find((item) => item.key === section)?.label ?? '设置'

  const refresh = () => {
    void load()
    void loadLlm()
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-52 shrink-0 border-r border-edge/70 bg-panel/25 p-3 md:block">
        <p className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-dim/70">设置</p>
        <nav className="space-y-0.5">
          {sections.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setSection(key)}
              className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12px] transition-colors ${
                section === key ? 'bg-accentSoft/35 text-ink' : 'text-dim hover:bg-raised hover:text-ink'
              }`}
            >
              <Icon size={14} className={section === key ? 'text-accent' : ''} />
              {label}
            </button>
          ))}
        </nav>
        <p className="mt-4 px-2 text-[10px] leading-relaxed text-dim/50">
          v{health?.version ?? '2.0.0'} · {user?.display_name || user?.username}
        </p>
      </aside>

      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl p-5 md:p-6">
          <div className="mb-4 flex items-center gap-2 md:hidden">
            <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
              {sections.map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setSection(key)}
                  className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] ${
                    section === key ? 'border-accent/60 bg-accentSoft/30 text-ink' : 'border-edge text-dim'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-[16px] font-semibold">{sectionTitle}</h2>
              <p className="mt-0.5 text-[11px] text-dim">
                {section === 'model'
                  ? '配置你自己的模型服务商与 API Key；支持按会话切换模型。'
                  : section === 'account'
                    ? '个人资料、密码与会话安全。'
                    : section === 'admin'
                      ? '管理系统账号、禁用账号与重置密码。'
                      : section === 'files'
                        ? '聊天附件与手动上传的个人文件，计入存储配额。'
                        : '用量、交付指标与运行状态。'}
              </p>
            </div>
            <Button size="sm" onClick={refresh} disabled={loading || llmLoading}>
              {loading || llmLoading ? <Spinner /> : <RefreshCw size={12} />} 刷新
            </Button>
          </div>

          {error && <p className="mb-3 text-[12.5px] text-err">{error}</p>}

          {section === 'model' && (
            <ModelSettings
              settings={llmSettings}
              loading={llmLoading}
              onReload={() => void loadLlm()}
            />
          )}

          {section === 'usage' && (
            <section className="rounded-xl border border-edge bg-panel p-4">
              <h3 className="mb-2 text-[13px] font-medium">今日用量与配额</h3>
              {usage ? (
                <div className="space-y-1">
                  <QuotaBar label="Token 用量" used={usage.today_tokens} limit={usage.daily_token_budget} />
                  <QuotaBar label="本小时消息数" used={usage.messages_last_hour} limit={usage.hourly_message_limit} />
                  <QuotaBar label="沙箱执行次数" used={usage.sandbox_runs_today} limit={usage.sandbox_daily_limit} />
                </div>
              ) : (
                <p className="flex items-center gap-2 text-[12px] text-dim">{loading && <Spinner />} 加载中…</p>
              )}
              {selfQuota && (
                <SelfBudgetEditor
                  quota={selfQuota}
                  onSaved={(updated) => {
                    setSelfQuota(updated)
                    void load()
                  }}
                />
              )}
              <p className="mt-2 text-[10.5px] leading-relaxed text-dim/70">
                使用个人密钥时仍会记录 token 用量与配额，便于审计；计费由你的服务商账户承担。管理员可在用户管理里为每个账号单独配置上限。
              </p>
            </section>
          )}

          {section === 'metrics' && (
            <section className="rounded-xl border border-edge bg-panel p-4">
              <div className="mb-2 flex items-center gap-2">
                <TrendingUp size={14} className="text-accent" />
                <h3 className="text-[13px] font-medium">交付指标</h3>
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
                    <p className="mb-1.5 text-[11px] uppercase tracking-wide text-dim">工具健康</p>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-[11.5px]">
                        <thead className="text-[10.5px] uppercase tracking-wide text-dim/70">
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
              ) : (
                <p className="flex items-center gap-2 text-[12.5px] text-dim"><Spinner /> 加载指标…</p>
              )}
            </section>
          )}

          {section === 'files' && <FilesPanel />}

          {section === 'memory' && (
            <section className="rounded-xl border border-edge bg-panel p-4">
              <div className="mb-2 flex items-center gap-2">
                <Brain size={14} className="text-accent" />
                <h3 className="text-[13px] font-medium">记忆</h3>
                <span className="text-[11px] text-dim">
                  {memory ? `${memory.facts.length} 条事实 · ${memory.daily.length} 份日摘要` : '加载中…'}
                </span>
              </div>

              {memory && memory.facts.length > 0 && (
                <div className="space-y-1.5">
                  <p className="text-[10px] uppercase tracking-wide text-dim">长期事实</p>
                  {memory.facts.map((fact) => (
                    <div key={fact.id} className="flex items-start gap-2 rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2">
                      <div className="min-w-0 flex-1">
                        <p className="text-[12px] leading-relaxed">{fact.content}</p>
                        <p className="mt-0.5 flex items-center gap-2 text-[10px] text-dim">
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
                  <p className="text-[10px] uppercase tracking-wide text-dim">日摘要</p>
                  {memory.daily.map((item) => (
                    <div key={item.day} className="rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2">
                      <div className="flex items-center gap-2">
                        <Clock size={11} className="text-dim" />
                        <span className="font-mono text-[11px] text-dim">{item.day}</span>
                        <span className="text-[10px] text-dim/70">{item.message_count} 条消息</span>
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
          )}

          {section === 'system' && (
            <section className="rounded-xl border border-edge bg-panel p-4">
              <div className="mb-1 flex items-center gap-2">
                <h3 className="text-[13px] font-medium">依赖服务</h3>
                {health && (
                  <Badge tone={health.status === 'ok' ? 'ok' : 'warn'}>
                    {health.status === 'ok' ? '全部正常' : '部分降级'}
                  </Badge>
                )}
                {health && (
                  <span className="ml-auto text-[11px] text-dim">
                    v{health.version} · 运行 {formatUptime(health.components.uptime_s)}
                  </span>
                )}
              </div>
              <div className="divide-y divide-edge/60">
                {components.map(([name, value]) => (
                  <ComponentRow key={name} name={name} value={value} />
                ))}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-dim">
                PostgreSQL 与 Qdrant 是检索/记忆的底座；LLM 可使用个人或服务端密钥；Embedding 使用服务端密钥；沙箱需要 Docker。
              </p>
            </section>
          )}

          {section === 'account' && <AccountPanel />}

          {section === 'admin' && user?.role === 'admin' && <AdminUsersPanel />}
        </div>
      </div>
    </div>
  )
}
