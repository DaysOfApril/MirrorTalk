import { useState, useEffect, useRef } from "react"
import { Users, ChevronRight, MessageSquare, Brain, Settings, Loader2, Check, X, AlertCircle, Clock, Eye, EyeOff, Wifi, Database, Trash2, FileText } from "lucide-react"
import { API_BASE } from "@/lib/utils"

// ---- Types ----
interface ChatRecord {
  platform_id: string
  name: string
  message_count: number
  file_size: number
  has_persona: boolean
}

interface PersonaInfo {
  id: string
  name: string
  style: any
  ocean: any
  message_count: number
}

interface ProviderInfo {
  id: string
  name: string
  has_api_key: boolean
  default_base_url: string
  default_model: string
}

interface StreamMsg {
  type: "meta" | "msg" | "error" | "end"
  data?: any
  error?: string
  platform_id?: string
  file?: string
}

type NavTab = "records" | "personas" | "chat"
type MainTab = "messages" | "build"

export default function PersonaManage() {
  const [navTab, setNavTab] = useState<NavTab>("records")
  const [records, setRecords] = useState<ChatRecord[]>([])
  const [selectedPid, setSelectedPid] = useState<string | null>(null)
  const [mainTab, setMainTab] = useState<MainTab>("messages")
  const [messages, setMessages] = useState<any[]>([])
  const [streaming, setStreaming] = useState(false)
  const [personas, setPersonas] = useState<PersonaInfo[]>([])
  const [buildStatus, setBuildStatus] = useState<any>(null)
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [buildBusy, setBuildBusy] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)
  const sseRef = useRef<AbortController | null>(null)
  const msgContainerRef = useRef<HTMLDivElement>(null)

  // ---- Model selection state ----
  const [stage1Provider, setStage1Provider] = useState("qwen")
  const [stage1Model, setStage1Model] = useState("qwen-turbo")
  const [stage2Provider, setStage2Provider] = useState("deepseek")
  const [stage2Model, setStage2Model] = useState("deepseek-chat")
  const [factsProvider, setFactsProvider] = useState("qwen")
  const [factsModel, setFactsModel] = useState("qwen-turbo")
  const [runningStyle, setRunningStyle] = useState(false)
  const [runningFacts, setRunningFacts] = useState(false)
  const [runningDeep, setRunningDeep] = useState(false)

  // ---- Load chat records ----
  useEffect(() => {
    fetch(API_BASE + "/chat-records").then(r => r.json()).then(data => {
      setRecords(data.records || [])
    })
  }, [])

  // ---- Load personas ----
  useEffect(() => {
    fetch(API_BASE + "/personas?page_size=200").then(r => r.json()).then(data => {
      setPersonas((data.items || data || []).map((p: any) => ({
        id: p.id, name: p.name, style: p.style || {},
        ocean: p.ocean || {}, message_count: p.message_count || 0
      })))
    })
  }, [])

  // ---- Load providers ----
  useEffect(() => {
    fetch(API_BASE + "/providers/available").then(r => r.json()).then(data => {
      setProviders(data.providers || [])
      const qwen = (data.providers || []).find((p: any) => p.id === "qwen")
      const ds = (data.providers || []).find((p: any) => p.id === "deepseek")
      if (qwen) { setStage1Provider(qwen.id); setStage1Model(qwen.default_model); setFactsProvider(qwen.id); setFactsModel(qwen.default_model) }
      if (ds) { setStage2Provider(ds.id); setStage2Model(ds.default_model) }
    })
  }, [])

  // ---- Load build status when selecting ----
  useEffect(() => {
    if (!selectedPid) return
    fetch(API_BASE + "/personas/by-platform/" + selectedPid + "/build-status")
      .then(r => r.json()).then(s => {
        setBuildStatus(s)
        // 如果该用户有构建进度，自动切到人物画像标签页
        if (s.style_status !== "not_started" || s.facts_status !== "not_started" || s.deep_status !== "not_started") {
          setMainTab("build")
        }
      })
  }, [selectedPid])

  // ---- Stream messages ----
  const loadMessages = (pid: string) => {
    setSelectedPid(pid)
    setMainTab("messages")
    setMessages([])
    setStreaming(true)
    sseRef.current?.abort()
    const controller = new AbortController()
    sseRef.current = controller

    fetch(API_BASE + "/chat-records/" + pid + "/messages", { signal: controller.signal })
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
                const event = JSON.parse(line.slice(6)) as StreamMsg
                if (event.type === "msg" && event.data) {
                  setMessages(prev => [...prev, event.data])
                } else if (event.type === "end") {
                  setStreaming(false)
                } else if (event.type === "error") {
                  setStreaming(false)
                }
              } catch {}
            }
          }
        }
      }).catch(() => setStreaming(false))
  }

  // ---- Auto scroll messages ----
  useEffect(() => {
    if (msgContainerRef.current) {
      msgContainerRef.current.scrollTop = msgContainerRef.current.scrollHeight
    }
  }, [messages])

  // ---- Run a single build task ----
  const runBuild = async (endpoint: string, body: any, statusKey: string, setRunning: (v: boolean) => void) => {
    if (!selectedPid) return
    setRunning(true)
    // 状态由后端同步写入，前端轮询获取真实状态
    try {
      await fetch(API_BASE + endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      // Poll for completion
      const poll = setInterval(async () => {
        const r = await fetch(API_BASE + "/personas/by-platform/" + selectedPid + "/build-status")
        const s = await r.json()
        setBuildStatus(s)
        if (s[statusKey] === "completed" || s[statusKey]?.startsWith("failed")) {
          clearInterval(poll)
          setRunning(false)
        }
      }, 2000)
    } catch { setRunning(false) }
  }

  const handleSingleBuild = (type: "style" | "facts" | "deep") => {
    if (!selectedPid || runningStyle || runningFacts || runningDeep) return
    const sel = records.find(r => r.platform_id === selectedPid)
    const name = sel?.name || selectedPid
    if (type === "style") {
      runBuild("/personas/by-platform/" + selectedPid + "/build-style",
        { provider: stage1Provider, model: stage1Model, name }, "style_status", setRunningStyle)
    } else if (type === "facts") {
      runBuild("/personas/by-platform/" + selectedPid + "/build-facts",
        { provider: factsProvider, model: factsModel }, "facts_status", setRunningFacts)
    } else if (type === "deep") {
      runBuild("/personas/by-platform/" + selectedPid + "/build-deep",
        { stage1_provider: stage1Provider, stage1_model: stage1Model, stage2_provider: stage2Provider, stage2_model: stage2Model, name }, "deep_status", setRunningDeep)
    }
  }

  // ---- Build persona ----
  const handleBuild = async () => {
    if (!selectedPid || buildBusy) return
    setBuildBusy(true)
    // 立即显示构建中，不等后端第一次响应
    setBuildStatus({platform_id: selectedPid, build_status: "starting", stage1_complete: false, stage2_complete: false, deep_status: "", persona: null})
    const sel = records.find(r => r.platform_id === selectedPid)
    try {
      const res = await fetch(API_BASE + "/personas/by-platform/" + selectedPid + "/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: sel?.name || selectedPid,
          stage1_provider: stage1Provider,
          stage1_model: stage1Model,
          stage2_provider: stage2Provider,
          stage2_model: stage2Model,
        }),
      })
      const data = await res.json()
      if (data.status === "running") {
        // Poll for completion
        const poll = setInterval(async () => {
          const r = await fetch(API_BASE + "/personas/by-platform/" + selectedPid + "/build-status")
          const s = await r.json()
          setBuildStatus(s)
          if (s.stage1_complete && s.stage2_complete) {
            clearInterval(poll)
            setBuildBusy(false)
            // Refresh personas list
            fetch(API_BASE + "/personas?page_size=200").then(r2 => r2.json()).then(d2 => {
              setPersonas((d2.items || d2 || []).map((p: any) => ({
                id: p.id, name: p.name, style: p.style || {},
                ocean: p.ocean || {}, message_count: p.message_count || 0
              })))
            })
          }
        }, 2000)
      }
    } catch {
      setBuildBusy(false)
    }
  }

  // ---- Test connection ----
  const handleTest = async () => {
    setTestResult(null)
    try {
      const res = await fetch(API_BASE + "/config/test-connection", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: stage1Provider, model: stage1Model,
          api_key: "", base_url: "",
        }),
      })
      const data = await res.json()
      if (data.status === "ok") {
        setTestResult("✅ " + data.latency_ms + "ms")
      } else {
        setTestResult("❌ " + (data.error || "连接失败"))
      }
    } catch {
      setTestResult("❌ 请求失败")
    }
  }

  // ---- Delete chat record ----
  const handleDelete = async (pid: string) => {
    if (!window.confirm("确定要删除该聊天记录吗？不会影响已构建的画像。")) return
    await fetch(API_BASE + "/chat-records/" + pid, { method: "DELETE" })
    setRecords(prev => prev.filter(r => r.platform_id !== pid))
    if (selectedPid === pid) setSelectedPid(null)
  }

  // ---- Helpers ----
  const selectedRecord = records.find(r => r.platform_id === selectedPid)
  const hasPersona = (pid: string) => personas.some(p => p.id === pid)
  const [allCollapsed, setAllCollapsed] = useState(false)

  const selectedPersona = personas.find(p => p.id === selectedPid)

  return (
    <div className="flex h-full">
      {/* ===== Col 1: Navigation ===== */}
      <nav className="w-44 shrink-0 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 flex flex-col">
        <div className="h-14 flex items-center px-4 border-b border-slate-200 dark:border-slate-700">
          <span className="text-sm font-semibold text-slate-600 dark:text-slate-300">导航</span>
        </div>
        <div className="flex-1 py-2 space-y-0.5 px-2">
          {[
            { id: "records" as NavTab, label: "导入记录", icon: FileText },
            { id: "personas" as NavTab, label: "画像管理", icon: Users },
            { id: "chat" as NavTab, label: "聊天记录", icon: MessageSquare },
          ].map(n => {
            const Icon = n.icon
            return (
              <button key={n.id} onClick={() => { setNavTab(n.id); if (n.id !== "records") setSelectedPid(null) }}
                className={"w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors " + (
                  navTab === n.id
                    ? "bg-white dark:bg-slate-800 shadow-sm text-indigo-500 dark:text-indigo-400 font-medium"
                    : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                )}>
                <Icon size={15} />
                {n.label}
              </button>
            )
          })}
        </div>
        <div className="p-3 border-t border-slate-200 dark:border-slate-700">
          <button onClick={() => window.location.href = "/import"}
            className="w-full text-xs text-slate-400 hover:text-indigo-500 transition-colors text-center">
            + 导入聊天记录
          </button>
        </div>
      </nav>

      {/* ===== Col 2: User list ===== */}
      <aside className="w-60 shrink-0 border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 flex flex-col">
        <div className="h-14 flex items-center px-4 border-b border-slate-200 dark:border-slate-700">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {navTab === "records" ? "好友列表" : navTab === "personas" ? "已有画像" : "聊天记录管理"}
          </span>
          <span className="ml-2 text-xs text-slate-400">({records.length})</span>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {navTab === "records" && records.map(r => {
            const built = hasPersona(r.platform_id)
            return (
              <div key={r.platform_id} onClick={() => loadMessages(r.platform_id)}
                className={"flex items-center gap-2 px-4 py-2.5 cursor-pointer transition-colors border-l-2 text-sm " +
                  (selectedPid === r.platform_id
                    ? "border-indigo-500 bg-indigo-500/5 text-indigo-600 dark:text-indigo-400"
                    : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700")}>
                <span className={"w-2 h-2 rounded-full shrink-0 " + (built ? "bg-red-500" : "bg-slate-300 dark:bg-slate-600")} />
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium">{r.name}</div>
                  <div className="text-xs text-slate-400">{r.message_count.toLocaleString()} 条</div>
                </div>
                {built && <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 shrink-0">已构建</span>}
              </div>
            )
          })}
          {navTab === "personas" && personas.map(p => (
            <div key={p.id} onClick={() => { setSelectedPid(p.id); setMainTab("build") }}
              className={"flex items-center gap-2 px-4 py-2.5 cursor-pointer transition-colors border-l-2 text-sm " +
                (selectedPid === p.id
                  ? "border-indigo-500 bg-indigo-500/5 text-indigo-600 dark:text-indigo-400"
                  : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700")}>
              <div className="flex-1 min-w-0">
                <div className="truncate font-medium">{p.name}</div>
                <div className="text-xs text-slate-400 truncate">
                  {(p.style?.personality || []).slice(0, 3).join("、") || "无标签"}
                </div>
              </div>
            </div>
          ))}
          {navTab === "chat" && records.filter(r => hasPersona(r.platform_id)).map(r => (
            <div key={r.platform_id} className="flex items-center gap-2 px-4 py-2.5 text-sm">
              <span className="flex-1 truncate">{r.name}</span>
              <button onClick={() => handleDelete(r.platform_id)} className="text-xs text-red-400 hover:text-red-600 shrink-0">
                <Trash2 size={14} />
              </button>
            </div>
          ))}
          {navTab === "records" && records.length === 0 && (
            <div className="text-center py-10 text-xs text-slate-400">
              <MessageSquare size={32} className="mx-auto opacity-30 mb-2" />
              <p>暂无聊天记录</p>
              <p className="mt-1">请先导入聊天记录</p>
            </div>
          )}
        </div>
      </aside>

      {/* ===== Col 3: Main content ===== */}
      <main className="flex-1 flex flex-col bg-white dark:bg-slate-900 overflow-hidden">
        {!selectedPid ? (
          <div className="flex-1 flex items-center justify-center text-slate-400">
            <div className="text-center">
              <MessageSquare size={48} className="mx-auto opacity-30 mb-3" />
              <p>选择一个好友查看聊天记录或构建画像</p>
            </div>
          </div>
        ) : (
          <>
            {/* Tabs */}
            <div className="flex items-center border-b border-slate-200 dark:border-slate-700 px-4 shrink-0">
              <button onClick={() => setMainTab("messages")}
                className={"px-4 py-3 text-sm border-b-2 transition-colors " + (
                  mainTab === "messages"
                    ? "border-indigo-500 text-indigo-600 dark:text-indigo-400 font-medium"
                    : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                )}>
                📄 查看消息内容
              </button>
              <button onClick={() => setMainTab("build")}
                className={"px-4 py-3 text-sm border-b-2 transition-colors " + (
                  mainTab === "build"
                    ? "border-indigo-500 text-indigo-600 dark:text-indigo-400 font-medium"
                    : "border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                )}>
                🧬 人物画像
              </button>
              <div className="flex-1" />
              {selectedRecord && (
                <span className="text-xs text-slate-400 mr-2">{selectedRecord.name} · {selectedRecord.message_count.toLocaleString()} 条</span>
              )}
            </div>

            {/* Content area */}
            <div className="flex-1 overflow-hidden">
              {mainTab === "messages" ? (
                /* ===== 查看消息内容 Tab ===== */
                <div ref={msgContainerRef} className="h-full overflow-y-auto p-4 space-y-2">
                  {streaming && messages.length === 0 && (
                    <div className="text-center py-10 text-sm text-slate-400">
                      <Loader2 size={20} className="animate-spin mx-auto mb-2" />
                      加载中...
                    </div>
                  )}
                  {messages.map((msg, i) => (
                    <div key={i} className="flex items-start gap-2 p-2.5 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors">
                      <span className="text-xs font-medium text-indigo-500 dark:text-indigo-400 shrink-0 w-16 truncate">{msg.sender}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm leading-relaxed">{msg.content}</p>
                        {msg.timestamp && (
                          <p className="text-[10px] text-slate-400 mt-0.5">{msg.timestamp}</p>
                        )}
                      </div>
                    </div>
                  ))}
                  {streaming && messages.length > 0 && (
                    <div className="text-center py-4 text-xs text-slate-400">
                      <Loader2 size={14} className="animate-spin inline mr-1" />
                      加载更多...
                    </div>
                  )}
                  {!streaming && messages.length > 0 && (
                    <div className="text-center py-4 text-xs text-slate-400">
                      共 {messages.length} 条消息
                    </div>
                  )}
                </div>
              ) : (
                /* ===== 人物画像 Tab ===== */
                <div className="h-full overflow-y-auto p-6 space-y-6">
                  {/* Status indicator for all three tasks */}
                  {buildStatus && (
                    <div className="space-y-2 p-4 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
                      <div className="flex items-center gap-2 text-xs">
                        <span className={"w-2 h-2 rounded-full " + (buildStatus.style_status === "completed" ? "bg-green-500" : buildStatus.style_status === "running" ? "bg-yellow-500 animate-pulse" : "bg-slate-300")} />
                        <span className={buildStatus.style_status === "completed" ? "text-green-600 font-medium" : buildStatus.style_status === "running" ? "text-yellow-600" : "text-slate-400"}>风格分析</span>
                        {buildStatus.style_status === "completed" && <Check size={12} className="text-green-500" />}
                        {buildStatus.style_status === "running" && <Loader2 size={12} className="animate-spin text-yellow-500" />}
                        {buildStatus.style_status?.startsWith("failed") && <span className="text-red-500 text-[10px]">失败</span>}
                      </div>
                      <div className="flex items-center gap-2 text-xs">
                        <span className={"w-2 h-2 rounded-full " + (buildStatus.facts_status === "completed" ? "bg-green-500" : buildStatus.facts_status === "running" ? "bg-yellow-500 animate-pulse" : "bg-slate-300")} />
                        <span className={buildStatus.facts_status === "completed" ? "text-green-600 font-medium" : buildStatus.facts_status === "running" ? "text-yellow-600" : "text-slate-400"}>事实提取</span>
                        {buildStatus.facts_status === "completed" && <Check size={12} className="text-green-500" />}
                        {buildStatus.facts_status === "running" && <Loader2 size={12} className="animate-spin text-yellow-500" />}
                        {buildStatus.facts_status?.startsWith("failed") && <span className="text-red-500 text-[10px]">失败</span>}
                      </div>
                      <div className="flex items-center gap-2 text-xs">
                        <span className={"w-2 h-2 rounded-full " + (buildStatus.deep_status === "completed" ? "bg-green-500" : buildStatus.deep_status === "running" ? "bg-yellow-500 animate-pulse" : "bg-slate-300")} />
                        <span className={buildStatus.deep_status === "completed" ? "text-green-600 font-medium" : buildStatus.deep_status === "running" ? "text-yellow-600" : "text-slate-400"}>深度画像</span>
                        {buildStatus.deep_status === "completed" && <Check size={12} className="text-green-500" />}
                        {buildStatus.deep_status === "running" && <Loader2 size={12} className="animate-spin text-yellow-500" />}
                        {buildStatus.deep_status?.startsWith("failed") && <span className="text-red-500 text-[10px]">失败</span>}
                      </div>
                      {buildStatus.persona?.style?.personality?.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-2 border-t border-slate-100 dark:border-slate-700 mt-2">
                          {buildStatus.persona.style.personality.map((t: string, i: number) => (
                            <span key={i} className="px-1.5 py-0.5 rounded-md bg-indigo-50 dark:bg-indigo-900/30 text-indigo-500 dark:text-indigo-400 text-[10px]">{t}</span>
                          ))}
                        </div>
                      )}
                      {buildStatus.deep_status === "completed" && (
                        <button onClick={() => window.open("/deep-profile", "_self")} className="text-[10px] text-indigo-500 hover:underline mt-1">
                          查看深度分析报告 →
                        </button>
                      )}
                    </div>
                  )}

                  {/* Three independent action cards */}
                  <div className="space-y-4">
                    {/* 风格分析 */}
                    <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 space-y-3">
                      <p className="text-xs font-medium">风格分析</p>
                      <p className="text-[10px] text-slate-400">提取说话风格、口头禅、语气等</p>
                      <div className="flex items-center gap-2">
                        <select value={stage1Provider} onChange={e => setStage1Provider(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px]">
                          {providers.filter(p => p.has_api_key).map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                        </select>
                        <input type="text" value={stage1Model} onChange={e => setStage1Model(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px] font-mono" />
                        <button onClick={() => handleSingleBuild("style")} disabled={runningStyle}
                          className="px-3 py-1.5 rounded-lg bg-indigo-500 text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-40">
                          {runningStyle ? <Loader2 size={12} className="animate-spin" /> : "开始"}
                        </button>
                      </div>
                    </div>

                    {/* 事实提取 */}
                    <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 space-y-3">
                      <p className="text-xs font-medium">事实提取</p>
                      <p className="text-[10px] text-slate-400">从聊天记录中提取原子事实（较慢，消息越多越久）</p>
                      <div className="flex items-center gap-2">
                        <select value={factsProvider} onChange={e => setFactsProvider(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px]">
                          {providers.filter(p => p.has_api_key).map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                        </select>
                        <input type="text" value={factsModel} onChange={e => setFactsModel(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px] font-mono" />
                        <button onClick={() => handleSingleBuild("facts")} disabled={runningFacts}
                          className="px-3 py-1.5 rounded-lg bg-indigo-500 text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-40">
                          {runningFacts ? <Loader2 size={12} className="animate-spin" /> : "开始"}
                        </button>
                      </div>
                    </div>

                    {/* 深度画像 */}
                    <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 space-y-3">
                      <p className="text-xs font-medium">深度画像</p>
                      <p className="text-[10px] text-slate-400">两阶段分析：语义清洗(S1) → 深度心理建模(S2)</p>
                      {/* Stage 1 */}
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-400 font-medium w-12 shrink-0">S1</span>
                        <select value={stage1Provider} onChange={e => setStage1Provider(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px]">
                          {providers.filter(p => p.has_api_key).map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                        </select>
                        <input type="text" value={stage1Model} onChange={e => setStage1Model(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px] font-mono" />
                      </div>
                      {/* Stage 2 */}
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-slate-400 font-medium w-12 shrink-0">S2</span>
                        <select value={stage2Provider} onChange={e => setStage2Provider(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px]">
                          {providers.filter(p => p.has_api_key).map(p => (<option key={p.id} value={p.id}>{p.name}</option>))}
                        </select>
                        <input type="text" value={stage2Model} onChange={e => setStage2Model(e.target.value)}
                          className="flex-1 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 py-1.5 text-[11px] font-mono" />
                      </div>
                      <button onClick={() => handleSingleBuild("deep")} disabled={runningDeep}
                        className="w-full px-3 py-1.5 rounded-lg bg-indigo-500 text-white text-[11px] font-medium hover:opacity-90 disabled:opacity-40">
                        {runningDeep ? <Loader2 size={12} className="animate-spin" /> : "开始分析"}
                      </button>
                    </div>

                    {testResult && (
                      <div className={"text-xs p-2.5 rounded-lg " + (testResult.startsWith("✅") ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700")}>
                        {testResult}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  )
}



