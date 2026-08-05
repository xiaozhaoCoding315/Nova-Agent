import { motion } from "framer-motion"

interface Props {
  label: string
  value: number  // 0-1
  color?: string
}

export default function MetricBar({ label, value, color = "bg-cyber-cyan" }: Props) {
  const pct = Math.round(value * 100)
  return (
    <div className="flex items-center gap-3">
      <span className="text-cyber-textDim text-xs w-24 shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-cyber-border rounded-full overflow-hidden">
        <motion.div
          className={`h-full ${color} rounded-full`}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5 }}
        />
      </div>
      <span className="text-cyber-text text-xs w-12 text-right">{pct}%</span>
    </div>
  )
}
