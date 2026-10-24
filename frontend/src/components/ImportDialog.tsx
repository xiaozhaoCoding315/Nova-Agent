import { FileArchive, FolderUp, GitBranch, UploadCloud } from 'lucide-react'
import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import JSZip from 'jszip'
import { ApiError } from '../lib/api'
import { useRepos } from '../stores/repos'
import { Button, Modal, Spinner } from './common'

const FOLDER_IGNORE = [
  'node_modules/', '.git/', 'dist/', 'build/', '.next/', '__pycache__/',
  '.venv/', 'venv/', '.idea/', '.vscode/', 'target/',
]
const MAX_FILE_BYTES = 4 * 1024 * 1024
const MAX_FILES = 2000

function isTextLike(path: string): boolean {
  const lower = path.toLowerCase()
  if (/\.(png|jpe?g|gif|webp|ico|svgz|zip|gz|tar|rar|7z|exe|dll|so|dylib|bin|wasm|pdf|mp4|mp3|woff2?|ttf|eot|class|jar|pyc|lock)$/.test(lower)) {
    return false
  }
  return true
}

function commonRoot(paths: string[]): string {
  if (paths.length === 0) return ''
  const first = paths[0].split('/')
  let prefix = first.slice(0, -1)
  for (const p of paths.slice(1, 50)) {
    const parts = p.split('/')
    const keep: string[] = []
    for (let i = 0; i < Math.min(prefix.length, parts.length - 1); i++) {
      if (prefix[i] === parts[i]) keep.push(prefix[i])
      else break
    }
    prefix = keep
    if (prefix.length === 0) break
  }
  return prefix.length ? prefix.join('/') + '/' : ''
}

async function zipDirectory(fileList: FileList): Promise<Blob> {
  const zip = new JSZip()
  let count = 0
  const paths: string[] = []
  for (const file of Array.from(fileList)) {
    const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    paths.push(rel)
  }
  const root = commonRoot(paths)
  for (const file of Array.from(fileList)) {
    const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
    const path = root && rel.startsWith(root) ? rel.slice(root.length) : rel
    if (!path || path.endsWith('/')) continue
    if (FOLDER_IGNORE.some((seg) => path.includes(seg) || rel.includes(seg))) continue
    if (!isTextLike(path) || file.size > MAX_FILE_BYTES) continue
    if (count >= MAX_FILES) break
    zip.file(path, file)
    count += 1
  }
  if (count === 0) throw new Error('所选文件夹里没有可导入的文本代码文件（已跳过二进制与依赖目录）')
  return zip.generateAsync({ type: 'blob', compression: 'DEFLATE' })
}

/** 直接从对话里导入：单个 zip 直接传；多文件（拖入的文件夹内容）浏览器内打包后传。 */
export async function importDroppedFiles(files: FileList): Promise<void> {
  const list = Array.from(files)
  if (list.length === 0) throw new Error('未识别到可导入的文件')
  if (list.length === 1 && list[0].name.toLowerCase().endsWith('.zip')) {
    await useRepos.getState().uploadZip(list[0])
    return
  }
  const blob = await zipDirectory(files)
  const name = (list[0] as File & { webkitRelativePath?: string }).webkitRelativePath?.split('/')[0] || list[0].name || 'local-folder'
  await useRepos.getState().uploadZip(new File([blob], `${name}.zip`, { type: 'application/zip' }))
}

export function ImportDialog({
  open,
  onClose,
  onImported,
}: {
  open: boolean
  onClose: () => void
  onImported: (repoId: string) => void
}) {
  const [tab, setTab] = useState<'zip' | 'folder' | 'git'>('folder')
  const [gitUrl, setGitUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [folderInfo, setFolderInfo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const folderInput = useRef<HTMLInputElement>(null)
  const { uploadZip, importGit } = useRepos()

  const reset = () => {
    setBusy(false)
    setError(null)
    setGitUrl('')
    setFolderInfo(null)
  }

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setError('请上传 .zip 压缩包（文件夹请用「上传文件夹」，公开项目可用 Git URL）')
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

  const handleFolder = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    setBusy(true)
    setError(null)
    setFolderInfo(`正在打包 ${fileList.length} 个文件…`)
    try {
      const blob = await zipDirectory(fileList)
      const name = (fileList[0] as File & { webkitRelativePath?: string }).webkitRelativePath?.split('/')[0] || 'local-folder'
      setFolderInfo('正在上传…')
      await uploadZip(new File([blob], `${name}.zip`, { type: 'application/zip' }))
      reset()
      onClose()
      onImported('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '文件夹导入失败')
      setBusy(false)
      setFolderInfo(null)
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

  const tabs: { key: 'folder' | 'zip' | 'git'; label: string; icon: typeof FolderUp }[] = [
    { key: 'folder', label: '上传文件夹', icon: FolderUp },
    { key: 'zip', label: '上传 ZIP', icon: FileArchive },
    { key: 'git', label: 'Git URL', icon: GitBranch },
  ]

  return (
    <Modal open={open} onClose={onClose} title="导入项目">
      <div className="mb-4 flex gap-1 rounded-lg border border-edge bg-raised p-1">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] ${
              tab === key ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink'
            }`}
            onClick={() => setTab(key)}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === 'folder' ? (
        <div
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
            dragOver ? 'border-accent bg-accentSoft/20' : 'border-edge hover:border-accentSoft'
          }`}
          onClick={() => folderInput.current?.click()}
        >
          <FolderUp size={26} className="text-accent" />
          <p className="text-[13.5px]">点击选择你的项目文件夹</p>
          <p className="text-[12px] leading-relaxed text-dim">
            自动跳过 node_modules / .git / 构建产物与二进制文件，浏览器内打包后上传；
            单文件 ≤ 4MB，最多 {MAX_FILES} 个
          </p>
          <input
            ref={(el) => {
              (folderInput as { current: HTMLInputElement | null }).current = el
              el?.setAttribute('webkitdirectory', '')
              el?.setAttribute('directory', '')
            }}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => void handleFolder(e.target.files)}
          />
        </div>
      ) : tab === 'zip' ? (
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
            placeholder="https://github.com/user/repo（公开项目）"
            className="w-full rounded-lg border border-edge bg-raised px-3 py-2 font-mono text-[13px] outline-none placeholder:text-dim/60 focus:border-accentSoft"
          />
          <p className="text-[12px] text-dim">服务端会浅克隆该公开项目，项目较大时请耐心等待。</p>
          <Button variant="primary" onClick={() => void handleGit()} disabled={busy || !gitUrl.trim()}>
            {busy ? <Spinner /> : <GitBranch size={13} />} 开始导入
          </Button>
        </div>
      )}

      {busy && (tab === 'zip' || tab === 'folder') && (
        <p className="mt-3 flex items-center gap-2 text-[12.5px] text-dim">
          <Spinner /> {folderInfo ?? '上传中…'}
        </p>
      )}
      {error && <p className="mt-3 text-[12.5px] text-err">{error}</p>}
    </Modal>
  )
}
