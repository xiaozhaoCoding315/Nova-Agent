import { useEffect, useState } from "react"
import { motion } from "framer-motion"
import { Network, Brain, Clock, RefreshCw, Search, Archive, ChevronRight } from "lucide-react"
import { getGraphStats, searchGraph, getMemoryProfile, getMemoryStats, archiveSession } from "../../services/api"
import { useChatStore } from "../../stores/chatStore"

type SubTab = "graph" | "profile" | "timeline"

interface GraphData {
  entity_count?: number
  relationship_count?: number
  top_entities?: { name: string; type: string; mentions?: number; count?: number }[]
  type_distribution?: { type: string; cnt: number }[]
}

interface ProfileFact {
  fact: string
  importance: number
}

interface ProfileData {
  profile?: {
    domains?: ProfileFact[]
    preferences?: ProfileFact[]
    learning?: ProfileFact[]
    style?: ProfileFact[]
    general?: ProfileFact[]
    total_facts?: number
  }
  summary?: string
}

function TimelineItem({ icon, title, value, color, time }: {
  icon: React.ReactNode; title: string; value: string; color: string; time: string
}) {
  return (
    <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}
      className="relative flex items-start gap-3">
      <div className="relative z-10 mt-2 w-6 h-6 rounded-full bg-cyber-surface border border-cyber-border flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div className={`flex-1 p-2.5 rounded-lg border ${color} bg-cyber-surface/40`}>
        <div className="flex items-center justify-between">
          <span className="text-cyber-text text-xs font-medium">{title}</span>
          <span className="text-cyber-textDim text-[10px]">{time}</span>
        </div>
        <p className="text-cyber-text text-sm font-bold mt-0.5">{value}</p>
      </div>
    </motion.div>
  )
}

