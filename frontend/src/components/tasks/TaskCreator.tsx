import { useState, useEffect } from "react"
import { motion } from "framer-motion"
import { Plus, Loader } from "lucide-react"
import { useTaskStore } from "../../stores/taskStore"

const SUGGESTIONS = [
  "对比 FastAPI 和 Django 的优缺点",
  "帮我调研 React 18 的新特性",
  "写一份 Docker 部署最佳实践",
  "设计用户认证最佳方案",
]

export default function TaskCreator() {
  const [task, setTask] = useState("")
  const { createTask, decomposing, taskDescription } = useTaskStore()

  // Sync local state with store
  useEffect(() => {
    if (taskDescription && task === "") {
      // Don't override user typing
    }
  }, [taskDescription])

  const handleCreate = () => {
    if (!task.trim() || decomposing) return
    createTask(task)
  }

  return (
    <div className="p-4 space-y-3 border-b border-cyber-border">
      <div className="flex gap-2">
        <input
          value={task}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          placeholder="输入复杂任务，如：对比 FastAPI 和 Django…"
          className="flex-1 px-3 py-2.5 text-sm rounded-lg bg-cyber-surface border border-cyber-border text-cyber-text placeholder:text-cyber-textDim focus:outline-none focus:border-cyber-cyan/50"
        />
        <motion.button
          whileTap={{ scale: 0.96 }}
          onClick={handleCreate}
          disabled={decomposing || !task.trim()}
          className="px-4 py-2.5 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan text-cyber-cyan text-sm flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-cyber-cyan/20"
        >
          {decomposing ? <Loader size={14} className="animate-spin" /> : <Plus size={14} />}
          创建
        </motion.button>
      </div>
      <div className="flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => setTask(s)}
            className="px-2.5 py-1 text-xs rounded-full border border-cyber-border text-cyber-textDim hover:text-cyber-text hover:border-cyber-cyan/30"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
