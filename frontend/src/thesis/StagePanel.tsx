import clsx from 'clsx'
import {
  ArrowLeft, ArrowRight, Check, CheckCircle2, Clock3, FileDown, FileText, MessageSquare,
  ShieldCheck,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { ThesisProjectDetail, ThesisStages } from '../lib/types'
import { useThesis } from '../stores/thesis'

const READINESS_OPTIONS = [
  { value: 'not_started', label: '未开始' },
  { value: 'gathering', label: '收集中' },
  { value: 'needs_user', label: '需要我确认' },
  { value: 'ready_for_review', label: '待审阅' },
  { value: 'needs_changes', label: '需要修改' },
]

const EVENT_LABEL: Record<string, string> = {
  content: '更新阶段说明',
  readiness: '更新状态',
  confirmed: '作者确认',
  advanced: '进入下一阶段',
  returned: '返回上一阶段',
  stale: '确认失效',
  artifact: '更新产物',
  draft: 'AI 阶段草稿',
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function readinessTone(readiness: string): 'ok' | 'warn' | 'err' | 'dim' | 'accent' {
  if (readiness === 'accepted') return 'ok'
  if (readiness === 'needs_changes') return 'err'
  if (readiness === 'ready_for_review') return 'accent'
  if (readiness === 'needs_user') return 'warn'
  return 'dim'
}

export function StagePanel({
  project,
  onOpenChat,
}: {
  project: ThesisProjectDetail
  onOpenChat?: () => void
}) {
  const [board, setBoard] = useState<ThesisStages | null>(null)
  const [content, setContent] = useState('')
  const [dirty, setDirty] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [draftOpen, setDraftOpen] = useState(false)
  const [requirements, setRequirements] = useState('')
  const [wordCount, setWordCount] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [draftNote, setDraftNote] = useState('')
  const [exporting, setExporting] = useState('')

  const current = useMemo(
    () => board?.summary.find((item) => item.position === 'current') ?? null,
    [board],
  )
  const earlier = useMemo(
    () => board?.summary.filter((item) => item.position === 'done') ?? [],
    [board],
  )
  const confirmation = board?.state.confirmations[board.state.stage] ?? null

  const apply = (next: ThesisStages) => {
    setBoard(next)
    setContent(next.current_content)
    setDirty(false)
    setDraftNote('')
  }

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      apply(await api.thesis.stages(project.id))
    } catch (err) {
      setError(messageOf(err, '加载阶段失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  const saveContent = async (): Promise<ThesisStages | null> => {
    if (!board) return null
    if (!dirty) return board
    const next = await api.thesis.setStageContent(project.id, content)
    apply(next)
    return next
  }

  const save = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await saveContent()
      setNotice('阶段说明已保存')
    } catch (err) {
      setError(messageOf(err, '保存阶段说明失败'))
    } finally {
      setBusy(false)
    }
  }

  const generateDraft = async () => {
    setDrafting(true)
    setError('')
    setNotice('')
    try {
      const result = await api.thesis.draftStage(project.id, {
        requirements: requirements.trim(),
        word_count: wordCount.trim() ? Number(wordCount) : undefined,
      })
      setContent(result.content)
      setDirty(true)
      setDraftNote(result.note)
      setDraftOpen(false)
      setNotice('草稿已放进编辑框，还没有保存；核对后再保存和确认。')
    } catch (err) {
      setError(messageOf(err, '生成阶段草稿失败'))
    } finally {
      setDrafting(false)
    }
  }

  const run = async (action: (saved: ThesisStages) => Promise<ThesisStages>, message: string) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const saved = await saveContent()
      if (!saved) return
      apply(await action(saved))
      setNotice(message)
    } catch (err) {
      setError(messageOf(err, '操作失败'))
    } finally {
      setBusy(false)
    }
  }

  const exportManuscript = async (format: 'md' | 'docx' | 'pdf') => {
    setExporting(format)
    setError('')
    setNotice('')
    try {
      const readiness = await api.thesis.exportReadiness(project.id)
      let acknowledge = false
      if (!readiness.ready) {
        const lines = readiness.warnings
          .slice(0, 6)
          .map((item) => `· ${item.message}`)
          .join('\n')
        const proceed = window.confirm(
          `导出前检查到以下未确认项：\n${lines}\n\n仍然导出阶段稿？` +
          '未确认的内容会以「未确认草稿」标记写进文件。',
        )
        if (!proceed) return
        acknowledge = true
      }
      await api.thesis.exportManuscript(project.id, format, acknowledge)
      setNotice(`已导出 ${format.toUpperCase()} 阶段稿`)
    } catch (err) {
      setError(messageOf(err, '导出阶段稿失败'))
    } finally {
      setExporting('')
    }
  }

  const goBack = (stage: string, label: string) => {
    if (!window.confirm(`返回到「${label}」？当前阶段会标记为需要修改，已确认的内容不会自动恢复。`)) return
    void run(() => api.thesis.returnStage(project.id, stage), `已返回到「${label}」`)
  }

  if (loading && !board) {
    return <p className="mt-4 flex items-center gap-2 text-xs text-faint"><Spinner /> 加载阶段…</p>
  }
  if (!board || !current) {
    return (
      <p className="mt-4 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
        {error || '阶段状态不可用'}
      </p>
    )
  }

  return (
    <div className="mt-4 space-y-4">
      <section className="rounded-lg border border-edge bg-panel/40 p-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {board.summary.map((item) => {
            const isCurrent = item.position === 'current'
            const isDone = item.position === 'done'
            return (
              <button
                key={item.stage}
                onClick={() => isDone && goBack(item.stage, item.label)}
                disabled={!isDone || busy}
                className={clsx(
                  'flex items-center gap-1 rounded-sm border px-2 py-1 text-xs transition-colors',
                  isCurrent && 'border-accent/50 bg-accentSoft/40 text-ink',
                  isDone && 'border-ok/30 bg-ok/10 text-ok hover:border-ok/60',
                  !isCurrent && !isDone && 'border-edge bg-base/40 text-faint',
                )}
                title={isDone ? `返回到${item.label}` : item.label}
              >
                {isDone ? <Check size={11} /> : <span className="font-mono text-2xs">{item.stage[0].toUpperCase()}</span>}
                {item.label}
                {item.stale && <span className="text-2xs text-warn">失效</span>}
              </button>
            )
          })}
        </div>
        <p className="mt-2 text-2xs leading-relaxed text-faint">
          点已完成的阶段可以返回重做；不能跳过中间的阶段。返回会把目标阶段标为「需要修改」。
        </p>
      </section>

      {error && (
        <div className="flex items-start gap-2 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
          <span className="min-w-0 flex-1">{error}</span>
          <button onClick={() => setError('')} className="underline">关闭</button>
        </div>
      )}
      {notice && (
        <div className="flex items-center gap-2 rounded-md border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok">
          <CheckCircle2 size={13} /> {notice}
          <button onClick={() => setNotice('')} className="ml-auto underline">关闭</button>
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 rounded-lg border border-edge bg-panel/40 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">{current.label}</h3>
            <Badge tone={readinessTone(board.state.readiness)}>
              {board.state.readiness === 'accepted'
                ? '已接受'
                : READINESS_OPTIONS.find((item) => item.value === board.state.readiness)?.label ?? board.state.readiness}
            </Badge>
            {confirmation && (
              <Badge tone={confirmation.stale ? 'warn' : 'ok'}>
                {confirmation.stale ? '确认已失效' : '内容已确认'}
              </Badge>
            )}
            {draftNote && <Badge tone="warn">AI 草稿 · 未保存</Badge>}
          </div>
          <p className="mt-1 text-2xs leading-relaxed text-faint">
            这一阶段只写你愿意负责的内容。你可以先给要求，让写作对话用 1-3 个问题把方向问清楚；
            写作进度与确认状态会随对话上下文一起提供给模型。
          </p>

          <textarea
            value={content}
            onChange={(event) => {
              setContent(event.target.value)
              setDirty(true)
              setNotice('')
            }}
            rows={10}
            maxLength={8000}
            placeholder="例：选题方向、研究对象、数据来源、提纲或本章要点。写不清楚时可以先写「暂不确定」。"
            className="mt-3 w-full resize-y rounded-md border border-edge bg-base px-2.5 py-2 text-sm leading-relaxed text-ink outline-none focus:border-accent"
          />
          {draftOpen && (
            <div className="mt-2 space-y-2 rounded-md border border-edge bg-base/50 p-2.5">
              <textarea
                value={requirements}
                onChange={(event) => setRequirements(event.target.value)}
                rows={2}
                maxLength={4000}
                placeholder="可选：这一阶段想解决什么、已有材料、导师要求。没想好可以留空。"
                className="w-full resize-y rounded-sm border border-edge bg-base px-2 py-1.5 text-xs leading-relaxed text-ink outline-none focus:border-accent"
              />
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1 text-2xs text-faint">
                  字数
                  <input
                    value={wordCount}
                    onChange={(event) => setWordCount(event.target.value.replace(/[^0-9]/g, ''))}
                    placeholder="可选"
                    className="w-16 rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
                  />
                </label>
                <span className="mr-auto text-2xs text-faint">
                  只生成当前阶段，不写整篇；缺的信息会写成「待补充」。
                </span>
                <Button
                  size="sm"
                  onClick={() => {
                    useThesis.getState().setChatSeed(
                      `当前论文项目《${project.title}》，阶段「${current.label}」。` +
                      '请先不要写正文，先问我 1-3 个具体问题，确认这一阶段的目标、范围、' +
                      '已有材料和导师要求。问题一次问完，简短具体。',
                    )
                    setDraftOpen(false)
                    onOpenChat?.()
                  }}
                >
                  <MessageSquare size={12} /> 先问我 1-3 个问题
                </Button>
                <Button size="sm" variant="primary" onClick={() => void generateDraft()} disabled={drafting}>
                  {drafting ? <Spinner /> : <FileText size={12} />} 生成草稿
                </Button>
                <Button size="sm" onClick={() => setDraftOpen(false)} disabled={drafting}>取消</Button>
              </div>
            </div>
          )}

          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <span className="mr-auto text-2xs text-faint">
              {content.length}/8000 字{dirty ? ' · 有未保存修改' : ''}
            </span>
            <Button size="sm" onClick={() => setDraftOpen((value) => !value)} disabled={busy || drafting}>
              <FileText size={12} /> 起草这一阶段
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={!dirty || busy}>
              {busy ? <Spinner /> : null} 保存阶段说明
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void run(
                () => api.thesis.confirmStage(project.id),
                '已确认当前内容；之后修改这段说明会让确认失效',
              )}
              disabled={busy || !content.trim()}
            >
              <ShieldCheck size={12} /> 确认当前内容
            </Button>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-edge pt-3">
            <label className="flex items-center gap-1.5 text-2xs text-faint">
              状态
              <select
                value={board.state.readiness === 'accepted' ? 'ready_for_review' : board.state.readiness}
                onChange={(event) => void run(
                  () => api.thesis.setStageReadiness(project.id, event.target.value),
                  '状态已更新',
                )}
                disabled={busy}
                className="rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
              >
                {READINESS_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>{item.label}</option>
                ))}
              </select>
            </label>
            <span className="text-2xs text-faint">
              进入下一阶段需要状态为「待审阅」或先确认内容。
            </span>
            <Button
              size="sm"
              className="ml-auto"
              onClick={() => void run(
                () => api.thesis.advanceStage(project.id),
                '已进入下一阶段',
              )}
              disabled={busy || !['ready_for_review', 'accepted'].includes(board.state.readiness)}
            >
              下一阶段 <ArrowRight size={12} />
            </Button>
          </div>

          {earlier.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-edge pt-3">
              <span className="text-2xs text-faint">返回：</span>
              {earlier.map((item) => (
                <button
                  key={item.stage}
                  onClick={() => goBack(item.stage, item.label)}
                  disabled={busy}
                  className="flex items-center gap-1 rounded-sm border border-edge px-1.5 py-1 text-2xs text-dim hover:text-ink"
                >
                  <ArrowLeft size={10} /> {item.label}
                </button>
              ))}
            </div>
          )}
        </section>

        <aside className="space-y-3">
          <section className="rounded-lg border border-edge bg-panel/40 p-3">
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
              <Clock3 size={13} /> 阶段记录
            </p>
            {board.events.length === 0 ? (
              <p className="mt-1 text-2xs text-faint">还没有记录。</p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {board.events.slice(0, 12).map((event) => (
                  <li key={event.id} className="rounded-sm border border-edge bg-base/40 px-2 py-1.5">
                    <p className="text-2xs text-dim">
                      {EVENT_LABEL[event.type] ?? event.type} · {event.stage}
                      {event.from_stage && event.from_stage !== event.stage ? `（从 ${event.from_stage}）` : ''}
                    </p>
                    <p className="mt-0.5 text-2xs text-faint">
                      {new Date(event.created_at).toLocaleString()}
                      {event.note ? ` · ${event.note}` : ''}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-edge bg-panel/40 p-3">
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
              <FileDown size={13} /> 阶段稿导出
            </p>
            <p className="mt-1.5 text-2xs leading-relaxed text-faint">
              把各阶段已填写的内容按顺序整理成一份稿子。未确认或已失效的内容会先提示，
              确认后仍会以「未确认草稿」标记写入。
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(['md', 'docx', 'pdf'] as const).map((format) => (
                <Button
                  key={format}
                  size="sm"
                  onClick={() => void exportManuscript(format)}
                  disabled={!!exporting}
                >
                  {exporting === format ? <Spinner /> : <FileDown size={12} />}
                  {format.toUpperCase()}
                </Button>
              ))}
            </div>
            <p className="mt-1.5 text-2xs leading-relaxed text-faint">
              这是通用版式，不是学校模板；提交前请自行核对格式与内容。
            </p>
          </section>

          <section className="rounded-lg border border-edge bg-panel/40 p-3 text-2xs leading-relaxed text-faint">
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink">边界</p>
            <p className="mt-1.5">
              阶段状态不会替你判定内容合格。确认绑定当前说明的 SHA-256；修改说明后确认会标为失效，
              导出前需要重新核对。整篇论文仍需你本人修改并署名。
            </p>
          </section>
        </aside>
      </div>
    </div>
  )
}
