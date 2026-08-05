import { motion } from "framer-motion"
import { Database, GitBranch, Layers, Activity } from "lucide-react"
import type { GraphStats, MemoryStatsOverview } from "../../stores/memoryStore"

interface Props {
  graphStats: GraphStats | null
  overview: MemoryStatsOverview | null
  loading: boolean
}

interface CardProps {
  icon: React.ReactNode
  label: string
  value: string | number
  color: string
  delay: number
}

function StatCard({ icon, label, value, color, delay }: CardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35 }}
      className="flex items-center gap-3 p-3 rounded-lg border border-cyber-border bg-cyber-surface/50"
    >
      <div className={`p-2 rounded-md ${color}`}>{icon}</div>
      <div className="flex-1 min-w-0">
        <p className="text-cyber-textDim text-xs">{label}</p>
        <p className="text-cyber-text text-lg font-bold leading-tight">{value}</p>
      </div>
    </motion.div>
  )
}

export default function StatsCards({ graphStats, overview, loading }: Props) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 gap-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-16 rounded-lg border border-cyber-border bg-cyber-surface/30 animate-pulse" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 gap-3">
      <StatCard
        icon={<Database size={16} className="text-cyber-cyan" />}
        label="实体总数"
        value={graphStats?.entity_count ?? "—"}
        color="bg-cyber-cyan/10"
        delay={0}
      />
      <StatCard
        icon={<GitBranch size={16} className="text-cyber-purple" />}
        label="关系总数"
        value={graphStats?.relationship_count ?? "—"}
        color="bg-cyber-purple/10"
        delay={0.05}
      />
      <StatCard
        icon={<Layers size={16} className="text-cyber-pink" />}
        label="活跃会话"
        value={overview?.total_sessions ?? "—"}
        color="bg-cyber-pink/10"
        delay={0.1}
      />
      <StatCard
        icon={<Activity size={16} className="text-cyber-cyan" />}
        label="提取事实"
        value={overview?.total_facts ?? "—"}
        color="bg-cyber-cyan/10"
        delay={0.15}
      />
    </div>
  )
}
