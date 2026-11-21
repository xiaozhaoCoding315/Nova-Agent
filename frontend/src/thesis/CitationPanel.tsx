import { FileText, MapPin, RefreshCw, Trash2, Upload } from 'lucide-react'
import { useRef, type ChangeEvent } from 'react'
import { Badge, Button, Spinner } from '../components/common'
import { useThesis } from '../stores/thesis'

const STATUS_LABEL: Record<string, string> = {
  matched: '已对应',
  missing_reference: '缺少文献条目',
  unverified: '需人工确认',
  cited: '正文已引用',
  uncited: '未在正文引用',
}

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'dim' | 'err'> = {
  matched: 'ok',
  missing_reference: 'err',
  unverified: 'warn',
  cited: 'ok',
  uncited: 'dim',
}

const METADATA_LABEL: Record<string, string> = {
  verified: '已核实',
  partial: '部分匹配',
  mismatch: '信息不符',
  not_found: '未找到',
  needs_review: '需人工确认',
  no_doi: '无 DOI',
}

const METADATA_TONE: Record<string, 'ok' | 'warn' | 'dim' | 'err'> = {
  verified: 'ok',
  partial: 'warn',
  mismatch: 'err',
  not_found: 'warn',
  needs_review: 'dim',
  no_doi: 'dim',
}

const SUPPORT_LABEL: Record<string, string> = {
  needs_review: '待确认',
  supported: '支持',
  partial: '部分支持',
  unsupported: '不支持',
}

const SUPPORT_TONE: Record<string, 'ok' | 'warn' | 'dim' | 'err'> = {
  needs_review: 'dim',
  supported: 'ok',
  partial: 'warn',
  unsupported: 'err',
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : value == null ? '' : String(value)
}

