import { motion } from "framer-motion"
import { MessageSquare, BookOpen, Brain, Wrench, BarChart3, Shield } from "lucide-react"

export type TabKey = "chat" | "knowledge" | "memory" | "eval" | "tasks" | "admin"

interface Props {
  active: TabKey
  onChange: (tab: TabKey) => void
}

const navItems: { key: TabKey; icon: typeof MessageSquare; label: string }[] = [
  { key: "chat", icon: MessageSquare, label: "对话" },
  { key: "knowledge", icon: BookOpen, label: "知识库" },
  { key: "memory", icon: Brain, label: "记忆" },
  { key: "eval", icon: BarChart3, label: "评测" },
  { key: "tasks", icon: Wrench, label: "任务" },
  { key: "admin", icon: Shield, label: "管理" },
]

export default function Sidebar({ active, onChange }: Props) {
  return (
    <aside className="w-64 border-r border-cyber-border glass flex flex-col py-4 shrink-0">
      <div className="px-4 mb-6">
        <h1 className="text-cyber-cyan font-bold text-xl tracking-widest">NOVA</h1>
        <p className="text-cyber-textDim text-xs">Tech Agent v1.0</p>
      </div>
      <nav className="flex-1 px-3 space-y-1">
        {navItems.map((item) => {
          const isActive = active === item.key
          return (
            <motion.button
              key={item.key}
              whileHover={{ x: 4 }}
              onClick={() => onChange(item.key)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                isActive
                  ? "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30"
                  : "text-cyber-textDim hover:text-cyber-text hover:bg-cyber-surface/50 border border-transparent"
              }`}
            >
              <item.icon size={16} />
              <span>{item.label}</span>
            </motion.button>
          )
        })}
      </nav>
      <div className="px-4 pt-4 border-t border-cyber-border">
        <p className="text-cyber-textDim text-xs">© 2026 NovaTech</p>
      </div>
    </aside>
  )
}
