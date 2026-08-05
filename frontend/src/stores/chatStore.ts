import { create } from "zustand"
import type { Message, RetrievedChunk } from "../types"

interface ChatState {
  messages: Message[]
  sessionId: string
  isStreaming: boolean
  retrievalResults: RetrievedChunk[]
  addMessage: (msg: Message) => void
  updateLastMessage: (content: string, streaming?: boolean) => void
  setSessionId: (id: string) => void
  setIsStreaming: (v: boolean) => void
  setRetrievalResults: (results: RetrievedChunk[]) => void
  clearMessages: () => void
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  sessionId: "",
  isStreaming: false,
  retrievalResults: [],
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  updateLastMessage: (content, streaming) =>
    set((s) => ({
      messages: s.messages.map((m, i) =>
        i === s.messages.length - 1 ? { ...m, content, streaming } : m
      ),
    })),
  setSessionId: (id) => set({ sessionId: id }),
  setIsStreaming: (v) => set({ isStreaming: v }),
  setRetrievalResults: (results) => set({ retrievalResults: results }),
  clearMessages: () => set({ messages: [], retrievalResults: [] }),
}))
