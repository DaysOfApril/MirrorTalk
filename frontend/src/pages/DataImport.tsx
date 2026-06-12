import { useState, useEffect, useRef } from "react"
import { Upload, FileText, Loader2, Check, X, AlertCircle, Settings } from "lucide-react"
import { API_BASE } from "@/lib/utils"

type TaskStatus = {
  id: string
  status: "running" | "done" | "failed" | "cancelled"
  phase: "uploading" | "parsing" | "grouping" | "building" | "done"
  progress_current: number
  progress_total: number
  sender_count: number
  profiles_created: number
  skipped: number
  error_message?: string
  file_name: string
}

type ProviderStatus = {
  status: "ok" | "error"
  latency_ms?: number
  error?: string
}

export default function DataImport() {
  const [name, setName] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get("name") || ""
  })
  const [mode, setMode] = useState<"json" | "raw">("json")
  const [rawText, setRawText] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [task, setTask] = useState<TaskStatus | null>(null)
  const [error, setError] = useState("")
  const [hasNewDone, setHasNewDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [checkingProviders, setCheckingProviders] = useState(false)
  const [providerIssues, setProviderIssues] = useState<Record<string, ProviderStatus> | null>(null)
  const sseRef = useRef<AbortController | null>(null)

  const lastViewedKey = "mirrortalk_last_viewed_task"
  const getLastViewed = () => localStorage.getItem(lastViewedKey) || ""

  useEffect(() => {
    fetch(`${API_BASE}/tasks?status=running`)
      .then(r => r.json()).then(data => {
        if (data.tasks?.length > 0) {
          const running = data.tasks[0]
          setTaskId(running.id); setTask(running); connectSSE(running.id)
        }
      }).catch(() => {})
  }, [])

  useEffect(() => { if (taskId) sessionStorage.setItem("mirrortalk_active_task", taskId) }, [taskId])

  const connectSSE = (tid: string) => {
    sseRef.current?.abort()
    const controller = new AbortController()
    sseRef.current = controller
    fetch(`${API_BASE}/tasks/${tid}/stream`, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error("连接失败")
        const reader = res.body?.getReader()
        if (!reader) return
        const decoder = new TextDecoder()
        let buffer = ""
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split("\n"); buffer = lines.pop() || ""
          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const event = JSON.parse(line.slice(6))
                if (event.type === "status" || event.type === "progress") setTask(event.task)
                else if (event.type === "done") {
                  setTask(event.task)
                  if (event.task.id !== getLastViewed() && event.task.status === "done") setHasNewDone(true)
                  controller.abort()
                }
              } catch {}
            }
          }
        }
      }).catch(() => {})
      .finally(() => setSubmitting(false))
  }

  const checkProviders = async (): Promise<boolean> => {
    setCheckingProviders(true)
    setProviderIssues(null)
    try {
      const res = await fetch(`${API_BASE}/check-providers`, { method: "POST" })
      const data = await res.json()
      const providers = data.providers as Record<string, ProviderStatus>
      setProviderIssues(providers)
      setCheckingProviders(false)

      // Allow import if at least one provider is OK (qwen or ollama)
      const okProviders = Object.entries(providers).filter(([_, v]) => v.status === "ok")
      if (okProviders.length === 0) {
        setError("未检测到可用 LLM 服务。请先到设置页配置 Qwen / DeepSeek API Key，或启动本地 Ollama。")
        setSubmitting(false)
        return false
      }
      return true
    } catch {
      setCheckingProviders(false)
      return true // Proceed if check itself fails (network error, etc.)
    }
  }

  const handleImport = async () => {
    setError(""); setHasNewDone(false); setProviderIssues(null)
    setSubmitting(true)

    // Step 1: Check providers first
    const providersOk = await checkProviders()
    if (!providersOk) return

    // Step 2: Proceed with import
    if (mode === "json") {
      if (!file) { setSubmitting(false); return }
      const safeName = name || file.name.replace(/\.(json|jsonl)$/i, "")
      if (!name.trim()) setName(safeName)
      const formData = new FormData()
      formData.append("file", file)
      formData.append("name", safeName)
      formData.append("min_messages", "5")
      try {
        const res = await fetch(`${API_BASE}/personas/import/file`, { method: "POST", body: formData })
        const data = await res.json()
        if (data.task_id) { setTaskId(data.task_id); connectSSE(data.task_id) }
        else { setError("启动导入失败"); setSubmitting(false) }
      } catch { setError("网络错误"); setSubmitting(false) }
    } else {
      if (!rawText.trim() || !name.trim()) { setSubmitting(false); return }
      const lines = rawText.trim().split("\n").filter(Boolean)
      const messages = lines.map(line => {
        const match = line.match(/^(.+?)[:：]\s*(.+)/)
        return match ? { sender: match[1], content: match[2] } : { sender: "unknown", content: line }
      })
      try {
        const res = await fetch(`${API_BASE}/personas/import`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ persona_id: name, name, messages, speaker: name }),
        })
        const data = await res.json()
        if (data.task_id) { setTaskId(data.task_id); connectSSE(data.task_id) }
        else { setError("启动导入失败"); setSubmitting(false) }
      } catch { setError("网络错误"); setSubmitting(false) }
    }
  }

  const dismissRedDot = () => {
    if (task?.id) localStorage.setItem(lastViewedKey, task.id)
    setHasNewDone(false)
  }

  const phaseLabel = (phase: string) => {
    const map: Record<string, string> = {
      uploading: "上传中...", parsing: "正在解析消息...", grouping: "正在分组发言人...",
      building: "正在构建画像...", done: "完成",
    }
    return map[phase] || phase
  }

  const isBusy = submitting || task?.status === "running" || cancelling

  const handleCancel = async () => {
    if (!taskId || cancelling) return
    setCancelling(true)
    try {
      await fetch(`${API_BASE}/tasks/${taskId}/cancel`, { method: "POST" })
    } catch {}
    sseRef.current?.abort()
    setSubmitting(false)
    setCancelling(false)
    setTask(prev => prev ? { ...prev, status: "cancelled" } : null)
  }

  const providerLabels: Record<string, string> = {
    qwen: "通义千问", deepseek: "DeepSeek", ollama: "Ollama（本地）",
  }

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <div className="flex items-center gap-3">
        <FileText size={24} className="text-indigo-500" />
        <h1 className="text-xl font-bold">导入聊天记录</h1>
      </div>

      <div>
        <label className="text-sm font-medium mb-2 block">画像名称</label>
        <input value={name} onChange={e => setName(e.target.value)} disabled={isBusy}
          placeholder='如：微信不是法外之地'
          className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50" />
      </div>

      <div>
        <label className="text-sm font-medium mb-2 block">导入方式</label>
        <div className="flex gap-2">
          {(["json", "raw"] as const).map(m => (
            <button key={m} onClick={() => setMode(m)} disabled={isBusy}
              className={`flex-1 rounded-xl border px-4 py-3 text-sm transition-colors ${mode === m ? "border-indigo-500 dark:border-indigo-400 bg-indigo-500/5 text-indigo-500" : "border-slate-200 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"} disabled:opacity-50`}
            >{m === "json" ? "JSON 文件" : "纯文本粘贴"}</button>
          ))}
        </div>
      </div>

      {!isBusy && mode === "json" && (
        <label className="flex flex-col items-center gap-3 p-10 rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 hover:border-indigo-500/30 transition-colors cursor-pointer">
          <Upload size={32} className="text-slate-500 dark:text-slate-400" />
          <span className="text-sm text-slate-500 dark:text-slate-400">{file ? file.name : "点击上传 JSON 聊天记录"}</span>
          <input type="file" accept=".json,.jsonl" onChange={e => setFile(e.target.files?.[0] || null)} className="hidden" />
        </label>
      )}

      {!isBusy && mode === "raw" && (
        <textarea value={rawText} onChange={e => setRawText(e.target.value)} rows={12}
          placeholder={"粘贴聊天记录，每行一条：\n张三: 今天吃什么？\n李四: 火锅！"}
          className="w-full resize-none rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      )}

      {/* Provider Status */}
      {providerIssues && !isBusy && (
        <div className="space-y-2 p-4 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wider">LLM 服务状态</p>
          {Object.entries(providerIssues).map(([id, status]) => (
            <div key={id} className="flex items-center justify-between text-sm">
              <span>{providerLabels[id] || id}</span>
              {status.status === "ok" ? (
                <span className="flex items-center gap-1 text-green-600 dark:text-green-400">
                  <Check size={14} /> {status.latency_ms}ms
                </span>
              ) : (
                <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400" title={status.error}>
                  <AlertCircle size={14} /> 未配置
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Import Button */}
      {!isBusy && (
        <button onClick={handleImport} disabled={isBusy || !name.trim() || (mode === "json" ? !file : !rawText.trim())}
          className="w-full py-3 rounded-xl bg-indigo-500 dark:bg-indigo-400 text-white font-medium text-sm disabled:opacity-40 hover:opacity-90 transition-opacity flex items-center justify-center gap-2">
          <FileText size={16} />开始导入并构建画像
        </button>
      )}

      {/* Busy / Progress */}
      {isBusy && (
        <div className="space-y-3 p-5 rounded-xl bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2 text-sm">
            <Loader2 size={16} className="animate-spin text-indigo-500" />
            <span className="font-medium">
              {checkingProviders ? "正在检查 LLM 服务..." : task ? phaseLabel(task.phase) : "正在启动..."}
            </span>
            {task && ["parsing", "building"].includes(task.phase) && task.progress_total > 0 && (
              <span className="text-slate-400">({task.progress_current.toLocaleString()} / {task.progress_total.toLocaleString()})</span>
            )}
          </div>
          {task && ["parsing", "building"].includes(task.phase) && task.progress_total > 0 && (
            <div className="w-full h-1.5 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
              <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${Math.min(100, (task.progress_current / task.progress_total) * 100)}%` }} />
            </div>
          )}
          {task?.phase === "grouping" && task.sender_count > 0 && (
            <p className="text-xs text-slate-500">发现 {task.sender_count} 个发言人</p>
          )}
          {task?.phase === "building" && (
            <p className="text-xs text-slate-500">{task.profiles_created}/{task.progress_total} 人已构建{task.skipped > 0 && `（${task.skipped} 人跳过）`}</p>
          )}
          <button onClick={handleCancel} disabled={cancelling}
            className="w-full py-2.5 rounded-xl border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 text-sm font-medium hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors disabled:opacity-40 flex items-center justify-center gap-2">
            <X size={16} />{cancelling ? "正在取消..." : "取消导入"}
          </button>
        </div>
      )}

      {task?.status === "done" && (
        <div className="p-4 rounded-xl text-sm flex items-center gap-2 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400">
          <Check size={16} />
          <span>导入完成！{task.profiles_created} 人画像已构建{task.skipped > 0 && `，${task.skipped} 人跳过（消息不足）`}。</span>
        </div>
      )}

      {task?.status === "cancelled" && (
        <div className="p-4 rounded-xl text-sm flex items-center gap-2 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400">
          <Check size={16} />
          <span>??????</span>
        </div>
      )}

      {task?.status === "cancelled" && (
        <div className="p-4 rounded-xl text-sm flex items-center gap-2 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400">
          <Check size={16} />
          <span>已取消导入。</span>
        </div>
      )}

      {task?.status === "failed" && (
        <div className="p-4 rounded-xl text-sm flex items-center gap-2 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400">
          <X size={16} /><span>导入失败：{task.error_message || "未知错误"}</span>
        </div>
      )}

      {error && !isBusy && (
        <div className="p-4 rounded-xl text-sm flex items-start gap-2 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400">
          <AlertCircle size={16} className="mt-0.5 shrink-0" /><span>{error}</span>
        </div>
      )}

      {error && error.includes("设置页") && !isBusy && (
        <a href="/settings"
          className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-slate-100 dark:bg-slate-800 text-sm font-medium hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors">
          <Settings size={16} />前往设置页配置 LLM
        </a>
      )}
    </div>
  )
}
