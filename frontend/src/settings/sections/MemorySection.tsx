import {
  Archive, Brain, Check, Clock, Coins, Download, Pencil, Plus, RotateCcw,
  ShieldAlert, SlidersHorizontal, Tags, Trash2, X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type {
  Memory, MemoryCategory, MemoryFact, MemoryFactScopeType, MemoryReviewItem,
  MemoryReviewKind, MemoryScopeType, MemorySettings, MemoryTopic,
} from '../../lib/types'
import { inputClass } from '../../lib/ui'

const SCOPE_LABELS: Record<MemoryFactScopeType, string> = {
  global: '全局',
  dev: '开发',
  thesis: '论文项目',
  repo: '仓库',
  agent: '子代理',
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

const REVIEW_KIND_LABELS: Record<MemoryReviewKind, string> = {
  high_risk_fact: '高风险记忆',
  merge: '重复记忆合并',
  conflict: '同主题冲突',
}

function scopeLabel(type: MemoryFactScopeType, id: string): string {
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
  const [settings, setSettings] = useState<MemorySettings | null>(null)
  const [draftSettings, setDraftSettings] = useState<MemorySettings | null>(null)
  const [keywordsText, setKeywordsText] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [savingSettings, setSavingSettings] = useState(false)
  const [overrideKey, setOverrideKey] = useState('')
  const [purgeOpen, setPurgeOpen] = useState(false)
  const [purgeMessages, setPurgeMessages] = useState(true)
  const [purging, setPurging] = useState(false)
  const [topics, setTopics] = useState<MemoryTopic[]>([])
  const [reviewItems, setReviewItems] = useState<MemoryReviewItem[]>([])
  const [reviewBusy, setReviewBusy] = useState<number | null>(null)

  useEffect(() => {
    let alive = true
    api.memory.settings()
      .then((next) => {
        if (!alive) return
        setSettings(next)
        setDraftSettings(next)
        setKeywordsText(next.blocked_keywords.join('，'))
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : '记忆设置加载失败')
      })
    return () => {
      alive = false
    }
  }, [refreshToken])

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

  useEffect(() => {
    let alive = true
    Promise.all([api.memory.topics(), api.memory.reviewQueue()])
      .then(([nextTopics, nextReview]) => {
        if (!alive) return
        setTopics(nextTopics)
        setReviewItems(nextReview)
      })
      .catch((err) => {
        if (alive) setError(err instanceof ApiError ? err.message : '记忆索引加载失败')
      })
    return () => {
      alive = false
    }
  }, [refreshToken, reloadKey])

  const reload = () => setReloadKey((value) => value + 1)

  const resolveReview = async (id: number, approve: boolean) => {
    setReviewBusy(id)
    setError(null)
    try {
      if (approve) await api.memory.approveReview(id)
      else await api.memory.rejectReview(id)
      setNotice(approve ? '已通过，记忆按规则生效' : '已拒绝，该记忆不会生效')
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '复核失败')
    } finally {
      setReviewBusy(null)
    }
  }

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

  const patchDraft = (patch: Partial<MemorySettings>) => {
    setDraftSettings((current) => (current ? { ...current, ...patch } : current))
  }

  const openSettings = () => {
    if (!settingsOpen && settings) {
      setDraftSettings(settings)
      setKeywordsText(settings.blocked_keywords.join('，'))
    }
    setSettingsOpen((value) => !value)
    setError(null)
    setNotice(null)
  }

  const toggleBlockedCategory = (category: MemoryCategory) => {
    if (!draftSettings) return
    const blocked = draftSettings.blocked_categories.includes(category)
      ? draftSettings.blocked_categories.filter((item) => item !== category)
      : [...draftSettings.blocked_categories, category]
    patchDraft({ blocked_categories: blocked })
  }

  const addOverride = () => {
    const key = overrideKey.trim()
    if (!key || !draftSettings) return
    patchDraft({
      scope_overrides: {
        ...draftSettings.scope_overrides,
        [key]: { auto_memory: true },
      },
    })
    setOverrideKey('')
  }

  const removeOverride = (key: string) => {
    if (!draftSettings) return
    const next = { ...draftSettings.scope_overrides }
    delete next[key]
    patchDraft({ scope_overrides: next })
  }

  const saveSettings = async () => {
    if (!draftSettings) return
    if (draftSettings.retention_days < 1 || draftSettings.retention_days > 3650) {
      setError('保留天数需在 1–3650 之间')
      return
    }
    setSavingSettings(true)
    setError(null)
    try {
      const updated = await api.memory.updateSettings({
        ...draftSettings,
        blocked_keywords: keywordsText
          .split(/[,，\n]/)
          .map((item) => item.trim())
          .filter(Boolean),
      })
      setSettings(updated)
      setDraftSettings(updated)
      setKeywordsText(updated.blocked_keywords.join('，'))
      setSettingsOpen(false)
      setNotice('记忆设置已保存，下一轮对话生效')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存记忆设置失败')
    } finally {
      setSavingSettings(false)
    }
  }

  const exportMemory = async (format: 'json' | 'markdown') => {
    setError(null)
    try {
      await api.memory.exportMemory(format)
      setNotice(format === 'markdown' ? '已导出 Markdown' : '已导出 JSON')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导出失败')
    }
  }

  const purgeAll = async () => {
    setPurging(true)
    setError(null)
    try {
      const result = await api.memory.purge({ includeMessages: purgeMessages })
      setPurgeOpen(false)
      setNotice(
        `已删除 ${result.facts} 条事实、${result.daily} 份日摘要、${result.lessons} 条经验`
        + (purgeMessages ? `、${result.messages} 条消息` : ''),
      )
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    } finally {
      setPurging(false)
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
          {settings && ` · 自动记忆${settings.auto_memory ? '开' : '关'} · 保留 ${settings.retention_days} 天`}
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

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={openSettings}
          className="flex items-center gap-1 rounded border border-edge px-2 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-fg"
        >
          <SlidersHorizontal size={12} /> 记忆策略
        </button>
        <button
          type="button"
          onClick={() => void exportMemory('markdown')}
          className="flex items-center gap-1 rounded border border-edge px-2 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-fg"
        >
          <Download size={12} /> 导出 Markdown
        </button>
        <button
          type="button"
          onClick={() => void exportMemory('json')}
          className="flex items-center gap-1 rounded border border-edge px-2 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-fg"
        >
          <Download size={12} /> 导出 JSON
        </button>
        <button
          type="button"
          onClick={() => setPurgeOpen(true)}
          className="ml-auto flex items-center gap-1 rounded px-2 py-1 text-xs text-err/80 transition-colors hover:bg-err/10 hover:text-err"
        >
          <Trash2 size={12} /> 删除全部
        </button>
      </div>

      {reviewItems.length > 0 && (
        <div className="mb-3 space-y-1.5 rounded-lg border border-warn/40 bg-warn/5 p-2.5">
          <p className="flex flex-wrap items-center gap-1 text-xs font-medium text-warn">
            <ShieldAlert size={12} /> 待复核 {reviewItems.length} 条
            <span className="font-normal text-dim">（通过前不会注入或参与检索）</span>
          </p>
          {reviewItems.map((item) => (
            <div
              key={item.id}
              className="rounded border border-edge/70 bg-base/50 px-2 py-1.5"
            >
              <div className="flex flex-wrap items-center gap-1.5 text-2xs text-dim">
                <Badge tone="warn">{REVIEW_KIND_LABELS[item.kind]}</Badge>
                <span>{item.reason || '需要确认'}</span>
                <Badge tone="dim">{scopeLabel(item.scope_type, item.scope_id)}</Badge>
                <span className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    disabled={reviewBusy === item.id}
                    onClick={() => void resolveReview(item.id, true)}
                    className="flex items-center gap-0.5 rounded bg-ok/15 px-1.5 py-0.5 text-ok transition-colors hover:bg-ok/25 disabled:opacity-50"
                  >
                    <Check size={10} /> 通过
                  </button>
                  <button
                    type="button"
                    disabled={reviewBusy === item.id}
                    onClick={() => void resolveReview(item.id, false)}
                    className="flex items-center gap-0.5 rounded px-1.5 py-0.5 text-dim transition-colors hover:bg-raised hover:text-err disabled:opacity-50"
                  >
                    <X size={10} /> 拒绝
                  </button>
                </span>
              </div>
              <p className="mt-1 text-sm leading-relaxed">
                {item.content || item.one_line}
              </p>
              {item.target_content && (
                <p className="mt-0.5 text-2xs text-dim">
                  对照现有：{item.target_content}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {settingsOpen && draftSettings && (
        <div className="mb-3 space-y-3 rounded-lg border border-edge/80 bg-base/40 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm">自动记忆</p>
              <p className="text-2xs leading-relaxed text-dim">
                关闭后不再自动抽取或注入长期记忆；已保存的记忆仍可在下方查看、导出或删除。
              </p>
            </div>
            <input
              type="checkbox"
              checked={draftSettings.auto_memory}
              onChange={(event) => patchDraft({ auto_memory: event.target.checked })}
              aria-label="自动记忆"
              className="mt-1"
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="space-y-1">
              <span className="text-xs text-dim">事实保留天数（1–3650）</span>
              <input
                type="number"
                min={1}
                max={3650}
                value={draftSettings.retention_days}
                onChange={(event) => patchDraft({
                  retention_days: Number(event.target.value) || 0,
                })}
                className={inputClass}
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-dim">手动记忆默认作用域</span>
              <select
                value={draftSettings.default_scope}
                onChange={(event) => patchDraft({
                  default_scope: event.target.value as 'global' | 'dev',
                })}
                className={inputClass}
              >
                <option value="dev">开发</option>
                <option value="global">全局</option>
              </select>
            </label>
          </div>
          <div>
            <p className="text-xs text-dim">不参与记忆的类别</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {(Object.keys(CATEGORY_LABELS) as MemoryCategory[]).map((category) => (
                <label
                  key={category}
                  className="flex items-center gap-1 rounded border border-edge/70 bg-base px-1.5 py-0.5 text-2xs text-dim"
                >
                  <input
                    type="checkbox"
                    checked={draftSettings.blocked_categories.includes(category)}
                    onChange={() => toggleBlockedCategory(category)}
                  />
                  {CATEGORY_LABELS[category]}
                </label>
              ))}
            </div>
          </div>
          <label className="block space-y-1">
            <span className="text-xs text-dim">屏蔽关键词（逗号分隔；命中即不学习也不召回）</span>
            <input
              value={keywordsText}
              onChange={(event) => setKeywordsText(event.target.value)}
              placeholder="例如：工资，身份证"
              className={inputClass}
            />
          </label>
          <div>
            <p className="text-xs text-dim">按作用域覆盖</p>
            {Object.keys(draftSettings.scope_overrides).length === 0 && (
              <p className="mt-1 text-2xs text-dim/70">
                暂无覆盖。键名形如 dev:、repo:&lt;仓库 ID&gt;、thesis:&lt;项目 ID&gt;。
              </p>
            )}
            <div className="mt-1 space-y-1">
              {Object.entries(draftSettings.scope_overrides).map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-center gap-2 rounded border border-edge/70 bg-base/40 px-2 py-1"
                >
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">{key}</span>
                  <label className="flex items-center gap-1 text-2xs text-dim">
                    <input
                      type="checkbox"
                      checked={value.auto_memory !== false}
                      onChange={(event) => patchDraft({
                        scope_overrides: {
                          ...draftSettings.scope_overrides,
                          [key]: { ...value, auto_memory: event.target.checked },
                        },
                      })}
                    />
                    自动记忆
                  </label>
                  <button
                    type="button"
                    onClick={() => removeOverride(key)}
                    className="text-dim transition-colors hover:text-err"
                    aria-label="移除作用域覆盖"
                  >
                    <X size={12} />
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-1 flex items-center gap-1.5">
              <input
                value={overrideKey}
                onChange={(event) => setOverrideKey(event.target.value)}
                placeholder="repo:<仓库 ID>"
                className={inputClass}
              />
              <Button size="sm" onClick={addOverride} disabled={!overrideKey.trim()}>
                添加
              </Button>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => setSettingsOpen(false)}>取消</Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void saveSettings()}
              disabled={savingSettings}
            >
              {savingSettings && <Spinner />} 保存设置
            </Button>
          </div>
        </div>
      )}

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
            显示已归档/待审核
          </label>
        </div>
      )}

      {topics.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1">
          <Tags size={11} className="text-dim" />
          {topics.slice(0, 16).map((topic) => (
            <span
              key={`${topic.scope_type}:${topic.scope_id}:${topic.topic}`}
              title={topic.samples.join('\n')}
              className="rounded-full border border-edge/70 bg-base/40 px-2 py-0.5 text-2xs text-dim"
            >
              {topic.topic} · {topic.count}
            </span>
          ))}
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
                  {fact.status === 'pending' && <Badge tone="warn">待审核</Badge>}
                  {fact.topic && <Badge tone="dim">{fact.topic}</Badge>}
                  {fact.version > 1 && <span>v{fact.version}</span>}
                  {fact.supersedes_id && <span>纠正 #{fact.supersedes_id}</span>}
                  {fact.merged_into_id && <span>已合并到 #{fact.merged_into_id}</span>}
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

      <Modal
        open={purgeOpen}
        onClose={() => setPurgeOpen(false)}
        title="删除全部记忆"
        width="max-w-sm"
      >
        <p className="text-sm leading-relaxed text-dim">
          将永久删除当前账号的全部长期事实、日摘要与经验教训，操作无法撤销。
        </p>
        <label className="mt-3 flex items-start gap-2 text-xs text-dim">
          <input
            type="checkbox"
            checked={purgeMessages}
            onChange={(event) => setPurgeMessages(event.target.checked)}
            className="mt-0.5"
          />
          同时删除聊天消息、压缩记录与会话摘要（取消勾选则只清空长期记忆）
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => setPurgeOpen(false)}>取消</Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => void purgeAll()}
            disabled={purging}
          >
            {purging && <Spinner />} 确认删除
          </Button>
        </div>
      </Modal>
    </section>
  )
}
