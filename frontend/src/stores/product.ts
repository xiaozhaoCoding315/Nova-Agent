import { create } from 'zustand'

export type ProductMode = 'dev' | 'thesis'

const STORAGE_KEY = 'nova.product-mode'

function readMode(): ProductMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'thesis' ? 'thesis' : 'dev'
  } catch {
    return 'dev'
  }
}

type ProductState = {
  mode: ProductMode
  setMode: (mode: ProductMode) => void
}

/** Product surface, not the server/local runtime mode in `useMode`. */
export const useProduct = create<ProductState>((set) => ({
  mode: readMode(),
  setMode: (mode) => {
    set({ mode })
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      /* localStorage 不可用时只失去记忆 */
    }
  },
}))
