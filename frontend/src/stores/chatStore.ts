import { create } from "zustand"
import type { Message, RetrievedChunk } from "../types"

const SESSION_STORAGE_KEY = "nova_session_id"

function getStoredSessionId(): string {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY) || ""
  } catch {
    return ""
  }
}

function storeSessionId(id: string): void {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, id)
  } catch {
    /* ignore storage errors */
  }
}

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
  sessionId: getStoredSessionId(),
  isStreaming: false,
  retrievalResults: [],
  addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
  updateLastMessage: (content, streaming) =>
    set((s) => ({
      messages: s.messages.map((m, i) =>
        i === s.messages.length - 1 ? { ...m, content, streaming } : m
      ),
    })),
  setSessionId: (id) => {
    storeSessionId(id)
    set({ sessionId: id })
  },
  setIsStreaming: (v) => set({ isStreaming: v }),
  setRetrievalResults: (results) => set({ retrievalResults: results }),
  clearMessages: () => set({ messages: [], retrievalResults: [] }),
}))
