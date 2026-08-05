import { useState } from "react"
import Sidebar, { TabKey } from "./components/layout/Sidebar"
import Header from "./components/layout/Header"
import ChatWindow from "./components/chat/ChatWindow"
import KnowledgePanel from "./components/knowledge/KnowledgePanel"
import MemoryPanel from "./components/memory/MemoryPanel"
import EvaluationPanel from "./components/eval/EvaluationPanel"
import TaskPanel from "./components/tasks/TaskPanel"
import AdminPanel from "./components/admin/AdminPanel"

export default function App() {
  const [tab, setTab] = useState<TabKey>("chat")

  return (
    <div className="h-screen flex flex-col bg-cyber-bg relative">
      <Header />
      <div className="flex-1 flex overflow-hidden z-10">
        <Sidebar active={tab} onChange={setTab} />
        <main className="flex-1 flex flex-col overflow-hidden bg-cyber-bg">
          {tab === "chat" && <ChatWindow />}
          {tab === "knowledge" && <KnowledgePanel />}
          {tab === "memory" && <MemoryPanel />}
          {tab === "eval" && <EvaluationPanel />}
          {tab === "tasks" && <TaskPanel />}
          {tab === "admin" && <AdminPanel />}
        </main>
      </div>
    </div>
  )
}
