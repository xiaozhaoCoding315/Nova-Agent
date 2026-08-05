import { useEffect, useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { FileText, Trash2, Upload, Database, Loader } from "lucide-react"
import { useKnowledgeStore } from "../../stores/knowledgeStore"
import UploadDialog from "./UploadDialog"

export default function KnowledgePanel() {
  const { documents, loading, fetchDocs, removeDoc } = useKnowledgeStore()
  const [showUpload, setShowUpload] = useState(false)

  useEffect(() => { fetchDocs() }, [])

  return (
    <div className="flex-1 flex flex-col p-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-cyber-text font-bold text-lg flex items-center gap-2">
          <Database size={18} className="text-cyber-cyan" />
          知识库管理
        </h2>
        <button
          onClick={() => setShowUpload(true)}
          className="flex items-center gap-1 px-3 py-1.5 text-xs text-cyber-cyan border border-cyber-cyan/40 rounded-lg hover:bg-cyber-cyan/10"
        >
          <Upload size={14} /> 上传
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader className="animate-spin text-cyber-cyan" size={24} />
        </div>
      ) : documents.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3">
          <Database size={40} className="text-cyber-textDim opacity-30" />
          <p className="text-cyber-textDim text-sm">暂无文档</p>
          <button onClick={() => setShowUpload(true)}
            className="text-cyber-cyan text-xs underline">立即上传</button>
        </div>
      ) : (
        <div className="space-y-2">
          <AnimatePresence>
            {documents.map((doc) => (
              <motion.div
                key={doc.name}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -20 }}
                className="flex items-center gap-3 p-3 rounded-lg border border-cyber-border bg-cyber-surface/50 hover:border-cyber-cyan/30 group"
              >
                <FileText size={16} className="text-cyber-cyan shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-cyber-text text-sm truncate">{doc.name}</p>
                  <p className="text-cyber-textDim text-xs">{doc.chunks} 个片段</p>
                </div>
                <button
                  onClick={() => removeDoc(doc.name)}
                  className="opacity-0 group-hover:opacity-100 text-cyber-textDim hover:text-cyber-pink transition-all"
                >
                  <Trash2 size={14} />
                </button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}

      {documents.length > 0 && (
        <div className="mt-4 p-3 rounded-lg border border-cyber-border bg-cyber-surface/30">
          <p className="text-cyber-textDim text-xs">
            共 {documents.length} 个文档, {documents.reduce((s, d) => s + d.chunks, 0)} 个片段
          </p>
        </div>
      )}

      <UploadDialog open={showUpload} onClose={() => { setShowUpload(false); fetchDocs() }} />
    </div>
  )
}
