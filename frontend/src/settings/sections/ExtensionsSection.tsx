import { Blocks, FileText } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type { Extensions } from '../../lib/types'

export function ExtensionsSection({ refreshToken }: { refreshToken: number }) {
  const [data, setData] = useState<Extensions | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.extensions()
      .then((value) => {
        if (!alive) return
        setData(value)
        setError(null)
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : '无法读取扩展状态')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [refreshToken])

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-edge bg-panel p-4">
        <div className="mb-1 flex items-center gap-2">
          <Blocks size={14} className="text-accent" />
          <h3 className="text-sm font-medium">MCP 服务器</h3>
          {data && (
            <Badge tone={data.mcp_ready ? 'ok' : 'dim'}>
              {data.mcp_ready ? '已就绪' : '未运行'}
            </Badge>
          )}
          {loading && <Spinner />}
        </div>
        <p className="text-xs leading-relaxed text-dim">
          外接工具由操作员在 <code className="rounded bg-raised px-1 py-0.5 font-mono text-2xs">mcp_servers.json</code>
          {' '}中按 allowlist 配置；工具名以 <code className="rounded bg-raised px-1 py-0.5 font-mono text-2xs">mcp__</code> 开头。
        </p>

        {error && <p className="mt-3 text-xs text-err" role="alert">{error}</p>}

        {!loading && data && !data.mcp_enabled && (
          <p className="mt-3 text-sm text-dim">MCP 已关闭（MCP_ENABLED=false）。</p>
        )}
        {!loading && data?.mcp_enabled && data.mcp_servers.length === 0 && (
          <p className="mt-3 text-sm text-dim">
            尚未发现可用服务器。没有配置 allowlist 时不会启动任何 MCP 工具。
          </p>
        )}

        {data?.mcp_servers.length ? (
          <div className="mt-3 space-y-2">
            {data.mcp_servers.map((server) => (
              <div key={server.name} className="rounded-md border border-edge/70 bg-base/40 p-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-sm text-ink">{server.name}</span>
                  <span className="text-2xs text-faint">{server.tools.length} 个工具</span>
                </div>
                <div className="mt-2 space-y-1.5">
                  {server.tools.map((tool) => (
                    <div key={tool.name} className="flex min-w-0 items-start gap-2">
                      <span className="shrink-0 font-mono text-xs text-accent">{tool.name}</span>
                      {tool.admin_only && <Badge tone="warn">仅管理员</Badge>}
                      <span className="min-w-0 truncate text-xs text-dim" title={tool.description}>
                        {tool.description}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="rounded-lg border border-edge bg-panel p-4">
        <div className="mb-1 flex items-center gap-2">
          <FileText size={14} className="text-accent" />
          <h3 className="text-sm font-medium">技能手册</h3>
          {data && <Badge tone={data.skills_enabled ? 'ok' : 'dim'}>{data.skills.length} 个</Badge>}
          {loading && <Spinner />}
        </div>
        <p className="text-xs leading-relaxed text-dim">
          操作员把 <code className="rounded bg-raised px-1 py-0.5 font-mono text-2xs">SKILL.md</code>
          {' '}放到 <code className="rounded bg-raised px-1 py-0.5 font-mono text-2xs">data/skills/&lt;name&gt;/</code>
          {' '}后自动发现；用户点名技能或命中触发词时注入完整手册。
        </p>

        {!loading && data && !data.skills_enabled && (
          <p className="mt-3 text-sm text-dim">技能系统已关闭（SKILLS_ENABLED=false）。</p>
        )}
        {!loading && data?.skills_enabled && data.skills.length === 0 && (
          <p className="mt-3 text-sm text-dim">还没有技能。放入 SKILL.md 后约 30 秒内生效。</p>
        )}

        {data?.skills.length ? (
          <div className="mt-3 divide-y divide-edge/60">
            {data.skills.map((skill) => (
              <div key={skill.name} className="py-2.5 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm text-ink">{skill.name}</span>
                  {skill.triggers.map((trigger) => (
                    <span key={trigger} className="rounded bg-raised px-1.5 py-0.5 font-mono text-2xs text-faint">
                      {trigger}
                    </span>
                  ))}
                </div>
                {skill.description && (
                  <p className="mt-1 text-xs leading-relaxed text-dim">{skill.description}</p>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  )
}
