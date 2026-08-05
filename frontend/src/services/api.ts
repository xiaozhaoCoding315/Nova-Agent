import axios from "axios"

const http = axios.create({ baseURL: "/api/v1", timeout: 120000 })

// === Knowledge ===
export async function uploadDocument(file: File) {
  const form = new FormData()
  form.append("file", file)
  const { data } = await http.post("/knowledge/upload", form, {
    headers: { "Content-Type": "multipart/form-data" },
  })
  return data
}

export async function listDocuments() {
  const { data } = await http.get("/knowledge")
  return data
}

export async function deleteDocument(name: string) {
  const { data } = await http.delete(`/knowledge/${encodeURIComponent(name)}`)
  return data
}

// === Memory & Graph ===
export async function getMemorySummary(sessionId: string) {
  const { data } = await http.get(`/memory/${sessionId}`)
  return data
}

export async function getGraphStats() {
  const { data } = await http.get("/graph/stats")
  return data
}

export async function searchGraph(entity: string, depth: number = 2) {
  const { data } = await http.get(`/graph/search?entity=${encodeURIComponent(entity)}&depth=${depth}`)
  return data
}

export async function getMemoryProfile(sessionId: string) {
  const { data } = await http.get(`/memory/${sessionId}/profile`)
  return data
}

export async function getMemoryStats() {
  const { data } = await http.get("/memory/stats/overview")
  return data
}

export async function archiveSession(sessionId: string) {
  const { data } = await http.post(`/memory/${sessionId}/archive`)
  return data
}

// === Evaluation ===
export async function evalSingle(query: string) {
  const { data } = await http.post("/eval/single", { query, relevant_ids: null })
  return data
}

export async function evalSuite(queries: string[], mode = "all") {
  const { data } = await http.post("/eval/suite", {
    queries: queries.map(q => ({ query: q, relevant_ids: null })),
    mode,
  })
  return data
}

export async function listDatasetQueries() {
  const { data } = await http.get("/dataset/queries")
  return data
}

export async function seedDataset() {
  const { data } = await http.post("/dataset/seed")
  return data
}

export async function getDatasetStats() {
  const { data } = await http.get("/dataset/stats")
  return data
}

export async function addGoldenQuery(query: string, category: string, notes: string = "") {
  const { data } = await http.post("/dataset/queries", { query, category, relevant_ids: [], notes })
  return data
}

export async function deleteGoldenQuery(id: number) {
  const { data } = await http.delete(`/dataset/queries/${id}`)
  return data
}

// === System / Admin ===
export async function getHarnessStatus() {
  const { data } = await http.get("/harness/status")
  return data
}

export async function getSandboxStatus() {
  const { data } = await http.get("/sandbox/status")
  return data
}

export async function getAuditLog(action: string = "", limit: number = 100) {
  const { data } = await http.get(`/audit/log${action ? "?action=" + action : ""}&limit=${limit}`)
  return data
}

export async function getAuditStats() {
  const { data } = await http.get("/audit/stats")
  return data
}

export async function validateInput(code: string = "", prompt: string = "") {
  const { data } = await http.post("/security/validate", { code, prompt })
  return data
}

export async function runSandboxCode(code: string, language: string = "python", timeout: number = 30) {
  const { data } = await http.post("/sandbox/execute", { code, language, inputs: "", timeout })
  return data
}

// === Tasks (DAG orchestration) ===
export async function decomposeTask(task: string): Promise<DAGPayload> {
  const { data } = await http.post("/tasks/decompose", { task })
  return data as DAGPayload
}

export interface DAGNode {
  id: string
  name: string
  task_type: string
  action?: string
  depends_on?: string[]
  status?: "pending" | "running" | "completed" | "failed"
}

export interface DAGPayload {
  nodes: DAGNode[]
  description?: string
}

/**
 * Stream task execution events from the backend.
 * Returns an unsubscribe/abort function.
 *
 * Expected event shapes:
 *   { type: "node_started",   node_id: string }
 *   { type: "node_completed", node_id: string }
 *   { type: "node_failed",    node_id: string, error?: string }
 *   { type: "dag_completed",  result?: unknown }
 */
export function executeTaskStream(task: string, onEvent: (event: any) => void): () => void {
  const controller = new AbortController()

  fetch("/api/v1/tasks/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task }),
    signal: controller.signal,
  })
    .then(async (res) => {
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
          if (line.startsWith("data: ")) {
            try {
              onEvent(JSON.parse(line.slice(6)))
            } catch {
              // ignore malformed event frames
            }
          }
        }
      }
    })
    .catch((e) => {
      if (e.name !== "AbortError") console.error("Task stream error:", e)
    })

  return () => controller.abort()
}
