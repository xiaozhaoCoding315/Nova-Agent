import { Check, Copy, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { Button, Modal } from './common'

export function RecoveryCodeModal({ code, onClose }: { code: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard may be unavailable */
    }
  }

  return (
    <Modal open onClose={onClose} title="保存你的恢复码" width="max-w-sm">
      <div className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-[11.5px] leading-relaxed text-warn">
        <ShieldAlert size={14} className="mt-0.5 shrink-0" />
        这是重置密码的唯一凭证，只显示一次。请立即保存到密码管理器。
      </div>
      <div className="mt-3 flex items-center gap-2 rounded-lg border border-edge bg-base px-3 py-3">
        <code className="flex-1 text-center font-mono text-[18px] tracking-[0.18em]">{code}</code>
        <button
          onClick={() => void copy()}
          className="text-dim transition-colors hover:text-ink"
          aria-label="复制恢复码"
        >
          {copied ? <Check size={15} className="text-ok" /> : <Copy size={15} />}
        </button>
      </div>
      <div className="mt-4 flex justify-end">
        <Button variant="primary" size="sm" onClick={onClose}>我已保存</Button>
      </div>
    </Modal>
  )
}
