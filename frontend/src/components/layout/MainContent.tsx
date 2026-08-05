import type { ReactNode } from "react"

export default function MainContent({ children }: { children: ReactNode }) {
  return (
    <main className="flex-1 flex flex-col overflow-hidden bg-cyber-bg">
      {children}
    </main>
  )
}
