import clsx from 'clsx'
import { Wrench } from 'lucide-react'
import type { Message, StreamToolCard } from '../lib/types'
import { Markdown } from './Markdown'
import { ToolCard } from './ToolCard'

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  const tools = message.tool_json?.tools_used ?? []

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
      {tools.length > 0 && (
        <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-dim">
          <Wrench size={11} />
          <span>调用了 {tools.join('、')}</span>
        </div>
      )}
    </div>
  )
}

export function StreamingBubble({ text, toolCards }: { text: string; toolCards: StreamToolCard[] }) {
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
    </div>
  )
}