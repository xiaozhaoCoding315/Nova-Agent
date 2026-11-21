import clsx from 'clsx'
import { AlertTriangle, FileText, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { HeroComposer } from '../components/HeroComposer'

type Mode = 'dev' | 'thesis'

const THESIS_ISSUES = [
  {
    level: '高',
    kind: '引用',
    text: '[7] 在参考文献中缺少对应条目',
    meta: '第 4 章 · 12 处引用',
  },
  {
    level: '中',
    kind: '结构',
    text: '2.1 后直接出现 2.1.1，标题层级跳级',
    meta: '第 2 章',
  },
  {
    level: '低',
    kind: '格式',
    text: '左边距 3.0cm，模板要求 3.5cm',
    meta: '全文',
  },
]

function ThesisPreview() {
  return (
    <div className="overflow-hidden rounded-lg border border-edge bg-panel shadow-pop">
      <div className="flex items-center justify-between gap-3 border-b border-edge/80 px-3.5 py-3">
        <span className="flex min-w-0 items-center gap-2 font-mono text-2xs text-dim">
          <FileText size={13} className="shrink-0 text-warn" />
          <span className="truncate">thesis.docx · 本科毕业论文模板</span>
        </span>
        <span className="shrink-0 rounded-sm border border-warn/30 bg-warn/10 px-1.5 py-0.5 font-mono text-2xs text-warn">
          3 个问题
        </span>
      </div>

      <div className="divide-y divide-edge/60">
        {THESIS_ISSUES.map((issue) => (
          <div key={issue.text} className="flex items-start gap-3 px-3.5 py-2.5">
            <span
              className={clsx(
                'mt-0.5 shrink-0 rounded-sm border px-1 py-0.5 font-mono text-2xs',
                issue.level === '高'
                  ? 'border-err/40 bg-err/10 text-err'
                  : issue.level === '中'
                    ? 'border-warn/40 bg-warn/10 text-warn'
                    : 'border-edge bg-raised text-dim',
              )}
            >
              {issue.level}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs leading-5 text-ink/90">{issue.text}</span>
              <span className="mt-0.5 block font-mono text-2xs text-faint">
                {issue.kind} · {issue.meta}
              </span>
            </span>
            <AlertTriangle size={12} className="mt-1 shrink-0 text-faint" aria-hidden="true" />
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-edge/80 bg-base/50 px-3.5 py-2.5 font-mono text-2xs text-faint">
        <span className="flex items-center gap-1.5">
          <ShieldCheck size={11} className="text-warn" />
          原文件只读
        </span>
        <span>修复写入 working.docx</span>
        <span>可撤销</span>
      </div>
    </div>
  )
}

/**
 * 首屏右侧的产物预览：开发模式展示真实输入框的排版，论文模式展示体检卡片。
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
            className={clsx(
              'rounded-sm px-2.5 py-1 text-2xs transition-colors duration-150',
              mode === 'dev' ? 'bg-accentSoft text-accent' : 'text-dim hover:text-ink',
            )}
          >
            开发模式
          </button>
          <button
            role="tab"
            aria-selected={mode === 'thesis'}
            onClick={() => setMode('thesis')}
            className={clsx(
              'rounded-sm px-2.5 py-1 text-2xs transition-colors duration-150',
              mode === 'thesis' ? 'bg-warn/10 text-warn' : 'text-dim hover:text-ink',
            )}
          >
            论文模式
          </button>
        </div>
        <span className="font-mono text-2xs tracking-[0.08em] text-faint">
          {mode === 'dev' ? '工具账本' : '文档体检'}
        </span>
      </div>

      <div role="tabpanel" aria-label={mode === 'dev' ? '开发模式预览' : '论文模式预览'}>
        {mode === 'dev' ? <HeroComposer onStart={onStart} /> : <ThesisPreview />}
      </div>
    </div>
  )
}
