import { FileText } from 'lucide-react'
import { EditCard } from '../components/EditCard'
import { Markdown } from '../components/Markdown'
import { PlanCard } from '../components/PlanCard'
import { Spinner } from '../components/common'
import { api } from '../lib/api'
import type {
  DeliveryReport, EditRef, Evidence, Message, PlanState, StreamToolCard, StreamUsage, ToolApproval,
} from '../lib/types'
import { ApprovalCard } from './ApprovalCard'
import { EvidenceStrip } from './EvidenceStrip'
import { RunSummary } from './RunSummary'
import { SignalGutter } from './SignalGutter'
import { ToolCardView } from './ToolCard'
import { eventToCard, formatBytes, toolLabel } from './cards'

export type TurnStream = {
  text: string
  toolCards: StreamToolCard[]
  editProposals: EditRef[]
  plan: PlanState | null
  approvals: ToolApproval[]
  usage?: StreamUsage | null
}

function formatTime(value?: string): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

function formatDuration(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function lastEvidence(assistant: Message[]): Evidence | null {
  for (let index = assistant.length - 1; index >= 0; index -= 1) {
    const evidence = assistant[index].tool_json?.evidence
    if (evidence) return evidence
  }
  return null
}

function UserLine({ message }: { message: Message }) {
  const attachments = message.attachments ?? []
  const time = formatTime(message.created_at)
  return (
    <div className="flex items-start gap-2">
      <span className="shrink-0 font-mono text-md leading-relaxed text-accent">›</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-3">
          <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-md leading-relaxed text-ink">
            {message.content}
          </p>
          {time && <span className="shrink-0 pt-0.5 font-mono text-2xs text-faint">{time}</span>}
        </div>
        {attachments.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {attachments.map((file) => (
              <a
                key={file.id}
                href={api.files.downloadUrl(file.id)}
                className="flex max-w-[220px] items-center gap-1 rounded-sm border border-edge bg-raised/60 px-2 py-0.5 font-mono text-2xs text-dim transition-colors duration-150 hover:border-faint hover:text-ink"
                title={`下载 ${file.filename}`}
              >
                <FileText size={11} className="shrink-0" />
                <span className="truncate">{file.filename}</span>
                <span className="shrink-0 text-faint">{formatBytes(file.size)}</span>
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function AssistantMessage({
  message,
  onOpenFile,
}: {
  message: Message
  onOpenFile?: (path: string) => void
}) {
  const tools = message.tool_json?.tools_used ?? []
  const events = message.tool_json?.tool_events ?? []
  const evidence = message.tool_json?.evidence
  const edits = message.tool_json?.edits ?? []
  const plan = message.tool_json?.plan ?? null
  const report = message.tool_json?.report ?? null

  return (
    <div className="space-y-2">
      {plan && <PlanCard plan={plan} />}
      {events.length > 0 && (
        <div className="space-y-1.5">
          {events.map((event, index) => (
            <ToolCardView
              key={`${message.id}-event-${index}`}
              card={eventToCard(event, index)}
              onOpenFile={onOpenFile}
            />
          ))}
        </div>
      )}
      {message.content.trim() ? <Markdown content={message.content} /> : null}
      {tools.length > 0 && events.length === 0 && (
        <p className="font-mono text-2xs text-faint">
          工具 · {tools.map(toolLabel).join('、')}
        </p>
      )}
      {edits.map((edit) => <EditCard key={edit.id} edit={edit} />)}
      {evidence && <EvidenceStrip evidence={evidence} onOpenFile={onOpenFile} />}
      <RunSummary report={report} />
    </div>
  )
}

function StreamingContent({
  stream,
  onCancelTool,
  onResolveApproval,
  onOpenFile,
}: {
  stream: TurnStream
  onCancelTool?: (toolCallId: string) => void
  onResolveApproval?: (toolCallId: string, approved: boolean) => void
  onOpenFile?: (path: string) => void
}) {
  const running = stream.toolCards.find((card) => !card.result)
  const statusText = running
    ? `正在执行 ${toolLabel(running.call.name)}…`
    : stream.toolCards.length > 0
      ? '工具执行完毕，等待模型总结…'
      : '思考中…'
  const totalTokens = stream.usage
    ? stream.usage.prompt_tokens + stream.usage.completion_tokens
    : 0

  return (
    <div className="space-y-2">
      {stream.plan && <PlanCard plan={stream.plan} />}
      {stream.approvals.map((approval) => (
        <ApprovalCard
          key={approval.id}
          approval={approval}
          onResolve={(approved) => onResolveApproval?.(approval.id, approved)}
        />
      ))}
      {stream.toolCards.length > 0 && (
        <div className="space-y-1.5">
          {stream.toolCards.map((card) => (
            <ToolCardView
              key={card.call.id}
              card={card}
              onCancel={onCancelTool ? () => onCancelTool(card.call.id) : undefined}
              onOpenFile={onOpenFile}
            />
          ))}
        </div>
      )}
      {stream.text ? (
        <Markdown content={stream.text} />
      ) : (
        <p className="flex items-center gap-2 text-sm text-dim">
          <Spinner className="h-3 w-3" />
          {statusText}
        </p>
      )}
      {totalTokens > 0 && (
        <p className="font-mono text-2xs text-faint">本轮用量 {totalTokens.toLocaleString()} tokens</p>
      )}
      {stream.editProposals.map((edit) => <EditCard key={edit.id} edit={edit} />)}
    </div>
  )
}

/** 单轮：信号轨 + 用户指令 + agent 内容 + 轮末元数据。 */
export function TurnView({
  index,
  user,
  assistant,
  stream,
  onCancelTool,
  onResolveApproval,
  onOpenFile,
}: {
  index: number
  user?: Message
  assistant: Message[]
  stream?: TurnStream
  onCancelTool?: (toolCallId: string) => void
  onResolveApproval?: (toolCallId: string, approved: boolean) => void
  onOpenFile?: (path: string) => void
}) {
  const events = assistant.flatMap((message) => message.tool_json?.tool_events ?? [])
  const namedTools = assistant.flatMap((message) => message.tool_json?.tools_used ?? [])
  const toolCount = events.length > 0 ? events.length : namedTools.length
  const evidence = lastEvidence(assistant)

  const report = [...assistant]
    .reverse()
    .map((message) => message.tool_json?.report)
    .find((item): item is DeliveryReport => Boolean(item))
  const elapsed = report?.stats.elapsed_ms
    ?? events.reduce((sum, event) => sum + (Number.isFinite(event.ms) ? event.ms : 0), 0)

  const meta: string[] = []
  if (toolCount > 0) meta.push(`${toolCount} 个工具`)
  if (elapsed > 0) meta.push(formatDuration(elapsed))
  if (evidence && evidence.citations.length > 0) {
    meta.push(`证据 ${evidence.verified}/${evidence.citations.length}`)
  }

  return (
    <div className="flex items-stretch gap-2 md:gap-3">
      <SignalGutter
        index={index}
        tools={toolCount + (stream?.toolCards.length ?? 0)}
        evidence={evidence}
        active={Boolean(stream)}
      />
      <div className="min-w-0 flex-1 pb-1">
        {user && <UserLine message={user} />}
        <div className={user ? 'mt-2 space-y-3' : 'space-y-3'}>
          {assistant.map((message) => (
            <AssistantMessage key={message.id} message={message} onOpenFile={onOpenFile} />
          ))}
          {stream && (
            <StreamingContent
              stream={stream}
              onCancelTool={onCancelTool}
              onResolveApproval={onResolveApproval}
              onOpenFile={onOpenFile}
            />
          )}
        </div>
        {!stream && meta.length > 0 && (
          <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-edge/60 pt-1.5 font-mono text-2xs text-faint">
            {meta.join(' · ')}
          </p>
        )}
      </div>
    </div>
  )
}
