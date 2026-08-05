import { create } from "zustand"
import { listDocuments, uploadDocument } from "../services/api"

interface DocItem {
  name: string
  chunks: number
}

interface KnowledgeState {
  documents: DocItem[]
  loading: boolean
  fetchDocs: () => Promise<void>
  upload: (file: File) => Promise<void>
  removeDoc: (name: string) => Promise<void>
}

export const useKnowledgeStore = create<KnowledgeState>((set) => ({
  documents: [],
  loading: false,
  fetchDocs: async () => {
    set({ loading: true })
    try {
      const { documents } = await listDocuments()
      set({ documents: documents as DocItem[] })
    } catch {
      set({ documents: [] })
    } finally {
      set({ loading: false })
    }
  },
  upload: async (file: File) => {
    await uploadDocument(file)
    await useKnowledgeStore.getState().fetchDocs()
  },
  removeDoc: async (name: string) => {
    await fetch(`/api/v1/knowledge/${encodeURIComponent(name)}`, { method: "DELETE" })
    await useKnowledgeStore.getState().fetchDocs()
  },
}))
