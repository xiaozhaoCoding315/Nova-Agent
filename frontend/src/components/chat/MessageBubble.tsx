import { motion } from "framer-motion"
import type { Message } from "../../types"

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
        <p className="whitespace-pre-wrap">{message.content}</p>
        {message.streaming && (
          <span className="inline-block w-2 h-4 ml-1 bg-cyber-cyan animate-pulse" />
        )}
      </div>
    </motion.div>
  )
}
