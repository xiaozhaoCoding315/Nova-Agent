import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { Repo } from '../lib/types'

type RepoState = {
  repos: Repo[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  uploadZip: (file: File) => Promise<void>
  importGit: (url: string) => Promise<void>
  remove: (id: string) => Promise<void>
  reindex: (id: string) => Promise<void>
  clearError: () => void
}

export const useRepos = create<RepoState>((set, get) => ({
  repos: [],
  loading: false,
  error: null,

  clearError: () => set({ error: null }),

  refresh: async () => {
    set({ loading: true })
    try {
      set({ repos: await api.repos.list(), error: null })
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '加载仓库失败' })
    } finally {
      set({ loading: false })
    }
  },

  uploadZip: async (file) => {
    set({ error: null })
    try {
      const repo = await api.repos.upload(file)
      set((s) => ({ repos: [repo, ...s.repos] }))
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '上传失败' })
      throw err
    }
  },

  importGit: async (url) => {
    set({ error: null })
    try {
      const repo = await api.repos.importGit(url)
      set((s) => ({ repos: [repo, ...s.repos] }))
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '导入失败' })
      throw err
    }
  },

  remove: async (id) => {
    try {
      await api.repos.remove(id)
      set((s) => ({ repos: s.repos.filter((r) => r.id !== id) }))
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '删除失败' })
    }
  },

  reindex: async (id) => {
    try {
      await api.repos.reindex(id)
      await get().refresh()
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '重建索引失败' })
    }
  },
}))