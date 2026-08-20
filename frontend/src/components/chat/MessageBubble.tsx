import { motion } from "framer-motion"
import type { Message, ToolCallEvent } from "../../types"

const TOOL_LABELS: Record<string, string> = {
  calculator: "计算器",
  db_query: "数据库查询",
  doc_parser: "文档解析",
}

function ToolCallCard({ tc }: { tc: ToolCallEvent }) {
  const label = TOOL_LABELS[tc.name] || tc.name
  let resultText = ""
  try {
    resultText = tc.result === undefined ? "" : JSON.stringify(tc.result, null, 2)
  } catch {
    resultText = String(tc.result)
  }
  return (
    <details className="group mt-2 rounded-lg border border-cyber-cyan/30 bg-cyber-bg/60 text-xs">
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-cyber-cyan select-none">
        <span className="font-mono">[ {tc.name} ]</span>
        <span>{label}</span>
        <span className="ml-auto text-cyber-text/60">
          {tc.done ? `${tc.duration_ms ?? 0}ms` : "执行中..."}
        </span>
      </summary>
      <div className="px-3 pb-2 space-y-1.5">
        <div>
          <div className="text-cyber-text/50 mb-0.5">入参</div>
          <pre className="whitespace-pre-wrap break-all font-mono text-cyber-text/80">
            {tc.arguments}
          </pre>
        </div>
        {resultText && (
          <div>
            <div className="text-cyber-text/50 mb-0.5">结果</div>
            <pre className="whitespace-pre-wrap break-all font-mono text-cyber-text/80 max-h-48 overflow-y-auto">
              {resultText}
            </pre>
          </div>
        )}
      </div>
    </details>
  )
}

export default function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user"
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"} mb-4`}
    >
      <div
        className={`max-w-[70%] px-4 py-3 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? "bg-cyber-purple/20 text-cyber-text border border-cyber-purple/30"
            : "bg-cyber-surface text-cyber-text border border-cyber-border"
        }`}
      >
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mb-1">
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} tc={tc} />
            ))}
          </div>
        )}
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.streaming && (
          <span className="inline-block w-2 h-4 ml-1 bg-cyber-cyan animate-pulse" />
        )}
      </div>
    </motion.div>
  )
}
