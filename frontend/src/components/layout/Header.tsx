export default function Header() {
  return (
    <header className="h-14 border-b border-cyber-border flex items-center justify-between px-6">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg neon-border flex items-center justify-center">
          <span className="text-cyber-cyan font-bold text-sm">N</span>
        </div>
        <h1 className="text-cyber-text font-bold tracking-wider">NOVATECH</h1>
      </div>
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-cyber-cyan glow-pulse" />
        <span className="text-cyber-textDim text-xs">ONLINE</span>
      </div>
    </header>
  )
}
