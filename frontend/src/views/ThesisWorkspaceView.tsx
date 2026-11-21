import clsx from 'clsx'
import {
  BookOpen, Check, CheckCircle2, Eye, EyeOff, FileText, MessageSquare, Plus, Settings2,
  ShieldCheck, Trash2, Undo2, Upload, X,
} from 'lucide-react'
import type { DragEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Badge, Button, EmptyState, Modal, Spinner, StatusDot } from '../components/common'
import type { ThesisDegree, ThesisFixPreview, ThesisIssue } from '../lib/types'
import { useThesis } from '../stores/thesis'
import { CitationPanel } from '../thesis/CitationPanel'
import { DisclosurePanel } from '../thesis/DisclosurePanel'
import { ExportPanel } from '../thesis/ExportPanel'
import { StagePanel } from '../thesis/StagePanel'
import { ThesisChatPanel } from '../thesis/ThesisChatPanel'
import { WritingPanel } from '../thesis/WritingPanel'

const DEGREE_LABEL: Record<string, string> = {
  undergraduate: '本科',
  master: '硕士',
  doctor: '博士',
}

const CATEGORY_LABEL: Record<string, string> = {
  format: '格式',
  structure: '结构',
  citation: '引用',
}

type TabKey = 'issues' | 'stages' | 'writing' | 'citations' | 'disclosure' | 'export'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'issues', label: '问题' },
  { key: 'stages', label: '阶段' },
  { key: 'writing', label: '写作' },
  { key: 'citations', label: '引用' },
  { key: 'disclosure', label: 'AI 使用声明' },
  { key: 'export', label: '导出' },
]

const FIX_FIELD_LABEL: Record<string, string> = {
  page_width_cm: '页宽',
  page_height_cm: '页高',
  top_margin_cm: '上边距',
  bottom_margin_cm: '下边距',
  left_margin_cm: '左边距',
  right_margin_cm: '右边距',
  style: '样式',
  heading_level: '标题级别',
  text: '段落文本',
}

const INPUT_CLASS =
  'mt-1 w-full rounded-md border border-edge bg-base px-2.5 py-1.5 text-sm text-ink outline-none transition-colors duration-150 focus:border-accent'

const SEVERITY_META: Record<string, { label: string; tone: 'err' | 'warn' | 'dim'; dot: string }> = {
  blocker: { label: '阻断', tone: 'err', dot: 'bg-err' },
  warn: { label: '警告', tone: 'warn', dot: 'bg-warn' },
  info: { label: '提示', tone: 'dim', dot: 'bg-dim/60' },
}

type CreateForm = {
  title: string
  school: string
  degree: ThesisDegree
  templateId: string
}

function severityMeta(severity: string) {
  return SEVERITY_META[severity] ?? SEVERITY_META.info
}

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function shortHash(hash: string): string {
  return hash ? `${hash.slice(0, 12)}…` : '—'
}

function formatDate(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString('zh-CN', { hour12: false })
}

function locationText(location: Record<string, unknown>): string {
  if (typeof location.section === 'string') return location.section
  if (typeof location.paragraph_index === 'number') {
    return `第 ${location.paragraph_index + 1} 段`
  }
  if (typeof location.text === 'string' && location.text) return `「${location.text}」`
  return '全文'
}

function evidenceLines(issue: ThesisIssue): string[] {
  const evidence = issue.evidence
  const actual = evidence.actual as Record<string, unknown> | undefined
  const expected = evidence.expected as Record<string, unknown> | undefined
  const lines: string[] = []
  if (issue.rule_id === 'format.page_size') {
    if (actual) lines.push(`实际：${String(actual.width_cm)} × ${String(actual.height_cm)} cm`)
    if (expected) lines.push(`要求：${String(expected.width_cm)} × ${String(expected.height_cm)} cm`)
  } else if (issue.rule_id === 'format.margins') {
    const deviations = Array.isArray(evidence.deviations) ? evidence.deviations : []
    for (const item of deviations) {
      const row = item as Record<string, unknown>
      lines.push(`${String(row.side)}：${String(row.actual_cm)}cm（要求 ${String(row.expected_cm)}cm）`)
    }
  } else if (issue.rule_id === 'structure.heading_hierarchy') {
    if (evidence.previous_level !== undefined) {
      lines.push(`上一级：${String(evidence.previous_level)} 级`)
    }
    if (evidence.heading_level !== undefined) {
      lines.push(`当前：${String(evidence.heading_level)} 级`)
    }
    if (evidence.max_level !== undefined) {
      lines.push(`模板上限：${String(evidence.max_level)} 级`)
    }
  } else if (issue.rule_id === 'structure.heading_style') {
    lines.push(`当前样式：${String(evidence.style || '正文')}`)
  } else if (issue.rule_id === 'format.page_number') {
    lines.push('要求：页脚或页眉包含 Word 的 PAGE 域')
    if (evidence.footer_text) lines.push(`页脚文本：${String(evidence.footer_text)}`)
  } else if (issue.rule_id === 'structure.required_sections') {
    const patterns = Array.isArray(evidence.patterns) ? evidence.patterns : []
    if (patterns.length > 0) lines.push(`匹配词：${patterns.join(' / ')}`)
  } else if (issue.category === 'citation') {
    if (typeof evidence.raw === 'string') lines.push(`标注：${evidence.raw}`)
    if (Array.isArray(evidence.numbers)) {
      lines.push(`编号：${evidence.numbers.map((item) => `[${String(item)}]`).join('、')}`)
    }
    if (Array.isArray(evidence.examples)) {
      lines.push(`示例：${evidence.examples.map(String).slice(0, 5).join('；')}`)
    }
    if (Array.isArray(evidence.entries)) {
      lines.push(`条目：${evidence.entries.map(String).slice(0, 3).join('；')}`)
    }
  }
  return lines
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border border-edge bg-base/40 px-2.5 py-2">
      <p className="font-mono text-2xs uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-0.5 text-lg leading-tight text-ink">{value}</p>
    </div>
  )
}

