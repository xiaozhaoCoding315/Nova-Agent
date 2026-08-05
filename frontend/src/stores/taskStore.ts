import { create } from "zustand"
import { type DAGNode, decomposeTask, executeTaskStream } from "../services/api"

export interface NodeResult {
  node_id: string
  node_name: string
  result: string
}

interface TaskState {
  nodes: DAGNode[]
  taskDescription: string
  running: boolean
  result: string | null
  nodeResults: NodeResult[]
  decomposing: boolean

  setNodes: (nodes: DAGNode[] | ((prev: DAGNode[]) => DAGNode[])) => void
  setTaskDescription: (desc: string) => void
  setRunning: (v: boolean) => void
  setResult: (r: string | null) => void
  updateNodeStatus: (nodeId: string, status: DAGNode["status"]) => void
  addNodeResult: (r: NodeResult) => void

  createTask: (description: string) => Promise<void>
  executeTask: (description: string) => void
}

export const useTaskStore = create<TaskState>((set, get) => ({
  nodes: [],
  taskDescription: "",
  running: false,
  result: null,
  nodeResults: [],
  decomposing: false,

  setNodes: (nodes) => {
    if (typeof nodes === "function") set((s) => ({ nodes: nodes(s.nodes) }))
    else set({ nodes })
  },
  setTaskDescription: (desc) => set({ taskDescription: desc }),
  setRunning: (v) => set({ running: v }),
  setResult: (r) => set({ result: r }),
  updateNodeStatus: (nodeId, status) => {
    set((s) => ({ nodes: s.nodes.map((n) => (n.id === nodeId ? { ...n, status } : n)) }))
  },
  addNodeResult: (r) => set((s) => ({ nodeResults: [...s.nodeResults, r] })),

  createTask: async (description: string) => {
    set({ decomposing: true })
    try {
      const dag = await decomposeTask(description)
      set({
        nodes: (dag.nodes || []).map((n: DAGNode) => ({ ...n, status: n.status || "pending" })),
        taskDescription: description,
        result: null,
        nodeResults: [],
        decomposing: false,
      })
    } catch {
      set({
        nodes: [{ id: "node_1", name: description, task_type: "research", action: description, status: "pending" }],
        taskDescription: description,
        result: null,
        nodeResults: [],
        decomposing: false,
      })
    }
  },

  executeTask: (description: string) => {
    set((s) => ({
      nodes: s.nodes.map((n: DAGNode) => ({ ...n, status: "pending" as const })),
      result: null,
      nodeResults: [],
      running: true,
    }))

    executeTaskStream(description, (event: any) => {
      const state = get()
      switch (event?.type) {
        case "node_started":
          state.updateNodeStatus(event.node_id, "running")
          break
        case "node_completed":
          state.updateNodeStatus(event.node_id, "completed")
          if (event.result) {
            const node = get().nodes.find((n: DAGNode) => n.id === event.node_id)
            state.addNodeResult({
              node_id: event.node_id,
              node_name: event.node_name || (node?.name ?? event.node_id),
              result: typeof event.result === "string" ? event.result : JSON.stringify(event.result),
            })
          }
          break
        case "node_failed":
          state.updateNodeStatus(event.node_id, "failed")
          break
        case "dag_completed":
          set({ running: false })
          break
      }
    })
  },
}))
