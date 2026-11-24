import { Check, Pencil, Plus, ScrollText, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Button, Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type { Instruction, InstructionLevel, MemoryScopeType } from '../../lib/types'
import { inputClass } from '../../lib/ui'

const LEVEL_LABELS: Record<InstructionLevel, string> = {
  org: '组织策略',
  user: '用户指令',
  project: '项目指令',
}

const LEVEL_TONES: Record<InstructionLevel, 'err' | 'accent' | 'ok'> = {
  org: 'err',
  user: 'accent',
  project: 'ok',
}

const LEVEL_HINTS: Record<InstructionLevel, string> = {
  org: '部署方下发的规则，最先注入，优先级最低。',
  user: '你自己的稳定要求，例如回答风格与工作习惯。',
  project: '只对某个开发/论文/仓库作用域生效的规则。',
}

type Draft = {
  level: InstructionLevel
  scope_type: MemoryScopeType
  scope_id: string
  name: string
  content: string
  pathsText: string
  enabled: boolean
  priority: number
}

const EMPTY_DRAFT: Draft = {
  level: 'user',
  scope_type: 'global',
  scope_id: '',
  name: '',
  content: '',
  pathsText: '',
  enabled: true,
  priority: 100,
}

function splitPaths(text: string): string[] {
  return text
    .split(/[,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function scopeLabel(item: Instruction): string {
  if (item.level !== 'project') return '全局'
  const base = item.scope_type === 'repo'
    ? '仓库'
    : item.scope_type === 'thesis' ? '论文项目' : '开发'
  return item.scope_id ? `${base} · ${item.scope_id.slice(0, 8)}` : base
}

export function InstructionsSection({ refreshToken }: { refreshToken: number }) {
  const [items, setItems] = useState<Instruction[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [busyId, setBusyId] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.instructions.list()
      .then((next) => {
        if (!alive) return
        setItems(next)
        setError(null)
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : '指令加载失败')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [refreshToken, reloadKey])

  const reload = () => setReloadKey((value) => value + 1)

  const patchDraft = (patch: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...patch }))
  }

  const openCreate = () => {
    setEditingId(null)
    setDraft(EMPTY_DRAFT)
    setEditorOpen(true)
    setError(null)
    setNotice(null)
  }

  const openEdit = (item: Instruction) => {
    setEditingId(item.id)
    setDraft({
      level: item.level,
      scope_type: item.level === 'project' ? item.scope_type : 'global',
      scope_id: item.scope_id,
      name: item.name,
      content: item.content,
      pathsText: item.paths.join(', '),
      enabled: item.enabled,
      priority: item.priority,
    })
    setEditorOpen(true)
    setError(null)
    setNotice(null)
  }

  const save = async () => {
    const content = draft.content.trim()
    if (!content) {
      setError('指令内容不能为空')
      return
    }
    const isProject = draft.level === 'project'
    const scopeType = isProject ? draft.scope_type : 'global'
    const scopeId = isProject ? draft.scope_id.trim() : ''
    if (isProject && (scopeType === 'repo' || scopeType === 'thesis') && !scopeId) {
      setError(scopeType === 'repo' ? '请填写仓库 ID' : '请填写论文项目 ID')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const payload = {
        level: draft.level,
        scope_type: scopeType,
        scope_id: scopeId,
        name: draft.name.trim(),
        content,
        paths: splitPaths(draft.pathsText),
        enabled: draft.enabled,
        priority: Number.isFinite(draft.priority) ? draft.priority : 100,
      }
      if (editingId !== null) {
        await api.instructions.update(editingId, payload)
        setNotice('指令已更新，下一轮对话生效')
      } else {
        await api.instructions.create(payload)
        setNotice('指令已创建，下一轮对话生效')
      }
      setEditorOpen(false)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存指令失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleEnabled = async (item: Instruction) => {
    setBusyId(item.id)
    setError(null)
    try {
      await api.instructions.update(item.id, { enabled: !item.enabled })
      setNotice(item.enabled ? '指令已停用' : '指令已启用')
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '更新指令失败')
    } finally {
      setBusyId(null)
    }
  }

  const remove = async (item: Instruction) => {
    setBusyId(item.id)
    setError(null)
    try {
      await api.instructions.remove(item.id)
      setNotice('指令已删除')
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除指令失败')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="rounded-lg border border-edge bg-panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <ScrollText size={14} className="text-accent" />
        <h3 className="text-sm font-medium">人工指令</h3>
        <span className="text-xs text-dim">
          {loading ? '加载中…' : `${items.length} 条 · 按组织 → 用户 → 项目顺序注入`}
        </span>
        <button
          type="button"
          onClick={openCreate}
          className="ml-auto flex items-center gap-1 rounded px-2 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-fg"
        >
          <Plus size={12} /> 新建指令
        </button>
      </div>
      <p className="mb-3 text-2xs leading-relaxed text-dim">
        人工指令每轮都会注入，关闭自动记忆也照常生效；它们不得覆盖安全策略、
        权限模型和工具审批规则。带路径的指令只会在工具访问匹配文件时追加注入。
      </p>

      {error && <p className="mb-2 text-xs text-err">{error}</p>}
      {notice && <p className="mb-2 text-xs text-ok">{notice}</p>}

      {editorOpen && (
        <div className="mb-3 space-y-2 rounded-lg border border-edge/80 bg-base/40 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs text-dim">层级</span>
              <select
                value={draft.level}
                onChange={(event) => {
                  const level = event.target.value as InstructionLevel
                  patchDraft({
                    level,
                    scope_type: level === 'project' ? 'dev' : 'global',
                    scope_id: '',
                  })
                }}
                className={inputClass}
              >
                <option value="org">组织策略</option>
                <option value="user">用户指令</option>
                <option value="project">项目指令</option>
              </select>
              <span className="block text-2xs text-dim/70">{LEVEL_HINTS[draft.level]}</span>
            </label>
            <div className="space-y-1">
              <span className="text-xs text-dim">优先级（数字越小越先注入）</span>
              <input
                type="number"
                min={0}
                max={1000}
                value={draft.priority}
                onChange={(event) => patchDraft({
                  priority: Number(event.target.value) || 0,
                })}
                className={inputClass}
              />
              <label className="flex items-center gap-1.5 pt-1 text-xs text-dim">
                <input
                  type="checkbox"
                  checked={draft.enabled}
                  onChange={(event) => patchDraft({ enabled: event.target.checked })}
                />
                启用这条指令
              </label>
            </div>
          </div>
          {draft.level === 'project' && (
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="space-y-1">
                <span className="text-xs text-dim">作用域</span>
                <select
                  value={draft.scope_type}
                  onChange={(event) => patchDraft({
                    scope_type: event.target.value as MemoryScopeType,
                    scope_id: '',
                  })}
                  className={inputClass}
                >
                  <option value="dev">开发</option>
                  <option value="thesis">论文项目</option>
                  <option value="repo">仓库</option>
                </select>
              </label>
              {(draft.scope_type === 'repo' || draft.scope_type === 'thesis') && (
                <label className="space-y-1">
                  <span className="text-xs text-dim">
                    {draft.scope_type === 'repo' ? '仓库 ID' : '论文项目 ID'}
                  </span>
                  <input
                    value={draft.scope_id}
                    onChange={(event) => patchDraft({ scope_id: event.target.value })}
                    className={inputClass}
                  />
                </label>
              )}
            </div>
          )}
          <label className="block space-y-1">
            <span className="text-xs text-dim">名称</span>
            <input
              value={draft.name}
              onChange={(event) => patchDraft({ name: event.target.value })}
              placeholder="例如：回答风格"
              maxLength={120}
              className={inputClass}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-dim">指令内容（最多 4000 字）</span>
            <textarea
              value={draft.content}
              onChange={(event) => patchDraft({ content: event.target.value })}
              rows={5}
              placeholder="例如：回答先给结论，再给关键证据；不要用客套话开头。"
              className="w-full resize-y rounded border border-edge bg-base px-2 py-1.5 text-sm outline-none focus:border-accent"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs text-dim">
              路径规则（可选，逗号或换行分隔；支持通配符）
            </span>
            <input
              value={draft.pathsText}
              onChange={(event) => patchDraft({ pathsText: event.target.value })}
              placeholder="例如：src/api/**, docs/*.md"
              className={inputClass}
            />
          </label>
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => setEditorOpen(false)}>取消</Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void save()}
              disabled={saving}
            >
              {saving && <Spinner />} {editingId !== null ? '保存修改' : '创建指令'}
            </Button>
          </div>
        </div>
      )}

      {loading && items.length === 0 && (
        <p className="flex items-center gap-2 text-sm text-dim"><Spinner /> 加载指令…</p>
      )}

      {!loading && items.length === 0 && (
        <p className="text-sm leading-relaxed text-dim">
          还没有人工指令。你可以把稳定的回答风格、项目约定或审查规则写在这里，
          Nova 会在每轮对话中优先遵守。
        </p>
      )}

      <div className="space-y-1.5">
        {items.map((item) => (
          <div
            key={item.id}
            className={
              item.enabled
                ? 'rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2'
                : 'rounded-lg border border-edge/60 bg-base/20 px-2.5 py-2 opacity-60'
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={LEVEL_TONES[item.level]}>{LEVEL_LABELS[item.level]}</Badge>
              <span className="text-sm font-medium">{item.name}</span>
              <Badge tone="dim">{scopeLabel(item)}</Badge>
              {item.paths.length > 0 && (
                <Badge tone="warn">{item.paths.length} 条路径规则</Badge>
              )}
              {!item.enabled && <Badge tone="dim">已停用</Badge>}
              <span className="ml-auto flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={busyId === item.id}
                  onClick={() => void toggleEnabled(item)}
                  className="rounded px-1.5 py-0.5 text-2xs text-dim transition-colors hover:bg-raised hover:text-fg disabled:opacity-50"
                >
                  {item.enabled ? '停用' : '启用'}
                </button>
                <button
                  type="button"
                  onClick={() => openEdit(item)}
                  className="text-dim/60 transition-colors hover:text-accent"
                  aria-label="编辑指令"
                >
                  <Pencil size={12} />
                </button>
                <button
                  type="button"
                  disabled={busyId === item.id}
                  onClick={() => void remove(item)}
                  className="text-dim/60 transition-colors hover:text-err disabled:opacity-50"
                  aria-label="删除指令"
                >
                  <Trash2 size={12} />
                </button>
              </span>
            </div>
            <p className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-dim">
              {item.content}
            </p>
            {item.paths.length > 0 && (
              <p className="mt-1 font-mono text-2xs text-dim/70">
                {item.paths.join('  ')}
              </p>
            )}
          </div>
        ))}
      </div>

      {items.some((item) => item.enabled) && (
        <p className="mt-2 flex items-center gap-1 text-2xs text-dim/70">
          <Check size={10} /> 修改后从下一轮对话开始生效；已停用的指令不会注入。
        </p>
      )}
    </section>
  )
}
