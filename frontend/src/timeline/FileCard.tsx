import clsx from 'clsx'
import { ChevronDown, ChevronRight, ExternalLink, FileCode2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { highlightCode, languageFromPath } from '../lib/highlight'
import type { StreamToolCard } from '../lib/types'
import {
  TOOL_CARD_CLASS, argString, diffEstimate, filePreview, formatBytes, toolFilePath, toolLabel,
} from './cards'

/** 文件卡：read_file / write_files / edit_file / read_uploaded_file。 */
export function FileCard({
  card,
  onOpenFile,
}: {
  card: StreamToolCard
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const path = toolFilePath(card) ?? toolLabel(card.call.name)
  const files = card.call.args?.files
  const fileList = Array.isArray(files)
    ? files.filter((item): item is string => typeof item === 'string')
    : files && typeof files === 'object'
      ? Object.keys(files)
      : []
  const preview = filePreview(card)
  const estimate = diffEstimate(card)
  const openable = argString(card, 'path') ?? fileList[0] ?? null
  const highlighted = useMemo(
    () => (preview ? highlightCode(preview.text, languageFromPath(openable ?? path)) : null),
    [preview, openable, path],
  )

  return (
    <div className={TOOL_CARD_CLASS}>
      <div className="flex h-8 items-center">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`${open ? '收起' : '展开'}文件 ${path}`}
          className="flex h-8 min-w-0 flex-1 items-center gap-2 pl-2.5 pr-1 text-left"
        >
          {open
            ? <ChevronDown size={12} className="shrink-0 text-faint" />
            : <ChevronRight size={12} className="shrink-0 text-faint" />}
          <FileCode2 size={12} className="shrink-0 text-faint" />
          <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink" title={path}>{path}</span>
          {fileList.length > 1 && (
            <span className="shrink-0 font-mono text-2xs text-faint">{fileList.length} 个文件</span>
          )}
          {preview && (
            <span className="hidden shrink-0 font-mono text-2xs text-faint sm:inline">
              {preview.lines} 行 · {formatBytes(preview.bytes)}
            </span>
          )}
          {estimate && (
            <span className="shrink-0 font-mono text-2xs">
              <span className="text-ok">+{estimate.add}</span>
              <span className="ml-1 text-err">-{estimate.del}</span>
            </span>
          )}
          {card.result && (
            <span className={clsx('shrink-0 font-mono text-2xs', card.result.ok ? 'text-ok' : 'text-err')}>
              {card.result.ms}ms
            </span>
          )}
        </button>
        {onOpenFile && openable && (
          <button
            type="button"
            onClick={() => onOpenFile(openable)}
            className="mr-1 flex h-6 shrink-0 items-center gap-1 rounded-sm px-1.5 font-mono text-2xs text-faint transition-colors duration-150 hover:text-ink"
            title={`在抽屉打开 ${openable}`}
            aria-label={`在抽屉打开 ${openable}`}
          >
            <ExternalLink size={11} />
            <span className="hidden sm:inline">在抽屉打开</span>
          </button>
        )}
      </div>

      {open && (
        <div className="border-t border-edge/60 px-2.5 py-2">
          {card.result && !card.result.ok && card.result.preview && (
            <p className="mb-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-err">
              {card.result.preview}
            </p>
          )}
          {preview ? (
            <>
              {highlighted ? (
                <pre className="max-h-80 overflow-auto rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed">
                  <code className="hljs bg-transparent p-0" dangerouslySetInnerHTML={{ __html: highlighted }} />
                </pre>
              ) : (
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                  {preview.text}
                </pre>
              )}
              <p className="mt-1.5 font-mono text-2xs text-faint">预览 {preview.lines} 行 · {formatBytes(preview.bytes)}</p>
            </>
          ) : (
            card.result?.preview && !card.result.ok ? null : (
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                {card.result?.preview || '没有可预览的内容。'}
              </pre>
            )
          )}
        </div>
      )}
    </div>
  )
}
