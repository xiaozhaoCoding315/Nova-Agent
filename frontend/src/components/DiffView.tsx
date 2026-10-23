import clsx from 'clsx'

export function DiffView({ diff, maxHeight = 'max-h-96' }: { diff: string; maxHeight?: string }) {
  if (!diff.trim()) {
    return <p className="text-[12px] text-dim">没有差异内容。</p>
  }
  return (
    <pre
      className={clsx(
        'overflow-auto rounded-lg border border-edge bg-[#0d1117] p-3 font-mono text-[11.5px] leading-relaxed',
        maxHeight,
      )}
    >
      {diff.split('\n').map((line, i) => (
        <div
          key={i}
          className={clsx(
            line.startsWith('+') && !line.startsWith('+++') && 'text-ok',
            line.startsWith('-') && !line.startsWith('---') && 'text-err',
            line.startsWith('@@') && 'text-accent',
            !line.startsWith('+') && !line.startsWith('-') && !line.startsWith('@@') && 'text-dim',
          )}
        >
          {line || ' '}
        </div>
      ))}
    </pre>
  )
}