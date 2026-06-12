import { useState, useEffect, useRef } from "react"
import { Upload, FileText, Loader2, Check, X, AlertCircle, Users, ArrowRight } from "lucide-react"
import { API_BASE } from "@/lib/utils"

interface TaskStatus {
  id: string
  status: "running" | "done" | "failed" | "cancelled"
  phase: "uploading" | "parsing" | "grouping" | "building" | "done"
  progress_current: number
  progress_total: number
  profiles_created: number
  skipped: number
  error_message?: string
  file_name: string
  result_json?: string
}

export default function DataImport() {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState("")
  const [taskId, setTaskId] = useState<string | null>(null)
  const [task, setTask] = useState<TaskStatus | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState("")
  const sseRef = useRef<AbortController | null>(null)

  useEffect(() => {
    fetch(API_BASE + "/tasks?status=running")
      .then(r => r.json()).then(data => {
        if (data.tasks?.length > 0) {
          const running = data.tasks[0]
          setTaskId(running.id); setTask(running); connectSSE(running.id)
        }
      }).catch(() => {})
  }, [])

  const connectSSE = (tid: string) => {
    sseRef.current?.abort()
    const controller = new AbortController()
    sseRef.current = controller
    fetch(API_BASE + "/tasks/" + tid + "/stream", { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) return
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
                else if (event.type === "done") { setTask(event.task); controller.abort() }
              } catch {}
            }
          }
        }
      }).catch(() => {}).finally(() => setSubmitting(false))
  }

  const handleImport = async () => {
    if (!file || !name.trim() || submitting) return
    setError("")
    setSubmitting(true)
    setTask(null)
    setTaskId(null)

    try {
      const formData = new FormData()
      formData.append("file", file)
      formData.append("name", name.trim())
      formData.append("min_messages", "1")
      const res = await fetch(API_BASE + "/personas/import/file", { method: "POST", body: formData })
      const data = await res.json()
      setTaskId(data.task_id)
      connectSSE(data.task_id)
    } catch {
      setError("导入请求失败，请检查后端是否运行正常")
      setSubmitting(false)
    }
  }

  const progressPct = task?.progress_total
    ? Math.round((task.progress_current / task.progress_total) * 100)
    : 0

  const result = task?.result_json ? (() => { try { return JSON.parse(task.result_json) } catch { return null } })() : null

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <div className="flex items-center gap-3">
        <FileText size={24} className="text-indigo-500" />
        <h1 className="text-xl font-bold">导入聊天记录</h1>
      </div>

      <div>
        <label className="text-sm font-medium mb-2 block">画像名称</label>
        <input type="text" value={name} onChange={e => setName(e.target.value)}
          placeholder="给这次导入取个名字（群聊名 / 好友名）"
          className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
      </div>

      <label className="flex flex-col items-center gap-3 p-10 rounded-2xl border-2 border-dashed border-slate-200 dark:border-slate-700 hover:border-indigo-500/30 transition-colors cursor-pointer">
        <Upload size={32} className="text-slate-500 dark:text-slate-400" />
        <span className="text-sm text-slate-500 dark:text-slate-400">{file ? file.name : "点击上传 JSON 聊天记录"}</span>
        <input type="file" accept=".json,.jsonl" onChange={e => setFile(e.target.files?.[0] || null)} className="hidden" />
      </label>

      <button onClick={handleImport} disabled={submitting || !name.trim() || !file}
        className="w-full py-3 rounded-xl bg-indigo-500 dark:bg-indigo-400 text-white font-medium text-sm disabled:opacity-40 hover:opacity-90 transition-opacity flex items-center justify-center gap-2">
        {submitting ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
        {submitting ? "正在解析..." : "开始解析并拆分"}
      </button>

      {error && (
        <div className="p-4 rounded-xl text-sm flex items-center gap-2 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400">
          <AlertCircle size={16} /><span>{error}</span>
        </div>
      )}

      {task && task.status === "running" && (
        <div className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-slate-600 dark:text-slate-400">
              {task.progress_total === 0 ? (
                <span className="flex items-center gap-2">
                  <Loader2 size={14} className="animate-spin" />
                  正在扫描文件...
                </span>
              ) : (
                "正在解析消息..."
              )}
            </span>
            {task.progress_total > 0 && (
              <span className="text-slate-400 text-xs">{task.progress_current} / {task.progress_total}</span>
            )}
          </div>
          {task.progress_total > 0 ? (
            <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
              <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: progressPct + "%" }} />
            </div>
          ) : (
            <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
              <div className="h-full rounded-full bg-indigo-500 animate-pulse" style={{ width: "30%" }} />
            </div>
          )}
        </div>
      )}

      {result?.success && (
        <div className="p-5 rounded-xl bg-green-50 dark:bg-green-900/30 border border-green-200 dark:border-green-800 space-y-3">
          <div className="flex items-center gap-2 text-green-700 dark:text-green-400 text-sm font-medium">
            <Check size={16} />
            解析完成
          </div>
          <div className="text-xs text-green-600 dark:text-green-400 space-y-1">
            <p>群组：{result.group_name}</p>
            <p>消息总数：{result.total_messages} 条</p>
            <p>发言人：{result.total_senders} 人</p>
          </div>
          {result.senders && (
            <div className="max-h-32 overflow-y-auto space-y-1">
              {result.senders.slice(0, 20).map((s: any) => (
                <div key={s.platform_id} className="flex items-center justify-between text-xs px-2 py-1 rounded bg-green-100/50 dark:bg-green-800/30">
                  <span>{s.name}</span>
                  <span className="text-green-500">{s.count} 条</span>
                </div>
              ))}
            </div>
          )}
          <a href="/personas"
            className="flex items-center justify-center gap-1.5 w-full py-2.5 rounded-xl bg-green-600 text-white text-sm font-medium hover:opacity-90 transition-opacity">
            <Users size={15} />
            前往画像管理构建画像
            <ArrowRight size={15} />
          </a>
        </div>
      )}

      {task?.status === "failed" && (
        <div className="p-4 rounded-xl text-sm flex items-center gap-2 bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400">
          <X size={16} /><span>导入失败：{task.error_message || "未知错误"}</span>
        </div>
      )}
    </div>
  )
}
