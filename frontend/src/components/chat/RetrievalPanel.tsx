import { motion } from "framer-motion"
import { Database, Search, GitBranch } from "lucide-react"
import { useChatStore } from "../../stores/chatStore"

const ICON_MAP: Record<string, typeof Database> = {
  dense: Search,
  keyword: Database,
  graph: GitBranch,
}

const COLOR_MAP: Record<string, string> = {
  dense: "text-cyber-cyan",
  keyword: "text-cyber-pink",
  graph: "text-cyber-purple",
}

export default function RetrievalPanel() {
  const results = useChatStore((s) => s.retrievalResults)

  if (results.length === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className="w-80 border-l border-cyber-border bg-cyber-surface/50 overflow-y-auto"
    >
      <div className="p-4 border-b border-cyber-border">
        <h3 className="text-cyber-text font-bold text-sm">检索结果</h3>
        <p className="text-cyber-textDim text-xs mt-1">
          三路召回 + RRF 融合,共 {results.length} 条
        </p>
      </div>
      <div className="p-3 space-y-2">
        {results.map((r, i) => {
          const Icon = ICON_MAP[r.score_type] || Database
          const color = COLOR_MAP[r.score_type] || "text-cyber-cyan"
          return (
            <motion.div
              key={r.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="p-3 rounded-lg border border-cyber-border bg-cyber-bg/50 hover:border-cyber-cyan/30 transition-colors"
            >
              <div className="flex items-center gap-2 mb-1">
                <Icon size={14} className={color} />
                <span className={`text-xs font-bold ${color}`}>{r.score_type}</span>
                <span className="text-cyber-textDim text-xs ml-auto">
                  {(r.score * 100).toFixed(1)}%
                </span>
              </div>
              <p className="text-cyber-textDim text-xs line-clamp-3 leading-relaxed">
                {r.content}
              </p>
              <p className="text-cyber-textDim text-xs mt-1 opacity-60">src: {r.source}</p>
            </motion.div>
          )
        })}
      </div>
    </motion.div>
  )
}
