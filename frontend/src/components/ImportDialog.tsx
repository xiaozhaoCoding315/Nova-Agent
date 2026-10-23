import { FileArchive, GitBranch, UploadCloud } from 'lucide-react'
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { ApiError } from '../lib/api'
import { useRepos } from '../stores/repos'
import { Button, Modal, Spinner } from './common'

export function ImportDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean
  onClose: () => void
  onImported: (repoId: string) => void
}) {
  const [tab, setTab] = useState<'zip' | 'git'>('zip')
  const [gitUrl, setGitUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const { uploadZip, importGit } = useRepos()

  const reset = () => {
    setBusy(false)
    setError(null)
    setGitUrl('')
  }

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setError('请上传 .zip 压缩包（git 仓库请用 Git URL 导入）')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await uploadZip(file)
      reset()
      onClose()
      onImported('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败')
      setBusy(false)
    }
  }

  const handleGit = async () => {
    if (!gitUrl.trim()) return
    setBusy(true)
    setError(null)
    try {
      await importGit(gitUrl.trim())
      reset()
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导入失败')
      setBusy(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void handleFile(e.dataTransfer.files?.[0])
  }

  return (
    <Modal open={open} onClose={onClose} title="导入工作区">
      <div className="mb-4 flex gap-1 rounded-lg border border-edge bg-raised p-1">
        <button
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] ${
            tab === 'zip' ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink'
          }`}
          onClick={() => setTab('zip')}
        >
          <FileArchive size={14} /> 上传 ZIP
        </button>
        <button
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] ${
            tab === 'git' ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink'
          }`}
          onClick={() => setTab('git')}
        >
          <GitBranch size={14} /> Git URL
        </button>
      </div>

      {tab === 'zip' ? (
        <div
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
            dragOver ? 'border-accent bg-accentSoft/20' : 'border-edge hover:border-accentSoft'
          }`}
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <UploadCloud size={26} className="text-accent" />
          <p className="text-[13.5px]">拖拽 zip 到此处，或点击选择文件</p>
          <p className="text-[12px] text-dim">支持代码 / Markdown / 文本；自动跳过 node_modules、构建产物与二进制文件</p>
          <input
            ref={fileInput}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={(e) => void handleFile(e.target.files?.[0] ?? undefined)}
          />
        </div>
      ) : (
        <div className="space-y-2">
          <input
            value={gitUrl}
            onChange={(e) => setGitUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void handleGit()}
            placeholder="https://github.com/user/repo（仅公开仓库）"
            className="w-full rounded-lg border border-edge bg-raised px-3 py-2 font-mono text-[13px] outline-none placeholder:text-dim/60 focus:border-accentSoft"
          />
          <p className="text-[12px] text-dim">服务端会执行 git clone --depth 1（浅克隆），仓库较大时请耐心等待。</p>
          <Button variant="primary" onClick={() => void handleGit()} disabled={busy || !gitUrl.trim()}>
            {busy ? <Spinner /> : <GitBranch size={13} />} 开始导入
          </Button>
        </div>
      )}

      {busy && tab === 'zip' && (
        <p className="mt-3 flex items-center gap-2 text-[12.5px] text-dim">
          <Spinner /> 上传中…
        </p>
      )}
      {error && <p className="mt-3 text-[12.5px] text-err">{error}</p>}
    </Modal>
  )
}