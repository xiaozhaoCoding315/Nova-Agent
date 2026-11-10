import { FileText } from 'lucide-react'
import { EditCard } from '../components/EditCard'
import { Markdown } from '../components/Markdown'
import { PlanCard } from '../components/PlanCard'
import { DotLoader } from './DotLoader'
import { api } from '../lib/api'
import { isVisionImage } from '../lib/attachments'
import type {
  DeliveryReport, EditRef, Evidence, Message, PlanState, StreamToolCard, StreamUsage, SubagentRun,
  ToolApproval,
} from '../lib/types'
import { formatBytes } from '../lib/ui'
import { ApprovalCard } from './ApprovalCard'
import { EvidenceStrip } from './EvidenceStrip'
import { RunSummary } from './RunSummary'
import { SignalGutter } from './SignalGutter'
import { SubagentPanel } from './SubagentPanel'
import { ToolCardView } from './ToolCard'
import { eventToCard, SUBAGENT_TOOL, toolLabel } from './cards'

export type TurnStream = {
  text: string
  toolCards: StreamToolCard[]
  editProposals: EditRef[]
  plan: PlanState | null
  approvals: ToolApproval[]
  subagents: SubagentRun[]
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
  const imageAttachments = attachments.filter(isVisionImage)
  const fileAttachments = attachments.filter((file) => !isVisionImage(file))
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
        {imageAttachments.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {imageAttachments.map((file) => (
              <a
                key={file.id}
                href={api.files.downloadUrl(file.id)}
                target="_blank"
                rel="noreferrer"
                className="block overflow-hidden rounded-sm border border-edge transition-colors duration-150 hover:border-faint"
                title={`查看 ${file.filename}`}
              >
                <img
                  src={api.files.downloadUrl(file.id)}
                  alt={file.filename}
                  className="h-24 w-24 object-cover"
                  loading="lazy"
                />
              </a>
            ))}
          </div>
        )}
        {fileAttachments.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {fileAttachments.map((file) => (
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
  const subagents = message.tool_json?.subagents ?? []
  const visibleEvents = events.filter(
    (event) => event.name !== SUBAGENT_TOOL || !event.ok || subagents.length === 0,
  )

  return (
    <div className="space-y-2">
      {plan && <PlanCard plan={plan} />}
      <SubagentPanel runs={subagents} onOpenFile={onOpenFile} />
      {visibleEvents.length > 0 && (
        <div className="space-y-1.5">
          {visibleEvents.map((event, index) => (
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
  const visibleCards = stream.toolCards.filter(
    (card) =>
      card.call.name !== SUBAGENT_TOOL
      || card.result?.ok === false
      || stream.subagents.length === 0,
  )
  const activeSubagent = stream.subagents.find((run) => run.status === 'running')
  const running = visibleCards.find((card) => !card.result)
  const statusText = activeSubagent
    ? `子代理「${activeSubagent.title}」调研中…`
    : running
      ? `正在执行 ${toolLabel(running.call.name)}…`
      : visibleCards.length > 0
        ? '工具执行完毕，等待模型总结…'
        : '思考中…'
  const totalTokens = stream.usage
    ? stream.usage.prompt_tokens + stream.usage.completion_tokens
    : 0

  return (
    <div className="space-y-2">
      {stream.plan && <PlanCard plan={stream.plan} />}
      <SubagentPanel runs={stream.subagents} onOpenFile={onOpenFile} />
      {stream.approvals.map((approval) => (
        <ApprovalCard
          key={approval.id}
          approval={approval}
          onResolve={(approved) => onResolveApproval?.(approval.id, approved)}
        />
      ))}
      {visibleCards.length > 0 && (
        <div className="space-y-1.5">
          {visibleCards.map((card) => (
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
          <DotLoader />
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

  // 细节默认收成一簇，悬停/聚焦才展开：证据圆点已经在左侧信号轨上，
  // 这里再排一串等宽文字只会让轮末变成一堵墙。
  // 只收「证据」这一类：轮数、tokens 这类数字在 RunSummary 里已经有了，
  // 塞进来会让 `+N` 变成一个没有信息量的按钮。
  const detail: string[] = []
  if (evidence) {
    if (evidence.citations.length > 0) {
      detail.push(`证据 ${evidence.verified}/${evidence.citations.length}`)
    }
    if (evidence.missing > 0) detail.push(`缺引用 ${evidence.missing}`)
    if (evidence.executed) detail.push('沙箱实测')
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
        {!stream && (meta.length > 0 || detail.length > 0) && (
          <div className="mt-3 flex items-center gap-1.5 border-t border-edge/60 pt-1.5 font-mono text-2xs text-faint">
            {meta.length > 0 && <span>{meta.join(' · ')}</span>}
            {detail.length > 0 && (
              <div className="group/meta relative">
                <button
                  type="button"
                  className="rounded px-1 text-faint transition-colors duration-150 hover:bg-raised hover:text-dim focus-visible:bg-raised focus-visible:text-dim"
                  aria-label={`本轮详情：${detail.join('，')}`}
                >
                  +{detail.length}
                </button>
                <span
                  role="tooltip"
                  className="pointer-events-none invisible absolute bottom-full left-0 z-10 mb-1 whitespace-nowrap rounded-md border border-edge bg-panel px-2 py-1 text-2xs text-dim opacity-0 shadow-pop transition-opacity duration-150 group-hover/meta:visible group-hover/meta:opacity-100 group-focus-within/meta:visible group-focus-within/meta:opacity-100"
                >
                  {detail.join(' · ')}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
