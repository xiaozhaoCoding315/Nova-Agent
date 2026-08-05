import { useEffect, useRef, useState, useCallback } from "react"
import { motion } from "framer-motion"
import type { DAGNode } from "../../services/api"

interface Props {
  nodes: DAGNode[]
  height?: number
}

const TYPE_COLORS: Record<string, string> = {
  search: "#00f0f0",
  research: "#8b5cf6",
  code: "#ff006e",
  write: "#fbbf24",
  review: "#34d399",
  execute: "#f472b6",
}

const TYPE_LABELS: Record<string, string> = {
  search: "搜索",
  research: "调研",
  code: "编码",
  write: "撰写",
  review: "审核",
  execute: "执行",
}

function typeColor(type: string): string {
  return TYPE_COLORS[type] || "#9ca3af"
}

function statusColor(status: string): string {
  switch (status) {
    case "completed":
      return "#34d399"
    case "failed":
      return "#ff006e"
    case "running":
      return "#00f0f0"
    default:
      return "transparent"
  }
}

export default function DAGCanvas({ nodes, height = 300 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [dims, setDims] = useState({ w: 600, h: height })
  const nodePositions = useRef<Map<string, { x: number; y: number }>>(new Map())

  // Measure container so canvas fills width
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const parent = canvas.parentElement
    if (!parent) return
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = Math.max(320, entry.contentRect.width)
        setDims((prev) => (prev.w === w ? prev : { w, h: height }))
      }
    })
    ro.observe(parent)
    return () => ro.disconnect()
  }, [height])

  // Calculate node positions in layers based on dependencies
  const layoutNodes = useCallback(() => {
    const positions = new Map<string, { x: number; y: number }>()
    const layers: string[][] = []
    const placed = new Set<string>()

    // Topological layering using depends_on
    let remaining = [...nodes]
    let safety = nodes.length + 1 // prevent infinite loop on cycles
    while (remaining.length > 0 && safety-- > 0) {
      const layer = remaining.filter(
        (n) => !n.depends_on || n.depends_on.every((d) => placed.has(d))
      )
      if (layer.length === 0) layer.push(remaining[0]) // cycle fallback

      layers.push(layer.map((n) => n.id))
      layer.forEach((n) => placed.add(n.id))
      remaining = remaining.filter((n) => !placed.has(n.id))
    }

    const layerCount = Math.max(layers.length, 1)

    layers.forEach((layer, li) => {
      const layerX = (dims.w / (layerCount + 1)) * (li + 1)
      layer.forEach((nid, ni) => {
        const layerH = dims.h / (layer.length + 1)
        const y = layerH * (ni + 1)
        positions.set(nid, { x: layerX, y })
      })
    })

    nodePositions.current = positions
  }, [nodes, dims])

  useEffect(() => {
    layoutNodes()
  }, [layoutNodes])

  // Draw graph
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = dims.w * dpr
    canvas.height = dims.h * dpr
    canvas.style.width = `${dims.w}px`
    canvas.style.height = `${dims.h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, dims.w, dims.h)

    const positions = nodePositions.current
    if (positions.size === 0) return

    // --- Draw edges ---
    for (const node of nodes) {
      if (!node.depends_on || node.depends_on.length === 0) continue
      const target = positions.get(node.id)
      if (!target) continue

      for (const depId of node.depends_on) {
        const source = positions.get(depId)
        if (!source) continue

        // Bezier curve
        ctx.beginPath()
        ctx.moveTo(source.x, source.y)
        const midX = (source.x + target.x) / 2
        ctx.bezierCurveTo(midX, source.y, midX, target.y, target.x, target.y)
        ctx.strokeStyle = "rgba(139, 92, 246, 0.4)"
        ctx.lineWidth = 1.5
        ctx.stroke()

        // Arrow head
        ctx.beginPath()
        ctx.moveTo(target.x, target.y)
        ctx.lineTo(target.x - 6, target.y - 4)
        ctx.lineTo(target.x - 6, target.y + 4)
        ctx.closePath()
        ctx.fillStyle = "rgba(139, 92, 246, 0.6)"
        ctx.fill()
      }
    }

    // --- Draw nodes ---
    for (const node of nodes) {
      const pos = positions.get(node.id)
      if (!pos) continue

      const color = typeColor(node.task_type)
      const status = node.status || "pending"
      const isActive = status === "running"
      const radius = isActive ? 9 : 7

      // Glow ring for active nodes
      if (isActive) {
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, radius + 8, 0, Math.PI * 2)
        ctx.fillStyle = color + "22"
        ctx.fill()
      }

      // Status ring
      const sc = statusColor(status)
      if (sc !== "transparent") {
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, radius + 2, 0, Math.PI * 2)
        ctx.strokeStyle = sc
        ctx.lineWidth = 2
        ctx.stroke()
      }

      // Node circle
      ctx.beginPath()
      ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2)
      ctx.fillStyle = color
      ctx.fill()

      // Sub-type badge label (above)
      const label = TYPE_LABELS[node.task_type] || node.task_type
      ctx.fillStyle = "#9ca3af"
      ctx.font = "9px JetBrains Mono, monospace"
      ctx.textAlign = "center"
      ctx.fillText(label, pos.x, pos.y - radius - 8)

      // Node name (below)
      ctx.fillStyle = "#e0e0e0"
      ctx.font = "10px JetBrains Mono, monospace"
      ctx.textAlign = "center"
      const displayName = node.name.length > 10 ? node.name.slice(0, 10) + "…" : node.name
      ctx.fillText(displayName, pos.x, pos.y + radius + 14)
    }
  }, [nodes, dims])

  const runningNode = nodes.find((n) => n.status === "running")

  return (
    <div className="relative w-full" style={{ height: `${dims.h}px` }}>
      {nodes.length === 0 ? (
        <div className="absolute inset-0 flex items-center justify-center border border-dashed border-cyber-border rounded-lg">
          <p className="text-cyber-textDim text-sm">创建任务以查看 DAG 编排图</p>
        </div>
      ) : (
        <motion.canvas
          ref={canvasRef}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4 }}
          className="rounded-lg"
        />
      )}
      {/* Live status overlay */}
      {runningNode && (
        <div className="absolute top-2 left-2 px-2 py-1 rounded-md bg-cyber-surface/80 border border-cyber-cyan/40 text-cyber-cyan text-xs flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-cyber-cyan animate-pulse" />
          {runningNode.name}
        </div>
      )}
    </div>
  )
}
