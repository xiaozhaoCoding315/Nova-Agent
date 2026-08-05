import { useCallback } from "react"
import { useChatStore } from "../stores/chatStore"
import type { RetrievedChunk } from "../types"

export function useSSE() {
  const sendMessage = useCallback(async (text: string) => {
    const store = useChatStore.getState()
    const sessionId = store.sessionId

    store.addMessage({ id: crypto.randomUUID(), role: "user", content: text })
    store.addMessage({ id: crypto.randomUUID(), role: "assistant", content: "", streaming: true })
    store.setIsStreaming(true)
    store.setRetrievalResults([])

    const res = await fetch("/api/v1/chat/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, session_id: sessionId }),
    })

    if (!res.body) return
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.type === "retrieval") {
            useChatStore.getState().setRetrievalResults(
              data.data as RetrievedChunk[]
            )
          } else if (data.type === "token") {
            const s = useChatStore.getState()
            const last = s.messages.at(-1)
            if (last) s.updateLastMessage(last.content + data.content, true)
          } else if (data.type === "done") {
            useChatStore.getState().setSessionId(data.session_id)
            const s = useChatStore.getState()
            const last = s.messages.at(-1)
            if (last) s.updateLastMessage(last.content, false)
            s.setIsStreaming(false)
          }
        } catch { /* skip malformed */ }
      }
    }
  }, [])

  return { sendMessage }
}
