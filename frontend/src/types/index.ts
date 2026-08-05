export interface Message {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  streaming?: boolean
}

export interface RetrievedChunk {
  id: string
  content: string
  source: string
  score_type: string  // "dense" | "keyword" | "graph"
  score: number
}
