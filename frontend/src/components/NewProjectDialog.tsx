import { Sparkles } from 'lucide-react'
import { useState } from 'react'
import { ApiError } from '../lib/api'
import { useRepos } from '../stores/repos'
import { Button, Modal, Spinner } from './common'

export function NewProjectDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (repoId: string) => void
}) {
  const [name, setName] = useState('')
  const [requirements, setRequirements] = useState('')
  const [rules, setRules] = useState('')
  const [stack, setStack] = useState<'python' | 'fullstack'>('python')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { createBuilder } = useRepos()

  const reset = () => {
    setName('')
    setRequirements('')
    setRules('')
    setStack('python')
    setBusy(false)
    setError(null)
  }

  const submit = async () => {
    if (!name.trim() || requirements.trim().length < 10) return
    setBusy(true)
    setError(null)
    try {
      const repo = await createBuilder(name.trim(), requirements.trim(), rules.trim() || undefined, stack)
      reset()
      onClose()
      onCreated(repo.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建项目失败')
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={() => { if (!busy) { reset(); onClose() } }} title="新建项目（从 0→1）" width="max-w-xl">
      <div className="space-y-3">
        <p className="text-[12px] leading-relaxed text-dim">
          Nova 会先给出结构化方案（技术栈 / 目录 / 数据模型 / API / 里程碑），你确认后生成完整项目文件；代码以提案形式展示，批准后才会写入工作区并建立索引。
          Python 模板生成 FastAPI 后端；全栈模板先生成 OpenAPI 契约，再生成 FastAPI 后端与 TypeScript 前端，并通过双栈 Gate。
        </p>
        <div>
          <label className="mb-1 block text-[12px] text-dim">项目模板</label>
          <div className="flex gap-2">
            {([
              ['python', 'Python 后端', 'FastAPI + SQLite + pytest'],
              ['fullstack', '全栈契约', 'OpenAPI + FastAPI + TS 前端'],
            ] as const).map(([key, label, hint]) => (
              <button
                key={key}
                type="button"
                onClick={() => setStack(key)}
                className={`flex-1 rounded-lg border px-3 py-2 text-left ${stack === key ? 'border-accent bg-accentSoft/25' : 'border-edge hover:border-accentSoft'}`}
              >
                <p className="text-[12.5px] font-medium">{label}</p>
                <p className="mt-0.5 text-[10.5px] text-dim">{hint}</p>
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[12px] text-dim">项目名称</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="例如：todo-api"
            className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none focus:border-accentSoft"
          />
        </div>
        <div>
          <label className="mb-1 block text-[12px] text-dim">需求描述</label>
          <textarea
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
            rows={6}
            placeholder={'描述要做什么、给谁用、核心功能与约束。\n例如：一个待办清单 API，支持创建/完成/删除任务，按状态过滤，SQLite 持久化，带 pytest 测试。'}
            className="w-full resize-y rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none placeholder:text-dim/50 focus:border-accentSoft"
          />
        </div>
        <div>
          <label className="mb-1 block text-[12px] text-dim">项目约定 / 规则（可选，会写入 AGENTS.md 并影响后续对话）</label>
          <textarea
            value={rules}
            onChange={(e) => setRules(e.target.value)}
            rows={3}
            placeholder="例如：接口统一返回 {code, data, message}；错误用 HTTPException；命名用 snake_case。"
            className="w-full resize-y rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none placeholder:text-dim/50 focus:border-accentSoft"
          />
        </div>
        {error && <p className="text-[12.5px] text-err">{error}</p>}
        <Button
          variant="primary"
          className="w-full"
          onClick={() => void submit()}
          disabled={busy || !name.trim() || requirements.trim().length < 10}
        >
          {busy ? <Spinner /> : <Sparkles size={13} />} 生成方案
        </Button>
      </div>
    </Modal>
  )
}