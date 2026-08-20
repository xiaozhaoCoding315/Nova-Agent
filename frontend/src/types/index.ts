export interface ToolCallEvent {
  id: string
  name: string
  arguments: string
  result?: unknown
  duration_ms?: number
  done?: boolean
}

export interface Message {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  streaming?: boolean
  toolCalls?: ToolCallEvent[]
}

export interface RetrievedChunk {
  id: string
  content: string
  source: string
  score_type: string  // "dense" | "keyword" | "graph"
  score: number
}
