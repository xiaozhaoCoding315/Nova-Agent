import clsx from 'clsx'
import { Wrench } from 'lucide-react'
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
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accentSoft/50 px-4 py-2.5 text-[14px]">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-full">
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
    <div className="max-w-full">
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
  )
}