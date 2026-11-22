import clsx from 'clsx'
import {
  AlertTriangle, CheckCircle2, FileCheck2, GitCompare, RefreshCw, ShieldCheck, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type {
  EnvironmentComparison, EvidenceClaim, EvidencePack, EvidencePackSummary,
  EvidenceVerifyResult,
} from '../lib/types'
import { useRepos } from '../stores/repos'

const CLAIM_STATUS: Record<string, { label: string; tone: 'ok' | 'warn' | 'err' | 'dim' }> = {
  confirmed: { label: '已证实', tone: 'ok' },
  failed: { label: '失败', tone: 'err' },
  not_run: { label: '未运行', tone: 'warn' },
  unsupported: { label: '不支持', tone: 'warn' },
  unverified: { label: '未证实', tone: 'dim' },
}

const CLAIM_KIND: Record<string, string> = {
  code_fact: '代码事实',
  test_result: '测试结果',
  human_note: '人工说明',
  unverified: '未核实',
}

const DIMENSION_LABEL: Record<string, string> = {
  os: '操作系统',
  arch: '架构',
  isolation: '隔离',
  network: '网络',
  image_digest: '镜像摘要',
  tool_versions: '工具版本',
  working_dir: '工作目录',
}

const COMPARE_TONE: Record<string, 'ok' | 'warn' | 'err'> = {
  same: 'ok',
  different: 'err',
  unknown: 'warn',
}

const COMPARE_LABEL: Record<string, string> = {
  same: '一致',
  different: '不同',
  unknown: '无法确认',
}

const SAMPLE_LOCAL = '{"mode":"host","os":"windows","arch":"x86_64","isolation":"none","network":"enabled"}'
const SAMPLE_CONTAINER = '{"mode":"container","os":"linux","arch":"x86_64","isolation":"container","network":"disabled"}'

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function claimStatus(value: string) {
  return CLAIM_STATUS[value] ?? CLAIM_STATUS.unverified
}

function showValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未记录'
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return '未记录'
    return entries.map(([key, item]) => `${key}=${String(item)}`).join('、')
  }
  return String(value)
}

function claimLine(claim: EvidenceClaim): string {
  if (!claim.path) return ''
  return claim.line ? `${claim.path}:${claim.line}` : claim.path
}

