import { useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Play, Plus, Trash2, Database, Zap, BarChart3 } from "lucide-react"
import { useEvalStore } from "../../stores/evalStore"
import MetricBar from "./MetricBar"

export default function EvaluationPanel() {
  const {
    results, running, datasetQueries, datasetStats,
    runSingle, runSuite, loadDataset, seedData, loadStats, addQuery, removeQuery,
  } = useEvalStore()

  const [activeTab, setActiveTab] = useState<"run" | "dataset" | "results">("run")
  const [queryInput, setQueryInput] = useState("")
  const [newQuery, setNewQuery] = useState("")
  const [newCategory, setNewCategory] = useState("general")

  useEffect(() => {
    loadDataset()
    loadStats()
  }, [])

  const handleRunSingle = () => {
    if (!queryInput.trim()) return
    runSingle(queryInput)
  }

  const handleRunSuite = () => {
    const queries = datasetQueries.map(q => ({ query: q.query, relevant_ids: q.relevant_ids ?? null }))
    if (queries.length > 0) runSuite(queries)
  }

  return (
    <div className="flex-1 flex flex-col p-6 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-cyber-text font-bold text-lg flex items-center gap-2">
          <BarChart3 size={20} className="text-cyber-cyan" />
          评测平台
        </h2>
        <div className="flex gap-2">
          {(["run", "dataset", "results"] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1.5 text-xs rounded-lg transition-colors ${
                activeTab === tab
                  ? "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30"
                  : "text-cyber-textDim border border-cyber-border hover:text-cyber-text"
              }`}
            >
              {{ run: "运行评测", dataset: "数据集", results: "结果" }[tab]}
            </button>
          ))}
        </div>
      </div>

      {/* Run Tab */}
      {activeTab === "run" && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="输入技术问题..."
              className="flex-1 px-4 py-2 bg-cyber-surface border border-cyber-border rounded-lg text-cyber-text text-sm outline-none focus:border-cyber-cyan"
              onKeyDown={(e) => e.key === "Enter" && handleRunSingle()}
            />
            <button
              onClick={handleRunSingle}
              disabled={running || !queryInput.trim()}
              className="px-4 py-2 bg-cyber-cyan/10 border border-cyber-cyan text-cyber-cyan rounded-lg text-sm flex items-center gap-2 disabled:opacity-50"
            >
              <Play size={14} /> 运行
            </button>
          </div>
          <button
            onClick={handleRunSuite}
            disabled={running || datasetQueries.length === 0}
            className="px-4 py-2 bg-cyber-purple/10 border border-cyber-purple text-cyber-purple rounded-lg text-sm flex items-center gap-2 disabled:opacity-50"
          >
            <Zap size={14} /> 批量运行 ({datasetQueries.length} 条)
          </button>
          {datasetStats && (
            <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/30 text-xs text-cyber-textDim">
              数据集: {datasetStats.golden_queries} 条查询, {datasetStats.eval_runs ?? 0} 次评测
            </div>
          )}
        </div>
      )}

      {/* Dataset Tab */}
      {activeTab === "dataset" && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input
              value={newQuery}
              onChange={(e) => setNewQuery(e.target.value)}
              placeholder="添加 Golden Query..."
              className="flex-1 px-3 py-2 bg-cyber-surface border border-cyber-border rounded-lg text-cyber-text text-sm outline-none focus:border-cyber-cyan"
            />
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              className="px-3 py-2 bg-cyber-surface border border-cyber-border rounded-lg text-cyber-text text-sm"
            >
              <option value="general">通用</option>
              <option value="framework">框架</option>
              <option value="database">数据库</option>
              <option value="algorithm">算法</option>
              <option value="error">报错</option>
              <option value="concept">概念</option>
              <option value="devops">DevOps</option>
            </select>
            <button
              onClick={() => { addQuery(newQuery, newCategory); setNewQuery("") }}
              disabled={!newQuery.trim()}
              className="px-3 py-2 bg-cyber-cyan/10 border border-cyber-cyan text-cyber-cyan rounded-lg text-sm disabled:opacity-50"
            >
              <Plus size={14} />
            </button>
            <button
              onClick={seedData}
              className="px-3 py-2 border border-cyber-border text-cyber-textDim rounded-lg text-sm hover:text-cyber-text"
            >
              <Database size={14} />
            </button>
          </div>
          <div className="space-y-2">
            {datasetQueries.map(q => (
              <div key={q.id} className="flex items-center gap-3 p-3 rounded-lg border border-cyber-border bg-cyber-surface/50 group">
                <div className="flex-1">
                  <p className="text-cyber-text text-sm">{q.query}</p>
                  <p className="text-cyber-textDim text-xs">{q.category} {q.notes && `— ${q.notes}`}</p>
                </div>
                <button onClick={() => removeQuery(q.id)} className="opacity-0 group-hover:opacity-100 text-cyber-pink">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Results Tab */}
      {activeTab === "results" && (
        <div className="space-y-4">
          {results.length === 0 ? (
            <p className="text-cyber-textDim text-sm text-center py-8">暂无评测结果</p>
          ) : (
            <AnimatePresence>
              {results.map((r, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50"
                >
                  <p className="text-cyber-text text-sm font-bold mb-2">{r.query}</p>
                  <p className="text-cyber-textDim text-xs mb-3">
                    检索 {r.retrieved_count} 条, 耗时 {r.retrieval_time_ms}ms
                  </p>
                  {r.retrieval_metrics && (
                    <div className="space-y-1.5 mb-3">
                      {Object.entries(r.retrieval_metrics).map(([k, v]) => (
                        <MetricBar key={k} label={k} value={v as number} />
                      ))}
                    </div>
                  )}
                  {r.ragas_scores && (
                    <div className="space-y-1.5">
                      <p className="text-cyber-textDim text-xs font-bold">RAGAS 评分</p>
                      {Object.entries(r.ragas_scores).map(([k, v]) => (
                        <MetricBar
                          key={k}
                          label={k}
                          value={v as number}
                          color={k === "faithfulness" ? "bg-cyber-cyan" : k === "answer_relevancy" ? "bg-cyber-pink" : "bg-cyber-purple"}
                        />
                      ))}
                    </div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </div>
      )}
    </div>
  )
}
