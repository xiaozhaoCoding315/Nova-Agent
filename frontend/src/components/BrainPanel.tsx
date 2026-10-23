import { BookOpen, Compass, Flame, Network } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { Brain } from '../lib/types'
import { Badge, EmptyState, Spinner } from './common'

function depGraph(brain: Brain) {
  const { nodes, edges } = brain.graph
  if (nodes.length === 0) return null
  const width = 680
  const height = 360
  const cx = width / 2
  const cy = height / 2
  const radius = Math.min(width, height) / 2 - 70
  const positions = new Map<string, { x: number; y: number }>()
  nodes.forEach((node, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2
    positions.set(node, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) })
  })
  const base = (p: string) => p.split('/').pop() ?? p
  return { width, height, positions, edges, base }
}

function Graph({ brain, onOpenFile }: { brain: Brain; onOpenFile: (path: string) => void }) {
  const layout = depGraph(brain)
  if (!layout) return <p className="text-[12.5px] text-dim">该仓库没有可展示的依赖关系。</p>
  const { width, height, positions, edges, base } = layout
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full">
      {edges.map(([from, to], i) => {
        const a = positions.get(from)
        const b = positions.get(to)
        if (!a || !b) return null
        return <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#2a3550" strokeWidth={1} />
      })}
      {[...positions.entries()].map(([path, p]) => (
        <g key={path} className="cursor-pointer" onClick={() => onOpenFile(path)}>
          <circle cx={p.x} cy={p.y} r={6} fill="#6c8cff" />
          <title>{path}</title>
          <text
            x={p.x}
            y={p.y + 18}
            textAnchor="middle"
            fontSize="10"
            fill="#8a93a8"
          >
            {base(path)}
          </text>
        </g>
      ))}
    </svg>
  )
}

export function BrainPanel({ repoId, onOpenFile }: { repoId: string; onOpenFile: (path: string) => void }) {
  const [brain, setBrain] = useState<Brain | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.repos
      .brain(repoId)
      .then((data) => {
        if (!cancelled) setBrain(data && data.totals ? data : null)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : '加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repoId])

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-[13px] text-dim">
        <Spinner /> 生成项目地图…
      </div>
    )
  }
  if (error) return <p className="p-4 text-[13px] text-err">{error}</p>
  if (!brain) {
    return <EmptyState title="还没有项目地图" hint="对仓库执行一次「重建索引」后即可生成。" />
  }

  const { totals } = brain
  const stats = [
    ['文件', totals.files],
    ['代码行', totals.lines],
    ['符号', totals.symbols],
    ['依赖关系', totals.dependencies],
    ['文档', totals.docs],
    ['测试文件', totals.tests],
  ] as const

  return (
    <div className="h-full space-y-5 overflow-y-auto p-4">
      <section>
        <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-medium text-ink">
          <Network size={13} className="text-accent" /> 仓库概览
        </h4>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {stats.map(([label, value]) => (
            <div key={label} className="rounded-lg border border-edge bg-panel/60 p-2 text-center">
              <p className="text-[15px] font-semibold">{value}</p>
              <p className="text-[10.5px] text-dim">{label}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section>
          <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
            <Compass size={13} className="text-accent" /> 推荐阅读顺序
          </h4>
          <ol className="space-y-1">
            {brain.reading_order.map((path, i) => (
              <li key={path}>
                <button
                  className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left font-mono text-[11.5px] text-dim hover:bg-raised hover:text-ink"
                  onClick={() => onOpenFile(path)}
                  title={path}
                >
                  <span className="text-[10px] text-dim/60">{i + 1}</span>
                  <span className="truncate">{path}</span>
                </button>
              </li>
            ))}
          </ol>
        </section>

        <section>
          <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
            <Flame size={13} className="text-warn" /> 核心文件（被依赖最多）
          </h4>
          <ul className="space-y-1">
            {brain.hot_files.map((f) => (
              <li key={f.path}>
                <button
                  className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-[11.5px] text-dim hover:bg-raised hover:text-ink"
                  onClick={() => onOpenFile(f.path)}
                  title={`入度 ${f.inbound} / 出度 ${f.outbound}`}
                >
                  <span className="truncate font-mono">{f.path}</span>
                  <Badge tone="dim">{f.inbound} 依赖</Badge>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <section>
        <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
          <Network size={13} className="text-accent" /> 依赖图（点击节点打开文件）
        </h4>
        <div className="rounded-lg border border-edge bg-panel/40 p-2">
          <Graph brain={brain} onOpenFile={onOpenFile} />
        </div>
      </section>

      <section>
        <h4 className="mb-2 flex items-center gap-1.5 text-[13px] font-medium">
          <BookOpen size={13} className="text-accent" /> 术语表（从符号表生成）
        </h4>
        <div className="overflow-hidden rounded-lg border border-edge">
          <table className="w-full text-[11.5px]">
            <tbody>
              {brain.glossary.map((g) => (
                <tr key={`${g.path}-${g.line}-${g.name}`} className="border-b border-edge/60 last:border-0">
                  <td className="px-2 py-1.5">
                    <button className="font-mono text-accent hover:underline" onClick={() => onOpenFile(g.path)}>
                      {g.name}
                    </button>
                  </td>
                  <td className="px-2 py-1.5 text-dim">{g.kind}</td>
                  <td className="px-2 py-1.5 font-mono text-dim">
                    {g.path}:{g.line}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}