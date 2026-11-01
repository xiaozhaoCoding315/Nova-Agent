import { FolderOpen, KeyRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { LocalSetupStatus } from '../lib/types'
import { Button, Modal, Spinner } from './common'

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

  useEffect(() => {
    if (!open) return
    setProvider(status?.default_provider || 'zhipu')
    setModel(status?.default_model || 'glm-4.7-flash')
    setApiKey('')
    setError(null)
  }, [open, status?.default_provider, status?.default_model])

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

  return (
    <Modal open={open} onClose={onClose} title="首次启动：连接你的项目与模型">
      <div className="space-y-3">
        <p className="text-[11.5px] leading-relaxed text-dim">
          选择本机上的项目文件夹。Nova 只读取该目录并在本机建立索引，不会复制或上传代码；
          <span className="text-warn"> 本地执行无容器隔离</span>。
        </p>
        {status?.data_dir && (
          <p className="break-all font-mono text-[10.5px] text-dim/70">
            数据目录：{status.data_dir}
          </p>
        )}
        <label className="block space-y-1">
          <span className="text-[11px] text-dim">项目文件夹（绝对路径）</span>
          <input
            value={path}
            onChange={(event) => setPath(event.target.value)}
            placeholder={'D:\\code\\my-project'}
            className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none transition-colors focus:border-accent/60"
          />
          <span className="text-[10px] text-dim/60">
            原生文件夹选择器将在后续桌面版提供；当前请粘贴绝对路径。
          </span>
        </label>
        <div className="grid gap-2 sm:grid-cols-2">
          <label className="block space-y-1">
            <span className="text-[11px] text-dim">模型厂商</span>
            <input
              value={provider}
              onChange={(event) => setProvider(event.target.value)}
              placeholder="zhipu"
              className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] text-dim">模型</span>
            <input
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder="glm-4.7-flash"
              className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
            />
          </label>
        </div>
        <label className="block space-y-1">
          <span className="flex items-center gap-1 text-[11px] text-dim">
            <KeyRound size={11} /> API Key
          </span>
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={status?.has_llm_key ? '已保存；留空保持不变' : '首次启动必填'}
            autoComplete="off"
            className="w-full rounded-lg border border-edge bg-base/60 px-2.5 py-1.5 text-[12px] text-ink outline-none focus:border-accent/60"
          />
          <span className="text-[10px] text-dim/60">
            Key 仅加密保存在本机，不会写入日志或返回给前端。
          </span>
        </label>
        {error && <p className="text-[11.5px] text-err">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <Button size="sm" onClick={onClose} disabled={busy}>稍后</Button>
          <Button size="sm" variant="primary" onClick={() => void submit()} disabled={busy}>
            {busy ? <Spinner /> : <FolderOpen size={12} />} 保存并打开项目
          </Button>
        </div>
      </div>
    </Modal>
  )
}
