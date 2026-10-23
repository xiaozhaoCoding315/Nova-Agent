import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { AuthConfig, RegisterResult, User } from '../lib/types'
import { useChat } from './chat'
import { useLlm } from './llm'
import { useRepos } from './repos'

function resetUserData() {
  useChat.getState().reset()
  useRepos.getState().reset()
  useLlm.getState().reset()
}

type AuthState = {
  user: User | null
  checked: boolean
  config: AuthConfig | null
  pendingRecoveryCode: string | null
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, displayName?: string, inviteCode?: string) => Promise<RegisterResult>
  guest: () => Promise<void>
  logout: () => Promise<void>
  check: () => Promise<void>
  loadConfig: () => Promise<void>
  updateProfile: (displayName: string) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  clearRecoveryCode: () => void
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  checked: false,
  config: null,
  pendingRecoveryCode: null,

  check: async () => {
    try {
      const user = await api.me()
      if (get().user?.id !== user.id) resetUserData()
      set({ user, checked: true })
    } catch {
      resetUserData()
      set({ user: null, checked: true })
    }
  },

  loadConfig: async () => {
    try {
      set({ config: await api.authConfig() })
    } catch {
      /* configuration is optional for the login screen */
    }
  },

  login: async (username, password) => {
    try {
      const user = await api.login(username, password)
      resetUserData()
      set({ user })
    } catch (err) {
      throw new ApiError(err instanceof ApiError ? err.status : 0,
        err instanceof ApiError ? err.message : '登录失败')
    }
  },

  register: async (username, password, displayName, inviteCode) => {
    const result = await api.register(username, password, displayName, inviteCode)
    resetUserData()
    set({ user: result.user, pendingRecoveryCode: result.recovery_code })
    return result
  },

  guest: async () => {
    const user = await api.guest()
    resetUserData()
    set({ user })
  },

  logout: async () => {
    try {
      await api.logout()
    } finally {
      resetUserData()
      set({ user: null, pendingRecoveryCode: null })
    }
  },

  updateProfile: async (displayName) => {
    set({ user: await api.updateProfile(displayName) })
  },

  changePassword: async (currentPassword, newPassword) => {
    set({ user: await api.changePassword(currentPassword, newPassword) })
  },

  clearRecoveryCode: () => set({ pendingRecoveryCode: null }),
}))
