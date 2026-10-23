import {
  Activity, AlertCircle, Brain, CheckCircle2, Clock, Coins, Cpu, Eye, EyeOff, KeyRound,
  RefreshCw, Server, Trash2, TrendingUp, Users, Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { AccountPanel } from '../components/AccountPanel'
import { AdminUsersPanel } from '../components/AdminUsersPanel'
import { Badge, Button, Modal, Spinner, StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Health, LlmSettings, Memory, Metrics, Usage } from '../lib/types'
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

type SectionKey = 'model' | 'usage' | 'metrics' | 'memory' | 'system' | 'account' | 'admin'

const SECTIONS: { key: SectionKey; label: string; icon: typeof Cpu }[] = [
  { key: 'model', label: '模型与密钥', icon: Cpu },
  { key: 'usage', label: '用量与配额', icon: Activity },
  { key: 'metrics', label: '交付指标', icon: TrendingUp },
  { key: 'memory', label: '长期记忆', icon: Brain },
  { key: 'system', label: '系统状态', icon: Server },
  { key: 'account', label: '账号与安全', icon: KeyRound },
  { key: 'admin', label: '用户管理', icon: Users },
]

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 flex items-center gap-2 text-[11.5px] text-dim">
        {label}
        {hint && <span className="text-[10px] text-dim/50">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

const inputClass =
  'w-full rounded-lg border border-edge bg-base/60 px-3 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-accent/60 disabled:opacity-50'

function ModelSection({ settings, loading, onReload }: {
  settings: LlmSettings | null
  loading: boolean
  onReload: () => void
}) {
  const { save, clear, test } = useLlm()
  const [hydrated, setHydrated] = useState(false)
  const [provider, setProvider] = useState('dashscope')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [feedback, setFeedback] = useState<{ ok: boolean; text: string } | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)

  useEffect(() => {
    if (!settings || hydrated) return
    const providers = settings.providers
    const saved = settings.source === 'user'
    const preset = providers.find((item) => item.id === (saved ? settings.provider : 'dashscope')) ?? providers[0]
    if (!preset) return
    const savedModel = saved ? (settings.model ?? '') : ''
    const known = preset.models.includes(savedModel)
    setProvider(preset.id)
    setBaseUrl(saved && settings.base_url ? settings.base_url : preset.base_url)
    setModel(savedModel && !known ? '__custom__' : (savedModel || preset.models[0] || '__custom__'))
    setCustomModel(savedModel && !known ? savedModel : '')
    setHydrated(true)
  }, [settings, hydrated])

  const preset = settings?.providers.find((item) => item.id === provider)
  const effectiveModel = model === '__custom__' ? customModel.trim() : model
  const sourceUser = settings?.source === 'user'

  const chooseProvider = (id: string) => {
    const next = settings?.providers.find((item) => item.id === id)
    setProvider(id)
    setBaseUrl(next?.base_url ?? '')
    setModel(next?.models[0] ?? '__custom__')
    setCustomModel('')
    setFeedback(null)
  }

  const submit = async (mode: 'save' | 'test') => {
    if (!effectiveModel) {
      setFeedback({ ok: false, text: '请选择或填写模型名称' })
      return
    }
    if (mode === 'save') setBusy(true)
    else setTesting(true)
    setFeedback(null)
    try {
      const input = {
        provider,
        model: effectiveModel,
        base_url: baseUrl.trim() || null,
        api_key: apiKey.trim() || null,
      }
      if (mode === 'save') {
        const saved = await save(input)
        setApiKey('')
        setHydrated(false)
        setFeedback({ ok: true, text: `已保存，当前模型：${saved.model}` })
        onReload()
      } else {
        const result = await test(input)
        setFeedback({
          ok: result.ok,
          text: `${result.message}${result.latency_ms ? `（${result.latency_ms} ms）` : ''}`,
        })
      }
    } catch (err) {
      setFeedback({ ok: false, text: err instanceof ApiError ? err.message : '操作失败' })
    } finally {
      setBusy(false)
      setTesting(false)
    }
  }

  if (!settings) {
    return <p className="flex items-center gap-2 text-[12.5px] text-dim">{loading ? <Spinner /> : null} 加载模型配置…</p>
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="flex items-start gap-3">
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${sourceUser ? 'bg-accentSoft/50 text-accent' : 'bg-raised text-dim'}`}>
            {sourceUser ? <KeyRound size={16} /> : <Server size={16} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[13px] font-medium">
                {sourceUser ? '正在使用你自己的 API Key' : settings.source === 'server' ? '正在使用服务端共享密钥' : '尚未配置可用模型'}
              </p>
              <Badge tone={sourceUser ? 'accent' : settings.source === 'server' ? 'ok' : 'err'}>
                {sourceUser ? '个人' : settings.source === 'server' ? '共享' : '未配置'}
              </Badge>
            </div>
            <p className="mt-1 break-all text-[11.5px] text-dim">
              {settings.model ?? '—'}
              {sourceUser && settings.key_hint ? ` · ${settings.key_hint}` : ''}
              {sourceUser && settings.provider ? ` · ${settings.providers.find((p) => p.id === settings.provider)?.label ?? settings.provider}` : ''}
            </p>
            {!sourceUser && settings.source === 'server' && (
              <p className="mt-1 text-[11px] leading-relaxed text-dim/80">
                对话会消耗部署者的额度。保存自己的 Key 后将完全改用你的配置，不回退到共享密钥。
              </p>
            )}
            {settings.source === 'none' && !settings.allow_server_fallback && (
              <p className="mt-1 text-[11px] leading-relaxed text-warn">
                服务端已关闭共享模型，必须配置个人 API Key 才能开始对话。
              </p>
            )}
          </div>
          {sourceUser && (
            <Button size="sm" variant="danger" onClick={() => setConfirmClear(true)}>
              移除
            </Button>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Cpu size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">模型服务商</h3>
          <span className="text-[10.5px] text-dim">任意 OpenAI 兼容端点</span>
        </div>
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
          {settings.providers.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => chooseProvider(item.id)}
              className={`rounded-lg border px-2.5 py-2 text-left transition-colors ${
                provider === item.id
                  ? 'border-accent/70 bg-accentSoft/25'
                  : 'border-edge/80 hover:border-accentSoft'
              }`}
            >
              <p className="truncate text-[12px] font-medium">{item.label}</p>
              <p className="mt-0.5 truncate font-mono text-[9.5px] text-dim">{item.base_url || '自定义地址'}</p>
            </button>
          ))}
        </div>
      </section>

      <section className="space-y-3 rounded-xl border border-edge bg-panel p-4">
        <Field label="Base URL" hint="OpenAI 兼容 /v1 地址">
          <input
            className={inputClass}
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder="https://api.example.com/v1"
            spellCheck={false}
          />
        </Field>

        <Field label="API Key" hint={settings.has_key ? `已保存 ${settings.key_hint}，留空保持不变` : '仅保存在服务端，加密存储'}>
          <div className="relative">
            <input
              className={`${inputClass} pr-9`}
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={settings.has_key ? '留空则继续使用已保存的 Key' : 'sk-…'}
              autoComplete="off"
              spellCheck={false}
            />
            <button
              type="button"
              onClick={() => setShowKey((value) => !value)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-dim hover:text-ink"
              aria-label={showKey ? '隐藏密钥' : '显示密钥'}
            >
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </Field>

        <Field label="模型">
          {preset && preset.models.length > 0 ? (
            <select
              className={inputClass}
              value={model}
              onChange={(event) => setModel(event.target.value)}
            >
              {preset.models.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
              <option value="__custom__">自定义模型…</option>
            </select>
          ) : null}
          {(model === '__custom__' || !preset?.models.length) && (
            <input
              className={`${inputClass} ${preset?.models.length ? 'mt-2' : ''}`}
              value={customModel}
              onChange={(event) => setCustomModel(event.target.value)}
              placeholder="填写模型 ID，例如 qwen3-coder-plus"
              spellCheck={false}
            />
          )}
        </Field>

        {feedback && (
          <p className={`flex items-start gap-1.5 text-[11.5px] ${feedback.ok ? 'text-ok' : 'text-err'}`}>
            {feedback.ok ? <CheckCircle2 size={13} className="mt-0.5 shrink-0" /> : <AlertCircle size={13} className="mt-0.5 shrink-0" />}
            <span className="break-all">{feedback.text}</span>
          </p>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void submit('save')}>
            {busy ? <Spinner /> : <KeyRound size={12} />} 保存配置
          </Button>
          <Button size="sm" disabled={testing} onClick={() => void submit('test')}>
            {testing ? <Spinner /> : <Zap size={12} />} 测试连接
          </Button>
          <p className="ml-auto text-[10px] text-dim/60">
            密钥以 SECRET_KEY 派生密钥加密；接口只返回掩码。Embedding 仍使用服务端密钥。
          </p>
        </div>
      </section>

      <Modal open={confirmClear} onClose={() => setConfirmClear(false)} title="移除个人模型配置" width="max-w-sm">
        <p className="text-[12.5px] leading-relaxed text-dim">
          移除后，对话会回退到服务端共享密钥{settings.allow_server_fallback ? '' : '；当前部署已关闭共享密钥，将无法继续对话'}。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => setConfirmClear(false)}>取消</Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              setConfirmClear(false)
              void clear().then(() => {
                setHydrated(false)
                setFeedback({ ok: true, text: '已移除个人模型配置' })
                onReload()
              })
            }}
          >
            确认移除
          </Button>
        </div>
      </Modal>
    </div>
  )
}

export function SettingsView() {
  const user = useAuth((s) => s.user)
  const {
    settings: llmSettings, loading: llmLoading, load: loadLlm,
  } = useLlm()

  const [section, setSection] = useState<SectionKey>('model')
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
                      : '用量、交付指标与运行状态。'}
              </p>
            </div>
            <Button size="sm" onClick={refresh} disabled={loading || llmLoading}>
              {loading || llmLoading ? <Spinner /> : <RefreshCw size={12} />} 刷新
            </Button>
          </div>

          {error && <p className="mb-3 text-[12.5px] text-err">{error}</p>}

          {section === 'model' && (
            <ModelSection settings={llmSettings} loading={llmLoading} onReload={() => void loadLlm()} />
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
              <p className="mt-2 text-[10.5px] leading-relaxed text-dim/70">
                使用个人密钥时仍会记录 token 用量与配额，便于审计；计费由你的服务商账户承担。
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
          )}

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
