import clsx from 'clsx'
import { CheckCircle2, ChevronDown, ChevronRight, FileCode2, RefreshCw, Sparkles, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { BuilderPlan, BuilderProposal, RepoStatus } from '../lib/types'
import { Badge, Button, Spinner } from './common'

const PHASES = [
  ['plan', '方案'],
  ['code', '生成代码'],
  ['review', '审阅提案'],
  ['done', '写入项目'],
] as const

function phaseOf(status: RepoStatus): string {
  if (status === 'planning' || status === 'plan_ready' || status === 'failed') return 'plan'
  if (status === 'approved' || status === 'generating') return 'code'
  if (status === 'review') return 'review'
  return 'done'
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-4">
      <h4 className="mb-1.5 text-[12.5px] font-medium text-ink">{title}</h4>
      {children}
    </section>
  )
}

export function BuilderPanel({
  repoId,
  status,
  onChanged,
}: {
  repoId: string
  status: RepoStatus
  onChanged: () => void
}) {
  const [plan, setPlan] = useState<BuilderPlan | null>(null)
  const [proposal, setProposal] = useState<BuilderProposal | null>(null)
  const [localStatus, setLocalStatus] = useState<RepoStatus>(status)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [feedback, setFeedback] = useState('')
  const [openFiles, setOpenFiles] = useState<Record<string, boolean>>({})

  useEffect(() => {
    setLocalStatus(status)
  }, [status])

  const load = async () => {
    try {
      const planResp = await api.repos.getPlan(repoId)
      setPlan(planResp.plan && 'summary' in planResp.plan ? (planResp.plan as BuilderPlan) : null)
      setLocalStatus(planResp.status)
      setError(planResp.error ?? null)

      if (['review', 'approved', 'indexing', 'ready'].includes(planResp.status)) {
        const prop = await api.repos.getProposal(repoId)
        setProposal(
          prop.proposal && 'files' in prop.proposal ? (prop.proposal as BuilderProposal) : null,
        )
        if (prop.status) setLocalStatus(prop.status)
        if (prop.error) setError(prop.error)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载失败')
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  useEffect(() => {
    if (!['planning', 'generating'].includes(localStatus)) return
    const timer = setInterval(() => {
      void load()
      onChanged()
    }, 2500)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [localStatus])

  const act = async (kind: 'approve_plan' | 'regen_plan' | 'generate' | 'approve_proposal' | 'reject_redo') => {
    setBusy(kind)
    setError(null)
    try {
      if (kind === 'approve_plan') {
        await api.repos.approvePlan(repoId)
        setLocalStatus('approved')
      } else if (kind === 'regen_plan') {
        await api.repos.regeneratePlan(repoId)
        setProposal(null)
        setLocalStatus('planning')
      } else if (kind === 'generate') {
        await api.repos.generate(repoId, feedback.trim() || undefined)
        setLocalStatus('generating')
      } else if (kind === 'approve_proposal') {
        await api.repos.approveProposal(repoId)
        setProposal(null)
        setLocalStatus('indexing')
      } else {
        await api.repos.rejectProposal(repoId)
        setProposal(null)
        if (feedback.trim()) {
          await api.repos.generate(repoId, feedback.trim())
          setLocalStatus('generating')
        } else {
          setLocalStatus('approved')
        }
      }
      setFeedback('')
      onChanged()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(null)
    }
  }

  const currentPhase = phaseOf(localStatus)

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
        {PHASES.map(([key, label], i) => {
          const active = key === currentPhase
          const done = PHASES.findIndex(([k]) => k === currentPhase) > i
          return (
            <span key={key} className="flex items-center gap-1.5">
              <span
                className={clsx(
                  'rounded-full px-2.5 py-1',
                  active && 'bg-accentSoft/60 text-ink',
                  done && 'bg-ok/10 text-ok',
                  !active && !done && 'bg-raised text-dim',
                )}
              >
                {done ? '✓ ' : ''}
                {label}
              </span>
              {i < PHASES.length - 1 && <span className="text-dim/50">→</span>}
            </span>
          )
        })}
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-err/40 bg-err/5 p-2.5 text-[12.5px] text-err">{error}</p>
      )}

      {['planning', 'generating'].includes(localStatus) && (
        <p className="mt-6 flex items-center gap-2 text-[13px] text-dim">
          <Spinner /> {localStatus === 'planning' ? '正在生成项目方案…' : '正在生成项目文件…'}（约 10–40 秒）
        </p>
      )}

      {plan && (
        <>
          <Section title="方案概述">
            <p className="rounded-lg border border-edge bg-panel/50 p-3 text-[12.5px] leading-relaxed text-dim">
              {plan.summary}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {plan.stack.map((item) => (
                <Badge key={item} tone="accent">
                  {item}
                </Badge>
              ))}
            </div>
          </Section>

          {plan.structure.length > 0 && (
            <Section title="目录结构">
              <div className="overflow-hidden rounded-lg border border-edge">
                <table className="w-full text-[11.5px]">
                  <tbody>
                    {plan.structure.map((item) => (
                      <tr key={item.path} className="border-b border-edge/60 last:border-0">
                        <td className="w-1/2 px-2 py-1.5 font-mono text-accent">{item.path}</td>
                        <td className="px-2 py-1.5 text-dim">{item.purpose}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {plan.api.length > 0 && (
            <Section title="API 设计">
              <div className="overflow-hidden rounded-lg border border-edge">
                <table className="w-full text-[11.5px]">
                  <tbody>
                    {plan.api.map((item, i) => (
                      <tr key={`${item.method}-${item.path}-${i}`} className="border-b border-edge/60 last:border-0">
                        <td className="px-2 py-1.5 font-mono text-accent">{item.method}</td>
                        <td className="px-2 py-1.5 font-mono">{item.path}</td>
                        <td className="px-2 py-1.5 text-dim">{item.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
          )}

          {plan.data_model.length > 0 && (
            <Section title="数据模型">
              <div className="space-y-1.5">
                {plan.data_model.map((model) => (
                  <div key={model.table} className="rounded-lg border border-edge bg-panel/40 p-2.5">
                    <p className="font-mono text-[12px] text-ink">{model.table}</p>
                    <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-dim">
                      {model.fields.map((field) => (
                        <li key={field}>· {field}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {plan.milestones.length > 0 && (
            <Section title="里程碑">
              <ol className="space-y-1.5">
                {plan.milestones.map((ms, i) => (
                  <li key={`${ms.name}-${i}`} className="rounded-lg border border-edge bg-panel/40 p-2.5 text-[12px]">
                    <p className="font-medium">
                      {i + 1}. {ms.name}
                    </p>
                    <p className="mt-0.5 text-dim">{ms.tasks.join('；')}</p>
                    {ms.verification && (
                      <p className="mt-0.5 font-mono text-[11px] text-dim">验证：{ms.verification}</p>
                    )}
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {plan.risks.length > 0 && (
            <Section title="风险提示">
              <ul className="space-y-0.5 text-[12px] text-warn">
                {plan.risks.map((risk) => (
                  <li key={risk}>· {risk}</li>
                ))}
              </ul>
            </Section>
          )}
        </>
      )}

      {localStatus === 'plan_ready' && (
        <div className="mt-4 flex items-center gap-2">
          <Button variant="primary" onClick={() => void act('approve_plan')} disabled={busy !== null}>
            {busy === 'approve_plan' ? <Spinner /> : <CheckCircle2 size={13} />} 确认方案
          </Button>
          <Button onClick={() => void act('regen_plan')} disabled={busy !== null}>
            {busy === 'regen_plan' ? <Spinner /> : <RefreshCw size={13} />} 重新生成方案
          </Button>
        </div>
      )}

      {localStatus === 'approved' && (
        <div className="mt-4 rounded-lg border border-edge bg-panel/50 p-3">
          <p className="mb-2 text-[12px] text-dim">方案已确认。可以补充要求后生成代码（不填则直接生成）。</p>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={2}
            placeholder="例如：加上分页参数；错误统一返回 {code, message}"
            className="w-full resize-y rounded-lg border border-edge bg-raised px-2.5 py-2 text-[12.5px] outline-none placeholder:text-dim/50 focus:border-accentSoft"
          />
          <Button
            variant="primary"
            className="mt-2"
            onClick={() => void act('generate')}
            disabled={busy !== null}
          >
            {busy === 'generate' ? <Spinner /> : <Sparkles size={13} />} 生成项目文件
          </Button>
        </div>
      )}

      {localStatus === 'review' && proposal && (
        <div className="mt-4">
          <div className="flex items-center gap-2">
            <h3 className="text-[13px] font-medium">代码提案（{proposal.files.length} 个文件）</h3>
            <Badge tone="warn">待审阅</Badge>
          </div>
          {proposal.notes && (
            <p className="mt-1.5 rounded-lg border border-edge bg-panel/40 p-2.5 text-[12px] text-dim">
              {proposal.notes}
            </p>
          )}
          <div className="mt-2 space-y-1">
            {proposal.files.map((file) => {
              const open = openFiles[file.path]
              return (
                <div key={file.path} className="rounded-lg border border-edge bg-panel/40">
                  <button
                    className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
                    onClick={() => setOpenFiles((prev) => ({ ...prev, [file.path]: !prev[file.path] }))}
                  >
                    {open ? <ChevronDown size={12} className="text-dim" /> : <ChevronRight size={12} className="text-dim" />}
                    <FileCode2 size={12} className="text-accent" />
                    <span className="min-w-0 flex-1 truncate font-mono text-[11.5px]">{file.path}</span>
                    <span className="text-[10.5px] text-dim">{(file.content.length / 1024).toFixed(1)} KB</span>
                  </button>
                  {open && (
                    <pre className="max-h-80 overflow-auto border-t border-edge bg-[#0d1117] p-2.5 font-mono text-[11px] leading-relaxed">
                      {file.content}
                    </pre>
                  )}
                </div>
              )
            })}
          </div>
          <div className="mt-3 rounded-lg border border-edge bg-panel/50 p-3">
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={2}
              placeholder="审阅意见（填写后点「退回重做」会带上意见重新生成）"
              className="w-full resize-y rounded-lg border border-edge bg-raised px-2.5 py-2 text-[12.5px] outline-none placeholder:text-dim/50 focus:border-accentSoft"
            />
            <div className="mt-2 flex items-center gap-2">
              <Button
                variant="primary"
                onClick={() => void act('approve_proposal')}
                disabled={busy !== null}
              >
                {busy === 'approve_proposal' ? <Spinner /> : <CheckCircle2 size={13} />} 批准写入项目
              </Button>
              <Button variant="danger" onClick={() => void act('reject_redo')} disabled={busy !== null}>
                {busy === 'reject_redo' ? <Spinner /> : <XCircle size={13} />} 退回重做
              </Button>
              <span className="text-[11px] text-dim">写入后会自动建立索引</span>
            </div>
          </div>
        </div>
      )}

      {(localStatus === 'indexing' || localStatus === 'ready') && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-ok/30 bg-ok/5 p-3 text-[12.5px] text-ok">
          <CheckCircle2 size={14} />
          {localStatus === 'indexing'
            ? '已写入项目，正在建立索引…'
            : '项目已就绪：切到「代码」「项目地图」「影响分析」查看，或在对话里关联它提问。'}
        </div>
      )}

      {localStatus === 'failed' && (
        <div className="mt-4">
          <Button onClick={() => void act('regen_plan')} disabled={busy !== null}>
            {busy === 'regen_plan' ? <Spinner /> : <RefreshCw size={13} />} 重新生成方案
          </Button>
        </div>
      )}
    </div>
  )
}