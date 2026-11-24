import { FileText, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { HeroComposer } from '../components/HeroComposer'

type Mode = 'dev' | 'thesis'

const THESIS_STAGES = ['选题', '提纲', '章节', '修改']

function ThesisPreview() {
  return (
    <div className="overflow-hidden rounded-lg border border-edge bg-panel shadow-pop">
      <div className="flex items-center justify-between gap-3 border-b border-edge/80 px-3.5 py-3">
        <span className="flex min-w-0 items-center gap-2 font-mono text-2xs text-dim">
          <FileText size={13} className="shrink-0 text-warn" />
          <span className="truncate">论文工作台 · 第 3 章 方法</span>
        </span>
        <span className="shrink-0 rounded-sm border border-warn/30 bg-warn/10 px-1.5 py-0.5 font-mono text-2xs text-warn">
          AI 草稿
        </span>
      </div>

      <div className="px-3.5 py-3">
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-2xs text-faint">
          {THESIS_STAGES.map((stage, index) => (
            <span key={stage} className="flex items-center gap-1.5">
              {index > 0 && <span aria-hidden="true">→</span>}
              <span className={stage === '章节' ? 'text-warn' : ''}>{stage}</span>
            </span>
          ))}
        </div>

        <p className="mt-3 text-xs leading-6 text-ink/90">
          本节采用访谈与问卷结合的混合方法。先说明样本来源与编码流程，再交代分析步骤；
          具体数字与引用由你补充，AI 只整理结构与表述。
        </p>

        <div className="mt-3 flex flex-wrap gap-1.5">
          <span className="rounded-sm border border-edge bg-base/60 px-1.5 py-0.5 font-mono text-2xs text-dim">
            阶段稿待确认
          </span>
          <span className="rounded-sm border border-edge bg-base/60 px-1.5 py-0.5 font-mono text-2xs text-dim">
            可回退重写
          </span>
          <span className="rounded-sm border border-edge bg-base/60 px-1.5 py-0.5 font-mono text-2xs text-dim">
            引用只用已导入条目
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-edge/80 bg-base/50 px-3.5 py-2.5 font-mono text-2xs text-faint">
        <span className="flex items-center gap-1.5">
          <ShieldCheck size={11} className="text-warn" />
          AI 内容标注草稿
        </span>
        <span>导出 MD / DOCX / PDF</span>
        <span>可选导入 DOCX 体检</span>
      </div>
    </div>
  )
}

/**
 * 首屏右侧的产物预览：开发模式展示真实输入框的排版，论文模式展示阶段稿卡片。
 * 切换由用户触发，不做自动轮播；两个面板高度接近，避免布局跳动。
 */
export function ModePreview({ onStart }: { onStart: () => void }) {
  const [mode, setMode] = useState<Mode>('dev')

  return (
    <div className="min-w-0">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div
          role="tablist"
          aria-label="切换产品预览"
          className="inline-flex rounded-md border border-edge bg-panel/60 p-0.5"
        >
          <button
            role="tab"
            aria-selected={mode === 'dev'}
            onClick={() => setMode('dev')}
            className={`rounded-sm px-2.5 py-1 text-2xs transition-colors duration-150 ${
              mode === 'dev' ? 'bg-accentSoft text-accent' : 'text-dim hover:text-ink'
            }`}
          >
            开发模式
          </button>
          <button
            role="tab"
            aria-selected={mode === 'thesis'}
            onClick={() => setMode('thesis')}
            className={`rounded-sm px-2.5 py-1 text-2xs transition-colors duration-150 ${
              mode === 'thesis' ? 'bg-warn/10 text-warn' : 'text-dim hover:text-ink'
            }`}
          >
            论文模式
          </button>
        </div>
        <span className="font-mono text-2xs tracking-[0.08em] text-faint">
          {mode === 'dev' ? '工具账本' : '阶段稿'}
        </span>
      </div>

      <div role="tabpanel" aria-label={mode === 'dev' ? '开发模式预览' : '论文模式预览'}>
        {mode === 'dev' ? <HeroComposer onStart={onStart} /> : <ThesisPreview />}
      </div>
    </div>
  )
}