export default function MemoryPanel() {
  const [subTab, setSubTab] = useState<SubTab>("graph")
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<any>(null)
  const [profileData, setProfileData] = useState<ProfileData | null>(null)
  const [statsData, setStatsData] = useState<any>(null)
  const [archiveMsg, setArchiveMsg] = useState("")
  const sessionId = useChatStore((s) => s.sessionId)

  const fetchGraph = async () => {
    setGraphLoading(true)
    try {
      const data = await getGraphStats()
      setGraphData(data)
    } catch {
      setGraphData(null)
    } finally {
      setGraphLoading(false)
    }
  }

  const fetchProfile = async () => {
    if (!sessionId) return
    try {
      const data = await getMemoryProfile(sessionId)
      setProfileData(data)
    } catch {
      setProfileData(null)
    }
  }

  const fetchStats = async () => {
    try {
      const data = await getMemoryStats()
      setStatsData(data)
    } catch {
      setStatsData(null)
    }
  }

  useEffect(() => {
    fetchGraph()
    fetchStats()
  }, [])

  useEffect(() => {
    if (subTab === "profile") fetchProfile()
  }, [subTab, sessionId])

  const handleSearch = async () => {
    if (!searchQuery.trim()) return
    try {
      const data = await searchGraph(searchQuery.trim(), 2)
      setSearchResults(data)
    } catch {
      setSearchResults(null)
    }
  }

  const handleArchive = async () => {
    if (!sessionId) return
    try {
      const result = await archiveSession(sessionId)
      setArchiveMsg(`已归档 ${result.archived} 条记忆`)
      setTimeout(() => setArchiveMsg(""), 3000)
    } catch {
      setArchiveMsg("归档失败")
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3 border-b border-cyber-border">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-cyber-text font-bold text-base flex items-center gap-2">
            <Brain size={16} className="text-cyber-cyan" />
            记忆管理
          </h2>
          <button onClick={fetchGraph} className="p-1.5 rounded-md text-cyber-textDim hover:text-cyber-cyan">
            <RefreshCw size={14} className={graphLoading ? "animate-spin" : ""} />
          </button>
        </div>
        <div className="flex gap-1">
          {(["graph", "profile", "timeline"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setSubTab(t)}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-colors ${
                subTab === t
                  ? "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30"
                  : "text-cyber-textDim hover:text-cyber-text border border-transparent"
              }`}
            >
              {t === "graph" && <Network size={14} />}
              {t === "profile" && <Brain size={14} />}
              {t === "timeline" && <Clock size={14} />}
              {{ graph: "知识图谱", profile: "用户画像", timeline: "记忆轨迹" }[t]}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {archiveMsg && (
          <div className="p-2 rounded-lg border border-cyber-cyan/30 bg-cyber-cyan/5 text-cyber-cyan text-xs">
            {archiveMsg}
          </div>
        )}

        {/* =================== Graph Tab =================== */}
        {subTab === "graph" && (
          <>
            {/* Stats */}
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/50">
                <p className="text-cyber-textDim text-xs">实体数</p>
                <p className="text-cyber-text text-2xl font-bold">
                  {graphLoading ? "..." : graphData?.entity_count ?? 0}
                </p>
              </div>
              <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/50">
                <p className="text-cyber-textDim text-xs">关系数</p>
                <p className="text-cyber-text text-2xl font-bold">
                  {graphLoading ? "..." : graphData?.relationship_count ?? 0}
                </p>
              </div>
            </div>

            {/* Search */}
            <div className="flex gap-2">
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="搜索实体..."
                className="flex-1 px-3 py-2 text-xs rounded-lg bg-cyber-surface border border-cyber-border text-cyber-text placeholder:text-cyber-textDim focus:outline-none focus:border-cyber-cyan/50"
              />
              <button
                onClick={handleSearch}
                className="px-3 py-2 rounded-lg border border-cyber-cyan/40 text-cyber-cyan text-xs hover:bg-cyber-cyan/10 transition-colors"
              >
                <Search size={14} />
              </button>
            </div>

            {/* Search Results */}
            {searchResults && (
              <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/40">
                <p className="text-cyber-cyan text-xs font-bold mb-2 flex items-center gap-1.5">
                  <Search size={12} />
                  搜索结果: {searchResults.entity}
                </p>
                {searchResults.neighbors && searchResults.neighbors.length > 0 ? (
                  <ul className="space-y-1">
                    {searchResults.neighbors.map((n: any, i: number) => (
                      <li key={i} className="flex items-center gap-2 text-xs">
                        <ChevronRight size={10} className="text-cyber-textDim" />
                        <span className="text-cyber-text truncate flex-1">{n.name ?? n.entity}</span>
                        <span className="text-cyber-textDim text-[10px] px-1.5 py-0.5 rounded bg-cyber-surface">
                          {n.type ?? n.relation}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-cyber-textDim text-xs">无关联实体</p>
                )}
              </div>
            )}

            {/* Top Entities */}
            <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/30">
              <p className="text-cyber-cyan text-xs font-bold mb-2">Top 实体</p>
              {graphLoading ? (
                <div className="space-y-2">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="h-4 rounded bg-cyber-surface animate-pulse" />
                  ))}
                </div>
              ) : graphData?.top_entities && graphData.top_entities.length > 0 ? (
                <ul className="space-y-1">
                  {graphData.top_entities.slice(0, 10).map((e, i) => (
                    <li
                      key={e.name}
                      className="flex items-center gap-2 text-xs cursor-pointer hover:bg-cyber-surface/60 rounded px-1 py-0.5"
                      onClick={() => {
                        setSearchQuery(e.name)
                        handleSearch()
                      }}
                    >
                      <span className="text-cyber-textDim w-4">{i + 1}</span>
                      <span className="text-cyber-text truncate flex-1">{e.name}</span>
                      <span className="text-cyber-textDim text-[10px] px-1.5 py-0.5 rounded bg-cyber-surface">
                        {e.type}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-cyber-textDim text-sm">暂无数据，请先上传文档</p>
              )}
            </div>

            {/* Type Distribution */}
            <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/30">
              <p className="text-cyber-purple text-xs font-bold mb-2">实体类型分布</p>
              {graphData?.type_distribution && graphData.type_distribution.length > 0 ? (
                <div className="space-y-1.5">
                  {graphData.type_distribution.map((t) => (
                    <div key={t.type} className="flex items-center gap-2 text-xs">
                      <span className="text-cyber-textDim w-20 shrink-0">{t.type}</span>
                      <div className="flex-1 h-2 bg-cyber-border rounded-full overflow-hidden">
                        <div
                          className="h-full bg-cyber-purple rounded-full"
                          style={{
                            width: `${Math.min(
                              100,
                              (t.cnt / Math.max(1, graphData.entity_count || 1)) * 100
                            )}%`,
                          }}
                        />
                      </div>
                      <span className="text-cyber-text w-8 text-right">{t.cnt}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-cyber-textDim text-sm">暂无数据</p>
              )}
            </div>
          </>
        )}

        {/* =================== Profile Tab =================== */}
        {subTab === "profile" && (
          <>
            {!sessionId && (
              <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/30">
                <p className="text-cyber-textDim text-sm text-center">暂无会话，请先开始对话</p>
              </div>
            )}

            {sessionId && !profileData && (
              <div className="space-y-3">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="h-12 rounded-lg bg-cyber-surface/30 animate-pulse" />
                ))}
              </div>
            )}

            {profileData && (
              <div className="space-y-4">
                {/* Summary */}
                {profileData.summary && (
                  <motion.div
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/40"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <Brain size={14} className="text-cyber-cyan" />
                      <span className="text-cyber-cyan text-xs font-bold">画像摘要</span>
                    </div>
                    <p className="text-cyber-text text-xs leading-relaxed">{profileData.summary}</p>
                  </motion.div>
                )}

                {/* Total Facts */}
                {profileData.profile?.total_facts != null && (
                  <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/50">
                    <p className="text-cyber-textDim text-xs">已沉淀事实</p>
                    <p className="text-cyber-text text-2xl font-bold">{profileData.profile.total_facts}</p>
                  </div>
                )}

                {/* Fact Sections */}
                {profileData.profile &&
                  (
                    [
                      { key: "domains", label: "擅长领域", color: "text-cyber-cyan", border: "border-cyber-cyan/40" },
                      { key: "preferences", label: "技术偏好", color: "text-cyber-pink", border: "border-cyber-pink/40" },
                      { key: "learning", label: "学习记录", color: "text-cyber-purple", border: "border-cyber-purple/40" },
                      { key: "style", label: "交互风格", color: "text-cyber-cyan", border: "border-cyber-cyan/40" },
                      { key: "general", label: "通用事实", color: "text-cyber-textDim", border: "border-cyber-border" },
                    ] as const
                  ).map(({ key, label, color, border }) => {
                    const facts = profileData.profile![key]
                    if (!facts || facts.length === 0) return null
                    return (
                      <motion.div
                        key={key}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        className={`p-3 rounded-lg border ${border} bg-cyber-surface/40`}
                      >
                        <p className={`${color} text-xs font-bold mb-2`}>{label}</p>
                        <ul className="space-y-1.5">
                          {facts.slice(0, 8).map((f, i) => (
                            <li key={i} className="flex items-start gap-2 text-xs">
                              <ChevronRight size={10} className="text-cyber-textDim mt-0.5 shrink-0" />
                              <span className="text-cyber-text">{f.fact}</span>
                            </li>
                          ))}
                        </ul>
                      </motion.div>
                    )
                  })}
              </div>
            )}
          </>
        )}

        {/* =================== Timeline Tab =================== */}
        {subTab === "timeline" && (
          <div className="space-y-4">
            {/* Timeline line */}
            <div className="relative">
              <div className="absolute left-[11px] top-3 bottom-3 w-px bg-cyber-border" />
              <div className="space-y-3">
                <TimelineItem
                  icon={<Network size={12} className="text-cyber-cyan" />}
                  title="知识图谱构建"
                  value={`${graphData?.entity_count ?? 0} 实体 · ${graphData?.relationship_count ?? 0} 关系`}
                  color="border-cyber-cyan/40"
                  time="实时"
                />
                <TimelineItem
                  icon={<Brain size={12} className="text-cyber-purple" />}
                  title="长期记忆沉淀"
                  value={`${statsData?.total_facts ?? 0} 条事实`}
                  color="border-cyber-purple/40"
                  time="累计"
                />
                <TimelineItem
                  icon={<Archive size={12} className="text-cyber-pink" />}
                  title="会话自动归档"
                  value="对话 ≥ 10 轮时触发"
                  color="border-cyber-pink/40"
                  time="自动"
                />
              </div>
            </div>

            {/* Stats */}
            {statsData?.by_category && statsData.by_category.length > 0 && (
              <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/30">
                <p className="text-cyber-cyan text-xs font-bold mb-2">事实分类</p>
                <div className="space-y-1.5">
                  {statsData.by_category.map((c: { category: string; count: number; avg_importance: number }) => (
                    <div key={c.category} className="flex items-center justify-between text-xs">
                      <span className="text-cyber-textDim">{c.category}</span>
                      <span className="text-cyber-text">{c.count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Archive Action */}
            <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/30">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-cyber-text text-xs font-bold">手动归档</p>
                  <p className="text-cyber-textDim text-[10px] mt-0.5">
                    将当前会话的事实提取并沉淀到长期记忆
                  </p>
                </div>
                <button
                  onClick={handleArchive}
                  disabled={!sessionId}
                  className="px-3 py-1.5 rounded-lg border border-cyber-pink/40 text-cyber-pink text-xs hover:bg-cyber-pink/10 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  <Archive size={12} />
                  归档
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
