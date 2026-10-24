import { Activity, RefreshCw, ScanLine } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { DebtReport } from '../lib/types'
import { Badge, Button, Spinner } from './common'

function scoreTone(score: number): 'ok' | 'warn' | 'err' {
  if (score < 30) return 'ok'
  if (score < 60) return 'warn'
  return 'err'
}

function scoreLabel(score: number): string {
  if (score < 30) return '健康'
  if (score < 60) return '有债'
  return '高债'
}

export function DebtPanel({ repoId }: { repoId: string }) {
  const [report, setReport] = useState<DebtReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      setReport(await api.repos.debt(repoId))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载技术债数据失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  const scan = async () => {
    setScanning(true)
    setError(null)
    try {
      await api.repos.debtScan(repoId)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '扫描失败')
    } finally {
      setScanning(false)
    }
  }

  const latest = report?.latest ?? null
  const history = report?.history ?? []
  const prev = history.length >= 2 ? history[history.length - 2] : null
  const delta = latest && prev ? latest.score - prev.score : null
  const maxScore = Math.max(10, ...history.map((h) => h.score))

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Activity size={14} className="text-accent" />
        <h3 className="text-[13px] font-medium">技术债雷达</h3>
        <span className="text-[10.5px] text-dim">确定性指标，无模型参与；每周自动快照</span>
        <div className="ml-auto flex gap-1.5">
          <Button size="sm" onClick={() => void load()} disabled={loading}>
            {loading ? <Spinner /> : <RefreshCw size={12} />} 刷新
          </Button>
          <Button size="sm" variant="primary" onClick={() => void scan()} disabled={scanning}>
            {scanning ? <Spinner /> : <ScanLine size={12} />} 立即扫描
          </Button>
        </div>
      </div>
      {error && <p className="mb-2 text-[11.5px] text-err">{error}</p>}

      {!latest && !loading && (
        <p className="py-4 text-[12px] leading-relaxed text-dim">
          还没有快照。点「立即扫描」生成第一份技术债报告，之后每周自动更新，趋势会显示债的变化方向。
        </p>
      )}

      {latest && (
        <>
          <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wide text-dim">债务分</p>
              <p className="mt-1 flex items-baseline gap-2 text-[20px] font-semibold tabular-nums">
                {latest.score}
                <Badge tone={scoreTone(latest.score)}>{scoreLabel(latest.score)}</Badge>
              </p>
              {delta !== null && (
                <p className={`mt-0.5 text-[10px] ${delta > 0 ? 'text-err' : 'text-ok'}`}>
                  较上次 {delta > 0 ? '+' : ''}{delta}
                </p>
              )}
            </div>
            <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wide text-dim">文件 / 测试文件</p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums">
                {latest.metrics.file_count ?? 0}
                <span className="text-[11px] font-normal text-dim"> / {latest.metrics.test_file_count ?? 0}</span>
              </p>
            </div>
            <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wide text-dim">超长函数</p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums">
                {latest.metrics.long_function_count ?? 0}
                <span className="text-[11px] font-normal text-dim"> / {latest.metrics.symbol_count ?? 0} 函数</span>
              </p>
            </div>
            <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wide text-dim">TODO/FIXME 文件</p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums">{latest.metrics.todo_chunk_count ?? 0}</p>
            </div>
            <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wide text-dim">巨型文件</p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums">{latest.metrics.huge_files?.length ?? 0}</p>
            </div>
            <div className="rounded-lg border border-edge/80 bg-base/40 px-3 py-2.5">
              <p className="text-[10px] uppercase tracking-wide text-dim">测试占比</p>
              <p className="mt-1 text-[18px] font-semibold tabular-nums">
                {Math.round((latest.metrics.test_ratio ?? 0) * 100)}%
              </p>
            </div>
          </div>

          {history.length > 1 && (
            <div className="mb-3 rounded-lg border border-edge/80 bg-base/40 p-3">
              <p className="mb-2 text-[11px] text-dim">趋势（每次快照的债务分）</p>
              <div className="flex h-16 items-end gap-1.5">
                {history.map((snap, i) => (
                  <div key={i} className="flex-1" title={`${snap.score} · ${snap.created_at ?? ''}`}>
                    <div
                      className={`w-full rounded-t ${scoreTone(snap.score) === 'err' ? 'bg-err/70' : scoreTone(snap.score) === 'warn' ? 'bg-warn/70' : 'bg-ok/70'}`}
                      style={{ height: `${Math.max(6, (snap.score / maxScore) * 60)}px` }}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-2">
            {(latest.metrics.long_functions?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-edge/80 bg-base/40 p-3">
                <p className="mb-1.5 text-[11.5px] font-medium">最长的函数（行数）</p>
                <ul className="space-y-1 text-[11.5px] text-dim">
                  {latest.metrics.long_functions!.map((f, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span className="truncate font-mono text-[10.5px]">{f.name}</span>
                      <span className="tabular-nums">{f.lines}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(latest.metrics.huge_files?.length ?? 0) > 0 && (
              <div className="rounded-lg border border-edge/80 bg-base/40 p-3">
                <p className="mb-1.5 text-[11.5px] font-medium">巨型文件（&gt;800 行）</p>
                <ul className="space-y-1 text-[11.5px] text-dim">
                  {latest.metrics.huge_files!.map((f, i) => (
                    <li key={i} className="flex justify-between gap-2">
                      <span className="truncate font-mono text-[10.5px]">{f.path}</span>
                      <span className="tabular-nums">{f.lines}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <p className="mt-3 text-[10px] leading-relaxed text-dim/60">
            债务分 = 超长函数 40% + TODO 密度 25% + 测试缺口 25% + 巨型文件 10%，全部由索引表确定性计算，可复现。
          </p>
        </>
      )}
    </div>
  )
}
