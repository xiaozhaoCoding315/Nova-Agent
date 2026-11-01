import { useEffect, useState } from 'react'
import { Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type { SelfQuota, Usage } from '../../lib/types'
import { QuotaBar, SelfBudgetEditor } from '../widgets'

export function UsageSection({ refreshToken }: { refreshToken: number }) {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [selfQuota, setSelfQuota] = useState<SelfQuota | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [nextUsage, nextQuota] = await Promise.all([
        api.status.usage(),
        api.quota.get(),
      ])
      setUsage(nextUsage)
      setSelfQuota(nextQuota)
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
  }, [refreshToken])

  return (
    <section className="rounded-lg border border-edge bg-panel p-4">
      <h3 className="mb-2 text-sm font-medium">今日用量与配额</h3>
      {error && <p className="mb-2 text-xs text-err">{error}</p>}
      {usage ? (
        <div className="space-y-1">
          <QuotaBar label="Token 用量" used={usage.today_tokens} limit={usage.daily_token_budget} />
          <QuotaBar label="本小时消息数" used={usage.messages_last_hour} limit={usage.hourly_message_limit} />
          <QuotaBar label="沙箱执行次数" used={usage.sandbox_runs_today} limit={usage.sandbox_daily_limit} />
        </div>
      ) : (
        <p className="flex items-center gap-2 text-sm text-dim">
          {loading ? <Spinner /> : null} {loading ? '加载中…' : '暂无用量数据'}
        </p>
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
      <p className="mt-2 text-2xs leading-relaxed text-dim/70">
        使用个人密钥时仍会记录 token 用量与配额，便于审计；计费由你的服务商账户承担。管理员可在用户管理里为每个账号单独配置上限。
      </p>
    </section>
  )
}
