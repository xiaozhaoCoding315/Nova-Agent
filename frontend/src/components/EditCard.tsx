import clsx from 'clsx'
import {
  CheckCircle2, ChevronDown, ChevronRight, FileCode2, RotateCcw, ShieldCheck, XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { EditRecord, EditRef } from '../lib/types'
import { Badge, Button, Spinner } from './common'
import { DiffView } from './DiffView'
import { ReviewPanel } from './ReviewPanel'

const STATUS: Record<string, { label: string; tone: 'warn' | 'ok' | 'dim' | 'err' }> = {
  pending: { label: '待批准', tone: 'warn' },
  applied: { label: '已应用', tone: 'ok' },
  rejected: { label: '已拒绝', tone: 'dim' },
  reverted: { label: '已撤销', tone: 'dim' },
}

export function EditCard({ edit }: { edit: EditRef }) {
  const [record, setRecord] = useState<EditRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorRetry, setErrorRetry] = useState<string | null>(null)
  const [showDiff, setShowDiff] = useState(false)

  const load = async () => {
    try {
      setRecord(await api.edits.get(edit.id))
      setError(null)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setErrorRetry(err.message)
      } else {
        setError(err instanceof ApiError ? err.message : '加载修改详情失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edit.id])

  const act = async (kind: 'approve' | 'reject' | 'revert') => {
    setBusy(true)
    setError(null)
    try {
      if (kind === 'approve') await api.edits.approve(edit.id)
      else if (kind === 'reject') await api.edits.reject(edit.id)
      else await api.edits.revert(edit.id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const runReview = async () => {
    setReviewing(true)
    setError(null)
    try {
      await api.edits.review(edit.id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '审查失败')
    } finally {
      setReviewing(false)
    }
  }

  const status = record?.status ?? edit.status ?? 'pending'
  const meta = STATUS[status] ?? { label: status, tone: 'dim' as const }
  const files = record?.file_paths ?? edit.files

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-accentSoft/60 bg-panel">
      <div className="flex items-center gap-2 border-b border-edge px-3 py-2">
        <FileCode2 size={13} className="text-accent" />
        <span className="text-[12.5px] font-medium">代码修改提案</span>
        <span className="text-[11px] text-dim">{files.length} 个文件</span>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        {loading && <Spinner />}
        <div className="ml-auto flex items-center gap-2">
          <button
            className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-[11px] text-dim hover:text-ink disabled:opacity-50"
            onClick={() => void runReview()}
            disabled={reviewing}
            title="只读审查当前 diff，不会修改文件"
          >
            {reviewing ? <Spinner /> : <ShieldCheck size={11} />} 审查
          </button>
          {record?.repo_name && <span className="text-[11px] text-dim">{record.repo_name}</span>}
        </div>
      </div>

      <div className="px-3 py-2">
        {files.length > 0 && (
          <ul className="space-y-0.5 font-mono text-[11.5px] text-dim">
            {files.map((path) => (
              <li key={path}>· {path}</li>
            ))}
          </ul>
        )}
        {record?.note && <p className="mt-1 text-[12px] text-dim">{record.note}</p>}

        {(record?.diff || edit.diff) && (
          <div className="mt-2">
            <button
              className="flex items-center gap-1 text-[11.5px] text-dim hover:text-ink"
              onClick={() => setShowDiff(!showDiff)}
            >
              {showDiff ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              查看 diff
            </button>
            {showDiff && (
              <div className="mt-1.5">
                <DiffView diff={record?.diff ?? edit.diff ?? ''} maxHeight="max-h-72" />
              </div>
            )}
          </div>
        )}

        <ReviewPanel review={record?.review} />

        {error && <p className="mt-2 text-[12px] text-err">{error}</p>}
        {errorRetry && <p className="mt-2 text-[12px] text-warn">{errorRetry}</p>}

        {status === 'pending' && (
          <div className="mt-2 flex items-center gap-2">
            <Button variant="primary" size="sm" onClick={() => void act('approve')} disabled={busy}>
              {busy ? <Spinner /> : <CheckCircle2 size={12} />} 批准修改
            </Button>
            <Button variant="danger" size="sm" onClick={() => void act('reject')} disabled={busy}>
              <XCircle size={12} /> 拒绝
            </Button>
            <span className="text-[11px] text-dim">批准后写入磁盘并重建索引</span>
          </div>
        )}

        {status === 'applied' && (
          <div className="mt-2 flex items-center gap-2">
            <Button size="sm" onClick={() => void act('revert')} disabled={busy}>
              {busy ? <Spinner /> : <RotateCcw size={12} />} 撤销这次修改
            </Button>
            <span className="text-[11px] text-dim">使用写入前快照恢复</span>
          </div>
        )}

        {status === 'reverted' && (
          <p className={clsx('mt-2 text-[11.5px] text-dim')}>已使用快照恢复到修改前的内容。</p>
        )}
        {status === 'rejected' && <p className="mt-2 text-[11.5px] text-dim">该提案已被拒绝，未写入磁盘。</p>}
      </div>
    </div>
  )
}