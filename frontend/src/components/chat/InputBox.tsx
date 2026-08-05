import { useState } from "react"
import { motion } from "framer-motion"
import { Send } from "lucide-react"
import { useChatStore } from "../../stores/chatStore"

interface Props {
  onSend: (text: string) => void
}

export default function InputBox({ onSend }: Props) {
  const [text, setText] = useState("")
  const isStreaming = useChatStore((s) => s.isStreaming)

  const handleSubmit = () => {
    if (!text.trim() || isStreaming) return
    onSend(text)
    setText("")
  }

  return (
    <div className="p-6 border-t border-cyber-border">
      <motion.div
        className="flex items-center gap-3 px-4 py-3 rounded-xl bg-cyber-surface border border-cyber-border focus-within:neon-border transition-all"
        animate={isStreaming ? { opacity: [1, 0.7, 1] } : { opacity: 1 }}
        transition={{ duration: 1.5, repeat: isStreaming ? Infinity : 0 }}
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
          placeholder="输入你的技术问题..."
          className="flex-1 bg-transparent outline-none text-cyber-text text-sm placeholder:text-cyber-textDim"
          disabled={isStreaming}
        />
        <button
          onClick={handleSubmit}
          disabled={isStreaming || !text.trim()}
          className="text-cyber-cyan disabled:text-cyber-textDim transition-colors"
        >
          <Send size={20} />
        </button>
      </motion.div>
    </div>
  )
}
