import { useEffect, useMemo, useRef } from 'react'
import type { ReactNode } from 'react'
import type {
  EditRef, Message, PlanState, StreamToolCard, StreamUsage, ToolApproval,
} from '../lib/types'
import { TurnView, type TurnStream } from './TurnView'

type Turn = { index: number; user?: Message; assistant: Message[] }

/** 遇到 user 消息开新轮；其余 assistant 消息归入当前轮。 */
function buildTurns(messages: Message[]): Turn[] {
  const turns: Turn[] = []
  for (const message of messages) {
    if (message.role === 'user') {
      turns.push({ index: turns.length + 1, user: message, assistant: [] })
      continue
    }
    if (turns.length === 0) {
      turns.push({ index: 1, assistant: [message] })
      continue
    }
    turns[turns.length - 1].assistant.push(message)
  }
  return turns
}

export function ChatTimeline({
  messages,
  streaming,
  streamText,
  toolCards,
  streamEdits,
  plan,
  approvals,
  usage,
  onCancelTool,
  onResolveApproval,
  onOpenFile,
  emptyState,
}: {
  messages: Message[]
  streaming: boolean
  streamText: string
  toolCards: StreamToolCard[]
  streamEdits: EditRef[]
  plan: PlanState | null
  approvals: ToolApproval[]
  usage?: StreamUsage | null
  onCancelTool?: (toolCallId: string) => void
  onResolveApproval?: (toolCallId: string, approved: boolean) => void
  onOpenFile?: (path: string) => void
  /** 空会话时显示的操作区（示例问题、连接本机、/fix 入口）。 */
  emptyState?: ReactNode
}) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const turns = useMemo(() => buildTurns(messages), [messages])
  const stream: TurnStream | undefined = streaming
    ? {
        text: streamText,
        toolCards,
        editProposals: streamEdits,
        plan,
        approvals,
        usage,
      }
    : undefined

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    // 空状态高于视口时不能自动滚到底，否则欢迎语和第一张卡片会被顶出屏幕。
    if (turns.length === 0 && !streaming) {
      el.scrollTop = 0
      stickRef.current = true
      return
    }
    if (stickRef.current) el.scrollTop = el.scrollHeight
  }, [turns.length, messages.length, streamText, toolCards.length, streaming])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="min-h-0 flex-1 overflow-y-auto"
      aria-label="对话时间线"
    >
      <div className="mx-auto flex max-w-4xl flex-col gap-6 px-3 py-5 sm:px-5">
        {turns.length === 0 && !streaming && emptyState}
        {turns.map((turn, position) => (
          <TurnView
            key={`${turn.index}-${turn.user?.id ?? 'turn'}`}
            index={turn.index}
            user={turn.user}
            assistant={turn.assistant}
            stream={stream && position === turns.length - 1 ? stream : undefined}
            onCancelTool={onCancelTool}
            onResolveApproval={onResolveApproval}
            onOpenFile={onOpenFile}
          />
        ))}
        {streaming && turns.length === 0 && (
          <TurnView
            index={1}
            assistant={[]}
            stream={stream}
            onCancelTool={onCancelTool}
            onResolveApproval={onResolveApproval}
            onOpenFile={onOpenFile}
          />
        )}
      </div>
    </div>
  )
}
