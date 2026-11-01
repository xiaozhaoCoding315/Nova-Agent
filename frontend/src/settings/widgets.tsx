import { useState } from 'react'
import { Button, Spinner, StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { SelfQuota } from '../lib/types'
import { inputClass } from '../lib/ui'

export function formatUptime(seconds: unknown): string {
  const s = Number(seconds) || 0
  if (s < 3600) return `${Math.floor(s / 60)} 分钟`
  if (s < 86400) return `${(s / 3600).toFixed(1)} 小时`
  return `${(s / 86400).toFixed(1)} 天`
}

export function ComponentRow({ name, value }: { name: string; value: unknown }) {
  if (typeof value === 'object' && value !== null) {
    const obj = value as Record<string, unknown>
    const available = Boolean(obj.available)
    return (
      <div className="flex items-start gap-2.5 py-2">
        <StatusDot state={available ? 'ok' : 'warn'} />
        <div className="min-w-0">
          <p className="text-sm">{name}</p>
          <p className="break-all font-mono text-xs text-dim">
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
        <p className="text-sm">{name}</p>
        <p className="break-all font-mono text-xs text-dim">{text}</p>
      </div>
    </div>
  )
}

export function QuotaBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const unlimited = limit <= 0
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100))
  return (
    <div className="py-2">
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-dim">{label}</span>
        <span className="font-mono text-xs">
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

export function MetricTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
      <p className="text-2xs uppercase tracking-wide text-dim">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-2xs text-dim/70">{hint}</p>}
    </div>
  )
}

const BUDGET_FIELDS = [
  { key: 'self_daily_tokens', label: '每日 token 预算', hint: '如 50000' },
  { key: 'self_hourly_messages', label: '每小时消息数', hint: '如 20' },
  { key: 'self_sandbox_daily', label: '每日沙箱执行', hint: '如 10' },
] as const

export function SelfBudgetEditor({ quota, onSaved }: { quota: SelfQuota; onSaved: (q: SelfQuota) => void }) {
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
      <p className="text-sm text-ink">个人预算（自我约束）</p>
      <p className="mt-0.5 text-2xs leading-relaxed text-dim/80">
        只会在管理员给你的上限之内进一步收紧，用于自我控制用量；留空表示不额外限制。
      </p>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {BUDGET_FIELDS.map(({ key, label, hint }) => (
          <label key={key} className="space-y-1">
            <span className="text-xs text-dim">{label}</span>
            <input
              value={form[key] ?? ''}
              onChange={(event) => setForm({ ...form, [key]: event.target.value })}
              placeholder={hint}
              inputMode="numeric"
              className={inputClass}
            />
          </label>
        ))}
      </div>
      {error && <p className="mt-2 text-xs text-err">{error}</p>}
      {notice && <p className="mt-2 text-xs text-ok">{notice}</p>}
      <div className="mt-3 flex justify-end">
        <Button size="sm" variant="primary" onClick={() => void save()} disabled={busy}>
          {busy && <Spinner />} 保存预算
        </Button>
      </div>
    </div>
  )
}
