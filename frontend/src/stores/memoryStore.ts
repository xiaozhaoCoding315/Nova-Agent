import { create } from "zustand"
import { getGraphStats, searchGraph, getMemoryProfile, getMemoryStats, archiveSession, getMemorySummary } from "../services/api"

export interface GraphNode {
  id: string
  label: string
  type: string
  properties?: Record<string, unknown>
}

export interface GraphEdge {
  source: string
  target: string
  type: string
}

export interface GraphStats {
  entity_count: number
  relationship_count: number
  top_entities: { name: string; type: string; count: number }[]
  type_distribution: Record<string, number>
}

export interface GraphExploreResult {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface MemoryProfile {
  summary: string
  top_topics: string[]
  preferences: Record<string, string>
  question_patterns: string[]
}

export interface MemoryStatsOverview {
  total_sessions: number
  total_facts: number
  facts_last_7_days: number
  avg_session_length: number
}

interface MemoryState {
  // Graph stats
  graphStats: GraphStats | null
  graphLoading: boolean
  graphError: string | null

  // Graph exploration
  exploreResult: GraphExploreResult | null
  exploreLoading: boolean
  exploreError: string | null

  // Memory profile
  profile: MemoryProfile | null
  profileLoading: boolean
  profileError: string | null

  // Memory stats overview
  overview: MemoryStatsOverview | null
  overviewLoading: boolean

  // Session session summary
  sessionSummary: Awaited<ReturnType<typeof getMemorySummary>> | null
  summaryLoading: boolean

  // Actions
  fetchGraphStats: () => Promise<void>
  exploreEntity: (entity: string, depth?: number) => Promise<void>
  fetchProfile: (sessionId: string) => Promise<void>
  fetchOverview: () => Promise<void>
  fetchSessionSummary: (sessionId: string) => Promise<void>
  triggerArchive: (sessionId: string) => Promise<void>
}

export const useMemoryStore = create<MemoryState>((set) => ({
  graphStats: null,
  graphLoading: false,
  graphError: null,

  exploreResult: null,
  exploreLoading: false,
  exploreError: null,

  profile: null,
  profileLoading: false,
  profileError: null,

  overview: null,
  overviewLoading: false,

  sessionSummary: null,
  summaryLoading: false,

  fetchGraphStats: async () => {
    set({ graphLoading: true, graphError: null })
    try {
      const data = await getGraphStats()
      set({ graphStats: data as GraphStats })
    } catch (e) {
      set({ graphError: e instanceof Error ? e.message : "Failed to load graph stats" })
    } finally {
      set({ graphLoading: false })
    }
  },

  exploreEntity: async (entity: string, depth: number = 2) => {
    set({ exploreLoading: true, exploreError: null })
    try {
      const data = await searchGraph(entity, depth)
      set({ exploreResult: data as GraphExploreResult })
    } catch (e) {
      set({ exploreError: e instanceof Error ? e.message : "Failed to explore entity" })
    } finally {
      set({ exploreLoading: false })
    }
  },

  fetchProfile: async (sessionId: string) => {
    set({ profileLoading: true, profileError: null })
    try {
      const data = await getMemoryProfile(sessionId)
      set({ profile: data as MemoryProfile })
    } catch (e) {
      set({ profileError: e instanceof Error ? e.message : "Failed to load profile" })
    } finally {
      set({ profileLoading: false })
    }
  },

  fetchOverview: async () => {
    set({ overviewLoading: true })
    try {
      const data = await getMemoryStats()
      set({ overview: data as MemoryStatsOverview })
    } catch {
      set({ overview: null })
    } finally {
      set({ overviewLoading: false })
    }
  },

  fetchSessionSummary: async (sessionId: string) => {
    set({ summaryLoading: true })
    try {
      const data = await getMemorySummary(sessionId)
      set({ sessionSummary: data })
    } catch {
      set({ sessionSummary: null })
    } finally {
      set({ summaryLoading: false })
    }
  },

  triggerArchive: async (sessionId: string) => {
    await archiveSession(sessionId)
  },
}))
