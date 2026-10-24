import { Download, FileText, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { FileList } from '../lib/types'
import { Badge, Button, Modal, Spinner } from './common'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function FilesPanel() {
  const [data, setData] = useState<FileList | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      setData(await api.files.list())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载文件失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const upload = async (file: File) => {
    setUploading(true)
    setError(null)
    try {
      await api.files.upload(file, { purpose: 'artifact' })
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const remove = async () => {
    if (!deleteId) return
    try {
      await api.files.remove(deleteId)
      setDeleteId(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const usedPct = data && data.limit_bytes > 0
    ? Math.min(100, Math.round((data.used_bytes / data.limit_bytes) * 100))
    : 0

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="flex flex-wrap items-center gap-2">
          <FileText size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">个人文件库</h3>
          {data && (
            <Badge tone={usedPct >= 90 ? 'err' : usedPct >= 70 ? 'warn' : 'dim'}>
              {formatBytes(data.used_bytes)} / {formatBytes(data.limit_bytes)}
            </Badge>
          )}
          <div className="ml-auto flex gap-1.5">
            <input
              ref={inputRef}
              type="file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void upload(file)
                event.target.value = ''
              }}
            />
            <Button size="sm" onClick={() => inputRef.current?.click()} disabled={uploading}>
              {uploading ? <Spinner /> : <Upload size={12} />} 上传
            </Button>
            <Button size="sm" onClick={() => void load()} disabled={loading}>
              {loading ? <Spinner /> : <RefreshCw size={12} />} 刷新
            </Button>
          </div>
        </div>

        {data && data.limit_bytes > 0 && (
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-raised">
            <div
              className={`h-full rounded-full ${usedPct >= 90 ? 'bg-err' : usedPct >= 70 ? 'bg-warn' : 'bg-accent'}`}
              style={{ width: `${usedPct}%` }}
            />
          </div>
        )}
        <p className="mt-2 text-[10.5px] leading-relaxed text-dim/70">
          聊天附件和手动上传都会进入个人文件库；文件仅自己可见，计入个人存储配额。
        </p>
        {error && <p className="mt-2 text-[11.5px] text-err">{error}</p>}
      </section>

      <section className="rounded-xl border border-edge bg-panel">
        {!data || data.files.length === 0 ? (
          <p className="px-4 py-6 text-[12px] text-dim">
            {loading ? '加载中…' : '还没有文件。在对话里点击回形针上传，或在这里手动上传。'}
          </p>
        ) : (
          <div className="divide-y divide-edge/60">
            {data.files.map((file) => (
              <div key={file.id} className="flex items-center gap-2 px-4 py-2.5">
                <FileText size={13} className="shrink-0 text-dim" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] text-ink" title={file.filename}>{file.filename}</p>
                  <p className="text-[10px] text-dim">
                    {formatBytes(file.size)} · {file.mime}
                    {file.created_at ? ` · ${new Date(file.created_at).toLocaleString()}` : ''}
                  </p>
                </div>
                <a
                  href={api.files.downloadUrl(file.id)}
                  className="rounded p-1 text-dim hover:bg-raised hover:text-ink"
                  title="下载"
                >
                  <Download size={13} />
                </a>
                <button
                  onClick={() => setDeleteId(file.id)}
                  className="rounded p-1 text-dim hover:bg-err/10 hover:text-err"
                  title="删除"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      <Modal
        open={Boolean(deleteId)}
        onClose={() => setDeleteId(null)}
        title="删除文件"
        width="max-w-sm"
      >
        <p className="text-[12px] leading-relaxed text-dim">
          将删除文件数据。历史消息中的附件名称会保留，但无法再下载。确认删除？
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => setDeleteId(null)}>取消</Button>
          <Button size="sm" variant="danger" onClick={() => void remove()}>确认删除</Button>
        </div>
      </Modal>
    </div>
  )
}
