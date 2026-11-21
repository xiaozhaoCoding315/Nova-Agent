import clsx from 'clsx'
import {
  AlertTriangle, Briefcase, CheckCircle2, Download, FileText, ListChecks, Plus,
  UserRound, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type {
  ResumeFact, ResumeFactStatus, ResumeJobVersion, ResumeProfile, ResumeProfileDetail,
  ResumeQuestion,
} from '../lib/types'

const STATUS_LABEL: Record<ResumeFactStatus, string> = {
  self_reported: '自述',
  evidence_linked: '有证据',
  needs_confirmation: '待确认',
  excluded: '不采用',
}

const STATUS_TONE: Record<ResumeFactStatus, 'ok' | 'warn' | 'err' | 'dim' | 'accent'> = {
  self_reported: 'dim',
  evidence_linked: 'ok',
  needs_confirmation: 'warn',
  excluded: 'err',
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function factStatus(value: string): ResumeFactStatus {
  return (['self_reported', 'evidence_linked', 'needs_confirmation', 'excluded']
    .includes(value) ? value : 'needs_confirmation') as ResumeFactStatus
}

export function ResumeWorkspace({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [profiles, setProfiles] = useState<ResumeProfile[]>([])
  const [activeId, setActiveId] = useState('')
  const [detail, setDetail] = useState<ResumeProfileDetail | null>(null)
  const [versions, setVersions] = useState<ResumeJobVersion[]>([])
  const [selectedVersion, setSelectedVersion] = useState<ResumeJobVersion | null>(null)
  const [markdown, setMarkdown] = useState('')
  const [questions, setQuestions] = useState<ResumeQuestion[]>([])
  const [audience, setAudience] = useState<'student' | 'tech'>('student')

  const [profileOpen, setProfileOpen] = useState(false)
  const [factOpen, setFactOpen] = useState(false)
  const [versionOpen, setVersionOpen] = useState(false)
  const [name, setName] = useState('')
  const [headline, setHeadline] = useState('')
  const [contact, setContact] = useState('')
  const [category, setCategory] = useState('项目')
  const [title, setTitle] = useState('')
  const [factDetail, setFactDetail] = useState('')
  const [metrics, setMetrics] = useState('')
  const [evidence, setEvidence] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [company, setCompany] = useState('')
  const [jdText, setJdText] = useState('')
  const [template, setTemplate] = useState('classic')
  const [selectedFacts, setSelectedFacts] = useState<string[]>([])

  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const active = useMemo(
    () => profiles.find((item) => item.id === activeId) ?? null,
    [profiles, activeId],
  )
  const includable = useMemo(
    () => (detail?.facts ?? []).filter((fact) => (
      fact.status === 'self_reported' || fact.status === 'evidence_linked'
    )),
    [detail],
  )

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !profileOpen && !factOpen && !versionOpen) {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, profileOpen, factOpen, versionOpen, onClose])

  const loadProfiles = async (preferId?: string) => {
    setLoading(true)
    setError('')
    try {
      const data = await api.resume.profiles()
      setProfiles(data.profiles)
      setActiveId((current) => preferId || current || data.profiles[0]?.id || '')
      if (data.profiles.length === 0) setProfileOpen(true)
    } catch (err) {
      setError(messageOf(err, '加载简历档案失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void loadProfiles()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const loadDetail = async (id: string) => {
    setLoading(true)
    setError('')
    setMarkdown('')
    setSelectedVersion(null)
    try {
      const data = await api.resume.profile(id)
      setDetail(data)
      setVersions(data.versions)
      setSelectedFacts(
        (data.facts || [])
          .filter((fact) => fact.status === 'self_reported' || fact.status === 'evidence_linked')
          .map((fact) => fact.id),
      )
    } catch (err) {
      setError(messageOf(err, '读取简历档案失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (activeId) void loadDetail(activeId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId])

  useEffect(() => {
    if (!open) return
    void api.resume.questions(audience)
      .then((data) => setQuestions(data.questions))
      .catch(() => setQuestions([]))
  }, [open, audience])

  const createProfile = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError('')
    try {
      const profile = await api.resume.createProfile({
        name: name.trim(),
        headline: headline.trim(),
        contact: contact.trim() ? { email: contact.trim() } : {},
      })
      setProfileOpen(false)
      setName('')
      setHeadline('')
      setContact('')
      setNotice('档案已创建；事实先录入，再生成岗位版本。')
      await loadProfiles(profile.id)
    } catch (err) {
      setError(messageOf(err, '创建档案失败'))
    } finally {
      setBusy(false)
    }
  }

  const addFact = async () => {
    if (!activeId || !title.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.resume.addFact(activeId, {
        category: category.trim() || '项目',
        title: title.trim(),
        detail: factDetail.trim(),
        metrics: metrics.split(/[，,、\n]/).map((item) => item.trim()).filter(Boolean),
        evidence: evidence.trim(),
        status: 'self_reported',
      })
      setFactOpen(false)
      setTitle('')
      setFactDetail('')
      setMetrics('')
      setEvidence('')
      setNotice('事实已加入。带数字但没有证据的条目会标为「待确认」。')
      await loadDetail(activeId)
    } catch (err) {
      setError(messageOf(err, '添加事实失败'))
    } finally {
      setBusy(false)
    }
  }

  const updateStatus = async (fact: ResumeFact, status: ResumeFactStatus) => {
    if (!activeId) return
    let nextEvidence = fact.evidence
    if (status === 'evidence_linked' && !nextEvidence.trim()) {
      const value = window.prompt('这条事实的证据是什么？例如仓库路径、证书、作品链接、老师评价。')
      if (!value?.trim()) return
      nextEvidence = value.trim()
    }
    setBusy(true)
    setError('')
    try {
      await api.resume.updateFact(activeId, fact.id, {
        status, evidence: nextEvidence,
      })
      setNotice('事实状态已更新')
      await loadDetail(activeId)
    } catch (err) {
      setError(messageOf(err, '更新事实失败'))
    } finally {
      setBusy(false)
    }
  }

  const createVersion = async () => {
    if (!activeId || !jobTitle.trim() || selectedFacts.length === 0) return
    setBusy(true)
    setError('')
    try {
      const version = await api.resume.createVersion(activeId, {
        title: jobTitle.trim(),
        company: company.trim(),
        jd_text: jdText.trim(),
        fact_ids: selectedFacts,
        template,
      })
      setVersionOpen(false)
      setJobTitle('')
      setCompany('')
      setJdText('')
      setNotice('岗位版本已生成；预览只包含你勾选的事实。')
      const data = await api.resume.profile(activeId)
      setDetail(data)
      setVersions(data.versions)
      setSelectedVersion(version)
      setMarkdown(version.markdown ?? '')
    } catch (err) {
      setError(messageOf(err, '生成岗位版本失败'))
    } finally {
      setBusy(false)
    }
  }

  const openVersion = async (version: ResumeJobVersion) => {
    setSelectedVersion(version)
    setMarkdown('')
    setError('')
    try {
      const data = await api.resume.version(version.id)
      setSelectedVersion(data)
      setMarkdown(data.markdown ?? '')
    } catch (err) {
      setError(messageOf(err, '读取岗位版本失败'))
    }
  }

  const download = async (format: 'md' | 'docx' | 'pdf') => {
    if (!selectedVersion) return
    setError('')
    try {
      if (format === 'md') await api.resume.downloadMarkdown(selectedVersion.id)
      else await api.resume.exportVersion(selectedVersion.id, format)
    } catch (err) {
      setError(messageOf(err, `导出 ${format.toUpperCase()} 失败`))
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-base text-ink">
      <header className="flex shrink-0 items-center gap-3 border-b border-edge px-3 py-2">
        <Briefcase size={16} className="text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">简历工作台</p>
          <p className="truncate font-mono text-2xs text-faint">
            {active ? `${active.name}${active.headline ? ` · ${active.headline}` : ''}` : '事实库 → 岗位版本 → 导出'}
          </p>
        </div>
        <Badge tone="warn">只重组你提供的事实</Badge>
        <button onClick={onClose} className="rounded-sm p-1 text-dim hover:text-ink" aria-label="关闭简历工作台">
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
              {profiles.length === 0 && <option value="">还没有档案</option>}
              {profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}</option>
              ))}
            </select>
            <button
              onClick={() => setProfileOpen(true)}
              className="rounded-sm border border-edge p-1 text-dim hover:text-ink"
              aria-label="新建简历档案"
            >
              <Plus size={13} />
            </button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <p className="px-1 pb-1 text-2xs text-faint">岗位版本</p>
            {versions.length === 0 ? (
              <p className="px-1 py-2 text-2xs leading-relaxed text-faint">
                还没有岗位版本。先录入事实，再按 JD 生成一版。
              </p>
            ) : (
              <ul className="space-y-0.5">
                {versions.map((version) => (
                  <li key={version.id}>
                    <button
                      onClick={() => void openVersion(version)}
                      className={clsx(
                        'w-full rounded-sm px-1.5 py-1 text-left text-xs transition-colors',
                        version.id === selectedVersion?.id
                          ? 'bg-accentSoft/40 text-ink'
                          : 'text-dim hover:bg-raised hover:text-ink',
                      )}
                    >
                      <span className="block truncate">{version.title}</span>
                      <span className="block truncate text-2xs text-faint">
                        {version.company || '未填公司'} · {new Date(version.created_at).toLocaleDateString()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-edge p-2">
            <Button
              size="sm"
              className="w-full"
              onClick={() => setVersionOpen(true)}
              disabled={!activeId || includable.length === 0}
            >
              <Plus size={12} /> 新建岗位版本
            </Button>
          </div>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
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

          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {loading && !detail ? (
              <p className="flex items-center gap-2 text-xs text-faint"><Spinner /> 加载…</p>
            ) : !detail ? (
              <p className="text-xs text-faint">先创建或选择一个简历档案。</p>
            ) : (
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
                <div className="space-y-3">
                  <section className="rounded-lg border border-edge bg-panel/40 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="flex items-center gap-1.5 text-sm font-medium"><UserRound size={14} /> 事实库</p>
                      <span className="text-2xs text-faint">{detail.facts.length} 条</span>
                      <Button size="sm" className="ml-auto" onClick={() => setFactOpen(true)}>
                        <Plus size={12} /> 添加事实
                      </Button>
                    </div>
                    <p className="mt-1 text-2xs leading-relaxed text-faint">
                      数字必须有证据；没有证据的条目会停在「待确认」，不会进入岗位版本。
                    </p>
                    {detail.facts.length === 0 ? (
                      <p className="mt-2 text-xs text-faint">还没有事实。课程项目、社团、实习、竞赛都可以是事实。</p>
                    ) : (
                      <ul className="mt-2 space-y-1.5">
                        {detail.facts.map((fact) => (
                          <li key={fact.id} className="rounded-md border border-edge bg-base/40 px-2.5 py-2">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Badge tone={STATUS_TONE[factStatus(fact.status)]}>
                                {STATUS_LABEL[factStatus(fact.status)]}
                              </Badge>
                              <span className="text-2xs text-faint">{fact.category}</span>
                              <span className="min-w-0 flex-1 truncate text-xs text-ink">{fact.title}</span>
                              <select
                                value={fact.status}
                                onChange={(event) => void updateStatus(fact, event.target.value as ResumeFactStatus)}
                                className="rounded-sm border border-edge bg-base px-1 py-0.5 text-2xs text-dim outline-none focus:border-accent"
                              >
                                <option value="self_reported">自述</option>
                                <option value="evidence_linked">有证据</option>
                                <option value="needs_confirmation">待确认</option>
                                <option value="excluded">不采用</option>
                              </select>
                            </div>
                            {fact.detail && <p className="mt-1 text-2xs leading-relaxed text-dim">{fact.detail}</p>}
                            {fact.metrics.length > 0 && (
                              <p className="mt-1 font-mono text-2xs text-warn">{fact.metrics.join(' · ')}</p>
                            )}
                            {fact.evidence && (
                              <p className="mt-1 text-2xs text-ok">证据：{fact.evidence}</p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>

                  <section className="rounded-lg border border-edge bg-panel/40 p-3">
                    <p className="flex items-center gap-1.5 text-sm font-medium">
                      <FileText size={14} /> 岗位版本预览
                    </p>
                    {!selectedVersion ? (
                      <p className="mt-1 text-2xs leading-relaxed text-faint">
                        选一个岗位版本，或新建一版。预览只包含事实库中勾选且可用的条目。
                      </p>
                    ) : (
                      <>
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          <span className="text-xs text-ink">{selectedVersion.title}</span>
                          <span className="text-2xs text-faint">{selectedVersion.company}</span>
                          <Button size="sm" className="ml-auto" onClick={() => void download('md')}>
                            <Download size={12} /> MD
                          </Button>
                          <Button size="sm" onClick={() => void download('docx')}>
                            <Download size={12} /> DOCX
                          </Button>
                          <Button size="sm" onClick={() => void download('pdf')}>
                            <Download size={12} /> PDF
                          </Button>
                        </div>
                        <pre className="mt-2 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-md border border-edge bg-base px-3 py-2 font-mono text-2xs leading-6 text-dim">
                          {markdown || '载入中…'}
                        </pre>
                      </>
                    )}
                  </section>
                </div>

                <aside className="space-y-3">
                  <section className="rounded-lg border border-edge bg-panel/40 p-3">
                    <p className="flex items-center gap-1.5 text-sm font-medium">
                      <ListChecks size={14} /> STAR 提问
                    </p>
                    <div className="mt-1 flex gap-1">
                      <button
                        onClick={() => setAudience('student')}
                        className={clsx(
                          'rounded-sm border px-1.5 py-1 text-2xs',
                          audience === 'student' ? 'border-accent/50 bg-accentSoft/40 text-ink' : 'border-edge text-faint',
                        )}
                      >
                        零经验学生
                      </button>
                      <button
                        onClick={() => setAudience('tech')}
                        className={clsx(
                          'rounded-sm border px-1.5 py-1 text-2xs',
                          audience === 'tech' ? 'border-accent/50 bg-accentSoft/40 text-ink' : 'border-edge text-faint',
                        )}
                      >
                        技术岗
                      </button>
                    </div>
                    <ol className="mt-2 space-y-1.5 text-2xs leading-relaxed text-dim">
                      {questions.map((item, index) => (
                        <li key={item.key}>
                          <span className="font-mono text-faint">{index + 1}. </span>{item.question}
                        </li>
                      ))}
                    </ol>
                  </section>

                  <section className="rounded-lg border border-edge bg-panel/40 p-3 text-2xs leading-relaxed text-faint">
                    <p className="text-xs font-medium text-ink">边界</p>
                    <p className="mt-1.5">
                      简历只重组你录入的事实。没有证据的数字会先停在「待确认」；
                      导出不会自动投递，也不承诺 ATS 通过率。请自己在 Word 中检查版式。
                    </p>
                  </section>
                </aside>
              </div>
            )}
          </div>
        </main>
      </div>

      <Modal open={profileOpen} onClose={() => setProfileOpen(false)} title="新建简历档案">
        <div className="space-y-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="姓名"
            className="w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
          />
          <input
            value={headline}
            onChange={(event) => setHeadline(event.target.value)}
            placeholder="一句话定位，例如：计算机专业本科生，找后端实习"
            className="w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
          />
          <input
            value={contact}
            onChange={(event) => setContact(event.target.value)}
            placeholder="邮箱（可选）"
            className="w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
          />
          <Button variant="primary" size="sm" onClick={() => void createProfile()} disabled={busy || !name.trim()}>
            {busy ? <Spinner /> : null} 创建
          </Button>
        </div>
      </Modal>

      <Modal open={factOpen} onClose={() => setFactOpen(false)} title="添加事实">
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              placeholder="分类：项目 / 实习 / 社团 / 竞赛"
              className="w-40 rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
            />
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="标题，例如：校园二手交易平台"
              className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
            />
          </div>
          <textarea
            value={factDetail}
            onChange={(event) => setFactDetail(event.target.value)}
            rows={3}
            placeholder="你具体做了什么，解决什么问题。只写真实发生的事。"
            className="w-full resize-y rounded-sm border border-edge bg-base px-2 py-1.5 text-xs leading-relaxed outline-none focus:border-accent"
          />
          <input
            value={metrics}
            onChange={(event) => setMetrics(event.target.value)}
            placeholder="数字结果，用逗号分隔；没有就留空"
            className="w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
          />
          <input
            value={evidence}
            onChange={(event) => setEvidence(event.target.value)}
            placeholder="证据：仓库、证书、链接、老师评价（有数字时必填）"
            className="w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
          />
          <Button variant="primary" size="sm" onClick={() => void addFact()} disabled={busy || !title.trim()}>
            {busy ? <Spinner /> : null} 添加
          </Button>
        </div>
      </Modal>

      <Modal open={versionOpen} onClose={() => setVersionOpen(false)} title="新建岗位版本">
        <div className="space-y-2">
          <div className="flex gap-2">
            <input
              value={jobTitle}
              onChange={(event) => setJobTitle(event.target.value)}
              placeholder="职位名称"
              className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
            />
            <input
              value={company}
              onChange={(event) => setCompany(event.target.value)}
              placeholder="公司（可选）"
              className="w-36 rounded-sm border border-edge bg-base px-2 py-1.5 text-xs outline-none focus:border-accent"
            />
          </div>
          <textarea
            value={jdText}
            onChange={(event) => setJdText(event.target.value)}
            rows={4}
            placeholder="粘贴 JD（可选，会保存快照）"
            className="w-full resize-y rounded-sm border border-edge bg-base px-2 py-1.5 text-xs leading-relaxed outline-none focus:border-accent"
          />
          <div className="flex items-center gap-2 text-2xs text-faint">
            模板
            <select
              value={template}
              onChange={(event) => setTemplate(event.target.value)}
              className="rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
            >
              <option value="classic">classic</option>
              <option value="modern">modern</option>
              <option value="compact">compact</option>
            </select>
          </div>
          <div className="max-h-44 space-y-1 overflow-y-auto rounded-sm border border-edge bg-base/40 p-2">
            {includable.length === 0 ? (
              <p className="text-2xs text-faint">没有可用事实。先确认证据或去掉待确认的数字。</p>
            ) : includable.map((fact) => (
              <label key={fact.id} className="flex items-start gap-2 text-2xs text-dim">
                <input
                  type="checkbox"
                  checked={selectedFacts.includes(fact.id)}
                  onChange={(event) => setSelectedFacts((current) => (
                    event.target.checked
                      ? [...current, fact.id]
                      : current.filter((id) => id !== fact.id)
                  ))}
                  className="mt-0.5"
                />
                <span><b className="text-ink">{fact.title}</b> · {fact.category}</span>
              </label>
            ))}
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void createVersion()}
            disabled={busy || !jobTitle.trim() || selectedFacts.length === 0}
          >
            {busy ? <Spinner /> : null} 生成
          </Button>
        </div>
      </Modal>
    </div>
  )
}
