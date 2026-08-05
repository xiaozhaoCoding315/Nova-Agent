import { useRef, useEffect, useState } from "react"
import MessageBubble from "./MessageBubble"
import InputBox from "./InputBox"
import RetrievalPanel from "./RetrievalPanel"
import UploadDialog from "../knowledge/UploadDialog"
import { useChatStore } from "../../stores/chatStore"
import { useSSE } from "../../hooks/useSSE"
import { Upload } from "lucide-react"

export default function ChatWindow() {
  const messages = useChatStore((s) => s.messages)
  const retrievalCount = useChatStore((s) => s.retrievalResults.length)
  const { sendMessage } = useSSE()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [showUpload, setShowUpload] = useState(false)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [messages])

  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="px-6 py-2 border-b border-cyber-border flex items-center justify-between">
          <span className="text-cyber-textDim text-xs">技术问答</span>
          <button
            onClick={() => setShowUpload(true)}
            className="flex items-center gap-1 px-3 py-1 text-xs text-cyber-cyan border border-cyber-cyan/30 rounded-lg hover:bg-cyber-cyan/10 transition-colors"
          >
            <Upload size={14} />
            上传文档
          </button>
        </div>
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-6">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center gap-4">
              <h2 className="text-cyber-textDim text-lg">开始你的技术探索之旅</h2>
              <button
                onClick={() => setShowUpload(true)}
                className="px-4 py-2 border border-cyber-cyan text-cyber-cyan rounded-lg text-sm hover:bg-cyber-cyan/10"
              >
                先上传文档,再开始问答
              </button>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
        </div>
        <InputBox onSend={sendMessage} />
      </div>
      {retrievalCount > 0 && <RetrievalPanel />}
      <UploadDialog open={showUpload} onClose={() => setShowUpload(false)} />
    </div>
  )
}
