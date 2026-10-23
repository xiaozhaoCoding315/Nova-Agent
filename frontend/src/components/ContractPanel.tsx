import clsx from 'clsx'
import {
  CheckCircle2, FileJson, GitCompare, Info, Play, RefreshCw, XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { ContractStatus } from '../lib/types'
import { Badge, Button, Spinner } from './common'

export function ContractPanel({
  repoId,
  refreshToken,
  onRunVerify,
}: {
  repoId: string
  refreshToken?: string | number
  onRunVerify: () => void
}) {
  const [status, setStatus] = useState<ContractStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setStatus(await api.repos.contract(repoId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载契约状态失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId, refreshToken])

  if (loading) {
    return <p className="flex items-center gap-2 p-4 text-[12.5px] text-dim"><Spinner /> 读取契约状态…</p>
  }
  if (error) {
    return <p className="p-4 text-[12.5px] text-err">{error}</p>
  }
  if (!status) return null

  const tone = status.last_status === 'passed' ? 'ok' : status.last_status === 'failed' ? 'err' : 'dim'
  const Icon = status.last_status === 'passed' ? CheckCircle2 : status.last_status === 'failed' ? XCircle : Info

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mx-auto max-w-3xl space-y-3">
        <div className="flex items-center gap-2">
          <GitCompare size={15} className="text-accent" />
          <h2 className="text-[14px] font-semibold">契约对齐</h2>
          {status.configured ? <Badge tone="accent">已配置</Badge> : <Badge tone="dim">未配置</Badge>}
          <div className="ml-auto flex gap-2">
            <Button size="sm" onClick={() => void load()}>
              <RefreshCw size={12} /> 刷新
            </Button>
            <Button size="sm" variant="primary" onClick={onRunVerify}>
              <Play size={12} /> 运行验证
            </Button>
          </div>
        </div>

        {!status.configured ? (
          <div className="rounded-xl border border-edge bg-panel/60 p-4 text-[12.5px] leading-relaxed text-dim">
            <p className="font-medium text-ink">未发现 OpenAPI 契约源</p>
            <p className="mt-1">
              在仓库提交 <code className="rounded bg-raised px-1 font-mono">contracts/openapi.yaml</code> 或
              <code className="ml-1 rounded bg-raised px-1 font-mono">openapi.json</code>，
              并在 <code className="rounded bg-raised px-1 font-mono">nova.yaml</code> 中配置 source/target，
              验证门会生成前端类型并检查漂移。
            </p>
            <pre className="mt-2 rounded bg-base p-2 font-mono text-[11px] text-dim">{`contract:
  source: contracts/openapi.yaml
  target: frontend/src/lib/api-schema.d.ts`}</pre>
          </div>
        ) : (
          <>
            <div className="grid gap-2 md:grid-cols-2">
              <div className="rounded-xl border border-edge bg-panel/60 p-3">
                <p className="text-[11px] uppercase tracking-wide text-dim">契约源</p>
                <p className="mt-1 break-all font-mono text-[12px] text-ink">{status.source}</p>
                <p className={clsx('mt-1 text-[11px]', status.source_exists ? 'text-ok' : 'text-err')}>
                  {status.source_exists ? '文件存在' : '文件缺失'}
                </p>
              </div>
              <div className="rounded-xl border border-edge bg-panel/60 p-3">
                <p className="text-[11px] uppercase tracking-wide text-dim">生成的前端类型</p>
                <p className="mt-1 break-all font-mono text-[12px] text-ink">{status.target}</p>
                <p className={clsx('mt-1 text-[11px]', status.target_exists ? 'text-ok' : 'text-err')}>
                  {status.target_exists ? '文件存在' : '文件缺失，契约检查会失败'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2 text-[11.5px] text-dim">
              <FileJson size={12} />
              {status.from_config ? '来自 nova.yaml 配置' : '自动发现'}
            </div>

            <div className="rounded-xl border border-edge bg-panel/60 p-3">
              <div className="flex items-center gap-2">
                <Icon size={13} className={clsx(
                  tone === 'ok' && 'text-ok', tone === 'err' && 'text-err', tone === 'dim' && 'text-dim',
                )} />
                <span className="text-[12.5px] font-medium">最近一次契约检查</span>
                <Badge tone={tone}>{status.last_status ?? '未运行'}</Badge>
                {status.checked_at && (
                  <span className="ml-auto text-[11px] text-dim">
                    {new Date(status.checked_at).toLocaleString()}
                  </span>
                )}
              </div>
              {status.last_detail ? (
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[10.5px] text-dim">
                  {status.last_detail}
                </pre>
              ) : (
                <p className="mt-2 text-[11.5px] text-dim">
                  运行一次验证后，这里会显示契约检查的 drift 输出。
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
