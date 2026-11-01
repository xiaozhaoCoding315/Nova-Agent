import { Check, CheckCircle2, ChevronDown, ChevronRight, Copy, ExternalLink, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '../components/common'
import type { StreamToolCard } from '../lib/types'
import {
  TOOL_CARD_CLASS, argString, toolCardKind, toolCommand, toolFilePath, toolLabel,
} from './cards'
import { FileCard } from './FileCard'
import { SearchCard } from './SearchCard'
import { ToolTerminal } from './ToolTerminal'
import { WebSearchCard } from './WebSearchCard'

/** 通用折叠卡：未归类的工具，保持旧 ToolCard 的信息密度。 */
export function GenericToolCard({
  card,
  onCancel,
  onOpenFile,
}: {
  card: StreamToolCard
  onCancel?: () => void
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const { call, result } = card
  const command = toolCommand(card)
  const path = toolFilePath(card) ?? argString(card, 'path')
  const running = !result

  const copy = (text: string) => {
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={TOOL_CARD_CLASS}>
      <div className="flex h-8 items-center">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`${open ? '收起' : '展开'}工具 ${toolLabel(call.name)}`}
          className="flex h-8 min-w-0 flex-1 items-center gap-2 pl-2.5 pr-1 text-left"
        >
          {open
            ? <ChevronDown size={12} className="shrink-0 text-faint" />
            : <ChevronRight size={12} className="shrink-0 text-faint" />}
          <span className="shrink-0 text-sm text-ink">{toolLabel(call.name)}</span>
          <span className="min-w-0 flex-1 truncate font-mono text-2xs text-faint">{call.name}</span>
          {typeof call.round === 'number' && call.round > 0 && (
            <span className="hidden shrink-0 font-mono text-2xs text-faint sm:inline">第 {call.round} 轮</span>
          )}
          {running && <Spinner className="h-3 w-3 shrink-0" />}
          {result && (result.ok
            ? <CheckCircle2 size={12} className="shrink-0 text-ok" />
            : <XCircle size={12} className="shrink-0 text-err" />)}
          {result && <span className="shrink-0 font-mono text-2xs text-faint">{result.ms}ms</span>}
        </button>
        {running && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="shrink-0 rounded-sm border border-edge px-1.5 font-mono text-2xs text-faint transition-colors duration-150 hover:border-err/50 hover:text-err"
            title="取消这个工具"
          >
            取消
          </button>
        )}
        {command && (
          <button
            type="button"
            onClick={() => copy(command)}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-faint transition-colors duration-150 hover:text-ink"
            title="复制命令"
            aria-label="复制命令"
          >
            {copied ? <Check size={11} className="text-ok" /> : <Copy size={11} />}
          </button>
        )}
      </div>

      {open && (
        <div className="space-y-2 border-t border-edge/60 px-2.5 py-2">
          {command && (
            <pre className="max-h-24 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
              {command}
            </pre>
          )}
          {path && onOpenFile && (
            <button
              type="button"
              onClick={() => onOpenFile(path)}
              className="flex items-center gap-1 rounded-sm border border-edge px-2 py-0.5 font-mono text-2xs text-dim transition-colors duration-150 hover:border-faint hover:text-ink"
            >
              <ExternalLink size={11} /> 在抽屉打开 {path}
            </button>
          )}
          {call.args && Object.keys(call.args).length > 0 && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint">入参</p>
              <pre className="max-h-40 overflow-auto rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                {JSON.stringify(call.args, null, 2)}
              </pre>
            </div>
          )}
          {!result && card.output && (
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
              {card.output}
            </pre>
          )}
          {result && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint">
                结果{result.ok ? '' : '（失败）'}
              </p>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                {result.content_preview || result.preview || '没有输出。'}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** 按工具名分发到终端卡 / 文件卡 / 检索卡 / 通用卡。 */
export function ToolCardView({
  card,
  onCancel,
  onOpenFile,
}: {
  card: StreamToolCard
  onCancel?: () => void
  onOpenFile?: (path: string) => void
}) {
  switch (toolCardKind(card.call.name)) {
    case 'terminal':
      return <ToolTerminal card={card} onCancel={onCancel} />
    case 'file':
      return <FileCard card={card} onOpenFile={onOpenFile} />
    case 'search':
      return <SearchCard card={card} onOpenFile={onOpenFile} />
    case 'web':
      return <WebSearchCard card={card} />
    default:
      return <GenericToolCard card={card} onCancel={onCancel} onOpenFile={onOpenFile} />
  }
}
