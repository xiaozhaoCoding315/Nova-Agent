import clsx from 'clsx'
import { Check, Copy, Radar, Search } from 'lucide-react'
import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import { api, ApiError } from '../lib/api'
import type { Impact } from '../lib/types'
import { Badge, Button, EmptyState, Spinner } from './common'

const RISK_META: Record<string, { label: string; tone: 'ok' | 'warn' | 'err' | 'dim'; color: string }> = {
  low: { label: '低风险', tone: 'ok', color: 'text-ok' },
  medium: { label: '中风险', tone: 'warn', color: 'text-warn' },
  high: { label: '高风险', tone: 'err', color: 'text-err' },
  unknown: { label: '未找到', tone: 'dim', color: 'text-dim' },
}

export function ImpactPanel({ repoId, onOpenFile }: { repoId: string; onOpenFile: (path: string) => void }) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<Impact | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const run = async () => {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    try {
      setResult(await api.repos.impact(repoId, q))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '分析失败')
    } finally {
      setLoading(false)
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') void run()
  }

  const copyCommand = async () => {
    if (!result?.suggested_command) return
    try {
      await navigator.clipboard.writeText(result.suggested_command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore */
    }
  }

  const risk = result?.risk
  const meta = RISK_META[risk?.level ?? 'unknown']

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="flex items-center gap-2">
        <Radar size={15} className="text-accent" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="输入函数名 / 类名 / 文件路径，例如 calculate_tax"
          className="min-w-0 flex-1 rounded-lg border border-edge bg-raised px-3 py-1.5 font-mono text-[12.5px] outline-none placeholder:text-dim/60 focus:border-accentSoft"
        />
        <Button variant="primary" size="sm" onClick={() => void run()} disabled={loading || !query.trim()}>
          {loading ? <Spinner /> : <Search size={12} />} 分析
        </Button>
      </div>

      {error && <p className="mt-3 text-[12.5px] text-err">{error}</p>}

      {!result && !loading && (
        <div className="mt-6">
          <EmptyState
            title="改这个函数会影响什么？"
            hint="基于仓库导入关系与符号引用做静态分析：直接/间接依赖文件、引用位置、相关测试与风险等级。分析会给出建议运行的测试命令，可复制到沙箱或本地执行。"
          />
        </div>
      )}

      {result && (
        <div className="mt-4 space-y-4">
          <section className={clsx('rounded-xl border p-3', risk?.level === 'high' ? 'border-err/40 bg-err/5' : risk?.level === 'medium' ? 'border-warn/40 bg-warn/5' : 'border-edge bg-panel/50')}>
            <div className="flex items-center gap-2">
              <span className={clsx('text-[14px] font-semibold', meta.color)}>{meta.label}</span>
              {typeof risk?.score === 'number' && <Badge tone={meta.tone}>评分 {risk.score}</Badge>}
              <span className="ml-auto text-[11.5px] text-dim">{result.targets?.join('，')}</span>
            </div>
            <ul className="mt-2 space-y-1 text-[12px] text-dim">
              {(risk?.reasons ?? []).map((reason) => (
                <li key={reason}>· {reason}</li>
              ))}
            </ul>
          </section>

          <section className="grid gap-3 md:grid-cols-2">
            <div>
              <h4 className="mb-1.5 text-[12.5px] font-medium">直接依赖（{result.direct_dependents?.length ?? 0}）</h4>
              <PathList paths={result.direct_dependents ?? []} onOpen={onOpenFile} empty="没有直接依赖文件" />
            </div>
            <div>
              <h4 className="mb-1.5 text-[12.5px] font-medium">间接依赖（{result.transitive_dependents?.length ?? 0}）</h4>
              <PathList paths={result.transitive_dependents ?? []} onOpen={onOpenFile} empty="没有间接依赖文件" />
            </div>
          </section>

          <section>
            <h4 className="mb-1.5 text-[12.5px] font-medium">引用位置（{result.references?.length ?? 0} 个文件）</h4>
            <div className="space-y-1">
              {result.references?.map((ref) => (
                <button
                  key={ref.path}
                  className="flex w-full items-center gap-2 rounded border border-edge bg-panel/40 px-2 py-1 text-left font-mono text-[11.5px] text-dim hover:text-ink"
                  onClick={() => onOpenFile(ref.path)}
                  title={ref.path}
                >
                  <span className="truncate">{ref.path}:{ref.line_start}</span>
                  <Badge tone="dim">{ref.occurrences} 次</Badge>
                </button>
              ))}
              {(result.references?.length ?? 0) === 0 && <p className="text-[12px] text-dim">没有发现符号引用。</p>}
            </div>
          </section>

          <section>
            <h4 className="mb-1.5 text-[12.5px] font-medium">相关测试（{result.tests?.length ?? 0}）</h4>
            <PathList paths={result.tests ?? []} onOpen={onOpenFile} empty="未发现相关测试（回归风险需人工确认）" />
          </section>

          {result.suggested_command && (
            <section className="rounded-lg border border-edge bg-panel/50 p-2.5">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[11.5px] text-dim">建议测试命令</span>
                <button className="text-dim hover:text-ink" onClick={() => void copyCommand()} aria-label="复制命令">
                  {copied ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                </button>
              </div>
              <code className="block break-all font-mono text-[11.5px] text-ink">{result.suggested_command}</code>
            </section>
          )}

          {result.note && <p className="text-[11px] leading-relaxed text-dim">{result.note}</p>}
        </div>
      )}
    </div>
  )
}

function PathList({ paths, onOpen, empty }: { paths: string[]; onOpen: (path: string) => void; empty: string }) {
  if (paths.length === 0) return <p className="text-[12px] text-dim">{empty}</p>
  return (
    <div className="space-y-1">
      {paths.map((path) => (
        <button
          key={path}
          className="block w-full truncate rounded border border-edge bg-panel/40 px-2 py-1 text-left font-mono text-[11.5px] text-dim hover:text-ink"
          onClick={() => onOpen(path)}
          title={path}
        >
          {path}
        </button>
      ))}
    </div>
  )
}