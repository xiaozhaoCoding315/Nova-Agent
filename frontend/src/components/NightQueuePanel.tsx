import { Moon, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { ChangeListItem, NightItem, Repo } from '../lib/types'
import { Badge, Button, Spinner } from './common'

const inputClass =
  'w-full rounded-lg border border-edge bg-base/60 px-3 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-accent/60'

const STATUS_LABEL: Record<NightItem['status'], string> = {
  pending: '排队中',
  running: '执行中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const STATUS_TONE: Record<NightItem['status'], 'ok' | 'warn' | 'err' | 'accent' | 'dim'> = {
  pending: 'dim',
  running: 'warn',
  done: 'ok',
  failed: 'err',
  cancelled: 'dim',
}

const NIGHT_HINT = '夜间窗口内由维护任务逐个执行（默认 0:00–8:00，可在 .env 调整）；只跑流水线，写入仍需早上人工批准。'

export function NightQueuePanel({ repos }: { repos: Repo[] }) {
  const [items, setItems] = useState<NightItem[]>([])
  const [changes, setChanges] = useState<ChangeListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [mode, setMode] = useState<'change' | 'task'>('change')
  const [changeId, setChangeId] = useState('')
  const [repoId, setRepoId] = useState('')
  const [bugReport, setBugReport] = useState('')
  const [busy, setBusy] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [queue, changeList] = await Promise.all([
        api.night.list(),
        api.changes.list().catch(() => [] as ChangeListItem[]),
      ])
      setItems(queue)
      setChanges(changeList)
      const executable = changeList.filter((c) => c.status === 'plan_approved')
      setChangeId((current) => current || executable[0]?.id || '')
      setRepoId((current) => current || repos.find((r) => r.status === 'ready')?.id || '')
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载夜间队列失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const add = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (mode === 'change') {
        await api.night.add({ kind: 'change_execute', change_id: changeId })
        setNotice('已排入夜间执行')
      } else {
        await api.night.add({ kind: 'task', repo_id: repoId, bug_report: bugReport })
        setBugReport('')
        setNotice('修复任务已排入夜间执行')
      }
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加入队列失败')
    } finally {
      setBusy(false)
    }
  }

  const cancel = async (id: string) => {
    try {
      await api.night.cancel(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '取消失败')
    }
  }

  const executable = changes.filter((c) => c.status === 'plan_approved')
  const readyRepos = repos.filter((r) => r.status === 'ready')
  const canAdd = mode === 'change' ? Boolean(changeId) : Boolean(repoId && bugReport.trim())

  return (
    <section className="rounded-xl border border-edge bg-panel p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Moon size={14} className="text-accent" />
        <h3 className="text-[13px] font-medium">夜间队列</h3>
        <span className="text-[10.5px] text-dim">睡前排队，早上看证据报告</span>
        <Button size="sm" className="ml-auto" onClick={() => void load()} disabled={loading}>
          {loading ? <Spinner /> : <RefreshCw size={12} />} 刷新
        </Button>
      </div>
      <p className="mb-3 text-[10.5px] leading-relaxed text-dim/70">{NIGHT_HINT}</p>

      <div className="mb-2 flex gap-1">
        {(['change', 'task'] as const).map((key) => (
          <button
            key={key}
            onClick={() => setMode(key)}
            className={`rounded-md px-2.5 py-1 text-[11.5px] transition-colors ${
              mode === key ? 'bg-accentSoft/45 text-ink' : 'text-dim hover:text-ink'
            }`}
          >
            {key === 'change' ? '排队已批准的变更' : '排队修复任务'}
          </button>
        ))}
      </div>
      {mode === 'change' ? (
        executable.length > 0 ? (
          <select value={changeId} onChange={(e) => setChangeId(e.target.value)} className={inputClass}>
            {executable.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}（{c.repo_name}）
              </option>
            ))}
          </select>
        ) : (
          <p className="text-[11.5px] text-dim">没有「计划已批准」的变更。先在工作流里完成 SPEC → 计划 → 批准计划。</p>
        )
      ) : (
        <div className="space-y-2">
          <select value={repoId} onChange={(e) => setRepoId(e.target.value)} className={inputClass}>
            <option value="">选择仓库…</option>
            {readyRepos.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
          <textarea
            value={bugReport}
            onChange={(e) => setBugReport(e.target.value)}
            placeholder="Bug 描述：预期行为 / 实际行为 / 复现步骤"
            className={`${inputClass} min-h-[64px] resize-y`}
          />
        </div>
      )}
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant="primary" onClick={() => void add()} disabled={busy || !canAdd}>
          {busy ? <Spinner /> : <Plus size={12} />} 排入夜间
        </Button>
      </div>

      {error && <p className="mt-2 text-[11.5px] text-err">{error}</p>}
      {notice && <p className="mt-2 text-[11.5px] text-ok">{notice}</p>}

      {items.length > 0 && (
        <table className="mt-3 w-full border-collapse text-[11.5px]">
          <thead>
            <tr className="border-b border-edge text-left text-dim">
              <th className="py-1.5 pr-2 font-medium">条目</th>
              <th className="px-2 py-1.5 font-medium">状态</th>
              <th className="px-2 py-1.5 font-medium">时间</th>
              <th className="px-2 py-1.5 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} className="border-b border-edge/50 align-top">
                <td className="py-2 pr-2">
                  <p className="text-ink">{item.title || '(无标题)'}</p>
                  <p className="text-[10px] text-dim/70">
                    {item.kind === 'change_execute' ? '变更执行' : '修复任务（红绿）'}
                    {item.error && <span className="text-err/80"> · {item.error}</span>}
                  </p>
                </td>
                <td className="px-2 py-2">
                  <Badge tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status] ?? item.status}</Badge>
                </td>
                <td className="px-2 py-2 text-[10.5px] text-dim">
                  {item.finished_at ?? item.started_at ?? item.created_at
                    ? new Date(item.finished_at ?? item.started_at ?? item.created_at!).toLocaleString()
                    : '—'}
                </td>
                <td className="px-2 py-2 text-right">
                  {item.status === 'pending' && (
                    <button
                      onClick={() => void cancel(item.id)}
                      className="rounded p-1 text-dim hover:bg-err/10 hover:text-err"
                      title="取消排队"
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
