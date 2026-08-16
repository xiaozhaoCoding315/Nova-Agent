import { create } from "zustand"
import { evalSingle, evalSuite, listDatasetQueries, seedDataset, getDatasetStats, addGoldenQuery, deleteGoldenQuery } from "../services/api"

interface EvalResult {
  query: string
  retrieval_time_ms: number
  retrieved_count: number
  retrieval_metrics?: Record<string, number>
  answer?: string
  ragas_scores?: Record<string, number>
}

interface EvalState {
  results: EvalResult[]
  running: boolean
  datasetQueries: { id: number; query: string; category: string; notes: string; relevant_ids?: string[] | null }[]
  datasetStats: any
  runSingle: (query: string, relevantIds?: string[] | null) => Promise<void>
  runSuite: (queries: { query: string; relevant_ids: string[] | null }[]) => Promise<void>
  loadDataset: () => Promise<void>
  seedData: () => Promise<void>
  loadStats: () => Promise<void>
  addQuery: (query: string, category: string, notes?: string) => Promise<void>
  removeQuery: (id: number) => Promise<void>
}

export const useEvalStore = create<EvalState>((set, get) => ({
  results: [],
  running: false,
  datasetQueries: [],
  datasetStats: null,

  runSingle: async (query: string, relevantIds: string[] | null = null) => {
    set({ running: true })
    try {
      const result = await evalSingle(query, relevantIds)
      set((s) => ({ results: [result, ...s.results].slice(0, 50) }))
    } finally {
      set({ running: false })
    }
  },

  runSuite: async (queries: { query: string; relevant_ids: string[] | null }[]) => {
    set({ running: true })
    try {
      const result = await evalSuite(queries)
      if (result.results) {
        set((s) => ({ results: [...result.results, ...s.results].slice(0, 50) }))
      }
    } finally {
      set({ running: false })
    }
  },

  loadDataset: async () => {
    const data = await listDatasetQueries()
    set({ datasetQueries: data })
  },

  seedData: async () => {
    await seedDataset()
    await get().loadDataset()
    await get().loadStats()
  },

  loadStats: async () => {
    const stats = await getDatasetStats()
    set({ datasetStats: stats })
  },

  addQuery: async (query, category, notes) => {
    await addGoldenQuery(query, category, notes)
    await get().loadDataset()
    await get().loadStats()
  },

  removeQuery: async (id) => {
    await deleteGoldenQuery(id)
    await get().loadDataset()
    await get().loadStats()
  },
}))
