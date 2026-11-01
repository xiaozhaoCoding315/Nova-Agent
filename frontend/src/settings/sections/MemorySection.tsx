import { Brain, Clock, Coins, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Badge, Spinner } from '../../components/common'
import { api, ApiError } from '../../lib/api'
import type { Memory } from '../../lib/types'

export function MemorySection({ refreshToken }: { refreshToken: number }) {
  const [memory, setMemory] = useState<Memory | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api.memory.get()
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
  }, [refreshToken])

  const removeFact = async (id: number) => {
    try {
      await api.memory.removeFact(id)
      setMemory((current) => current ? { ...current, facts: current.facts.filter((fact) => fact.id !== id) } : current)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const removeDaily = async (day: string) => {
    try {
      await api.memory.removeDaily(day)
      setMemory((current) => current ? { ...current, daily: current.daily.filter((item) => item.day !== day) } : current)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  return (
    <section className="rounded-lg border border-edge bg-panel p-4">
      <div className="mb-2 flex items-center gap-2">
        <Brain size={14} className="text-accent" />
        <h3 className="text-sm font-medium">记忆</h3>
        <span className="text-xs text-dim">
          {memory
            ? `${memory.facts.length} 条事实 · ${memory.daily.length} 份日摘要`
            : loading ? '加载中…' : '暂无数据'}
        </span>
      </div>

      {error && <p className="mb-2 text-xs text-err">{error}</p>}

      {!memory && loading && (
        <p className="flex items-center gap-2 text-sm text-dim"><Spinner /> 加载记忆…</p>
      )}

      {memory && memory.facts.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-2xs uppercase tracking-wide text-dim">长期事实</p>
          {memory.facts.map((fact) => (
            <div key={fact.id} className="flex items-start gap-2 rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-relaxed">{fact.content}</p>
                <p className="mt-0.5 flex items-center gap-2 text-2xs text-dim">
                  <span className="flex items-center gap-1"><Coins size={10} /> 重要性 {fact.importance.toFixed(1)}</span>
                  {fact.promoted_at && <Badge tone="ok">已晋升</Badge>}
                  {fact.last_used_at && <span>最近使用 {new Date(fact.last_used_at).toLocaleDateString()}</span>}
                </p>
              </div>
              <button
                className="mt-0.5 text-dim/60 transition-colors hover:text-err"
                onClick={() => void removeFact(fact.id)}
                aria-label="删除事实"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </div>
      )}

      {memory && memory.daily.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <p className="text-2xs uppercase tracking-wide text-dim">日摘要</p>
          {memory.daily.map((item) => (
            <div key={item.day} className="rounded-lg border border-edge/80 bg-base/40 px-2.5 py-2">
              <div className="flex items-center gap-2">
                <Clock size={11} className="text-dim" />
                <span className="font-mono text-xs text-dim">{item.day}</span>
                <span className="text-2xs text-dim/70">{item.message_count} 条消息</span>
                <button
                  className="ml-auto text-dim/60 transition-colors hover:text-err"
                  onClick={() => void removeDaily(item.day)}
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

      {memory && memory.facts.length === 0 && memory.daily.length === 0 && (
        <p className="text-sm leading-relaxed text-dim">
          还没有长期记忆。对话中抽取的偏好、日摘要与晋升事实会出现在这里；你可以随时删除。
        </p>
      )}
    </section>
  )
}
