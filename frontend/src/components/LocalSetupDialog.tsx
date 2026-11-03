import { FolderOpen, KeyRound, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useFocusTrap } from '../lib/focus'
import type { LocalSetupStatus } from '../lib/types'
import { inputClass } from '../lib/ui'
import { ModeBadge } from '../shell/ModeBadge'
import { Button, Spinner } from './common'

export function LocalSetupDialog({
  open,
  status,
  onClose,
  onDone,
}: {
  open: boolean
  status: LocalSetupStatus | null
  onClose: () => void
  onDone: (status: LocalSetupStatus) => void
}) {
  const [path, setPath] = useState('')
  const [provider, setProvider] = useState('zhipu')
  const [model, setModel] = useState('glm-4.7-flash')
  const [apiKey, setApiKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  // 桌面壳才有原生选择器；浏览器/服务器模式回退为手动输入路径。
  const canBrowse = typeof window !== 'undefined' && !!window.novaDesktop?.pickDirectory

  useEffect(() => {
    if (!open) return
    setProvider(status?.default_provider || 'zhipu')
    setModel(status?.default_model || 'glm-4.7-flash')
    setApiKey('')
    setError(null)
  }, [open, status?.default_provider, status?.default_model])

  useFocusTrap(panelRef, open)

  const browse = async () => {
    const bridge = window.novaDesktop?.pickDirectory
    if (!bridge) return
    try {
      const picked = await bridge()
      if (picked.ok && picked.path) {
        setPath(picked.path)
        setError(null)
      }
    } catch {
      setError('打开文件夹选择器失败，请手动粘贴绝对路径')
    }
  }

  const submit = async () => {
    if (!path.trim()) {
      setError('请填写项目文件夹的绝对路径')
      return
    }
    if (!status?.has_llm_key && !apiKey.trim()) {
      setError('首次启动请填写 API Key')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await api.local.setup({
        project_path: path.trim(),
        provider: provider.trim() || 'zhipu',
        model: model.trim() || 'glm-4.7-flash',
        api_key: apiKey.trim() || null,
      })
      onDone({
        configured: true,
        data_dir: status?.data_dir ?? '',
        project_count: (status?.project_count ?? 0) + 1,
        has_llm_key: true,
        default_provider: result.provider,
        default_model: result.model,
      })
      setPath('')
      setApiKey('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="local-setup-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="flex w-full max-w-lg flex-col overflow-hidden rounded-lg border border-edge bg-panel shadow-pop outline-none"
      >
        <header className="flex items-center gap-2 border-b border-edge px-4 py-3">
          <ModeBadge />
          <h3 id="local-setup-title" className="min-w-0 flex-1 truncate text-md font-semibold">
            首次启动：连接你的项目与模型
          </h3>
          <button
            onClick={onClose}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
            title="关闭 · Esc"
            aria-label="关闭首次启动向导"
          >
            <X size={14} />
          </button>
        </header>

        <div className="space-y-3 overflow-y-auto p-4">
          <p className="text-xs leading-relaxed text-dim">
            选择本机上的项目文件夹。Nova 只读取该目录并在本机建立索引，不会复制或上传代码；
            <span className="text-warn"> 本地执行无容器隔离</span>。
          </p>
          {status?.data_dir && (
            <p className="break-all font-mono text-2xs text-faint">
              数据目录：{status.data_dir}
            </p>
          )}
          <div className="space-y-1">
            <label htmlFor="local-setup-path" className="block text-xs text-dim">
              项目文件夹（绝对路径）
            </label>
            <div className="flex gap-2">
              <input
                id="local-setup-path"
                value={path}
                onChange={(event) => setPath(event.target.value)}
                placeholder={'D:\\code\\my-project'}
                className={`${inputClass} min-w-0 flex-1`}
              />
              {canBrowse && (
                <Button size="sm" onClick={() => void browse()} className="shrink-0">
                  <FolderOpen size={12} /> 选择文件夹
                </Button>
              )}
            </div>
            <span className="text-2xs text-faint">
              {canBrowse
                ? '可以直接选择文件夹，也可以粘贴绝对路径。'
                : '浏览器模式无法打开原生选择器；请粘贴项目文件夹的绝对路径。'}
            </span>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="text-xs text-dim">模型厂商</span>
              <input
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                placeholder="zhipu"
                className={inputClass}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-dim">模型</span>
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="glm-4.7-flash"
                className={inputClass}
              />
            </label>
          </div>
          <label className="block space-y-1">
            <span className="flex items-center gap-1 text-xs text-dim">
              <KeyRound size={11} /> API Key
            </span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={status?.has_llm_key ? '已保存；留空保持不变' : '首次启动必填'}
              autoComplete="off"
              className={inputClass}
            />
            <span className="text-2xs text-faint">
              Key 仅加密保存在本机，不会写入日志或返回给前端。
            </span>
          </label>
          {error && <p className="text-xs text-err" role="alert">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" onClick={onClose} disabled={busy}>稍后</Button>
            <Button size="sm" variant="primary" onClick={() => void submit()} disabled={busy}>
              {busy ? <Spinner /> : <FolderOpen size={12} />} 保存并打开项目
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
