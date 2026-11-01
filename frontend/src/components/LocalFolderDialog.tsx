import { FolderOpen } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { Repo } from '../lib/types'
import { inputClass } from '../lib/ui'
import { Button, Modal, Spinner } from './common'

export function LocalFolderDialog({
  open,
  onClose,
  onOpened,
}: {
  open: boolean
  onClose: () => void
  onOpened: (repo: Repo) => void
}) {
  const [path, setPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setPath('')
      setError(null)
    }
  }, [open])

  const submit = async () => {
    if (!path.trim()) {
      setError('请填写项目文件夹的绝对路径')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const repo = await api.repos.localFolder(path.trim())
      onOpened(repo)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '打开失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="打开本地文件夹">
      <div className="space-y-3">
        <p className="text-sm leading-relaxed text-dim">
          输入本机项目目录的绝对路径。Nova 原地读取并建立索引，不复制文件；
          删除项目只取消登记，不会删除磁盘内容。<span className="text-warn">执行无容器隔离。</span>
        </p>
        <label className="block space-y-1">
          <span className="text-xs text-dim">绝对路径</span>
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder={'D:\\code\\my-project'}
            className={inputClass}
          />
        </label>
        {error && <p className="text-sm text-err">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button size="sm" onClick={onClose} disabled={busy}>取消</Button>
          <Button size="sm" variant="primary" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : <FolderOpen size={12} />} 打开并索引
          </Button>
        </div>
      </div>
    </Modal>
  )
}
