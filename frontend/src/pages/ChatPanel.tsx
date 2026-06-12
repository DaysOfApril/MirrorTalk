import { useState, useRef, useEffect } from "react"
import { Send, Plus, MessageSquare, Bot, User, ChevronDown, ArrowLeft } from "lucide-react"
import { API_BASE } from "@/lib/utils"

interface Message { id: number; role: string; content: string }
interface ConvInfo { id: string; title: string; updated_at: string; last_message: { content: string; role: string } | null }

export default function ChatPanel({ personaId, personaName, onBack }: {
  personaId: string; personaName: string; onBack: () => void
}) {
  const [convId, setConvId] = useState<string | null>(null)
  const [convs, setConvs] = useState<ConvInfo[]>([])
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [showConvList, setShowConvList] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const prevPersonaRef = useRef(personaId)

  // 切换好友时清空状态
  useEffect(() => {
    if (prevPersonaRef.current !== personaId) {
      prevPersonaRef.current = personaId
      setConvId(null)
      setMessages([])
      setConvs([])
      setInput("")
      setShowConvList(false)
    }
  }, [personaId])

  // 加载对话列表
  useEffect(() => {
    if (!personaId) return
    fetch(`${API_BASE}/conversations?persona_id=${personaId}&limit=20`)
      .then(r => r.json()).then(data => {
        const list = data.conversations || []
        setConvs(list)
        if (list.length > 0) setConvId(list[0].id)
      })
  }, [personaId])

  // 加载消息
  useEffect(() => {
    if (!convId) { setMessages([]); return }
    fetch(`${API_BASE}/conversations/${convId}/messages`)
      .then(r => r.json()).then(data => setMessages(data.messages || []))
  }, [convId])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages])

  const refreshConvs = () => {
    fetch(`${API_BASE}/conversations?persona_id=${personaId}&limit=20`)
      .then(r => r.json()).then(data => setConvs(data.conversations || []))
  }

  const send = async () => {
    if (!input.trim() || loading) return
    const userMsg: Message = { id: Date.now(), role: "user", content: input }
    setMessages(prev => [...prev, userMsg])
    setInput("")
    setLoading(true)
    const assistantId = Date.now() + 1
    setMessages(prev => [...prev, { id: assistantId, role: "assistant", content: "" }])

    try {
      const res = await fetch(`${API_BASE}/chat/friend/stream`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona_id: personaId, message: userMsg.content, agent_type: "friend", conversation_id: convId || undefined }),
      })
      const reader = res.body?.getReader(); const decoder = new TextDecoder()
      let full = ""; let newConvId = convId
      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split("\n").filter(Boolean)) {
          if (line.startsWith("data: ")) {
            try {
              const parsed = JSON.parse(line.slice(6))
              if (parsed.type === "end") {
                if (parsed.data?.reply) full = parsed.data.reply
                if (parsed.data?.conversation_id) newConvId = parsed.data.conversation_id
              }
            } catch { full += line.slice(6) }
          }
        }
        setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: full } : m))
      }
      if (newConvId && newConvId !== convId) { setConvId(newConvId); refreshConvs() }
    } catch (e) { console.error("Stream error", e) }
    finally { setLoading(false); refreshConvs() }
  }

  const startNewChat = () => { setConvId(null); setMessages([]); setShowConvList(false) }
  const selectConv = (id: string) => { setConvId(id); setShowConvList(false) }
  const activeConv = convs.find(c => c.id === convId)

  return (
    <div className="h-full flex flex-col max-w-3xl mx-auto">
      {/* 顶部 */}
      <div className="h-14 flex items-center justify-between px-6 border-b border-slate-200 dark:border-slate-700 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400 transition-colors" title="返回画像">
            <ArrowLeft size={18} />
          </button>
          <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0">
            <Bot size={15} className="text-indigo-500" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{personaName}</p>
            {activeConv && <p className="text-[10px] text-slate-400 truncate">{activeConv.title}</p>}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setShowConvList(!showConvList)} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400" title="对话列表">
            <ChevronDown size={16} className={showConvList ? "rotate-180" : ""} />
          </button>
          <button onClick={startNewChat} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-400" title="新对话">
            <Plus size={16} />
          </button>
        </div>
      </div>

      {/* 对话列表下拉 */}
      {showConvList && convs.length > 0 && (
        <div className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 max-h-44 overflow-y-auto">
          <button onClick={startNewChat}
            className="w-full text-left px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors flex items-center gap-2 text-indigo-500 font-medium"
          >
            <Plus size={14} /> 新对话
          </button>
          {convs.map(c => (
            <button key={c.id} onClick={() => selectConv(c.id)}
              className={`w-full text-left px-4 py-2.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors ${c.id === convId ? "bg-indigo-500/5 dark:bg-indigo-400/5" : ""}`}
            >
              <p className="truncate font-medium text-xs">{c.title}</p>
              {c.last_message && <p className="text-[10px] text-slate-400 truncate mt-0.5">{c.last_message.content.slice(0, 50)}</p>}
            </button>
          ))}
        </div>
      )}

      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-16 text-slate-400">
            <MessageSquare size={40} className="mx-auto opacity-30 mb-3" />
            <p className="text-sm">开始与 {personaName} 对话</p>
          </div>
        )}
        {messages.map(m => (
          <div key={m.id} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0">
                <Bot size={15} className="text-indigo-500" />
              </div>
            )}
            <div className={`max-w-[70%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${m.role === "user" ? "bg-indigo-500 dark:bg-indigo-400 text-white" : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200"}`}>
              {m.content || (m.role === "assistant" && loading ? "..." : "")}
            </div>
            {m.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center shrink-0">
                <User size={15} />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* 输入框 */}
      <div className="border-t border-slate-200 dark:border-slate-700 px-6 py-4 shrink-0">
        <div className="flex gap-3">
          <input value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder={`给 ${personaName} 发消息...`}
            className="flex-1 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <button onClick={send} disabled={loading || !input.trim()}
            className="px-4 py-2.5 rounded-xl bg-indigo-500 dark:bg-indigo-400 text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
          ><Send size={18} /></button>
        </div>
      </div>
    </div>
  )
}