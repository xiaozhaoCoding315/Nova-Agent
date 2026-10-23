import clsx from 'clsx'
import { ChevronDown, ChevronRight, FileText, FolderClosed, FolderOpen } from 'lucide-react'
import { useState } from 'react'
import type { FileNode } from '../lib/types'

function Node({
  node,
  depth,
  selectedPath,
  onSelect,
}: {
  node: FileNode
  depth: number
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  const [open, setOpen] = useState(depth < 1)

  if (node.type === 'dir') {
    return (
      <div>
        <button
          className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-[12.5px] text-dim hover:bg-raised hover:text-ink"
          style={{ paddingLeft: depth * 12 + 6 }}
          onClick={() => setOpen(!open)}
        >
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {open ? <FolderOpen size={13} className="text-accent" /> : <FolderClosed size={13} className="text-accent/70" />}
          <span className="truncate">{node.name}</span>
        </button>
        {open &&
          node.children.map((child) => (
            <Node key={child.path} node={child} depth={depth + 1} selectedPath={selectedPath} onSelect={onSelect} />
          ))}
      </div>
    )
  }

  return (
    <button
      className={clsx(
        'flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12.5px]',
        selectedPath === node.path ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
      )}
      style={{ paddingLeft: depth * 12 + 20 }}
      onClick={() => onSelect(node.path)}
      title={node.path}
    >
      <FileText size={12} className="shrink-0 text-dim/70" />
      <span className="truncate">{node.name}</span>
    </button>
  )
}

export function FileTree({
  nodes,
  selectedPath,
  onSelect,
}: {
  nodes: FileNode[]
  selectedPath: string | null
  onSelect: (path: string) => void
}) {
  if (nodes.length === 0) {
    return <p className="px-3 py-4 text-[12.5px] text-dim">索引完成后这里会显示文件树。</p>
  }
  return (
    <div className="py-1">
      {nodes.map((node) => (
        <Node key={node.path} node={node} depth={0} selectedPath={selectedPath} onSelect={onSelect} />
      ))}
    </div>
  )
}