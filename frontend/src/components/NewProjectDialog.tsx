import { ArrowUpRight, MessageSquare, Send, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { useRepos } from '../stores/repos'
import { Button, Modal, Spinner } from './common'

const SPEC_MARK = '[方案定稿]'

type DesignMessage = { role: 'user' | 'assistant'; content: string }

const OPENING: DesignMessage = {
  role: 'assistant',
  content: '你好！我来帮你把想法变成可生成的项目方案。先聊两句：这个项目是给谁用的？最核心要解决的一件事是什么？',
}

export function NewProjectDialog({
  open,
  onClose,
  onCreated,
  onStartImport,
}: {
  open: boolean
  onClose: () => void
  onCreated: (repoId: string) => void
  onStartImport?: () => void
}) {
  const [name, setName] = useState('')
  const [rules, setRules] = useState('')
  const [stack, setStack] = useState<'python' | 'fullstack'>('fullstack')
  const [messages, setMessages] = useState<DesignMessage[]>([OPENING])
  const [input, setInput] = useState('')
  const [thinking, setThinking] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const { createBuilder } = useRepos()

  let spec: string | null = null
  for (let i = messages.length - 1; i >= 1; i--) {
    const m = messages[i]
    if (m.role === 'assistant' && m.content.includes(SPEC_MARK)) {
      spec = m.content.slice(m.content.indexOf(SPEC_MARK) + SPEC_MARK.length).trim()
      break
    }
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, thinking])

  const send = async () => {
    const text = input.trim()
    if (!text || thinking || creating) return
    setInput('')
    setError(null)
    const next = [...messages, { role: 'user' as const, content: text }]
    setMessages(next)
    setThinking(true)
    try {
      // Send the real conversation (skip the local opening line).
      const { reply } = await api.repos.designChat(
        next.slice(1),
        stack,
      )
      setMessages([...next, { role: 'assistant', content: reply }])
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '设计对话失败，请重试')
    } finally {
      setThinking(false)
    }
  }

  const reset = () => {
    setName('')
    setRules('')
    setStack('fullstack')
    setMessages([OPENING])
    setInput('')
    setCreating(false)
    setError(null)
  }

  const submit = async () => {
    if (!name.trim() || !spec || spec.length < 20) return
    setCreating(true)
    setError(null)
    try {
      const repo = await createBuilder(name.trim(), spec, rules.trim() || undefined, stack)
      onClose()
      reset()
      onCreated(repo.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建项目失败')
      setCreating(false)
    }
  }

  return (
    <Modal open={open} onClose={() => { if (!thinking && !creating) onClose() }} title="新建项目 · 对话式设计" width="max-w-xl">
      <div className="space-y-3">
        <p className="text-[11.5px] leading-relaxed text-dim">
          和设计搭档聊几轮（目标用户、核心功能、数据模型…），聊够了它会给出「方案定稿」，确认后直接生成项目。已有现成代码？
          {onStartImport ? (
            <button className="ml-1 text-accent hover:underline" onClick={() => { onClose(); onStartImport() }}>导入文件夹 / ZIP →</button>
          ) : '可在左侧「项目」面板导入文件夹 / ZIP。'}
        </p>

        <div className="flex gap-2">
          {([
            ['python', 'Python 后端', 'FastAPI + SQLite + pytest'],
            ['fullstack', '全栈契约', 'OpenAPI + FastAPI + TS 前端'],
          ] as const).map(([key, label, hint]) => (
            <button
              key={key}
              type="button"
              onClick={() => setStack(key)}
              className={`flex-1 rounded-lg border px-3 py-2 text-left transition-colors ${stack === key ? 'border-accent bg-accentSoft/25' : 'border-edge hover:border-accentSoft'}`}
            >
              <p className="text-[12.5px] font-medium">{label}</p>
              <p className="mt-0.5 text-[10.5px] text-dim">{hint}</p>
            </button>
          ))}
        </div>

        <div ref={scrollRef} className="max-h-[44vh] min-h-[180px] space-y-2 overflow-y-auto rounded-lg border border-edge bg-base/50 p-3">
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[86%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-[12.5px] leading-relaxed ${
                  m.role === 'user'
                    ? 'rounded-br-md bg-accentSoft/55'
                    : 'rounded-bl-md border border-edge bg-panel'
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
          {thinking && (
            <div className="flex items-center gap-2 text-[12px] text-dim">
              <Spinner /> 设计搭档思考中…
            </div>
          )}
        </div>

        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), void send())}
            placeholder="描述你的想法，或回答上面的问题…"
            disabled={thinking || creating}
            className="flex-1 rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none placeholder:text-dim/60 focus:border-accentSoft disabled:opacity-60"
          />
          <Button variant="primary" onClick={() => void send()} disabled={thinking || creating || !input.trim()}>
            {thinking ? <Spinner /> : <Send size={13} />}
          </Button>
        </div>

        {spec && (
          <div className="rounded-lg border border-ok/40 bg-ok/5 p-3">
            <p className="flex items-center gap-1.5 text-[12px] font-medium text-ok">
              <MessageSquare size={12} /> 方案已定稿，预览：
            </p>
            <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-dim">
              {spec.slice(0, 600)}{spec.length > 600 ? '…' : ''}
            </p>
          </div>
        )}

        <div className="grid gap-2 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-[11.5px] text-dim">项目名称</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="例如：todo-api"
              disabled={creating}
              className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none focus:border-accentSoft"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11.5px] text-dim">项目约定（可选 → AGENTS.md）</label>
            <input
              value={rules}
              onChange={(e) => setRules(e.target.value)}
              placeholder="如：统一返回 {code, data, message}"
              disabled={creating}
              className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none focus:border-accentSoft"
            />
          </div>
        </div>

        {error && <p className="text-[12.5px] text-err">{error}</p>}

        <Button
          variant="primary"
          className="w-full"
          onClick={() => void submit()}
          disabled={creating || !spec || spec.length < 20 || !name.trim()}
        >
          {creating ? <Spinner /> : <Sparkles size={13} />} 按定稿方案生成项目
        </Button>
        {!spec && (
          <p className="flex items-center justify-center gap-1 text-[10.5px] text-dim/60">
            <ArrowUpRight size={11} /> 聊到方案定稿后即可生成；也可以直接说「直接出方案」
          </p>
        )}
      </div>
    </Modal>
  )
}
