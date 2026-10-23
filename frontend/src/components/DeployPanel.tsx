import { ExternalLink, RefreshCw, Rocket, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { Deployment } from '../lib/types'
import { Badge, Button, Spinner } from './common'

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'err' | 'dim'> = {
  running: 'ok',
  starting: 'warn',
  failed: 'err',
  stopped: 'dim',
}

export function DeployPanel({ repoId }: { repoId: string }) {
  const [deployments, setDeployments] = useState<Deployment[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setDeployments(await api.deploys.list(repoId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载预览失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  const deploy = async (force = false) => {
    setBusy('deploy')
    setError(null)
    try {
      const deployment = await api.deploys.deploy(repoId, force)
      setDeployments((current) => [deployment, ...current.filter((d) => d.id !== deployment.id)])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '部署失败')
    } finally {
      setBusy('')
      await load()
    }
  }

  const teardown = async (id: string) => {
    setBusy(`stop-${id}`)
    setError(null)
    try {
      const updated = await api.deploys.teardown(id)
      setDeployments((current) => current.map((d) => (d.id === id ? updated : d)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '下线失败')
    } finally {
      setBusy('')
    }
  }

  const running = deployments.find((d) => d.status === 'running')

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mx-auto max-w-3xl space-y-3">
        <div className="flex items-center gap-2">
          <Rocket size={15} className="text-accent" />
          <h2 className="text-[14px] font-semibold">预览部署</h2>
          {running && <Badge tone="ok">运行中</Badge>}
          <div className="ml-auto flex gap-2">
            <Button size="sm" onClick={() => void load()} disabled={Boolean(busy)}>
              <RefreshCw size={12} /> 刷新
            </Button>
            <Button size="sm" variant="primary" onClick={() => void deploy()} disabled={Boolean(busy)}>
              {busy === 'deploy' ? <Spinner /> : <Rocket size={12} />} 部署预览
            </Button>
          </div>
        </div>

        <p className="text-[11.5px] leading-relaxed text-dim">
          使用隔离容器启动项目并做健康检查：支持 Python/FastAPI（<code className="rounded bg-raised px-1 font-mono">app/main.py</code>）
          与 Node（<code className="rounded bg-raised px-1 font-mono">package.json</code> 的 start 脚本）。
          可在 <code className="rounded bg-raised px-1 font-mono">nova.yaml</code> 的 preview.runtime/command/port/health 覆盖；
          Node 依赖需先安装到仓库依赖卷。仅管理员可操作。
        </p>

        {error && (
          <div className="rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12px] text-err">
            {error}
          </div>
        )}

        {running ? (
          <div className="rounded-xl border border-ok/30 bg-ok/5 p-4">
            <div className="flex items-center gap-2">
              <Badge tone="ok">running</Badge>
              <span className="font-mono text-[11px] text-dim">{running.container_name}</span>
              <span className="ml-auto text-[11px] text-dim">端口 {running.host_port}</span>
            </div>
            <a
              href={running.url || '#'}
              target="_blank"
              rel="noreferrer"
              className="mt-2 flex items-center gap-1.5 text-[13px] text-accent hover:underline"
            >
              <ExternalLink size={13} /> {running.url}
            </a>
            <p className="mt-1 break-all font-mono text-[10.5px] text-dim">{running.command}</p>
            <Button
              size="sm"
              variant="danger"
              className="mt-3"
              onClick={() => void teardown(running.id)}
              disabled={Boolean(busy)}
            >
              {busy === `stop-${running.id}` ? <Spinner /> : <Trash2 size={12} />} 下线预览
            </Button>
          </div>
        ) : (
          <div className="rounded-xl border border-edge bg-panel/60 p-4 text-[12.5px] text-dim">
            当前没有运行中的预览。部署成功后这里会出现可访问的本地 URL。
          </div>
        )}

        <div className="rounded-xl border border-edge bg-panel/60 p-3">
          <p className="mb-2 text-[11px] uppercase tracking-wide text-dim">部署历史</p>
          {loading ? (
            <p className="flex items-center gap-2 text-[12px] text-dim"><Spinner /> 加载中…</p>
          ) : deployments.length === 0 ? (
            <p className="text-[12px] text-dim">还没有部署记录。</p>
          ) : (
            <div className="space-y-1.5">
              {deployments.map((deployment) => (
                <div key={deployment.id} className="flex items-start gap-2 rounded-lg border border-edge bg-base/40 px-2.5 py-2">
                  <Badge tone={STATUS_TONE[deployment.status] ?? 'dim'}>{deployment.status}</Badge>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-mono text-[11px] text-ink">{deployment.url || deployment.container_name}</p>
                    <p className="mt-0.5 text-[10.5px] text-dim">
                      {deployment.created_at ? new Date(deployment.created_at).toLocaleString() : ''}
                      {deployment.error ? ` · ${deployment.error}` : ''}
                    </p>
                  </div>
                  {deployment.status === 'running' && (
                    <button
                      className="text-dim/60 hover:text-err"
                      onClick={() => void teardown(deployment.id)}
                      aria-label="下线预览"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