export function EvidenceWorkspace({ open, onClose }: { open: boolean; onClose: () => void }) {
  const repos = useRepos((state) => state.repos)
  const readyRepos = useMemo(() => repos.filter((repo) => repo.status === 'ready'), [repos])

  const [packs, setPacks] = useState<EvidencePackSummary[]>([])
  const [pack, setPack] = useState<EvidencePack | null>(null)
  const [activeId, setActiveId] = useState('')
  const [repoId, setRepoId] = useState('')
  const [verification, setVerification] = useState<EvidenceVerifyResult | null>(null)
  const [buildOpen, setBuildOpen] = useState(false)
  const [claimsJson, setClaimsJson] = useState('')
  const [artifactPaths, setArtifactPaths] = useState('')
  const [environmentJson, setEnvironmentJson] = useState('')

  const [compareOpen, setCompareOpen] = useState(false)
  const [localJson, setLocalJson] = useState(SAMPLE_LOCAL)
  const [containerJson, setContainerJson] = useState(SAMPLE_CONTAINER)
  const [comparison, setComparison] = useState<EnvironmentComparison | null>(null)

  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !compareOpen && !event.defaultPrevented) {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, compareOpen, onClose])

  const loadPacks = async (preferId?: string) => {
    setLoading(true)
    setError('')
    try {
      const data = await api.evidence.packs()
      setPacks(data.packs)
      setActiveId((current) => preferId || current || data.packs[0]?.pack_id || '')
    } catch (err) {
      setError(messageOf(err, '加载证据包失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) void loadPacks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!repoId && readyRepos.length > 0) setRepoId(readyRepos[0].id)
  }, [readyRepos, repoId])

  useEffect(() => {
    if (!activeId) {
      setPack(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    setVerification(null)
    api.evidence
      .pack(activeId)
      .then((data) => {
        if (!cancelled) setPack(data)
      })
      .catch((err) => {
        if (!cancelled) setError(messageOf(err, '读取证据包失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [activeId])

  const buildPack = async () => {
    if (!repoId) return
    setError('')
    let claims: Record<string, unknown>[] | undefined
    if (claimsJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(claimsJson)
        if (!Array.isArray(parsed)) throw new Error('not an array')
        claims = parsed as Record<string, unknown>[]
      } catch {
        setError('自定义主张必须是 JSON 数组，例如 [{"kind":"human_note","text":"..."}]')
        return
      }
    }
    let environment: Record<string, unknown> | undefined
    if (environmentJson.trim()) {
      try {
        const parsed: unknown = JSON.parse(environmentJson)
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('not an object')
        }
        environment = parsed as Record<string, unknown>
      } catch {
        setError('环境描述必须是 JSON 对象')
        return
      }
    }
    setBusy(true)
    try {
      const created = await api.evidence.build(repoId, {
        claims,
        artifact_paths: artifactPaths
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean),
        environment,
      })
      setActiveId(created.pack_id)
      setPack(created)
      await loadPacks(created.pack_id)
      setBuildOpen(false)
    } catch (err) {
      setError(messageOf(err, '生成证据包失败'))
    } finally {
      setBusy(false)
    }
  }

  const verifyPack = async () => {
    if (!activeId) return
    setBusy(true)
    setError('')
    setVerification(null)
    try {
      setVerification(await api.evidence.verify(activeId))
    } catch (err) {
      setError(messageOf(err, '核对证据包失败'))
    } finally {
      setBusy(false)
    }
  }

  const compare = async () => {
    setBusy(true)
    setError('')
    setComparison(null)
    try {
      let local: Record<string, unknown>
      let container: Record<string, unknown>
      try {
        local = JSON.parse(localJson)
        container = JSON.parse(containerJson)
      } catch {
        setError('环境描述不是有效的 JSON')
        return
      }
      setComparison(await api.evidence.compare(local, container))
    } catch (err) {
      setError(messageOf(err, '环境对比失败'))
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-base text-ink">
      <header className="flex shrink-0 items-center gap-3 border-b border-edge px-3 py-2">
        <ShieldCheck size={16} className="text-accent" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">证据包</p>
          <p className="truncate font-mono text-2xs text-faint">
            {pack ? `${pack.pack_id}${pack.commit ? ` · ${pack.commit.slice(0, 10)}` : ''}` : '验证结果 → 主张、工件与环境'}
          </p>
        </div>
        <Badge tone="warn">未记录 ≠ 一致</Badge>
        <button
          onClick={onClose}
          className="rounded-sm p-1 text-dim transition-colors hover:text-ink"
          aria-label="关闭证据包"
        >
          <X size={16} />
        </button>
      </header>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="flex w-full shrink-0 flex-col border-b border-edge md:w-64 md:border-b-0 md:border-r">
          <div className="space-y-1.5 border-b border-edge p-2">
            <select
              value={repoId}
              onChange={(event) => setRepoId(event.target.value)}
              className="w-full rounded-sm border border-edge bg-base px-1.5 py-1 text-xs text-dim outline-none focus:border-accent"
            >
              {readyRepos.length === 0 && <option value="">还没有就绪的仓库</option>}
              {readyRepos.map((repo) => (
                <option key={repo.id} value={repo.id}>{repo.name}</option>
              ))}
            </select>
            <Button
              size="sm"
              className="w-full"
              onClick={() => void buildPack()}
              disabled={!repoId || busy}
            >
              {busy ? <Spinner /> : <RefreshCw size={12} />} 从验证结果生成
            </Button>
            <button
              onClick={() => setBuildOpen((value) => !value)}
              className="text-left text-2xs text-accent underline underline-offset-2"
            >
              {buildOpen ? '收起自定义输入' : '高级：自定义主张 / 工件 / 环境'}
            </button>
            {buildOpen && (
              <div className="space-y-1.5 rounded-sm border border-edge bg-base/40 p-2">
                <label className="block text-2xs text-dim">
                  自定义主张（JSON 数组，可选）
                  <textarea
                    value={claimsJson}
                    onChange={(event) => setClaimsJson(event.target.value)}
                    rows={3}
                    placeholder='[{"kind":"human_note","statement":"我手工验证了导出"}]'
                    className="mt-0.5 w-full resize-y rounded-sm border border-edge bg-base px-1.5 py-1 font-mono text-2xs text-ink outline-none placeholder:text-faint focus:border-accent"
                  />
                </label>
                <label className="block text-2xs text-dim">
                  工件路径（每行一个，相对仓库根目录）
                  <textarea
                    value={artifactPaths}
                    onChange={(event) => setArtifactPaths(event.target.value)}
                    rows={2}
                    placeholder={'dist/report.pdf\nlogs/test.log'}
                    className="mt-0.5 w-full resize-y rounded-sm border border-edge bg-base px-1.5 py-1 font-mono text-2xs text-ink outline-none placeholder:text-faint focus:border-accent"
                  />
                </label>
                <label className="block text-2xs text-dim">
                  环境描述（JSON 对象，可选）
                  <textarea
                    value={environmentJson}
                    onChange={(event) => setEnvironmentJson(event.target.value)}
                    rows={2}
                    placeholder='{"os":"linux","tool_versions":{"node":"20"}}'
                    className="mt-0.5 w-full resize-y rounded-sm border border-edge bg-base px-1.5 py-1 font-mono text-2xs text-ink outline-none placeholder:text-faint focus:border-accent"
                  />
                </label>
              </div>
            )}
            <p className="text-2xs leading-relaxed text-faint">
              默认只读取仓库里最近一次验证的事实；失败、跳过与不支持都会留在「未证实」里。
              自定义工件必须位于仓库内，路径越界会被拒绝。
            </p>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            <p className="px-1 pb-1 text-2xs text-faint">已保存的证据包</p>
            {packs.length === 0 ? (
              <p className="px-1 py-2 text-2xs leading-relaxed text-faint">
                还没有证据包。先运行一次验证，再从上面的仓库生成。
              </p>
            ) : (
              <ul className="space-y-0.5">
                {packs.map((item) => (
                  <li key={item.pack_id}>
                    <button
                      onClick={() => setActiveId(item.pack_id)}
                      className={clsx(
                        'w-full rounded-sm px-1.5 py-1 text-left text-xs transition-colors',
                        item.pack_id === activeId
                          ? 'bg-accentSoft/40 text-ink'
                          : 'text-dim hover:bg-raised hover:text-ink',
                      )}
                    >
                      <span className="block truncate font-mono text-2xs">{item.pack_id}</span>
                      <span className="block truncate text-2xs text-faint">
                        {new Date(item.created_at).toLocaleString()} · {item.claims} 条主张
                        {item.unproven > 0 ? ` · ${item.unproven} 未证实` : ''}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="border-t border-edge p-2">
            <Button size="sm" className="w-full" onClick={() => setCompareOpen(true)}>
              <GitCompare size={12} /> 环境对比
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

          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {loading && !pack ? (
              <p className="flex items-center gap-2 text-xs text-faint"><Spinner /> 加载中…</p>
            ) : !pack ? (
              <div className="rounded-md border border-edge bg-panel/40 p-4">
                <p className="flex items-center gap-1.5 text-sm text-ink"><FileCheck2 size={14} /> 还没有选中证据包</p>
                <p className="mt-1.5 max-w-xl text-xs leading-relaxed text-dim">
                  证据包把一次验证拆成可以逐条核对的主张：哪些通过、哪些失败、哪些没运行、
                  哪些工具不支持。工件用 SHA-256 记录，之后可以重新核对是否被修改。
                </p>
              </div>
            ) : (
              <div className="space-y-4">
                <section className="rounded-md border border-edge bg-panel/40 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs text-ink">{pack.pack_id}</span>
                    <Badge tone="dim">{pack.claims.length} 条主张</Badge>
                    <Badge tone={pack.unproven.length > 0 ? 'warn' : 'ok'}>
                      {pack.unproven.length} 条未证实
                    </Badge>
                    <Button size="sm" onClick={() => void verifyPack()} disabled={busy}>
                      {busy ? <Spinner /> : <ShieldCheck size={12} />} 重新核对
                    </Button>
                  </div>
                  <div className="mt-2 grid gap-1 font-mono text-2xs text-faint sm:grid-cols-2">
                    <span>仓库：{pack.repo_id || '未记录'}</span>
                    <span>提交：{pack.commit || '未记录'}</span>
                    <span>创建：{new Date(pack.created_at).toLocaleString()}</span>
                    <span className="truncate" title={pack.manifest_sha256}>
                      清单：{pack.manifest_sha256 || '缺失'}
                    </span>
                  </div>
                  {verification && (
                    <div
                      className={clsx(
                        'mt-2 rounded-sm border px-2 py-1.5 text-xs',
                        verification.ok
                          ? 'border-ok/40 bg-ok/10 text-ok'
                          : 'border-warn/40 bg-warn/10 text-warn',
                      )}
                    >
                      <p className="flex items-center gap-1.5">
                        {verification.ok ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                        {verification.ok ? '清单与工件哈希都能对上' : '核对发现问题'}
                      </p>
                      {verification.problems.map((item) => (
                        <p key={item} className="mt-1 text-2xs leading-relaxed">{item}</p>
                      ))}
                    </div>
                  )}
                </section>

                <section>
                  <p className="text-xs font-medium text-ink">主张</p>
                  {pack.claims.length === 0 ? (
                    <p className="mt-1 text-2xs text-faint">这次验证没有产生可记录的主张。</p>
                  ) : (
                    <ul className="mt-1.5 space-y-1">
                      {pack.claims.map((claim) => {
                        const status = claimStatus(claim.status)
                        return (
                          <li key={claim.claim_id} className="rounded-sm border border-edge bg-panel/40 px-2 py-1.5">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <Badge tone={status.tone}>{status.label}</Badge>
                              <span className="text-2xs text-faint">{CLAIM_KIND[claim.kind] ?? claim.kind}</span>
                              {claimLine(claim) && (
                                <span className="font-mono text-2xs text-faint">{claimLine(claim)}</span>
                              )}
                            </div>
                            <p className="mt-1 text-xs leading-relaxed text-ink">{claim.statement}</p>
                            {claim.notes.map((item) => (
                              <p key={item} className="mt-0.5 text-2xs leading-relaxed text-dim">{item}</p>
                            ))}
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </section>

                {pack.unproven.length > 0 && (
                  <section>
                    <p className="text-xs font-medium text-warn">未证实</p>
                    <ul className="mt-1.5 space-y-0.5">
                      {pack.unproven.map((item) => (
                        <li key={item} className="flex items-start gap-1.5 text-2xs leading-relaxed text-dim">
                          <AlertTriangle size={11} className="mt-0.5 shrink-0 text-warn" />
                          <span className="min-w-0 flex-1">{item}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <section>
                  <p className="text-xs font-medium text-ink">工件</p>
                  {pack.artifacts.length === 0 ? (
                    <p className="mt-1 text-2xs text-faint">这个证据包没有绑定文件工件。</p>
                  ) : (
                    <ul className="mt-1.5 space-y-1">
                      {pack.artifacts.map((artifact) => (
                        <li key={artifact.artifact_id} className="rounded-sm border border-edge bg-panel/40 px-2 py-1.5">
                          <p className="truncate font-mono text-2xs text-ink">{artifact.name}</p>
                          <p className="truncate font-mono text-2xs text-faint" title={artifact.sha256}>
                            {artifact.sha256} · {artifact.size} 字节
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section>
                  <p className="text-xs font-medium text-ink">环境</p>
                  <div className="mt-1.5 grid gap-1 text-2xs text-dim sm:grid-cols-2">
                    <span>运行位置：{showValue(pack.environment.mode)}</span>
                    <span>系统：{showValue(pack.environment.os)} / {showValue(pack.environment.arch)}</span>
                    <span>隔离：{showValue(pack.environment.isolation)}</span>
                    <span>网络：{showValue(pack.environment.network)}</span>
                    <span>镜像：{showValue(pack.environment.image_digest)}</span>
                    <span>工作目录：{showValue(pack.environment.working_dir)}</span>
                  </div>
                  {Object.keys(pack.environment.tool_versions).length > 0 && (
                    <p className="mt-1 font-mono text-2xs text-faint">
                      工具：{Object.entries(pack.environment.tool_versions).map(([key, value]) => `${key} ${value}`).join('、')}
                    </p>
                  )}
                  {pack.environment.notes.map((item) => (
                    <p key={item} className="mt-1 text-2xs leading-relaxed text-faint">{item}</p>
                  ))}
                </section>
              </div>
            )}
          </div>
        </main>
      </div>

      <Modal open={compareOpen} onClose={() => setCompareOpen(false)} title="环境对比" width="max-w-2xl">
        <div className="space-y-3">
          <p className="text-xs leading-relaxed text-dim">
            分别填写本地与容器的环境描述（JSON）。只比较两边都记录了的维度；缺记录显示为「无法确认」，不会当作一致。
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block text-2xs text-dim">
              本地
              <textarea
                value={localJson}
                onChange={(event) => setLocalJson(event.target.value)}
                spellCheck={false}
                className="mt-0.5 h-28 w-full resize-none rounded-sm border border-edge bg-base px-2 py-1.5 font-mono text-2xs text-ink outline-none focus:border-accent"
              />
            </label>
            <label className="block text-2xs text-dim">
              容器
              <textarea
                value={containerJson}
                onChange={(event) => setContainerJson(event.target.value)}
                spellCheck={false}
                className="mt-0.5 h-28 w-full resize-none rounded-sm border border-edge bg-base px-2 py-1.5 font-mono text-2xs text-ink outline-none focus:border-accent"
              />
            </label>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="primary" onClick={() => void compare()} disabled={busy}>
              {busy ? <Spinner /> : <GitCompare size={12} />} 对比
            </Button>
            <Button size="sm" onClick={() => setCompareOpen(false)}>关闭</Button>
          </div>
          {comparison && (
            <div className="space-y-2">
              <p className="text-xs leading-relaxed text-dim">{comparison.note}</p>
              <ul className="space-y-1">
                {comparison.rows.map((row) => (
                  <li key={row.dimension} className="rounded-sm border border-edge bg-panel/40 px-2 py-1.5">
                    <div className="flex items-center gap-1.5">
                      <Badge tone={COMPARE_TONE[row.result] ?? 'warn'}>
                        {COMPARE_LABEL[row.result] ?? row.result}
                      </Badge>
                      <span className="text-xs text-ink">
                        {DIMENSION_LABEL[row.dimension] ?? row.dimension}
                      </span>
                    </div>
                    <p className="mt-0.5 font-mono text-2xs text-faint">
                      本地 {showValue(row.local)} · 容器 {showValue(row.container)}
                    </p>
                    <p className="text-2xs leading-relaxed text-dim">{row.note}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
