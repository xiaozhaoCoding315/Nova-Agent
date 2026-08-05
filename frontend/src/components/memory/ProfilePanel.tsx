import { motion } from "framer-motion"
import { User, Tag, Heart, HelpCircle } from "lucide-react"
import type { MemoryProfile } from "../../stores/memoryStore"

interface Props {
  profile: MemoryProfile | null
  loading: boolean
  error: string | null
}

export default function ProfilePanel({ profile, loading, error }: Props) {
  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-12 rounded-lg bg-cyber-surface/30 animate-pulse" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 rounded-lg border border-cyber-pink/30 bg-cyber-pink/5">
        <p className="text-cyber-pink text-xs">{error}</p>
      </div>
    )
  }

  if (!profile) {
    return (
      <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/30">
        <p className="text-cyber-textDim text-xs text-center">选择会话以查看用户画像</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/40"
      >
        <div className="flex items-center gap-2 mb-2">
          <User size={14} className="text-cyber-cyan" />
          <span className="text-cyber-cyan text-xs font-bold">画像摘要</span>
        </div>
        <p className="text-cyber-text text-xs leading-relaxed">{profile.summary}</p>
      </motion.div>

      {/* Top Topics */}
      {profile.top_topics?.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/40"
        >
          <div className="flex items-center gap-2 mb-2">
            <Tag size={14} className="text-cyber-purple" />
            <span className="text-cyber-purple text-xs font-bold">热门话题</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {profile.top_topics.map((topic) => (
              <span
                key={topic}
                className="px-2 py-0.5 text-xs rounded-full border border-cyber-purple/30 text-cyber-purple bg-cyber-purple/5"
              >
                {topic}
              </span>
            ))}
          </div>
        </motion.div>
      )}

      {/* Preferences */}
      {profile.preferences && Object.keys(profile.preferences).length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/40"
        >
          <div className="flex items-center gap-2 mb-2">
            <Heart size={14} className="text-cyber-pink" />
            <span className="text-cyber-pink text-xs font-bold">技术偏好</span>
          </div>
          <div className="space-y-1.5">
            {Object.entries(profile.preferences).map(([key, val]) => (
              <div key={key} className="flex items-center justify-between">
                <span className="text-cyber-textDim text-xs">{key}</span>
                <span className="text-cyber-text text-xs">{val}</span>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* Question Patterns */}
      {profile.question_patterns?.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/40"
        >
          <div className="flex items-center gap-2 mb-2">
            <HelpCircle size={14} className="text-cyber-cyan" />
            <span className="text-cyber-cyan text-xs font-bold">提问模式</span>
          </div>
          <ul className="space-y-1">
            {profile.question_patterns.map((p, i) => (
              <li key={i} className="text-cyber-textDim text-xs flex items-start gap-1.5">
                <span className="text-cyber-cyan mt-0.5">›</span>
                {p}
              </li>
            ))}
          </ul>
        </motion.div>
      )}
    </div>
  )
}
