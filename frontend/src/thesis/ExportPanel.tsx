import { Download, FileDown, Package } from 'lucide-react'
import { Button, Spinner } from '../components/common'
import { useThesis } from '../stores/thesis'

const PACKAGE_ITEMS = [
  '修复版 DOCX（未修复时复制原文件）',
  '论文体检报告 DOCX + HTML',
  '引用核验清单 CSV',
  'AI 使用声明 DOCX',
  '修改记录 JSON 与提交说明',
]

export function ExportPanel() {
  const { document, fixes, disclosures, busy, exportReport, exportPackage } = useThesis()
  const applied = fixes.filter((fix) => !fix.undone_at).length
  const disabled = !document || document.status !== 'parsed' || busy

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-ink">导出</h2>
        <span className="text-2xs text-faint">
          {applied} 项修复 · {disclosures.length} 条 AI 使用记录
        </span>
      </div>

      <div className="rounded-md border border-edge bg-panel/40 p-3">
        <p className="text-sm font-medium text-ink">定稿包</p>
        <p className="mt-1 text-xs leading-relaxed text-dim">
          一次打包修复后的文档、体检报告、引用清单、AI 使用声明和修改记录。
          原文件始终保留，不会被覆盖。导出前会检查七个阶段的作者确认，
          未确认或已失效的内容会先列出来。
        </p>
        <ul className="mt-2 space-y-1 text-2xs leading-relaxed text-faint">
          {PACKAGE_ITEMS.map((item) => (
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
          <Button size="sm" onClick={() => void exportReport('docx')} disabled={disabled}>
            {busy ? <Spinner /> : <FileDown size={13} />} 报告 DOCX
          </Button>
          <Button size="sm" onClick={() => void exportReport('html')} disabled={disabled}>
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