function IssueCard({
  issue,
  fixing,
  onPreview,
  onApply,
  onUndo,
  onIgnore,
  onRestore,
}: {
  issue: ThesisIssue
  fixing: string | null
  onPreview: (issue: ThesisIssue) => void
  onApply: (issue: ThesisIssue) => void
  onUndo: (issue: ThesisIssue) => void
  onIgnore: (issue: ThesisIssue) => void
  onRestore: (issue: ThesisIssue) => void
}) {
  const meta = severityMeta(issue.severity)
  const evidence = evidenceLines(issue)
  const busy = fixing === issue.id
  const status = issue.status
  return (
    <article className="rounded-md border border-edge bg-panel/50 p-3">
      <div className="flex items-start gap-2">
        <span className={clsx('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', meta.dot)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium text-ink">{issue.title}</h3>
            <Badge tone={meta.tone}>{meta.label}</Badge>
            {status === 'fixed' && <Badge tone="ok">已修复</Badge>}
            {status === 'ignored' && <Badge tone="dim">已忽略</Badge>}
            <span className="font-mono text-2xs text-faint">{issue.rule_id}</span>
            {issue.confidence === 'medium' && (
              <span className="text-2xs text-warn">需人工确认</span>
            )}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-dim">{issue.detail}</p>
          <p className="mt-1.5 font-mono text-2xs text-faint">{locationText(issue.location)}</p>
          {evidence.length > 0 && (
            <div className="mt-2 rounded-sm border border-edge bg-base/40 px-2.5 py-2">
              <p className="font-mono text-2xs uppercase tracking-wide text-faint">证据</p>
              <ul className="mt-1 space-y-0.5 text-2xs leading-relaxed text-dim">
                {evidence.map((line, index) => <li key={`${issue.id}-${index}`}>{line}</li>)}
              </ul>
            </div>
          )}
          {issue.source && (
            <p className="mt-1.5 text-2xs leading-relaxed text-faint">依据：{issue.source}</p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-2">
            {status === 'open' && issue.fix_available && (
              <>
                <Button size="sm" onClick={() => onPreview(issue)} disabled={busy}>
                  {busy ? <Spinner /> : <Eye size={12} />} 预览修复
                </Button>
                <Button size="sm" variant="primary" onClick={() => onApply(issue)} disabled={busy}>
                  {busy ? <Spinner /> : <Check size={12} />} 应用修复
                </Button>
              </>
            )}
            {status === 'open' && (
              <Button size="sm" onClick={() => onIgnore(issue)} disabled={busy}>
                <EyeOff size={12} /> 忽略
              </Button>
            )}
            {status === 'fixed' && (
              <Button size="sm" onClick={() => onUndo(issue)} disabled={busy}>
                {busy ? <Spinner /> : <Undo2 size={12} />} 撤销修复
              </Button>
            )}
            {status === 'ignored' && (
              <Button size="sm" onClick={() => onRestore(issue)} disabled={busy}>
                <Undo2 size={12} /> 恢复
              </Button>
            )}
            {status === 'open' && !issue.fix_available && (
              <span className="text-2xs text-faint">此项需要按提示手动处理</span>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

export function ThesisWorkspaceView({ onOpenSettings }: { onOpenSettings: () => void }) {
  const {
    projects, templates, current, document, issues, fixes, citations, disclosures,
    report, scan, loading, busy, fixing, error,
    refresh, selectProject, createProject, removeProject, uploadDocument, scanProject,
    previewFix, applyFix, undoFix, setIssueStatus, clearError,
  } = useThesis()

  const [createOpen, setCreateOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('issues')
  const [chatOpen, setChatOpen] = useState(false)
  // CSS 隐藏的桌面 aside 仍会挂载组件；用媒体查询决定只渲染一份面板。
  const [desktopChat, setDesktopChat] = useState(
    () => window.matchMedia('(min-width: 1280px)').matches,
  )
  const [preview, setPreview] = useState<{ issue: ThesisIssue; data: ThesisFixPreview } | null>(null)
  const [previewLoading, setPreviewLoading] = useState<string | null>(null)
  const [form, setForm] = useState<CreateForm>({
    title: '',
    school: '',
    degree: 'undergraduate',
    templateId: '',
  })
  const fileRef = useRef<HTMLInputElement>(null)
  const mobileChatRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    void refresh()
  }, [refresh])

  // 桌面宽度下右侧栏常驻；关掉移动端抽屉，保证同一时间只挂载一份面板。
  useEffect(() => {
    const media = window.matchMedia('(min-width: 1280px)')
    const sync = () => {
      setDesktopChat(media.matches)
      if (media.matches) setChatOpen(false)
    }
    sync()
    media.addEventListener('change', sync)
    return () => media.removeEventListener('change', sync)
  }, [])

  // 移动端抽屉按对话框处理：Esc 关闭，打开后把焦点送进输入框。
  useEffect(() => {
    if (!chatOpen || desktopChat) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setChatOpen(false)
    }
    // 组件里的 `document` 是当前论文文档状态，DOM 必须走 window.document。
    window.document.addEventListener('keydown', onKey)
    const timer = window.setTimeout(() => {
      mobileChatRef.current
        ?.querySelector<HTMLElement>('textarea, select, button')
        ?.focus()
    }, 0)
    return () => {
      window.document.removeEventListener('keydown', onKey)
      window.clearTimeout(timer)
    }
  }, [chatOpen, desktopChat])

  useEffect(() => {
    if (loading || current || projects.length === 0) return
    void selectProject(projects[0].id)
  }, [loading, current, projects, selectProject])

  useEffect(() => {
    if (form.templateId || templates.length === 0) return
    setForm((value) => ({ ...value, templateId: templates[0].id }))
  }, [form.templateId, templates])

  const template = templates.find((item) => item.id === current?.template_id) ?? null
  const templateName = template?.name ?? '示例模板'
  const hasScanned = scan !== null || issues.length > 0
  const openIssues = issues.filter((issue) => issue.status === 'open')
  const fixedIssues = issues.filter((issue) => issue.status === 'fixed')
  const ignoredIssues = issues.filter((issue) => issue.status === 'ignored')
  const counts = {
    blocker: openIssues.filter((issue) => issue.severity === 'blocker').length,
    warn: openIssues.filter((issue) => issue.severity === 'warn').length,
    info: openIssues.filter((issue) => issue.severity === 'info').length,
    total: openIssues.length,
  }
  const citationIssueCount = (citations?.in_text ?? []).filter(
    (item) => item.status === 'missing_reference',
  ).length
  const visibleError = localError || error

  const updateForm = (patch: Partial<CreateForm>) => {
    setForm((value) => ({ ...value, ...patch }))
  }

  const openCreate = () => {
    setLocalError(null)
    clearError()
    setForm({
      title: '',
      school: '',
      degree: 'undergraduate',
      templateId: templates[0]?.id ?? '',
    })
    setCreateOpen(true)
  }

  const handleCreate = async () => {
    const title = form.title.trim()
    if (!title) {
      setLocalError('请填写论文题目')
      return
    }
    setLocalError(null)
    try {
      await createProject({
        title,
        school: form.school.trim(),
        degree: form.degree,
        template_id: form.templateId || undefined,
      })
      setCreateOpen(false)
    } catch {
      /* store.error 已包含失败原因 */
    }
  }

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.docx')) {
      setLocalError('只支持 .docx 文件；.doc 请先在 Word/WPS 中另存为 .docx')
      return
    }
    setLocalError(null)
    clearError()
    setUploading(true)
    try {
      await uploadDocument(file)
    } finally {
      setUploading(false)
    }
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    void handleFile(event.dataTransfer.files?.[0])
  }

  const handleDelete = async () => {
    if (!current) return
    if (!window.confirm(`删除「${current.title}」及其本地文件？此操作不可撤销。`)) return
    setLocalError(null)
    clearError()
    await removeProject(current.id)
  }

  const handleScan = async () => {
    setLocalError(null)
    clearError()
    await scanProject()
  }

  const handlePreview = async (issue: ThesisIssue) => {
    setLocalError(null)
    clearError()
    setPreviewLoading(issue.id)
    try {
      const data = await previewFix(issue.id)
      setPreview({ issue, data })
    } catch {
      /* store.error 已展示 */
    } finally {
      setPreviewLoading(null)
    }
  }

  const handleApply = async (issue: ThesisIssue) => {
    setLocalError(null)
    clearError()
    try {
      await applyFix(issue.id)
      setPreview(null)
    } catch {
      /* store.error 已展示 */
    }
  }

  const handleUndo = async (issue: ThesisIssue) => {
    if (!window.confirm('撤销这次修复并恢复到修复前的文档？')) return
    setLocalError(null)
    clearError()
    try {
      await undoFix(issue.id)
    } catch {
      /* store.error 已展示 */
    }
  }

  const handleIgnore = async (issue: ThesisIssue) => {
    setLocalError(null)
    clearError()
    try {
      await setIssueStatus(issue.id, 'ignored')
    } catch {
      /* store.error 已展示 */
    }
  }

  const handleRestore = async (issue: ThesisIssue) => {
    setLocalError(null)
    clearError()
    try {
      await setIssueStatus(issue.id, 'open')
    } catch {
      /* store.error 已展示 */
    }
  }

  return (
    <div className="flex h-full min-h-0 bg-base text-ink">
      <aside className="flex w-[248px] shrink-0 flex-col border-r border-edge bg-panel/40 sm:w-[280px]">
        <div className="flex items-center justify-between gap-2 border-b border-edge px-3 py-3">
          <div className="min-w-0">
            <p className="font-mono text-2xs uppercase tracking-[0.14em] text-faint">Thesis</p>
            <p className="truncate text-sm font-medium">我的论文</p>
          </div>
          <button
            onClick={openCreate}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-edge text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
            title="新建论文项目"
            aria-label="新建论文项目"
          >
            <Plus size={14} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {loading && projects.length === 0 ? (
            <div className="flex items-center gap-2 px-2 py-4 text-xs text-faint">
              <Spinner /> 加载中…
            </div>
          ) : projects.length === 0 ? (
            <div className="rounded-md border border-dashed border-edge px-3 py-6 text-center">
              <BookOpen size={18} className="mx-auto text-faint" />
              <p className="mt-2 text-sm text-dim">还没有论文项目</p>
              <button
                onClick={openCreate}
                className="mt-2 text-xs text-accent transition-colors duration-150 hover:text-ink"
              >
                新建一个
              </button>
            </div>
          ) : (
            projects.map((project) => {
              const active = project.id === current?.id
              const dot = project.status === 'failed' ? 'err' : project.status === 'ready' ? 'ok' : 'idle'
              return (
                <button
                  key={project.id}
                  onClick={() => void selectProject(project.id)}
                  aria-pressed={active}
                  className={clsx(
                    'mb-1 flex w-full flex-col rounded-md px-2 py-2 text-left transition-colors duration-150',
                    active ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                  )}
                >
                  <span className="flex w-full items-center gap-2">
                    <StatusDot state={dot} />
                    <span className="min-w-0 flex-1 truncate text-sm">{project.title}</span>
                    {project.open_issue_count > 0 && (
                      <span className="shrink-0 rounded-sm bg-warn/15 px-1.5 py-0.5 font-mono text-2xs text-warn">
                        {project.open_issue_count}
                      </span>
                    )}
                  </span>
                  <span className="mt-1 flex w-full items-center gap-1.5 pl-4 text-2xs text-faint">
                    <span>{DEGREE_LABEL[project.degree] ?? project.degree}</span>
                    {project.school && (
                      <>
                        <span>·</span>
                        <span className="truncate">{project.school}</span>
                      </>
                    )}
                  </span>
                </button>
              )
            })
          )}
        </div>

        <div className="space-y-2 border-t border-edge px-3 py-2.5 text-2xs leading-relaxed text-faint">
          <p>v0.2 · 格式 / 引用 / 声明 / 导出</p>
          <p>原始 DOCX 只读；修复写新版本，可撤销</p>
          <button
            onClick={onOpenSettings}
            className="flex items-center gap-1 text-dim transition-colors duration-150 hover:text-ink"
          >
            <Settings2 size={11} /> 模型与密钥
          </button>
        </div>
      </aside>

      <section className="min-h-0 min-w-0 flex-1 overflow-y-auto">
        {loading && !current ? (
          <div className="flex h-full items-center justify-center gap-2 font-mono text-sm text-dim">
            <Spinner /> 加载中…
          </div>
        ) : current ? (
          <div className="mx-auto max-w-6xl px-4 py-5 sm:px-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="truncate text-xl font-semibold text-ink">{current.title}</h1>
                  <Badge
                    tone={current.status === 'failed' ? 'err' : current.status === 'ready' ? 'ok' : 'dim'}
                  >
                    {current.status === 'failed' ? '解析失败' : current.status === 'ready' ? '可检查' : '待导入'}
                  </Badge>
                </div>
                <p className="mt-1 text-sm text-dim">
                  {current.school || '未填写学校'} · {DEGREE_LABEL[current.degree] ?? current.degree} · {templateName}
                  {template?.is_sample && (
                    <span className="ml-1 text-faint">（示例模板，非学校官方标准）</span>
                  )}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" className="xl:hidden" onClick={() => setChatOpen(true)}>
                  <MessageSquare size={13} /> AI 写作
                </Button>
                <Button size="sm" onClick={onOpenSettings}>
                  <Settings2 size={13} /> 模型设置
                </Button>
                <Button size="sm" variant="danger" onClick={() => void handleDelete()}>
                  <Trash2 size={13} /> 删除
                </Button>
              </div>
            </div>

            {visibleError && (
              <div className="mt-3 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-sm leading-relaxed text-err">
                {visibleError}
              </div>
            )}

            <div className="mt-3 flex items-start gap-2 rounded-md border border-accent/20 bg-accentSoft/20 px-3 py-2 text-xs leading-relaxed text-dim">
              <ShieldCheck size={14} className="mt-0.5 shrink-0 text-accent" />
              <p>
                <span className="font-mono text-accent">v0.2</span> 格式体检、引用 L1、AI 使用声明与定稿包导出。
                原始 DOCX 只读；每次修复都先备份，可逐条预览、应用和撤销。
              </p>
            </div>

            {!document ? (
              <div
                onDragOver={(event) => {
                  event.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                className={clsx(
                  'mt-5 rounded-lg border border-dashed p-6 text-center transition-colors duration-150',
                  dragging ? 'border-accent bg-accentSoft/20' : 'border-edge bg-panel/40',
                )}
              >
                <Upload size={22} className="mx-auto text-faint" />
                <p className="mt-2 text-sm text-ink">拖入 DOCX，或点击选择文件</p>
                <p className="mt-1 text-xs leading-relaxed text-faint">
                  只支持 .docx，最大 25MB；原始文件不会被修改。
                </p>
                <Button
                  variant="primary"
                  size="sm"
                  className="mt-3"
                  onClick={() => fileRef.current?.click()}
                  disabled={uploading || busy}
                >
                  {uploading ? <Spinner /> : <Upload size={13} />}
                  {uploading ? '解析中…' : '选择 DOCX'}
                </Button>
              </div>
            ) : (
              <div className="mt-5 rounded-lg border border-edge bg-panel/40 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex min-w-0 items-start gap-3">
                    <FileText size={18} className="mt-0.5 shrink-0 text-accent" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-ink">{document.filename}</p>
                      <p className="mt-1 font-mono text-2xs text-faint">
                        {formatBytes(document.size)} · SHA-256 {shortHash(document.sha256)}
                      </p>
                      <p className="mt-1 text-2xs text-faint">原文件保持不变；检查基于解析快照。</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={document.status === 'parsed' ? 'ok' : 'err'}>
                      {document.status === 'parsed' ? '已解析' : '解析失败'}
                    </Badge>
                    <Button
                      size="sm"
                      onClick={() => fileRef.current?.click()}
                      disabled={uploading || busy}
                    >
                      {uploading ? <Spinner /> : <Upload size={13} />} 重新导入
                    </Button>
                  </div>
                </div>

                {document.parse_error && (
                  <p className="mt-3 rounded-sm border border-err/30 bg-err/10 px-2.5 py-2 text-xs leading-relaxed text-err">
                    {document.parse_error}
                  </p>
                )}

                {document.status === 'parsed' && (
                  <>
                    <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <Stat label="段落" value={Number(document.stats.paragraph_count ?? 0)} />
                      <Stat label="标题" value={Number(document.stats.heading_count ?? 0)} />
                      <Stat label="表格" value={Number(document.stats.table_count ?? 0)} />
                      <Stat label="字符" value={Number(document.stats.char_count ?? 0)} />
                    </div>
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => void handleScan()}
                        disabled={busy}
                      >
                        {busy ? <Spinner /> : <ShieldCheck size={13} />}
                        {busy ? '检查中…' : hasScanned ? '重新检查' : '开始检查'}
                      </Button>
                      <span className="text-xs text-faint">使用模板：{templateName}</span>
                    </div>
                  </>
                )}
              </div>
            )}

            <input
              ref={fileRef}
              type="file"
              accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="hidden"
              onChange={(event) => {
                const input = event.currentTarget
                const file = input.files?.[0]
                input.value = ''
                void handleFile(file)
              }}
            />

            <div
              role="tablist"
              aria-label="论文工作区"
              className="mt-4 flex flex-wrap gap-1 rounded-md border border-edge bg-panel/40 p-1"
            >
              {TABS.map((item) => {
                const active = item.key === tab
                const badge = item.key === 'issues'
                  ? counts.total
                  : item.key === 'citations'
                    ? citationIssueCount
                    : item.key === 'disclosure'
                      ? disclosures.length
                      : item.key === 'export'
                        ? fixes.filter((fix) => !fix.undone_at).length
                        : 0
                return (
                  <button
                    key={item.key}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setTab(item.key)}
                    className={clsx(
                      'flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs transition-colors duration-150',
                      active ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                    )}
                  >
                    {item.label}
                    {badge > 0 && (
                      <span className={clsx(
                        'rounded-sm px-1 font-mono text-2xs',
                        item.key === 'citations' ? 'bg-err/15 text-err' : 'bg-raised text-faint',
                      )}>
                        {badge}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>

            {tab === 'issues' && (
            <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
              <div className="min-w-0 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-semibold text-ink">问题清单</h2>
                  {hasScanned ? (
                    <>
                      <Badge tone="err">{counts.blocker} 阻断</Badge>
                      <Badge tone="warn">{counts.warn} 警告</Badge>
                      <Badge tone="dim">{counts.info} 提示</Badge>
                      <span className="text-2xs text-faint">
                        待处理 {counts.total} 条
                        {fixedIssues.length > 0 && ` · 已修复 ${fixedIssues.length}`}
                        {ignoredIssues.length > 0 && ` · 已忽略 ${ignoredIssues.length}`}
                      </span>
                    </>
                  ) : (
                    <span className="text-xs text-faint">尚未检查</span>
                  )}
                </div>

                {!document ? (
                  <div className="rounded-md border border-edge bg-panel/40 px-3 py-4 text-xs leading-relaxed text-dim">
                    导入 DOCX 后，这里会列出页边距、纸张和标题层级等可复核的问题。
                  </div>
                ) : document.status !== 'parsed' ? (
                  <div className="rounded-md border border-err/30 bg-err/10 px-3 py-4 text-xs leading-relaxed text-err">
                    文档解析失败，暂时无法运行检查。请修复文件或重新导出为 .docx 后再试。
                  </div>
                ) : !hasScanned ? (
                  <div className="rounded-md border border-edge bg-panel/40 px-3 py-4 text-xs leading-relaxed text-dim">
                    还没有运行检查。点击上方「开始检查」，规则会逐条给出位置和证据。
                  </div>
                ) : openIssues.length === 0 ? (
                  <div className="rounded-md border border-ok/30 bg-ok/10 px-3 py-3">
                    <p className="flex items-center gap-2 text-sm text-ok">
                      <CheckCircle2 size={15} /> 未发现待处理的规则问题
                    </p>
                    <p className="mt-1 text-xs leading-relaxed text-dim">
                      这不等于论文一定合规：引用真实性、内容质量和学校特殊要求仍需人工确认。
                    </p>
                  </div>
                ) : (
                  (['blocker', 'warn', 'info'] as const).map((severity) => {
                    const group = openIssues.filter((issue) => issue.severity === severity)
                    if (group.length === 0) return null
                    const meta = severityMeta(severity)
                    return (
                      <div key={severity} className="space-y-2">
                        <p className="flex items-center gap-2 font-mono text-2xs uppercase tracking-wide text-faint">
                          <span className={clsx('h-1.5 w-1.5 rounded-full', meta.dot)} />
                          {meta.label} · {group.length}
                        </p>
                        {group.map((issue) => (
                          <IssueCard
                            key={issue.id}
                            issue={issue}
                            fixing={fixing ?? previewLoading}
                            onPreview={(item) => void handlePreview(item)}
                            onApply={(item) => void handleApply(item)}
                            onUndo={(item) => void handleUndo(item)}
                            onIgnore={(item) => void handleIgnore(item)}
                            onRestore={(item) => void handleRestore(item)}
                          />
                        ))}
                      </div>
                    )
                  })
                )}

                {(fixedIssues.length > 0 || ignoredIssues.length > 0) && (
                  <div className="space-y-2 pt-2">
                    <p className="font-mono text-2xs uppercase tracking-wide text-faint">
                      已处理 · {fixedIssues.length + ignoredIssues.length}
                    </p>
                    {[...fixedIssues, ...ignoredIssues].map((issue) => (
                      <IssueCard
                        key={issue.id}
                        issue={issue}
                        fixing={fixing ?? previewLoading}
                        onPreview={(item) => void handlePreview(item)}
                        onApply={(item) => void handleApply(item)}
                        onUndo={(item) => void handleUndo(item)}
                        onIgnore={(item) => void handleIgnore(item)}
                        onRestore={(item) => void handleRestore(item)}
                      />
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-4">
                <div className="rounded-lg border border-edge bg-panel/40">
                  <div className="flex items-center justify-between border-b border-edge px-3 py-2">
                    <h2 className="text-sm font-semibold text-ink">章节结构</h2>
                    <span className="font-mono text-2xs text-faint">{document?.outline.length ?? 0}</span>
                  </div>
                  <div className="max-h-[360px] overflow-y-auto p-2">
                    {!document ? (
                      <p className="px-1 py-2 text-xs text-faint">导入后显示</p>
                    ) : document.outline.length === 0 ? (
                      <p className="px-1 py-2 text-xs text-faint">未检测到标题样式</p>
                    ) : (
                      document.outline.map((node, index) => (
                        <div
                          key={`${node.block_index}-${index}`}
                          style={{ paddingLeft: `${Math.max(0, node.level - 1) * 14}px` }}
                          className="flex items-start gap-1.5 rounded-sm px-1 py-1 text-xs text-dim transition-colors duration-150 hover:bg-raised"
                          title={node.style}
                        >
                          <span className="mt-0.5 shrink-0 font-mono text-2xs text-faint">H{node.level}</span>
                          <span className="min-w-0 truncate">{node.text}</span>
                        </div>
                      ))
                    )}
                  </div>
                  {document && document.warnings.length > 0 && (
                    <div className="border-t border-edge px-3 py-2">
                      {document.warnings.map((warning, index) => (
                        <p key={index} className="text-2xs leading-relaxed text-faint">· {warning}</p>
                      ))}
                    </div>
                  )}
                </div>

                <div className="rounded-lg border border-edge bg-panel/40">
                  <div className="border-b border-edge px-3 py-2">
                    <h2 className="text-sm font-semibold text-ink">检查报告</h2>
                    <p className="mt-0.5 text-2xs text-faint">
                      {hasScanned
                        ? `生成于 ${formatDate(scan?.scanned_at ?? report?.generated_at)}`
                        : '运行检查后生成'}
                    </p>
                  </div>
                  <div className="space-y-2 p-3 text-xs">
                    {hasScanned ? (
                      <>
                        <div className="flex justify-between">
                          <span className="text-dim">阻断</span>
                          <span className="font-mono text-err">{counts.blocker}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-dim">警告</span>
                          <span className="font-mono text-warn">{counts.warn}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-dim">提示</span>
                          <span className="font-mono text-dim">{counts.info}</span>
                        </div>
                        <div className="border-t border-edge pt-2">
                          <p className="font-mono text-2xs uppercase tracking-wide text-faint">按类别</p>
                          {Object.entries(report?.by_category ?? {}).length === 0 ? (
                            <p className="mt-1 text-2xs text-faint">暂无</p>
                          ) : (
                            Object.entries(report?.by_category ?? {}).map(([category, count]) => (
                              <div key={category} className="mt-1 flex justify-between">
                                <span className="text-dim">{CATEGORY_LABEL[category] ?? category}</span>
                                <span className="font-mono text-ink">{count}</span>
                              </div>
                            ))
                          )}
                        </div>
                      </>
                    ) : (
                      <p className="text-xs leading-relaxed text-faint">
                        检查后会生成一份只包含确定性规则结果的报告。
                      </p>
                    )}
                    <p className="pt-1 text-2xs leading-relaxed text-faint">
                      报告覆盖格式、结构、引用 L1 与修复记录；页面级渲染仍需在 Word/WPS 中确认。
                    </p>
                  </div>
                </div>
              </div>
            </div>
            )}

            {tab === 'stages' && (
              <StagePanel project={current} />
            )}
            {tab === 'writing' && (
              <WritingPanel project={current} />
            )}
            {tab === 'citations' && (
              <div className="mt-4"><CitationPanel /></div>
            )}
            {tab === 'disclosure' && (
              <div className="mt-4"><DisclosurePanel /></div>
            )}
            {tab === 'export' && (
              <div className="mt-4"><ExportPanel /></div>
            )}
          </div>
        ) : (
          <EmptyState
            title="论文模式：体检、修复、交付"
            hint="导入一份 DOCX，检查格式与结构、核对引用标注、登记 AI 使用并导出定稿包。原文件不会被修改，不需要先配置模型。"
            action={(
              <Button variant="primary" onClick={openCreate}>
                <Plus size={14} /> 新建论文项目
              </Button>
            )}
          />
        )}
      </section>

      {desktopChat && (
        <aside className="flex w-[340px] shrink-0 flex-col border-l border-edge">
          {current ? (
            <ThesisChatPanel project={current} onOpenSettings={onOpenSettings} />
          ) : (
            <div className="flex h-full items-center justify-center px-4 text-center text-xs leading-relaxed text-faint">
              选择或新建一个论文项目后，就可以在这里与 AI 一起读项目、搭提纲、写章节草稿。
            </div>
          )}
        </aside>
      )}

      {!desktopChat && chatOpen && current && (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-black/50 xl:hidden"
          onClick={() => setChatOpen(false)}
        >
          <div
            ref={mobileChatRef}
            role="dialog"
            aria-modal="true"
            aria-label="写作对话"
            className="flex h-full w-[min(400px,94vw)] flex-col border-l border-edge bg-panel"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-edge px-3 py-2">
              <span className="font-mono text-2xs uppercase tracking-wide text-faint">写作对话</span>
              <button
                onClick={() => setChatOpen(false)}
                className="rounded-sm p-1 text-dim hover:text-ink"
                aria-label="关闭写作对话面板"
              >
                <X size={14} />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <ThesisChatPanel project={current} onOpenSettings={onOpenSettings} />
            </div>
          </div>
        </div>
      )}

      <Modal open={preview !== null} onClose={() => setPreview(null)} title="预览修复">
        {preview && (
          <div className="space-y-3">
            <p className="text-sm leading-relaxed text-ink">{preview.issue.title}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {(['before', 'after'] as const).map((side) => (
                <div key={side} className="rounded-md border border-edge bg-base/40 p-2.5">
                  <p className="font-mono text-2xs uppercase tracking-wide text-faint">
                    {side === 'before' ? '修复前' : '修复后'}
                  </p>
                  <div className="mt-1 space-y-1">
                    {Object.entries(preview.data[side]).map(([key, value]) => (
                      <p key={key} className="flex justify-between gap-2 text-2xs">
                        <span className="text-dim">{FIX_FIELD_LABEL[key] ?? key}</span>
                        <span className="min-w-0 truncate font-mono text-ink" title={String(value)}>
                          {String(value)}
                        </span>
                      </p>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="rounded-sm border border-edge bg-panel/40 px-2.5 py-2 text-2xs leading-relaxed text-dim">
              <p>
                内容校验：段数 {String(preview.data.verification.paragraph_count ?? '—')} ·
                字数 {String(preview.data.verification.char_count ?? '—')}（应与修复前一致）
              </p>
              <p className="mt-1">{preview.data.note}</p>
            </div>
            <div className="flex justify-end gap-2">
              <Button size="sm" onClick={() => setPreview(null)}>取消</Button>
              <Button
                size="sm"
                variant="primary"
                onClick={() => void handleApply(preview.issue)}
                disabled={fixing === preview.issue.id}
              >
                {fixing === preview.issue.id ? <Spinner /> : <Check size={13} />} 应用修复
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建论文项目">
        <div className="space-y-3">
          <label className="block text-xs text-dim">
            论文题目
            <input
              autoFocus
              value={form.title}
              onChange={(event) => updateForm({ title: event.target.value })}
              className={INPUT_CLASS}
              placeholder="例如：基于视觉的目标检测系统设计与实现"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-dim">
              学校（可选）
              <input
                value={form.school}
                onChange={(event) => updateForm({ school: event.target.value })}
                className={INPUT_CLASS}
                placeholder="例如：某某大学"
              />
            </label>
            <label className="block text-xs text-dim">
              学位
              <select
                value={form.degree}
                onChange={(event) => updateForm({ degree: event.target.value as ThesisDegree })}
                className={INPUT_CLASS}
              >
                <option value="undergraduate">本科</option>
                <option value="master">硕士</option>
                <option value="doctor">博士</option>
              </select>
            </label>
          </div>
          <label className="block text-xs text-dim">
            格式模板
            <select
              value={form.templateId}
              onChange={(event) => updateForm({ templateId: event.target.value })}
              className={INPUT_CLASS}
            >
              {templates.length === 0 && <option value="">加载模板中…</option>}
              {templates.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <p className="text-2xs leading-relaxed text-faint">
            当前只有示例模板，不对应任何具体学校。正式使用前请以学校最新文件为准。
          </p>
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void handleCreate()}
              disabled={!form.title.trim() || busy}
            >
              {busy ? <Spinner /> : <Plus size={13} />} 创建项目
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
