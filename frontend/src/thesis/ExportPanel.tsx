import { Download, FileDown, Package } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { ThesisExportReadiness } from '../lib/types'
import { useThesis } from '../stores/thesis'

const DOCUMENT_PACKAGE_ITEMS = [
  '修复版 DOCX',
  '论文体检报告 DOCX + HTML',
  '引用核验清单 CSV',
  'AI 使用声明 DOCX',
  '提交说明',
  '修改记录 JSON',
]

const STAGE_PACKAGE_ITEMS = [
  '阶段稿 Markdown（始终包含）',
  '阶段稿 DOCX（转换工具可用时）',
  'AI 使用声明 DOCX',
  '阶段确认记录与提交说明',
]

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function ExportPanel() {
  const { current, document, fixes, disclosures, busy, exportReport, exportPackage } = useThesis()
  const [readiness, setReadiness] = useState<ThesisExportReadiness | null>(null)
  const [exporting, setExporting] = useState('')
  const [error, setError] = useState('')
  const applied = fixes.filter((fix) => !fix.undone_at).length
  const stageAvailable = readiness?.manuscript_available ?? false
  const documentReady = document?.status === 'parsed'
  const disabled = (!documentReady && !stageAvailable) || busy

  useEffect(() => {
    if (!current) {
      setReadiness(null)
      return
    }
    let cancelled = false
    api.thesis.exportReadiness(current.id)
      .then((data) => {
        if (!cancelled) setReadiness(data)
      })
      .catch(() => {
        if (!cancelled) setReadiness(null)
      })
    return () => {
      cancelled = true
    }
  }, [current])

  const exportManuscript = async (format: 'md' | 'docx' | 'pdf') => {
    if (!current) return
    setExporting(format)
    setError('')
    try {
      let acknowledge = false
      if (readiness && !readiness.ready) {
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
      await api.thesis.exportManuscript(current.id, format, acknowledge)
    } catch (err) {
      setError(messageOf(err, '导出阶段稿失败'))
    } finally {
      setExporting('')
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-ink">导出</h2>
        <span className="text-2xs text-faint">
          {applied} 项修复 · {disclosures.length} 条 AI 使用记录
        </span>
      </div>

      {error && (
        <p className="rounded-md border border-err/30 bg-err/10 px-3 py-2 text-xs leading-relaxed text-err">
          {error}
        </p>
      )}

      {!document && (
        <p className="rounded-md border border-warn/30 bg-warn/10 px-3 py-2 text-xs leading-relaxed text-warn">
          还没有导入可解析的 DOCX。阶段稿可以单独导出 MD / DOCX / PDF；
          {stageAvailable
            ? '定稿包也会改用阶段稿，并附上 AI 使用声明与阶段确认记录。'
            : '先在「阶段」页填写内容，或导入已有论文。'}
        </p>
      )}

      <div className="rounded-md border border-edge bg-panel/40 p-3">
        <p className="text-sm font-medium text-ink">阶段稿</p>
        <p className="mt-1 text-xs leading-relaxed text-dim">
          按七个阶段的顺序整理你已填写的内容，不生成未写过的段落。
          未确认或已失效的内容会先提示，导出后仍以「未确认草稿」标记。
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(['md', 'docx', 'pdf'] as const).map((format) => (
            <Button
              key={format}
              size="sm"
              onClick={() => void exportManuscript(format)}
              disabled={!stageAvailable || busy || !!exporting}
            >
              {exporting === format ? <Spinner /> : <FileDown size={13} />}
              {format.toUpperCase()}
            </Button>
          ))}
        </div>
        {!stageAvailable && (
          <p className="mt-2 text-2xs text-faint">阶段页还没有已填写的内容。</p>
        )}
      </div>

      <div className="rounded-md border border-edge bg-panel/40 p-3">
        <p className="text-sm font-medium text-ink">定稿包</p>
        <p className="mt-1 text-xs leading-relaxed text-dim">
          {documentReady
            ? '一次打包修复后的文档、体检报告、引用清单、AI 使用声明和修改记录。原文件始终保留，不会被覆盖。'
            : '没有可用的导入文档，定稿包会改用你在「阶段」页写的内容；体检报告、引用清单和修改记录只在导入并解析 DOCX 后生成。'}
          导出前会检查所有已填写阶段的作者确认，未确认或已失效的内容会先列出来。
        </p>
        <ul className="mt-2 space-y-1 text-2xs leading-relaxed text-faint">
          {(documentReady ? DOCUMENT_PACKAGE_ITEMS : STAGE_PACKAGE_ITEMS).map((item) => (
            <li key={item}>· {item}</li>
          ))}
        </ul>
        <Button
          variant="primary"
          size="sm"
          className="mt-3"
          onClick={() => void exportPackage()}
          disabled={disabled}
        >
          {busy ? <Spinner /> : <Package size={13} />} 导出定稿包 ZIP
        </Button>
      </div>

      <div className="rounded-md border border-edge bg-panel/40 p-3">
        <p className="text-sm font-medium text-ink">单独导出报告</p>
        <p className="mt-1 text-xs leading-relaxed text-dim">
          报告包含模板版本、扫描时间、问题清单、证据、修复状态和局限说明。
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void exportReport('docx')} disabled={!documentReady || busy}>
            {busy ? <Spinner /> : <FileDown size={13} />} 报告 DOCX
          </Button>
          <Button size="sm" onClick={() => void exportReport('html')} disabled={!documentReady || busy}>
            {busy ? <Spinner /> : <Download size={13} />} 报告 HTML
          </Button>
        </div>
      </div>

      <div className="rounded-md border border-accent/20 bg-accentSoft/20 px-3 py-2 text-xs leading-relaxed text-dim">
        导出不包含任何未授权文件；报告只记录本地检查结果，不是学校出具的合规证明。
        目录、交叉引用等 Word 域请在 Word 中按 F9 更新。
      </div>
    </div>
  )
}
