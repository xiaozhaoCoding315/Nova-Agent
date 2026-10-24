import clsx from 'clsx'
import { FileText, Wrench } from 'lucide-react'
import type { EditRef, Message, StreamToolCard } from '../lib/types'
import { DeliveryReport } from './DeliveryReport'
import { EditCard } from './EditCard'
import { EvidenceBar } from './EvidenceBar'
import { Markdown } from './Markdown'
import { ToolCard } from './ToolCard'

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const tools = message.tool_json?.tools_used ?? []
  const evidence = message.tool_json?.evidence
  const edits = message.tool_json?.edits ?? []

  if (isUser) {
    const attachments = message.attachments ?? []
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-accentSoft/55 px-4 py-2.5">
          <p className="whitespace-pre-wrap text-[14px] leading-relaxed">{message.content}</p>
          {attachments.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {attachments.map((file) => (
                <a
                  key={file.id}
                  href={`/api/v1/files/${file.id}/download`}
                  className="flex max-w-[220px] items-center gap-1 rounded-lg border border-white/15 bg-black/15 px-2 py-1 text-[10.5px] text-ink/90 hover:bg-black/25"
                  title={`下载 ${file.filename}`}
                >
                  <FileText size={11} className="shrink-0" />
                  <span className="truncate">{file.filename}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-edge bg-raised text-[10.5px] font-semibold text-accent">
        N
      </div>
      <div className="min-w-0 flex-1">
        <Markdown content={message.content} />
        {edits.map((edit) => (
          <EditCard key={edit.id} edit={edit} />
        ))}
        {evidence && <EvidenceBar evidence={evidence} />}
        <DeliveryReport report={message.tool_json?.report} />
        {tools.length > 0 && (
          <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-dim">
            <Wrench size={11} />
            <span>调用了 {tools.join('、')}</span>
          </div>
        )}
      </div>
    </div>
  )
}

export function StreamingBubble({
  text,
  toolCards,
  editProposals,
}: {
  text: string
  toolCards: StreamToolCard[]
  editProposals: EditRef[]
}) {
  return (
    <div className="flex gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-edge bg-raised text-[10.5px] font-semibold text-accent">
        N
      </div>
      <div className="min-w-0 flex-1">
        {toolCards.map((card) => (
          <ToolCard key={card.call.id} card={card} />
        ))}
        {text ? (
          <Markdown content={text} />
        ) : (
          <p className="flex items-center gap-2 text-[13px] text-dim">
            <span className="inline-flex gap-1">
              <span className={clsx('h-1.5 w-1.5 animate-pulse rounded-full bg-accent')} />
              <span className={clsx('h-1.5 w-1.5 animate-pulse rounded-full bg-accent [animation-delay:150ms]')} />
              <span className={clsx('h-1.5 w-1.5 animate-pulse rounded-full bg-accent [animation-delay:300ms]')} />
            </span>
            思考中…
          </p>
        )}
        {editProposals.map((edit) => (
          <EditCard key={edit.id} edit={edit} />
        ))}
      </div>
    </div>
  )
}