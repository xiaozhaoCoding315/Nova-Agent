import clsx from 'clsx'
import {
  AlertTriangle, ArrowRightLeft, CheckCircle2, Download, FileDown, FileText, History, Plus,
  RefreshCw, Save, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type {
  DocumentContent, DocumentConvertResult, DocumentDiagnostics, DocumentExportResult,
  DocumentFile, DocumentVersion, DocumentWorkspace as Workspace,
} from '../lib/types'
import { useMode } from '../stores/mode'

const KIND_LABEL: Record<Workspace['kind'], string> = {
  report: '报告',
  thesis: '论文',
  resume: '简历',
}

const STATUS_LABEL: Record<string, string> = {
  exact: '无损',
  partial: '部分保留',
  lossy: '有损',
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function slugName(value: string): string {
  const normalized = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5-]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return normalized || 'chapter'
}

export function DocumentWorkspace({ open, onClose }: { open: boolean; onClose: () => void }) {
  const localMode = useMode((state) => state.mode?.local ?? false)

  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [activeId, setActiveId] = useState('')
  const [files, setFiles] = useState<DocumentFile[]>([])
  const [activePath, setActivePath] = useState('')
  const [doc, setDoc] = useState<DocumentContent | null>(null)
  const [content, setContent] = useState('')
  const [versions, setVersions] = useState<DocumentVersion[]>([])
  const [exportResult, setExportResult] = useState<DocumentExportResult | null>(null)
  const [convertSource, setConvertSource] = useState('')
  const [convertTarget, setConvertTarget] = useState<'docx' | 'pdf'>('docx')
  const [convertProfile, setConvertProfile] = useState<Workspace['kind']>('report')
  const [convertLossy, setConvertLossy] = useState(false)
  const [convertResult, setConvertResult] = useState<DocumentConvertResult | null>(null)
  const [converting, setConverting] = useState(false)
  const [diagnostics, setDiagnostics] = useState<DocumentDiagnostics | null>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<Workspace['kind']>('report')
  const [root, setRoot] = useState('')
  const [newPath, setNewPath] = useState('')
  const [newFileOpen, setNewFileOpen] = useState(false)
  const [draftOpen, setDraftOpen] = useState(false)
  const [requirements, setRequirements] = useState('')
  const [wordCount, setWordCount] = useState('')
  const [drafting, setDrafting] = useState(false)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState<'docx' | 'pdf' | ''>('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const active = useMemo(
    () => workspaces.find((item) => item.id === activeId) ?? null,
    [workspaces, activeId],
  )
  const dirty = doc !== null && content !== doc.content

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !createOpen && !newFileOpen && !event.defaultPrevented) {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, createOpen, newFileOpen, onClose])

  const loadWorkspaces = async (preferId?: string) => {
    setLoading(true)
    setError('')
    try {
      const data = await api.documents.workspaces()
      setWorkspaces(data.workspaces)
      setActiveId((current) => preferId || current || data.workspaces[0]?.id || '')
      if (data.workspaces.length === 0) setCreateOpen(true)
    } catch (err) {
      setError(messageOf(err, '加载文档工作区失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void loadWorkspaces()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const loadFile = async (path: string) => {
    if (!activeId || !path) return
    setLoading(true)
    setError('')
    setExportResult(null)
    setConvertResult(null)
    setConvertSource(path)
    try {
      const [next, versionData] = await Promise.all([
        api.documents.content(activeId, path),
        api.documents.versions(activeId, path),
      ])
      setActivePath(path)
      setDoc(next)
      setContent(next.content)
      setVersions(versionData.versions)
    } catch (err) {
      setError(messageOf(err, '读取正文失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!activeId) return
    let cancelled = false
    setFiles([])
    setActivePath('')
    setDoc(null)
    setContent('')
    setVersions([])
    setExportResult(null)
    setDiagnostics(null)
    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const [fileData, diagData] = await Promise.all([
          api.documents.files(activeId),
          api.documents.diagnostics(activeId),
        ])
        if (cancelled) return
        setFiles(fileData.files)
        setDiagnostics(diagData)
        const first = fileData.files.find((item) => item.path.endsWith('main.md')) ?? fileData.files[0]
        if (first) void loadFile(first.path)
      } catch (err) {
        if (!cancelled) setError(messageOf(err, '加载文件列表失败'))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  const createWorkspace = async () => {
    if (!title.trim()) return
    setSaving(true)
    setError('')
    try {
      const workspace = await api.documents.createWorkspace({
        title: title.trim(),
        kind,
        root: localMode && root.trim() ? root.trim() : null,
      })
      setCreateOpen(false)
      setTitle('')
      setRoot('')
      setKind('report')
      setNotice('已创建工作区')
      await loadWorkspaces(workspace.id)
    } catch (err) {
      setError(messageOf(err, '创建工作区失败'))
    } finally {
      setSaving(false)
    }
  }

  const save = async () => {
    if (!activeId || !activePath) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const result = await api.documents.saveContent(activeId, {
        path: activePath,
        content,
        base_sha: doc?.sha256 ?? null,
      })
      const next = {
        ...(doc as DocumentContent), content, sha256: result.sha256,
        size: new TextEncoder().encode(content).length,
      }
      setDoc(next)
      setNotice('已保存')
      const fileData = await api.documents.files(activeId)
      setFiles(fileData.files)
      const versionData = await api.documents.versions(activeId, activePath)
      setVersions(versionData.versions)
    } catch (err) {
      setError(messageOf(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const createManuscript = async () => {
    if (!activeId) return
    const base = slugName(newPath || `chapter-${files.length + 1}`)
    const path = `manuscripts/${base.endsWith('.md') ? base : `${base}.md`}`
    setSaving(true)
    setError('')
    try {
      await api.documents.saveContent(activeId, {
        path,
        content: `# ${base.replace(/\.md$/, '')}\n\n`,
      })
      setNewFileOpen(false)
      setNewPath('')
      const fileData = await api.documents.files(activeId)
      setFiles(fileData.files)
      await loadFile(path)
    } catch (err) {
      setError(messageOf(err, '新建正文失败'))
    } finally {
      setSaving(false)
    }
  }

  const draftReport = async () => {
    if (!activeId || !requirements.trim()) return
    setDrafting(true)
    setError('')
    try {
      const result = await api.documents.draft(activeId, {
        requirements: requirements.trim(),
        path: 'manuscripts/report.md',
        word_count: wordCount.trim() ? Number(wordCount) : undefined,
      })
      const next: DocumentContent = {
        path: result.path, content: result.content, sha256: result.sha256,
        size: new TextEncoder().encode(result.content).length, last_known_sha: null,
      }
      setDraftOpen(false)
      setRequirements('')
      setWordCount('')
      setActivePath(result.path)
      setDoc(next)
      setContent(result.content)
      setNotice('初稿已写入 manuscripts/report.md；事实缺口以「待补充」标出，请核对后再导出。')
      const [fileData, versionData] = await Promise.all([
        api.documents.files(activeId),
        api.documents.versions(activeId, result.path),
      ])
      setFiles(fileData.files)
      setVersions(versionData.versions)
    } catch (err) {
      setError(messageOf(err, '起草失败'))
    } finally {
      setDrafting(false)
    }
  }

  const exportDocument = async (format: 'docx' | 'pdf') => {
    if (!activeId || !activePath) return
    setExporting(format)
    setError('')
    setExportResult(null)
    try {
      const result = await api.documents.export(activeId, { path: activePath, format })
      setExportResult(result)
    } catch (err) {
      setError(messageOf(err, '导出失败'))
    } finally {
      setExporting('')
    }
  }

  const convertDocument = async () => {
    if (!activeId || !convertSource.trim()) return
    setConverting(true)
    setError('')
    setConvertResult(null)
    try {
      const result = await api.documents.convert(activeId, {
        source_path: convertSource.trim(),
        target_format: convertTarget,
        profile: convertProfile,
        allow_lossy: convertLossy,
      })
      setConvertResult(result)
    } catch (err) {
      setError(messageOf(err, '转换失败'))
    } finally {
      setConverting(false)
    }
  }

  const restore = async (version: DocumentVersion) => {
    if (!activeId || !activePath || !doc) return
    if (!window.confirm(`恢复到 ${new Date(version.created_at).toLocaleString()} 的版本？当前内容会先存为版本。`)) return
    setSaving(true)
    setError('')
    try {
      await api.documents.restore(activeId, version.version_id, {
        path: activePath,
        base_sha: doc.sha256,
      })
      await loadFile(activePath)
      setNotice('已恢复，当前内容也保留在版本里')
    } catch (err) {
      setError(messageOf(err, '恢复版本失败'))
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  const fidelity = exportResult?.fidelity
  const fidelityStatus = typeof fidelity?.status === 'string' ? fidelity.status : ''

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-base text-ink">
      <header className="flex shrink-0 items-center gap-3 border-b border-edge px-3 py-2">
        <FileText size={16} className="text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">文档工作区</p>
          <p className="truncate font-mono text-2xs text-faint">
            {active ? `${active.title} · ${KIND_LABEL[active.kind]}${active.root ? ` · ${active.root}` : ''}` : 'Markdown 主控源，导出 DOCX/PDF'}
          </p>
        </div>
        <Badge tone={localMode ? 'warn' : 'dim'}>{localMode ? '本地目录' : '服务器存储'}</Badge>
        <button
          onClick={onClose}
          className="rounded-sm p-1 text-dim transition-colors hover:text-ink"
          aria-label="关闭文档工作区"
        >
          <X size={16} />
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="flex w-full shrink-0 flex-col border-b border-edge md:w-64 md:border-b-0 md:border-r">
          <div className="flex items-center gap-2 border-b border-edge px-2 py-2">
            <select
              value={activeId}
              onChange={(event) => setActiveId(event.target.value)}
              className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-1.5 py-1 text-xs text-dim outline-none focus:border-accent"
            >
              {workspaces.length === 0 && <option value="">还没有工作区</option>}
              {workspaces.map((item) => (
                <option key={item.id} value={item.id}>{item.title}</option>
              ))}
            </select>
            <button
              onClick={() => setCreateOpen(true)}
              className="rounded-sm border border-edge p-1 text-dim hover:text-ink"
              title="新建文档工作区"
              aria-label="新建文档工作区"
            >
              <Plus size={13} />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading && files.length === 0 ? (
              <p className="flex items-center gap-2 px-1 py-2 text-2xs text-faint"><Spinner /> 加载中…</p>
            ) : files.length === 0 ? (
              <p className="px-1 py-2 text-2xs leading-relaxed text-faint">还没有正文文件。</p>
            ) : (
              <ul className="space-y-0.5">
                {files.map((file) => (
                  <li key={file.path}>
                    <button
                      onClick={() => {
                        if (dirty && !window.confirm('当前正文有未保存修改，切换后丢失。继续？')) return
                        void loadFile(file.path)
                      }}
                      className={clsx(
                        'flex w-full items-center gap-1.5 rounded-sm px-1.5 py-1 text-left text-xs transition-colors',
                        file.path === activePath
                          ? 'bg-accentSoft/40 text-ink'
                          : 'text-dim hover:bg-raised hover:text-ink',
                      )}
                    >
                      <FileText size={12} className="shrink-0" />
                      <span className="min-w-0 flex-1 truncate">{file.path.replace('manuscripts/', '')}</span>
                      {file.path === activePath && dirty && <span className="text-2xs text-warn">未保存</span>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-edge p-2">
            {newFileOpen ? (
              <div className="space-y-1.5">
                <input
                  value={newPath}
                  onChange={(event) => setNewPath(event.target.value)}
                  placeholder="chapter-1"
                  className="w-full rounded-sm border border-edge bg-base px-2 py-1 text-xs outline-none focus:border-accent"
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void createManuscript()
                    if (event.key === 'Escape') setNewFileOpen(false)
                  }}
                  autoFocus
                />
                <div className="flex gap-1.5">
                  <Button size="sm" variant="primary" onClick={() => void createManuscript()} disabled={saving}>
                    新建
                  </Button>
                  <Button size="sm" onClick={() => setNewFileOpen(false)}>取消</Button>
                </div>
              </div>
            ) : (
              <Button
                size="sm"
                className="w-full"
                onClick={() => setNewFileOpen(true)}
                disabled={!activeId}
              >
                <Plus size={12} /> 新建正文
              </Button>
            )}
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
            <span className="min-w-0 flex-1 truncate font-mono text-2xs text-faint">
              {activePath || '选择一份正文'}
              {dirty && <span className="ml-2 text-warn">有未保存修改</span>}
            </span>
            <Button size="sm" onClick={() => activePath && void loadFile(activePath)} disabled={!activePath || loading}>
              <RefreshCw size={12} /> 重新载入
            </Button>
            <Button size="sm" variant="primary" onClick={() => void save()} disabled={!activePath || !dirty || saving}>
              {saving ? <Spinner /> : <Save size={12} />} 保存
            </Button>
            {active?.kind === 'report' && (
              <Button size="sm" onClick={() => setDraftOpen(true)} disabled={!!exporting || drafting}>
                <FileText size={12} /> 从要求起草
              </Button>
            )}
            <Button size="sm" onClick={() => void exportDocument('docx')} disabled={!activePath || !!exporting}>
              {exporting === 'docx' ? <Spinner /> : <FileDown size={12} />} DOCX
            </Button>
            <Button size="sm" onClick={() => void exportDocument('pdf')} disabled={!activePath || !!exporting}>
              {exporting === 'pdf' ? <Spinner /> : <FileDown size={12} />} PDF
            </Button>
          </div>

          {error && (
            <div className="flex shrink-0 items-start gap-2 border-b border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1">{error}</span>
              <button onClick={() => setError('')} className="underline">关闭</button>
            </div>
          )}
          {notice && (
            <div className="flex shrink-0 items-center gap-2 border-b border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok">
              <CheckCircle2 size={13} /> {notice}
              <button onClick={() => setNotice('')} className="ml-auto underline">关闭</button>
            </div>
          )}

          <textarea
            value={content}
            onChange={(event) => {
              setContent(event.target.value)
              setNotice('')
            }}
            disabled={!doc}
            spellCheck={false}
            placeholder={doc ? '' : '选择或新建一份 Markdown 正文'}
            className="min-h-0 flex-1 resize-none bg-base px-4 py-3 font-mono text-xs leading-6 text-ink outline-none placeholder:text-faint disabled:opacity-60"
          />
        </main>

        <aside className="w-full shrink-0 space-y-3 overflow-y-auto border-t border-edge p-3 md:w-80 md:border-t-0 md:border-l">
          <section>
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink"><History size={13} /> 版本</p>
            {versions.length === 0 ? (
              <p className="mt-1 text-2xs leading-relaxed text-faint">保存一次后，旧内容会出现在这里。</p>
            ) : (
              <ul className="mt-1.5 space-y-1">
                {versions.map((version) => (
                  <li key={version.version_id} className="rounded-sm border border-edge bg-panel/40 px-2 py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-2xs text-dim">
                        {new Date(version.created_at).toLocaleString()}
                      </span>
                      <button
                        onClick={() => void restore(version)}
                        className="text-2xs text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
                      >
                        恢复
                      </button>
                    </div>
                    <p className="mt-0.5 truncate font-mono text-2xs text-faint">
                      {version.sha256.slice(0, 12)} · {version.size} 字节
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink"><Download size={13} /> 导出</p>
            {!exportResult ? (
              <p className="mt-1 text-2xs leading-relaxed text-faint">
                导出副本写到 exports/，Markdown 源文件不变。PDF 是终态导出，不能反向编辑。
              </p>
            ) : (
              <div className="mt-1.5 rounded-sm border border-edge bg-panel/40 px-2 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={exportResult.status === 'done' ? 'ok' : exportResult.status === 'failed' ? 'err' : 'warn'}>
                    {exportResult.status === 'done' ? '已生成' : exportResult.status === 'failed' ? '失败' : '不支持'}
                  </Badge>
                  <span className="font-mono text-2xs uppercase text-faint">{exportResult.format}</span>
                  {fidelityStatus && (
                    <Badge tone={fidelityStatus === 'exact' ? 'ok' : 'warn'}>
                      保真：{STATUS_LABEL[fidelityStatus] ?? fidelityStatus}
                    </Badge>
                  )}
                </div>
                {exportResult.status === 'done' && exportResult.path && (
                  <button
                    onClick={() => activeId && exportResult.path && void api.documents.downloadExport(activeId, exportResult.path)}
                    className="mt-2 flex items-center gap-1 text-xs text-accent underline underline-offset-2"
                  >
                    <Download size={12} /> {exportResult.filename}
                  </button>
                )}
                {fidelity?.unsupported && fidelity.unsupported.length > 0 && (
                  <p className="mt-1.5 text-2xs leading-relaxed text-warn">
                    不支持：{fidelity.unsupported.join('、')}
                  </p>
                )}
                {exportResult.diagnostics.map((item) => (
                  <p key={item} className="mt-1 text-2xs leading-relaxed text-dim">{item}</p>
                ))}
                {fidelity?.notes?.map((item) => (
                  <p key={item} className="mt-1 text-2xs leading-relaxed text-faint">{item}</p>
                ))}
              </div>
            )}
          </section>

          <section>
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink"><ArrowRightLeft size={13} /> 格式转换</p>
            <p className="mt-1 text-2xs leading-relaxed text-faint">
              把工作区里的 Markdown 或 DOCX 转成 DOCX/PDF，输出同样写到 exports/。
              PDF 是终态，不能反向转回可编辑文档。
            </p>
            <div className="mt-1.5 space-y-1.5">
              <label className="block text-2xs text-dim">
                源文件
                <input
                  value={convertSource}
                  onChange={(event) => setConvertSource(event.target.value)}
                  placeholder="manuscripts/chapter-1.md"
                  className="mt-0.5 w-full rounded-sm border border-edge bg-base px-2 py-1 font-mono text-2xs text-ink outline-none placeholder:text-faint focus:border-accent"
                />
              </label>
              <div className="flex gap-1.5">
                <label className="min-w-0 flex-1 text-2xs text-dim">
                  目标格式
                  <select
                    value={convertTarget}
                    onChange={(event) => setConvertTarget(event.target.value as 'docx' | 'pdf')}
                    className="mt-0.5 w-full rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
                  >
                    <option value="docx">DOCX</option>
                    <option value="pdf">PDF</option>
                  </select>
                </label>
                <label className="min-w-0 flex-1 text-2xs text-dim">
                  版式
                  <select
                    value={convertProfile}
                    onChange={(event) => setConvertProfile(event.target.value as Workspace['kind'])}
                    className="mt-0.5 w-full rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
                  >
                    <option value="report">报告</option>
                    <option value="thesis">论文</option>
                    <option value="resume">简历</option>
                  </select>
                </label>
              </div>
              <label className="flex items-start gap-1.5 rounded-sm border border-warn/30 bg-warn/10 px-2 py-1.5 text-2xs leading-relaxed text-warn">
                <input
                  type="checkbox"
                  checked={convertLossy}
                  onChange={(event) => setConvertLossy(event.target.checked)}
                  className="mt-0.5"
                />
                <span>
                  允许有损转换。Markdown 里的原始 HTML 或公式可能丢失；默认会拒绝，
                  并先列出会丢失的内容。
                </span>
              </label>
              <Button
                size="sm"
                className="w-full"
                onClick={() => void convertDocument()}
                disabled={!activeId || !convertSource.trim() || converting}
              >
                {converting ? <Spinner /> : <ArrowRightLeft size={12} />} 开始转换
              </Button>
            </div>
            {convertResult && (
              <div className="mt-1.5 rounded-sm border border-edge bg-panel/40 px-2 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={convertResult.status === 'done' ? 'ok' : convertResult.status === 'failed' ? 'err' : 'warn'}>
                    {convertResult.status === 'done' ? '已生成' : convertResult.status === 'failed' ? '失败' : '不支持'}
                  </Badge>
                  {convertResult.fidelity?.status && (
                    <Badge tone={convertResult.fidelity.status === 'exact' ? 'ok' : 'warn'}>
                      保真：{STATUS_LABEL[convertResult.fidelity.status] ?? convertResult.fidelity.status}
                    </Badge>
                  )}
                </div>
                {convertResult.output_path && (
                  <button
                    onClick={() => activeId && convertResult.output_path && void api.documents.downloadExport(activeId, convertResult.output_path)}
                    className="mt-2 flex items-center gap-1 text-xs text-accent underline underline-offset-2"
                  >
                    <Download size={12} /> {convertResult.output_path.split('/').pop()}
                  </button>
                )}
                {convertResult.fidelity?.unsupported?.length > 0 && (
                  <p className="mt-1.5 text-2xs leading-relaxed text-warn">
                    不支持：{convertResult.fidelity.unsupported.join('、')}
                  </p>
                )}
                {convertResult.diagnostics.map((item) => (
                  <p key={item} className="mt-1 text-2xs leading-relaxed text-dim">{item}</p>
                ))}
                {convertResult.fidelity?.notes?.map((item) => (
                  <p key={item} className="mt-1 text-2xs leading-relaxed text-faint">{item}</p>
                ))}
              </div>
            )}
          </section>

          <section>
            <p className="text-xs font-medium text-ink">检查</p>
            {!diagnostics ? (
              <p className="mt-1 text-2xs text-faint">加载中…</p>
            ) : (
              <div className="mt-1.5 space-y-1 text-2xs leading-relaxed text-dim">
                <p>正文：{diagnostics.manuscripts} 份</p>
                <p>Pandoc：{diagnostics.tools.pandoc ? '可用' : '未安装'}；LibreOffice：{diagnostics.tools.libreoffice ? '可用' : '未安装'}</p>
                {Object.keys(diagnostics.unsupported).length > 0 ? (
                  <p className="text-warn">
                    不支持的对象：{Object.entries(diagnostics.unsupported).map(([key, value]) => `${key}×${value}`).join('、')}
                  </p>
                ) : (
                  <p>未发现不支持的对象。</p>
                )}
                {diagnostics.unreadable.map((item) => (
                  <p key={item} className="text-err">{item}</p>
                ))}
              </div>
            )}
          </section>
        </aside>
      </div>

      <Modal open={draftOpen} onClose={() => setDraftOpen(false)} title="从要求起草报告" width="max-w-xl">
        <div className="space-y-3">
          <label className="block text-xs text-dim">
            报告要求
            <textarea
              value={requirements}
              onChange={(event) => setRequirements(event.target.value)}
              rows={6}
              maxLength={8000}
              placeholder="例：写一份数据库课程设计报告，主题是校园二手交易系统。需要包含需求分析、数据库设计、关键表结构和测试结论。真实数据我还没填，先留空。"
              className="mt-1 w-full resize-y rounded-md border border-edge bg-base px-2.5 py-2 text-sm leading-relaxed text-ink outline-none focus:border-accent"
            />
          </label>
          <label className="block text-xs text-dim">
            目标字数（可选）
            <input
              value={wordCount}
              onChange={(event) => setWordCount(event.target.value.replace(/[^0-9]/g, ''))}
              placeholder="例如 3000"
              className="mt-1 w-full rounded-md border border-edge bg-base px-2.5 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
          <p className="rounded-sm border border-edge bg-base/40 px-2.5 py-2 text-2xs leading-relaxed text-faint">
            初稿写入 manuscripts/report.md。缺少的数据、姓名、日期和统计值会写成「待补充」，不会编造；
            这是一份普通报告草稿，需要你核对事实、补全材料后再导出。已存在同名文件时不会覆盖。
          </p>
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => setDraftOpen(false)} disabled={drafting}>取消</Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void draftReport()}
              disabled={!requirements.trim() || drafting}
            >
              {drafting ? <Spinner /> : <FileText size={12} />} 生成初稿
            </Button>
          </div>
        </div>
      </Modal>

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="新建文档工作区">
        <div className="space-y-3">
          <label className="block text-xs text-dim">
            名称
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={120}
              placeholder="例：课程设计报告"
              className="mt-1 w-full rounded-md border border-edge bg-base px-2.5 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
          <label className="block text-xs text-dim">
            类型
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as Workspace['kind'])}
              className="mt-1 w-full rounded-md border border-edge bg-base px-2.5 py-2 text-sm text-dim outline-none focus:border-accent"
            >
              <option value="report">报告</option>
              <option value="thesis">论文</option>
              <option value="resume">简历</option>
            </select>
          </label>
          {localMode && (
            <label className="block text-xs text-dim">
              本地目录（可留空，默认放在 Nova 数据目录）
              <input
                value={root}
                onChange={(event) => setRoot(event.target.value)}
                placeholder="D:\\Documents\\报告"
                className="mt-1 w-full rounded-md border border-edge bg-base px-2.5 py-2 font-mono text-xs text-ink outline-none focus:border-accent"
              />
              <span className="mt-1 block text-2xs leading-relaxed text-faint">
                目录不是空的且不是 Nova 工作区时会被拒绝，不会改动已有文件。
              </span>
            </label>
          )}
          <p className="text-2xs leading-relaxed text-faint">
            会创建 source/、manuscripts/、assets/、exports/ 与 .nova/。正文以 Markdown 保存，导出文件写到 exports/。
          </p>
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button size="sm" variant="primary" onClick={() => void createWorkspace()} disabled={!title.trim() || saving}>
              {saving ? <Spinner /> : <Plus size={12} />} 创建
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
