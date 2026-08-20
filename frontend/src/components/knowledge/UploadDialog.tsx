import { useState, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { X, Upload, FileText, CheckCircle, AlertCircle } from "lucide-react"
import { uploadDocument } from "../../services/api"

interface Props {
  open: boolean
  onClose: () => void
}

export default function UploadDialog({ open, onClose }: Props) {
  const [dragOver, setDragOver] = useState(false)
  const [status, setStatus] = useState<"idle" | "uploading" | "success" | "error">("idle")
  const [result, setResult] = useState<{ chunks_count?: number; entities_count?: number }>({})
  const [errorMsg, setErrorMsg] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (file: File) => {
    setStatus("uploading")
    try {
      const r = await uploadDocument(file)
      setResult(r)
      setStatus("success")
    } catch (e: any) {
      setErrorMsg(e.response?.data?.detail || e.message || "Upload failed")
      setStatus("error")
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="w-[480px] bg-cyber-surface border border-cyber-border rounded-2xl p-6 shadow-2xl"
            initial={{ scale: 0.9, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.9, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-cyber-text font-bold text-lg flex items-center gap-2">
                <Upload size={20} className="text-cyber-cyan" />
                上传技术文档
              </h2>
              <button onClick={onClose} className="text-cyber-textDim hover:text-cyber-text">
                <X size={20} />
              </button>
            </div>

            {status === "idle" && (
              <div
                className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
                  dragOver ? "border-cyber-cyan bg-cyber-cyan/5" : "border-cyber-border hover:border-cyber-purple"
                }`}
                onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => inputRef.current?.click()}
              >
                <FileText size={40} className="mx-auto mb-3 text-cyber-cyan" />
                <p className="text-cyber-text text-sm">拖拽文件到这里,或点击选择</p>
                <p className="text-cyber-textDim text-xs mt-2">
                  文档 .md / .txt,代码 .py / .java / .ts / .go 等,最大 5MB
                </p>
                <input ref={inputRef} type="file"
                  accept=".md,.markdown,.txt,.py,.java,.ts,.tsx,.js,.jsx,.go,.rs,.cpp,.cc,.c,.h,.hpp,.cs,.rb,.php,.kt,.swift,.sql,.sh,.yaml,.yml,.json,.toml"
                  className="hidden"
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f) }} />
              </div>
            )}

            {status === "uploading" && (
              <div className="py-10 text-center">
                <div className="w-10 h-10 border-2 border-cyber-cyan border-t-transparent rounded-full animate-spin mx-auto mb-4" />
                <p className="text-cyber-textDim text-sm">正在处理:切片 → 向量化 → 索引...</p>
                <p className="text-cyber-textDim/60 text-xs mt-1">代码文件按函数/类边界智能分块</p>
              </div>
            )}

            {status === "success" && (
              <div className="py-8 text-center">
                <CheckCircle size={40} className="mx-auto mb-3 text-green-400" />
                <p className="text-cyber-text font-bold">上传成功!</p>
                <p className="text-cyber-textDim text-sm mt-1">
                  生成 {result.chunks_count} 个片段,提取 {result.entities_count} 个技术实体
                </p>
                <button onClick={onClose}
                  className="mt-4 px-6 py-2 bg-cyber-cyan/10 border border-cyber-cyan text-cyber-cyan rounded-lg text-sm hover:bg-cyber-cyan/20">
                  完成
                </button>
              </div>
            )}

            {status === "error" && (
              <div className="py-8 text-center">
                <AlertCircle size={40} className="mx-auto mb-3 text-cyber-pink" />
                <p className="text-cyber-pink font-bold">上传失败</p>
                <p className="text-cyber-textDim text-sm mt-1">{errorMsg}</p>
                <button onClick={() => setStatus("idle")}
                  className="mt-4 px-6 py-2 border border-cyber-border text-cyber-text rounded-lg text-sm hover:bg-cyber-surface">
                  重试
                </button>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
