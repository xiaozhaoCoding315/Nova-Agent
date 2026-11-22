import {
  Archive, Brain, Check, Clock, Coins, Pencil, Plus, RotateCcw, Trash2, X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type {
  Memory, MemoryCategory, MemoryFact, MemoryScopeType,
} from '../../lib/types'

const SCOPE_LABELS: Record<MemoryScopeType, string> = {
  global: '全局',
  dev: '开发',
  thesis: '论文项目',
  repo: '仓库',
}

const SCOPE_FILTERS: Array<{ value: 'all' | MemoryScopeType; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'global', label: '全局' },
  { value: 'dev', label: '开发' },
  { value: 'thesis', label: '论文' },
  { value: 'repo', label: '仓库' },
]

const CATEGORY_LABELS: Record<MemoryCategory, string> = {
  fact: '事实',
  preference: '偏好',
  project: '项目',
  decision: '决策',
  correction: '纠正',
}

function scopeLabel(type: MemoryScopeType, id: string): string {
  const base = SCOPE_LABELS[type] ?? type
  return id ? `${base} · ${id.slice(0, 8)}` : base
}

export function MemorySection({ refreshToken }: { refreshToken: number }) {
  const [memory, setMemory] = useState<Memory | null>(null)
  const [scopeFilter, setScopeFilter] = useState<'all' | MemoryScopeType>('all')
  const [showInactive, setShowInactive] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editText, setEditText] = useState('')
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const [draftScope, setDraftScope] = useState<MemoryScopeType>('global')
  const [draftScopeId, setDraftScopeId] = useState('')
  const [draftCategory, setDraftCategory] = useState<MemoryCategory>('preference')

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.memory.get(undefined, { includeInactive: showInactive })
      .then((next) => {
        if (!alive) return
        setMemory(next)
        setError(null)
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : '加载失败')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [refreshToken, showInactive, reloadKey])

  const reload = () => setReloadKey((value) => value + 1)

  const removeFact = async (id: number) => {
    try {
      await api.memory.removeFact(id)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const setFactStatus = async (fact: MemoryFact, status: 'active' | 'archived') => {
    setSaving(true)
    try {
      await api.memory.updateFact(fact.id, { status })
      setNotice(status === 'archived' ? '已归档，可随时恢复' : '已恢复为生效记忆')
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '更新失败')
    } finally {
      setSaving(false)
    }
  }

  const startEdit = (fact: MemoryFact) => {
    setEditingId(fact.id)
    setEditText(fact.content)
    setError(null)
    setNotice(null)
  }

  const saveEdit = async (id: number) => {
    if (!editText.trim()) return
    setSaving(true)
    try {
      await api.memory.updateFact(id, { content: editText.trim() })
      setEditingId(null)
      setNotice('记忆已更新，下一轮对话生效')
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const addFact = async () => {
    if (!draft.trim()) return
    if ((draftScope === 'repo' || draftScope === 'thesis') && !draftScopeId.trim()) {
      setError(draftScope === 'repo' ? '请填写仓库 ID' : '请填写论文项目 ID')
      return
    }
    setSaving(true)
    try {
      const result = await api.memory.addFact({
        content: draft.trim(),
        scope_type: draftScope,
        scope_id: draftScopeId.trim(),
        category: draftCategory,
      })
      setDraft('')
      setAdding(false)
      setNotice(result.added ? '已记住' : '已有相同记忆，已强化原有条目')
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const removeDaily = async (day: string, scopeType: MemoryScopeType, scopeId: string) => {
    try {
      await api.memory.removeDaily(day, scopeType, scopeId)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const facts = memory
    ? memory.facts.filter((fact) => scopeFilter === 'all' || fact.scope_type === scopeFilter)
    : []
  const daily = memory
    ? memory.daily.filter((item) => scopeFilter === 'all' || item.scope_type === scopeFilter)
    : []
  const activeCount = memory?.facts.filter((fact) => fact.status === 'active').length ?? 0

  return (
    <section className="rounded-lg border border-edge bg-panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <Brain size={14} className="text-accent" />
        <h3 className="text-sm font-medium">记忆</h3>
        <span className="text-xs text-dim">
          {memory
            ? `${activeCount} 条生效事实 · ${memory.daily.length} 份日摘要`
            : loading ? '加载中…' : '暂无数据'}
        </span>
        <button
          type="button"
          onClick={() => setAdding((value) => !value)}
          className="ml-auto flex items-center gap-1 rounded px-2 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-fg"
        >
          <Plus size={12} /> 记住
        </button>
      </div>

      {error && <p className="mb-2 text-xs text-err">{error}</p>}
      {notice && <p className="mb-2 text-xs text-ok">{notice}</p>}

      {adding && (
        <div className="mb-3 space-y-2 rounded-lg border border-edge/80 bg-base/40 p-2.5">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={2}
            placeholder="要长期记住的内容，例如：以后回答先给结论"
            className="w-full resize-none rounded border border-edge bg-base px-2 py-1.5 text-sm outline-none focus:border-accent"
          />
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              value={draftScope}
              onChange={(event) => setDraftScope(event.target.value as MemoryScopeType)}
              className="rounded border border-edge bg-base px-1.5 py-1 text-xs"
            >
              <option value="global">全局</option>
              <option value="dev">开发</option>
              <option value="thesis">论文项目</option>
              <option value="repo">仓库</option>
            </select>
            {(draftScope === 'repo' || draftScope === 'thesis') && (
              <input
                value={draftScopeId}
                onChange={(event) => setDraftScopeId(event.target.value)}
                placeholder={draftScope === 'repo' ? '仓库 ID' : '论文项目 ID'}
                className="w-36 rounded border border-edge bg-base px-1.5 py-1 font-mono text-xs"
              />
            )}
            <select
              value={draftCategory}
              onChange={(event) => setDraftCategory(event.target.value as MemoryCategory)}
              className="rounded border border-edge bg-base px-1.5 py-1 text-xs"
            >
              <option value="preference">偏好</option>
              <option value="fact">事实</option>
              <option value="project">项目</option>
              <option value="decision">决策</option>
            </select>
            <button
              type="button"
              disabled={saving || !draft.trim()}
              onClick={() => void addFact()}
              className="ml-auto flex items-center gap-1 rounded bg-accentSoft/70 px-2 py-1 text-xs text-accent disabled:opacity-50"
            >
              <Check size={12} /> 保存
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="rounded px-2 py-1 text-xs text-dim hover:bg-raised"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {memory && (
        <div className="mb-3 flex flex-wrap items-center gap-1">
          {SCOPE_FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => setScopeFilter(filter.value)}
              className={
                scopeFilter === filter.value
                  ? 'rounded bg-accentSoft/70 px-2 py-1 text-xs text-accent'
                  : 'rounded px-2 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-fg'
              }
            >
              {filter.label}
            </button>
          ))}
          <label className="ml-auto flex items-center gap-1 text-2xs text-dim">
            <input
              type="checkbox"
              checked={showInactive}
              onChange={(event) => setShowInactive(event.target.checked)}
            />
            显示已归档
          </label>
        </div>
      )}

      {!memory && loading && (
        <p className="flex items-center gap-2 text-sm text-dim"><Spinner /> 加载记忆…</p>
      )}

      {memory && facts.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs uppercase tracking-wide text-dim">长期事实</p>
          {facts.map((fact) => (
            <div key={fact.id} className="flex items-start gap-2 rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2">
              <div className="min-w-0 flex-1">
                {editingId === fact.id ? (
                  <div className="space-y-1.5">
                    <textarea
                      value={editText}
                      onChange={(event) => setEditText(event.target.value)}
                      rows={2}
                      className="w-full resize-none rounded border border-edge bg-base px-2 py-1.5 text-sm outline-none focus:border-accent"
                    />
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        disabled={saving || !editText.trim()}
                        onClick={() => void saveEdit(fact.id)}
                        className="flex items-center gap-1 rounded bg-accentSoft/70 px-2 py-1 text-xs text-accent disabled:opacity-50"
                      >
                        <Check size={12} /> 保存
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="flex items-center gap-1 rounded px-2 py-1 text-xs text-dim hover:bg-raised"
                      >
                        <X size={12} /> 取消
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="text-sm leading-relaxed">{fact.content}</p>
                )}
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-2xs text-dim">
                  <span className="flex items-center gap-1"><Coins size={10} /> 重要性 {fact.importance.toFixed(1)}</span>
                  <Badge tone="accent">{scopeLabel(fact.scope_type, fact.scope_id)}</Badge>
                  <Badge tone="dim">{CATEGORY_LABELS[fact.category] ?? fact.category}</Badge>
                  {fact.promoted_at && <Badge tone="ok">已晋升</Badge>}
                  {fact.status === 'superseded' && <Badge tone="warn">已被新记忆替代</Badge>}
                  {fact.status === 'archived' && <Badge tone="err">已归档</Badge>}
                  {fact.version > 1 && <span>v{fact.version}</span>}
                  {fact.supersedes_id && <span>纠正 #{fact.supersedes_id}</span>}
                  {fact.source_session_id && (
                    <span>来源会话 {fact.source_session_id.slice(0, 8)}
                      {fact.source_message_id ? ` · 消息 #${fact.source_message_id}` : ''}
                    </span>
                  )}
                  {fact.last_used_at && <span>最近使用 {new Date(fact.last_used_at).toLocaleDateString()}</span>}
                </p>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5">
                <button
                  className="text-dim/60 transition-colors hover:text-accent"
                  onClick={() => startEdit(fact)}
                  aria-label="编辑事实"
                >
                  <Pencil size={12} />
                </button>
                <button
                  className="text-dim/60 transition-colors hover:text-warn"
                  onClick={() => void setFactStatus(fact, fact.status === 'archived' ? 'active' : 'archived')}
                  aria-label={fact.status === 'archived' ? '恢复事实' : '归档事实'}
                >
                  {fact.status === 'archived' ? <RotateCcw size={12} /> : <Archive size={12} />}
                </button>
                <button
                  className="text-dim/60 transition-colors hover:text-err"
                  onClick={() => void removeFact(fact.id)}
                  aria-label="删除事实"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {memory && daily.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <p className="text-2xs uppercase tracking-wide text-dim">日摘要</p>
          {daily.map((item) => (
            <div key={`${item.scope_type}:${item.scope_id}:${item.day}`} className="rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2">
              <div className="flex items-center gap-2">
                <Clock size={11} className="text-dim" />
                <span className="font-mono text-xs text-dim">{item.day}</span>
                <Badge tone="accent">{scopeLabel(item.scope_type, item.scope_id)}</Badge>
                <span className="text-2xs text-dim/70">{item.message_count} 条消息</span>
                <button
                  className="ml-auto text-dim/60 transition-colors hover:text-err"
                  onClick={() => void removeDaily(item.day, item.scope_type, item.scope_id)}
                  aria-label="删除日摘要"
                >
                  <Trash2 size={12} />
                </button>
              </div>
              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-dim">
                {item.summary}
              </p>
            </div>
          ))}
        </div>
      )}

      {memory && facts.length === 0 && daily.length === 0 && (
        <p className="text-sm leading-relaxed text-dim">
          {memory.facts.length === 0 && memory.daily.length === 0
            ? '还没有长期记忆。对话中抽取的偏好、日摘要与晋升事实会出现在这里；你可以随时添加、编辑或删除。'
            : '这个范围还没有记忆。切换到「全部」查看其他范围的记忆。'}
        </p>
      )}
    </section>
  )
}
