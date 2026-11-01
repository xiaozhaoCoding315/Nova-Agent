import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { AuthConfig, RegisterResult, User } from '../lib/types'
import { useChat } from './chat'
import { useLlm } from './llm'
import { useRepos } from './repos'
import { clearStoredRuns, useRun } from './run'

function resetUserData(options: { clearRunStorage?: boolean } = {}) {
  useChat.getState().reset()
  useRepos.getState().reset()
  useLlm.getState().reset()
  // 运行面板不属于 chat store：必须单独停轮询并清空，否则上一个账号的任务会
  // 被下一个账号看到，失败的轮询也会在后台一直重试。
  useRun.getState().reset()
  // 登录/登出等明确的账号切换要连按会话保存的运行记录一起清掉；初始 auth
  // 校验不清，保留同一浏览器刷新后的会话恢复能力。
  if (options.clearRunStorage) clearStoredRuns()
}

type AuthState = {
  user: User | null
  checked: boolean
  config: AuthConfig | null
  pendingRecoveryCode: string | null
  login: (username: string, password: string) => Promise<void>
  register: (username: string, password: string, options?: {
    displayName?: string
    inviteCode?: string
    email?: string
    emailCode?: string
  }) => Promise<RegisterResult>
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
      const previous = get().user
      if (previous?.id !== user.id) resetUserData({ clearRunStorage: Boolean(previous) })
      set({ user, checked: true })
    } catch {
      resetUserData({ clearRunStorage: Boolean(get().user) })
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
      resetUserData({ clearRunStorage: true })
      set({ user })
    } catch (err) {
      throw new ApiError(err instanceof ApiError ? err.status : 0,
        err instanceof ApiError ? err.message : '登录失败')
    }
  },

  register: async (username, password, options) => {
    const opts = options ?? {}
    const result = await api.register(username, password, opts.displayName, opts.inviteCode, opts.email, opts.emailCode)
    resetUserData({ clearRunStorage: true })
    set({ user: result.user, pendingRecoveryCode: result.recovery_code })
    return result
  },

  guest: async () => {
    const user = await api.guest()
    resetUserData({ clearRunStorage: true })
    set({ user })
  },

  logout: async () => {
    try {
      await api.logout()
    } finally {
      resetUserData({ clearRunStorage: true })
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