function num(value: unknown): string {
  return typeof value === 'number' ? String(value) : str(value)
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

export function CitationPanel() {
  const {
    citations,
    referencePdfs,
    evidence,
    busy,
    auditCitations,
    verifyMetadata,
    uploadReferencePdf,
    deleteReferencePdf,
    locateEvidence,
    updateEvidence,
  } = useThesis()
  const fileInput = useRef<HTMLInputElement>(null)
  const references = (citations?.references ?? []) as Record<string, unknown>[]
  const inText = (citations?.in_text ?? []) as Record<string, unknown>[]
  const missing = inText.filter((item) => item.status === 'missing_reference').length
  const verified = references.filter(
    (item) => item.metadata_status === 'verified',
  ).length

  const handlePdf = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      await uploadReferencePdf(file)
    } catch {
      /* store.error 已展示 */
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-ink">引用核对</h2>
        <Badge tone={missing > 0 ? 'err' : 'dim'}>{references.length} 条文献</Badge>
        <Badge tone={missing > 0 ? 'err' : 'dim'}>{inText.length} 处文内引用</Badge>
        {missing > 0 && <Badge tone="err">{missing} 处缺条目</Badge>}
        {verified > 0 && <Badge tone="ok">{verified} 条元数据已核实</Badge>}
        <Button size="sm" onClick={() => void auditCitations()} disabled={busy}>
          {busy ? <Spinner /> : <RefreshCw size={13} />} 重新核对 L1
        </Button>
        <Button size="sm" onClick={() => void verifyMetadata()} disabled={busy}>
          {busy ? <Spinner /> : <RefreshCw size={13} />} 联网核验 DOI
        </Button>
      </div>

      <div className="rounded-md border border-accent/20 bg-accentSoft/20 px-3 py-2 text-xs leading-relaxed text-dim">
        <p>
          L1 只做文内标注与文末列表的文本对照：缺条目、重复、编号不连续和顺序问题。
          它不判断文献是否真实存在，也不判断引用是否恰当。
        </p>
        <p className="mt-1">
          L2 只把 DOI 发送到 Crossref，不发送论文正文；结果缓存 30 天。
          「未找到」只表示 Crossref 查不到该 DOI，不等于文献是伪造的。
        </p>
      </div>

      {references.length === 0 && inText.length === 0 ? (
        <div className="rounded-md border border-edge bg-panel/40 px-3 py-4 text-xs leading-relaxed text-dim">
          还没有引用核对结果。导入 DOCX 并运行检查后，这里会显示参考文献与文内标注的对应关系。
        </div>
      ) : (
        <>
          <section className="overflow-hidden rounded-md border border-edge bg-panel/40">
            <div className="flex items-center justify-between border-b border-edge px-3 py-2">
              <h3 className="text-sm font-medium text-ink">参考文献</h3>
              <span className="font-mono text-2xs text-faint">{references.length}</span>
            </div>
            <div className="max-h-[420px] overflow-y-auto">
              {references.length === 0 ? (
                <p className="px-3 py-3 text-xs text-faint">未解析到参考文献列表</p>
              ) : (
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-panel/95 text-2xs text-faint">
                    <tr>
                      <th className="w-12 px-3 py-1.5 font-normal">编号</th>
                      <th className="px-3 py-1.5 font-normal">条目</th>
                      <th className="w-20 px-3 py-1.5 font-normal">正文引用</th>
                      <th className="w-36 px-3 py-1.5 font-normal">DOI / 元数据</th>
                    </tr>
                  </thead>
                  <tbody>
                    {references.map((item, index) => {
                      const metadata = record(item.metadata)
                      const status = str(item.metadata_status)
                      return (
                        <tr key={index} className="border-t border-edge/60 align-top">
                          <td className="px-3 py-1.5 font-mono text-faint">{num(item.index)}</td>
                          <td className="px-3 py-1.5 leading-relaxed text-dim">
                            <p>{str(item.raw)}</p>
                            {str(metadata.title) && (
                              <p className="mt-1 text-2xs text-faint">
                                Crossref：{str(metadata.title)}
                                {str(metadata.container) && ` · ${str(metadata.container)}`}
                                {str(metadata.year) && ` · ${str(metadata.year)}`}
                              </p>
                            )}
                            {str(metadata.detail) && (
                              <p className="mt-0.5 text-2xs text-faint">{str(metadata.detail)}</p>
                            )}
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge tone={item.cited ? 'ok' : 'dim'}>
                              {item.cited ? '是' : '否'}
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5">
                            {str(item.doi) ? (
                              <p className="break-all font-mono text-2xs text-faint">
                                {str(item.doi)}
                              </p>
                            ) : (
                              <p className="text-2xs text-faint">未识别到 DOI</p>
                            )}
                            {status ? (
                              <Badge tone={METADATA_TONE[status] ?? 'dim'}>
                                {METADATA_LABEL[status] ?? status}
                              </Badge>
                            ) : (
                              <span className="text-2xs text-faint">未联网核验</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="overflow-hidden rounded-md border border-edge bg-panel/40">
            <div className="flex items-center justify-between border-b border-edge px-3 py-2">
              <h3 className="text-sm font-medium text-ink">文内引用</h3>
              <span className="font-mono text-2xs text-faint">{inText.length}</span>
            </div>
            <div className="max-h-[360px] overflow-y-auto">
              {inText.length === 0 ? (
                <p className="px-3 py-3 text-xs text-faint">未识别到文内引用标注</p>
              ) : (
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-panel/95 text-2xs text-faint">
                    <tr>
                      <th className="w-24 px-3 py-1.5 font-normal">标注</th>
                      <th className="w-24 px-3 py-1.5 font-normal">类型</th>
                      <th className="w-28 px-3 py-1.5 font-normal">状态</th>
                      <th className="px-3 py-1.5 font-normal">上下文</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inText.map((item, index) => {
                      const status = str(item.status)
                      return (
                        <tr key={index} className="border-t border-edge/60 align-top">
                          <td className="px-3 py-1.5 font-mono text-ink">{str(item.raw)}</td>
                          <td className="px-3 py-1.5 text-faint">
                            {item.kind === 'numeric' ? '数字编号' : '作者-年份'}
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge tone={STATUS_TONE[status] ?? 'dim'}>
                              {STATUS_LABEL[status] ?? status}
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5 text-dim">{str(item.context)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </section>
        </>
      )}

      <section className="rounded-md border border-edge bg-panel/40">
        <div className="flex flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
          <h3 className="text-sm font-medium text-ink">全文证据（L3 · 实验）</h3>
          <Badge tone="dim">{referencePdfs.length} 个 PDF</Badge>
          <Badge tone="dim">{evidence.length} 条候选</Badge>
          <Button size="sm" onClick={() => fileInput.current?.click()} disabled={busy}>
            {busy ? <Spinner /> : <Upload size={13} />} 附加参考文献 PDF
          </Button>
          <Button
            size="sm"
            onClick={() => void locateEvidence()}
            disabled={busy || referencePdfs.length === 0}
          >
            {busy ? <Spinner /> : <MapPin size={13} />} 定位候选页码
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={(event) => void handlePdf(event)}
          />
        </div>

        <div className="space-y-2 px-3 py-2 text-xs leading-relaxed text-dim">
          <p>
            附加你手头有授权的参考文献 PDF，Nova 会在本机提取文字层并定位候选页码与原文。
            不做联网检索，也不判断引用是否恰当；扫描版 PDF 无法提取文字。
          </p>
          {referencePdfs.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {referencePdfs.map((pdf) => (
                <span
                  key={pdf.id}
                  className="inline-flex items-center gap-1.5 rounded-sm border border-edge bg-base/50 px-2 py-1 text-2xs text-dim"
                >
                  <FileText size={12} />
                  {pdf.filename}
                  <span className="text-faint">{pdf.page_count} 页</span>
                  <button
                    onClick={() => void deleteReferencePdf(pdf.id)}
                    className="text-faint transition-colors duration-150 hover:text-err"
                    title="删除这个 PDF 及其证据"
                    aria-label="删除这个 PDF"
                  >
                    <Trash2 size={12} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {evidence.length === 0 ? (
          <p className="border-t border-edge/60 px-3 py-3 text-xs text-faint">
            还没有全文证据。附加 PDF 后点「定位候选页码」；结果只是候选，支持度需要你确认。
          </p>
        ) : (
          <div className="max-h-[420px] overflow-y-auto border-t border-edge/60">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-panel/95 text-2xs text-faint">
                <tr>
                  <th className="w-14 px-3 py-1.5 font-normal">编号</th>
                  <th className="px-3 py-1.5 font-normal">候选原文</th>
                  <th className="w-24 px-3 py-1.5 font-normal">位置</th>
                  <th className="w-32 px-3 py-1.5 font-normal">支持度（人工）</th>
                </tr>
              </thead>
              <tbody>
                {evidence.map((item) => (
                  <tr key={item.id} className="border-t border-edge/60 align-top">
                    <td className="px-3 py-1.5 font-mono text-faint">
                      {item.reference_index == null ? '—' : item.reference_index}
                    </td>
                    <td className="px-3 py-1.5">
                      <p className="max-h-24 overflow-y-auto whitespace-pre-wrap leading-relaxed text-dim">
                        {item.quote || '未提取到候选原文'}
                      </p>
                      <p className="mt-1 truncate text-2xs text-faint" title={item.reference_raw}>
                        {item.reference_raw}
                      </p>
                    </td>
                    <td className="px-3 py-1.5 text-2xs text-faint">
                      <p>{item.pdf_filename}</p>
                      <p>第 {item.page ?? '—'} 页 · 匹配 {Math.round((item.score || 0) * 100)}%</p>
                    </td>
                    <td className="px-3 py-1.5">
                      <Badge tone={SUPPORT_TONE[item.support] ?? 'dim'}>
                        {SUPPORT_LABEL[item.support] ?? item.support}
                      </Badge>
                      <select
                        value={item.support}
                        onChange={(event) =>
                          void updateEvidence(item.id, event.target.value)
                        }
                        className="mt-1 w-full rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-ink outline-none focus:border-accent"
                        aria-label="设置证据支持度"
                      >
                        <option value="needs_review">待确认</option>
                        <option value="supported">支持</option>
                        <option value="partial">部分支持</option>
                        <option value="unsupported">不支持</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
