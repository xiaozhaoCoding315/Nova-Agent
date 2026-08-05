import { motion } from "framer-motion"
import type { GraphStats } from "../../stores/memoryStore"

interface Props {
  graphStats: GraphStats | null
}

const BAR_COLORS = ["#00f0f0", "#8b5cf6", "#ff006e", "#fbbf24", "#34d399", "#f472b6", "#60a5fa", "#9ca3af"]

export default function TypeDistribution({ graphStats }: Props) {
  if (!graphStats?.type_distribution) {
    return (
      <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/30">
        <p className="text-cyber-textDim text-xs text-center">暂无类型数据</p>
      </div>
    )
  }

  const entries = Object.entries(graphStats.type_distribution).sort((a, b) => b[1] - a[1])
  const max = Math.max(...entries.map(([, v]) => v))

  return (
    <div className="space-y-2">
      {entries.map(([type, count], i) => (
        <motion.div
          key={type}
          initial={{ opacity: 0, x: -10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * 0.05 }}
          className="flex items-center gap-2"
        >
          <span className="text-cyber-textDim text-xs w-20 truncate">{type}</span>
          <div className="flex-1 h-2 rounded-full bg-cyber-surface overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${(count / max) * 100}%` }}
              transition={{ delay: i * 0.05 + 0.2, duration: 0.5 }}
              className="h-full rounded-full"
              style={{ backgroundColor: BAR_COLORS[i % BAR_COLORS.length] }}
            />
          </div>
          <span className="text-cyber-text text-xs w-8 text-right">{count}</span>
        </motion.div>
      ))}
    </div>
  )
}
