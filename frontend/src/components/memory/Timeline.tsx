import { motion } from "framer-motion"
import { Clock, Archive, FileText } from "lucide-react"
import type { MemoryStatsOverview } from "../../stores/memoryStore"

interface Props {
  overview: MemoryStatsOverview | null
  loading: boolean
}

export default function Timeline({ overview, loading }: Props) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-14 rounded-lg bg-cyber-surface/30 animate-pulse" />
        ))}
      </div>
    )
  }

  const events = [
    {
      icon: <FileText size={14} className="text-cyber-cyan" />,
      title: "事实提取 (7天)",
      value: overview?.facts_last_7_days ?? "—",
      time: "最近一周",
      color: "border-cyber-cyan/40",
    },
    {
      icon: <Clock size={14} className="text-cyber-purple" />,
      title: "平均会话长度",
      value: overview ? `${overview.avg_session_length} 条消息` : "—",
      time: "所有会话",
      color: "border-cyber-purple/40",
    },
    {
      icon: <Archive size={14} className="text-cyber-pink" />,
      title: "总会话数",
      value: overview?.total_sessions ?? "—",
      time: "累计",
      color: "border-cyber-pink/40",
    },
  ]

  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute left-[11px] top-3 bottom-3 w-px bg-cyber-border" />

      <div className="space-y-3">
        {events.map((evt, i) => (
          <motion.div
            key={evt.title}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.1 }}
            className="relative flex items-start gap-3 pl-0"
          >
            {/* Dot */}
            <div className="relative z-10 mt-3 w-6 h-6 rounded-full bg-cyber-surface border border-cyber-border flex items-center justify-center shrink-0">
              {evt.icon}
            </div>
            {/* Card */}
            <div className={`flex-1 p-2.5 rounded-lg border ${evt.color} bg-cyber-surface/40`}>
              <div className="flex items-center justify-between">
                <span className="text-cyber-text text-xs font-medium">{evt.title}</span>
                <span className="text-cyber-textDim text-[10px]">{evt.time}</span>
              </div>
              <p className="text-cyber-text text-sm font-bold mt-0.5">{evt.value}</p>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  )
}
