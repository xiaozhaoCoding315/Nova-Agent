import { useEffect, useRef, useState, useCallback } from "react"
import { motion } from "framer-motion"
import type { GraphNode, GraphEdge } from "../../stores/memoryStore"

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onNodeClick?: (node: GraphNode) => void
}

interface SimNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
}

// Color palette per entity type
const TYPE_COLORS: Record<string, string> = {
  Person: "#00f0f0",
  Organization: "#8b5cf6",
  Technology: "#ff006e",
  Concept: "#fbbf24",
  Location: "#34d399",
  Event: "#f472b6",
  Product: "#60a5fa",
}
const DEFAULT_COLOR = "#9ca3af"

function typeColor(type: string): string {
  return TYPE_COLORS[type] || DEFAULT_COLOR
}

export default function GraphCanvas({ nodes, edges, onNodeClick }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const simNodes = useRef<SimNode[]>([])
  const animRef = useRef<number>(0)
  const dragNode = useRef<SimNode | null>(null)
  const [hovered, setHovered] = useState<SimNode | null>(null)
  const [dims, setDims] = useState({ w: 600, h: 400 })

  // Initialize simulation nodes when data changes
  useEffect(() => {
    const cx = dims.w / 2
    const cy = dims.h / 2
    simNodes.current = nodes.map((n, i) => {
      const angle = (i / nodes.length) * Math.PI * 2
      const r = 80 + Math.random() * 60
      return {
        ...n,
        x: cx + Math.cos(angle) * r,
        y: cy + Math.sin(angle) * r,
        vx: 0,
        vy: 0,
      }
    })
  }, [nodes, dims])

  // Resize observer
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setDims({ w: width, h: height })
      }
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Physics simulation + render loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext("2d")
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    canvas.width = dims.w * dpr
    canvas.height = dims.h * dpr
    ctx.scale(dpr, dpr)

    const edgeMap: Record<string, GraphEdge[]> = {}
    for (const e of edges) {
      if (!edgeMap[e.source]) edgeMap[e.source] = []
      edgeMap[e.source].push(e)
    }

    const tick = () => {
      const sn = simNodes.current
      // Repulsion
      for (let i = 0; i < sn.length; i++) {
        for (let j = i + 1; j < sn.length; j++) {
          const dx = sn[i].x - sn[j].x
          const dy = sn[i].y - sn[j].y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const force = 800 / (dist * dist)
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          sn[i].vx += fx
          sn[i].vy += fy
          sn[j].vx -= fx
          sn[j].vy -= fy
        }
      }
      // Attraction along edges
      for (const e of edges) {
        const s = sn.find((n) => n.id === e.source)
        const t = sn.find((n) => n.id === e.target)
        if (!s || !t) continue
        const dx = t.x - s.x
        const dy = t.y - s.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (dist - 100) * 0.05
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        s.vx += fx
        s.vy += fy
        t.vx -= fx
        t.vy -= fy
      }
      // Center gravity
      const cx = dims.w / 2
      const cy = dims.h / 2
      for (const n of sn) {
        n.vx += (cx - n.x) * 0.001
        n.vy += (cy - n.y) * 0.001
        // Damping
        n.vx *= 0.85
        n.vy *= 0.85
        if (n !== dragNode.current) {
          n.x += n.vx
          n.y += n.vy
        }
      }

      // Draw
      ctx.clearRect(0, 0, dims.w, dims.h)

      // Edges
      for (const e of edges) {
        const s = sn.find((n) => n.id === e.source)
        const t = sn.find((n) => n.id === e.target)
        if (!s || !t) continue
        ctx.beginPath()
        ctx.moveTo(s.x, s.y)
        ctx.lineTo(t.x, t.y)
        ctx.strokeStyle = "rgba(139, 92, 246, 0.25)"
        ctx.lineWidth = 1
        ctx.stroke()
      }

      // Nodes
      for (const n of sn) {
        const color = typeColor(n.type)
        const isHovered = hovered?.id === n.id
        const radius = isHovered ? 10 : 6

        // Glow
        ctx.beginPath()
        ctx.arc(n.x, n.y, radius + 6, 0, Math.PI * 2)
        ctx.fillStyle = color + "22"
        ctx.fill()

        // Core
        ctx.beginPath()
        ctx.arc(n.x, n.y, radius, 0, Math.PI * 2)
        ctx.fillStyle = color
        ctx.fill()

        // Label
        ctx.fillStyle = "#e0e0e0"
        ctx.font = "10px JetBrains Mono, monospace"
        ctx.textAlign = "center"
        ctx.fillText(n.label.slice(0, 16), n.x, n.y + radius + 14)
      }

      animRef.current = requestAnimationFrame(tick)
    }

    animRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(animRef.current)
  }, [nodes, edges, dims, hovered])

  const getNodeAt = useCallback(
    (x: number, y: number): SimNode | null => {
      for (const n of simNodes.current) {
        const dx = x - n.x
        const dy = y - n.y
        if (dx * dx + dy * dy <= 144) return n
      }
      return null
    },
    []
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      if (dragNode.current) {
        dragNode.current.x = x
        dragNode.current.y = y
        dragNode.current.vx = 0
        dragNode.current.vy = 0
      } else {
        setHovered(getNodeAt(x, y))
      }
    },
    [getNodeAt]
  )

  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect()
      if (!rect) return
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      dragNode.current = getNodeAt(x, y)
    },
    [getNodeAt]
  )

  const handleMouseUp = useCallback(() => {
    if (dragNode.current && onNodeClick) {
      onNodeClick(dragNode.current)
    }
    dragNode.current = null
  }, [onNodeClick])

  return (
    <div ref={containerRef} className="relative w-full h-full min-h-[300px]">
      <canvas
        ref={canvasRef}
        style={{ width: dims.w, height: dims.h }}
        className="cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => {
          setHovered(null)
          dragNode.current = null
        }}
      />
      {hovered && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute pointer-events-none px-2 py-1 rounded bg-cyber-surface border border-cyber-border text-xs"
          style={{ left: hovered.x + 14, top: hovered.y - 10 }}
        >
          <span className="text-cyber-cyan">{hovered.label}</span>
          <span className="text-cyber-textDim ml-1">({hovered.type})</span>
        </motion.div>
      )}
      {nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="text-cyber-textDim text-sm">输入实体名称探索知识图谱</p>
        </div>
      )}
    </div>
  )
}
