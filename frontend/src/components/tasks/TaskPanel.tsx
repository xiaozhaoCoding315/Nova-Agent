import { useEffect, useRef, useCallback } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Play, RotateCcw, CheckCircle, XCircle, Loader, GitBranch, FileText } from "lucide-react"
import { useTaskStore } from "../../stores/taskStore"
import { type DAGNode, executeTaskStream } from "../../services/api"
import DAGCanvas from "./DAGCanvas"
import TaskCreator from "./TaskCreator"

export default function TaskPanel() {
  const {
    nodes,
    taskDescription,
    running,
    result,
    nodeResults,
    setNodes,
    setTaskDescription,
    setRunning,
    setResult,
    updateNodeStatus,
    addNodeResult,
  } = useTaskStore()

  const abortRef = useRef<(() => void) | null>(null)
  const safetyRef = useRef<number | null>(null)

  const clearSafety = useCallback(() => {
    if (safetyRef.current !== null) {
      window.clearTimeout(safetyRef.current)
      safetyRef.current = null
    }
  }, [])

  const handleExecute = useCallback(() => {
    if (!taskDescription.trim() || running) return
    setNodes((prev: DAGNode[]) => prev.map((n: DAGNode) => ({ ...n, status: "pending" as const })))
    setResult(null)

    setRunning(true)
    abortRef.current = executeTaskStream(taskDescription, (event: any) => {
      switch (event?.type) {
        case "node_started":
          updateNodeStatus(event.node_id, "running")
          break
        case "node_completed":
          updateNodeStatus(event.node_id, "completed")
          if (event.result) {
            const node = nodes.find((n: DAGNode) => n.id === event.node_id)
            addNodeResult({
              node_id: event.node_id,
              node_name: event.node_name || node?.name || event.node_id,
              result: typeof event.result === "string" ? event.result : JSON.stringify(event.result),
            })
          }
          break
        case "node_failed":
          updateNodeStatus(event.node_id, "failed")
          break
        case "dag_completed": {
          setRunning(false)
          clearSafety()
          const doneCount = event.results ? Object.keys(event.results).length : 0
          setResult(`全部 ${event.total_nodes ?? nodes.length} 个节点中 ${doneCount} 个执行完成`)
          break
        }
        case "done":
          setRunning(false)
          clearSafety()
          break
      }
    })

    safetyRef.current = window.setTimeout(() => {
      setRunning(false)
      abortRef.current?.()
      safetyRef.current = null
    }, 120000)
  }, [taskDescription, running, nodes, setNodes, setResult, setRunning, updateNodeStatus, addNodeResult, clearSafety])

  const handleReset = useCallback(() => {
    abortRef.current?.()
    setRunning(false)
    clearSafety()
    setNodes((prev: DAGNode[]) => prev.map((n: DAGNode) => ({ ...n, status: "pending" as const })))
  }, [setRunning, setNodes, clearSafety])

  const handleClear = useCallback(() => {
    abortRef.current?.()
    setRunning(false)
    clearSafety()
    setNodes([])
    setTaskDescription("")
    setResult(null)
  }, [setRunning, setNodes, setTaskDescription, setResult, clearSafety])

  useEffect(() => {
    return () => {
      abortRef.current?.()
      if (safetyRef.current !== null) window.clearTimeout(safetyRef.current)
    }
  }, [])

  const completedCount = nodes.filter((n: DAGNode) => n.status === "completed").length
  const failedCount = nodes.filter((n: DAGNode) => n.status === "failed").length

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="shrink-0 p-4 flex items-center justify-between border-b border-cyber-border">
        <h2 className="text-cyber-text font-bold text-lg flex items-center gap-2">
          <GitBranch size={20} className="text-cyber-cyan" />
          任务编排
        </h2>
        {nodes.length > 0 && (
          <div className="flex items-center gap-3 text-xs">
            <span className="text-green-400">{completedCount} 完成</span>
            {failedCount > 0 && <span className="text-cyber-pink">{failedCount} 失败</span>}
            <span className="text-cyber-textDim">{nodes.length} 节点</span>
          </div>
        )}
      </div>

      <TaskCreator />

      {nodes.length > 0 && (
        <div className="shrink-0 p-4 border-b border-cyber-border">
          <div className="flex items-center gap-2 mb-2">
            <div className={`w-2 h-2 rounded-full ${running ? "bg-cyber-cyan animate-pulse" : "bg-cyber-textDim"}`} />
            <span className="text-cyber-text text-sm font-bold">依赖关系图</span>
          </div>
          <DAGCanvas nodes={nodes} height={200} />
          <div className="flex items-center gap-2 mt-3">
            <motion.button
              whileTap={{ scale: 0.96 }}
              onClick={handleExecute}
              disabled={running}
              className="px-3 py-2 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan text-cyber-cyan text-xs flex items-center gap-1.5 disabled:opacity-40"
            >
              {running ? <Loader size={12} className="animate-spin" /> : <Play size={12} />}
              {running ? "执行中…" : "开始执行"}
            </motion.button>
            <button onClick={handleReset} disabled={running} className="px-3 py-2 rounded-lg border border-cyber-border text-cyber-textDim text-xs flex items-center gap-1.5 disabled:opacity-40">
              <RotateCcw size={12} /> 重置
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {/* Node status list */}
        <AnimatePresence>
          {nodes.map((node: DAGNode) => (
            <motion.div key={node.id} layout initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="flex items-center gap-3 p-3 rounded-lg border border-cyber-border bg-cyber-surface/40">
              <StatusIcon status={node.status || "pending"} />
              <div className="flex-1 min-w-0">
                <p className="text-cyber-text text-sm truncate">{node.name}</p>
                <p className="text-cyber-textDim text-[11px] mt-0.5">
                  {node.task_type}
                  {node.depends_on && node.depends_on.length > 0 && (
                    <span className="ml-2">依赖 {node.depends_on.length} 节点</span>
                  )}
                </p>
              </div>
              <span className={`text-[11px] px-2 py-0.5 rounded border ${badgeClass(node.status || "pending")}`}>
                {statusLabel(node.status || "pending")}
              </span>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Node Results — show when any node has results */}
        {nodeResults.length > 0 && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 space-y-2">
            <p className="text-cyber-cyan text-xs font-bold flex items-center gap-1.5">
              <FileText size={12} /> 执行结果
            </p>
            {nodeResults.map((nr) => (
              <div key={nr.node_id} className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/60">
                <p className="text-cyber-cyan text-xs font-bold mb-1">{nr.node_name}</p>
                <div className="text-cyber-text text-xs leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {nr.result}
                </div>
              </div>
            ))}
          </motion.div>
        )}

        {/* Final result */}
        {result && !running && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
            className="p-3 rounded-lg border border-green-400/40 bg-green-400/5">
            <p className="text-green-400 text-xs font-bold mb-1">✓ 全部完成</p>
            <p className="text-cyber-text text-xs leading-relaxed whitespace-pre-wrap">{result}</p>
          </motion.div>
        )}

        {nodes.length === 0 && (
          <div className="p-6 rounded-lg border border-dashed border-cyber-border text-center">
            <p className="text-cyber-textDim text-sm">在上方输入任务开始编排</p>
          </div>
        )}

        {nodes.length > 0 && !running && (
          <div className="pt-2 text-center">
            <button onClick={handleClear} className="text-cyber-textDim text-xs hover:text-cyber-pink">清除当前任务</button>
          </div>
        )}
      </div>
    </div>
  )
}

function StatusIcon({ status }: { status: DAGNode["status"] | "pending" }) {
  switch (status) {
    case "running": return <Loader size={14} className="text-cyber-cyan animate-spin shrink-0" />
    case "completed": return <CheckCircle size={14} className="text-green-400 shrink-0" />
    case "failed": return <XCircle size={14} className="text-cyber-pink shrink-0" />
    default: return <span className="block w-2 h-2 rounded-full bg-cyber-textDim/50 shrink-0" />
  }
}

function badgeClass(status: string): string {
  switch (status) {
    case "running": return "border-cyber-cyan/40 text-cyber-cyan bg-cyber-cyan/5"
    case "completed": return "border-green-400/40 text-green-400 bg-green-400/5"
    case "failed": return "border-cyber-pink/40 text-cyber-pink bg-cyber-pink/5"
    default: return "border-cyber-border text-cyber-textDim bg-transparent"
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case "running": return "运行中"
    case "completed": return "已完成"
    case "failed": return "失败"
    default: return "待执行"
  }
}
