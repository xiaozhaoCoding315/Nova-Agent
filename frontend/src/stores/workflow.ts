import { create } from 'zustand'

type WorkflowState = {
  /** Requirement text carried from a chat suggestion into the change form. */
  pendingRequirements: string | null
  setPendingRequirements: (text: string | null) => void
}

export const useWorkflow = create<WorkflowState>((set) => ({
  pendingRequirements: null,
  setPendingRequirements: (text) => set({ pendingRequirements: text }),
}))
